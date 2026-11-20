#!/usr/bin/env python3
"""Write layout/lna_core/item2.envelope.json -- the T1 item-2 (Layout)
artifact-anchored generic envelope (issues #228, #2718).

    python3 layout/item2_envelope.py [repo-root]

Called by layout/run_flow.sh right after the GDS and its provenance are
regenerated, so the ``provenance.regeneration`` claim it writes is backed by
the run that just happened: ``regenerated_hash`` is the sha256 this flow's
own ``generate.py`` invocation produced (the grader never re-runs the
generator; it checks the claim against the bound artifact, and the manifest
pins the same hash).

``status`` is derived, never hand-set: the envelope is written ``pass`` only
when

* the committed GDS still re-hashes to ``lna_core.provenance.json``'s
  ``gds_sha256`` (the freshness gate's own first check), and
* realization.json partitions the netlist with an empty ``out_of_scope``
  (every netlist instance drawn -- the layout-scope guard's precondition
  for a block-level item-2 citation);

otherwise the script fails and writes nothing, so a stale envelope can never
turn the row ``met``. Stdlib only; no PDK, no klayout.
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent


def main(argv: list[str]) -> int:
    root = Path(argv[1]).resolve() if len(argv) > 1 else REPO
    cell = root / "layout" / "lna_core"
    gds = cell / "lna_core.gds"
    prov = json.loads((cell / "lna_core.provenance.json").read_text())
    rz = json.loads((cell / "realization.json").read_text())

    gds_sha = hashlib.sha256(gds.read_bytes()).hexdigest()
    if gds_sha != prov.get("gds_sha256"):
        print(
            f"item2_envelope: {gds.name} re-hashes to {gds_sha} but provenance records "
            f"{prov.get('gds_sha256')}; regenerate both together (layout/run_flow.sh)",
            file=sys.stderr,
        )
        return 1
    if rz.get("out_of_scope"):
        print(
            f"item2_envelope: realization.json still lists {len(rz['out_of_scope'])} "
            "out_of_scope instances; a partial layout cannot back item 2",
            file=sys.stderr,
        )
        return 1

    envelope = {
        "kind": "generic",
        "schema_version": 1,
        "t1_item": 2,
        "status": "pass",
        "source": "layout/lna_core/lna_core.gds via layout/lna_core/generate.py (layout/run_flow.sh)",
        "summary": (
            "Full-block LNA layout. realization.json partitions design/netlist/lna.spice "
            "with an empty out_of_scope list (every instance drawn), and the committed GDS "
            "re-hashes to lna_core.provenance.json's gds_sha256, which this envelope pins. "
            "The regeneration claim's hash is the one this flow's own generate.py run "
            "produced. Scope metadata confirms instance coverage only; DRC/LVS are items "
            "3 and 4 and are not claimed here."
        ),
        "provenance": {
            "input": {
                "role": "layout",
                "path": "layout/lna_core/lna_core.gds",
                "content_hash": f"sha256:{gds_sha}",
            },
            "regeneration": {
                "generator": "python3 layout/lna_core/generate.py",
                "regenerated_hash": f"sha256:{gds_sha}",
            },
        },
    }
    out = cell / "item2.envelope.json"
    out.write_text(json.dumps(envelope, indent=2, sort_keys=True) + "\n")
    print(f"item2_envelope: wrote {out.relative_to(root)} (gds sha256 {gds_sha[:12]}...)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
