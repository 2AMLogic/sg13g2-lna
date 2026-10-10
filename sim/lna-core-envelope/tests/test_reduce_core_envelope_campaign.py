"""Offline tests for reduce_core_envelope_campaign.py.

All report data comes from tests/synthetic_reports.py: INVENTED numbers, labeled
synthetic, never evidence.
"""
import contextlib
import csv
import importlib.util
import io
import json
import math
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
EXP = HERE.parent
sys.path.insert(0, str(HERE))
import synthetic_reports as syn  # noqa: E402

_spec = importlib.util.spec_from_file_location("reduce_cec", EXP / "reduce_core_envelope_campaign.py")
R = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(R)
C = R.CAMP


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.snap = C.generate("t", "campaign", self.root)
        self.cd = self.root / "corners"
        self.out = self.root / "out"

    def tearDown(self):
        self.tmp.cleanup()

    def build(self, override=None, **kw):
        syn.write_reports(self.snap, self.cd, override=override, **kw)

    def reduce(self, **kw):
        err = io.StringIO()
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(err):
            rc = R.run(self.snap, self.cd, self.out, **kw)
        self.err = err.getvalue()
        return rc

    def summary(self):
        return json.loads((self.out / "t-summary.json").read_text())

    def cells(self):
        with open(self.out / "t-cells.csv") as f:
            return list(csv.DictReader(f))


class BiasClassification(unittest.TestCase):
    def op(self, **kw):
        d = {"ic1": 3.5e-3, "ic2": 3.5e-3, "vbe1": 0.77, "vbe2": 0.77, "vbc1": -0.1, "vbc2": -0.1,
             "vce1": 0.87, "vce2": 0.87}
        d.update(kw)
        return d

    def test_forward_active(self):
        c = R.classify_bias(self.op())
        self.assertEqual((c["class"], c["valid"]), ("forward_active", True))

    def test_each_failure_class(self):
        cases = {
            "marginal": dict(vbc2=0.4),
            "saturated": dict(vbc1=0.65, vce1=0.1),
            "cutoff": dict(ic2=0.0),
            "reverse": dict(vce2=-0.1),
            "nonfinite": dict(vbe1=float("nan")),
        }
        for want, kw in cases.items():
            c = R.classify_bias(self.op(**kw))
            self.assertEqual(c["class"], want, kw)
            self.assertFalse(c["valid"])

    def test_either_hbt_decides(self):
        self.assertEqual(R.classify_bias(self.op(vbc2=0.7))["class2"], "saturated")
        self.assertEqual(R.classify_bias(self.op(vbc2=0.7))["class1"], "forward_active")

    def test_missing_and_model_box_flag(self):
        self.assertEqual(R.classify_bias({})["class"], "missing")
        self.assertEqual(R.classify_bias(self.op(vce1=0.3))["vce_box_flag"], "vce1")
        self.assertEqual(R.classify_bias(self.op())["vce_box_flag"], "")


class CompleteCampaign(Base):
    def test_complete_synthetic_reduces_and_is_stamped(self):
        self.build()
        self.assertEqual(self.reduce(client_version="klt 0.7.0"), 0, self.err)
        s = self.summary()
        self.assertTrue(s["complete"])
        self.assertTrue(s["synthetic_fixture"])
        md = (self.out / "t-summary.md").read_text()
        self.assertIn("SYNTHETIC FIXTURE OUTPUT -- NOT EVIDENCE", md)
        g = s["cases"]["grid__s_fixi_a80__ideal"]
        self.assertEqual(g["n_expected"], 45)
        self.assertEqual(g["n_nf290_pass"], 45)
        self.assertIn("45/45", g["claim"])
        self.assertEqual(g["emitter_units"], 80)
        self.assertEqual(s["cases"]["grid__s_ctrl_a8__ideal"]["emitter_units"], 8)
        self.assertAlmostEqual(g["emitter_area_um2"], 80 * 0.1152)
        self.assertEqual(len(self.cells()), 2 * 5 * 45 + 2 * 7 * 3)

    def test_measured_columns(self):
        self.build()
        self.reduce()
        row = next(r for r in self.cells() if r["case"] == "grid__s_ctrl_a8__ideal"
                   and r["corner_label"] == "typ" and r["temp_c"] == "27" and r["vdd_v"] == "1.8")
        want = 10 * math.log10(1 + (10 ** 0.1 - 1) * (27 + 273.15) / 290.0)
        self.assertAlmostEqual(float(row["nfmin290_db_worst"]), want, places=6)
        self.assertAlmostEqual(float(row["nf290_db_worst"]), 1.2)           # distinct quantity
        self.assertNotAlmostEqual(float(row["nf290_db_worst"]), float(row["nfmin290_db_worst"]), places=2)
        self.assertAlmostEqual(float(row["pdc_mw"]), 7.0)
        self.assertAlmostEqual(float(row["nf_margin_db"]), 0.3)
        self.assertAlmostEqual(float(row["gain_margin_db"]), 1.0)
        self.assertAlmostEqual(float(row["pdc_margin_mw"]), 3.0)
        self.assertEqual(row["bias_class"], "forward_active")

    def test_nf_failures_counted_and_hot_gap(self):
        def ov(stem, case, an, cell, vals):
            if an == "noise" and case == "grid__s_fixi_a80__ideal" and cell[1] == 125:
                vals["nf290_db_worst"] = 1.62 if cell[0] == "wcs" else 1.3
                for i in range(11):
                    vals[f"nf290_db_f{i:02d}"] = vals["nf290_db_worst"] if i == 0 else 1.0
        self.build(override=ov)
        self.assertEqual(self.reduce(), 0)
        g = self.summary()["cases"]["grid__s_fixi_a80__ideal"]
        self.assertEqual(g["n_nf290_pass"], 45 - 3)  # wcs at 125 C, three supplies
        self.assertAlmostEqual(g["worst_hot_gap_nf290_db"], 0.12)
        self.assertEqual(g["worst_hot_gap_nf290_cell"], "wcs/125C/1.62V")
        self.assertAlmostEqual(g["worst_nf290_db_worst"], 1.62)
        self.assertEqual(g["hot_cells_expected"], 15)
        self.assertEqual(g["hot_cells_counted_nf290"], 15)
        self.assertEqual(g["hot_cells_counted_nfmin290"], 15)
        self.assertNotIn("worst_hot_gap_db", g)  # ambiguous unqualified name is gone

    def test_hot_gap_uses_all_15_hot_cells_not_the_3_split_cells(self):
        # Only sf/125/1.98 fails, and it is NOT one of the 3 divider-sweep cells.
        self.assertNotIn(("sf", 125, 1.98), [tuple(c) for c in C.HOT_CELLS])

        def ov(stem, case, an, cell, vals):
            if case != "grid__s_fixi_a80__ideal" or tuple(cell) != ("sf", 125, 1.98):
                return
            if an == "noise":
                vals["nf290_db_worst"] = 1.71
                vals["nf290_db_f00"] = 1.71
        self.build(override=ov)
        self.assertEqual(self.reduce(), 0, self.err)
        g = self.summary()["cases"]["grid__s_fixi_a80__ideal"]
        self.assertEqual(g["n_nf290_pass"], 44)
        self.assertAlmostEqual(g["worst_hot_gap_nf290_db"], 0.21)
        self.assertEqual(g["worst_hot_gap_nf290_cell"], "sf/125C/1.98V")
        self.assertEqual(g["hot_cells_counted_nf290"], 15)
        md = (self.out / "t-summary.md").read_text()
        self.assertIn("sf/125C/1.98V", md)
        self.assertIn("15/15 hot cells counted", md)

    def test_hot_gap_nfmin290_reported_separately(self):
        # NFmin worst hot cell (wcs/125/1.98, not a split cell) differs from the
        # 50 Ohm-source NF worst hot cell (fs/125/1.62): the two are not conflated.
        def ov(stem, case, an, cell, vals):
            if case != "grid__s_fixi_a80__ideal":
                return
            if an == "sp_band" and tuple(cell) == ("wcs", 125, 1.98):
                vals["nfmin_sp_db_worst"] = 1.9
            if an == "noise" and tuple(cell) == ("fs", 125, 1.62):
                vals["nf290_db_worst"] = 1.6
                vals["nf290_db_f00"] = 1.6
        self.build(override=ov)
        self.assertEqual(self.reduce(), 0, self.err)
        g = self.summary()["cases"]["grid__s_fixi_a80__ideal"]
        self.assertEqual(g["worst_hot_gap_nf290_cell"], "fs/125C/1.62V")
        self.assertAlmostEqual(g["worst_hot_gap_nf290_db"], 0.1)
        self.assertEqual(g["worst_hot_gap_nfmin290_cell"], "wcs/125C/1.98V")
        want = R.nf_reref(1.9, 125 + 273.15, 290.0) - 1.5
        self.assertAlmostEqual(g["worst_hot_gap_nfmin290_db"], want)

    def test_hot_gap_excludes_invalid_bias_and_reports_count(self):
        def ov(stem, case, an, cell, vals):
            if case == "grid__s_fixi_a80__ideal" and tuple(cell) == ("sf", 125, 1.62):
                if an == "op":
                    vals.update(ic2=0.0)
                if an == "noise":
                    vals["nf290_db_worst"] = 2.5
                    vals["nf290_db_f00"] = 2.5
        self.build(override=ov)
        self.assertEqual(self.reduce(), 0, self.err)
        g = self.summary()["cases"]["grid__s_fixi_a80__ideal"]
        self.assertEqual(g["hot_cells_counted_nf290"], 14)
        self.assertEqual(g["hot_cells_expected"], 15)
        self.assertNotEqual(g["worst_hot_gap_nf290_cell"], "sf/125C/1.62V")

    def test_split_dnf_against_same_cell_baseline(self):
        def ov(stem, case, an, cell, vals):
            if an == "noise" and case.startswith("split__s_fixi_a80__dp2"):
                vals["nf290_db_worst"] = 1.25
                vals["nf290_db_f00"] = 1.25
        self.build(override=ov)
        self.reduce()
        with open(self.out / "t-split.csv") as f:
            rows = list(csv.DictReader(f))
        self.assertEqual(len(rows), 2 * 7 * 3)
        dp2 = [r for r in rows if r["sizing"] == "s_fixi_a80" and r["divider"] == "dp2"]
        self.assertEqual(len(dp2), 3)
        for r in dp2:
            self.assertAlmostEqual(float(r["d_nf290_db_vs_d0"]), 0.05)
        d0 = [r for r in rows if r["divider"] == "d0"]
        self.assertTrue(all(abs(float(r["d_nf290_db_vs_d0"])) < 1e-12 for r in d0))

    def test_invalid_bias_point_retained_flagged_not_passed(self):
        def ov(stem, case, an, cell, vals):
            if an == "op" and case == "split__s_fixi_a80__dp3" and cell[0] == "bcs":
                vals.update(vbc2=0.7, vce2=0.05)  # Q2 into saturation: raised vb2 / low supply
        self.build(override=ov)
        self.assertEqual(self.reduce(), 0)  # coverage complete; bias invalid is a flag
        with open(self.out / "t-split.csv") as f:
            rows = list(csv.DictReader(f))
        bad = [r for r in rows if r["bias_class"] != "forward_active"]
        self.assertEqual(len(bad), 1)
        self.assertEqual(bad[0]["bias_class2"], "saturated")
        self.assertEqual(bad[0]["counts_for_pass"], "False")
        self.assertIn("INVALID BIAS POINT", (self.out / "t-summary.md").read_text())

    def test_invalid_bias_in_grid_excluded_from_pass_count(self):
        def ov(stem, case, an, cell, vals):
            if an == "op" and case == "grid__s_fixi_a80__ideal" and cell == ("sf", -40, 1.62):
                vals.update(ic2=0.0)
        self.build(override=ov)
        self.reduce()
        g = self.summary()["cases"]["grid__s_fixi_a80__ideal"]
        self.assertEqual(g["n_bias_invalid"], 1)
        self.assertEqual(g["n_nf290_pass"], 44)

    def test_outputs_append_only_and_refuse_records(self):
        self.build()
        self.assertEqual(self.reduce(), 0)
        self.assertEqual(self.reduce(), 2)
        self.assertIn("append-only", self.err)
        self.out = EXP / "records" / "__never_written__"
        try:
            self.assertEqual(self.reduce(), 2)
            self.assertIn("synthetic-fixture", self.err)
            self.assertFalse(self.out.exists())
        finally:
            if self.out.exists():
                import shutil
                shutil.rmtree(self.out)


class Rejections(Base):
    def kinds(self):
        return {(i["kind"], i["analysis"]) for i in self.summary()["issues"]}

    def incomplete(self, override=None):
        self.build(override=override)
        rc = self.reduce()
        self.assertEqual(rc, 2, self.err)
        s = self.summary()
        self.assertFalse(s["complete"])
        self.assertIn("COVERAGE INCOMPLETE", (self.out / "t-summary.md").read_text())
        return s

    def test_missing_report(self):
        self.build()
        (self.cd / "grid__s_fixi_a80__ideal__noise.report.json").unlink()
        self.assertEqual(self.reduce(), 2)
        self.assertIn(("missing_report", "noise"), self.kinds())
        c = self.summary()["cases"]["grid__s_fixi_a80__ideal"]
        self.assertIn("INCOMPLETE", c["claim"])
        self.assertNotIn("/45 cells with", c["claim"])

    def test_missing_cell(self):
        self.build()
        p = self.cd / "grid__s_ctrl_a8__ideal__op.report.json"
        d = json.loads(p.read_text())
        d["corners"].pop()
        p.write_text(json.dumps(d))
        self.assertEqual(self.reduce(), 2)
        self.assertIn(("missing_cell", "op"), self.kinds())
        self.assertEqual(self.summary()["cases"]["grid__s_ctrl_a8__ideal"]["n_complete"], 44)

    def test_error_status_cell(self):
        self.build()
        p = self.cd / "grid__s_ctrl_a8__ideal__sp_stab.report.json"
        d = json.loads(p.read_text())
        d["corners"][3]["status"] = "error"
        d["corners"][4]["error"] = "ngspice crashed"
        p.write_text(json.dumps(d))
        self.assertEqual(self.reduce(), 2)
        self.assertEqual(sum(1 for i in self.summary()["issues"] if i["kind"] == "failed_cell"), 2)

    def test_nonfinite_and_null_and_absent_measurement(self):
        def ov(stem, case, an, cell, vals):
            if case == "grid__s_ctrl_a8__ideal" and an == "op" and cell == ("typ", 27, 1.8):
                vals["ic1"] = float("inf")
                vals["pdc"] = None
                del vals["vce2"]
        self.incomplete(ov)
        k = {i["kind"] for i in self.summary()["issues"]}
        self.assertTrue({"non_finite_value", "missing_measurement"} <= k)

    def test_duplicate_and_unexpected_cell(self):
        self.build()
        p = self.cd / "grid__s_ctrl_a8__ideal__op.report.json"
        d = json.loads(p.read_text())
        d["corners"].append(dict(d["corners"][0]))
        d["corners"].append({**d["corners"][0], "temperature_c": 85})
        p.write_text(json.dumps(d))
        self.assertEqual(self.reduce(), 2)
        k = {i["kind"] for i in self.summary()["issues"]}
        self.assertTrue({"duplicate_cell", "unexpected_cell"} <= k)

    def test_runner_client_version_mismatch(self):
        self.build(runner="0.6.0")
        self.assertEqual(self.reduce(client_version="klt 0.7.0"), 2)
        self.assertIn("version_mismatch", {i["kind"] for i in self.summary()["issues"]})

    def test_unreadable_report(self):
        self.build()
        (self.cd / "grid__s_ctrl_a8__ideal__op.report.json").write_text("{not json")
        self.assertEqual(self.reduce(), 2)
        self.assertIn("unreadable_report", {i["kind"] for i in self.summary()["issues"]})

    def test_tampered_snapshot(self):
        self.build()
        p = self.snap / "grid__s_ctrl_a8__ideal__op.request.json"
        p.write_text(p.read_text() + " ")
        self.assertEqual(self.reduce(), 2)
        self.assertIn("snapshot_drift", {i["kind"] for i in self.summary()["issues"]})


class ControlReplay(Base):
    def reference(self, bump=0.0):
        path = self.root / "ref.csv"
        cols = ["point_id", "corner_label", "temp_c", "vdd_v", "ic1_a", "pdc_w", "s11_db_worst",
                "s21_db_min", "nfmin_sp_db_at_band_lo", "nf290_db_worst"]
        with open(path, "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(cols)
            for lab in C.LABELS:
                for t in C.TEMPS:
                    for v in C.VDDS:
                        w.writerow(["x", lab, t, f"{v:.2f}", 3.5e-3, 7.0e-3, -12.0, 16.0 * (1 + bump), 1.0, 1.2])
        return path

    def test_replay_matches(self):
        self.build()
        self.assertEqual(self.reduce(reference_csv=self.reference()), 0, self.err)
        self.assertIn("45 control cells compared", self.summary()["control_replay"])

    def test_drift_beyond_tolerance_fails(self):
        self.build()
        self.assertEqual(self.reduce(reference_csv=self.reference(bump=1e-5)), 3)
        self.assertTrue(self.summary()["control_drift"])
        self.assertEqual(R.REPLAY_REL_TOL, 1e-6)  # the existing parser's tolerance, not relaxed

    def test_tolerance_matches_existing_parser(self):
        src = (EXP / "parse_core_envelope.py").read_text()
        self.assertIn("worst > 1e-6", src)


if __name__ == "__main__":
    unittest.main()
