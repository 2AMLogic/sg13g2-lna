"""Unit tests for reduce_spec_envelopes.py (issue #364).

Exercises rollup and binding-corner extraction and the --check replay gate
against a small synthetic report fixture (tests/fixtures/
spec-envelope-reports.json, label: synthetic-fixture -- invented numbers,
never circuit evidence) plus a mutation check on a temp copy of the
committed issue-#231 record. Stdlib only, headless, PDK-free, single
process; nothing under sim/ is written: every write lands in a temp dir.

Run from the repo root (single process):

    python3 -I -m unittest discover -s sim/lna-characterization/tests
"""
import csv
import importlib.util
import io
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
LNA = HERE.parent
FIXTURE = HERE / "fixtures" / "spec-envelope-reports.json"
SNAPS = LNA / "netlist-snapshots"
RECORD_ID = "20261117-054141-bdebb4d"  # committed issue-#231 envelope record
REDUCER = LNA / "reduce_spec_envelopes.py"


def load(name):
    spec = importlib.util.spec_from_file_location(name, LNA / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


R = load("reduce_spec_envelopes")


def synth_snapshot(tmp, rec_id="synthetic-env", reports=None):
    """Materialize the synthetic fixture as <tmp>/<rec_id>/reports/*.report.json."""
    data = json.loads(FIXTURE.read_text(encoding="utf-8"))
    if reports is not None:
        data = reports
    snap = Path(tmp) / rec_id
    (snap / "reports").mkdir(parents=True)
    for stem in R.STEMS:
        (snap / "reports" / f"{stem}.report.json").write_text(
            json.dumps(data[stem]), encoding="utf-8")
    return snap


class FormatHelper(unittest.TestCase):
    def test_fmt_is_10_significant_digits_with_empty_for_none(self):
        self.assertEqual(R.fmt(None), "")
        self.assertEqual(R.fmt(0.004), "0.004")
        self.assertEqual(R.fmt(0.0005), "0.0005")
        self.assertEqual(R.fmt(-13.0), "-13")
        self.assertEqual(R.fmt(15.75), "15.75")
        self.assertEqual(R.fmt(-10.25), "-10.25")
        self.assertEqual(R.fmt(1.0000004), "1.0000004")
        self.assertEqual(R.fmt(4e-07), "4e-07")
        self.assertEqual(R.fmt(-2.9), "-2.9")


class SyntheticReduction(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory(prefix="env-reducer-tests-")
        cls.snap = synth_snapshot(cls._tmp.name)
        (cls.rec_id, cls.reports, cls.summary, cls.rollups, cls.rows) = R.reduce_snapshot(cls.snap)

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def test_record_id_comes_from_dir_name(self):
        self.assertEqual(self.rec_id, "synthetic-env")

    def test_summary_echoes_per_envelope_verdicts(self):
        self.assertEqual(self.summary["matched_op"],
                         {"status": "pass", "passed": 2, "failed": 0, "corner_count": 2})
        self.assertEqual(self.summary["matched_sp_stab"],
                         {"status": "fail", "passed": 1, "failed": 1, "corner_count": 2})
        self.assertEqual(self.summary["matched_noise"],
                         {"status": "fail", "passed": 1, "failed": 1, "corner_count": 2})

    def test_rollup_count_and_order_follow_graded(self):
        expected = [(stem, meas) for stem in R.STEMS for (meas, _, _) in R.GRADED[stem]]
        self.assertEqual([(r["stem"], r["measurement"]) for r in self.rollups], expected)
        self.assertEqual(len(self.rollups), 9)

    def test_rollup_extraction_hand_computed(self):
        # ic1: max extreme over the two corners is wcs 0.0042 (limits {"max": 0.0045}).
        self.assertEqual(self.rollups[0], {
            "stem": "matched_op", "row": "ic1", "measurement": "ic1", "unit": "A",
            "limits": '{"max": 0.0045}', "status": "pass",
            "binding_corner": "wcs/1.620V/125C", "worst_value": "0.0042",
            "corner_status": "pass"})
        # s21 grades on the min extreme: worst is wcs 15.75.
        self.assertEqual(self.rollups[2], {
            "stem": "matched_sp_band", "row": "gain", "measurement": "s21_db_min",
            "unit": "dB", "limits": '{"min": 15}', "status": "pass",
            "binding_corner": "wcs/1.620V/125C", "worst_value": "15.75",
            "corner_status": "pass"})
        # s22_mag_max fails its {"max": 1} limit at wcs 1.0000005.
        self.assertEqual(self.rollups[7], {
            "stem": "matched_sp_stab", "row": "negres", "measurement": "s22_mag_max",
            "unit": "1", "limits": '{"max": 1}', "status": "fail",
            "binding_corner": "wcs/1.620V/125C", "worst_value": "1.0000005",
            "corner_status": "fail"})
        # nf has no spec_row in the report (deliberately untagged) -> "" here.
        self.assertEqual(self.rollups[8], {
            "stem": "matched_noise", "row": "nf", "measurement": "nf290_db_worst",
            "unit": "dB", "limits": '{"max": 1.5}', "status": "fail",
            "binding_corner": "wcs/1.620V/125C", "worst_value": "4.4",
            "corner_status": "fail"})

    def test_per_corner_rows_hand_computed(self):
        # 9 graded measurements x 2 corners, grouped per measurement in report
        # corner order.
        self.assertEqual(len(self.rows), 18)
        self.assertEqual(self.rows[0], {
            "analysis": "matched_op", "measurement": "ic1", "spec_row": "ic1",
            "corner_id": "typ/1.800V/27C", "value": "0.004", "unit": "A",
            "status": "pass", "margin": "0.0005"})
        self.assertEqual(self.rows[1], {
            "analysis": "matched_op", "measurement": "ic1", "spec_row": "ic1",
            "corner_id": "wcs/1.620V/125C", "value": "0.0042", "unit": "A",
            "status": "pass", "margin": "0.0003"})
        self.assertEqual(self.rows[16], {
            "analysis": "matched_noise", "measurement": "nf290_db_worst", "spec_row": "",
            "corner_id": "typ/1.800V/27C", "value": "1.25", "unit": "dB",
            "status": "pass", "margin": "0.25"})
        self.assertEqual(self.rows[17], {
            "analysis": "matched_noise", "measurement": "nf290_db_worst", "spec_row": "",
            "corner_id": "wcs/1.620V/125C", "value": "4.4", "unit": "dB",
            "status": "fail", "margin": "-2.9"})

    def test_csv_layout(self):
        text = R.build_csv("synthetic-env", self.rollups, self.rows)
        rows = list(csv.reader(io.StringIO(text)))
        self.assertEqual(rows[0], ["# record", "synthetic-env"])
        self.assertEqual(rows[1], ["analysis", "measurement", "spec_row", "unit", "limits",
                                   "status", "binding_corner", "worst_value"])
        # rollup section: 9 rows, then a blank separator row
        self.assertEqual(rows[2], ["matched_op", "ic1", "", "A", '{"max": 0.0045}',
                                   "pass", "wcs/1.620V/125C", "0.0042"])
        self.assertEqual(rows[10], ["matched_noise", "nf290_db_worst", "", "dB", '{"max": 1.5}',
                                    "fail", "wcs/1.620V/125C", "4.4"])
        self.assertEqual(rows[11], [])
        self.assertEqual(rows[12], ["# per-corner graded measurements"])
        self.assertEqual(rows[13], ["analysis", "measurement", "spec_row", "corner_id",
                                    "value", "unit", "status", "margin"])
        self.assertEqual(rows[14], ["matched_op", "ic1", "ic1", "typ/1.800V/27C",
                                    "0.004", "A", "pass", "0.0005"])
        self.assertEqual(len(rows), 14 + 18)

    def test_md_tables(self):
        md = R.build_md("synthetic-env", self.reports, self.summary, self.rollups)
        self.assertIn("# Issue #231 -- ratified-row `klt sim` envelope verdicts (synthetic-env)", md)
        # run provenance: no "remote" in the synthetic environment -> local backend
        self.assertIn("| `matched_op` | ngspice 47 | ihp-sg13g2 0.3.0 | 0.9.2 | local |", md)
        # per-envelope verdict lines
        self.assertIn("| `matched_op` (DC operating point (op)) | **pass** | 2/2 | 0/2 |", md)
        self.assertIn("| `matched_sp_stab` (Broadband stability (sp, dec 40, 10 MHz-30 GHz)) "
                      "| **fail** | 1/2 | 1/2 |", md)
        # per-row verdict: pass and **fail** both render, with limits and binding corner
        self.assertIn("| `ic1` | `matched_op.ic1` | `{\"max\": 0.0045}` | 0.0042 A "
                      "| `wcs/1.620V/125C` | pass |", md)
        self.assertIn("| `negres` | `matched_sp_stab.s22_mag_max` | `{\"max\": 1}` | 1.0000005 1 "
                      "| `wcs/1.620V/125C` | **fail** |", md)
        self.assertIn("| `nf` | `matched_noise.nf290_db_worst` | `{\"max\": 1.5}` | 4.4 dB "
                      "| `wcs/1.620V/125C` | **fail** |", md)
        # bench-equivalence anchor line pulls the pinned PR #334 worst value
        self.assertIn("| `matched_noise.nf290_db_worst` | 4.3779 dB (wcs/125C/1.98V) "
                      "| 4.4 dB at `wcs/1.620V/125C` |", md)


class EdgePaths(unittest.TestCase):
    def test_null_extreme_and_missing_limits_yield_empty_fields(self):
        data = json.loads(FIXTURE.read_text(encoding="utf-8"))
        nf = data["matched_noise"]["measurements"][0]
        nf["max"] = None
        del nf["limits"]
        with tempfile.TemporaryDirectory(prefix="env-reducer-edge-") as tmp:
            snap = synth_snapshot(tmp, reports=data)
            (_, _, _, rollups, _) = R.reduce_snapshot(snap)
            nf_rollup = rollups[8]
            self.assertEqual(nf_rollup["binding_corner"], "")
            self.assertEqual(nf_rollup["worst_value"], "")
            self.assertEqual(nf_rollup["limits"], "")
            # the per-corner rows are unaffected by a null rollup extreme
            text = R.build_csv("synthetic-env", rollups, R.reduce_snapshot(snap)[4])
            rows = list(csv.reader(io.StringIO(text)))
            self.assertIn(["matched_noise", "nf290_db_worst", "", "typ/1.800V/27C",
                           "1.25", "dB", "pass", "0.25"], rows)


class ReducerMain(unittest.TestCase):
    """End-to-end runs of the script itself (subprocess, temp dirs only)."""

    def run_reducer(self, *args):
        return subprocess.run([sys.executable, "-I", str(REDUCER), *args],
                              capture_output=True, text=True)

    def test_write_mode_then_check_passes_on_synthetic(self):
        with tempfile.TemporaryDirectory(prefix="env-reducer-main-") as tmp:
            snap = synth_snapshot(tmp)
            out = self.run_reducer("--snapshot-dir", str(snap))
            self.assertEqual(out.returncode, 0, out.stderr)
            md = snap / "synthetic-env-envelope-verdict.md"
            csv_path = snap / "synthetic-env-envelope-verdict.csv"
            self.assertTrue(md.is_file() and csv_path.is_file())
            self.assertIn("matched_op: status=pass passed=2/2 failed=0/2", out.stdout)
            chk = self.run_reducer("--snapshot-dir", str(snap), "--check")
            self.assertEqual(chk.returncode, 0, chk.stdout + chk.stderr)
            self.assertIn("OK", chk.stdout)

    def test_check_detects_mutated_committed_copy(self):
        # Mutation check on a TEMP copy of the committed record, never in sim/.
        with tempfile.TemporaryDirectory(prefix="env-reducer-mutation-") as tmp:
            copy = Path(tmp) / RECORD_ID
            shutil.copytree(SNAPS / RECORD_ID, copy)
            ok = self.run_reducer("--snapshot-dir", str(copy), "--check")
            self.assertEqual(ok.returncode, 0, ok.stdout + ok.stderr)
            csv_path = copy / f"{RECORD_ID}-envelope-verdict.csv"
            text = csv_path.read_text(encoding="utf-8")
            needle = "0.00415097376"  # committed ic1 worst value (bcs/1.980V/-40C)
            self.assertIn(needle, text)
            csv_path.write_text(text.replace(needle, "0.00415097377", 1), encoding="utf-8")
            bad = self.run_reducer("--snapshot-dir", str(copy), "--check")
            self.assertEqual(bad.returncode, 1)
            self.assertIn("does not match a fresh reduction", bad.stdout)

    def test_check_detects_missing_verdict_file(self):
        with tempfile.TemporaryDirectory(prefix="env-reducer-missing-") as tmp:
            copy = Path(tmp) / RECORD_ID
            shutil.copytree(SNAPS / RECORD_ID, copy)
            (copy / f"{RECORD_ID}-envelope-verdict.md").unlink()
            bad = self.run_reducer("--snapshot-dir", str(copy), "--check")
            self.assertEqual(bad.returncode, 1)
            self.assertIn("missing", bad.stdout)


if __name__ == "__main__":
    unittest.main()
