"""Unit tests for the fixed-T0 NF re-derivation (issue #101).

Pins sim/hbt-characterization/rederive_nf_fixed_t0.py (issue #25's
algebraic correction), whose helpers are also imported by
sim/lna-core-envelope/. Stdlib only, headless, no ngspice, no PDK, single
process. Numeric expectations are hand-computed from the documented formula

    F_corrected = F_committed + (T0 - T_amb) / T0,   T0 = 300.15 K

(i.e. inoise^2 re-referenced from 4kT_amb*RS to 4kT0*RS, divided by the
4kT0*RS floor), not read back from the code under test, so a perturbed
constant or sign in corrected_nf_db() fails here.

Nothing here writes under sim/: the end-to-end tests lay the fixture CSVs
(rows copied verbatim from the committed source records) out in a temporary
repo root, and the replay test re-derives the committed correction record
20260921-124900-d6da30a into a temporary directory and compares bytes.

Run from the repo root:

    python3 -I -m unittest discover -s sim/hbt-characterization/tests
"""
import contextlib
import csv
import importlib.util
import io
import math
import os
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
HBT = HERE.parent
REPO = HBT.parents[1]
FIX = HERE / "fixtures"
RECORDS = HBT / "records"

SRC_A = "20260910-200059-7da7038"
SRC_B = "20260918-203652-4293920"
CORRECTION = "20260921-124900-d6da30a"

_spec = importlib.util.spec_from_file_location(
    "rederive_nf_fixed_t0", HBT / "rederive_nf_fixed_t0.py")
R = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(R)


def db10(x: float) -> float:
    return 10.0 * math.log10(x)


def run_main(repo_root: Path, out_dir: Path, record_id: str = "test"):
    """Run R.main() with explicit outputs; return (rc, stdout, pts, summ)."""
    pts = out_dir / "corrected.csv"
    summ = out_dir / "summary.csv"
    argv = ["rederive_nf_fixed_t0.py", "--record-id", record_id,
            "--record-id-csv", str(pts), "--summary-csv", str(summ),
            "--repo-root", str(repo_root)]
    buf = io.StringIO()
    err = io.StringIO()
    with mock.patch("sys.argv", argv), contextlib.redirect_stdout(buf), \
            contextlib.redirect_stderr(err):
        rc = R.main()
    return rc, buf.getvalue(), pts, summ


def fixture_repo(tmp: Path, mutate=None) -> Path:
    """Lay the trimmed fixture CSVs out where main() expects the sources."""
    rec = tmp / "repo" / "sim" / "hbt-characterization" / "records"
    rec.mkdir(parents=True)
    for src in (SRC_A, SRC_B):
        dst = rec / f"{src}.csv"
        shutil.copyfile(FIX / f"{src}.trimmed.csv", dst)
        if mutate is not None:
            mutate(src, dst)
    return tmp / "repo"


class Constants(unittest.TestCase):
    def test_bench_constants(self):
        # The values the records' NF bench definition declares.
        self.assertEqual(R.KB, 1.380649e-23)
        self.assertEqual(R.T0, 300.15)
        self.assertEqual(R.RS, 50.0)
        self.assertEqual(tuple(R.AFFECTED_TEMPS), (-40, 125))

    def test_validity_box_constants(self):
        # spec/target-spec.md: ic < 0.003*Nx A, vbe 0.65-0.96 V,
        # vce 0.4-2.0 V.
        self.assertEqual(R.IC_LIMIT_FACTOR, 0.003)
        self.assertEqual((R.VBE_MIN, R.VBE_MAX), (0.65, 0.96))
        self.assertEqual((R.VCE_MIN, R.VCE_MAX), (0.4, 2.0))


class CorrectedNfDb(unittest.TestCase):
    def test_identity_at_t0(self):
        # 27 C -> T_amb = 300.15 K = T0: no correction at all.
        for nf in (0.0, 1.276670, 3.0, 8.74034, 56.1623):
            got, rt = R.corrected_nf_db(nf, 27)
            self.assertAlmostEqual(got, nf, places=12)
            self.assertLess(rt, 1e-9)

    def test_minus_40c_hand_value(self):
        # T_amb = 233.15 K; F += (300.15 - 233.15)/300.15 = 67/300.15.
        # NF 0 dB (F=1) -> 10log10(1 + 67/300.15) = 0.8750518485 dB.
        got, _ = R.corrected_nf_db(0.0, -40)
        self.assertAlmostEqual(got, 0.8750518485194088, places=12)
        # Cold ambient under-counted the source noise: correction raises NF.
        self.assertGreater(got, 0.0)
        # Committed fixture row nx8 bcs -40C vce1.2 vbe0.95, NF 1.276670 dB:
        # 10log10(10^0.127667 + 67/300.15) = 1.9450254741 dB.
        got, _ = R.corrected_nf_db(1.276670, -40)
        self.assertAlmostEqual(got, 1.9450254740686668, places=12)

    def test_125c_hand_value(self):
        # T_amb = 398.15 K; F -= 98/300.15. NF 3.0103 dB (F=2) ->
        # 10log10(2 - 98/300.15) = 2.2362483047 dB.
        got, _ = R.corrected_nf_db(db10(2.0), 125)
        self.assertAlmostEqual(got, 2.236248304676566, places=12)
        self.assertLess(got, db10(2.0))
        # Committed fixture row nx1 wcs 125C vce1.0 vbe0.91, NF 8.740340 dB:
        # 10log10(10^0.874034 - 98/300.15) = 8.5465681850 dB.
        got, _ = R.corrected_nf_db(8.740340, 125)
        self.assertAlmostEqual(got, 8.546568185006135, places=12)

    def test_independent_noise_power_construction(self):
        # Build inoise^2 explicitly from N_rest + 4kT_amb*RS, swap in 4kT0*RS,
        # and compare: the docstring's derivation, done without the helper.
        k, rs, t0 = 1.380649e-23, 50.0, 300.15
        for temp_c in (-40, 125):
            t_amb = temp_c + 273.15
            for n_rest_over_floor in (0.05, 0.4, 2.0, 1e5):
                n_rest = n_rest_over_floor * 4 * k * t0 * rs
                committed = db10((n_rest + 4 * k * t_amb * rs)
                                 / (4 * k * t0 * rs))
                want = db10((n_rest + 4 * k * t0 * rs) / (4 * k * t0 * rs))
                got, rt = R.corrected_nf_db(committed, temp_c)
                self.assertAlmostEqual(got, want, places=10)
                self.assertLess(rt, 1e-9)

    def test_roundtrip_residue(self):
        for temp_c in (-40, 27, 125):
            for nf in (0.5, 1.3, 4.4, 9.9, 52.57):
                _, rt = R.corrected_nf_db(nf, temp_c)
                self.assertGreaterEqual(rt, 0.0)
                self.assertLess(rt, 1e-9)

    def test_delta_shrinks_with_nf(self):
        # The additive F shift is fixed, so its dB size falls as NF grows.
        d_lo = R.corrected_nf_db(1.0, -40)[0] - 1.0
        d_hi = R.corrected_nf_db(20.0, -40)[0] - 20.0
        self.assertGreater(d_lo, d_hi)
        self.assertGreater(d_hi, 0.0)


class ClassifyValidity(unittest.TestCase):
    IN = dict(ic_a=1e-3, vbe_v=0.85, vce_v=1.0, nx=1)

    def c(self, **kw):
        args = dict(self.IN)
        args.update(kw)
        return R.classify_validity(args["ic_a"], args["vbe_v"],
                                   args["vce_v"], args["nx"])

    def test_inside_box_is_empty(self):
        self.assertEqual(self.c(), "")

    def test_ic_boundary_scales_with_nx(self):
        for nx in (1, 8):
            lim = 0.003 * nx
            self.assertEqual(self.c(ic_a=lim * (1 - 1e-9), nx=nx), "")
            # ic < 0.003*Nx is the box; equality is already outside.
            self.assertEqual(self.c(ic_a=lim, nx=nx), "ic_high")
            self.assertEqual(self.c(ic_a=lim * 1.01, nx=nx), "ic_high")
        # 5 mA: outside for one finger, inside for eight.
        self.assertEqual(self.c(ic_a=5e-3, nx=1), "ic_high")
        self.assertEqual(self.c(ic_a=5e-3, nx=8), "")

    def test_vbe_boundaries_inclusive(self):
        self.assertEqual(self.c(vbe_v=0.65), "")
        self.assertEqual(self.c(vbe_v=0.96), "")
        self.assertEqual(self.c(vbe_v=0.6499), "vbe_low")
        self.assertEqual(self.c(vbe_v=0.9601), "vbe_high")

    def test_vce_boundaries_inclusive(self):
        self.assertEqual(self.c(vce_v=0.4), "")
        self.assertEqual(self.c(vce_v=2.0), "")
        self.assertEqual(self.c(vce_v=0.3999), "vce_low")
        self.assertEqual(self.c(vce_v=2.0001), "vce_high")

    def test_flag_order_and_join(self):
        self.assertEqual(self.c(ic_a=0.01, vbe_v=1.05),
                         "ic_high;vbe_high")
        self.assertEqual(self.c(ic_a=0.01, vbe_v=0.5, vce_v=0.2),
                         "ic_high;vbe_low;vce_low")
        self.assertEqual(self.c(vbe_v=1.0, vce_v=2.5), "vbe_high;vce_high")

    def test_reproduces_committed_flag_column(self):
        # Every row of record 20260918 (all temperatures, not only the
        # corrected ones) carries a validity_flags column produced from the
        # same three limits; the classifier must reproduce it exactly.
        n = 0
        for row in R.source_row_iter(str(RECORDS / f"{SRC_B}.csv")):
            got = R.classify_validity(float(row["ic_a"]),
                                      float(row["vbe_v"]),
                                      float(row["vce_v"]), int(row["nx"]))
            self.assertEqual(got, row["validity_flags"], row["point_id"])
            n += 1
        self.assertGreater(n, 3000)


class SmallHelpers(unittest.TestCase):
    def test_float_or_none(self):
        self.assertIsNone(R.float_or_none(None))
        self.assertIsNone(R.float_or_none(""))
        self.assertIsNone(R.float_or_none("   "))
        self.assertEqual(R.float_or_none("1.5"), 1.5)
        self.assertEqual(R.float_or_none("3.826030e-11"), 3.826030e-11)

    def test_source_row_iter_reads_fixture(self):
        rows = list(R.source_row_iter(str(FIX / f"{SRC_B}.trimmed.csv")))
        self.assertEqual(len(rows), 9)
        self.assertEqual(rows[0]["point_id"], "nx1_typ_-40c_vce0.6v")
        self.assertEqual(rows[0]["validity_flags"], "vbe_low")
        self.assertEqual(rows[2]["validity_flags"], "")
        self.assertEqual(rows[-1]["nf_db"], "1.330920")
        # Record 20260910 has no validity_flags column at all.
        rows = list(R.source_row_iter(str(FIX / f"{SRC_A}.trimmed.csv")))
        self.assertEqual(len(rows), 6)
        self.assertNotIn("validity_flags", rows[0])

    def test_mint_record_id_format(self):
        if shutil.which("git") is None:
            self.skipTest("git not available")
        try:
            subprocess.run(["git", "rev-parse", "HEAD"], cwd=REPO,
                           capture_output=True, check=True)
        except subprocess.CalledProcessError:
            self.skipTest("not a git checkout")
        # mint_record_id() runs git in the CWD; pin it to the repo.
        old = os.getcwd()
        os.chdir(REPO)
        try:
            rid = R.mint_record_id()
        finally:
            os.chdir(old)
        self.assertRegex(rid, r"^\d{8}-\d{6}-[0-9a-f]{4,}$")


class FixtureEndToEnd(unittest.TestCase):
    def test_fixture_rows_are_verbatim_committed_rows(self):
        # The fixtures are trimmed copies, not invented data.
        for src in (SRC_A, SRC_B):
            committed = (RECORDS / f"{src}.csv").read_text().splitlines()
            trimmed = (FIX / f"{src}.trimmed.csv").read_text().splitlines()
            self.assertEqual(trimmed[0], committed[0])
            body = set(committed[1:])
            for line in trimmed[1:]:
                self.assertIn(line, body)

    def test_expected_rows_are_in_committed_correction_record(self):
        # Every expected corrected row is byte-identical to the row the
        # committed correction record holds for the same point.
        committed = (RECORDS / f"{CORRECTION}-corrected.csv").read_text()
        lines = set(committed.splitlines())
        expected = (FIX / "expected-corrected.csv").read_text().splitlines()
        self.assertEqual(expected[0], committed.splitlines()[0])
        for line in expected[1:]:
            self.assertIn(line, lines)

    def test_main_matches_checked_in_expected(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            repo = fixture_repo(d)
            rc, out, pts, summ = run_main(repo, d / "out")
            self.assertEqual(rc, 0)
            self.assertEqual(pts.read_bytes(),
                             (FIX / "expected-corrected.csv").read_bytes())
            self.assertEqual(summ.read_bytes(),
                             (FIX / "expected-summary.csv").read_bytes())
        # 27 C fixture rows (one per source) are skipped as identity.
        self.assertIn("corrected points: 13 rows", out)
        self.assertIn("affected temps only: [-40, 125]", out)
        self.assertIn("corrected cells: 4", out)
        self.assertIn("validity-flag reproduction mismatches vs "
                      "20260918: 0", out)
        self.assertIn("record id: test", out)

    def test_main_passes_dropped_nf_row_through(self):
        # A source row with an empty nf_db is a dropped operating point: it
        # must pass through with empty corrected/delta cells, not crash.
        def blank_nf(src, path):
            if src != SRC_A:
                return
            with open(path, newline="") as f:
                rows = list(csv.DictReader(f))
                fields = list(rows[0].keys())
            rows[2]["nf_db"] = ""  # nx1 wcs 125C vbe 0.91
            with open(path, "w", newline="") as f:
                w = csv.DictWriter(f, fieldnames=fields, lineterminator="\n")
                w.writeheader()
                w.writerows(rows)
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            rc, _, pts, summ = run_main(fixture_repo(d, blank_nf), d / "out")
            self.assertEqual(rc, 0)
            with open(pts, newline="") as f:
                got = [r for r in csv.DictReader(f)
                       if r["point_id"] == "nx1_wcs_125c_vce1.0v"
                       and r["vbe_v"] == "0.91"]
            with open(summ, newline="") as f:
                cell = [r for r in csv.DictReader(f)
                        if r["source_record"] == SRC_A]
        self.assertEqual(len(got), 1)
        self.assertEqual(got[0]["nf_db_committed_ambient_source"], "")
        self.assertEqual(got[0]["nf_db_corrected_fixed_t0"], "")
        self.assertEqual(got[0]["nf_delta_db"], "")
        self.assertEqual(got[0]["validity_flags"], "")
        # That was the only in-box point of the cell: in_box keeps counting
        # it but has no optimum; "all" still finds one among the rest.
        by_scope = {r["scope"]: r for r in cell}
        self.assertEqual(by_scope["in_box"]["n_points"], "1")
        self.assertEqual(
            by_scope["in_box"]["noise_optimum_nf_db_corrected_fixed_t0"], "")
        self.assertEqual(
            by_scope["all"]["noise_optimum_nf_db_corrected_fixed_t0"],
            "8.359725")

    def test_main_rejects_flag_mismatch(self):
        # Record 20260918's committed validity_flags column is a guard: a
        # disagreeing row must abort the derivation.
        def bad_flag(src, path):
            if src != SRC_B:
                return
            text = path.read_text().replace(
                "1.276670,\n", "1.276670,ic_high\n")
            self.assertNotEqual(text, path.read_text())
            path.write_text(text)
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            with self.assertRaises(AssertionError):
                run_main(fixture_repo(d, bad_flag), d / "out")


class AppendOnlyOutputs(unittest.TestCase):
    """Existing evidence is never overwritten (issue #123)."""

    def _run(self, repo, pts, summ):
        argv = ["rederive_nf_fixed_t0.py", "--record-id", "test",
                "--record-id-csv", str(pts), "--summary-csv", str(summ),
                "--repo-root", str(repo)]
        err = io.StringIO()
        with mock.patch("sys.argv", argv), \
                contextlib.redirect_stdout(io.StringIO()), \
                contextlib.redirect_stderr(err):
            return R.main(), err.getvalue()

    def test_fresh_success(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            rc, _, pts, summ = run_main(fixture_repo(d), d / "out")
            self.assertEqual(rc, 0)
            self.assertTrue(pts.stat().st_size > 0)
            self.assertTrue(summ.stat().st_size > 0)

    def test_existing_first_output_refused(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            pts, summ = d / "p.csv", d / "s.csv"
            pts.write_bytes(b"landed-points")
            rc, err = self._run(fixture_repo(d), pts, summ)
            self.assertEqual(rc, 4)
            self.assertIn("refusing to overwrite", err)
            self.assertEqual(pts.read_bytes(), b"landed-points")
            self.assertFalse(summ.exists())

    def test_collision_at_second_output_leaves_nothing_behind(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            pts, summ = d / "p.csv", d / "s.csv"
            summ.write_bytes(b"landed-summary")
            rc, err = self._run(fixture_repo(d), pts, summ)
            self.assertEqual(rc, 4)
            self.assertEqual(summ.read_bytes(), b"landed-summary")
            self.assertFalse(pts.exists())  # first reservation rolled back

    def test_existing_record_id_in_default_location_refused(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            repo = fixture_repo(d)
            rec = repo / "sim/hbt-characterization/records"
            old = rec / "test-corrected.csv"
            old.write_bytes(b"landed")
            argv = ["rederive_nf_fixed_t0.py", "--record-id", "test",
                    "--repo-root", str(repo)]
            with mock.patch("sys.argv", argv), \
                    contextlib.redirect_stdout(io.StringIO()), \
                    contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(R.main(), 4)
            self.assertEqual(old.read_bytes(), b"landed")
            self.assertFalse((rec / "test-summary.csv").exists())

    def test_concurrent_reservation_has_single_winner(self):
        import threading
        with tempfile.TemporaryDirectory() as d:
            target = os.path.join(d, "x.csv")
            barrier = threading.Barrier(8)
            wins, losses = [], []

            def worker(i):
                barrier.wait()
                try:
                    (h,) = R.reserve_outputs([target])
                except FileExistsError:
                    losses.append(i)
                    return
                with h:
                    h.write(f"winner-{i}")
                wins.append(i)

            ts = [threading.Thread(target=worker, args=(i,))
                  for i in range(8)]
            for t in ts:
                t.start()
            for t in ts:
                t.join()
            self.assertEqual(len(wins), 1)
            self.assertEqual(len(losses), 7)
            self.assertEqual(Path(target).read_text(), f"winner-{wins[0]}")

    def test_duplicate_destinations_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            t = os.path.join(d, "same.csv")
            with self.assertRaises(FileExistsError):
                R.reserve_outputs([t, t])
            self.assertFalse(os.path.exists(t))


class CommittedRecordReplay(unittest.TestCase):
    def test_replays_committed_correction_record(self):
        # Re-derive correction record 20260921-124900-d6da30a from the
        # committed source records into a temp dir; it must be
        # byte-identical to the committed files. Read-only on sim/.
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            rc, out, pts, summ = run_main(REPO, d, CORRECTION)
            self.assertEqual(rc, 0)
            self.assertEqual(
                pts.read_bytes(),
                (RECORDS / f"{CORRECTION}-corrected.csv").read_bytes())
            self.assertEqual(
                summ.read_bytes(),
                (RECORDS / f"{CORRECTION}-summary.csv").read_bytes())
        self.assertTrue(re.search(r"corrected points: \d+ rows", out))


if __name__ == "__main__":
    unittest.main()
