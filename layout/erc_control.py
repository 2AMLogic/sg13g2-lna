#!/usr/bin/env python3
"""Assemble layout/lna_core/erc_control.json -- the negative-control record
for the T1 item-11 `klt erc` supply evidence (issue #35).

    python3 layout/erc_control.py <repo-root> <control-substrate.json> <control-well.json>
    python3 layout/erc_control.py --print-controls

A clean supply verdict is only evidence if the same invocation REJECTS a
stream whose tie is actually severed, so `layout/run_flow.sh` re-runs the
committed spec against two scratch copies of the GDS that
`layout/erc_break.py` broke -- the Cont cut out under the core `ptap1`
substrate strip (the tap no longer reaches the `vss` rail) and under the
bias `ntap1` well tap (no longer reaches `vdd`). This script reads the intact
envelope (`layout/lna_core/erc_report.json`) plus the two control envelopes
the flow just produced, and writes the committed side-by-side record.

What each control breaks, and where, is declared once, in `CONTROLS` below:
run_flow.sh's control loop consumes `--print-controls` (one
`name<TAB>layer<TAB>box` line per control) and hands those values to
`erc_break.py`, so the `break_layer` this record writes is the layer the
flow actually broke (issue #438) -- there is no second, independently
edited literal to drift out of sync.

`status` is derived, never hand-set: the record is written `rejected: true`
only when the committed layout is `erc_status: "clean"` with both tie
declarations in `erc_coverage.checked`, and each control is
`erc_status: "violations"` with an `erc.missing_tie` finding naming that
control's tie and net. Anything else writes `rejected: false` and exits 1 --
a control that leaves the verdict unchanged is a failed control, never a
silent pass. Stdlib only; no PDK, no klayout, no klt.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

GDS_REL = "layout/lna_core/lna_core.gds"
SPEC_REL = "layout/lna_core/erc_spec.json"
INVOCATION = (
    "klt erc layout/lna_core/lna_core.gds layout/lna_core/erc_spec.json "
    "--top lna_core --deck sg13g2 --format json"
)

# One entry per negative control: what the flow breaks, where, and which
# declared tie the ERC run must name when it rejects the broken stream.
# Each break removes the ContAct cuts between tap diffusion and Metal1.
# The tap and rail still overlap, so only a contact-aware tie check can fail.
CONTROLS = [
    {
        "name": "substrate_tie_severed",
        "break": (
            "erc_break.py removes the ContAct cuts (6/0) from the core ptap1 "
            "strip, disconnecting its diffusion from the vss rail"
        ),
        "box": [-59.5, -8.9, 22.5, -7.1],
        "break_layer": "6/0",
        "expected_tie": "substrate_vss",
        "expected_net": "vss",
    },
    {
        "name": "well_tie_severed",
        "break": (
            "erc_break.py removes the ContAct cuts (6/0) from the bias ntap1 "
            "strip, disconnecting its diffusion from the vdd rail"
        ),
        "box": [-1000.5, 141.5, -967.5, 143.2],
        "break_layer": "6/0",
        "expected_tie": "nwell_vdd",
        "expected_net": "vdd",
    },
]


def verdict(env: dict) -> dict:
    """The roll-up half of an ERC envelope, the way the vco's record carries it."""
    findings = env.get("erc_findings") or []
    rules = [f.get("rule") if isinstance(f, dict) else None for f in findings]
    valid_rules = all(isinstance(rule, str) and rule for rule in rules)
    return {
        "erc_status": env.get("erc_status"),
        "finding_count": env.get("erc_finding_count"),
        "rules": sorted(set(rules)) if valid_rules else None,
        "supply_islands": {n.get("name"): n.get("matched_islands") for n in env.get("nets") or []},
        "tie_findings": [
            {"rule": f.get("rule"), "net": f.get("net"), "tie": f.get("layer")}
            for f in findings
            if isinstance(f, dict) and f.get("rule") == "erc.missing_tie"
        ],
    }


def tie_checked(env: dict, tie: str) -> bool:
    """The tie's missing_tie work ran (checked) and was not skipped as degenerate."""
    cov = env.get("erc_coverage") or {}
    work = f'erc.missing_tie:["{tie}"]'
    checked = work in (cov.get("checked") or [])
    skipped = any(s.get("id") == work for s in (cov.get("skipped") or []))
    return checked and not skipped


def print_controls() -> int:
    """Emit one `name<TAB>layer<TAB>box` line per control -- the single
    declaration run_flow.sh's control loop consumes (issue #438), so the
    layer recorded in erc_control.json and the layer handed to erc_break.py
    are the same value."""
    for spec in CONTROLS:
        box = ",".join(str(v) for v in spec["box"])
        print(f"{spec['name']}\t{spec['break_layer']}\t{box}")
    return 0


def main(argv: list[str]) -> int:
    if argv[1:] == ["--print-controls"]:
        return print_controls()
    if len(argv) != 4:
        print(__doc__, file=sys.stderr)
        return 2
    root = Path(argv[1]).resolve()
    cell = root / "layout" / "lna_core"
    intact = json.loads((cell / "erc_report.json").read_text())
    broken = [json.loads(Path(p).read_text()) for p in argv[2:4]]

    intact_v = verdict(intact)
    intact_clean = (
        intact_v["erc_status"] == "clean"
        and intact_v["finding_count"] == 0
        and intact_v["rules"] == []
        and all(tie_checked(intact, c["expected_tie"]) for c in CONTROLS)
    )

    controls = []
    for spec, env in zip(CONTROLS, broken):
        v = verdict(env)
        named = any(
            t.get("tie") == spec["expected_tie"] and t.get("net") == spec["expected_net"]
            for t in v["tie_findings"]
        )
        rejected = v["erc_status"] == "violations" and v["rules"] is not None and named
        controls.append(
            {
                "name": spec["name"],
                "break": spec["break"],
                "break_layer": spec["break_layer"],
                "box": spec["box"],
                "expected": (
                    f"erc_status violations with an erc.missing_tie finding "
                    f"naming tie {spec['expected_tie']} on net {spec['expected_net']}"
                ),
                "verdict": v,
                "rejected": rejected,
            }
        )

    all_rejected = intact_clean and all(c["rejected"] for c in controls)
    record = {
        "schema_version": 1,
        "file": GDS_REL,
        "spec": SPEC_REL,
        "invocation": INVOCATION,
        "committed_layout": intact_v,
        "controls": controls,
        "rejected": all_rejected,
        "evidence": (
            "the supply verdict is VERIFIED: clean on the committed layout with "
            "both tie declarations checked, and rejected (violations, "
            "erc.missing_tie naming the severed tie) on each negative control"
            if all_rejected
            else "FAILED CONTROL: a control did not move the verdict (or the "
            "committed run is not clean), so the clean supply verdict is "
            "indistinguishable from a check that cannot fail -- do not cite "
            "this evidence"
        ),
    }
    (cell / "erc_control.json").write_text(json.dumps(record, indent=2, sort_keys=True) + "\n")
    print(
        f"erc_control: committed={intact_v['erc_status']} "
        + " ".join(f"{c['name']}={c['verdict']['erc_status']}" for c in controls)
        + f" rejected={all_rejected}"
    )
    if not all_rejected:
        print("erc_control: FAILED CONTROL -- see the record just written", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
