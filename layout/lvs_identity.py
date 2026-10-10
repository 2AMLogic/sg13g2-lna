#!/usr/bin/env python3
"""Record the input identity of an LVS report (issue #130).

    python3 -I layout/lvs_identity.py <cell_dir> <request.json> <report.json>

Called by layout/run_flow.sh only after `klt lvs` ran successfully (exit 0 or
the recorded mismatch exit 3) and the report was published. Binds the exact
bytes of the report to the GDS, the reference netlist and the request that
the invocation used, in <cell_dir>/lvs_inputs.json (one entry per report).

The reference and GDS paths are read from the request itself (resolved the
way klt resolves them, relative to the request's directory); nothing is
inferred from filenames. The sidecar is published atomically (tmp + rename).
It only attests identity; it never changes a report's verdict.
"""
import hashlib, json, os, sys
from pathlib import Path

SCHEMA = "sg13g2-lna.lvs-inputs/1"
NAME = "lvs_inputs.json"


def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def main(argv):
    if len(argv) != 4:
        print(__doc__, file=sys.stderr)
        return 2
    cd = Path(argv[1]).resolve()
    req_name, rep_name = argv[2], argv[3]
    req = cd / req_name
    rep = cd / rep_name
    spec = json.loads(req.read_bytes())
    ref = (req.parent / spec["reference"]["netlist"]).resolve()
    gds = (req.parent / spec["layout"]["file"]).resolve()
    root = cd.parent.parent
    entry = {
        "request": req_name, "request_sha256": sha(req),
        "reference": os.path.relpath(ref, root),
        "reference_sha256": sha(ref),
        "gds": os.path.relpath(gds, root),
        "gds_sha256": sha(gds),
        "report_sha256": sha(rep),
    }
    side = cd / NAME
    doc = {"schema": SCHEMA, "reports": {}}
    if side.is_file():
        try:
            old = json.loads(side.read_text())
        except ValueError:
            old = None
        if (isinstance(old, dict) and old.get("schema") == SCHEMA
                and isinstance(old.get("reports"), dict)):
            doc = old
        else:
            # Not silently: the other report's entry is dropped, so the
            # freshness gate will flag it until that report is regenerated.
            print(f"lvs_identity: warning: existing {NAME} is malformed or "
                  f"not schema {SCHEMA}; starting a fresh sidecar (other "
                  f"reports' entries are dropped)", file=sys.stderr)
    doc["reports"][rep_name] = entry
    tmp = cd / (NAME + ".tmp")
    tmp.write_text(json.dumps(doc, indent=2, sort_keys=True) + "\n")
    os.replace(tmp, side)
    print(f"lvs_identity: recorded {rep_name} in {NAME}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
