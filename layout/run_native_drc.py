#!/usr/bin/env python3
"""Run the IHP SG13G2 *native* DRC deck on the committed partial GDS
(issue #185).

    python3 -I layout/run_native_drc.py --min-klayout-version <x.y.z>
        [--klayout-exe PATH] [--pdk-root DIR] [pass-through options]

This runner consumes layout/lna_core/lna_core.gds exactly as committed — it
never regenerates or edits geometry — and publishes an independent
native-deck verdict beside the curated one, as a pair:

    lna_core/native_drc_report.json   the klt drc --engine klayout envelope
    lna_core/native_drc_inputs.json   binding of those report bytes to the
                                      GDS, PDK/deck identity, the standalone
                                      executable version, the klt identity
                                      and the exact argv (issue #185)

The curated run (layout/run_flow.sh -> klt drc --deck sg13g2) is untouched;
so are its committed reports and the signoff scope guard.

Prerequisites, all explicit:
  - A *standalone* KLayout executable (the application the native deck
    shells out to — not the pip `klayout` module generation.py uses):
    --klayout-exe, else $KLAYOUT_EXE, else `klayout` on PATH. Its `-v`
    output must parse and be >= --min-klayout-version, or the runner
    refuses up front, printing the detected and required versions.
  - --min-klayout-version is a caller-supplied input and has no default on
    purpose: the deck's true minimum is established only on an evidence
    host (issue #201). This repo does not invent one, and installing the
    pip `klayout` module does not update the standalone binary.
  - klt: the pinned PyPI release klayout-tools==0.8.0 run isolated through
    uvx (override with $KLT), the same release layout/run_flow.sh pins.
    The same --min-klayout-version is passed to klt, which re-probes the
    binary it finds on PATH; the runner prepends the preflighted
    executable's directory to PATH so both probes hit the same binary.
  - The IHP PDK install ($PDK_ROOT, or --pdk-root) so klt can resolve the
    native deck for --pdk (default ihp-sg13g2).

Completed-run exit semantics (verified against the klt 0.8.0 release docs):
`klt drc --engine klayout` exits 0 for clean, 3 for violations, and 4 for
coverage_unknown — zero findings without a caller-vouched rule-category
assertion, which is how a genuinely clean layout looks until someone
supplies a reviewed --expect-rule-categories(-file) list. All three are
completed runs and are published verbatim with the report's own status.
Any other klt exit is a failed run: nothing is published.

Exit codes of this runner (each failure class distinguishable):
  0   published a completed run (status clean / violations / coverage_unknown)
  2   usage error (bad arguments, missing committed GDS)
  3   standalone executable not found
  4   `-v` output missing, failed or unparseable
  5   detected version below --min-klayout-version
  6   klt invocation failed, or its report does not pin this GDS;
      raw output is kept in native_drc_report.json.tmp for inspection
  7   post-publication self-check failed (binding inconsistent — a bug;
      the one-sided pair fails the freshness gate loudly on purpose)

On any failure path (3-6) a previously published pair is moved to
native_drc_stale/<utc-timestamp>/ first: a failed rerun must never leave an
old report sitting in place as if it were fresh evidence. Staging uses
native_drc_report.json.tmp (gitignored); the pair itself is published
atomically only after the report has been validated against the GDS hash.
No native verdict exists in this tree until issue #201 runs this on an
evidence host; see layout/README.md for scope and honest-status caveats.
"""
import argparse, hashlib, json, os, re, shlex, shutil, subprocess, sys, time
from pathlib import Path

LAYOUT_DIR = Path(__file__).resolve().parent
REPO_ROOT = LAYOUT_DIR.parent
IDENTITY = LAYOUT_DIR / "native_drc_identity.py"
KLT_RELEASE = "0.8.0"  # keep in sync with layout/run_flow.sh (check-klt-pin.sh)
REPORT_NAME = "native_drc_report.json"
SIDE_NAME = "native_drc_inputs.json"
STAGING = REPORT_NAME + ".tmp"
STATUSES = ("clean", "violations", "coverage_unknown")
COMPLETED_RC = {0, 3, 4}

E_PUBLISHED, E_USAGE, E_NO_EXE, E_BAD_VERSION, E_OLD_VERSION, E_RUN, E_SELFCHECK \
    = 0, 2, 3, 4, 5, 6, 7


def say(msg):
    print(f"run_native_drc: {msg}")


# Version helpers, duplicated from native_drc_identity.py on purpose: `python3
# -I` does not put this script's directory on sys.path, so the runner cannot
# import its sibling. test_native_drc.py pins both copies to the same contract.
_VERSION_RE = re.compile(r"\d+(?:\.\d+)+")


def version_tuple(s):
    if not isinstance(s, str):
        return None
    m = _VERSION_RE.search(s)
    return tuple(int(x) for x in m.group(0).split(".")) if m else None


def version_at_least(got, minimum):
    a, b = version_tuple(got), version_tuple(minimum)
    if a is None or b is None:
        return False
    n = max(len(a), len(b))
    return a + (0,) * (n - len(a)) >= b + (0,) * (n - len(b))


def die(code, msg):
    print(f"run_native_drc: {msg}", file=sys.stderr)
    raise SystemExit(code)


def segregate_old_pair(cd):
    """Move a previously published pair out of the gate's view (kept under
    native_drc_stale/<ts>/), so a failed rerun cannot leave it attested."""
    moved = []
    stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    for name in (REPORT_NAME, SIDE_NAME):
        src = cd / name
        if src.is_file():
            dst_dir = cd / "native_drc_stale" / stamp
            dst_dir.mkdir(parents=True, exist_ok=True)
            os.replace(src, dst_dir / name)
            moved.append(name)
    if moved:
        say(f"segregated previous native evidence ({', '.join(moved)}) "
            f"to {cd / 'native_drc_stale' / stamp}/")


def resolve_exe(candidate):
    """Absolute path to an executable *candidate*, or None."""
    p = Path(candidate).expanduser()
    if p.is_absolute() or len(p.parts) > 1:
        if p.is_file() and os.access(p, os.X_OK):
            return p.resolve()
        return None
    found = shutil.which(candidate)
    return Path(found).resolve() if found else None


def probe_version(exe):
    """Raw first line of `klayout -v`, or a refusal string."""
    try:
        r = subprocess.run([str(exe), "-v"], capture_output=True, text=True,
                           timeout=120)
    except OSError as e:
        return f"could not execute {exe}: {e}"
    except subprocess.TimeoutExpired:
        return f"{exe} -v timed out"
    if r.returncode != 0:
        return (f"{exe} -v exited {r.returncode}: "
                f"{(r.stderr or r.stdout).strip()[:200]!r}")
    line = (r.stdout or "").strip().splitlines()
    if not line:
        return f"{exe} -v produced no output"
    return line[0].strip()


def klt_identity(klt_cmd):
    try:
        r = subprocess.run(klt_cmd + ["version", "--format", "json"],
                           capture_output=True, text=True, timeout=600)
    except subprocess.TimeoutExpired:
        die(E_RUN, "klt version timed out")
    except OSError as e:
        die(E_RUN, f"could not execute klt: {e}")
    if r.returncode != 0:
        die(E_RUN, f"klt version failed (exit {r.returncode}): "
                   f"{(r.stderr or r.stdout).strip()[:200]}")
    try:
        doc = json.loads(r.stdout)
        assert isinstance(doc, dict) and isinstance(doc.get("version"), str)
    except (ValueError, AssertionError):
        die(E_RUN, f"klt version output is not a version document: "
                   f"{r.stdout.strip()[:200]!r}")
    return json.dumps(doc)


def main(argv):
    ap = argparse.ArgumentParser(
        prog="run_native_drc.py",
        description="Run the IHP SG13G2 native DRC deck on the committed "
                    "partial GDS (issue #185).")
    ap.add_argument("--cell-dir", default=str(LAYOUT_DIR / "lna_core"),
                    help="cell directory holding the committed GDS "
                         "(default: layout/lna_core)")
    ap.add_argument("--gds", default=None,
                    help="GDS file name inside --cell-dir "
                         "(default: <cell-dir name>.gds)")
    ap.add_argument("--min-klayout-version", required=True,
                    help="minimum standalone KLayout application version the "
                         "deck needs; caller-supplied, no default (issue #201 "
                         "establishes the deck's true requirement)")
    ap.add_argument("--klayout-exe", default=None,
                    help="standalone KLayout executable (default: "
                         "$KLAYOUT_EXE, else 'klayout' on PATH)")
    ap.add_argument("--pdk", default="ihp-sg13g2",
                    help="PDK variant naming the native deck "
                         "(default: ihp-sg13g2)")
    ap.add_argument("--pdk-root", default=None,
                    help="PDK install root (default: $PDK_ROOT / klt search "
                         "order)")
    ap.add_argument("--expect-rule-categories", type=int, default=None,
                    help="pass through to klt: vouch the deck declares "
                         "exactly N rule categories (turns a zero-finding "
                         "run into a real clean verdict)")
    ap.add_argument("--expect-rule-categories-file", default=None,
                    help="pass through to klt: exact-set category assertion")
    ap.add_argument("--timeout-s", type=int, default=None,
                    help="pass through to klt: wall-clock budget for the "
                         "klayout subprocess")
    args = ap.parse_args(argv[1:])

    if version_tuple(args.min_klayout_version) is None:
        die(E_USAGE, f"--min-klayout-version {args.min_klayout_version!r} is "
                     f"not a dotted version like 0.29.0")
    if args.expect_rule_categories is not None \
            and args.expect_rule_categories_file is not None:
        die(E_USAGE, "--expect-rule-categories and "
                     "--expect-rule-categories-file are mutually exclusive")
    if args.expect_rule_categories is not None \
            and args.expect_rule_categories < 1:
        die(E_USAGE, "--expect-rule-categories must be a positive integer")

    cd = Path(args.cell_dir).resolve()
    gds = cd / (args.gds or f"{cd.name}.gds")
    if not gds.is_file():
        die(E_USAGE, f"committed GDS {gds} missing; this runner consumes the "
                     f"committed GDS and never regenerates geometry")
    (cd / STAGING).unlink(missing_ok=True)  # staging from an earlier crashed
    # run is not evidence; the pair names are the only publication channel

    klt_cmd = shlex.split(os.environ.get(
        "KLT", f"uvx --isolated --from klayout-tools=={KLT_RELEASE} klt"))
    exe_req = args.klayout_exe or os.environ.get("KLAYOUT_EXE") or "klayout"

    # --- preflight: the standalone executable and its version ---
    exe = resolve_exe(exe_req)
    if exe is None:
        segregate_old_pair(cd)
        die(E_NO_EXE, f"standalone KLayout executable not found "
                      f"({exe_req!r}; tried PATH and --klayout-exe/$KLAYOUT_EXE). "
                      f"Note: the pip `klayout` module is not this binary.")
    ver_raw = probe_version(exe)
    if version_tuple(ver_raw) is None:
        segregate_old_pair(cd)
        die(E_BAD_VERSION, f"cannot parse a version from {exe} -v: {ver_raw!r}")
    if not version_at_least(ver_raw, args.min_klayout_version):
        segregate_old_pair(cd)
        die(E_OLD_VERSION, f"standalone KLayout {ver_raw!r} is below the "
                           f"required minimum {args.min_klayout_version!r}; "
                           f"refusing to run the native deck")
    say(f"preflight ok: {exe} reports {ver_raw!r} >= "
        f"{args.min_klayout_version!r}")

    klt_json = klt_identity(klt_cmd)

    # --- run the native deck, staged ---
    klt_argv = klt_cmd + ["drc", "--engine", "klayout", "--pdk", args.pdk]
    if args.pdk_root:
        klt_argv += ["--pdk-root", args.pdk_root]
    klt_argv += [gds.name, "--format", "json",
                 "--min-klayout-version", args.min_klayout_version]
    if args.expect_rule_categories is not None:
        klt_argv += ["--expect-rule-categories",
                     str(args.expect_rule_categories)]
    if args.expect_rule_categories_file:
        klt_argv += ["--expect-rule-categories-file",
                     args.expect_rule_categories_file]
    if args.timeout_s is not None:
        klt_argv += ["--timeout-s", str(args.timeout_s)]

    env = dict(os.environ)
    env["PATH"] = f"{exe.parent}{os.pathsep}{env.get('PATH', '')}"
    out_path = cd / STAGING
    say(f"running: {' '.join(klt_argv)} (cwd {cd})")
    try:
        with open(out_path, "wb") as out:
            rc = subprocess.run(klt_argv, cwd=cd, env=env, stdout=out,
                                stderr=subprocess.PIPE, text=True).returncode
    except OSError as e:
        out_path.unlink(missing_ok=True)
        segregate_old_pair(cd)
        die(E_RUN, f"could not execute klt: {e}")

    if rc not in COMPLETED_RC:
        segregate_old_pair(cd)
        tail = ""
        if out_path.exists():
            tail = out_path.read_text(errors="replace").strip()[-400:]
        die(E_RUN, f"klt drc --engine klayout failed (exit {rc}); raw output "
                   f"kept in {out_path}" + (f": {tail}" if tail else ""))
    if not out_path.exists():
        segregate_old_pair(cd)
        die(E_RUN, f"klt exited {rc} but wrote no report")

    # --- validate the staged report before publishing its binding ---
    gds_sha = hashlib.sha256(gds.read_bytes()).hexdigest()
    try:
        rep = json.loads(out_path.read_bytes())
        ok = isinstance(rep, dict) and rep.get("status") in STATUSES
        inp = (rep.get("provenance") or {}).get("input") if ok else None
        ok = ok and isinstance(inp, dict) \
            and inp.get("role") == "layout" \
            and inp.get("content_hash") == f"sha256:{gds_sha}"
    except ValueError:
        ok = False
    if not ok:
        segregate_old_pair(cd)
        die(E_RUN, f"klt exited {rc} but the report does not pin this GDS "
                   f"(sha256:{gds_sha[:12]}…) or has an unknown status; "
                   f"refusing to publish; raw output kept in {out_path}")

    os.replace(out_path, cd / REPORT_NAME)
    status = rep["status"]
    count = rep.get("violation_count")
    say(f"native run completed (klt exit {rc}): status {status!r}, "
        f"violation_count {count}")

    rec = [sys.executable, "-I", str(IDENTITY), "record", str(cd),
           REPORT_NAME, "--gds", str(gds), "--klayout-exe", exe_req,
           "--klayout-exe-resolved", str(exe),
           "--klayout-exe-version", ver_raw,
           "--min-klayout-version", args.min_klayout_version,
           "--pdk", args.pdk, "--klt-version-json", klt_json,
           "--argv", json.dumps(klt_argv)]
    r = subprocess.run(rec, capture_output=True, text=True)
    if r.returncode != 0:
        # The report is published but unbound: a one-sided pair, which the
        # freshness gate fails loudly (issue #130's property). Do not hide it.
        die(E_SELFCHECK, "binding the published report failed: "
                         f"{(r.stderr or r.stdout).strip()}")
    val = [sys.executable, "-I", str(IDENTITY), "validate", str(cd),
           "--gds", str(gds)]
    r = subprocess.run(val, capture_output=True, text=True)
    if r.returncode != 0:
        die(E_SELFCHECK, "published pair failed its self-check: "
                         f"{(r.stderr or r.stdout).strip()}")
    say(f"published {REPORT_NAME} + {SIDE_NAME} in {cd} "
        f"(status {status!r}; see layout/README.md for scope)")
    return E_PUBLISHED


if __name__ == "__main__":
    sys.exit(main(sys.argv))
