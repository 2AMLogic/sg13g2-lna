"""Unit tests for layout/erc_control.py (issues #35, #438).

Pins the negative-control contract: the record is written ``rejected: true``
and exits 0 only when the committed run is clean with both tie declarations
checked and each broken stream flipped to violations with an
``erc.missing_tie`` finding naming that control's tie and net. Every other
shape -- an intact run that is not clean, a control that stayed clean, a
control whose findings name the wrong tie -- writes ``rejected: false`` and
exits 1, so a control that cannot fail can never back the item-11 citation.
Issue #438 adds the single-declaration contract: run_flow.sh must perform
each break with the layer/box ``--print-controls`` emits from CONTROLS, so
the ``break_layer`` in erc_control.json is the layer that was broken, not an
independently edited literal. Stdlib only: no klt, no klayout, no PDK.
Fixtures are minimal stand-in ERC envelopes in a temp repo root laid out as
<root>/layout/lna_core/.

Run from the repo root:
    python3 -I -m unittest discover -s layout/tests -v
"""

from __future__ import annotations

import contextlib
import io
import json
import re
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import erc_control  # noqa: E402


def envelope(status: str, findings: list[dict], checked: list[str]) -> dict:
    return {
        "erc_status": status,
        "erc_finding_count": len(findings),
        "erc_findings": findings,
        "nets": [
            {"name": "vdd", "matched_islands": 1},
            {"name": "vss", "matched_islands": 1},
        ],
        "erc_coverage": {"checked": checked, "skipped": []},
    }


def missing_tie(tie: str, net: str) -> dict:
    return {"rule": "erc.missing_tie", "net": net, "layer": tie}


INTACT = envelope("clean", [], ['erc.missing_tie:["substrate_vss"]', 'erc.missing_tie:["nwell_vdd"]'])
SUBSTRATE_BROKEN = envelope("violations", [missing_tie("substrate_vss", "vss")], [])
WELL_BROKEN = envelope("violations", [missing_tie("nwell_vdd", "vdd")], [])


class ErcControlTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name).resolve()
        self.cd = self.root / "layout" / "lna_core"
        self.cd.mkdir(parents=True)
        self.cd.joinpath("erc_report.json").write_text(json.dumps(INTACT))
        for name, env in (("sub", SUBSTRATE_BROKEN), ("well", WELL_BROKEN)):
            p = self.root / f"control-{name}.json"
            p.write_text(json.dumps(env))
            setattr(self, f"{name}_path", p)

    def run_main(self) -> tuple[int, str]:
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            rc = erc_control.main(
                [
                    "erc_control.py",
                    str(self.root),
                    str(self.sub_path),
                    str(self.well_path),
                ]
            )
        return rc, stdout.getvalue()

    def record(self) -> dict:
        return json.loads((self.cd / "erc_control.json").read_text())

    def test_rejecting_controls_write_rejected_record(self):
        rc, out = self.run_main()
        self.assertEqual(rc, 0)
        rec = self.record()
        self.assertTrue(rec["rejected"])
        self.assertEqual(rec["committed_layout"]["erc_status"], "clean")
        self.assertEqual(len(rec["controls"]), 2)
        for c, tie in zip(rec["controls"], ("substrate_vss", "nwell_vdd")):
            self.assertTrue(c["rejected"])
            self.assertEqual(c["break_layer"], "6/0")
            self.assertEqual(c["verdict"]["tie_findings"][0]["tie"], tie)
        self.assertIn("VERIFIED", rec["evidence"])
        self.assertEqual(rec["file"], "layout/lna_core/lna_core.gds")
        self.assertEqual(rec["spec"], "layout/lna_core/erc_spec.json")
        self.assertIn("--deck sg13g2", rec["invocation"])
        self.assertIn("rejected=True", out)

    def test_record_is_deterministic(self):
        self.run_main()
        first = (self.cd / "erc_control.json").read_bytes()
        self.run_main()
        self.assertEqual(first, (self.cd / "erc_control.json").read_bytes())

    def test_control_that_stays_clean_fails(self):
        self.sub_path.write_text(json.dumps(INTACT))
        rc, _ = self.run_main()
        self.assertEqual(rc, 1)
        rec = self.record()
        self.assertFalse(rec["rejected"])
        self.assertFalse(rec["controls"][0]["rejected"])
        self.assertIn("FAILED CONTROL", rec["evidence"])

    def test_control_naming_the_wrong_tie_fails(self):
        wrong = envelope("violations", [missing_tie("nwell_vdd", "vss")], [])
        self.sub_path.write_text(json.dumps(wrong))
        rc, _ = self.run_main()
        self.assertEqual(rc, 1)
        self.assertFalse(self.record()["rejected"])

    def test_control_violating_without_missing_tie_fails(self):
        other = envelope(
            "violations",
            [{"rule": "erc.unconnected_net", "net": "vss", "layer": None}],
            [],
        )
        self.well_path.write_text(json.dumps(other))
        rc, _ = self.run_main()
        self.assertEqual(rc, 1)
        self.assertFalse(self.record()["rejected"])

    def test_finding_without_rule_fails_even_with_expected_tie(self):
        findings = [missing_tie("nwell_vdd", "vdd"), {"net": "vdd"}]
        self.well_path.write_text(json.dumps(envelope("violations", findings, [])))
        rc, _ = self.run_main()
        self.assertEqual(rc, 1)
        self.assertFalse(self.record()["controls"][1]["rejected"])

    def test_intact_run_not_clean_fails(self):
        self.cd.joinpath("erc_report.json").write_text(
            json.dumps(envelope("violations", [missing_tie("substrate_vss", "vss")], []))
        )
        rc, _ = self.run_main()
        self.assertEqual(rc, 1)
        self.assertFalse(self.record()["rejected"])

    def test_intact_run_with_degenerate_tie_fails(self):
        degenerate = json.loads(json.dumps(INTACT))
        degenerate["erc_coverage"]["checked"] = ['erc.missing_tie:["nwell_vdd"]']
        degenerate["erc_coverage"]["skipped"] = [
            {"id": 'erc.missing_tie:["substrate_vss"]', "reason": "degenerate_tap_declaration"}
        ]
        self.cd.joinpath("erc_report.json").write_text(json.dumps(degenerate))
        rc, _ = self.run_main()
        self.assertEqual(rc, 1)
        self.assertFalse(self.record()["rejected"])

    def test_bad_argument_count_is_usage_error(self):
        self.assertEqual(erc_control.main(["erc_control.py"]), 2)


FLOW = Path(__file__).resolve().parent.parent / "run_flow.sh"


def erc_break_call(text: str) -> str:
    """run_flow.sh's erc_break.py invocation as one logical line."""
    joined = re.sub(r"\\\n\s*", " ", text)
    lines = [ln for ln in joined.splitlines() if "erc_break.py\"" in ln]
    return lines[0] if lines else ""


def flow_wiring_errors(text: str) -> list[str]:
    """Why run_flow.sh's control wiring could let the performed break drift
    from the recorded one (issue #438). The flow must source each control's
    name/layer/box from erc_control.py's CONTROLS via --print-controls and
    hand the loop's variables to erc_break.py -- any literal re-declaration
    is a second source of truth for the break layer."""
    errors = []
    if "--print-controls" not in text:
        errors.append("controls not sourced from erc_control.py --print-controls")
    call = erc_break_call(text)
    if not call:
        errors.append("no erc_break.py invocation")
        return errors
    if '"${layer}"' not in call:
        errors.append("erc_break.py layer is not the loop's ${layer}")
    if '"${box}"' not in call:
        errors.append("erc_break.py box is not the loop's ${box}")
    literal = re.search(r"\d+/\d+", call)
    if literal:
        errors.append(f"erc_break.py re-declares layer {literal.group()!r}")
    return errors


class PrintControlsTest(unittest.TestCase):
    """--print-controls is what run_flow.sh consumes, so its lines must
    carry exactly what CONTROLS declares, in the form erc_break.py parses."""

    def test_emits_name_layer_box_per_control(self):
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            rc = erc_control.main(["erc_control.py", "--print-controls"])
        self.assertEqual(rc, 0)
        lines = stdout.getvalue().splitlines()
        self.assertEqual(len(lines), len(erc_control.CONTROLS))
        for line, spec in zip(lines, erc_control.CONTROLS):
            name, layer, box = line.split("\t")
            self.assertEqual(name, spec["name"])
            self.assertEqual(layer, spec["break_layer"])
            values = box.split(",")
            self.assertEqual(len(values), 4)
            for got, want in zip(values, spec["box"]):
                self.assertEqual(float(got), want)

    def test_unknown_single_argument_is_usage_error(self):
        self.assertEqual(erc_control.main(["erc_control.py", "--print-boxes"]), 2)


class RunFlowWiringTest(unittest.TestCase):
    """The layer erc_break.py performs must come from erc_control.py's
    CONTROLS (via --print-controls), so the break_layer written into
    erc_control.json cannot drift from the break that was performed."""

    def setUp(self):
        self.flow = FLOW.read_text()

    def test_flow_sources_break_from_controls(self):
        self.assertEqual(flow_wiring_errors(self.flow), [])

    def test_redeclared_performed_layer_fails(self):
        # reintroduce the pre-#438 drift: the flow breaks diffusion on 1/0
        # while CONTROLS -- what erc_control.json records -- says 6/0
        drifted = self.flow.replace('"${layer}"', "1/0")
        self.assertNotEqual(drifted, self.flow)
        self.assertTrue(flow_wiring_errors(drifted))

    def test_flow_without_print_controls_fails(self):
        drifted = self.flow.replace(" --print-controls", "")
        self.assertNotEqual(drifted, self.flow)
        self.assertTrue(flow_wiring_errors(drifted))

    def test_redeclared_performed_box_fails(self):
        drifted = self.flow.replace('"${box}"', '"-59.5,-8.9,22.5,-7.1"')
        self.assertNotEqual(drifted, self.flow)
        self.assertTrue(flow_wiring_errors(drifted))


if __name__ == "__main__":
    unittest.main()
