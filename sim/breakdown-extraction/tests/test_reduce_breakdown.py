"""Focused tests for reduce_breakdown.py and the replay checker (issue #145).

Expected values are computed independently (by hand / math.exp), not by
calling the code under test.
"""
import csv
import math
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE))
import reduce_breakdown as rb  # noqa: E402
import check_breakdown_replay as replay  # noqa: E402

HDR_A = rb.META + ["ic_per_nx_a", "vce_v"]
HDR_B = rb.META + ["ic_per_nx_a", "vce_v"]


def meta(pid="p1", role="extraction", rb_label="open"):
    return [pid, role, "typ", "hbt_typ", "27", "1", "1", rb_label, "1e12"]


def write(path, hdr, rows):
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(hdr)
        w.writerows(rows)


class Tmp(unittest.TestCase):
    def setUp(self):
        self._t = tempfile.TemporaryDirectory()
        self.d = Path(self._t.name)
        self.addCleanup(self._t.cleanup)

    def a(self, pts, **kw):
        p = self.d / "a.csv"
        write(p, HDR_A, [meta(**kw) + [i, v] for i, v in pts])
        return rb.reduce_bench_a(p)

    def b(self, pts, **kw):
        p = self.d / "b.csv"
        write(p, HDR_B, [meta(**kw) + [i, v] for v, i in pts])
        return rb.reduce_bench_b(p)


class Interp(unittest.TestCase):
    def test_log_midpoint(self):
        # target 1e-5 is the geometric midpoint of 1e-6..1e-4 -> halfway in x
        self.assertAlmostEqual(rb.interp_x_at_y([(1e-6, 2.0), (1e-4, 4.0)], 1e-5), 3.0, places=12)

    def test_log_not_linear(self):
        # target 1e-5 (log fraction 0.5) vs linear fraction (1e-5-1e-6)/(1e-4-1e-6)=0.0909
        v = rb.interp_x_at_y([(1e-6, 0.0), (1e-4, 1.0)], 1e-5)
        self.assertAlmostEqual(v, 0.5, places=12)

    def test_exact_endpoints(self):
        pts = [(1e-6, 2.0), (1e-4, 4.0)]
        self.assertEqual(rb.interp_x_at_y(pts, 1e-6), 2.0)
        self.assertAlmostEqual(rb.interp_x_at_y(pts, 1e-4), 4.0, places=12)

    def test_outside_range_is_none(self):
        pts = [(1e-6, 2.0), (1e-4, 4.0)]
        self.assertIsNone(rb.interp_x_at_y(pts, 1e-7))
        self.assertIsNone(rb.interp_x_at_y(pts, 1e-3))
        self.assertIsNone(rb.interp_x_at_y([], 1e-5))

    def test_duplicate_y_returns_x(self):
        self.assertEqual(rb.interp_x_at_y([(1e-5, 3.0), (1e-5, 3.5)], 1e-5), 3.5)


class BenchA(Tmp):
    def test_criteria_interpolated_and_missing_crossings_blank(self):
        # points span 1e-6..1e-4 only: 1ua exact, 10ua midpoint, 100ua exact end,
        # 500ua is a missing crossing.
        r = self.a([(1e-6, 2.0), (1e-4, 4.0)])[0]
        self.assertEqual(r["vce_at_1ua_per_nx_v"], "2.0000")
        self.assertEqual(r["vce_at_10ua_per_nx_v"], "3.0000")
        self.assertEqual(r["vce_at_100ua_per_nx_v"], "4.0000")
        self.assertEqual(r["vce_at_500ua_per_nx_v"], "")

    def test_interior_minimum_is_foldback(self):
        r = self.a([(1e-7, 5.0), (1e-6, 3.0), (1e-5, 1.5), (1e-4, 2.0)])[0]
        self.assertEqual(r["locus_has_foldback"], "yes")
        self.assertEqual(r["locus_min_vce_v"], "1.5000")
        self.assertEqual(r["locus_min_at_ic_per_nx_a"], "1.0000e-05")

    def test_endpoint_minimum_is_not_foldback(self):
        low = self.a([(1e-7, 1.0), (1e-6, 2.0), (1e-5, 3.0)])[0]
        self.assertEqual(low["locus_has_foldback"], "no")
        self.assertEqual(low["locus_min_vce_v"], "1.0000")
        high = self.a([(1e-7, 3.0), (1e-6, 2.0), (1e-5, 1.0)])[0]
        self.assertEqual(high["locus_has_foldback"], "no")

    def test_nonconverged_points_counted_not_used(self):
        r = self.a([(1e-7, ""), (1e-6, 2.0), (1e-4, 4.0)])[0]
        self.assertEqual((r["n_points"], r["n_converged"]), (3, 2))
        # unconverged low point is not an endpoint: minimum at 1e-6 is the endpoint
        self.assertEqual(r["locus_has_foldback"], "no")

    def test_all_nonconverged_probe_row_retained(self):
        r = self.a([(1e-7, ""), (1e-6, "")], role="probe")[0]
        self.assertEqual((r["n_points"], r["n_converged"]), (2, 0))
        self.assertEqual(r["locus_min_vce_v"], "")
        self.assertEqual(r["locus_has_foldback"], "")
        self.assertEqual(r["role"], "probe")

    def test_unsorted_input_sorted_by_current(self):
        r = self.a([(1e-4, 4.0), (1e-6, 2.0)])[0]
        self.assertEqual(r["vce_at_10ua_per_nx_v"], "3.0000")


class BenchB(Tmp):
    def test_monotone_and_crossing_interpolation(self):
        r = self.b([(1.0, 1e-8), (2.0, 1e-6), (3.0, 1e-4)], role="leakage")[0]
        self.assertEqual(r["ic_monotone_in_vce"], "yes")
        self.assertEqual(r["vce_at_1ua_per_nx_v"], "2.0000")  # exact point crossing
        self.assertEqual(r["vce_at_10ua_per_nx_v"], "2.5000")  # log midpoint 1e-6..1e-4
        self.assertEqual(r["v_last_v"], "3.00")
        self.assertEqual(r["ic_per_nx_max_a"], "1.0000e-04")

    def test_first_point_already_above_criterion(self):
        r = self.b([(0.2, 5e-6), (0.4, 6e-6)])[0]
        self.assertEqual(r["vce_at_1ua_per_nx_v"], "0.2000")
        self.assertEqual(r["vce_at_10ua_per_nx_v"], "")

    def test_non_monotone_detected(self):
        r = self.b([(1.0, 1e-6), (2.0, 5e-7), (3.0, 2e-6)])[0]
        self.assertEqual(r["ic_monotone_in_vce"], "no")

    def test_tolerance_allows_1e9_relative_dip(self):
        r = self.b([(1.0, 1e-6), (2.0, 1e-6 * (1 - 1e-10))])[0]
        self.assertEqual(r["ic_monotone_in_vce"], "yes")

    def test_missing_crossing_blank(self):
        r = self.b([(1.0, 1e-9), (2.0, 1e-8)])[0]
        self.assertEqual(r["vce_at_1ua_per_nx_v"], "")

    def test_leakage_readout_points_present_and_missing(self):
        pts = [(1.12, 1e-9), (1.6, 3e-9), (2.0, 5e-9)]  # 1.40 V not swept
        r = self.b(pts, role="leakage")[0]
        self.assertEqual(r["ic_per_nx_at_1p12v_a"], "1.0000e-09")
        self.assertEqual(r["ic_per_nx_at_1p40v_a"], "")
        self.assertEqual(r["ic_per_nx_at_1p60v_a"], "3.0000e-09")
        self.assertEqual(r["ic_per_nx_at_2p00v_a"], "5.0000e-09")

    def test_truncated_control_n_points(self):
        r = self.b([(0.2, 1e-12), (0.4, 2e-12)], role="control-open")[0]
        self.assertEqual(r["n_points"], 2)


class Malformed(Tmp):
    def expect(self, fn, path, needle):
        with self.assertRaises(rb.ReductionError) as cm:
            fn(path)
        self.assertIn(needle, str(cm.exception))

    def test_missing_file(self):
        self.expect(rb.reduce_bench_a, self.d / "nope.csv", "cannot read input")

    def test_empty_file(self):
        p = self.d / "e.csv"; p.write_text("")
        self.expect(rb.reduce_bench_a, p, "empty file")

    def test_header_only(self):
        p = self.d / "h.csv"; write(p, HDR_A, [])
        self.expect(rb.reduce_bench_b, p, "no data rows")

    def test_missing_column(self):
        p = self.d / "m.csv"; write(p, HDR_A[:-1], [meta() + [1e-6]])
        self.expect(rb.reduce_bench_a, p, "missing required column(s): vce_v")

    def test_non_numeric_value(self):
        p = self.d / "n.csv"; write(p, HDR_B, [meta() + ["abc", "1.0"]])
        self.expect(rb.reduce_bench_b, p, "not numeric")

    def test_nan_value(self):
        p = self.d / "n.csv"; write(p, HDR_B, [meta() + ["1e-6", "nan"]])
        self.expect(rb.reduce_bench_b, p, "not finite")

    def test_short_row(self):
        p = self.d / "s.csv"
        p.write_text(",".join(HDR_A) + "\n" + ",".join(meta()) + "\n")
        self.expect(rb.reduce_bench_a, p, "wrong field count")

    def test_bad_temp(self):
        p = self.d / "t.csv"
        row = meta(); row[4] = "hot"
        write(p, HDR_A, [row + [1e-6, 1.0]])
        self.expect(rb.reduce_bench_a, p, "temp_c")

    def test_cli_exit_2_and_no_outputs(self):
        p = self.d / "m.csv"; write(p, HDR_A[:-1], [meta() + [1e-6]])
        good = self.d / "g.csv"; write(good, HDR_B, [meta() + ["1e-6", "1.0"]])
        oa, ob = self.d / "oa.csv", self.d / "ob.csv"
        proc = subprocess.run([sys.executable, "-I", str(HERE.parent / "reduce_breakdown.py"),
                               "--locus", str(p), "--sweep", str(good),
                               "--out-locus-summary", str(oa), "--out-sweep-summary", str(ob)],
                              capture_output=True, text=True)
        self.assertEqual(proc.returncode, 2)
        self.assertIn("missing required column", proc.stderr)
        self.assertFalse(oa.exists() or ob.exists())


class Replay(Tmp):
    """The committed record replays byte-identically; mutations fail."""
    R = replay.REC / f"{replay.RECORD_ID}"

    def paths(self):
        return (f"{self.R}-bvceo-locus.csv", f"{self.R}-heldbase-sweep.csv",
                f"{self.R}-bvceo-summary.csv", f"{self.R}-heldbase-summary.csv")

    def test_committed_record_replays(self):
        self.assertEqual(replay.check(*self.paths()), 0)

    def test_mutated_summary_fails(self):
        l, s, sa, sb = self.paths()
        m = self.d / "mut.csv"
        data = Path(sa).read_bytes()
        m.write_bytes(data.replace(b",no\n", b",yes\n", 1))
        self.assertEqual(replay.check(l, s, m, sb), 1)

    def test_missing_input_fails(self):
        l, s, sa, sb = self.paths()
        self.assertEqual(replay.check(self.d / "gone.csv", s, sa, sb), 2)

    def test_malformed_input_fails(self):
        l, s, sa, sb = self.paths()
        bad = self.d / "bad.csv"; bad.write_text("x,y\n1,2\n")
        self.assertEqual(replay.check(bad, s, sa, sb), 2)


if __name__ == "__main__":
    unittest.main()
