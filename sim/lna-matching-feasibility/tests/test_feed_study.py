"""Unit tests for sim/lna-matching-feasibility/feed_study.py (issue #193).

Stdlib-only, PDK-free, no ngspice, single process. Synthetic fixtures for the
tank / sizing / audit / recommendation logic, structural checks of the
generated decks (feed edits, model inclusion, DC-path continuity), rejection of
malformed or missing data, and a deterministic replay of the committed record
(reduce the retained wrdata/logs in a temp copy; compare byte for byte with the
committed CSVs). Never writes under sim/.
"""
from __future__ import annotations

import cmath
import json
import math
import re
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

HERE = Path(__file__).resolve().parent
EXP = HERE.parent
sys.path.insert(0, str(EXP))
import feed_study as fs  # noqa: E402
import matching_solver as ms  # noqa: E402


def committed_record() -> str:
    ids = sorted(p.name[: -len("-feeds.csv")] for p in (EXP / "records").glob("*-feeds.csv"))
    assert ids, "no committed feed-study record"
    return ids[-1]


RID = committed_record()
PLAN = json.loads((EXP / "netlist-snapshots" / RID / "feed_plan.json").read_text())["plan"]
ARGS = SimpleNamespace(models_lib="/m/cornerHBT.lib", mos_lib="/m/cornerMOShv.lib", osdi_dir="/o",
                       cap_lib="/m/cornerCAP.lib", outdir="/c", nf_npts=21, snapdir="/s", deckdir="/s",
                       relative_em=False)


class Declaration(unittest.TestCase):
    def test_committed_declaration_matches_code(self):
        self.assertEqual((EXP / "feed-study-declaration.md").read_text(), fs.declaration_text())

    def test_candidate_set_is_declared_and_separates_the_bound(self):
        roles = {n: v["role"] for n, v in fs.VARIANTS.items()}
        self.assertEqual(roles["committed"], "baseline")
        self.assertEqual(roles["ideal_choke"], "diagnostic bound")
        finite = [n for n, v in fs.VARIANTS.items() if v["role"] == "finite candidate"]
        self.assertTrue(finite)
        for n, v in fs.VARIANTS.items():
            if v["kind"] == "tank":
                self.assertIn(v["geom"], ms.EM_GEOMS)          # EM geometries only, no scaled ideal L
        self.assertIn("em1", fs.EXCLUDED)


class TankMath(unittest.TestCase):
    def test_tune_c_resonates_lc(self):
        w = 2 * math.pi * 2.44175e9
        y = 1 / (1j * w * 5e-9) + 0.0005               # inductive branch with some loss
        c = fs.tune_c(y, 2.44175e9)
        self.assertAlmostEqual(c, 1 / (w * w * 5e-9), delta=1e-18)
        self.assertAlmostEqual(fs.tank_admittance(y, c, 2.44175e9).imag, 0.0, delta=1e-12)

    def test_tune_c_rejects_capacitive_branch(self):
        with self.assertRaises(ValueError):
            fs.tune_c(complex(1e-3, 5e-3), 2.44e9)

    def test_resonance_found_and_classified(self):
        l, c = 5e-9, 1e-12
        f0 = 1 / (2 * math.pi * math.sqrt(l * c))
        fr = fs.dec_freqs(200, 1e7, 3e10)
        ys = [1 / (1j * 2 * math.pi * f * l) + 1e-3 for f in fr]
        res = fs.tank_resonances(fr, ys, c)
        self.assertEqual(len(res), 1)
        self.assertEqual(res[0]["kind"], "parallel")
        self.assertAlmostEqual(res[0]["f_hz"] / f0, 1.0, delta=2e-3)
        self.assertAlmostEqual(res[0]["z_mag_ohm"], 1000.0, delta=15.0)   # 1/G at the peak
        # a series resonance is reported as such (Im Y falls through zero)
        ys2 = [1 / complex(0.5, 2 * math.pi * f * 1e-9 - 1 / (2 * math.pi * f * 4.2e-12)) for f in fr]
        kinds = [r["kind"] for r in fs.tank_resonances(fr, ys2, 1e-30)]
        self.assertEqual(kinds.count("series"), 1)

    def test_resonances_reject_bad_grids(self):
        with self.assertRaises(ValueError):
            fs.tank_resonances([1e9], [1j], 1e-12)
        with self.assertRaises(ValueError):
            fs.tank_resonances([1e9, 2e9], [1j], 1e-12)

    def test_esr_and_q(self):
        w = 2 * math.pi * ms.F_MID
        self.assertAlmostEqual(fs.esr_for_q(1e-12, 30.0), 1 / (w * 1e-12 * 30))
        for bad in ((0, 1e-12), (30, 0), (-1, 1e-12)):
            with self.assertRaises(ValueError):
                fs.esr_for_q(bad[1], bad[0])

    def test_cmim_sizing_roundtrip(self):
        for c in (0.2e-12, 0.77356e-12, 0.95381e-12, 5e-12):
            self.assertAlmostEqual(fs.cmim_cap_f(fs.cmim_side_for(c)), c, delta=1e-6 * c)
        for bad in (0, -1e-12, float("nan"), float("inf")):
            with self.assertRaises(ValueError):
                fs.cmim_side_for(bad)

    def test_dec_freqs_match_ngspice_grid(self):
        fr = fs.dec_freqs(200, 1e7, 3e10)
        self.assertEqual(len(fr), 696)
        self.assertEqual(fr[0], 1e7)
        self.assertAlmostEqual(fr[-1], 3e10, delta=1e-3)
        self.assertAlmostEqual(fr[1], 10115865.635, delta=1e-2)    # value ngspice-46 wrote in the record


class FeedEdits(unittest.TestCase):
    def test_committed_is_untouched(self):
        self.assertEqual(fs.feed_lines("committed", None), ms.R3B_LINE)
        self.assertEqual(fs.feed_includes("committed", "/cap"), "* (no EM inductor / MIM capacitor in this variant)")

    def test_choke_variant(self):
        t = fs.feed_lines("ideal_choke", None)
        self.assertIn("R3b bref b1f 330 m=1", t)
        self.assertIn("Lfeed b1f b1 1e-06", t)
        self.assertNotIn("inductor", t)

    def test_every_tank_keeps_r3b_and_adds_the_em_spiral(self):
        for n, v in fs.VARIANTS.items():
            if v["kind"] != "tank":
                continue
            t = fs.feed_lines(n, PLAN)
            self.assertIn("R3b bref b1f 330 m=1", t, n)             # R3b retained, same value
            g = v["geom"]
            self.assertIn(f"XLfeed b1f b1 vss {ms.em_instance(g)}", t, n)   # existing EM geometry, not a scaled L
            self.assertIn(f".include \"{ms.EM_MODEL}\"", fs.feed_includes(n, "/cap"), n)

    def test_capacitor_models(self):
        self.assertRegex(fs.feed_lines("em5_cideal", PLAN), r"Cfeed b1f b1 7\.7")
        self.assertNotIn("cap_cmim", fs.feed_lines("em5_cideal", PLAN))
        cm = fs.feed_lines("em5_cmim", PLAN)
        self.assertRegex(cm, r"XCfeed b1f b1 cap_cmim w=22\.\d+u l=22\.\d+u")
        self.assertIn('.lib "/cap/cornerCAP.lib" cap_typ', fs.feed_includes("em5_cmim", "/cap/cornerCAP.lib"))
        self.assertNotIn("cornerCAP", fs.feed_includes("em5_cideal", "/cap/cornerCAP.lib"))
        bp = fs.feed_lines("em5_cmim_bp10", PLAN)
        self.assertRegex(bp, r"Cbpfeed b1 vss 7\.7\d+e-14")           # 10 % of the tuning C at the base node
        q = fs.feed_lines("em5_cq30", PLAN)
        self.assertIn("Rcfeed cf_x b1", q)
        esr = float(re.search(r"Rcfeed cf_x b1 (\S+)", q).group(1))
        self.assertAlmostEqual(esr, fs.esr_for_q(PLAN["c_tune_f"]["em5"], 30.0), delta=1e-5 * esr)

    def test_tank_without_plan_or_with_partial_plan_is_rejected(self):
        with self.assertRaises(ValueError):
            fs.feed_lines("em5_cideal", None)
        with self.assertRaises(ValueError):
            fs.feed_lines("em5_cideal", {"c_tune_f": {}})
        with self.assertRaises(KeyError):
            fs.feed_lines("em5_cideal", {"c_tune_f": {}, "cmim_side_um": {}})

    def test_scan_decks_render_and_keep_a_dc_path(self):
        for n in fs.VARIANTS:
            with self.subTest(variant=n):
                deck = fs.scan_deck(ARGS, n, PLAN)
                self.assertNotIn("@@", deck)
                self.assertEqual(deck.count("R3b bref "), 1)
                self.assertTrue(fs.dc_connected(deck, "bref", "b1"))
                has_em = f'.include "{ms.EM_MODEL}"' in deck
                self.assertEqual(has_em, fs.VARIANTS[n]["kind"] == "tank")
                self.assertEqual("cap_typ" in deck, fs.VARIANTS[n].get("cap") == "cmim")
                self.assertIn(f"scan_{n}.inband.dat", deck)
        # the committed deck is the committed DUT: its only feed line is the original R3b
        committed = fs.scan_deck(ARGS, "committed", PLAN)
        self.assertIn(ms.R3B_LINE, committed)
        self.assertNotIn("BENCH EDIT (issue #193", committed)

    def test_dc_path_continuity_checker(self):
        good = fs.scan_deck(ARGS, "em5_cideal", PLAN)
        self.assertTrue(fs.dc_connected(good, "bref", "b1"))
        fs.assert_feed_dc_path(good)
        # remove the inductor: a capacitor alone does not carry Q1's base current
        broken = "\n".join(ln for ln in good.splitlines() if not ln.startswith("XLfeed"))
        self.assertFalse(fs.dc_connected(broken, "bref", "b1"))
        with self.assertRaises(ValueError):
            fs.assert_feed_dc_path(broken)
        # the inductor model is DC-transparent only through the XL subcircuit instance
        self.assertFalse(fs.dc_connected("Cfeed b1f b1 1p\nR3b bref b1f 330\n", "bref", "b1"))
        self.assertTrue(fs.dc_connected("R3b bref b1f 330\nLfeed b1f b1 1u\n", "bref", "b1"))

    def test_apply_feed_on_characterization_and_verify_decks(self):
        char = ms.char_deck(ARGS)
        out = fs.apply_feed(char, "em5_cmim", PLAN, "/m/cornerCAP.lib")
        self.assertEqual(len(re.findall(r'^\.include ".*sg13g2_inductor_em\.spice"', out, re.M)), 1)
        self.assertEqual(out.count(".lib \"/m/cornerCAP.lib\" cap_typ"), 1)
        self.assertEqual(out.count("XLfeed"), 1)
        self.assertNotIn(f"\n{ms.R3B_LINE}\n", out)
        with self.assertRaises(ValueError):
            fs.apply_feed("no feed here\n.options temp=27 tnom=27 gmin=1e-10\n", "ideal_choke", None, "/c")
        with self.assertRaises(ValueError):
            fs.apply_feed(ms.R3B_LINE + "\n", "em5_cmim", PLAN, "/c")     # no .options anchor


class DcAudit(unittest.TestCase):
    LINE = ("DC ic1 0.0039403 ic2 0.0039348 ib1 5.43e-06 vb1 0.8435 ve1 0 vcasc 0.8027 voutn 1.8 "
            "vb2 1.65 vbref 0.8453 idd 0.0047 pdc 0.0085\nBENCH_COMPLETE\n")

    def _log(self, td, text):
        p = Path(td, "x.log")
        p.write_text(text)
        return p

    def test_parse_and_derived(self):
        with tempfile.TemporaryDirectory() as td:
            a = fs.parse_dc_audit(self._log(td, self.LINE))
        self.assertAlmostEqual(a["vbe1"], 0.8435)
        self.assertAlmostEqual(a["vce1"], 0.8027)
        self.assertAlmostEqual(a["vce2"], 1.8 - 0.8027)
        self.assertAlmostEqual(a["vbc1"], 0.8435 - 0.8027)
        self.assertAlmostEqual(a["vfeed_drop"], 0.0018)

    def test_malformed_logs_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            for bad in (self.LINE.replace("BENCH_COMPLETE\n", ""),                 # no marker
                        "BENCH_COMPLETE\n",                                          # no audit line
                        self.LINE.replace(" ib1 5.43e-06", ""),                      # missing key
                        self.LINE.replace("ic1 0.0039403", "ic1 nan"),               # non-finite
                        self.LINE.replace("pdc 0.0085", "pdc")):                     # odd token count
                with self.assertRaises(ValueError, msg=bad):
                    fs.parse_dc_audit(self._log(td, bad))
            with self.assertRaises(FileNotFoundError):
                fs.parse_dc_audit(Path(td, "missing.log"))

    def test_flags(self):
        with tempfile.TemporaryDirectory() as td:
            base = fs.parse_dc_audit(self._log(td, self.LINE))
        self.assertEqual(fs.dc_flags(base, base), [])
        shifted = {**base, "ic1": base["ic1"] * 0.97, "idd": base["idd"]}
        self.assertTrue(any(f.startswith("DC_BIAS_SHIFT_IC1") for f in fs.dc_flags(shifted, base)))
        small = {**base, "ic1": base["ic1"] * 0.995}
        self.assertEqual(fs.dc_flags(small, base), [])
        sat = {**base, "vce1": 0.1, "vbc2": 0.6}
        flags = fs.dc_flags(sat, base)
        self.assertTrue(any(f.startswith("NEAR_SATURATION_Q1") for f in flags))
        self.assertTrue(any(f.startswith("BC_FORWARD_Q2") for f in flags))
        self.assertTrue(any("NONPOSITIVE" in f for f in fs.dc_flags({**base, "ic2": 0.0}, base)))


class Recommendation(unittest.TestCase):
    SCAN = {"dc_flags": [], "convergence": {"normal": True}, "nfmin290_worst_db": 0.9}
    MATCH = {"nf290_db_worst": 1.1, "s11_db_worst": -11.0, "s22_db_worst": -14.0, "s21_db_min": 18.0,
             "mu_bb_min": 1.0000004, "convergence": {"normal": True}}

    def test_go(self):
        r = fs.recommend(self.SCAN, self.MATCH)
        self.assertEqual(r["verdict"], "GO")
        self.assertIsNone(r["binding"])
        self.assertAlmostEqual(r["limit_db"], 1.2)

    def test_binding_constraint_order(self):
        r = fs.recommend({**self.SCAN, "nfmin290_worst_db": 1.51}, {**self.MATCH, "nf290_db_worst": 2.6})
        self.assertEqual((r["verdict"], r["binding"]), ("NO-GO", "noise_floor"))
        r = fs.recommend(self.SCAN, {**self.MATCH, "nf290_db_worst": 1.8})
        self.assertEqual(r["binding"], "noise_match_penalty")
        r = fs.recommend(self.SCAN, {**self.MATCH, "nf290_db_worst": 1.35})
        self.assertEqual(r["binding"], "noise_margin")
        r = fs.recommend({**self.SCAN, "dc_flags": ["DC_BIAS_SHIFT_IC1 (+3 %)"]}, {**self.MATCH, "s11_db_worst": -8.0})
        self.assertEqual(r["failing"], ["dc_validity", "s11"])
        self.assertEqual(r["binding"], "dc_validity")
        r = fs.recommend(self.SCAN, {**self.MATCH, "mu_bb_min": 0.9999})
        self.assertEqual(r["failing"], ["stability"])
        # a table-resolution wobble around 1 is not a resolved deficit
        self.assertEqual(fs.recommend(self.SCAN, {**self.MATCH, "mu_bb_min": 1.0 - 5e-10})["verdict"], "GO")
        r = fs.recommend(self.SCAN, {**self.MATCH, "convergence": {"normal": False}})
        self.assertEqual(r["binding"], "convergence")

    def test_no_valid_feed_is_no_go(self):
        r = fs.recommend(None, None)
        self.assertEqual((r["verdict"], r["binding"]), ("NO-GO", "dc_validity"))

    def test_policy_margin_is_a_parameter(self):
        r = fs.recommend(self.SCAN, {**self.MATCH, "nf290_db_worst": 1.4}, margin_db=0.05)
        self.assertEqual(r["verdict"], "GO")

    def test_select_best(self):
        def res(nf, flags=(), normal=True):
            return {"summary": {"nfmin290_worst_db": nf, "dc_flags": list(flags), "convergence": {"normal": normal}}}
        results = {n: res(2.4) for n in fs.VARIANTS}
        results["ideal_choke"] = res(0.4)                     # bound is never selected
        results["em5_cq30"] = res(0.5)                        # bracket is never selected
        results["em5_cideal"] = res(1.5)
        results["em4_cideal"] = res(1.4, flags=["DC_BIAS_SHIFT_IC1 (-2 %)"])      # invalid: skipped
        results["em4_cmim"] = res(1.3, normal=False)                                # fallback: skipped
        self.assertEqual(fs.select_best(results, PLAN), "em5_cideal")
        for n in ("em5_cideal", "em5_cmim", "em4_cideal", "em4_cmim"):
            results[n] = res(1.0, flags=["X"])
        self.assertIsNone(fs.select_best(results, PLAN))


class ReplayAndRejection(unittest.TestCase):
    def _copy(self, td) -> tuple:
        corn = Path(td, "corners")
        shutil.copytree(EXP / "corners" / RID, corn)
        snap = Path(td, "snap")
        shutil.copytree(EXP / "netlist-snapshots" / RID, snap)
        return snap, corn

    def test_committed_scan_replays_byte_for_byte_and_deterministically(self):
        for _ in range(2):
            with tempfile.TemporaryDirectory() as td:
                snap, corn = self._copy(td)
                rc = fs.main(["scan-reduce", "--snapdir", str(snap), "--corners", str(corn),
                              "--csv", f"{td}/f.csv", "--band-csv", f"{td}/b.csv", "--markdown", f"{td}/s.md"])
                self.assertEqual(rc, 0)
                self.assertEqual(Path(td, "f.csv").read_bytes(), (EXP / "records" / f"{RID}-feeds.csv").read_bytes())
                self.assertEqual(Path(td, "b.csv").read_bytes(), (EXP / "records" / f"{RID}-feeds-band.csv").read_bytes())
                self.assertEqual(Path(td, "s.md").read_bytes(), (corn / "scan_headlines.md").read_bytes())

    def test_committed_match_replays_byte_for_byte(self):
        with tempfile.TemporaryDirectory() as td:
            snap, corn = self._copy(td)
            rc = fs.main(["match-reduce", "--snapdir", str(snap), "--corners", str(corn),
                          "--csv", f"{td}/m.csv", "--markdown", f"{td}/m.md"])
            self.assertEqual(rc, 0)
            self.assertEqual(Path(td, "m.csv").read_bytes(), (EXP / "records" / f"{RID}-match.csv").read_bytes())
            self.assertEqual(Path(td, "m.md").read_bytes(), (corn / "match_headlines.md").read_bytes())
            self.assertEqual(json.loads((corn / "recommendation.json").read_text()),
                             json.loads((EXP / "corners" / RID / "recommendation.json").read_text()))

    def test_committed_evidence_honors_the_declared_policy(self):
        doc = json.loads((EXP / "corners" / RID / "scan_summary.json").read_text())
        self.assertEqual(set(doc["variants"]), set(fs.VARIANTS))
        base = doc["variants"]["committed"]["audit"]
        for n, s in doc["variants"].items():
            self.assertEqual(s["dc_flags"], fs.dc_flags(s["audit"], base), n)
            self.assertTrue(s["convergence"]["normal"], n)
        # the committed feed reproduces the #186 diagnostic the study starts from
        self.assertAlmostEqual(doc["variants"]["committed"]["nfmin290_mid_db"], 2.445, delta=0.005)
        self.assertAlmostEqual(doc["variants"]["ideal_choke"]["nfmin290_mid_db"], 0.467, delta=0.005)
        self.assertEqual(doc["best_valid_feed"], fs.select_best(
            {n: {"summary": s} for n, s in doc["variants"].items()}, PLAN))

    def test_missing_and_malformed_data_rejected(self):
        victims = ("scan_em5_cideal.stab.dat", "scan_em5_cideal.inband.dat", "scan_em5_cideal.nf290.dat",
                   "scan_em5_cideal.log")
        for victim in victims:
            with self.subTest(missing=victim), tempfile.TemporaryDirectory() as td:
                _, corn = self._copy(td)
                (corn / victim).unlink()
                with self.assertRaises(FileNotFoundError):
                    fs.reduce_scan_variant(corn, "em5_cideal", 21)
        with self.subTest("truncated"), tempfile.TemporaryDirectory() as td:
            _, corn = self._copy(td)
            p = corn / "scan_em5_cideal.stab.dat"
            lines = p.read_text().splitlines()
            p.write_text("\n".join(lines[:-3]) + "\n")
            with self.assertRaises(ValueError):
                fs.reduce_scan_variant(corn, "em5_cideal", 21)
        with self.subTest("nonfinite"), tempfile.TemporaryDirectory() as td:
            _, corn = self._copy(td)
            p = corn / "scan_em5_cideal.inband.dat"
            lines = p.read_text().splitlines()
            lines[3] = lines[3].replace(lines[3].split()[2], "nan", 1)
            p.write_text("\n".join(lines) + "\n")
            with self.assertRaises(ValueError):
                fs.reduce_scan_variant(corn, "em5_cideal", 21)
        with self.subTest("no-marker"), tempfile.TemporaryDirectory() as td:
            _, corn = self._copy(td)
            p = corn / "scan_em5_cideal.log"
            p.write_text(p.read_text().replace("BENCH_COMPLETE", "BENCH_DONE"))
            with self.assertRaises(ValueError):
                fs.reduce_scan_variant(corn, "em5_cideal", 21)
        with self.subTest("tune-sign"), tempfile.TemporaryDirectory() as td:
            _, corn = self._copy(td)
            p = corn / "tune_yser_mid.dat"
            rows = p.read_text().splitlines()
            cols = rows[1].split()
            cols[1] = "-" + cols[1].lstrip("-")                      # flip Re(Yser) of em1
            rows[1] = " ".join(cols)
            p.write_text("\n".join(rows) + "\n")
            with self.assertRaises(ValueError):
                fs.load_tune(corn)

    def test_reduce_scan_flags_convergence_fallback(self):
        with tempfile.TemporaryDirectory() as td:
            _, corn = self._copy(td)
            p = corn / "scan_em4_cmim.log"
            p.write_text(p.read_text() + "\nNote: Transient op started\n")
            results, problems = fs.reduce_scan(corn, PLAN, 21)
            self.assertTrue(any("em4_cmim" in x and "convergence" in x for x in problems))
            self.assertNotEqual(fs.select_best(results, PLAN), "em4_cmim")

    def test_tuning_table_matches_measured_parasitic_inclusive_admittance(self):
        tune = fs.load_tune(EXP / "corners" / RID)
        plan = fs.make_plan(tune)
        self.assertEqual(plan["c_tune_f"], PLAN["c_tune_f"])
        for g in ("em4", "em5"):
            c = plan["c_tune_f"][g]
            y = fs.tank_admittance(tune[g]["y_mid"], c, ms.F_MID)
            self.assertAlmostEqual(y.imag, 0.0, delta=1e-12)           # tuned at f_mid, Cser already inside Yser
            self.assertAlmostEqual(fs.cmim_cap_f(plan["cmim_side_um"][g]), c, delta=1e-6 * c)
        # em1 cannot form a useful tank: tens of pF and a few Ohm of peak impedance
        self.assertGreater(plan["geoms"]["em1"]["c_tune_pf"], 20.0)
        self.assertLess(plan["geoms"]["em1"]["rp_alone_ohm"], 20.0)


if __name__ == "__main__":
    unittest.main()
