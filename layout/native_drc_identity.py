#!/usr/bin/env python3
"""Record and validate the provenance binding of a native PDK DRC report
(issue #185).

    python3 -I layout/native_drc_identity.py record <cell_dir> <report.json>
        --gds <gds> --klayout-exe <name> --klayout-exe-resolved <path>
        --klayout-exe-version <str> --min-klayout-version <ver> --pdk <name>
        --klt-version-json <json> --argv <json-list>

    python3 -I layout/native_drc_identity.py validate <cell_dir> --gds <gds>

`record` is called by layout/run_native_drc.py only after the native-deck
run completed (klt exit 0, 3 or 4) and the report was published. It binds
the exact bytes of the report to the committed GDS, to the PDK/deck identity
the report itself records (copied verbatim from its provenance block), and
to the standalone-klayout / klt identity of the invocation, in
<cell_dir>/native_drc_inputs.json. It refuses to bind a report that does not
pin the given GDS bytes. The sidecar is published atomically (tmp + rename).
It only attests identity; it never changes a report's verdict.

`validate` re-checks a committed pair against the GDS: the same contract
.github/scripts/check-layout-freshness enforces for the native pair (the
gate inlines its copy to stay bash + stdlib and read-only). run_native_drc.py
runs it as a publication self-check. Absence of the whole pair is valid —
no native verdict exists in this tree until issue #201 supplies one; a
one-sided pair is not.

Stdlib only: no klayout, klt or PDK. Run tests with
    python3 -I -m unittest discover -s layout/tests -v
"""
import argparse, hashlib, json, os, re, sys
from pathlib import Path

SCHEMA = "sg13g2-lna.native-drc/1"
NAME = "native_drc_inputs.json"
REPORT = "native_drc_report.json"
STATUSES = ("clean", "violations", "coverage_unknown")

_VERSION_RE = re.compile(r"\d+(?:\.\d+)+")


def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def version_tuple(s):
    """First dotted-number run in *s* as a tuple of ints, else None."""
    if not isinstance(s, str):
        return None
    m = _VERSION_RE.search(s)
    return tuple(int(x) for x in m.group(0).split(".")) if m else None


def version_at_least(got, minimum):
    """got >= minimum, padding the shorter tuple with zeros: 0.29 == 0.29.0."""
    a, b = version_tuple(got), version_tuple(minimum)
    if a is None or b is None:
        return False
    n = max(len(a), len(b))
    a += (0,) * (n - len(a))
    b += (0,) * (n - len(b))
    return a >= b


def _report_facts(rep_bytes, gds_sha):
    """(status, deck, pdk) from a published native report, or a refusal str."""
    try:
        rep = json.loads(rep_bytes)
    except ValueError as e:
        return f"published report is not valid JSON ({e})"
    if not isinstance(rep, dict):
        return "published report is not a JSON object"
    status = rep.get("status")
    if status not in STATUSES:
        return (f"report status {status!r} is not one of {list(STATUSES)}; "
                f"refusing to bind it as a completed native run")
    prov = rep.get("provenance")
    if not isinstance(prov, dict):
        return "report has no provenance object"
    inp = prov.get("input")
    if not isinstance(inp, dict):
        return "report provenance has no input object"
    if inp.get("role") != "layout":
        return f"report provenance.input.role is {inp.get('role')!r}, want 'layout'"
    ch = inp.get("content_hash")
    if not isinstance(ch, str) or not ch.startswith("sha256:"):
        return f"report provenance.input.content_hash missing or malformed ({ch!r})"
    if ch[len("sha256:"):] != gds_sha:
        return (f"report pins input {ch[:19]}…, not this GDS "
                f"(sha256:{gds_sha[:12]}…); refusing to bind")
    deck, pdk = prov.get("deck"), prov.get("pdk")
    if not isinstance(deck, dict):
        return "report provenance has no deck object"
    if not isinstance(pdk, dict):
        return "report provenance has no pdk object (--pdk must be given)"
    return status, deck, pdk


def record(cell_dir, report_name, gds, klayout_exe, klayout_exe_resolved,
           klayout_exe_version, min_klayout_version, pdk, klt_version_json,
           argv):
    """Write the binding sidecar for a published native report. Returns the
    sidecar doc; raises ValueError with the refusal reason."""
    cd = Path(cell_dir)
    gds = Path(gds).resolve()
    gds_sha = sha(gds)
    rep_path = cd / report_name
    facts = _report_facts(rep_path.read_bytes(), gds_sha)
    if isinstance(facts, str):
        raise ValueError(f"native_drc_identity: {facts}")
    status, deck, pdk_binding = facts
    try:
        klt = json.loads(klt_version_json)
    except ValueError as e:
        raise ValueError(f"native_drc_identity: --klt-version-json is not "
                         f"valid JSON ({e})") from None
    if not isinstance(klt, dict) or not isinstance(klt.get("version"), str) \
            or not klt["version"]:
        raise ValueError("native_drc_identity: --klt-version-json has no "
                         "version string")
    try:
        argv_list = json.loads(argv)
    except ValueError as e:
        raise ValueError(f"native_drc_identity: --argv is not valid JSON "
                         f"({e})") from None
    if not isinstance(argv_list, list) or not argv_list \
            or any(not isinstance(a, str) for a in argv_list):
        raise ValueError("native_drc_identity: --argv must be a JSON list of "
                         "strings")
    if version_tuple(min_klayout_version) is None:
        raise ValueError(f"native_drc_identity: --min-klayout-version "
                         f"{min_klayout_version!r} is not a dotted version")
    if not version_at_least(klayout_exe_version, min_klayout_version):
        raise ValueError(f"native_drc_identity: detected standalone version "
                         f"{klayout_exe_version!r} is below the required "
                         f"minimum {min_klayout_version!r}")
    root = cd.parent.parent
    doc = {
        "schema": SCHEMA,
        "report": report_name,
        "report_sha256": sha(rep_path),
        "status": status,
        "gds": os.path.relpath(gds, root),
        "gds_sha256": gds_sha,
        "pdk": pdk,
        "deck_binding": deck,
        "pdk_binding": pdk_binding,
        "klayout_exe": klayout_exe,
        "klayout_exe_resolved": str(klayout_exe_resolved),
        "klayout_exe_version": klayout_exe_version,
        "min_klayout_version": min_klayout_version,
        "klt": klt,
        "argv": argv_list,
    }
    tmp = cd / (NAME + ".tmp")
    tmp.write_text(json.dumps(doc, indent=2, sort_keys=True) + "\n")
    os.replace(tmp, cd / NAME)
    return doc


def validate(cell_dir, gds, report_name=REPORT):
    """Check the committed pair in *cell_dir* against *gds*.
    Returns a list of problem strings; empty means consistent (or absent)."""
    cd = Path(cell_dir)
    gds = Path(gds).resolve()
    rep_path, side_path = cd / report_name, cd / NAME
    have_rep, have_side = rep_path.is_file(), side_path.is_file()
    if not have_rep and not have_side:
        return []
    rel = f"{cd.name}/{NAME}"
    if not have_rep:
        return [f"{rel}: {report_name} missing: native report/sidecar pair "
                f"is one-sided"]
    if not have_side:
        return [f"{cd.name}/{report_name}: {NAME} missing: native "
                f"report/sidecar pair is one-sided"]
    problems = []
    try:
        side = json.loads(side_path.read_text())
    except ValueError as e:
        return [f"{rel}: unparseable JSON ({e})"]
    if not isinstance(side, dict) or side.get("schema") != SCHEMA:
        return [f"{rel}: malformed (bad schema)"]
    str_fields = ("report", "report_sha256", "status", "gds", "gds_sha256",
                  "pdk", "klayout_exe", "klayout_exe_resolved",
                  "klayout_exe_version", "min_klayout_version")
    missing = [k for k in str_fields
               if not isinstance(side.get(k), str) or not side[k]]
    if missing:
        return [f"{rel}: missing or malformed field(s): {', '.join(missing)}"]
    for k in ("deck_binding", "pdk_binding"):
        if k not in side:
            return [f"{rel}: missing {k}"]
    if side["report"] != report_name:
        return [f"{rel}: report is {side['report']!r}, want {report_name!r}"]
    klt = side.get("klt")
    if not isinstance(klt, dict) or not isinstance(klt.get("version"), str) \
            or not klt["version"]:
        return [f"{rel}: klt identity missing or malformed"]
    argv = side.get("argv")
    if not isinstance(argv, list) or not argv \
            or any(not isinstance(a, str) for a in argv):
        return [f"{rel}: argv missing or malformed"]

    if sha(rep_path) != side["report_sha256"]:
        problems.append(
            f"{rel}: report changed since this native run (recorded "
            f"{side['report_sha256'][:12]}, now {sha(rep_path)[:12]}); "
            f"rerun layout/run_native_drc.py")
    root = cd.parent.parent
    try:
        want_gds = str(gds.relative_to(root))
    except ValueError:
        want_gds = str(gds)
    if side["gds"] != want_gds:
        problems.append(f"{rel}: gds path {side['gds']!r} != {want_gds!r}")
    elif sha(gds) != side["gds_sha256"]:
        problems.append(
            f"{rel}: GDS changed since this native run (recorded "
            f"{side['gds_sha256'][:12]}, now {sha(gds)[:12]}); rerun "
            f"layout/run_native_drc.py")
    try:
        rep = json.loads(rep_path.read_bytes())
        if not isinstance(rep, dict):
            raise ValueError("not a JSON object")
    except ValueError as e:
        problems.append(f"{cd.name}/{report_name}: unparseable report ({e})")
        return problems
    facts = _report_facts(rep_path.read_bytes(), sha(gds))
    if isinstance(facts, str):
        problems.append(f"{cd.name}/{report_name}: {facts}")
        return problems
    status, deck, pdk_binding = facts
    if side["status"] != status:
        problems.append(f"{rel}: status {side['status']!r} != report "
                        f"status {status!r}")
    if side["deck_binding"] != deck:
        problems.append(f"{rel}: deck_binding differs from the report's "
                        f"provenance.deck; rerun layout/run_native_drc.py")
    if side["pdk_binding"] != pdk_binding:
        problems.append(f"{rel}: pdk_binding differs from the report's "
                        f"provenance.pdk; rerun layout/run_native_drc.py")
    if not version_at_least(side["klayout_exe_version"],
                            side["min_klayout_version"]):
        problems.append(
            f"{rel}: klayout_exe_version "
            f"{side['klayout_exe_version']!r} is below min_klayout_version "
            f"{side['min_klayout_version']!r}")
    return problems


def main(argv):
    parser = argparse.ArgumentParser(
        prog="native_drc_identity.py", description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="cmd", required=True)

    def add_record(p):
        p.add_argument("cell_dir")
        p.add_argument("report")
        p.add_argument("--gds", required=True)
        p.add_argument("--klayout-exe", required=True)
        p.add_argument("--klayout-exe-resolved", required=True)
        p.add_argument("--klayout-exe-version", required=True)
        p.add_argument("--min-klayout-version", required=True)
        p.add_argument("--pdk", required=True)
        p.add_argument("--klt-version-json", required=True)
        p.add_argument("--argv", required=True)

    p_rec = sub.add_parser("record", help="write the binding sidecar")
    add_record(p_rec)
    p_val = sub.add_parser("validate", help="validate a committed pair")
    p_val.add_argument("cell_dir")
    p_val.add_argument("--gds", required=True)
    p_val.add_argument("--report", default=REPORT)
    args = parser.parse_args(argv[1:])
    if args.cmd == "record":
        try:
            doc = record(args.cell_dir, args.report, args.gds, args.klayout_exe,
                         args.klayout_exe_resolved, args.klayout_exe_version,
                         args.min_klayout_version, args.pdk,
                         args.klt_version_json, args.argv)
        except ValueError as e:
            print(str(e), file=sys.stderr)
            return 1
        print(f"native_drc_identity: recorded {doc['report']} "
              f"(status {doc['status']}) in {NAME}")
        return 0
    problems = validate(args.cell_dir, args.gds, args.report)
    if problems:
        print("\n".join(problems), file=sys.stderr)
        print(f"native_drc_identity: FAILED ({len(problems)} problem(s))",
              file=sys.stderr)
        return 1
    print("native_drc_identity: ok (pair consistent or absent)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
