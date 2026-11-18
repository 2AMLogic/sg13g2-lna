"""Unit tests for layout/inductance_report.py (issue #347). Stdlib only."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import inductance_report as ir  # noqa: E402


class TestLowFreq(unittest.TestCase):
    def test_extracted_p13_point(self):
        # 5 turns, w=6.1, s=3.29, d=110.11 (EM point p13): ~5.05 nH
        self.assertAlmostEqual(ir.l_lowfreq(5, 6.1, 3.29, 110.11) * 1e9, 5.0474, places=3)

    def test_drawn_geometries_hit_netlist_values(self):
        for n, w, s, d, target in [
            (4, 8.22, 3.74, 30.13, 1.0),
            (5, 6.1, 3.29, 109.15, 5.0),
            (4, 8.22, 3.74, 151.95, 4.56374),
        ]:
            self.assertAlmostEqual(ir.l_lowfreq(n, w, s, d) * 1e9, target, delta=0.001 * target)

    def test_monotonic_in_d_and_turns(self):
        self.assertLess(ir.l_lowfreq(4, 8.22, 3.74, 30), ir.l_lowfreq(4, 8.22, 3.74, 60))
        self.assertLess(ir.l_lowfreq(1, 8.22, 3.29, 47.65), ir.l_lowfreq(4, 8.22, 3.29, 47.65))

    def test_em_point_flag(self):
        self.assertTrue(ir._nearest_em_point(4, 8.22, 3.74, 141.975)["within_0p5um_of_extracted_d"])
        self.assertFalse(ir._nearest_em_point(4, 8.22, 3.74, 151.95)["within_0p5um_of_extracted_d"])

    def test_non_micron_length_rejected(self):
        with self.assertRaises(SystemExit):
            ir._um("1m")


if __name__ == "__main__":
    unittest.main()
