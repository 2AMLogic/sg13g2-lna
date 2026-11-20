"""Unit tests for layout/erc_control.py (issue #35).

Pins the negative-control contract: the record is written ``rejected: true``
and exits 0 only when the committed run is clean with both tie declarations
checked and each broken stream flipped to violations with an
``erc.missing_tie`` finding naming that control's tie and net. Every other
shape -- an intact run that is not clean, a control that stayed clean, a
control whose findings name the wrong tie -- writes ``rejected: false`` and
exits 1, so a control that cannot fail can never back the item-11 citation.
Stdlib only: no klt, no klayout, no PDK. Fixtures are minimal stand-in ERC
envelopes in a temp repo root laid out as <root>/layout/lna_core/.

Run from the repo root:
    python3 -I -m unittest discover -s layout/tests -v
"""

from __future__ import annotations

import contextlib
import io
import json
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


if __name__ == "__main__":
    unittest.main()
