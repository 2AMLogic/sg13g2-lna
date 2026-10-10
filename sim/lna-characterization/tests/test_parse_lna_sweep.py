"""Unit tests for the lna-characterization result-reduction code.

Stdlib only, headless, no ngspice, no PDK. Expectations are hand-computed
(see each test's comment), not read back from the code under test. Nothing
here writes under sim/: the regression test re-parses a committed record's
raw inputs into a temporary directory and only reads the committed files.

Run from the repo root (single process):

    python3 -I -m unittest discover -s sim/lna-characterization/tests
"""
import contextlib
import importlib.util
import io
import math
import shutil
import sys
import os
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
LNA = HERE.parent
FIX = HERE / "fixtures"
RECORD = "20260926-122301-088c734"


def load(name: str):
    spec = importlib.util.spec_from_file_location(name, LNA / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


P = load("parse_lna_sweep")


class PowerHelpers(unittest.TestCase):
    def test_db20(self):
        self.assertAlmostEqual(P.db20(1.0), 0.0)
        self.assertAlmostEqual(P.db20(10.0), 20.0)
        self.assertAlmostEqual(P.db20(0.1), -20.0)
        self.assertAlmostEqual(P.db20(2.0), 6.0206, places=4)
        self.assertEqual(P.db20(0.0), float("-inf"))

    def test_dbm_from_w(self):
        self.assertAlmostEqual(P.dbm_from_w(1e-3), 0.0)
        self.assertAlmostEqual(P.dbm_from_w(1.0), 30.0)
        self.assertAlmostEqual(P.dbm_from_w(1e-6), -30.0)
        self.assertEqual(P.dbm_from_w(0.0), float("-inf"))

    def test_out_power_dbm(self):
        # 1 V peak into 50 Ohm: V^2/(2*50) = 10 mW = +10 dBm.
        self.assertAlmostEqual(P.out_power_dbm(1.0), 10.0)
        # 0.1 V peak: 0.01/100 = 100 uW = -10 dBm.
        self.assertAlmostEqual(P.out_power_dbm(0.1), -10.0)
        # Doubling the voltage adds 6.0206 dB.
        self.assertAlmostEqual(
            P.out_power_dbm(0.2) - P.out_power_dbm(0.1), 6.0206, places=4
        )

    def test_avail_power_dbm(self):
        # 1 V peak open-circuit source behind 50 Ohm: V^2/(8*50) = 2.5 mW.
        self.assertAlmostEqual(P.avail_power_dbm(1.0), 10 * math.log10(2.5), places=9)
        self.assertAlmostEqual(P.avail_power_dbm(1.0), 3.9794, places=4)
        # 0.2 V peak: 0.04/400 = 100 uW = -10 dBm exactly.
        self.assertAlmostEqual(P.avail_power_dbm(0.2), -10.0)

    def test_matched_source_is_6db_below_load_power(self):
        # A matched load sees half the open-circuit voltage: the available
        # power is the load-power formula at V/2 (factor 4 = 6.0206 dB).
        for v in (0.001, 0.37, 1.0):
            self.assertAlmostEqual(P.avail_power_dbm(v), P.out_power_dbm(v / 2.0))
            self.assertAlmostEqual(
                P.out_power_dbm(v) - P.avail_power_dbm(v), 6.0206, places=4
            )


class Iip3(unittest.TestCase):
    def test_iip3_from_hand_values(self):
        # Pin -30, Pout -20, PIM3 -80 dBm: -30 + (60)/2 = 0 dBm.
        self.assertAlmostEqual(P.iip3_from(-30.0, -20.0, -80.0), 0.0)
        # Pin -50, Pout -40, PIM3 -130: -50 + 90/2 = -5.
        self.assertAlmostEqual(P.iip3_from(-50.0, -40.0, -130.0), -5.0)

    def test_three_to_one_point_is_drive_invariant(self):
        # Ideal cubic: gain 10 dB, IIP3 = +5 dBm, so
        # Pout - PIM3 = 2*(IIP3 - Pin). Every drive level must return +5.
        for pin in (-60.0, -45.0, -30.0):
            pout = pin + 10.0
            pim3 = pout - 2.0 * (5.0 - pin)
            self.assertAlmostEqual(P.iip3_from(pin, pout, pim3), 5.0)

    def test_slope_flag_in_and_out_of_3to1_region(self):
        def cell(pim3_lo, pim3_hi):
            # Two drive levels 1 mV / 2 mV: Pin steps by 6.0206 dB.
            rows = []
            for tag, amp, pim3 in (("a1mv", 1e-3, pim3_lo), ("a2mv", 2e-3, pim3_hi)):
                pin = P.avail_power_dbm(amp)
                rows.append(
                    {
                        "point_id": f"iip3_typ_27c_vdd1.80v_{tag}",
                        "corner_label": "typ",
                        "temp_c": "27",
                        "vdd_v": "1.80",
                        "amp_v_peak_per_tone": f"{amp:.6e}",
                        "pin_avail_dbm_per_tone": f"{pin:.4f}",
                        "pim3_dbm": f"{pim3:.4f}",
                        "iip3_dbm": "0",
                    }
                )
            per_cell = {
                "c": {"corner_label": "typ", "temp_c": "27", "vdd_v": "1.80"}
            }
            P.join_iip3_into_summary(per_cell, rows)
            return per_cell["c"]

        dpin = P.avail_power_dbm(2e-3) - P.avail_power_dbm(1e-3)
        ideal = cell(-100.0, -100.0 + 3.0 * dpin)
        self.assertAlmostEqual(float(ideal["im3_slope_2pt"]), 3.0, places=3)
        # IM3 growing only 2 dB/dB (compressing / IM5 contamination).
        off = cell(-100.0, -100.0 + 2.0 * dpin)
        self.assertAlmostEqual(float(off["im3_slope_2pt"]), 2.0, places=3)
        self.assertGreater(abs(float(off["im3_slope_2pt"]) - 3.0), 0.5)
        self.assertEqual(ideal["iip3_dbm_a1mv"], "0")

    def test_single_drive_level_gives_no_slope(self):
        per_cell = {"c": {"corner_label": "typ", "temp_c": "27", "vdd_v": "1.80"}}
        P.join_iip3_into_summary(per_cell, [])
        self.assertEqual(per_cell["c"]["im3_slope_2pt"], "")


class LogReaders(unittest.TestCase):
    def test_is_complete(self):
        self.assertTrue(P.is_complete(str(FIX / "sp_typ_27c_vdd1.80v.log")))
        self.assertTrue(P.is_complete(str(FIX / "iip3_typ_27c_vdd1.80v_a1mv.log")))
        self.assertFalse(P.is_complete(str(FIX / "sp_trunc.log")))

    def test_parse_sp_log(self):
        d = P.parse_sp_log(str(FIX / "sp_typ_27c_vdd1.80v.log"))
        self.assertEqual(d["ic1"], 0.0039403)
        self.assertEqual(d["pdc"], 0.00848596)
        self.assertEqual(d["vbe1"], 0.843494)
        self.assertEqual(d["gain"], {"lo": 11.5657, "mid": 11.5137, "hi": 11.4604})
        self.assertEqual(d["nf290"]["lo"], 2.65592)
        self.assertEqual(d["nf30015"]["lo"], 2.58821)
        self.assertEqual(set(d["nf290"]), {"lo", "mid", "hi"})

    def test_parse_sp_log_truncated_lacks_nf(self):
        d = P.parse_sp_log(str(FIX / "sp_trunc.log"))
        self.assertEqual(d["gain"], {"lo": 11.5657})
        self.assertEqual(d["nf290"], {})

    def test_parse_iip3_log(self):
        d = P.parse_iip3_log(str(FIX / "iip3_typ_27c_vdd1.80v_a1mv.log"))
        self.assertEqual(d["npts"], 65536)
        self.assertEqual(d["fft_df"], 3.8147e6)
        self.assertEqual(d["dft_tone1"], 0.00187927)
        self.assertEqual(d["dft_im3h"], 6.47937e-9)
        self.assertEqual(d["fft_im3l"], 6.5763e-9)
        self.assertEqual(d["fft_im5h"], 7.74664e-11)
        self.assertEqual(d["fft_src2"], 0.000999618)
        self.assertEqual(d["ic1"], 0.0039403)

    def test_iip3_reduction_of_fixture(self):
        # Hand chain for the fixture: tones ~1.878225 mV, IM3 ~6.5333e-9 V,
        # Pin = avail(1 mV). IIP3 = Pin + (Pout - PIM3)/2.
        d = P.parse_iip3_log(str(FIX / "iip3_typ_27c_vdd1.80v_a1mv.log"))
        t = (d["fft_tone1"] + d["fft_tone2"]) / 2
        i3 = (d["fft_im3l"] + d["fft_im3h"]) / 2
        pin = P.avail_power_dbm(1e-3)
        self.assertAlmostEqual(pin, -56.0206, places=4)  # (1e-3)^2/400 = 2.5 nW
        pout = P.out_power_dbm(t)
        self.assertAlmostEqual(pout, 10 * math.log10(t * t / 100 / 1e-3), places=9)
        iip3 = P.iip3_from(pin, pout, P.out_power_dbm(i3))
        # Committed value for this point: records/20260926-122301-088c734-iip3.csv,
        # row iip3_typ_27c_vdd1.80v_a1mv, iip3_dbm = -1.4345.
        self.assertAlmostEqual(iip3, -1.4345, places=3)

    def test_read_table(self):
        with tempfile.TemporaryDirectory() as td:
            p = os.path.join(td, "t.dat")
            with open(p, "w") as fh:
                fh.write(" 1.0 2.0 3.0\n\n 4.0e0 5 6\n")
            self.assertEqual(P.read_table(p, 3), [[1.0, 2.0, 3.0], [4.0, 5.0, 6.0]])
            with self.assertRaises(SystemExit):
                P.read_table(p, 4)
            empty = os.path.join(td, "e.dat")
            open(empty, "w").close()
            with self.assertRaises(SystemExit):
                P.read_table(empty, 3)


SP = "sp_typ_27c_vdd1.80v"
A1 = "iip3_typ_27c_vdd1.80v_a1mv"
A2 = "iip3_typ_27c_vdd1.80v_a2mv"
A4 = "iip3_typ_27c_vdd1.80v_a4mv"
BCS_SP = "sp_bcs_27c_vdd1.80v"
BCS_A1 = "iip3_bcs_27c_vdd1.80v_a1mv"
BCS_A2 = "iip3_bcs_27c_vdd1.80v_a2mv"


def _write_table(path, ncols, nrows=2):
    with open(path, "w") as fh:
        for i in range(nrows):
            fh.write(" ".join(f"{0.5 + 0.01 * (i + j):.4f}" for j in range(ncols)) + "\n")


def make_cell(d: Path, sp_id: str, iip3_ids, sp_fix=SP, ip_fix=A1):
    """Synthesise one cell's artefacts from the committed fixture logs. The
    wrdata tables are synthetic: coverage tests care about which files exist
    and are complete, not about the numbers."""
    shutil.copy(FIX / f"{sp_fix}.log", d / f"{sp_id}.log")
    _write_table(d / f"{sp_id}.inband.dat", 24)
    _write_table(d / f"{sp_id}.stability.dat", 12)
    for pid in iip3_ids:
        shutil.copy(FIX / f"{ip_fix}.log", d / f"{pid}.log")


MANIFEST_TEXT = f"""# test inventory
kind campaign
sp {SP}
iip3 {A1}
iip3 {A2}
pair {A1} {A2}
iip3 {A4}
sp {BCS_SP}
iip3 {BCS_A1}
iip3 {BCS_A2}
pair {BCS_A1} {BCS_A2}
"""


class Coverage(unittest.TestCase):
    """Expected-point manifest: absent / truncated / dropped-level cases."""

    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.addCleanup(self._td.cleanup)
        self.td = Path(self._td.name)
        self.cd = self.td / "corners"
        self.cd.mkdir()
        make_cell(self.cd, SP, [A1, A2, A4])
        make_cell(self.cd, BCS_SP, [BCS_A1, BCS_A2])
        self.manifest = self.td / "expected.txt"
        self.manifest.write_text(MANIFEST_TEXT)

    def run_main(self, *extra, manifest=True):
        argv = [
            "parse_lna_sweep.py",
            "--corners-dir", str(self.cd),
            "--sparam-csv", str(self.td / "sp.csv"),
            "--iip3-csv", str(self.td / "ip.csv"),
            "--summary-csv", str(self.td / "sum.csv"),
            "--coverage-json", str(self.td / "cov.json"),
        ]
        if manifest:
            argv += ["--manifest", str(self.manifest)]
        argv += list(extra)
        old = sys.argv
        sys.argv = argv
        try:
            with contextlib.redirect_stderr(io.StringIO()):
                return P.main()
        finally:
            sys.argv = old

    def cov(self):
        import json
        return json.loads((self.td / "cov.json").read_text())

    def test_valid_inventory_is_complete(self):
        self.assertEqual(self.run_main("--strict"), 0)
        c = self.cov()
        self.assertEqual(c["status"], "complete")
        self.assertEqual((c["missing"], c["failed"], c["missing_drive_pairs"]), ([], [], []))
        self.assertEqual(len(c["completed"]), len(c["expected"]), 8)
        self.assertIn("complete", "\n".join(P.coverage_prose(c)))
        self.assertNotIn("PARTIAL", "\n".join(P.coverage_prose(c)))

    def test_valid_smoke_inventory(self):
        for f in list(self.cd.glob("*bcs*")) + [self.cd / f"{A4}.log"]:
            f.unlink()
        self.manifest.write_text(
            f"kind smoke\nsp {SP}\niip3 {A1}\niip3 {A2}\npair {A1} {A2}\n"
        )
        self.assertEqual(self.run_main("--strict"), 0)
        c = self.cov()
        self.assertEqual(c["status"], "complete")
        self.assertEqual(c["inventory_kind"], "smoke")
        prose = "\n".join(P.coverage_prose(c))
        self.assertIn("NOT a PVT campaign", prose)

    def test_deleted_sp_log_is_reported_and_distinct_exit(self):
        (self.cd / f"{BCS_SP}.log").unlink()
        # diagnostic reduction still succeeds and is marked partial
        self.assertEqual(self.run_main(), 0)
        self.assertEqual(self.cov()["missing"], [BCS_SP])
        self.assertEqual(self.cov()["status"], "partial")
        self.assertEqual(self.run_main("--strict"), P.STRICT_EXIT_BASE + P.EXIT_MISSING)

    def test_truncated_log_is_failed_not_missing(self):
        shutil.copy(FIX / "sp_trunc.log", self.cd / f"{BCS_SP}.log")
        self.assertEqual(self.run_main("--strict"), P.STRICT_EXIT_BASE + P.EXIT_FAILED)
        c = self.cov()
        self.assertEqual((c["missing"], c["failed"]), ([], [BCS_SP]))

    def test_removed_iip3_level_breaks_drive_pair(self):
        (self.cd / f"{BCS_A2}.log").unlink()
        self.assertEqual(
            self.run_main("--strict"),
            P.STRICT_EXIT_BASE + P.EXIT_MISSING + P.EXIT_PAIR,
        )
        c = self.cov()
        self.assertEqual(c["missing"], [BCS_A2])
        self.assertEqual(c["missing_drive_pairs"],
                         [{"points": [BCS_A1, BCS_A2], "unavailable": [BCS_A2]}])
        prose = "\n".join(P.coverage_prose(c))
        self.assertIn("PARTIAL INVENTORY", prose)
        self.assertIn("NOT a full campaign", prose)
        self.assertIn(BCS_A2, prose)

    def test_nominal_only_level_is_not_a_required_pair_member(self):
        # Dropping the nominal-only 4 mV level is a missing point but leaves
        # the mandatory pair intact; non-nominal cells never list it at all.
        (self.cd / f"{A4}.log").unlink()
        self.assertEqual(self.run_main("--strict"), P.STRICT_EXIT_BASE + P.EXIT_MISSING)
        c = self.cov()
        self.assertEqual(c["missing_drive_pairs"], [])
        self.assertNotIn(A4.replace("typ", "bcs"), c["expected"])

    def test_extra_levels_on_disk_are_unexpected_not_required(self):
        shutil.copy(FIX / f"{A1}.log", self.cd / "iip3_bcs_27c_vdd1.80v_a4mv.log")
        self.assertEqual(self.run_main("--strict"), 0)
        self.assertEqual(self.cov()["unexpected"], ["iip3_bcs_27c_vdd1.80v_a4mv"])

    def test_sp_log_without_wrdata_is_failed(self):
        (self.cd / f"{BCS_SP}.stability.dat").unlink()
        self.assertEqual(self.run_main("--strict"), P.STRICT_EXIT_BASE + P.EXIT_FAILED)

    def test_historical_replay_without_manifest_unchanged(self):
        self.assertEqual(self.run_main(manifest=False), 0)
        self.assertFalse((self.td / "cov.json").exists())
        self.assertIn("NOT established", "\n".join(P.coverage_prose(None)))

    def test_strict_requires_manifest(self):
        with self.assertRaises(SystemExit):
            self.run_main("--strict", manifest=False)

    def test_manifest_rejects_bad_lines(self):
        self.manifest.write_text("bogus line\n")
        with self.assertRaises(SystemExit):
            P.read_manifest(str(self.manifest))
        self.manifest.write_text(f"sp {SP}\npair {A1} {A2}\n")
        with self.assertRaises(SystemExit):
            P.read_manifest(str(self.manifest))

    def test_committed_record_dir_has_no_sidecars_required(self):
        # Historical records predate the manifest; nothing is demanded of them.
        self.assertFalse(
            list((LNA / "records").glob(f"{RECORD}-expected-points.txt"))
        )


class RecordRegression(unittest.TestCase):
    """Re-parse a committed record's retained raw artefacts; the output must
    match the committed CSVs byte-for-byte and the record's headline text."""

    def test_reparse_reproduces_committed_record(self):
        corners = LNA / "corners" / RECORD
        rec = LNA / "records"
        with tempfile.TemporaryDirectory() as td:
            out = {k: os.path.join(td, k + ".csv") for k in ("sparam", "iip3", "summary")}
            sp, per_cell, sp_skipped = P.build_sparam_rows(str(corners))
            ip, ip_skipped = P.build_iip3_rows(str(corners))
            P.join_iip3_into_summary(per_cell, ip)
            P.write_csv(out["sparam"], sp, list(sp[0].keys()))
            P.write_csv(out["iip3"], ip, list(ip[0].keys()))
            summ = [per_cell[k] for k in sorted(per_cell)]
            P.write_csv(out["summary"], summ, list(summ[0].keys()))
            self.assertEqual((sp_skipped, ip_skipped), ([], []))
            for kind, path in out.items():
                self.assertEqual(
                    Path(path).read_bytes(),
                    (rec / f"{RECORD}-{kind}.csv").read_bytes(),
                    kind,
                )
            text = P.headlines(out["summary"], out["iip3"])
        md_lines = set((rec / f"{RECORD}.md").read_text().splitlines())
        lines = text.split("\n")
        self.assertEqual(len(lines), 12)
        for line in lines:
            self.assertIn(line, md_lines)


if __name__ == "__main__":
    unittest.main()
