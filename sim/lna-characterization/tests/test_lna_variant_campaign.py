"""Unit tests for the pure helpers in lna_variant_campaign.py (stdlib only)."""
import argparse
import csv
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
_ps_spec = importlib.util.spec_from_file_location("parse_lna_sweep", LNA / "parse_lna_sweep.py")
_sweep = importlib.util.module_from_spec(_ps_spec)
_ps_spec.loader.exec_module(_sweep)


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
            self.assertIn(lc, ("ideal", "em", "design"), name)
            self.assertTrue(le_q is None or le_q > 0, name)

    def test_matched_variant_inlines_live_netlist_verbatim(self):
        body = V.dut_subckt("design", None)
        self.assertIn("Lb lb_x rfin", body)  # the #27 input network is present
        self.assertNotIn(V.LC_LINE, body)    # not the pre-match Lc
        self.assertNotIn("VARIANT EDIT", body)
        self.assertNotIn("Lb ", V.dut_subckt("ideal", None))  # baseline stays pre-match
        self.assertIn("matched", V.header("matched", "sp_band"))

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


class TemperatureSlice(unittest.TestCase):
    """--temps / LNA_TEMPS slicing (issue #306). apply_temps mutates the module
    global TEMPS, so every test restores the full list in tearDown: a leaked
    slice would silently shrink ExpectedGrid.test_grid_size_and_smoke's
    45-cell assertion depending on test order."""

    def tearDown(self):
        V.TEMPS = list(V.TEMPS_ALL)

    def test_slice_noop_and_validation(self):
        V.apply_temps("125")
        self.assertEqual(V.TEMPS, [125])
        V.apply_temps("")
        self.assertEqual(V.TEMPS, [125])  # empty spec is a no-op
        for bad in ("25", ","):
            with self.assertRaises(SystemExit):
                V.apply_temps(bad)
        self.assertEqual(V.TEMPS, [125])  # a rejected spec leaves the slice untouched

    def test_rejected_value_exits_nonzero_with_existing_message(self):
        with self.assertRaises(SystemExit) as cm:
            V.apply_temps("25")
        self.assertIn("--temps must be a comma list drawn from", str(cm.exception))

    def test_canonical_order_not_input_order(self):
        V.apply_temps("27,-40")
        self.assertEqual(V.TEMPS, [-40, 27])

    def test_slice_equal_to_full_set_is_not_a_slice(self):
        V.apply_temps("125,-40,27")
        self.assertEqual(V.TEMPS, V.TEMPS_ALL)
        md = V.coverage_markdown([], V.GRID_FULL, True, [])
        self.assertFalse(any("TEMPERATURE SLICE" in line for line in md))

    def test_expected_grid_shrinks_to_the_slice(self):
        V.apply_temps("125")
        grid = V.expected_grid()
        self.assertEqual(len(grid), len(V.LABELS) * 1 * len(V.VDDS))
        self.assertEqual(len(grid), 15)
        self.assertEqual({t for _, t, _ in grid}, {125})

    def test_summarize_names_slice_and_full_grid_does_not(self):
        # Sliced run: disclosure line in headlines.md + machine-readable temps in
        # coverage.json. Full-grid run: neither appears (the disclosure must not
        # silently fire on every record).
        with tempfile.TemporaryDirectory() as d1, tempfile.TemporaryDirectory() as d2:
            V.apply_temps("125")
            write_reports(d1)
            rc1, cov1, _ = run_summ(d1)
            V.TEMPS = list(V.TEMPS_ALL)
            write_reports(d2)
            rc2, cov2, _ = run_summ(d2)
            self.assertEqual((rc1, rc2), (0, 0))
            self.assertEqual(cov1["temps"], [125])
            self.assertEqual(cov2["temps"], V.TEMPS_ALL)
            md1 = (Path(d1) / "h.md").read_text()
            md2 = (Path(d2) / "h.md").read_text()
            self.assertIn("TEMPERATURE SLICE", md1)
            self.assertIn(f"only {[125]} of {V.TEMPS_ALL}", md1)
            self.assertNotIn("TEMPERATURE SLICE", md2)

    def test_smoke_slice_names_grid_temp_not_slice_temp(self):
        # Smoke grid's single expected cell is the nominal 27 C cell regardless of
        # the slice (issue #329): the disclosure must name 27, not the slice's 125.
        with tempfile.TemporaryDirectory() as d:
            V.apply_temps("125")
            write_reports(d, grid=V.GRID_SMOKE)
            rc, cov, _ = run_summ(d, grid=V.GRID_SMOKE)
            self.assertEqual(rc, 0)
            self.assertEqual(cov["temps"], [125])  # requested slice, machine-readable
            md = (Path(d) / "h.md").read_text()
            self.assertIn("TEMPERATURE SLICE", md)
            self.assertIn(f"only [27] of {V.TEMPS_ALL}", md)
            self.assertNotIn("only [125]", md)


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

    def test_wrapper_passes_same_temps_to_gen_and_summarize(self):
        # issue #306: LNA_TEMPS is read once and handed to BOTH subcommands (so
        # they cannot diverge through the wrapper), and the slice must disclose
        # itself in the run log and the generated record.
        text = (LNA / "run_lna_variant.sh").read_text()
        gen_call = text.index("lna_variant_campaign.py\" gen")
        summ_call = text.index("lna_variant_campaign.py\" summarize")
        self.assertIn('GEN_ARGS+=("--temps=${LNA_TEMPS}")', text[:gen_call])
        self.assertIn('SUMMARIZE_ARGS+=("--temps=${LNA_TEMPS}")', text[gen_call:summ_call])
        self.assertIn("LNA_TEMPS set", text[:gen_call])
        self.assertIn("TEMPERATURE SLICE", text[summ_call:])

    def test_wrapper_record_smoke_branch_precedes_slice(self):
        # issue #352: the record's Claim and Reduction chains must consult
        # LNA_VARIANT_SMOKE before the LNA_TEMPS slice elif, and each smoke
        # arm must name the single cell and disclose an ignored slice.
        text = (LNA / "run_lna_variant.sh").read_text()
        record = text[text.index("# Record ${RECORD_ID}"):]
        claim = record[record.index("**Claim**"):record.index("**DUT**")]
        self.assertLess(claim.index("LNA_VARIANT_SMOKE"),
                        claim.index('elif [[ -n "${LNA_TEMPS:-}" ]]'))
        self.assertIn("single nominal 27 C", claim)
        self.assertIn("was ignored", claim)
        reduction = record[record.index("if (( SUMMARIZE_RC != 0 ))"):record.index("**Headlines")]
        self.assertLess(reduction.index("SUMMARIZE_RC != 0"),
                        reduction.index("LNA_VARIANT_SMOKE"))
        self.assertLess(reduction.index("LNA_VARIANT_SMOKE"),
                        reduction.index('elif [[ -n "${LNA_TEMPS:-}" ]]'))
        self.assertIn("single nominal 27 C", reduction)
        self.assertIn("was ignored", reduction)

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


class BiasAttribution(unittest.TestCase):
    """The bias-attribution claim generator in cmd_summarize: pct() (the
    `ic1_pct` compare-CSV column), span_scaled() (the `I_C1 [mA]` and
    `DC emitter lift v(e1) [mV]` headline rows) and the attribution branch
    whose ±0.05 % bound decides whether a variant's gain/NF delta may be
    quoted as a loss cost at all. The bound is `V.IC1_ATTRIB_PCT`, the value
    documented in README "Bias confound" -- cited, not re-invented here.
    label: synthetic-fixture -- every number below is a reducer input invented
    by this module, never circuit evidence."""

    def ic1_hook(self, factors, bumps=None):
        """write_reports mutate hook: in `op` reports, per canonical cell i,
        ic1 = factors[v] * (1 + i*1e-6) * (1 + bumps.get(v, {}).get(i, 0)) and
        ve1 = 1 + i*1e-6. The i-spread makes span_scaled()'s min/max cells
        unique and identifiable (i==0 the minimum, i==44 the maximum); a bump
        at one cell makes the worst-pct cell unique."""
        if not factors:
            return None
        bumps = bumps or {}

        def mut(v, a, corners):
            if a != "op" or v not in factors:
                return
            vb = bumps.get(v, {})
            for i, c in enumerate(corners):
                for m in c["measurements"]:
                    if m["name"] == "ic1":
                        m["value"] = factors[v] * (1.0 + i * 1e-6) * (1.0 + vb.get(i, 0.0))
                    elif m["name"] == "ve1":
                        m["value"] = 1.0 + i * 1e-6
        return mut

    @staticmethod
    def section(md, variant):
        i = md.index(f"### Variant `{variant}`")
        j = md.find("### Variant `", i + 1)
        return md[i: j if j != -1 else len(md)]

    def run_case(self, factors=None, bumps=None, variants=("ideal", "le_q10"), mutate=None):
        with tempfile.TemporaryDirectory() as d:
            write_reports(d, variants=variants, mutate=mutate or self.ic1_hook(factors, bumps))
            rc, cov, _ = run_summ(d)
            md = (Path(d) / "h.md").read_text()
            with open(Path(d) / "c.csv") as f:
                rows = list(csv.reader(f))
            return rc, cov, md, rows

    def test_equal_ic1_takes_within_branch_and_zero_pct(self):
        # untouched fixtures: ic1 == ideal at every cell -> the "within" line
        rc, _, md, rows = self.run_case(variants=("ideal", "le_q20"))
        self.assertEqual(rc, 0)
        sec = self.section(md, "le_q20")
        self.assertIn(f"- Bias attribution: I_C1 within +/-{V.IC1_ATTRIB_PCT} % of `ideal` "
                      "at every cell -- the deltas above are inductor loss, not a bias shift.", sec)
        head, data = rows[0], rows[1:]
        j = head.index("ic1_pct")
        self.assertEqual(data[0][0], "le_q20")  # first compare row: le_q20 typ/-40C/1.62V
        self.assertEqual(data[0][j], "+0.00")

    def test_negative_shift_takes_not_inductor_loss_branch(self):
        # ic1 = 0.88 x ideal (-12 %) everywhere, one cell (idx 44) pushed to
        # -13.76 % so the worst cell is unique and named in the emitted line.
        rc, _, md, rows = self.run_case({"ideal": 1.0, "le_q10": 0.88},
                                        bumps={"le_q10": {44: -0.02}})
        self.assertEqual(rc, 0)
        sec = self.section(md, "le_q10")
        self.assertIn("**I_C1 shifts up to -13.76 % vs `ideal`**", sec)
        self.assertIn("NOT inductor loss alone", sec)
        self.assertIn("worst fs/125C/1.98V", sec)
        head, data = rows[0], rows[1:]
        jp, jd = head.index("ic1_pct"), head.index("d_ic1_a")
        first = next(r for r in data if r[0] == "le_q10")
        # variant below ideal: d_ic1_a and ic1_pct both negative, signs agree
        self.assertEqual(first[jd], "-0.12000")
        self.assertEqual(first[jp], "-12.00")

    def test_threshold_boundary_pinned_from_both_sides(self):
        # worst-cell shift +0.04 % (< the bound) stays "within"; +0.06 %
        # crosses it and must warn. Positive shifts on purpose: a sign
        # inversion must not hide behind an all-negative fixture set.
        rc, _, md, _ = self.run_case({"ideal": 1.0, "le_q5": 1.0},
                                     bumps={"le_q5": {10: 4e-4}},
                                     variants=("ideal", "le_q5"))
        self.assertEqual(rc, 0)
        sec = self.section(md, "le_q5")
        self.assertIn(f"- Bias attribution: I_C1 within +/-{V.IC1_ATTRIB_PCT} % of `ideal`", sec)
        self.assertNotIn("NOT inductor loss alone", sec)
        rc, _, md, _ = self.run_case({"ideal": 1.0, "le_q5": 1.0},
                                     bumps={"le_q5": {10: 6e-4}},
                                     variants=("ideal", "le_q5"))
        self.assertEqual(rc, 0)
        sec = self.section(md, "le_q5")
        self.assertIn("**I_C1 shifts up to +0.06 % vs `ideal`**", sec)
        self.assertIn("NOT inductor loss alone", sec)
        self.assertNotIn("inductor loss, not a bias shift", sec)

    def test_span_scaled_units_and_min_max_cell_identities(self):
        # ic1 is measured in A, reported in mA (1e3x, 4 dp); ve1 in V reported
        # in mV (1e3x, 3 dp). The min/max cells must name the cells that
        # actually hold the extremes, not each other's.
        rc, _, md, _ = self.run_case({"ideal": 1.0, "le_q10": 1.0})
        self.assertEqual(rc, 0)
        sec = self.section(md, "le_q10")
        lo = V.cell_text(V.expected_grid()[0])
        hi = V.cell_text(V.expected_grid()[44])
        self.assertIn(f"- I_C1 [mA]: min 1000.0000 @ {lo}, max 1000.0440 @ {hi}", sec)
        self.assertIn(f"- DC emitter lift v(e1) [mV]: min 1000.000 @ {lo}, max 1000.044 @ {hi}", sec)

    def test_no_ideal_ic1_emits_explicit_not_computed_line(self):
        # ic1 removed from the ideal op reports only: pcts empty AND base_ic1
        # empty. Coverage validation fails the run (missing_measurement), but
        # headlines.md is still written -- the attribution row must say so
        # explicitly instead of being silently omitted from the artifact.
        def mut(v, a, corners):
            if v == "ideal" and a == "op":
                for c in corners:
                    c["measurements"] = [m for m in c["measurements"] if m["name"] != "ic1"]
        rc, cov, md, _ = self.run_case(mutate=mut)
        self.assertNotEqual(rc, 0)
        self.assertIn("missing_measurement", kinds(cov))
        sec = self.section(md, "le_q10")
        self.assertIn("- Bias attribution: I_C1 not computed", sec)
        self.assertNotIn("within +/-", sec)
        self.assertNotIn("NOT inductor loss alone", sec)

    def test_zero_ideal_ic1_reports_no_per_cell_comparison(self):
        # ideal ic1 present (0.0 at every cell) but falsy, so no per-cell
        # comparison happens: the existing "no per-cell" line is emitted, not
        # the "not computed" one -- base_ic1 is non-empty in this branch.
        def mut(v, a, corners):
            if v == "ideal" and a == "op":
                for c in corners:
                    for m in c["measurements"]:
                        if m["name"] == "ic1":
                            m["value"] = 0.0
        rc, _, md, _ = self.run_case(mutate=mut)
        self.assertEqual(rc, 0)
        sec = self.section(md, "le_q10")
        self.assertIn("- Bias attribution: no per-cell `ideal` I_C1 to compare against.", sec)
        self.assertNotIn("I_C1 not computed", sec)


# ---------------------------------------------------------------------------
# Two-tone IIP3 (issue #337): generation helpers and the summarize-iip3
# reducer, on synthetic fixtures only.
# ---------------------------------------------------------------------------

def synth_log(path, ic1=0.00394, ic2=0.00393, idd=0.00471, dft=(0.005114, 0.005116, 2.55e-10, 2.56e-10, 0.000999)):
    t1, t2, i3l, i3h, s1 = dft
    path.write_text(
        f'OP ic1 {ic1!r} ic2 {ic2!r} vce1 0.8 vce2 0.96 idd {idd!r}\n'
        'NPTS 65536\n'
        f'DFT tone1 {t1!r} tone2 {t2!r} im3l {i3l!r} im3h {i3h!r} src1 {s1!r}\n')


def synth_report(path, label, temp, vdd, amp, fft):
    """One IIP3 corner's klt report + its kept-log layout, as gen-iip3/the
    batch set produce them. `fft` = the nine measurements[].expr values."""
    stem = f"matched_iip3_{V.iip3_amp_label(amp)}"
    cdir = path.parent / "set" / stem / klt_corner_dirname(label, temp, vdd)
    cdir.mkdir(parents=True, exist_ok=True)
    log = cdir / "ngspice.log"
    synth_log(log)
    corner = {
        "corner_id": f"{label}/{vdd:.3f}V/{temp}C",
        "process": {"name": label},
        "supply_v": {"vdd": vdd},
        "temperature_c": temp,
        "status": "pass",
        "measurements": [{"name": k, "value": v} for k, v in fft.items()],
        "artifacts": {"log": str(log), "deck": str(cdir / "corner.cir")},
    }
    path.write_text(json.dumps({"corners": [corner], "status": "pass"}, indent=1) + "\n")
    return path


def klt_corner_dirname(label, temp, vdd):
    """klt's corner directory naming: typ_1p800V_27C / bcs_1p620V_n40C."""
    vv = ("%0.3f" % vdd).replace(".", "p")
    tt = f"{temp}C" if temp >= 0 else f"n{abs(temp)}C"
    return f"{label}_{vv}V_{tt}"


def reroot_report_logs(root):
    """Rewrite every report's artifacts.log into the shape the committed klt
    reports carry: an absolute path into the (since-reaped) submitting
    worktree, embedding corners/<record-id>/ ahead of the committed-layout
    suffix -- dead on any later replay, exercising the reducer's re-rooting."""
    for rp in sorted(root.glob("matched_iip3_*.report.json")):
        doc = json.loads(rp.read_text())
        for c in doc["corners"]:
            log = (c.get("artifacts") or {}).get("log")
            if not log:
                continue
            suffix = Path(log).relative_to(root / "set")
            c["artifacts"]["log"] = str(
                Path("/gone/.loom/worktrees/issue-337/sim/lna-characterization/corners")
                / root.name / "set" / suffix)
        rp.write_text(json.dumps(doc, indent=1) + "\n")


def fft_values(tone=0.01023, im3=2.0e-9):
    v = {"fft_df": V.IIP3_DF, "tone1": tone, "tone2": tone * 1.0005,
         "im3l": im3, "im3h": im3 * 1.005,
         "im5l": 7.13e-11, "im5h": 7.36e-11,
         "src1": 0.001999, "src2": 0.001998}
    return v


class Iip3Generation(unittest.TestCase):
    def test_amp_label(self):
        self.assertEqual(V.iip3_amp_label(2e-3), "a2mv")
        self.assertEqual(V.iip3_amp_label(1e-3), "a1mv")
        self.assertEqual(V.iip3_amp_label(5e-4), "a0p5mv")
        self.assertEqual(V.iip3_amp_label(8e-3), "a8mv")

    def test_protocol_constants_are_the_ratified_ones(self):
        # spec/target-spec.md IIP3 row (and the AC): f1/f2/spacing and the
        # FFT parameters are pinned exactly; the template stays the source.
        self.assertEqual(V.IIP3_TSTEP, 4e-12)
        self.assertEqual(V.IIP3_NFFT, 65536)
        self.assertEqual(V.IIP3_TSTART, 1e-6)
        self.assertAlmostEqual(V.IIP3_DF, 3814697.265625, places=6)
        self.assertEqual(V.IIP3_F1, 2441406250.0)
        self.assertEqual(V.IIP3_F2, 2449035644.53125)
        self.assertEqual(V.IIP3_FSPACE, 7629394.53125)
        self.assertAlmostEqual(V.IIP3_TSTOP, 1.26214e-6, places=12)
        self.assertEqual((V.IIP3_B1, V.IIP3_B2, V.IIP3_BIM3L, V.IIP3_BIM3H,
                          V.IIP3_BIM5L, V.IIP3_BIM5H), (640, 642, 638, 644, 636, 646))
        self.assertEqual(V.IIP3_AMPS_GRID, (1e-3, 2e-3))
        self.assertEqual(V.IIP3_AMPS_NOMINAL_ONLY, (5e-4, 4e-3, 8e-3))

    def test_control_kind_reproduces_the_template_sequence(self):
        k = V.iip3_control_kind().split("\n")
        self.assertEqual(k[0], "set specwindow = none")
        self.assertIn("op", k)
        self.assertIn(f"tran {V.IIP3_TSTEP:g} {V.IIP3_TSTOP:.11g} {V.IIP3_TSTART:g} {V.IIP3_TSTEP:g}", k)
        self.assertIn("linearize v(rfout) v(vin)", k)
        self.assertIn("fft v(rfout) v(vin)", k)
        echoes = [ln for ln in k if ln.startswith("echo ")]
        self.assertEqual(len(echoes), 3)  # OP, NPTS and DFT echoes
        self.assertIn('echo "OP ic1 $&ic1 ic2 $&ic2 vce1 $&vce1 vce2 $&vce2 idd $&idd"', echoes)
        self.assertIn('echo "DFT tone1 $&d1 tone2 $&d2 im3l $&d3 im3h $&d4 src1 $&ds"', echoes)
        self.assertIn('echo "NPTS $&npts"', echoes)
        # no newline issues: every line is non-empty
        self.assertTrue(all(ln.strip() for ln in k))

    def test_measurements_are_the_fft_bins(self):
        m = {x["name"]: x["expr"] for x in V.iip3_measurements()}
        self.assertEqual(m["tone1"], "mag(v(rfout))[640]")
        self.assertEqual(m["tone2"], "mag(v(rfout))[642]")
        self.assertEqual(m["im3l"], "mag(v(rfout))[638]")
        self.assertEqual(m["im3h"], "mag(v(rfout))[644]")
        self.assertEqual(m["im5l"], "mag(v(rfout))[636]")
        self.assertEqual(m["im5h"], "mag(v(rfout))[646]")
        self.assertEqual(m["src1"], "mag(v(vin))[640]")
        self.assertEqual(m["src2"], "mag(v(vin))[642]")
        self.assertEqual(m["fft_df"], "frequency[1] - frequency[0]")

    def test_request_grids_and_sharding(self):
        full = V.iip3_request("matched", 2e-3, "m.spice", False, "")
        n_full = (len(full["corners"]["process"]) * len(full["corners"]["supply_v"]["vdd"])
                  * len(full["corners"]["temperature_c"]))
        self.assertEqual(n_full, 45)
        self.assertEqual(full["remote"]["hosts"], 15)  # 45 units / 3 per job
        self.assertEqual(full["options"]["timeout_s"], 900)
        self.assertEqual(full["options"]["ngspice_init"], ["set numdgt=8"])
        self.assertTrue(full["options"]["osdi_preload"])
        nom = V.iip3_request("matched", 8e-3, "m.spice", False, "", nominal_only=True)
        n_nom = (len(nom["corners"]["process"]) * len(nom["corners"]["supply_v"]["vdd"])
                 * len(nom["corners"]["temperature_c"]))
        self.assertEqual(n_nom, 1)
        self.assertEqual(nom["corners"]["process"][0]["name"], "typ")
        self.assertEqual(nom["remote"]["hosts"], 1)
        smoke = V.iip3_request("matched", 1e-3, "m.spice", True, "")
        n_smoke = (len(smoke["corners"]["process"]) * len(smoke["corners"]["supply_v"]["vdd"])
                   * len(smoke["corners"]["temperature_c"]))
        self.assertEqual(n_smoke, 1)

    def test_gen_iip3_writes_the_full_set(self):
        with tempfile.TemporaryDirectory() as d:
            a = argparse.Namespace(outdir=d, variants="matched", amps="0.001,0.002",
                                   amps_nominal_only="0.0005,0.004,0.008", op=True,
                                   smoke=False, backend="", temps="")
            V.cmd_gen_iip3(a)
            names = sorted(p.name for p in Path(d).iterdir())
            for stem in ("matched_op", "matched_iip3_a1mv", "matched_iip3_a2mv",
                         "matched_iip3_a0p5mv", "matched_iip3_a4mv", "matched_iip3_a8mv"):
                self.assertIn(f"{stem}.spice", names)
                self.assertIn(f"{stem}.request.json", names)
            req = json.loads((Path(d) / "matched_iip3_a8mv.request.json").read_text())
            self.assertEqual(len(req["corners"]["process"]), 1)  # nominal cell only
            req2 = json.loads((Path(d) / "matched_iip3_a2mv.request.json").read_text())
            self.assertEqual(len(req2["corners"]["process"]), 5)  # full grid

    def test_gen_iip3_rejects_a_level_declared_twice(self):
        with tempfile.TemporaryDirectory() as d:
            a = argparse.Namespace(outdir=d, variants="matched", amps="0.001,0.002",
                                   amps_nominal_only="0.002", op=False,
                                   smoke=False, backend="", temps="")
            with self.assertRaises(SystemExit):
                V.cmd_gen_iip3(a)

    def test_gen_iip3_without_extras(self):
        with tempfile.TemporaryDirectory() as d:
            a = argparse.Namespace(outdir=d, variants="matched", amps="0.001,0.002",
                                   amps_nominal_only="", op=False,
                                   smoke=False, backend="", temps="")
            V.cmd_gen_iip3(a)
            names = sorted(p.name for p in Path(d).iterdir())
            self.assertEqual(names, ["matched_iip3_a1mv.request.json", "matched_iip3_a1mv.spice",
                                     "matched_iip3_a2mv.request.json", "matched_iip3_a2mv.spice"])


class Iip3Reduction(unittest.TestCase):
    def run_reduce(self, cells, amps="0.001,0.002", extras="", s11=None,
                   op=True, extra_report=None, grid=V.GRID_SMOKE,
                   reroot_logs=False):
        """cells: {(label, temp, vdd): {"a1": (tone, im3), "a2": (tone, im3)}};
        a missing level key makes that point genuinely missing. With
        reroot_logs=True the reports' artifacts.log paths are rewritten into
        the dead absolute-worktree shape the committed klt reports carry."""
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            for key, lv in cells.items():
                for tag, amp in (("a1", 1e-3), ("a2", 2e-3)):
                    if tag not in lv:
                        continue
                    tone, im3 = lv[tag]
                    synth_report(root / f"matched_iip3_{tag}mv.report.json",
                                 key[0], key[1], key[2], amp, fft_values(tone, im3))
            if extra_report:
                synth_report(root / extra_report, "typ", 27, 1.8, 4e-3, fft_values())
            if reroot_logs:
                reroot_report_logs(root)
            op_path = ""
            if op:
                op_cells = []
                for (label, temp, vdd) in cells:
                    op_cells.append({
                        "corner_id": f"{label}/{vdd:.3f}V/{temp}C",
                        "process": {"name": label}, "supply_v": {"vdd": vdd},
                        "temperature_c": temp, "status": "pass",
                        "measurements": [{"name": n, "value": 0.00394}
                                         for n, _e, _u in V.OP_MEASUREMENTS],
                        "artifacts": {},
                    })
                (root / "matched_op.report.json").write_text(
                    json.dumps({"corners": op_cells, "status": "pass"}, indent=1) + "\n")
                op_path = str(root / "matched_op.report.json")
            s11_path = ""
            if s11:
                p = root / "s11.csv"
                p.write_text("variant,corner_label,temp_c,vdd_v,s11_db_mid\n" + "".join(
                    f"matched,{k[0]},{k[1]},{k[2]:.2f},{v}\n" for k, v in s11.items()) + "\n")
                s11_path = str(p)
            out = root / "iip3.csv"
            summ = root / "summary.csv"
            head = root / "h.md"
            a = argparse.Namespace(corners_dir=d, iip3_csv=str(out),
                                   summary_csv=str(summ), headlines_md=str(head),
                                   variant="matched", amps=amps,
                                   amps_nominal_only=extras, op_report=op_path,
                                   s11_csv=s11_path,
                                   slope_tol=_sweep.IIP3_SLOPE_TOL,
                                   grid=grid, temps="")
            rc = V.cmd_summarize_iip3(a)
            rows = list(csv.DictReader(open(out)))
            srows = list(csv.DictReader(open(summ)))
            return rc, rows, srows, head.read_text()

    def test_nominal_cell_valid_and_arithmetic_matches_the_definition(self):
        tone, im3 = 0.01023, 2.0e-9
        rc, rows, srows, md = self.run_reduce({("typ", 27, 1.80): {"a1": (tone / 2, im3 / 8), "a2": (tone, im3)}},
                                              s11={("typ", 27, 1.80): -12.0})
        self.assertEqual(rc, 0)
        self.assertEqual(len(rows), 2)
        r2 = next(r for r in rows if r["point_id"].endswith("a2mv"))
        pin = _sweep.avail_power_dbm(2e-3)
        t_out = (float(r2["v_tone1_out_v"]) + float(r2["v_tone2_out_v"])) / 2
        i_out = (float(r2["v_im3l_out_v"]) + float(r2["v_im3h_out_v"])) / 2
        pout = _sweep.out_power_dbm(t_out)
        pim3 = _sweep.out_power_dbm(i_out)
        self.assertAlmostEqual(float(r2["iip3_dbm"]), pin + (pout - pim3) / 2, places=3)
        self.assertAlmostEqual(float(r2["pin_avail_dbm_per_tone"]), -50.0, places=3)
        self.assertAlmostEqual(float(r2["gain_db"]), pout - pin, places=3)
        # 8x amplitude per 2x drive is the exact 3:1 slope
        s = srows[0]
        self.assertEqual(s["iip3_validity"], "valid")
        self.assertAlmostEqual(float(s["im3_slope_2pt"]), 3.0, places=3)
        self.assertIn("The 3:1 IM3 slope assumption holds at every cell", md)
        term = V.iip3_mismatch_term_db(-12.0)
        self.assertAlmostEqual(float(s["iip3_mismatch_term_db"]), term, places=4)
        self.assertAlmostEqual(float(s["iip3_device_plane_dbm_a2mv"]),
                               float(s["iip3_dbm_a2mv"]) - term, places=4)
        self.assertIn("Draft > 0 dBm value", md)
        self.assertIn("stays DRAFT", md)

    def test_dead_recorded_log_path_reroots_onto_corners_dir(self):
        # The committed klt reports record artifacts.log as an absolute path
        # into the submitting worktree, reaped long since; the replay must
        # still reduce every point by re-rooting the suffix after
        # corners/<record-id>/ onto --corners-dir (the committed layout)
        # instead of taking the missing_log_echoes branch.
        tone, im3 = 0.01023, 2.0e-9
        rc, rows, srows, md = self.run_reduce(
            {("typ", 27, 1.80): {"a1": (tone / 2, im3 / 8), "a2": (tone, im3)}},
            s11={("typ", 27, 1.80): -12.0}, reroot_logs=True)
        self.assertEqual(rc, 0)
        self.assertEqual(len(rows), 2)
        self.assertEqual(srows[0]["iip3_validity"], "valid")
        self.assertIn("The 3:1 IM3 slope assumption holds at every cell", md)
        self.assertNotIn("missing_log_echoes", md)

    def test_log_unreachable_everywhere_still_fails_loudly(self):
        # Neither the recorded absolute path nor the committed-layout re-root
        # finds the log: the point must still fail as missing_log_echoes -- a
        # genuinely missing log never silently reduces.
        tone, im3 = 0.01023, 2.0e-9
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            for tag, amp, t, i3 in (("a1", 1e-3, tone / 2, im3 / 8),
                                    ("a2", 2e-3, tone, im3)):
                synth_report(root / f"matched_iip3_{tag}mv.report.json",
                             "typ", 27, 1.8, amp, fft_values(t, i3))
            reroot_report_logs(root)
            (root / "set" / "matched_iip3_a2mv" / klt_corner_dirname("typ", 27, 1.8)
             / "ngspice.log").unlink()
            out = root / "iip3.csv"
            a = argparse.Namespace(corners_dir=d, iip3_csv=str(out),
                                   summary_csv=str(root / "s.csv"),
                                   headlines_md=str(root / "h.md"),
                                   variant="matched", amps="0.001,0.002",
                                   amps_nominal_only="", op_report="",
                                   s11_csv="", slope_tol=0.15,
                                   grid=V.GRID_SMOKE, temps="")
            rc = V.cmd_summarize_iip3(a)
            self.assertEqual(rc, 2)
            md = (root / "h.md").read_text()
            self.assertIn("missing_log_echoes", md)
            # the healthy a1mv point still reduces; only the dead one is dropped
            rows = list(csv.DictReader(open(out)))
            self.assertEqual(len(rows), 1)
            self.assertTrue(rows[0]["point_id"].endswith("a1mv"))

    def test_invalid_slope_gets_no_intercept_but_raw_rows_survive(self):
        # 2x amplitude per 2x drive = slope 1: the cell is invalid. Validity is
        # measurement policy, distinct from point coverage (README), so the
        # reduce still exits 0 -- the headlines just refuse the intercept.
        tone, im3 = 0.01023, 2.0e-9
        rc, rows, srows, md = self.run_reduce({("typ", 27, 1.80): {"a1": (tone / 2, im3 / 2), "a2": (tone, im3)}})
        self.assertEqual(rc, 0)
        self.assertEqual(srows[0]["iip3_validity"], "invalid")
        self.assertIn("outside 3 +/-", md)
        self.assertIn("no intercept accepted", md)
        self.assertIn("**No intercept accepted**: zero cells passed the slope check.", md)
        self.assertNotIn("slope assumption holds at every cell", md)
        # raw per-point iip3 values are still in the IIP3 CSV
        self.assertEqual(len(rows), 2)
        self.assertTrue(all(r["iip3_dbm"] for r in rows))

    def test_missing_drive_level_is_unknown_and_fails_coverage(self):
        tone, im3 = 0.01023, 2.0e-9
        rc, _rows, srows, md = self.run_reduce({("typ", 27, 1.80): {"a2": (tone, im3)}})
        self.assertEqual(rc, 2)
        self.assertEqual(srows[0]["iip3_validity"], "unknown")
        self.assertIn("missing_report", md)  # the a1mv report never appeared

    def test_grid_incompleteness_fails_and_extra_report_is_flagged(self):
        cells = {("typ", 27, 1.80): {"a1": (0.01, 2e-9), "a2": (0.01023, 2.0e-9)}}
        rc, _r, _s, md = self.run_reduce(cells, extra_report="matched_iip3_a4mv.report.json",
                                         grid=V.GRID_FULL)
        self.assertEqual(rc, 2)
        self.assertIn("missing_cell", md)   # 44 cells of the box absent
        self.assertIn("unexpected_report", md)

    def test_nonfinite_bin_fails_the_cell(self):
        # a1mv healthy (so rows exist and CSVs are still written), a2mv's IM3L
        # bin non-finite: the cell gets no a2 intercept, coverage fails, and
        # the issue is named in the headlines.
        tone, im3 = 0.01023, 2.0e-9
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            stem = "matched_iip3_a1mv"
            cdir = root / "set" / stem / klt_corner_dirname("typ", 27, 1.8)
            cdir.mkdir(parents=True)
            synth_log(cdir / "ngspice.log")
            (root / f"{stem}.report.json").write_text(json.dumps({"corners": [{
                "corner_id": "typ/1.800V/27C", "process": {"name": "typ"},
                "supply_v": {"vdd": 1.8}, "temperature_c": 27, "status": "pass",
                "measurements": [{"name": k, "value": v}
                                 for k, v in fft_values(tone / 2, im3 / 8).items()],
                "artifacts": {"log": str(cdir / "ngspice.log")}}]}))
            stem = "matched_iip3_a2mv"
            cdir = root / "set" / stem / klt_corner_dirname("typ", 27, 1.8)
            cdir.mkdir(parents=True)
            synth_log(cdir / "ngspice.log")
            vals = fft_values(tone, im3)
            vals["im3l"] = None
            (root / f"{stem}.report.json").write_text(json.dumps({"corners": [{
                "corner_id": "typ/1.800V/27C", "process": {"name": "typ"},
                "supply_v": {"vdd": 1.8}, "temperature_c": 27, "status": "pass",
                "measurements": [{"name": k, "value": v} for k, v in vals.items()],
                "artifacts": {"log": str(cdir / "ngspice.log")}}]}))
            a = argparse.Namespace(corners_dir=d, iip3_csv=str(root / "o.csv"),
                                   summary_csv=str(root / "s.csv"),
                                   headlines_md=str(root / "h.md"),
                                   variant="matched", amps="0.001,0.002",
                                   amps_nominal_only="", op_report="",
                                   s11_csv="", slope_tol=0.15,
                                   grid=V.GRID_SMOKE, temps="")
            rc = V.cmd_summarize_iip3(a)
            self.assertEqual(rc, 2)
            self.assertIn("non-finite or absent FFT bins", (root / "h.md").read_text())

    def test_incoherent_fft_df_fails_the_cell(self):
        tone, im3 = 0.01023, 2.0e-9
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            stem = "matched_iip3_a1mv"
            cdir = root / "set" / stem / klt_corner_dirname("typ", 27, 1.8)
            cdir.mkdir(parents=True)
            synth_log(cdir / "ngspice.log")
            (root / f"{stem}.report.json").write_text(json.dumps({"corners": [{
                "corner_id": "typ/1.800V/27C", "process": {"name": "typ"},
                "supply_v": {"vdd": 1.8}, "temperature_c": 27, "status": "pass",
                "measurements": [{"name": k, "value": v}
                                 for k, v in fft_values(tone / 2, im3 / 8).items()],
                "artifacts": {"log": str(cdir / "ngspice.log")}}]}))
            stem = "matched_iip3_a2mv"
            cdir = root / "set" / stem / klt_corner_dirname("typ", 27, 1.8)
            cdir.mkdir(parents=True)
            synth_log(cdir / "ngspice.log")
            vals = fft_values(tone, im3)
            vals["fft_df"] = V.IIP3_DF * 2  # zero-padded / incoherent grid
            (root / f"{stem}.report.json").write_text(json.dumps({"corners": [{
                "corner_id": "typ/1.800V/27C", "process": {"name": "typ"},
                "supply_v": {"vdd": 1.8}, "temperature_c": 27, "status": "pass",
                "measurements": [{"name": k, "value": v} for k, v in vals.items()],
                "artifacts": {"log": str(cdir / "ngspice.log")}}]}))
            a = argparse.Namespace(corners_dir=d, iip3_csv=str(root / "o.csv"),
                                   summary_csv=str(root / "s.csv"),
                                   headlines_md=str(root / "h.md"),
                                   variant="matched", amps="0.001,0.002",
                                   amps_nominal_only="", op_report="",
                                   s11_csv="", slope_tol=0.15,
                                   grid=V.GRID_SMOKE, temps="")
            rc = V.cmd_summarize_iip3(a)
            self.assertEqual(rc, 2)
            self.assertIn("incoherent_fft_df", (root / "h.md").read_text())

    def test_mismatch_term_formula(self):
        # |S11| = 10^(-12/20): term = -10*log10(1 - |S11|^2)
        t = V.iip3_mismatch_term_db(-12.0)
        self.assertAlmostEqual(t, -10 * math.log10(1 - (10 ** (-12 / 20)) ** 2), places=9)
        # historical anchors: the unmatched 0.933 DUT inflated by ~8.9 dB,
        # the matched DUT sits near 0.3 dB (README "IIP3 mismatch-inflation")
        self.assertAlmostEqual(V.iip3_mismatch_term_db(-0.60), 8.9, places=1)
        self.assertLess(V.iip3_mismatch_term_db(-11.0), 0.5)
        with self.assertRaises(ValueError):
            V.iip3_mismatch_term_db(0.0)   # |S11| = 1: no delivered power

    def test_op_and_bias_join_lands_in_the_summary(self):
        rc, _rows, srows, _md = self.run_reduce(
            {("typ", 27, 1.80): {"a1": (0.005, 2.5e-10), "a2": (0.01023, 2.0e-9)}},
            s11={("typ", 27, 1.80): -12.0})
        self.assertEqual(rc, 0)
        s = srows[0]
        self.assertEqual(s["ic1"], "0.00394")
        self.assertEqual(s["pdc"], "0.00394")
        self.assertTrue(s["iip3_device_plane_dbm_a2mv"])


if __name__ == "__main__":
    unittest.main()
