"""Unit tests for parse_core_envelope.py against a trimmed wrdata fixture (#104).

Stdlib only, headless, no ngspice, no PDK. The fixture under fixtures/ is one
corner (point p001) with 2 in-band and 3 broadband frequency points; the
expected values are hand-computed from it (see comments), not read back from
the parser. The parser runs as a subprocess writing into a temp dir; nothing
here writes under sim/.

Run: python3 -I -m unittest discover -s sim/lna-core-envelope/tests
"""

import csv
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
PARSER = HERE.parent / "parse_core_envelope.py"
FIX = HERE / "fixtures"


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

    def run_parser(self):
        return subprocess.run(
            [sys.executable, "-I", str(PARSER), "--record-id", "rec",
             "--corners-dir", str(self.corners), "--records-dir", str(self.records),
             "--manifest", str(self.manifest)],
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


if __name__ == "__main__":
    unittest.main()
