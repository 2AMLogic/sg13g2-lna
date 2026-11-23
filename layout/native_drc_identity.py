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
.github/scripts/check-layout-freshness enforces for the native pair, in one
implementation (native_drc_pair.py beside the gate) loaded by both (issue
#359). run_native_drc.py runs it as a publication self-check. Absence of
the whole pair is valid — no native verdict exists in this tree until
issue #201 supplies one; a one-sided pair is not.

Stdlib only: no klayout, klt or PDK. Run tests with
    python3 -I -m unittest discover -s layout/tests -v
"""
import argparse, hashlib, importlib.util, json, os, sys
from pathlib import Path

LAYOUT_DIR = Path(__file__).resolve().parent
# The native-DRC vocabulary, version helpers and pair check live once, in
# .github/scripts/native_drc_pair.py beside the freshness gate (operator
# ruling, rjwalters 2026-11-17, issue #359). This reverses the
# copy-and-pin arrangement the comment here used to document — STATUSES and
# the version helpers were duplicated into this file and the runner on
# purpose, because `python3 -I` does not put a script's directory on
# sys.path and the gate is bash + stdlib only — and the ruling keeps those
# constraints while dropping the copies: the shared module is loaded by
# explicit path (importlib.util.spec_from_file_location), which works under
# -I and stays stdlib-only, and the gate does not import anything from
# layout/, the directory whose output it judges. test_native_drc.py's sync
# tests, which pinned the three copies equal, are gone with them.
sys.dont_write_bytecode = True
_pair_path = str(LAYOUT_DIR.parent / ".github" / "scripts" / "native_drc_pair.py")
# Register in sys.modules (the documented spec_from_file_location pattern):
# several consumers in one process — the test suite imports the runner and
# this module together — must execute and re-export one module object.
if "native_drc_pair" in sys.modules:
    native_drc_pair = sys.modules["native_drc_pair"]
else:
    _pair_spec = importlib.util.spec_from_file_location("native_drc_pair",
                                                        _pair_path)
    native_drc_pair = importlib.util.module_from_spec(_pair_spec)
    sys.modules["native_drc_pair"] = native_drc_pair
    _pair_spec.loader.exec_module(native_drc_pair)

SCHEMA = native_drc_pair.SCHEMA
NAME = native_drc_pair.SIDE
REPORT = native_drc_pair.REPORT
STATUSES = native_drc_pair.STATUSES
sha = native_drc_pair.sha
version_tuple = native_drc_pair.version_tuple
version_at_least = native_drc_pair.version_at_least


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
    if not (cd / report_name).is_file() and not (cd / NAME).is_file():
        return []
    problems = []
    native_drc_pair.check_pair(cd, cd.parent.parent, cd.name, gds, sha(gds),
                               lambda rel, msg: problems.append(f"{rel}: {msg}"),
                               report_name=report_name, side_name=NAME)
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
