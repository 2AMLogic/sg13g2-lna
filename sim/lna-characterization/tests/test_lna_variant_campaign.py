"""Unit tests for the pure helpers in lna_variant_campaign.py (stdlib only)."""
import importlib.util
import io
import json
import math
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

LNA = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location("lna_variant_campaign", LNA / "lna_variant_campaign.py")
V = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(V)


class VariantHelpers(unittest.TestCase):
    def test_le_series_r(self):
        # R = w L / Q, w = 2 pi 2.44175e9, L = 1 nH: wL = 15.3420 Ohm.
        self.assertAlmostEqual(V.le_series_r(1.0), 15.3420, places=3)
        self.assertAlmostEqual(V.le_series_r(10.0), 1.53420, places=4)
        self.assertAlmostEqual(V.le_series_r(5.0) / V.le_series_r(20.0), 4.0)

    def test_corner_key_and_values(self):
        c = {"process": {"name": "typ"}, "temperature_c": 27, "supply_v": {"vdd": 1.8}}
        self.assertEqual(V.corner_key(c), ("typ", 27.0, 1.8))
        c2 = {"process": "bcs", "temp_c": "-40", "supply_v": 1.62}
        self.assertEqual(V.corner_key(c2), ("bcs", -40.0, 1.62))
        self.assertEqual(
            V.corner_values({"measurements": [{"name": "a", "value": 1}, {"name": "b"}]}),
            {"a": 1, "b": None},
        )

    def test_variant_table_is_consistent(self):
        for name, (desc, lc, le_q) in V.VARIANTS.items():
            self.assertIn(lc, ("ideal", "em"), name)
            self.assertTrue(le_q is None or le_q > 0, name)

    def test_dut_subckt_edits(self):
        ideal = V.dut_subckt("ideal", None)
        self.assertIn(V.LE_LINE, ideal)
        self.assertIn(V.LC_LINE, ideal)
        q = V.dut_subckt("ideal", 10)
        self.assertNotIn(V.LE_LINE, q)
        self.assertIn(f"Rle le_x vss {V.le_series_r(10):.5f}", q)
        em = V.dut_subckt("em", None)
        self.assertNotIn(V.LC_LINE, em)
        self.assertIn("XLc vdd outn vss " + V.LC_EM_INSTANCE, em)


# ---------------------------------------------------------------------------
# SYNTHETIC FIXTURES. Every number below is invented by this test module to
# exercise the reducer. They are NOT circuit evidence and must never be cited
# as such (label: "synthetic-fixture").
# ---------------------------------------------------------------------------

GOOD = {  # passes every ratified row
    "s21_db_min": 16.0, "s11_db_worst": -12.0, "s22_db_worst": -11.0,
    "mu_min": 1.5, "nf290_db_worst": 1.2,
}


def synth_values(analysis, overrides=None):
    vals = {m["name"]: 1.0 for m in V.measurements(analysis)}
    vals.update({k: v for k, v in GOOD.items() if k in vals})
    if analysis == "noise":  # retained NF samples consistent with the reported worst
        worst = vals["nf290_db_worst"]
        for n in V.nf_sample_names():
            vals[n] = worst
    vals.update(overrides or {})
    return vals


def synth_cell(key, analysis, overrides=None, status="ok"):
    lab, t, v = key
    return {"process": {"name": lab}, "temperature_c": t, "supply_v": {"vdd": v},
            "status": status,
            "measurements": [{"name": n, "value": x} for n, x in synth_values(analysis, overrides).items()]}


def write_reports(d, variants=("ideal",), grid=V.GRID_FULL, mutate=None):
    """Write synthetic-fixture reports. mutate(variant, analysis, corners) may edit."""
    for var in variants:
        for an in V.ANALYSES:
            corners = [synth_cell(k, an) for k in V.expected_grid(grid)]
            if mutate:
                corners = mutate(var, an, corners) or corners
            (Path(d) / f"{var}_{an}.report.json").write_text(
                json.dumps({"fixture": "synthetic-fixture", "corners": corners}))


def run_summ(d, grid=V.GRID_FULL, variants=""):
    d = Path(d)
    argv = ["summarize", "--corners-dir", str(d), "--summary-csv", str(d / "s.csv"),
            "--compare-csv", str(d / "c.csv"), "--headlines-md", str(d / "h.md"),
            "--coverage-json", str(d / "cov.json"), "--grid", grid]
    if variants:
        argv += ["--variants", variants]
    old = sys.argv
    sys.argv = ["x"] + argv
    out, err = io.StringIO(), io.StringIO()
    try:
        with redirect_stdout(out), redirect_stderr(err):
            try:
                V.main()
                rc = 0
            except SystemExit as e:
                rc = e.code if isinstance(e.code, int) else 1
    finally:
        sys.argv = old
    cov = json.loads((d / "cov.json").read_text()) if (d / "cov.json").exists() else None
    return rc, cov, err.getvalue()


def kinds(cov):
    return sorted({i["kind"] for i in cov["issues"]})


class ExpectedGrid(unittest.TestCase):
    def test_grid_size_and_smoke(self):
        self.assertEqual(len(V.expected_grid()), 45)
        self.assertEqual(len(set(V.expected_grid())), 45)
        self.assertEqual(V.expected_grid(V.GRID_SMOKE), [("typ", 27.0, 1.8)])

    def test_matches_generated_request(self):
        req = V.request("ideal", "noise", "x.spice", False, None)
        c = req["corners"]
        self.assertEqual(len(c["process"]) * len(c["supply_v"]["vdd"]) * len(c["temperature_c"]), 45)


class Reduction(unittest.TestCase):
    def test_complete_grid_summary_and_order_independence(self):
        with tempfile.TemporaryDirectory() as d1, tempfile.TemporaryDirectory() as d2:
            write_reports(d1)
            write_reports(d2, mutate=lambda v, a, c: list(reversed(c)))
            rc1, cov1, _ = run_summ(d1)
            rc2, cov2, _ = run_summ(d2)
            self.assertEqual((rc1, rc2), (0, 0))
            self.assertEqual(cov1["coverage"], "complete")
            self.assertEqual(cov1, cov2)  # deterministic, order independent
            self.assertEqual({r["row"] for r in cov1["ideal_rows"]},
                             {"gain", "s11", "s22", "stability", "nf290"})
            for r in cov1["ideal_rows"]:
                self.assertEqual((r["valid_cells"], r["expected_cells"]), (45, 45))
                self.assertIn("meets target", r["verdict"])
                self.assertIn("spec/target-spec.md", r["spec_row"])
            md = (Path(d1) / "h.md").read_text()
            self.assertIn("three", md.lower())
            self.assertIn("IIP3", md)
            self.assertIn("DC power", md)
            self.assertNotIn("COVERAGE INCOMPLETE", md)

    def test_worst_cell_and_tie_handling(self):
        def mut(v, a, corners):
            for c in corners:
                if a == "sp_band":
                    c["measurements"] = [
                        {"name": m["name"], "value": (14.0 if m["name"] == "s21_db_min"
                                                      and c["process"]["name"] in ("wcs", "fs") else m["value"])}
                        for m in c["measurements"]]
        with tempfile.TemporaryDirectory() as d:
            write_reports(d, mutate=mut)
            rc, cov, _ = run_summ(d)
            self.assertEqual(rc, 0)
            gain = next(r for r in cov["ideal_rows"] if r["row"] == "gain")
            # ties: first cell in canonical order (wcs precedes fs in LABELS; temp -40, 1.62 V)
            self.assertEqual(gain["worst_cell"], "wcs/-40C/1.62V")
            self.assertEqual(gain["worst_value"], 14.0)
            self.assertIn("FAILS", gain["verdict"])

    def test_strict_threshold_equality_fails(self):
        for row, meas, val in [("gain", "s21_db_min", 15.0), ("s11", "s11_db_worst", -10.0),
                               ("s22", "s22_db_worst", -10.0), ("stability", "mu_min", 1.0),
                               ("nf290", "nf290_db_worst", 1.5)]:
            an = next(r[2] for r in V.ROW_REDUCTIONS if r[0] == row)

            def mut(v, a, corners, an=an, meas=meas, val=val):
                if a == an:
                    for c in corners:
                        for m in c["measurements"]:
                            if m["name"] == meas or (
                                    meas == "nf290_db_worst" and m["name"] in V.nf_sample_names()):
                                m["value"] = val
            with tempfile.TemporaryDirectory() as d:
                write_reports(d, mutate=mut)
                rc, cov, _ = run_summ(d)
                self.assertEqual(rc, 0, row)
                r = next(x for x in cov["ideal_rows"] if x["row"] == row)
                self.assertIn("FAILS", r["verdict"], row)

    def test_worst_in_band_vs_mid_band(self):
        # mid-band S11 is fine, worst in-band is not: the worst-in-band column decides.
        def mut(v, a, corners):
            for c in corners:
                for m in c["measurements"]:
                    if m["name"] == "s11_db_mid":
                        m["value"] = -30.0
                    if m["name"] == "s11_db_worst":
                        m["value"] = -9.0
        with tempfile.TemporaryDirectory() as d:
            write_reports(d, mutate=mut)
            _, cov, _ = run_summ(d)
            r = next(x for x in cov["ideal_rows"] if x["row"] == "s11")
            self.assertEqual(r["measurement"], "s11_db_worst")
            self.assertIn("FAILS", r["verdict"])

    def test_nf_conventions_distinct(self):
        nf = next(r for r in V.ROW_REDUCTIONS if r[0] == "nf290")
        self.assertEqual(nf[3], "nf290_db_worst")
        self.assertNotIn("sp", nf[3])
        self.assertTrue(any("nfmin" in x.lower() and "290" in x for x in V.DISCLOSURES))

    def test_smoke_one_cell(self):
        with tempfile.TemporaryDirectory() as d:
            write_reports(d, grid=V.GRID_SMOKE)
            rc, cov, _ = run_summ(d, grid=V.GRID_SMOKE)
            self.assertEqual(rc, 0)
            self.assertEqual(cov["expected_cells_per_analysis"], 1)
            self.assertIn("SMOKE", (Path(d) / "h.md").read_text())
            # the same one-cell input is incomplete against the full grid
            rc, cov, _ = run_summ(d)
            self.assertNotEqual(rc, 0)
            self.assertIn("missing_cell", kinds(cov))

    def test_variant_comparison_still_written(self):
        with tempfile.TemporaryDirectory() as d:
            write_reports(d, variants=("ideal", "le_q10"))
            rc, cov, _ = run_summ(d)
            self.assertEqual(rc, 0)
            self.assertEqual(len((Path(d) / "c.csv").read_text().splitlines()), 1 + 45)


class BadInput(unittest.TestCase):
    def check_bad(self, mutate, kind, detail_in=None, variants=("ideal",)):
        with tempfile.TemporaryDirectory() as d:
            write_reports(d, variants=variants, mutate=mutate)
            rc, cov, err = run_summ(d)
            self.assertNotEqual(rc, 0)
            self.assertEqual(cov["coverage"], "incomplete")
            self.assertIn(kind, kinds(cov))
            self.assertIn("COVERAGE INCOMPLETE", (Path(d) / "h.md").read_text())
            self.assertIn("COVERAGE INCOMPLETE", err)
            self.assertTrue(all("NOT EVALUATED" in r["verdict"] for r in cov["ideal_rows"]
                                if r["valid_cells"] < r["expected_cells"]))
            if detail_in:
                self.assertIn(detail_in, err)
            return cov

    def test_missing_cell(self):
        cov = self.check_bad(lambda v, a, c: c[:-1] if a == "noise" else None, "missing_cell", "analysis=noise")
        nf = next(r for r in cov["ideal_rows"] if r["row"] == "nf290")
        self.assertEqual(nf["valid_cells"], 44)
        gain = next(r for r in cov["ideal_rows"] if r["row"] == "gain")
        self.assertEqual(gain["valid_cells"], 45)

    def test_missing_analysis(self):
        with tempfile.TemporaryDirectory() as d:
            write_reports(d)
            (Path(d) / "ideal_sp_stab.report.json").unlink()
            rc, cov, _ = run_summ(d)
            self.assertNotEqual(rc, 0)
            self.assertIn("missing_report", kinds(cov))

    def test_missing_ideal_when_other_variant_only(self):
        with tempfile.TemporaryDirectory() as d:
            write_reports(d, variants=("le_q10",))
            rc, cov, _ = run_summ(d)
            self.assertNotEqual(rc, 0)
            rc, cov, _ = run_summ(d, variants="le_q10")
            self.assertEqual(rc, 0)
            self.assertIsNone(cov["ideal_rows"])

    def test_missing_measurement(self):
        def mut(v, a, c):
            if a == "sp_band":
                c[3]["measurements"] = [m for m in c[3]["measurements"] if m["name"] != "s11_db_worst"]
        self.check_bad(mut, "missing_measurement", "measurement=s11_db_worst")

    def test_null_measurement(self):
        def mut(v, a, c):
            if a == "sp_stab":
                c[0]["measurements"][0]["value"] = None
        self.check_bad(mut, "missing_measurement")

    def test_duplicate_cell(self):
        def mut(v, a, c):
            if a == "sp_band":
                c.append(json.loads(json.dumps(c[7])))
        cov = self.check_bad(mut, "duplicate_cell", "duplicate_cell")
        gain = next(r for r in cov["ideal_rows"] if r["row"] == "gain")
        self.assertEqual(gain["valid_cells"], 44)

    def test_unexpected_cell(self):
        def mut(v, a, c):
            if a == "noise":
                extra = json.loads(json.dumps(c[0]))
                extra["temperature_c"] = 85
                c.append(extra)
        self.check_bad(mut, "unexpected_cell", "temperature" if False else "cell=typ/85C")

    def test_failed_cell(self):
        def mut(v, a, c):
            if a == "sp_band":
                c[10]["status"] = "error"
        cov = self.check_bad(mut, "failed_cell")
        bad = [i for i in cov["issues"] if i["kind"] == "failed_cell"][0]
        self.assertEqual(bad["analysis"], "sp_band")
        self.assertEqual(bad["cell"], cell_of(10))

    def test_non_finite(self):
        for bad in (float("nan"), float("inf"), float("-inf")):
            def mut(v, a, c, bad=bad):
                if a == "noise":
                    for m in c[2]["measurements"]:
                        if m["name"] == "nf290_db_worst":
                            m["value"] = bad
            cov = self.check_bad(mut, "non_finite_value", "measurement=nf290_db_worst")
            nf = next(r for r in cov["ideal_rows"] if r["row"] == "nf290")
            self.assertIn("NOT EVALUATED", nf["verdict"])

    def test_unreadable_report(self):
        with tempfile.TemporaryDirectory() as d:
            write_reports(d)
            (Path(d) / "ideal_noise.report.json").write_text("{not json")
            rc, cov, _ = run_summ(d)
            self.assertNotEqual(rc, 0)
            self.assertIn("unreadable_report", kinds(cov))

    def test_no_reports_nonzero(self):
        with tempfile.TemporaryDirectory() as d:
            rc, cov, _ = run_summ(d)
            self.assertNotEqual(rc, 0)


def cell_of(i):
    return V.cell_text(V.expected_grid()[i])


class WrapperPropagation(unittest.TestCase):
    """Static + CLI checks; the wrapper itself needs a PDK and klt, so it is
    not executed here (no simulator or fleet run)."""

    def test_wrapper_no_longer_masks_reduction(self):
        text = (LNA / "run_lna_variant.sh").read_text()
        i = text.index("lna_variant_campaign.py\" summarize")
        self.assertNotIn("|| true", text[i:i + 400])
        self.assertIn("SUMMARIZE_RC", text)
        self.assertIn("exit 1", text[text.rindex("SUMMARIZE_RC != 0"):])

    def test_cli_exit_code_and_artifacts_retained(self):
        with tempfile.TemporaryDirectory() as d:
            write_reports(d, mutate=lambda v, a, c: c[:-1] if a == "noise" else None)
            p = subprocess.run(
                [sys.executable, "-I", str(LNA / "lna_variant_campaign.py"), "summarize",
                 "--corners-dir", d, "--summary-csv", f"{d}/s.csv", "--compare-csv", f"{d}/c.csv",
                 "--headlines-md", f"{d}/h.md"], capture_output=True, text=True)
            self.assertNotEqual(p.returncode, 0)
            self.assertTrue((Path(d) / "s.csv").exists() and (Path(d) / "h.md").exists())
            self.assertTrue((Path(d) / "ideal_noise.report.json").exists())


class NoiseGrid(unittest.TestCase):
    """Issue #134: 290 K NF over the full in-band grid (synthetic fixtures)."""

    PEAK_IDX = 3  # interior, not one of lo/mid/hi

    def peak_mutator(self, idx=PEAK_IDX, peak=1.4, base=1.0):
        names = V.nf_sample_names()

        def mut(v, a, c):
            if a != "noise":
                return
            for cell in c:
                for m in cell["measurements"]:
                    if m["name"] in names:
                        m["value"] = peak if m["name"] == names[idx] else base
                    elif m["name"] in ("nf290_db_lo", "nf290_db_mid", "nf290_db_hi"):
                        m["value"] = base
                    elif m["name"] == "nf290_db_worst":
                        m["value"] = peak
        return mut

    def test_default_grid_is_the_sparameter_grid(self):
        self.assertEqual(V.N_NF, V.N_BAND)
        self.assertEqual(len(V.nf_freqs()), 11)
        self.assertAlmostEqual(V.nf_freqs()[V.MID], V.F_MID, delta=1.0)
        self.assertEqual(V.nf_freqs()[0], V.F_LO)
        card = V.analysis_card("noise")
        self.assertEqual(card["args"], "v(nfout) vin lin 11 2.4e+09 2.4835e+09")

    def test_baseline_and_lossy_variants_share_grid_and_conventions(self):
        cards = {(v, a): (V.request(v, a, "x.spice", False, None)["analysis"],
                          V.request(v, a, "x.spice", False, None)["measurements"])
                 for v in V.VARIANTS for a in ("noise",)}
        self.assertEqual(len({json.dumps(c, sort_keys=True) for c in cards.values()}), 1)
        for v in V.VARIANTS:
            self.assertEqual(len(V.measurements("noise")), 4 + 11)
            self.assertIn("Rs vin nfin 50 noisy=0", V.netlist(v, "noise", "m.spice"))
            self.assertIn("RL nfout 0 50 noisy=0", V.netlist(v, "noise", "m.spice"))

    def test_interior_peak_is_the_worst_with_its_frequency(self):
        with tempfile.TemporaryDirectory() as d:
            write_reports(d, mutate=self.peak_mutator())
            rc, cov, _ = run_summ(d)
            self.assertEqual(rc, 0)
            nf = next(r for r in cov["ideal_rows"] if r["row"] == "nf290")
            self.assertAlmostEqual(nf["worst_value"], 1.4)
            self.assertAlmostEqual(nf["worst_frequency_hz"], V.nf_freqs()[self.PEAK_IDX], delta=1.0)
            self.assertEqual(nf["nf_grid"]["n"], 11)
            self.assertIn("11 pts", nf["frequency_sampling"])
            self.assertIn("peak narrower than the spacing", nf["frequency_sampling"])
            # the three lo/mid/hi samples alone would have said 1.0
            self.assertIn("GHz", (Path(d) / "h.md").read_text())
            self.assertIn("worst SAMPLED", (Path(d) / "h.md").read_text())
            self.assertIn("nf290_f_at_worst_hz", (Path(d) / "s.csv").read_text())

    def test_missing_duplicate_nonfinite_samples_reject_complete_grid(self):
        names = V.nf_sample_names()
        def drop(v, a, c):
            if a == "noise":
                c[0]["measurements"] = [m for m in c[0]["measurements"] if m["name"] != names[4]]
        def dup(v, a, c):
            if a == "noise":
                m = next(m for m in c[0]["measurements"] if m["name"] == names[4])
                c[0]["measurements"].append(dict(m))
        def nan(v, a, c):
            if a == "noise":
                for m in c[0]["measurements"]:
                    if m["name"] == names[4]:
                        m["value"] = float("nan")
        for mut, kind in ((drop, "missing_measurement"), (dup, "duplicate_measurement"),
                          (nan, "non_finite_value")):
            with tempfile.TemporaryDirectory() as d:
                write_reports(d, mutate=mut)
                rc, cov, _ = run_summ(d)
                self.assertNotEqual(rc, 0, kind)
                self.assertIn(kind, kinds(cov))
                nf = next(r for r in cov["ideal_rows"] if r["row"] == "nf290")
                self.assertIn("NOT EVALUATED", nf["verdict"])
                self.assertEqual(nf["valid_cells"], 44)

    def test_reported_worst_must_match_retained_samples(self):
        def mut(v, a, c):
            if a == "noise":
                for m in c[0]["measurements"]:
                    if m["name"] == "nf290_db_worst":
                        m["value"] = 0.5  # below every retained sample
        with tempfile.TemporaryDirectory() as d:
            write_reports(d, mutate=mut)
            rc, cov, _ = run_summ(d)
            self.assertNotEqual(rc, 0)
            self.assertIn("inconsistent_nf_worst", kinds(cov))

    def test_denser_validation_grid_is_configurable(self):
        n = 41
        self.assertEqual(len(V.measurements("noise", n)), 4 + n)
        self.assertIn(f"lin {n} ", V.analysis_card("noise", n)["args"])
        self.assertAlmostEqual(V.nf_freqs(n)[(n - 1) // 2], V.F_MID, delta=1.0)
        # a report generated with the default grid is incomplete against 41 points
        with tempfile.TemporaryDirectory() as d:
            write_reports(d)
            old = sys.argv
            argv = ["x", "summarize", "--corners-dir", d, "--summary-csv", f"{d}/s.csv",
                    "--compare-csv", f"{d}/c.csv", "--headlines-md", f"{d}/h.md",
                    "--coverage-json", f"{d}/cov.json", "--nf-npts", str(n)]
            sys.argv = argv
            try:
                with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                    with self.assertRaises(SystemExit) as cm:
                        V.main()
            finally:
                sys.argv = old
            self.assertNotEqual(cm.exception.code, 0)
            cov = json.loads((Path(d) / "cov.json").read_text())
            self.assertEqual(cov["nf290_npts"], n)
            self.assertIn("missing_measurement", kinds(cov))

    def test_bad_grid_sizes_rejected(self):
        for n in (3, 10, 12, 0, -11):
            with self.assertRaises(SystemExit):
                V.check_nf_npts(n)



if __name__ == "__main__":
    unittest.main()
