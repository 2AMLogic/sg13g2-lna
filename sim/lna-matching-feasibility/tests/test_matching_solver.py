"""Unit tests for sim/lna-matching-feasibility/matching_solver.py (issue #186).

Stdlib-only, PDK-free, no ngspice, single process. Synthetic fixtures for the
RF math and the solvers; a replay of every committed record (reduce the
retained wrdata into a temp dir, compare byte for byte with the committed
CSVs; re-synthesize from the retained characterization data and compare with
the committed candidates.json). Never writes under sim/.
"""
from __future__ import annotations

import cmath
import json
import math
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

HERE = Path(__file__).resolve().parent
EXP = HERE.parent
sys.path.insert(0, str(EXP))
import matching_solver as ms  # noqa: E402

W = ms.W_MID
NOISE = {"fmin": 10 ** (2.38 / 10), "rn": 24.6, "gopt": complex(0.26, 0.015)}
ZIN = complex(280.0, -39.0)


def close(a, b, tol):
    return abs(a - b) <= tol


class RfMath(unittest.TestCase):
    def test_z_gamma_roundtrip(self):
        for z in (complex(50, 0), complex(280, -39), complex(10, 70)):
            g = ms.gamma(z)
            self.assertTrue(close(ms.z_from_s(g), z, 1e-9 * abs(z)))
        self.assertEqual(ms.gamma(50), 0)

    def test_db20_floor(self):
        self.assertEqual(ms.db20(0.0), -300.0)
        self.assertAlmostEqual(ms.db20(0.1), -20.0)

    def test_q_resistors(self):
        l = 5e-9
        self.assertEqual(ms.q_series_r(l, None), 0.0)
        self.assertAlmostEqual(W * l / ms.q_series_r(l, 10.0), 10.0)
        self.assertAlmostEqual(ms.q_parallel_r(l, 10.0) / (W * l), 10.0)
        with self.assertRaises(ValueError):
            ms.q_series_r(l, 0)
        with self.assertRaises(ValueError):
            ms.q_parallel_r(l, None)

    def test_nf_reref(self):
        self.assertAlmostEqual(ms.nf_reref(2.0, 290.0), 2.0)
        f = 10 ** (2.0 / 10)
        want = 10 * math.log10(1 + (f - 1) * 300.15 / 290)
        self.assertAlmostEqual(ms.nf_reref(2.0, 300.15), want)

    def test_two_port_f(self):
        zopt = ms.z_from_s(NOISE["gopt"])
        self.assertAlmostEqual(ms.two_port_f(zopt, NOISE["fmin"], NOISE["rn"], NOISE["gopt"]), NOISE["fmin"])
        # away from Zopt F grows
        self.assertGreater(ms.two_port_f(complex(300, 0), NOISE["fmin"], NOISE["rn"], NOISE["gopt"]),
                           NOISE["fmin"])

    def test_stability_unilateral(self):
        s11, s22 = complex(0.5, 0.1), complex(0.3, -0.4)
        mu, k, d = ms.stability(s11, complex(3, 1), 0j, s22)
        # S12 = 0: Delta = S11*S22, so mu = (1-|S11|^2)/(|S22|(1-|S11|^2)) = 1/|S22|
        self.assertAlmostEqual(mu, 1 / abs(s22))
        self.assertEqual(k, math.inf)
        self.assertAlmostEqual(d, abs(s11 * s22))

    def test_stability_matches_formula(self):
        s11, s21, s12, s22 = complex(0.7, -0.04), complex(-3.5, 1.4), complex(-1.6e-5, -5e-6), complex(0.4, 0.915)
        mu, k, _ = ms.stability(s11, s21, s12, s22)
        dlt = s11 * s22 - s12 * s21
        self.assertAlmostEqual(mu, (1 - abs(s11) ** 2) / (abs(s22 - s11.conjugate() * dlt) + abs(s12 * s21)))
        self.assertAlmostEqual(k, (1 - abs(s11) ** 2 - abs(s22) ** 2 + abs(dlt) ** 2) / (2 * abs(s12 * s21)))


class InputNetwork(unittest.TestCase):
    def test_lsection_closed_form_matches(self):
        for zl in (complex(280, -39), complex(470, 60), complex(30, 80), complex(100, 0)):
            sols = ms.lsection_closed_form(zl)
            self.assertEqual(len(sols), 2)
            for x, b in sols:
                zin = 1j * x + 1 / (1j * b + 1 / zl)
                self.assertTrue(close(zin, 50, 1e-9), (zl, zin))

    def test_lsection_impossible(self):
        self.assertEqual(ms.lsection_closed_form(complex(-5, 0)), [])
        self.assertEqual(ms.lsection_closed_form(complex(20, 0)), [])   # R_L < Z0, X_L = 0

    def test_reactances_to_elements(self):
        self.assertEqual(ms.reactances_to_elements(10, 0.01)[0], "lowpass")
        self.assertEqual(ms.reactances_to_elements(-10, -0.01)[0], "highpass")
        self.assertEqual(ms.reactances_to_elements(10, -0.01)[0], "mixed")
        topo, l, c = ms.reactances_to_elements(W * 5e-9, W * 1e-12)
        self.assertAlmostEqual(l, 5e-9)
        self.assertAlmostEqual(c, 1e-12)

    def test_power_match_lossless_and_lossy(self):
        for topo in ("lowpass", "highpass"):
            for q in (None, 20.0, 10.0):
                sol = ms.solve_input_power(topo, ZIN, q)
                z = ms.input_zlook(topo, sol["values"], q, ms.F_MID, ZIN)
                self.assertTrue(close(z, 50, 1e-6), (topo, q, z))
                if q is None:
                    self.assertEqual(sol["values"], sol["closed_form"])

    def test_present_target_zs(self):
        target = complex(170, 14)
        for q in (None, 10.0):
            sol = ms.solve_input("lowpass", target, q)
            self.assertTrue(close(ms.input_zs("lowpass", sol["values"], q, ms.F_MID), target, 1e-6))

    def test_avail_gain(self):
        vals = ms.solve_input_power("lowpass", ZIN, None)["values"]
        self.assertAlmostEqual(ms.input_avail_gain("lowpass", vals, None, ms.F_MID), 1.0)
        vals = ms.solve_input_power("lowpass", ZIN, 10.0)["values"]
        self.assertLess(ms.input_avail_gain("lowpass", vals, 10.0, ms.F_MID), 1.0)

    def test_predicted_nf_lossless_equals_two_port(self):
        vals = ms.solve_input_power("highpass", ZIN, None)["values"]
        zs = ms.input_zs("highpass", vals, None, ms.F_MID)
        want = ms.nf_reref(10 * math.log10(ms.two_port_f(zs, NOISE["fmin"], NOISE["rn"], NOISE["gopt"])),
                           ms.T_ANALYSIS)
        self.assertAlmostEqual(ms.predicted_nf290("highpass", vals, None, ms.F_MID, NOISE), want, places=9)

    def test_predicted_nf_loss_adds_noise(self):
        lossless = ms.predicted_nf290("lowpass", ms.solve_input_power("lowpass", ZIN, None)["values"],
                                      None, ms.F_MID, NOISE)
        lossy = ms.predicted_nf290("lowpass", ms.solve_input_power("lowpass", ZIN, 10.0)["values"],
                                   10.0, ms.F_MID, NOISE)
        self.assertGreater(lossy, lossless)

    def test_noise_compromise_boundary(self):
        zs, f, on_b = ms.noise_compromise_zs(ZIN, NOISE)
        g = 10 ** (ms.MISMATCH_TARGET_DB / 20)
        self.assertTrue(on_b)
        self.assertAlmostEqual(abs((zs - ZIN.conjugate()) / (zs + ZIN)), g, places=9)
        # no other boundary point is quieter (coarse independent scan)
        for i in range(0, 360, 5):
            gm = g * cmath.exp(1j * math.radians(i))
            z = (ZIN.conjugate() + gm * ZIN) / (1 - gm)
            self.assertGreaterEqual(ms.two_port_f(z, NOISE["fmin"], NOISE["rn"], NOISE["gopt"]), f - 1e-9)

    def test_noise_compromise_inside(self):
        zopt = ms.z_from_s(NOISE["gopt"])
        zs, f, on_b = ms.noise_compromise_zs(zopt.conjugate(), NOISE)
        self.assertFalse(on_b)
        self.assertTrue(close(zs, zopt, 1e-9))
        self.assertEqual(f, NOISE["fmin"])

    def test_solve_input_noise(self):
        for q in (None, 10.0):
            sol = ms.solve_input_noise("lowpass", ZIN, NOISE, q, n=61, refine=2)
            g = abs(ms.gamma(ms.input_zlook("lowpass", sol["values"], q, ms.F_MID, ZIN)))
            self.assertLessEqual(g, 10 ** (ms.MISMATCH_TARGET_DB / 20) + 1e-12)
            nf = ms.predicted_nf290("lowpass", sol["values"], q, ms.F_MID, NOISE)
            nf_pm = ms.predicted_nf290("lowpass", ms.solve_input_power("lowpass", ZIN, q)["values"],
                                       q, ms.F_MID, NOISE)
            self.assertLess(nf, nf_pm)

    def test_newton_failure_raises(self):
        with self.assertRaises(RuntimeError):
            ms.newton2(lambda a, b: complex(1.0, 1.0), (1.0, 1.0))


class OutputNetwork(unittest.TestCase):
    YDEV = complex(7.4e-6, 3.09e-4)

    def test_fixed_lc(self):
        for q in (None, 10.0):
            lc = 5e-9
            ylc = 1 / ms.z_ind(lc, ms.q_series_r(lc, q), ms.F_MID)
            o = ms.solve_output_fixed_lc(self.YDEV, ylc)
            self.assertTrue(o["feasible"])
            z = ms.output_zlook(self.YDEV, ylc, o["cp"], o["cs"], ms.F_MID)
            self.assertTrue(close(z, 50, 1e-6), z)

    def test_fixed_lc_infeasible(self):
        # a too-large Lc leaves the node capacitive enough that Cp would be negative
        ylc = 1 / ms.z_ind(200e-9, 0.0, ms.F_MID)
        o = ms.solve_output_fixed_lc(self.YDEV, ylc)
        self.assertFalse(o["feasible"])
        self.assertLess(o["cp_raw"], 0)
        # conductance above 1/50 cannot be matched by a shunt-C + series-C section
        self.assertFalse(ms.solve_output_fixed_lc(complex(0.05, 0), 0j)["feasible"])

    def test_free_lc(self):
        for q in (None, 20.0, 10.0):
            o = ms.solve_output_free_lc(self.YDEV, q)
            ylc = 1 / ms.z_ind(o["lc"], o["r_lc"], ms.F_MID)
            z = ms.output_zlook(self.YDEV, ylc, 0.0, o["cs"], ms.F_MID)
            self.assertTrue(close(z, 50, 1e-4), (q, z))
        # Lc ~ 50*Q/w for a lossy tank (the record's "2-element" column)
        self.assertTrue(close(ms.solve_output_free_lc(self.YDEV, 10.0)["lc"], 50 * 10 / W, 0.35 * 50 * 10 / W))

    def test_ydev_from_choke_roundtrip(self):
        f = ms.F_MID
        y_node = self.YDEV + 1 / complex(0, 2 * math.pi * f * ms.CHOKE)
        z22 = 1 / y_node + ms.z_cap(ms.COUT, f)
        s22 = ms.gamma(z22)
        self.assertTrue(close(ms.ydev_from_choke_s22(s22, f), self.YDEV, 1e-9))


class DataAndDecks(unittest.TestCase):
    def test_read_wrdata(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td, "a.dat")
            p.write_text(" frequency  x\n 1.0 2.0\n 2.0 3.0\n")
            names, rows = ms.read_wrdata(p)
            self.assertEqual(names, ["frequency", "x"])
            self.assertEqual(rows, [[1.0, 2.0], [2.0, 3.0]])
            _, cols = ms.columns(p, 2, [1.0, 2.0])
            self.assertEqual(cols["x"], [2.0, 3.0])
            with self.assertRaises(ValueError):
                ms.columns(p, 3)
            with self.assertRaises(ValueError):
                ms.columns(p, 2, [1.0, 2.5])
            p.write_text(" frequency  x\n 1.0\n")
            with self.assertRaises(ValueError):
                ms.read_wrdata(p)
            p.write_text(" frequency  x\n 1.0 nan\n")
            with self.assertRaises(ValueError):
                ms.read_wrdata(p)
            p.write_text("")
            with self.assertRaises(ValueError):
                ms.read_wrdata(p)

    def test_grids(self):
        self.assertEqual(len(ms.band_freqs()), 11)
        self.assertAlmostEqual(ms.band_freqs()[ms.MID], ms.F_MID)
        self.assertEqual(len(ms.stab_freqs()), 140)
        self.assertAlmostEqual(ms.stab_freqs()[-1] / 1e7, 10 ** (139 / 40))
        with self.assertRaises(ValueError):
            ms.nf_freqs(12)
        self.assertAlmostEqual(ms.nf_freqs(21)[10], ms.F_MID)

    def test_dut_edits(self):
        base = ms.dut_base()
        self.assertIn(".subckt lna vdd vss rfin rfout", base)
        self.assertNotIn("\n.end\n", base)
        t = ms.dut_text(ms.q_parallel_r(1e-9, 10.0), ("ideal", 5e-9, 7.67))
        self.assertIn(ms.LE_LINE, t)            # Le itself is untouched (parallel R)
        self.assertIn("Rle e1 vss", t)
        self.assertNotIn(ms.LC_LINE, t)
        self.assertIn("Rlc lc_x outn 7.67", t)
        t = ms.dut_text(None, ("em", "em5"))
        self.assertIn("XLc vdd outn vss inductor w=6.100u s=3.290u d=110.110u nr_r=5", t)
        self.assertEqual(ms.dut_text(None, None), base)

    def test_decks_render_completely(self):
        a = SimpleNamespace(models_lib="/m/cornerHBT.lib", mos_lib="/m/cornerMOShv.lib", osdi_dir="/o",
                            outdir="/c", snapdir="/s", deckdir="/s", relative_em=False, nf_npts=21)
        char = ms.char_deck(a)
        self.assertNotIn("@@", char)
        for case in ms.CHAR_CASES:
            self.assertIn(f"/c/char_{case}_twoport.dat", char)
        self.assertEqual(char.count("echo \"LESWEEP"), len(ms.LE_SWEEP_NH))
        feed = ms.feed_deck(a)
        self.assertIn("Lfeed b1f b1 1e-06", feed)
        self.assertNotIn(ms.R3B_LINE, feed)
        with self.assertRaises(SystemExit):
            ms.render(ms.TB_FEED, {})

    def test_em_outer_diameter(self):
        # 5-turn: 110.11 + 2*4*(3.29+6.10+0.01) + 2*6.10
        self.assertAlmostEqual(ms.em_outer_diameter_um("em5"), 110.11 + 8 * 9.40 + 12.2)

    def test_feasibility_classes(self):
        lq = {"em1": (0.1e-9, 4.0), "em4": (4.5e-9, 10.3), "em5": (5.5e-9, 8.5)}
        self.assertIn("EM-backed", ms.feasibility(4.6e-9, lq))
        self.assertIn("inside the extracted L range", ms.feasibility(2.0e-9, lq))
        self.assertIn("above the largest", ms.feasibility(8e-9, lq))
        self.assertIn("below the smallest", ms.feasibility(0.05e-9, lq))

    def test_rank_and_rows(self):
        base = {"s11_db_worst": -12, "s22_db_worst": -12, "s21_db_min": 16, "nf290_db_worst": 3.0,
                "mu_bb_min": 1.000001}
        self.assertEqual(sum(ms.row_verdicts(base).values()), 4)
        res = {("lp_power", "q10"): {**base, "nf290_db_worst": 4.0},
               ("hp_power", "q10"): {**base, "s22_db_worst": -5.0, "nf290_db_worst": 2.0},
               ("lp_noise", "q10"): {**base, "nf290_db_worst": 3.3}}
        self.assertEqual(ms.rank_topologies(res), ["lp_noise", "lp_power", "hp_power"])

    def test_parse_log(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td, "x.log")
            p.write_text("OP ic1 0.0039 ic2 0.0039 idd 0.0047 pdc 0.0085\nGAIN mid 20.1\nBENCH_COMPLETE\n")
            self.assertAlmostEqual(ms.parse_log(p)["gt_mid_db"], 20.1)
            p.write_text("OP ic1 0.0039 ic2 0.0039 idd 0.0047 pdc 0.0085\nGAIN mid 20.1\n")
            with self.assertRaises(ValueError):
                ms.parse_log(p)


class CommittedRecordReplay(unittest.TestCase):
    """Every committed record: reduce its retained data into a temp dir and
    compare byte for byte; re-synthesize its candidates from its retained
    characterization data and compare element values."""

    def records(self):
        return sorted(p.name[: -len("-candidates.csv")] for p in (EXP / "records").glob("*-candidates.csv"))

    def test_reduce_replays(self):
        ids = self.records()
        for rid in ids:
            with self.subTest(record=rid), tempfile.TemporaryDirectory() as td:
                a = ["reduce", "--candidates", str(EXP / "netlist-snapshots" / rid / "candidates.json"),
                     "--corners", str(EXP / "corners" / rid),
                     "--candidates-csv", f"{td}/c.csv", "--band-csv", f"{td}/b.csv", "--markdown", f"{td}/h.md"]
                self.assertEqual(ms.main(a), 0)
                self.assertEqual(Path(td, "c.csv").read_bytes(),
                                 (EXP / "records" / f"{rid}-candidates.csv").read_bytes())
                self.assertEqual(Path(td, "b.csv").read_bytes(),
                                 (EXP / "records" / f"{rid}-band.csv").read_bytes())
                self.assertEqual(Path(td, "h.md").read_bytes(),
                                 (EXP / "corners" / rid / "headlines.md").read_bytes())

    def test_synthesis_replays(self):
        for rid in self.records():
            with self.subTest(record=rid):
                doc = json.loads((EXP / "netlist-snapshots" / rid / "candidates.json").read_text())
                data = ms.load_char(EXP / "corners" / rid)
                entries, _ = ms.synthesize(data)
                got = {(e["candidate"], e["qcase"]): e for e in entries}
                for e in doc["candidates"]:
                    g = got[(e["candidate"], e["qcase"])]
                    for k in ("input_values", "zs_target"):
                        for x, y in zip(g[k], e[k]):
                            self.assertTrue(math.isclose(x, y, rel_tol=1e-12), (rid, k, x, y))
                    for k in ("lc", "cp_out", "cs_out"):
                        self.assertTrue(math.isclose(g[k], e[k], rel_tol=1e-12), (rid, k))


if __name__ == "__main__":
    unittest.main()
