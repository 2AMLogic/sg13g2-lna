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


GRID_LINES = (
    "grid inband lin 11 2.4e9 2.4835e9\n"
    "grid stability dec 40 1e7 3e10\n"
)


def grid_freqs(kind):
    # Hand-derived: lin 11 pts 2.4e9..2.4835e9; dec 40/decade from 1e7 gives
    # floor(40*log10(3000))+1 = 140 points ending at 1e7*10^(139/40) = 2.985e10.
    if kind == "inband":
        return [2.4e9 + i * 8.35e6 for i in range(11)]
    return [1e7 * 10 ** (i / 40) for i in range(140)]


def write_grid_table(path, kind, freqs=None, edit=None):
    ncols, scale_cols = (24, [0, 3, 6, 9, 12, 14, 16, 18, 21]) if kind == "inband" else (12, [0, 2, 4, 6, 8, 10])
    freqs = grid_freqs(kind) if freqs is None else freqs
    with open(path, "w") as fh:
        for i, f in enumerate(freqs):
            row = [0.5 + 0.001 * i] * ncols
            for c in scale_cols:
                row[c] = f
            if edit:
                edit(i, row)
            fh.write(" ".join(f"{v:.8e}" for v in row) + "\n")


class GridHarness(unittest.TestCase):
    """Shared temp-dir/manifest harness (no tests of its own)."""

    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.addCleanup(self._td.cleanup)
        self.td = Path(self._td.name)
        self.cd = self.td / "corners"
        self.cd.mkdir()
        make_cell(self.cd, SP, [A1, A2])
        self.write(SP)
        self.manifest = self.td / "expected.txt"
        self.manifest.write_text(
            f"kind smoke\n{GRID_LINES}sp {SP}\niip3 {A1}\niip3 {A2}\npair {A1} {A2}\n"
        )

    def write(self, pid, inband=None, stab=None):
        write_grid_table(self.cd / f"{pid}.inband.dat", "inband", **(inband or {}))
        write_grid_table(self.cd / f"{pid}.stability.dat", "stability", **(stab or {}))

    def run_main(self, *extra):
        argv = ["parse_lna_sweep.py", "--corners-dir", str(self.cd),
                "--sparam-csv", str(self.td / "sp.csv"),
                "--iip3-csv", str(self.td / "ip.csv"),
                "--summary-csv", str(self.td / "sum.csv"),
                "--coverage-json", str(self.td / "cov.json"),
                "--manifest", str(self.manifest), *extra]
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

    def assert_invalid(self, artifact, needle):
        self.assertEqual(self.run_main("--strict"), P.STRICT_EXIT_BASE + P.EXIT_GRID)
        c = self.cov()
        self.assertEqual(c["status"], "partial")
        self.assertEqual(c["completed"], [A1, A2])
        hits = [g for g in c["invalid_grids"] if g["artifact"] == f"{SP}.{artifact}.dat"]
        self.assertTrue(hits, c["invalid_grids"])
        self.assertTrue(any(needle in g["reason"] for g in hits), hits)
        self.assertEqual(hits[0]["point"], SP)
        self.assertIn("Invalid frequency grid", "\n".join(P.coverage_prose(c)))


class FrequencyGrid(GridHarness):
    """Raw-table frequency contract: a complete log with a bad table is not
    a completed point."""

    def test_expected_grid_shapes(self):
        g = P.expected_grid({"mode": "dec", "n": 40, "lo": 1e7, "hi": 3e10})
        self.assertEqual(len(g), 140)
        self.assertAlmostEqual(g[-1] / 2.98538262e10, 1.0, places=8)
        self.assertEqual(len(P.expected_grid({"mode": "lin", "n": 11, "lo": 2.4e9, "hi": 2.4835e9})), 11)

    def test_valid_grids_are_complete_and_smoke_keeps_contract(self):
        self.assertEqual(self.run_main("--strict"), 0)
        c = self.cov()
        self.assertEqual(c["status"], "complete")
        self.assertEqual(c["inventory_kind"], "smoke")
        self.assertEqual(c["invalid_grids"], [])
        self.assertEqual(set(c["frequency_grid_contract"]), {"inband", "stability"})
        self.assertIn("validated", "\n".join(P.coverage_prose(c)))
        self.assertNotIn("NOT validated", "\n".join(P.coverage_prose(c)))

    def test_legacy_manifest_without_contract_is_marked_unvalidated(self):
        self.manifest.write_text(f"sp {SP}\niip3 {A1}\niip3 {A2}\npair {A1} {A2}\n")
        write_grid_table(self.cd / f"{SP}.inband.dat", "inband", freqs=grid_freqs("inband")[:3])
        self.assertEqual(self.run_main("--strict"), 0)
        c = self.cov()
        self.assertIn("legacy", c["frequency_grid_contract"])
        self.assertIn("NOT validated", "\n".join(P.coverage_prose(c)))

    def test_deleted_interior_row(self):
        f = grid_freqs("stability")
        del f[70]
        self.write(SP, stab={"freqs": f})
        self.assert_invalid("stability", "139 frequency points, expected 140")
        self.assertIn("first grid mismatch at row 71",
                      "\n".join(g["reason"] for g in self.cov()["invalid_grids"]))

    def test_deleted_interior_row_inband_same_count_shape(self):
        f = grid_freqs("inband")
        del f[5]
        self.write(SP, inband={"freqs": f})
        self.assert_invalid("inband", "10 frequency points, expected 11")

    def test_shortened_upper_endpoint(self):
        f = grid_freqs("inband")[:-1] + [2.45e9]
        self.write(SP, inband={"freqs": f})
        self.assert_invalid("inband", "upper endpoint")

    def test_truncated_table_valid_width_rows(self):
        self.write(SP, stab={"freqs": grid_freqs("stability")[:100]})
        self.assert_invalid("stability", "100 frequency points, expected 140")

    def test_duplicate_frequency(self):
        f = grid_freqs("inband")
        f[4] = f[3]
        self.write(SP, inband={"freqs": f})
        self.assert_invalid("inband", "duplicate frequency")

    def test_unordered_frequency(self):
        f = grid_freqs("inband")
        f[4], f[5] = f[5], f[4]
        self.write(SP, inband={"freqs": f})
        self.assert_invalid("inband", "not increasing")

    def test_inconsistent_repeated_scale_column(self):
        def edit(i, row):
            if i == 3:
                row[9] *= 1.01
        self.write(SP, inband={"edit": edit})
        self.assert_invalid("inband", "repeated frequency column 9")

    def test_nan_and_inf(self):
        for bad in ("nan", "inf"):
            def edit(i, row, bad=bad):
                if i == 2:
                    row[13] = float(bad)
            self.write(SP, stab=None, inband={"edit": edit})
            self.assert_invalid("inband", "non-finite")

    def test_wrong_width_row_reported(self):
        (self.cd / f"{SP}.stability.dat").write_text("1.0 2.0\n")
        self.assert_invalid("stability", "expected 12 columns")

    def test_invalid_point_excluded_from_extrema_and_nonstrict_still_reduces(self):
        make_cell(self.cd, BCS_SP, [BCS_A1, BCS_A2])
        self.write(BCS_SP)
        self.manifest.write_text(
            f"kind campaign\n{GRID_LINES}sp {SP}\nsp {BCS_SP}\n"
            f"iip3 {A1}\niip3 {A2}\npair {A1} {A2}\n"
            f"iip3 {BCS_A1}\niip3 {BCS_A2}\npair {BCS_A1} {BCS_A2}\n"
        )
        self.write(SP, inband={"freqs": grid_freqs("inband")[:-1]})
        self.assertEqual(self.run_main(), 0)
        import csv
        ids = {r["point_id"] for r in csv.DictReader(open(self.td / "sum.csv"))}
        self.assertEqual(ids, {BCS_SP})
        self.assertEqual(self.cov()["status"], "partial")
        self.assertEqual(self.run_main("--strict"), P.STRICT_EXIT_BASE + P.EXIT_GRID)

    def test_failed_run_keeps_its_own_exit_bit_alongside_grid_bit(self):
        make_cell(self.cd, BCS_SP, [BCS_A1, BCS_A2])
        self.write(BCS_SP)
        self.manifest.write_text(
            f"{GRID_LINES}sp {SP}\nsp {BCS_SP}\niip3 {A1}\niip3 {A2}\npair {A1} {A2}\n"
        )
        (self.cd / f"{BCS_SP}.stability.dat").unlink()
        self.write(SP, inband={"freqs": grid_freqs("inband")[:-1]})
        self.assertEqual(self.run_main("--strict"),
                         P.STRICT_EXIT_BASE + P.EXIT_FAILED + P.EXIT_GRID)

    def test_manifest_grid_parsing_rejects_garbage(self):
        for bad in ("grid inband lin x 1 2", "grid inband lin 11 5 1",
                    "grid foo lin 11 1 2", "grid inband lin 11 1 2"):
            self.manifest.write_text(f"sp {SP}\n{bad}\n")
            with self.assertRaises(SystemExit):
                P.read_manifest(str(self.manifest))

    def test_committed_record_tables_satisfy_the_contract(self):
        # Read-only: the real 088c734 tables must satisfy the grid derived
        # from the deck, proving the tolerances fit real ngspice output.
        d = LNA / "corners" / RECORD
        specs = {"inband": {"mode": "lin", "n": 11, "lo": 2.4e9, "hi": 2.4835e9},
                 "stability": {"mode": "dec", "n": 40, "lo": 1e7, "hi": 3e10}}
        files = sorted(d.glob("sp_*.inband.dat"))[:6] + sorted(d.glob("sp_*.stability.dat"))[:6]
        self.assertTrue(files)
        for f in files:
            kind = "inband" if f.name.endswith(".inband.dat") else "stability"
            self.assertEqual(P.validate_table(str(f), kind, specs[kind]), [], f.name)


NF_LINE = "grid nf290 lin 11 2.4e9 2.4835e9\n"
# lo/mid/hi values of tests/fixtures/sp_typ_27c_vdd1.80v.log (the cross-check).
NF_LMH = {0: 2.65592, 5: 2.65551, 10: 2.6551}


def write_nf_table(path, freqs=None, nf=None, peak=None):
    """Synthetic-fixture 290 K NF table: flat-ish, optionally an interior
    peak that none of the lo/mid/hi samples can see."""
    freqs = grid_freqs("inband") if freqs is None else freqs
    with open(path, "w") as fh:
        for i, f in enumerate(freqs):
            v = NF_LMH.get(i, 2.6) if nf is None else nf[i]
            if peak and i == peak[0]:
                v = peak[1]
            fh.write(f" {f:.8e} {v:.8e} {f:.8e} {v - 0.0677:.8e}\n")


class Nf290Grid(GridHarness):
    """Issue #134: the independent 290 K NF sweep covers the whole in-band
    grid; malformed tables never produce a complete-grid summary."""

    def setUp(self):
        super().setUp()
        self.manifest.write_text(
            f"kind smoke\n{GRID_LINES}{NF_LINE}sp {SP}\niip3 {A1}\niip3 {A2}\npair {A1} {A2}\n")
        write_nf_table(self.cd / f"{SP}.nf290.dat")

    def run_main(self, *extra):
        return super().run_main("--nf-csv", str(self.td / "nf.csv"), *extra)

    def summary(self):
        import csv
        return list(csv.DictReader(open(self.td / "sum.csv")))[0]

    def test_valid_grid_reports_worst_sample_frequency_and_limits(self):
        self.assertEqual(self.run_main("--strict"), 0)
        r = self.summary()
        self.assertEqual(r["nf290_n_samples"], "11")
        self.assertEqual(r["nf290_db_worst"], "2.6559")  # band lo, first max
        self.assertEqual(float(r["nf290_f_at_worst_hz"]), 2.4e9)
        self.assertIn("lin 11 pts 2.4..2.4835 GHz", r["nf290_grid"])
        self.assertIn("not a continuous-band bound", r["nf290_sampling"])
        self.assertIn("8.35 MHz", r["nf290_sampling"])
        self.assertEqual(r["nf290_db_at_band_mid"], "2.6555")  # cross-check retained
        import csv
        rows = list(csv.DictReader(open(self.td / "nf.csv")))
        self.assertEqual(len(rows), 11)  # raw table retained
        self.assertEqual({r["freq_hz"] for r in rows}, {f"{f:.6e}" for f in grid_freqs("inband")})

    def test_interior_peak_beats_lo_mid_hi(self):
        write_nf_table(self.cd / f"{SP}.nf290.dat", peak=(3, 2.9))
        self.assertEqual(self.run_main("--strict"), 0)
        r = self.summary()
        self.assertEqual(r["nf290_db_worst"], "2.9000")
        self.assertAlmostEqual(float(r["nf290_f_at_worst_hz"]), 2.4e9 + 3 * 8.35e6, delta=10)
        self.assertEqual(r["nf290_db_at_band_lo"], "2.6559")  # 3-point view would say 2.6559
        self.assertIn("2.9", P.headlines(str(self.td / "sum.csv"), str(self.td / "ip.csv")))

    def test_headline_states_grid_and_limit(self):
        write_nf_table(self.cd / f"{SP}.nf290.dat", peak=(3, 2.9))
        self.run_main()
        h = P.headlines(str(self.td / "sum.csv"), str(self.td / "ip.csv"))
        nf_line = next(l for l in h.splitlines() if "NF (T0 = 290 K" in l)
        self.assertIn("2.425050e+09 Hz", nf_line)
        self.assertIn("lin 11 pts", nf_line)
        self.assertIn("peak narrower than the spacing", nf_line)

    def test_missing_interior_row_is_invalid(self):
        f = grid_freqs("inband")
        del f[4]
        write_nf_table(self.cd / f"{SP}.nf290.dat", freqs=f, nf=[2.6] * 10)
        self.assertEqual(self.run_main("--strict"), P.STRICT_EXIT_BASE + P.EXIT_GRID)
        self.assertEqual(self.cov()["status"], "partial")
        self.assertTrue(any(g["artifact"].endswith(".nf290.dat") for g in self.cov()["invalid_grids"]))

    def test_missing_file_is_failed_point(self):
        (self.cd / f"{SP}.nf290.dat").unlink()
        self.assertEqual(self.run_main("--strict"), P.STRICT_EXIT_BASE + P.EXIT_FAILED)

    def test_duplicate_and_nonfinite_samples_are_invalid(self):
        f = grid_freqs("inband")
        f[5] = f[4]
        write_nf_table(self.cd / f"{SP}.nf290.dat", freqs=f)
        self.assertEqual(self.run_main("--strict"), P.STRICT_EXIT_BASE + P.EXIT_GRID)
        self.assertTrue(any("duplicate" in g["reason"] for g in self.cov()["invalid_grids"]))
        for bad in (float("nan"), float("inf")):
            nf = [2.6] * 11
            nf[7] = bad
            write_nf_table(self.cd / f"{SP}.nf290.dat", nf=nf)
            self.assertEqual(self.run_main("--strict"), P.STRICT_EXIT_BASE + P.EXIT_GRID)
            self.assertTrue(any("non-finite" in g["reason"] for g in self.cov()["invalid_grids"]))

    def test_without_manifest_gaps_and_short_tables_still_rejected(self):
        why = P.validate_nf_table(str(self.cd / f"{SP}.nf290.dat"))
        self.assertEqual(why, [])
        f = grid_freqs("inband")
        write_nf_table(self.cd / f"{SP}.nf290.dat", freqs=[f[0], f[5], f[10]], nf=[2.6] * 3)
        self.assertTrue(P.validate_nf_table(str(self.cd / f"{SP}.nf290.dat")))  # 3 points
        del f[4]
        write_nf_table(self.cd / f"{SP}.nf290.dat", freqs=f, nf=[2.6] * 10)
        self.assertTrue(P.validate_nf_table(str(self.cd / f"{SP}.nf290.dat")))

    def test_grid_disagreeing_with_lo_mid_hi_crosscheck_is_excluded(self):
        nf = [2.6] * 11
        write_nf_table(self.cd / f"{SP}.nf290.dat", nf=nf)  # lo/mid/hi 2.6 != log
        self.assertNotEqual(self.run_main("--strict"), 0)

    def test_denser_grid_via_manifest(self):
        n = 21
        self.manifest.write_text(
            f"kind smoke\n{GRID_LINES}grid nf290 lin {n} 2.4e9 2.4835e9\nsp {SP}\n"
            f"iip3 {A1}\niip3 {A2}\npair {A1} {A2}\n")
        f = [2.4e9 + i * 4.175e6 for i in range(n)]
        write_nf_table(self.cd / f"{SP}.nf290.dat", freqs=f,
                       nf=[{0: 2.65592, 10: 2.65551, 20: 2.6551}.get(i, 2.6) for i in range(n)])
        self.assertEqual(self.run_main("--strict"), 0)
        self.assertEqual(self.summary()["nf290_n_samples"], "21")

    def test_manifest_rejects_even_or_small_nf_grid(self):
        for bad in ("grid nf290 lin 10 2.4e9 2.4835e9", "grid nf290 lin 3 2.4e9 2.4835e9"):
            self.manifest.write_text(f"{GRID_LINES}{bad}\nsp {SP}\n")
            with self.assertRaises(SystemExit):
                P.read_manifest(str(self.manifest))

    def test_historical_points_are_labelled_three_point_when_mixed(self):
        # A directory with no nf290 tables at all keeps the historical column
        # set; with one grid cell, the legacy cell is explicitly marked.
        (self.cd / f"{SP}.nf290.dat").unlink()
        self.manifest.write_text(
            f"kind smoke\n{GRID_LINES}sp {SP}\niip3 {A1}\niip3 {A2}\npair {A1} {A2}\n")
        self.assertEqual(self.run_main("--strict"), 0)
        self.assertNotIn("nf290_n_samples", self.summary())
        import shutil as sh
        for ext in (".log", ".inband.dat", ".stability.dat"):
            sh.copy(self.cd / f"{SP}{ext}", self.cd / f"{BCS_SP}{ext}")
        write_nf_table(self.cd / f"{SP}.nf290.dat")
        rows, per_cell, _, _ = P.build_sparam_rows(str(self.cd))
        self.assertEqual(per_cell[SP]["nf290_n_samples"], "11")
        self.assertEqual(per_cell[BCS_SP]["nf290_n_samples"], "3")
        self.assertIn("HISTORICAL three-point", per_cell[BCS_SP]["nf290_grid"])


class IIP3MethodValidity(unittest.TestCase):
    """Per-cell IIP3 method validity (issue #137): synthetic data only."""

    DPIN = P.avail_power_dbm(2e-3) - P.avail_power_dbm(1e-3)

    def pair(self, slope, corner="typ", temp="27", vdd="1.80", iip3=(-5.0, -5.0)):
        rows = []
        for tag, amp, pim3, ip in (
            ("a1mv", 1e-3, -100.0, iip3[0]),
            ("a2mv", 2e-3, -100.0 + slope * self.DPIN, iip3[1]),
        ):
            rows.append(
                {
                    "point_id": f"iip3_{corner}_{temp}c_vdd{vdd}v_{tag}",
                    "corner_label": corner,
                    "temp_c": temp,
                    "vdd_v": vdd,
                    "amp_v_peak_per_tone": f"{amp:.6e}",
                    "pin_avail_dbm_per_tone": f"{P.avail_power_dbm(amp):.4f}",
                    "pim3_dbm": f"{pim3:.4f}",
                    "iip3_dbm": f"{ip:.4f}",
                }
            )
        return rows

    def headline(self, rows, cells, tol=P.IIP3_SLOPE_TOL):
        with tempfile.TemporaryDirectory() as td:
            per_cell = {
                i: {"corner_label": c[0], "temp_c": c[1], "vdd_v": c[2]}
                for i, c in enumerate(cells)
            }
            P.join_iip3_into_summary(per_cell, rows)
            sm = [dict(per_cell[k], **_SUMMARY_STUB) for k in sorted(per_cell)]
            P.write_csv(os.path.join(td, "s.csv"), sm, list(sm[0].keys()))
            P.write_csv(os.path.join(td, "i.csv"), rows, list(rows[0].keys()))
            return P.headlines(os.path.join(td, "s.csv"), os.path.join(td, "i.csv"), tol)

    def test_valid_and_documented_tolerance(self):
        self.assertEqual(P.IIP3_SLOPE_TOL, 0.15)
        v, why = P.classify_iip3_cell(self.pair(3.0))
        self.assertEqual((v, why), ("valid", "slope 3.000 within 3 +/- 0.15"))

    def test_slope_1_and_5_invalid_with_reasons(self):
        self.assertEqual(
            P.classify_iip3_cell(self.pair(1.0)),
            ("invalid", "slope 1.000 outside 3 +/- 0.15"),
        )
        self.assertEqual(
            P.classify_iip3_cell(self.pair(5.0)),
            ("invalid", "slope 5.000 outside 3 +/- 0.15"),
        )

    def test_boundary_is_inclusive_and_deterministic(self):
        for s, want in ((3.15, "valid"), (2.85, "valid"), (3.16, "invalid"), (2.84, "invalid")):
            self.assertEqual(P.classify_iip3_cell(self.pair(s))[0], want, s)
        self.assertEqual(P.classify_iip3_cell(self.pair(3.2), tol=0.2)[0], "valid")

    def test_unknown_cases_do_not_raise(self):
        full = self.pair(3.0)
        self.assertEqual(P.classify_iip3_cell([])[0], "unknown")
        v, why = P.classify_iip3_cell(full[:1])
        self.assertEqual(v, "unknown")
        self.assertIn("a2mv", why)
        self.assertIn("duplicated", P.classify_iip3_cell(full + full[:1])[1])
        for bad in ("nan", "inf", "-inf", ""):
            rows = self.pair(3.0)
            rows[1]["pim3_dbm"] = bad
            v, why = P.classify_iip3_cell(rows)
            self.assertEqual(v, "unknown", bad)
            self.assertEqual(why, "nonfinite or unparsable pim3_dbm at a2mv")
        rows = self.pair(3.0)
        rows[1]["pin_avail_dbm_per_tone"] = rows[0]["pin_avail_dbm_per_tone"]
        self.assertEqual(
            P.classify_iip3_cell(rows),
            ("unknown", "zero Pin step between drive levels"),
        )

    def test_invalid_pair_cannot_claim_cubic_assumption(self):
        for slope in (1.0, 5.0):
            h = self.headline(self.pair(slope), [("typ", "27", "1.80")])
            self.assertNotIn("holds at every cell", h)
            self.assertIn("NO accepted intercept", h)
            self.assertIn("0 valid / 1 invalid / 0 unknown of 1 cells", h)
            self.assertNotIn("across all points", h)

    def test_all_valid_keeps_original_wording(self):
        h = self.headline(self.pair(3.0), [("typ", "27", "1.80")])
        self.assertIn("holds at every cell", h)
        self.assertIn("IIP3 (two-tone, 2 drive points)", h)

    def test_mixed_cells_extrema_only_over_valid(self):
        rows = (
            self.pair(3.0, "typ", "27", iip3=(-5.0, -4.0))
            + self.pair(5.0, "bcs", "27", iip3=(-90.0, 90.0))  # invalid
            + self.pair(1.0, "wcs", "27", iip3=(-80.0, 80.0))  # invalid
        )
        rows += self.pair(3.0, "tt", "85")[:1]  # unknown: a2mv missing
        cells = [("typ", "27", "1.80"), ("bcs", "27", "1.80"), ("wcs", "27", "1.80"),
                 ("tt", "85", "1.80")]
        h = self.headline(rows, cells)
        self.assertNotIn("holds at every cell", h)
        self.assertIn("1 valid / 2 invalid / 1 unknown of 4 cells", h)
        self.assertIn("min -5.0000 dBm at typ/27 C", h)
        self.assertIn("max -4.0000 dBm at typ/27 C", h)
        self.assertNotIn("90.0000", h)
        self.assertNotIn("-80.0000", h)
        self.assertIn("claimed only at the valid cells", h)

    def test_zero_valid_cells_no_accepted_claim(self):
        rows = self.pair(5.0, "bcs") + self.pair(1.0, "wcs")
        h = self.headline(rows, [("bcs", "27", "1.80"), ("wcs", "27", "1.80")])
        self.assertIn("NO accepted intercept", h)
        self.assertIn("no cell has a validated slope", h)

    def test_validity_does_not_change_summary_columns(self):
        per_cell = {"c": {"corner_label": "typ", "temp_c": "27", "vdd_v": "1.80"}}
        P.join_iip3_into_summary(per_cell, self.pair(5.0))
        self.assertNotIn("iip3_method_validity", per_cell["c"])
        self.assertEqual(per_cell["c"]["im3_slope_2pt"], "5.000")


_SUMMARY_STUB = {'point_id': 'sp_bcs_-40c_vdd1.62v', 'ic1_a': '3.898010e-03', 'ic2_a': '3.896460e-03', 'vce1_v': '0.5967', 'vce2_v': '1.0233', 'vbe1_v': '0.8894', 'idd_a': '4.643000e-03', 'pdc_w': '7.521660e-03', 's11_db_worst': '-2.9695', 's21_db_min': '12.1454', 's21_db_max': '12.2799', 's22_db_worst': '-0.0036', 'k_inband_min': '4.404008', 'mu_inband_min': '1.000306', 'mag_delta_inband_max': '0.710134', 'nf_sp_db_at_band_lo': '2.2051', 'nfmin_sp_db_at_band_lo': '2.0823', 'nf290_db_worst': '1.8522', 'nf290_db_at_band_lo': '1.8522', 'nf290_db_at_band_mid': '1.8519', 'nf290_db_at_band_hi': '1.8516', 'nf30015_db_at_band_lo': '1.8009', 'gain_ac_db_at_band_lo': '12.2799', 'gain_ac_minus_s21_db': '-0.0000', 'k_broadband_min': '-2.950322', 'f_at_k_broadband_min_hz': '5.011872e+07', 'n_broadband_pts_k_lt_1': '61', 'n_broadband_pts': '140', 'mu_broadband_min': '0.999996', 'f_at_mu_broadband_min_hz': '5.956621e+08', 'n_broadband_pts_mu_lt_1': '61', 'mag_delta_broadband_max': '0.811068', 'f_at_mag_delta_broadband_max_hz': '1.000000e+07', 's11_mag_broadband_max': '0.811068', 'f_at_s11_mag_broadband_max_hz': '1.000000e+07', 's22_mag_broadband_max': '1.000000', 'f_at_s22_mag_broadband_max_hz': '1.584893e+08'}


class RecordRegression(unittest.TestCase):
    """Re-parse a committed record's retained raw artefacts; the output must
    match the committed CSVs byte-for-byte and the record's headline text."""

    def test_reparse_reproduces_committed_record(self):
        corners = LNA / "corners" / RECORD
        rec = LNA / "records"
        with tempfile.TemporaryDirectory() as td:
            out = {k: os.path.join(td, k + ".csv") for k in ("sparam", "iip3", "summary")}
            sp, per_cell, sp_skipped, _nf = P.build_sparam_rows(str(corners))
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
