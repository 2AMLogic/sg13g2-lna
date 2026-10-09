"""Unit tests for the pure helpers in lna_variant_campaign.py (stdlib only)."""
import importlib.util
import math
import unittest
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


if __name__ == "__main__":
    unittest.main()
