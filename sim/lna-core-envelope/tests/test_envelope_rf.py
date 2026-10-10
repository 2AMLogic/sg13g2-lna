"""Numerical self-tests for the shared envelope_rf helpers (issue #94).

Hand-checkable cases that fail if an equation or the 50 Ohm normalization
changes. Run: python3 -I -m unittest discover -s sim/lna-core-envelope/tests
"""

import importlib.util
import math
import tempfile
import unittest
from pathlib import Path

_P = Path(__file__).resolve().parents[1] / "envelope_rf.py"
_spec = importlib.util.spec_from_file_location("envelope_rf", _P)
rf = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(rf)


class EnvelopeRfTests(unittest.TestCase):
    def test_nf_reref(self):
        self.assertAlmostEqual(rf.nf_reref(3.0, 290.0, 290.0), 3.0, places=12)
        # F=2 (3.0103 dB): 580 K -> 290 K doubles F-1 (F=3); 290 K -> 580 K halves it (F=1.5)
        f2 = 10 * math.log10(2.0)
        self.assertAlmostEqual(rf.nf_reref(f2, 580.0, 290.0),
                               10 * math.log10(3.0), places=12)
        self.assertAlmostEqual(rf.nf_reref(f2, 290.0, 580.0),
                               10 * math.log10(1.5), places=12)
        self.assertAlmostEqual(rf.nf_reref(0.0, 300.0, 290.0), 0.0, places=12)

    def test_s_to_y_known_two_ports(self):
        y0 = 1 / 50.0
        # matched through line: S = [[0,1],[1,0]] has no finite Y; use
        # series 50 Ohm resistor: S11=S22=1/3, S21=S12=2/3 -> Y = [[y0,-y0],[-y0,y0]]
        y = rf.s_to_y(1 / 3, 2 / 3, 2 / 3, 1 / 3)
        for got, want in zip(y, (y0, -y0, -y0, y0)):
            self.assertAlmostEqual(got, want, places=12)
        # open ports (S11=S22=1, no coupling): Y=0
        y = rf.s_to_y(1 + 0j, 0, 0, 1 + 0j)
        for v in y:
            self.assertAlmostEqual(abs(v), 0.0, places=12)
        # matched termination, no coupling: Y11=Y22=y0
        y = rf.s_to_y(0, 0, 0, 0)
        self.assertAlmostEqual(y[0], y0, places=12)
        self.assertAlmostEqual(y[3], y0, places=12)

    def test_s_y_roundtrip(self):
        s = (0.3 - 0.2j, 0.05 + 0.01j, 2.5 - 1.0j, -0.4 + 0.3j)
        back = rf.y_to_s(*rf.s_to_y(*s))
        for a, b in zip(s, back):
            self.assertAlmostEqual(abs(a - b), 0.0, places=12)

    def test_ga_max_db(self):
        self.assertAlmostEqual(rf.ga_max_db(0, 0, 10, 0), 20.0, places=12)
        # |s11|^2 = 0.5 and |s22|^2 = 0.5 each add 3.0103 dB
        r = math.sqrt(0.5)
        self.assertAlmostEqual(rf.ga_max_db(r, 0, 1, r),
                               2 * 10 * math.log10(2.0), places=12)

    def test_tank_q_shunt_loss(self):
        s = (0.1, 0.0, 10.0, 0.2)
        f = 2.44175e9
        ideal = rf.ga_max_db(*s)
        self.assertLess(rf.ga_max_with_tank_q(*s, 10.0, f), ideal)
        # monotone in Q; huge Q approaches the ideal value
        self.assertLess(rf.ga_max_with_tank_q(*s, 5.0, f),
                        rf.ga_max_with_tank_q(*s, 50.0, f))
        self.assertAlmostEqual(rf.ga_max_with_tank_q(*s, 1e12, f), ideal, places=6)
        # independent construction: add G=1/(Q*2*pi*f*Lc) to Y22 by hand
        y0 = 0.02
        y = list(rf.s_to_y(*s))
        y[3] += 1 / (10.0 * 2 * math.pi * f * 5e-9)
        dn = (y0 + y[0]) * (y0 + y[3]) - y[1] * y[2]
        s22 = ((y0 + y[0]) * (y0 - y[3]) + y[1] * y[2]) / dn
        s11 = ((y0 - y[0]) * (y0 + y[3]) + y[1] * y[2]) / dn
        s21 = -2 * y[2] * y0 / dn
        want = (20 * math.log10(abs(s21)) - 10 * math.log10(1 - abs(s11) ** 2)
                - 10 * math.log10(1 - abs(s22) ** 2))
        self.assertAlmostEqual(rf.ga_max_with_tank_q(*s, 10.0, f), want, places=12)

    def test_parse_table_inband_layout(self):
        g = 1.0e9
        vals = [g, 0.1, 0.2, g, 3.0, 4.0, g, 0.01, 0.02, g, 0.5, 0.6,
                g, 1.5, g, 2.5, g, 0.9, g, 3.5, 0.0, g, 1.25, 0.0]
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "x.dat"
            p.write_text("\n" + " ".join(repr(v) for v in vals) + "\n\n")
            (r,) = rf.parse_table(p)
        self.assertEqual(r["freq_hz"], 1.0e9)
        self.assertEqual(r["s11"], 0.1 + 0.2j)
        self.assertEqual(r["s21"], 3.0 + 4.0j)
        self.assertEqual(r["s12"], 0.01 + 0.02j)
        self.assertEqual(r["s22"], 0.5 + 0.6j)
        self.assertEqual(r["k"], 1.5)
        self.assertEqual(r["mu"], 2.5)
        self.assertEqual(r["mag_delta"], 0.9)
        self.assertEqual(r["nf"], 3.5 + 0j)
        self.assertEqual(r["nfmin"], 1.25 + 0j)


class TableIntegrity(unittest.TestCase):
    G = 1.0e9

    def row(self, f=None, **over):
        g = self.G if f is None else f
        v = [g, 0.1, 0.2, g, 3.0, 4.0, g, 0.01, 0.02, g, 0.5, 0.6,
             g, 1.5, g, 2.5, g, 0.9, g, 3.5, 0.0, g, 1.25, 0.0]
        for k, x in over.items():
            v[int(k[1:])] = x
        return " ".join(repr(x) for x in v)

    def parse(self, lines, **kw):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "x.dat"
            p.write_text("\n".join(lines) + "\n")
            return rf.parse_table(p, **kw)

    def rejects(self, lines, frag, **kw):
        with self.assertRaises(rf.TableError) as cm:
            self.parse(lines, **kw)
        self.assertIn(frag, str(cm.exception))
        self.assertIn("x.dat", str(cm.exception))

    def test_valid_multirow(self):
        self.assertEqual(len(self.parse([self.row(1e9), self.row(2e9)],
                                        expected_points=2)), 2)

    def test_nan_inf_overflow(self):
        self.rejects([self.row().replace("2.5", "nan")], "non-finite")
        self.rejects([self.row().replace("2.5", "inf")], "non-finite")
        self.rejects([self.row().replace("2.5", "1e999")], "non-finite")

    def test_column_count(self):
        self.rejects([self.row() + " 7.0"], "columns")
        self.rejects([" ".join(self.row().split()[:-1])], "columns")

    def test_inconsistent_scale(self):
        self.rejects([self.row().replace("1.5", "1.5", 1).replace(
            f"{self.G!r} 2.5", "2e9 2.5")], "inconsistent repeated frequency")

    def test_duplicate_and_reversed(self):
        self.rejects([self.row(1e9), self.row(1e9)], "strictly increasing")
        self.rejects([self.row(2e9), self.row(1e9)], "strictly increasing")

    def test_nonpositive_frequency(self):
        self.rejects([self.row(0.0)], "non-positive")

    def test_missing_declared_grid_points(self):
        self.rejects([self.row(1e9)], "declared grid", expected_points=2)


class DeclaredGridCheck(unittest.TestCase):
    """check_declared_grid against the live campaign grid (run_core_envelope.sh)."""

    @staticmethod
    def rows(freqs):
        return [{"freq_hz": float(f"{f:.8e}")} for f in freqs]  # wrdata precision

    def stab(self):
        # ngspice `sp dec 40 1e7 3e10`: 140 points, last 2.98538262e10 (the
        # committed record 20260926-180931-90b07a0 has exactly this).
        return self.rows(1e7 * 10 ** (i / 40) for i in range(140))

    def inband(self):
        return self.rows(2.4e9 + i * (2.4835e9 - 2.4e9) / 10 for i in range(11))

    def ok(self, rows, sweep, lo, hi, n):
        rf.check_declared_grid(rows, "x.dat", sweep, lo, hi, n)

    def bad(self, rows, sweep, lo, hi, n, frag):
        with self.assertRaises(rf.TableError) as cm:
            rf.check_declared_grid(rows, "x.dat", sweep, lo, hi, n)
        self.assertIn(frag, str(cm.exception))
        self.assertIn("x.dat", str(cm.exception))

    def test_campaign_grids_pass(self):
        self.assertAlmostEqual(self.stab()[-1]["freq_hz"], 2.98538262e10, delta=1e2)
        self.ok(self.stab(), "dec", 1e7, 3e10, 40)
        self.ok(self.inband(), "lin", 2.4e9, 2.4835e9, 11)

    def test_stab_missing_middle_row(self):
        r = self.stab()
        del r[70]
        self.bad(r, "dec", 1e7, 3e10, 40, "requires 140")

    def test_stab_truncated_tail(self):
        self.bad(self.stab()[:-1], "dec", 1e7, 3e10, 40, "requires 140")
        self.bad(self.stab()[:100], "dec", 1e7, 3e10, 40, "requires 140")

    def test_stab_missing_head(self):
        self.bad(self.stab()[1:], "dec", 1e7, 3e10, 40, "declared start")

    def test_stab_overshoot(self):
        r = self.stab()
        r[-1] = {"freq_hz": 3.1e10}
        self.bad(r, "dec", 1e7, 3e10, 40, "declared stop")

    def test_inband_count_and_endpoints(self):
        self.bad(self.inband()[:-1], "lin", 2.4e9, 2.4835e9, 11, "declared grid has 11")
        r = self.inband()
        r[-1] = {"freq_hz": 2.5e9}
        self.bad(r, "lin", 2.4e9, 2.4835e9, 11, "declared stop")

    def test_empty(self):
        self.bad([], "lin", 2.4e9, 2.4835e9, 11, "no points")

    def test_parse_grid_arg(self):
        self.assertEqual(rf.parse_grid_arg("1e7,3e10,40"), (1e7, 3e10, 40))
        for bad in ("1e7,3e10", "3e10,1e7,40", "1e7,3e10,0", "0,1e9,5", "1e7,inf,4"):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                rf.parse_grid_arg(bad)


if __name__ == "__main__":
    unittest.main()
