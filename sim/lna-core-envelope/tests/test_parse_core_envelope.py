"""Unit tests for parse_core_envelope.py against a trimmed wrdata fixture (#104).

Stdlib only, headless, no ngspice, no PDK. The fixture under fixtures/ is one
corner (point p001) with 2 in-band and 3 broadband frequency points; the
expected values are hand-computed from it (see comments), not read back from
the parser. Nothing here writes under sim/.

Two layers, deliberately:

* **CLI/end-to-end** (the classes using `run_parser`): the parser runs as a
  subprocess writing into a temp dir. These cover exit codes, exclusive
  publication and the published artifacts -- contracts that only exist at the
  process boundary.
* **Unit-level** (the `*Unit` classes, #276): the parser's stage functions are
  imported and called directly. These cover the three load-bearing behaviours
  the parser's own docstring names -- the T0 = 290 K NF re-reference, the
  Q-parameterized available-gain envelope, and stability counts taken from raw
  rather than rounded points -- including cases a fixture campaign on disk
  cannot reach, such as a mu that rounds to `1.00000000` while still being
  below 1.

Any invented number below is labeled synthetic where it appears; synthetic
values are test inputs, never evidence.

Run: python3 -I -m unittest discover -s sim/lna-core-envelope/tests
"""

import csv
import importlib.util
import math
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
PARSER = HERE.parent / "parse_core_envelope.py"
FIX = HERE / "fixtures"

# Import the parser for the unit-level layer (#276). Before that issue its
# whole body was one 404-line main() and this import bought nothing.
_spec = importlib.util.spec_from_file_location("parse_core_envelope", PARSER)
pce = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(pce)

# The fixture's manifest line, as manifest_points() yields it.
P001 = ("p001", "s_ctrl_a8", "ctrl", "2stage", "1", "1", "1", "1", "8", "2",
        "typ", "26.85", "1.8")


class ParserCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(self._tmp.name)
        self.corners = self.tmp / "corners"
        self.corners.mkdir()
        self.records = self.tmp / "records"
        self.records.mkdir()
        shutil.copy(FIX / "corners" / "p001.log.txt", self.corners / "p001.log")
        for ext in ("inband.dat", "stability.dat"):
            shutil.copy(FIX / "corners" / f"p001.{ext}", self.corners / f"p001.{ext}")
        self.manifest = self.tmp / "manifest.txt"
        shutil.copy(FIX / "manifest.txt", self.manifest)

    def run_parser(self, *extra):
        return subprocess.run(
            [sys.executable, "-I", str(PARSER), "--record-id", "rec",
             "--corners-dir", str(self.corners), "--records-dir", str(self.records),
             "--manifest", str(self.manifest), *extra],
            capture_output=True, text=True)

    def rows(self):
        with open(self.records / "rec.csv", newline="") as fh:
            return list(csv.DictReader(fh))


class EndToEnd(ParserCase):
    def test_csv_row(self):
        p = self.run_parser()
        self.assertEqual(p.returncode, 0, p.stderr)
        rows = self.rows()
        self.assertEqual(len(rows), 1)
        r = rows[0]
        exp = {
            "point_id": "p001", "variant": "s_ctrl_a8", "topology": "2stage",
            "emitter_units_stage1": "8",
            "emitter_area_um2_stage1": "0.9216",       # 8 * 0.1152
            "ic1_a": "2.000000e-03", "pdc_w": "7.200000e-03",
            "jc1_ma_um2": "2.1701",                    # 2e-3/0.9216 mA/um^2 *1e3
            "pdc_violates_10mw": "0", "ic1_violates_4p5ma": "0",
            # |S| dB: s11 -20 / -13.9794, s21 20 / 13.9794, s12 -60 / -40,
            # s22 -6.0206 / -4.4370
            "s11_db_worst": "-13.9794", "s21_db_min": "13.9794",
            "s21_db_max": "20.0", "s12_db_max": "-40.0",
            "s22_db_worst": "-4.437",
            # 20log|s21| - 10log(1-|s11|^2): 20.0436 / 14.1567
            "gain_in_match_basis_db_min": "14.1567",
            # basis minus 10log(1-|s22|^2): 21.2930 / 16.0949
            "ga_max_ideal_db_min": "16.0949",
            # nf/nfmin from the table, then F-1 scaled by 300/290 (T_a = 26.85 C)
            "nf_sp_db_at_band_lo": "3.0", "nfmin_sp_db_at_band_lo": "1.0",
            "nfmin290_db_at_band_lo": "1.0307", "nfmin290_db_worst": "1.236",
            "nfmin_reref_delta_db": "0.0307",
            "nf290_db_at_band_lo": "2.0", "nf290_db_worst": "2.5",
            "nf30015_db_at_band_lo": "2.1", "gain_ac_db_at_band_lo": "18.0",
            "k_inband_min": "1.1", "mu_inband_min": "0.9999",
            "n_inband_pts_mu_lt_1": "1", "n_inband_pts": "2",
            "mag_delta_inband_max": "0.02",
            "k_broadband_min": "1.3", "mu_broadband_min": "0.99",
            "f_at_mu_broadband_min_hz": "1.000000e+10",
            "n_broadband_pts_mu_lt_1": "1",  # mu == 1.0 exactly is not < 1
            "n_broadband_pts": "3",
            "s11_mag_broadband_max": "0.7", "s22_mag_broadband_max": "1.0",
            "model_card_flags": "in_box",
        }
        for k, v in exp.items():
            self.assertEqual(r[k], v, k)
        # Q=10 gain is the ideal figure degraded by the tank loss.
        self.assertLess(float(r["ga_max_q10_db_min"]),
                        float(r["ga_max_ideal_db_min"]))

    def test_summary_and_record(self):
        self.assertEqual(self.run_parser().returncode, 0)
        with open(self.records / "rec-variant-summary.csv", newline="") as fh:
            s = list(csv.DictReader(fh))
        self.assertEqual(len(s), 1)
        self.assertEqual(s[0]["geom"], "1x1 + 1x1")
        self.assertEqual(s[0]["mu_ib_viol"], "1")
        self.assertEqual(s[0]["mu_bb_viol"], "1")
        self.assertEqual(s[0]["mu_bb_pts_lt_1"], "1")
        self.assertEqual(s[0]["mu_bb_pts"], "3")
        self.assertTrue((self.records / "rec.md").read_text().startswith("# Record rec"))

    def test_out_of_box_flag(self):
        log = self.corners / "p001.log"
        log.write_text(log.read_text().replace("vbe1 0.85", "vbe1 0.50"))
        self.assertEqual(self.run_parser().returncode, 0)
        self.assertEqual(self.rows()[0]["model_card_flags"],
                         "vbe1=0.5000_outside_0.65-0.96")


class ExclusivePublication(ParserCase):
    """Issue #126: published summaries are never overwritten."""

    def test_existing_output_refused_and_untouched(self):
        for name in ("rec.csv", "rec-variant-summary.csv", "rec.md"):
            with self.subTest(existing=name):
                for f in self.records.iterdir():
                    f.unlink()
                (self.records / name).write_text("evidence\n")
                r = self.run_parser()
                self.assertEqual(r.returncode, 4)
                self.assertIn("CORE_ENV_PUBLICATION_EXISTS", r.stderr)
                self.assertEqual([p.name for p in self.records.iterdir()], [name])
                self.assertEqual((self.records / name).read_text(), "evidence\n")

    def test_second_run_does_not_rewrite(self):
        self.assertEqual(self.run_parser().returncode, 0)
        before = {p.name: p.read_bytes() for p in self.records.iterdir()}
        self.assertEqual(set(before), {"rec.csv", "rec-variant-summary.csv", "rec.md"})
        self.assertEqual(self.run_parser().returncode, 4)
        self.assertEqual({p.name: p.read_bytes() for p in self.records.iterdir()}, before)

    def test_provenance_cited(self):
        r = subprocess.run(
            [sys.executable, "-I", str(PARSER), "--record-id", "rec",
             "--corners-dir", str(self.corners), "--records-dir", str(self.records),
             "--manifest", str(self.manifest), "--pdk-release", "0.3.0",
             "--pdk-provenance", "records/rec.pdk-provenance.json"],
            capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        md = (self.records / "rec.md").read_text()
        self.assertIn("verified installed release `0.3.0`", md)
        self.assertIn("records/rec.pdk-provenance.json", md)


class Malformed(ParserCase):
    def assert_fails(self, reason):
        p = self.run_parser()
        self.assertEqual(p.returncode, 1)
        self.assertIn("no parsable points", p.stderr)
        self.assertFalse((self.records / "rec.csv").exists())
        return reason

    def test_missing_output(self):
        (self.corners / "p001.stability.dat").unlink()
        self.assert_fails("missing output")

    def test_truncated_log_no_bench_complete(self):
        log = self.corners / "p001.log"
        log.write_text(log.read_text().replace("BENCH_COMPLETE\n", ""))
        self.assert_fails("no BENCH_COMPLETE")

    def test_no_op_line(self):
        log = self.corners / "p001.log"
        log.write_text("BENCH_COMPLETE\n")
        self.assert_fails("no OP line")

    def test_empty_table(self):
        (self.corners / "p001.inband.dat").write_text("\n")
        self.assert_fails("empty table")

    def test_failed_point_is_skipped_not_fatal(self):
        # A second manifest point with no outputs fails; p001 still parses.
        with open(self.manifest, "a") as fh:
            fh.write("p002|s_ctrl_a8|ctrl|2stage|1|1|1|1|8|2|typ|26.85|1.8\n")
        p = self.run_parser()
        self.assertEqual(p.returncode, 0)
        self.assertIn("1 failed points", p.stderr)
        self.assertEqual(len(self.rows()), 1)
        self.assertIn("p002", (self.records / "rec.md").read_text())

    def test_require_all_points_fails_before_publishing(self):
        # Strict mode (#128): the same partial campaign publishes nothing.
        with open(self.manifest, "a") as fh:
            fh.write("p002|s_ctrl_a8|ctrl|2stage|1|1|1|1|8|2|typ|26.85|1.8\n")
        p = self.run_parser("--require-all-points")
        self.assertEqual(p.returncode, 5, p.stderr)
        self.assertIn("p002", p.stderr)
        self.assertEqual(list(self.records.iterdir()), [])

    def test_require_all_points_complete_campaign_publishes(self):
        p = self.run_parser("--require-all-points")
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual(len(self.rows()), 1)

    def test_truncated_table_row_raises(self):
        # Row cut mid-line: parse_table slices short and the parser must not
        # silently emit a CSV from it.
        dat = self.corners / "p001.inband.dat"
        dat.write_text(dat.read_text().splitlines()[0][:60] + "\n")
        p = self.run_parser()
        self.assertNotEqual(p.returncode, 0)
        self.assertFalse((self.records / "rec.csv").exists())

    def test_non_numeric_table_raises(self):
        dat = self.corners / "p001.stability.dat"
        dat.write_text("1e7 nan_x 1e7\n")
        p = self.run_parser()
        self.assertNotEqual(p.returncode, 0)
        self.assertFalse((self.records / "rec.csv").exists())

    def _assert_invalid_point(self, frag):
        p = self.run_parser()
        self.assertEqual(p.returncode, 1)
        self.assertIn("no parsable points", p.stderr)
        self.assertFalse((self.records / "rec.csv").exists())
        self.assertNotIn("Traceback", p.stderr)
        self.assertIn("failed point p001: invalid table", p.stderr)
        self.assertIn(frag, p.stderr)
        return p

    def test_broadband_nan_mu_is_invalid_not_nonviolating(self):
        dat = self.corners / "p001.stability.dat"
        lines = dat.read_text().splitlines()
        toks = lines[1].split()
        toks[3] = "nan"  # mu column
        lines[1] = " ".join(toks)
        dat.write_text("\n".join(lines) + "\n")
        self._assert_invalid_point("non-finite")

    def test_surplus_column_is_invalid(self):
        dat = self.corners / "p001.stability.dat"
        lines = dat.read_text().splitlines()
        lines[0] += " 1.0"
        dat.write_text("\n".join(lines) + "\n")
        self._assert_invalid_point("columns")

    def test_invalid_point_is_skipped_with_diagnostic(self):
        with open(self.manifest, "a") as fh:
            fh.write("p002|s_ctrl_a8|ctrl|2stage|1|1|1|1|8|2|typ|26.85|1.8\n")
        for ext in ("log", "inband.dat", "stability.dat"):
            src = self.corners / (f"p001.{ext}")
            shutil.copy(src, self.corners / f"p002.{ext}")
        dat = self.corners / "p002.stability.dat"
        dat.write_text(dat.read_text().replace("0.99", "inf"))
        p = self.run_parser()
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual(len(self.rows()), 1)
        md = (self.records / "rec.md").read_text()
        self.assertIn("p002", md)
        self.assertIn("invalid table", md)

    def test_finite_instability_remains_measured_violation(self):
        # Fixture broadband mu has 0.99 (<1): finite, so a counted violation.
        self.assertEqual(self.run_parser().returncode, 0)
        self.assertEqual(self.rows()[0]["n_broadband_pts_mu_lt_1"], "1")


class DeclaredGrid(ParserCase):
    """#165: with the campaign's declared grid, a short table is invalid.

    The stability table is rewritten onto a declared `sp dec 1 1e7 1e10` grid
    (4 points: 1e7, 1e8, 1e9, 1e10) reusing the fixture's per-row values; the
    in-band fixture already is `sp lin 2 2.4e9 2.48e9`. p002 is an intact
    copy so the run still publishes and the failed-points list is visible.
    """

    GRID = ["--inband-grid", "2.4e9,2.48e9,2", "--stab-grid", "1e7,1e10,1"]

    def setUp(self):
        super().setUp()
        rows = (FIX / "corners" / "p001.stability.dat").read_text().splitlines()
        vals = [r.split()[1::2] for r in rows] + [rows[0].split()[1::2]]
        lines = [" ".join(f"{f} {v}" for v in vs)
                 for f, vs in zip(("1e7", "1e8", "1e9", "1e10"), vals)]
        (self.corners / "p001.stability.dat").write_text("\n".join(lines) + "\n")
        with open(self.manifest, "a") as fh:
            fh.write("p002|s_ctrl_a8|ctrl|2stage|1|1|1|1|8|2|typ|26.85|1.8\n")
        for ext in ("log", "inband.dat", "stability.dat"):
            shutil.copy(self.corners / f"p001.{ext}", self.corners / f"p002.{ext}")

    def run_grid(self, grid=True):
        return subprocess.run(
            [sys.executable, "-I", str(PARSER), "--record-id", "rec",
             "--corners-dir", str(self.corners), "--records-dir", str(self.records),
             "--manifest", str(self.manifest)] + (self.GRID if grid else []),
            capture_output=True, text=True)

    def drop_row(self, ext, idx):
        dat = self.corners / f"p001.{ext}"
        lines = dat.read_text().splitlines()
        del lines[idx]
        dat.write_text("\n".join(lines) + "\n")

    def assert_p001_invalid(self, frag):
        p = self.run_grid()
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertNotIn("Traceback", p.stderr)
        self.assertEqual([r["point_id"] for r in self.rows()], ["p002"])
        self.assertIn("failed point p001: invalid table", p.stderr)
        self.assertIn(frag, p.stderr)
        md = (self.records / "rec.md").read_text()
        self.assertIn("`p001`: invalid table", md)
        self.assertIn("1 failed", md)

    def test_full_declared_grid_reduces(self):
        p = self.run_grid()
        self.assertEqual(p.returncode, 0, p.stderr)
        rows = self.rows()
        self.assertEqual([r["point_id"] for r in rows], ["p001", "p002"])
        self.assertEqual(rows[0]["n_broadband_pts"], "4")
        self.assertEqual(rows[0]["n_broadband_pts_mu_lt_1"], "1")

    def test_dropped_stability_row_is_invalid_not_reduced(self):
        # Dropping the mu=0.99 row would otherwise undercount the violation.
        self.drop_row("stability.dat", 1)
        self.assert_p001_invalid("requires 4")

    def test_truncated_stability_tail_is_invalid(self):
        self.drop_row("stability.dat", -1)
        self.assert_p001_invalid("p001.stability.dat")

    def test_dropped_inband_row_is_invalid(self):
        self.drop_row("inband.dat", -1)
        self.assert_p001_invalid("declared grid has 2")

    def test_without_grid_args_historical_behaviour(self):
        # No declared grid (historical replay): the short table still reduces.
        self.drop_row("stability.dat", 1)
        p = self.run_grid(grid=False)
        self.assertEqual(p.returncode, 0, p.stderr)
        rows = self.rows()
        self.assertEqual(rows[0]["point_id"], "p001")
        self.assertEqual(rows[0]["n_broadband_pts"], "3")

    def test_malformed_grid_arg_is_usage_error(self):
        self.GRID = ["--stab-grid", "1e10,1e7,1"]
        p = self.run_grid()
        self.assertEqual(p.returncode, 2)
        self.assertIn("0 < LO < HI", p.stderr)
        self.assertFalse((self.records / "rec.csv").exists())


class PointRowUnit(ParserCase):
    """#276: the per-point reduction, called directly instead of via the CLI."""

    def row(self, fields=P001, inband_grid=None, stab_grid=None):
        return pce.point_row(fields, self.corners, inband_grid, stab_grid)

    def at_temp(self, temp_c):
        """The fixture point with only its manifest temp_c field replaced."""
        return P001[:11] + (str(temp_c),) + P001[12:]

    def set_stability(self, lines):
        (self.corners / "p001.stability.dat").write_text("\n".join(lines) + "\n")

    def test_reduces_fixture_point(self):
        r = self.row()
        self.assertEqual(r["point_id"], "p001")
        self.assertEqual(r["variant"], "s_ctrl_a8")
        # Key order IS the published CSV column order.
        self.assertEqual(list(r)[0], "point_id")
        self.assertEqual(list(r)[-1], "model_card_flags")

    # --- docstring behaviour 1: the T0 = 290 K NF re-reference -----------

    def test_nfmin_is_rereferenced_to_290k_not_passed_through(self):
        # Fixture nfmin column is 1.0 / 1.2 dB at temp_c 26.85 -> T_a = 300.0 K.
        r = self.row()
        self.assertEqual(r["nfmin_sp_db_at_band_lo"], 1.0)
        self.assertEqual(r["nfmin290_db_at_band_lo"],
                         round(pce.nf_reref(1.0, 300.0, pce.T0_IEEE), 4))
        # Re-referencing a 300 K figure down to 290 K RAISES it, so the
        # published 290 K column is strictly the larger -- the raw `sp` column
        # is not the quantity spec/target-spec.md's NF row binds.
        self.assertGreater(r["nfmin290_db_at_band_lo"],
                           r["nfmin_sp_db_at_band_lo"])
        self.assertEqual(
            r["nfmin_reref_delta_db"],
            round(r["nfmin290_db_at_band_lo"] - r["nfmin_sp_db_at_band_lo"], 4))

    def test_reref_tracks_analysis_temperature(self):
        # The re-reference is driven by the manifest's temp_c and nothing else:
        # the raw sp column is identical across temperatures, the 290 K one is
        # not. Unreachable through the CLI without rewriting a manifest.
        cold = self.row(self.at_temp(-40))
        hot = self.row(self.at_temp(125))
        self.assertEqual(cold["nfmin_sp_db_at_band_lo"],
                         hot["nfmin_sp_db_at_band_lo"])
        self.assertLess(cold["nfmin290_db_at_band_lo"],
                        hot["nfmin290_db_at_band_lo"])
        # At exactly T0 the re-reference is the identity.
        at_t0 = self.row(self.at_temp(pce.T0_IEEE - 273.15))
        self.assertEqual(at_t0["nfmin290_db_at_band_lo"],
                         at_t0["nfmin_sp_db_at_band_lo"])
        self.assertEqual(at_t0["nfmin_reref_delta_db"], 0.0)

    # --- docstring behaviour 2: the Q-parameterized gain envelope --------

    def test_three_gain_metrics_are_ordered(self):
        # README "Three gain metrics": the raw 50 Ohm measurement is the
        # lowest, +input-match is next, both-ports-ideal is the ceiling, and
        # the finite-Q figure sits strictly below that ceiling.
        r = self.row()
        self.assertLess(r["s21_db_min"], r["gain_in_match_basis_db_min"])
        self.assertLess(r["gain_in_match_basis_db_min"],
                        r["ga_max_ideal_db_min"])
        self.assertLess(r["ga_max_q10_db_min"], r["ga_max_ideal_db_min"])

    def test_gain_in_match_uses_the_named_helper(self):
        # The published column is exactly the shared helper's value, so the
        # two callers of gain_in_match_db cannot drift again (#276 part 1).
        r = self.row()
        ib = pce.parse_table(self.corners / "p001.inband.dat", pce.INBAND_COLS)
        want = min(pce.gain_in_match_db(p["s11"], p["s21"]) for p in ib)
        self.assertEqual(r["gain_in_match_basis_db_min"], round(want, 4))
        # And it is the input-match-only figure: adding the output-match term
        # recovers the both-ports metric.
        worst = min(ib, key=lambda p: pce.gain_in_match_db(p["s11"], p["s21"]))
        self.assertAlmostEqual(
            pce.gain_in_match_db(worst["s11"], worst["s21"])
            - 10 * math.log10(1 - abs(worst["s22"]) ** 2),
            pce.ga_max_db(worst["s11"], worst["s12"], worst["s21"],
                          worst["s22"]),
            places=12)

    # --- docstring behaviour 3: counts from RAW, not rounded, points -----

    def test_mu_counts_come_from_raw_points(self):
        r = self.row()
        # Fixture in-band mu 1.5 / 0.9999; broadband 1.2 / 0.99 / 1.0.
        self.assertEqual(r["n_inband_pts_mu_lt_1"], 1)
        self.assertEqual(r["n_inband_pts"], 2)
        self.assertEqual(r["n_broadband_pts_mu_lt_1"], 1)
        self.assertEqual(r["n_broadband_pts"], 3)

    def test_submicro_mu_dip_rounds_to_one_but_still_counts(self):
        # THE trap the parser's docstring note 3 exists for, and the case no
        # on-disk fixture campaign reached before #276: mu = 1 - 1e-12 prints
        # as 1.00000000 in the rounded column yet IS below 1. Synthetic mu.
        self.set_stability([
            "1e7 1.5 1e7 1.2 1e7 0.01 1e7 0.3 1e7 5 1e7 0.9",
            "1e10 1.4 1e10 0.999999999999 1e10 0.02 1e10 0.7 1e10 4 1e10 1.0",
            "3e10 1.3 3e10 1.0 3e10 0.03 3e10 0.4 3e10 3 3e10 0.8",
        ])
        r = self.row()
        self.assertEqual(r["mu_broadband_min"], 1.0)   # rounded: looks passing
        self.assertEqual(r["n_broadband_pts_mu_lt_1"], 1)  # raw: a violation

    def test_mu_exactly_one_is_not_a_violation(self):
        self.set_stability([
            "1e7 1.5 1e7 1.0 1e7 0.01 1e7 0.3 1e7 5 1e7 0.9",
            "1e10 1.4 1e10 1.0 1e10 0.02 1e10 0.7 1e10 4 1e10 1.0",
        ])
        self.assertEqual(self.row()["n_broadband_pts_mu_lt_1"], 0)

    # --- invalid evidence is raised, never reduced -----------------------

    def test_point_error_reasons(self):
        for ext, frag in (("stability.dat", "missing output"),
                          ("inband.dat", "missing output"),
                          ("log", "missing output")):
            with self.subTest(removed=ext):
                self.setUp()
                (self.corners / f"p001.{ext}").unlink()
                with self.assertRaises(pce.PointError) as cm:
                    self.row()
                self.assertIn(frag, str(cm.exception))

    def test_no_bench_complete_and_no_op_line(self):
        log = self.corners / "p001.log"
        log.write_text(log.read_text().replace("BENCH_COMPLETE\n", ""))
        with self.assertRaises(pce.PointError) as cm:
            self.row()
        self.assertIn("no BENCH_COMPLETE", str(cm.exception))
        log.write_text("BENCH_COMPLETE\n")
        with self.assertRaises(pce.PointError) as cm:
            self.row()
        self.assertIn("no OP line", str(cm.exception))

    def test_invalid_table_is_point_error_not_table_error(self):
        (self.corners / "p001.stability.dat").write_text("1e7 nan 1e7\n")
        with self.assertRaises(pce.PointError) as cm:
            self.row()
        self.assertIn("invalid table", str(cm.exception))

    def test_empty_table_is_point_error(self):
        (self.corners / "p001.inband.dat").write_text("\n")
        with self.assertRaises(pce.PointError) as cm:
            self.row()
        self.assertIn("empty table", str(cm.exception))

    def test_declared_grid_mismatch_is_point_error(self):
        with self.assertRaises(pce.PointError) as cm:
            self.row(inband_grid=(2.4e9, 2.48e9, 11))
        self.assertIn("invalid table", str(cm.exception))

    def test_model_card_flags(self):
        log = self.corners / "p001.log"
        self.assertEqual(self.row()["model_card_flags"], "in_box")
        log.write_text(log.read_text().replace("vbe1 0.85", "vbe1 0.50"))
        self.assertEqual(self.row()["model_card_flags"],
                         "vbe1=0.5000_outside_0.65-0.96")

    def test_reduce_points_separates_rows_from_failures(self):
        rows, failed = pce.reduce_points(self.manifest, self.corners, None, None)
        self.assertEqual([r["point_id"] for r in rows], ["p001"])
        self.assertEqual(failed, [])
        with open(self.manifest, "a") as fh:
            fh.write("p002|s_ctrl_a8|ctrl|2stage|1|1|1|1|8|2|typ|26.85|1.8\n")
        rows, failed = pce.reduce_points(self.manifest, self.corners, None, None)
        self.assertEqual([r["point_id"] for r in rows], ["p001"])
        self.assertEqual(failed, [("p002", "missing output")])


class ControlCheckUnit(unittest.TestCase):
    """#276: the control-variant regression gate, called directly.

    All numbers here are SYNTHETIC test inputs, not measurements.
    """

    COLS = ("corner_label", "temp_c", "vdd_v") + pce.CONTROL_COLS

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(self._tmp.name)

    def reference(self, **bump):
        base = dict(s21_db_min=16.0, s11_db_worst=-12.0,
                    nfmin_sp_db_at_band_lo=1.0, nf290_db_worst=1.2,
                    pdc_w=7.0e-3, ic1_a=3.5e-3)
        base.update(bump)
        path = self.tmp / "ref.csv"
        with open(path, "w", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=list(self.COLS))
            w.writeheader()
            w.writerow(dict(corner_label="typ", temp_c="27", vdd_v="1.80",
                            **base))
        return path

    def rows(self, variant="s_ctrl_a8", **bump):
        base = dict(s21_db_min=16.0, s11_db_worst=-12.0,
                    nfmin_sp_db_at_band_lo=1.0, nf290_db_worst=1.2,
                    pdc_w=7.0e-3, ic1_a=3.5e-3)
        base.update(bump)
        return [dict(variant=variant, corner_label="typ", temp_c="27",
                     vdd_v="1.80", **base)]

    def test_no_reference_summary_is_not_drift(self):
        note, drifted = pce.control_check(self.rows(), None)
        self.assertFalse(drifted)
        self.assertIn("not checked", note)

    def test_exact_match_passes(self):
        note, drifted = pce.control_check(self.rows(), self.reference())
        self.assertFalse(drifted)
        self.assertIn("1 control cells compared", note)
        self.assertIn("0.000e+00", note)

    def test_drift_beyond_tolerance_is_flagged(self):
        note, drifted = pce.control_check(
            self.rows(s21_db_min=16.0 * (1 + 1e-5)), self.reference())
        self.assertTrue(drifted)
        self.assertIn("s21_db_min", note)

    def test_drift_just_under_tolerance_passes(self):
        # The gate is strictly ">" CONTROL_RTOL, so 1e-6 exactly still passes.
        note, drifted = pce.control_check(
            self.rows(s21_db_min=16.0 * (1 + pce.CONTROL_RTOL / 2)),
            self.reference())
        self.assertFalse(drifted)

    def test_non_control_variants_are_ignored(self):
        note, drifted = pce.control_check(
            self.rows(variant="s_fixj_a2", s21_db_min=99.0), self.reference())
        self.assertFalse(drifted)
        self.assertIn("not present in this run", note)

    def test_cell_absent_from_reference_is_skipped(self):
        rows = self.rows()
        rows[0]["vdd_v"] = "1.62"  # no such key in the reference
        note, drifted = pce.control_check(rows, self.reference())
        self.assertFalse(drifted)
        self.assertIn("not present in this run", note)

    def test_every_control_column_is_compared(self):
        for col in pce.CONTROL_COLS:
            with self.subTest(column=col):
                rows = self.rows()
                rows[0][col] = float(rows[0][col]) * (1 + 1e-4)
                _, drifted = pce.control_check(rows, self.reference())
                self.assertTrue(drifted)


class RollupUnit(unittest.TestCase):
    """#276: the per-variant roll-up, called directly. SYNTHETIC inputs."""

    def vrow(self, **over):
        r = {
            "family": "ctrl", "topology": "2stage", "nx1": "1", "m1": "1",
            "nx2": "1", "m2": "1", "xmis_w_um": "2",
            "jc1_ma_um2": 2.0, "ic1_a": "2.0e-03", "pdc_w": "7.2e-03",
            "pdc_violates_10mw": 0, "ic1_violates_4p5ma": 0,
            "s21_db_min": 16.0, "gain_in_match_basis_db_min": 17.0,
            "ga_max_q10_db_min": 18.0, "nfmin290_db_at_band_lo": 1.0,
            "nfmin290_db_worst": 1.2, "nf290_db_worst": 1.3,
            "mu_inband_min": 1.5, "mu_broadband_min": 1.1,
            "n_inband_pts_mu_lt_1": 0, "n_broadband_pts_mu_lt_1": 0,
            "n_broadband_pts": 140, "model_card_flags": "in_box",
        }
        r.update(over)
        return r

    def test_geometry_string_depends_on_topology(self):
        self.assertEqual(pce.rollup([self.vrow()])["geom"], "1x1 + 1x1")
        self.assertEqual(
            pce.rollup([self.vrow(topology="1stage")])["geom"], "1x1")

    def test_violation_counts_use_raw_subunity_counts(self):
        # Docstring note 3 at roll-up level: a cell whose ROUNDED mu minimum
        # prints 1.000000 still counts as violating when its raw sub-unity
        # point count is non-zero. This is the roll-up half of the trap.
        r = pce.rollup([self.vrow(mu_inband_min=1.0, n_inband_pts_mu_lt_1=3,
                                  mu_broadband_min=1.0,
                                  n_broadband_pts_mu_lt_1=7)])
        self.assertEqual(r["mu_ib_lo"], 1.0)
        self.assertEqual(r["mu_bb_lo"], 1.0)
        self.assertEqual(r["mu_ib_viol"], 1)
        self.assertEqual(r["mu_bb_viol"], 1)
        self.assertEqual(r["mu_bb_pts_lt_1"], 7)

    def test_a_cell_counts_once_however_many_points_dip(self):
        r = pce.rollup([self.vrow(n_broadband_pts_mu_lt_1=50),
                        self.vrow(n_broadband_pts_mu_lt_1=0)])
        self.assertEqual(r["n"], 2)
        self.assertEqual(r["mu_bb_viol"], 1)       # cells, not points
        self.assertEqual(r["mu_bb_pts_lt_1"], 50)  # points, summed
        self.assertEqual(r["mu_bb_pts"], 280)

    def test_spec_bar_counters(self):
        # Bars quoted in the record: gain > 15 dB, NFmin@290 < 1.5 dB.
        r = pce.rollup([self.vrow(ga_max_q10_db_min=15.0),
                        self.vrow(ga_max_q10_db_min=15.1),
                        self.vrow(nfmin290_db_worst=1.5)])
        self.assertEqual(r["gq10_viol"], 1)       # <= 15.0 counts
        self.assertEqual(r["nfmin290_viol"], 1)   # >= 1.5 counts

    def test_out_of_box_cells_counted(self):
        r = pce.rollup([self.vrow(model_card_flags="in_box"),
                        self.vrow(model_card_flags="vbe1=0.5_outside")])
        self.assertEqual(r["oob"], 1)

    def test_summary_keys_cover_every_rollup_field(self):
        # The staged summary CSV writes SUMMARY_KEYS; a roll-up field with no
        # column would be silently dropped from published evidence.
        produced = set(pce.rollup([self.vrow()])) | {"variant"}
        self.assertEqual(produced, set(pce.SUMMARY_KEYS))


class PublicationUnit(unittest.TestCase):
    """#276: the exclusive-publication helpers (#126), called directly."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.records = Path(self._tmp.name)

    def test_published_names(self):
        self.assertEqual(pce.published_names("rec"),
                         ["rec.csv", "rec-variant-summary.csv", "rec.md"])

    def test_refuses_each_existing_name(self):
        names = pce.published_names("rec")
        for n in names:
            with self.subTest(existing=n):
                for f in self.records.iterdir():
                    f.unlink()
                (self.records / n).write_text("evidence\n")
                self.assertTrue(
                    pce.refuse_existing_publication(self.records, names))
        for f in self.records.iterdir():
            f.unlink()
        self.assertFalse(pce.refuse_existing_publication(self.records, names))

    def test_publish_links_all_and_clears_staging(self):
        names = pce.published_names("rec")
        stage = pce.stage_paths(self.records, names)
        for n in names:
            stage[n].write_text(f"body of {n}\n")
        self.assertTrue(pce.publish(self.records, names, stage))
        self.assertEqual(sorted(p.name for p in self.records.iterdir()),
                         sorted(names))
        for n in names:
            self.assertEqual((self.records / n).read_text(), f"body of {n}\n")
            self.assertFalse(stage[n].exists())

    def test_publish_refuses_to_replace_and_leaves_no_staging(self):
        names = pce.published_names("rec")
        stage = pce.stage_paths(self.records, names)
        for n in names:
            stage[n].write_text("new\n")
        (self.records / names[1]).write_text("existing evidence\n")
        self.assertFalse(pce.publish(self.records, names, stage))
        # The pre-existing file is untouched and no temp file is left behind.
        self.assertEqual((self.records / names[1]).read_text(),
                         "existing evidence\n")
        for n in names:
            self.assertFalse(stage[n].exists())


if __name__ == "__main__":
    unittest.main()
