"""Unit tests for sim/lna-matching-feasibility/le_study.py and the explicit-Le
plumbing in matching_solver.py (issue #198).

Stdlib-only, PDK-free, no ngspice, single process. Covers: exact Le targeting
in every generated deck, loss values recomputed from the selected Le, the
historical (1 nH) decks re-rendered byte for byte from the committed #186 /
#193 snapshots, rejection of invalid / missing outputs, the declared shortlist
/ go-no-go / control rules on synthetic fixtures, and a deterministic replay of
the committed #198 record. Never writes under sim/.
"""
from __future__ import annotations

import csv
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
import le_study as ls  # noqa: E402
import matching_solver as ms  # noqa: E402

ARGS = SimpleNamespace(models_lib="/m/cornerHBT.lib", mos_lib="/m/cornerMOShv.lib", osdi_dir="/o",
                       cap_lib="/m/cornerCAP.lib", outdir="/c", nf_npts=21, snapdir="/s", deckdir="/s",
                       relative_em=False)
PLAN = ls.prior_feed_plan()
W = 2 * math.pi * ms.F_MID


def prior_entry(feed="em5_cideal"):
    mp = json.loads((ls.PRIOR_SNAP / "match_plan.json").read_text())
    return dict(next(e for e in mp["candidates"] if e["feed_variant"] == feed))


class Declaration(unittest.TestCase):
    def test_committed_declaration_matches_code(self):
        self.assertEqual((EXP / "le-study-declaration.md").read_text(), ls.declaration_text())

    def test_point_set_budget_and_order(self):
        pts = ls.study_points()
        ids = [p["id"] for p in pts]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertEqual(len(pts), 13)
        self.assertLessEqual(ls.planned_decks(), ls.DECK_BUDGET)
        self.assertEqual(ls.planned_decks(), 28)
        # controls first, all at 1 nH, exactly the three feeds #193 verified
        n_ctl = sum(p["control"] for p in pts)
        self.assertTrue(all(p["control"] for p in pts[:n_ctl]))
        self.assertEqual({p["feed"] for p in pts if p["control"]}, set(ls.CONTROL_FEEDS))
        self.assertTrue(all(p["le_nh"] == 1.0 for p in pts if p["control"]))
        for feed in ls.FEEDS:
            self.assertEqual(sorted(p["le_nh"] for p in pts if p["feed"] == feed), list(ls.LE_POINTS_NH))
        for p in pts:
            self.assertIn(p["feed"], fs.VARIANTS)
        self.assertEqual(fs.VARIANTS[ls.FINITE_FEED]["cap"], "cmim")      # the PDK cap_cmim feed
        self.assertEqual(fs.VARIANTS["ideal_choke"]["role"], "diagnostic bound")

    def test_tags(self):
        self.assertEqual(ls.le_tag(0.1), "le0p10")
        self.assertEqual(ls.point_id("em5_cmim", 1.0), "em5_cmim_le1p00")
        for bad in (0, -0.3, float("nan"), float("inf")):
            with self.assertRaises(ValueError):
                ls.le_tag(bad)


class ExplicitLe(unittest.TestCase):
    def test_le_line(self):
        self.assertEqual(ms.le_line(), ms.LE_LINE)
        self.assertEqual(ms.le_line(1.0), ms.LE_LINE)
        self.assertEqual(ms.le_line(0.3), "Le e1 vss 0.3n m=1")
        for bad in (0, -1, float("nan"), float("inf")):
            with self.assertRaises(ValueError):
                ms.le_line(bad)

    def test_dut_text_defaults_unchanged_and_loss_exclusive(self):
        base = ms.dut_base()
        self.assertEqual(ms.dut_text(None, None), base)
        self.assertEqual(ms.dut_text(None, None, 1.0), base)
        t = ms.dut_text(None, None, 0.6)
        self.assertEqual(ls.le_elements(t), [("vss", 0.6)])
        self.assertIn("BENCH EDIT (issue #198): Le = 0.6 nH", t)
        with self.assertRaises(ValueError):
            ms.dut_text(100.0, None, 0.3, le_rs=0.5)
        for bad in (0.0, -1.0, float("inf")):
            with self.assertRaises(ValueError):
                ms.dut_text(None, None, 0.3, le_rs=bad)
        s = ms.dut_text(None, None, 0.3, le_rs=0.46)
        self.assertEqual(ls.le_elements(s), [("le_x", 0.3)])
        self.assertIn("Rles le_x vss 0.46", s)
        self.assertNotIn("Rle e1", s)

    def test_char_decks_target_le_exactly(self):
        for p in ls.study_points():
            with self.subTest(point=p["id"]):
                deck = ls.render_char(ARGS, p, PLAN)
                self.assertNotIn("@@", deck)
                self.assertEqual(ls.le_elements(deck), [("vss", p["le_nh"])])
                self.assertNotIn("alter l.xa.le", deck)                   # no 1 nH reset
                self.assertNotIn("LESWEEP", deck)
                for case, q in ls.CHAR_CASES_LE.items():
                    r = ms.R_IDEAL_PLACEHOLDER if q is None else q * W * p["le_nh"] * 1e-9
                    self.assertIn(f"alter r.xa.rle = {r:.6g}\n", deck)
                    self.assertIn(f"/c/charset/{p['id']}/char_{case}_twoport.dat", deck)
                self.assertTrue(fs.dc_connected(deck, "bref", "b1"))
                self.assertEqual("cap_typ" in deck, p["feed"] == "em5_cmim")

    def test_check_le_deck_rejects_stale_or_wrong(self):
        p = {"id": "em5_cmim_le0p30", "feed": "em5_cmim", "le_nh": 0.3}
        deck = ls.render_char(ARGS, p, PLAN)
        ls.check_le_deck(deck, 0.3, "char")
        with self.assertRaises(ValueError):
            ls.check_le_deck(deck, 0.6, "char")                            # wrong target
        with self.assertRaises(ValueError):                                # stale committed line kept
            ls.check_le_deck(deck.replace("Le e1 vss 0.3n m=1", "Le e1 vss 0.3n m=1\n" + ms.LE_LINE), 0.3, "char")
        with self.assertRaises(ValueError):                                # loss computed from 1 nH
            r = ms.q_parallel_r(0.3e-9, 10.0)
            ls.check_le_deck(deck.replace(f"alter r.xa.rle = {r:.6g}", f"alter r.xa.rle = {ms.q_parallel_r(1e-9, 10.0):.6g}"),
                             0.3, "char")
        with self.assertRaises(ValueError):                                # Le sweep that resets Le
            ls.check_le_deck(deck + "alter l.xa.le = 1e-09\n", 0.3, "char")
        with self.assertRaises(ValueError):
            ls.check_le_deck(deck, 0.3, "other")

    def test_verify_loss_consistent_with_selected_le(self):
        base = prior_entry()
        for le in ls.LE_POINTS_NH:
            for q, loss in ((10.0, "parallel"), (5.0, "parallel"), (10.0, "series")):
                with self.subTest(le=le, q=q, loss=loss):
                    e = {**base, "le_nh": le, "le_q": q, "le_loss": loss, "stem": "x"}
                    deck = ls.render_verify(ARGS, e, PLAN)
                    if loss == "parallel":
                        r = float(re.search(r"^Rle e1 vss (\S+)$", deck, re.M).group(1))
                        self.assertAlmostEqual(r / (W * le * 1e-9), q, delta=1e-4 * q)       # Q = R/(wL)
                        self.assertEqual(ls.le_elements(deck), [("vss", le)])
                    else:
                        r = float(re.search(r"^Rles le_x vss (\S+)$", deck, re.M).group(1))
                        self.assertAlmostEqual(W * le * 1e-9 / r, q, delta=1e-4 * q)       # Q = wL/R
                        self.assertEqual(ls.le_elements(deck), [("le_x", le)])
                    # the Le-Q override touches Le only: input inductor and Lc keep Q = 10
                    self.assertIn(f"Rlb lb_x xin {base['input_r']:.6g}", deck)
                    self.assertIn(f"Rlc lc_x outn {base['r_lc']:.6g}", deck)
                    self.assertEqual(deck.count('echo "DC ic1'), 1)
        with self.assertRaises(ValueError):
            ms.verify_deck(ARGS, {**base, "le_loss": "shunt"}, "x")

    def test_check_le_deck_verify_mismatch(self):
        e = {**prior_entry(), "le_nh": 0.3, "stem": "x"}
        deck = ms.verify_deck(ARGS, e, "x")
        ls.check_le_deck(deck, 0.3, "verify", 10.0, "parallel")
        with self.assertRaises(ValueError):
            ls.check_le_deck(deck, 0.3, "verify", 5.0, "parallel")
        with self.assertRaises(ValueError):
            ls.check_le_deck(deck, 0.3, "verify", 10.0, "series")
        with self.assertRaises(ValueError):
            ls.check_le_deck(deck, 0.3, "verify", None)

    def test_dc_audit_is_print_only(self):
        e = {**prior_entry(), "le_nh": 0.6, "stem": "x"}
        raw = fs.apply_feed(ms.verify_deck(ARGS, e, "x"), "em5_cmim", PLAN, ARGS.cap_lib)
        out = ls.add_dc_audit(raw)
        added = [ln for ln in out.splitlines() if ln not in set(raw.splitlines())]
        self.assertTrue(added)
        self.assertTrue(all(ln.startswith(("let ", "echo ", "*")) for ln in added), added)
        with self.assertRaises(ValueError):
            ls.add_dc_audit("no op line\n")
        with self.assertRaises(ValueError):
            ls.add_dc_audit(raw + ls.OP_ANCHOR)


def _paths(text):
    g = lambda rx: re.search(rx, text, re.M).group(1)  # noqa: E731
    em = re.search(r'^\.include "(\S+sg13g2_inductor_em\.spice)"$', text, re.M)
    cap = re.search(r'^\.lib "(\S+)" cap_typ$', text, re.M)
    return SimpleNamespace(models_lib=g(r'^\.lib "(\S+)" hbt_typ$'), mos_lib=g(r'^\.lib "(\S+)" mos_tt$'),
                           osdi_dir=g(r"^pre_osdi (\S+)/psp103\.osdi$"), em=em.group(1) if em else None,
                           cap_lib=cap.group(1) if cap else "/unused/cornerCAP.lib",
                           wr=g(r"^wrdata (\S+)/\S+ "))


class HistoricalDecksUnchanged(unittest.TestCase):
    """The explicit-Le plumbing at its defaults re-renders the committed #186
    and #193 decks byte for byte (absolute paths taken from each snapshot)."""

    def setUp(self):
        self._em = ms.EM_MODEL

    def tearDown(self):
        ms.EM_MODEL = self._em

    def _args(self, text, snapdir):
        p = _paths(text)
        if p.em:
            ms.EM_MODEL = Path(p.em)
        return SimpleNamespace(models_lib=p.models_lib, mos_lib=p.mos_lib, osdi_dir=p.osdi_dir, outdir=p.wr,
                               deckdir=snapdir, relative_em=False, nf_npts=21, cap_lib=p.cap_lib)

    def test_feed_study_decks(self):
        snap = ls.PRIOR_SNAP
        plan = PLAN
        n = 0
        for deck in sorted(snap.glob("char_*.spice")):
            feed = deck.stem[len("char_"):]
            want = deck.read_text()
            a = self._args(want, str(snap))
            self.assertEqual(fs.apply_feed(ms.char_deck(a), feed, plan, a.cap_lib), want, deck.name)
            n += 1
        mp = json.loads((snap / "match_plan.json").read_text())
        for e in mp["candidates"]:
            want = (snap / f"{e['stem']}.spice").read_text()
            a = self._args(want, str(snap))
            got = fs.apply_feed(ms.verify_deck(a, e, e["stem"]), e["feed_variant"], plan, a.cap_lib)
            self.assertEqual(got, want, e["stem"])
            n += 1
        self.assertEqual(n, 6)

    def test_matching_study_decks(self):
        """#190's DC-reference decks come from the current verify template. #186's
        (record 20261010-201010-6aca84c) predate #190's template header and are
        replayed through their retained data instead (test_matching_solver)."""
        snap = EXP / "netlist-snapshots" / "20261010-213251-3ccb391"
        doc = json.loads((snap / "candidates.json").read_text())
        n = 0
        for e in doc["candidates"]:
            if e.get("infeasible") or not (snap / f"{e['stem']}.spice").exists():
                continue
            with self.subTest(stem=e["stem"]):
                want = (snap / f"{e['stem']}.spice").read_text()
                a = self._args(want, str(snap))
                self.assertEqual(ms.verify_deck(a, e, e["stem"]), want)
                n += 1
        self.assertEqual(n, 8)
        old = (EXP / "netlist-snapshots" / "20261010-201010-6aca84c" / "verify_lp_noise_q10.spice").read_text()
        self.assertNotIn("DC reference (issue #190)", old)

    def test_fixed_le_synthesis_replays_feed_record(self):
        """The restricted-set synthesis this study uses reproduces #193's
        match_plan input/output values from #193's retained characterizations."""
        mp = json.loads((ls.PRIOR_SNAP / "match_plan.json").read_text())
        for e in mp["candidates"]:
            data = ms.load_char(ls.PRIOR_CORNERS / "charset" / e["feed_variant"], require_feed=False,
                                char_cases={"ideal": None, "q10": 10.0}, require_sweep=False)
            got, _ = ms.synthesize(data, le_nh=1.0, candidates={"lp_noise": ms.CANDIDATES["lp_noise"]},
                                   qcases={"q10": ms.QCASES["q10"]}, char_cases={"ideal": None, "q10": 10.0})
            self.assertNotIn("le_nh", got[0])                           # default Le leaves the entry historical
            for k in ("input_values", "zs_target"):
                for x, y in zip(got[0][k], e[k]):
                    self.assertTrue(math.isclose(x, y, rel_tol=1e-12), (e["feed_variant"], k))
            for k in ("cp_out", "cs_out"):
                self.assertTrue(math.isclose(got[0][k], e[k], rel_tol=1e-12))

    def test_le_feasibility_uses_selected_le(self):
        data = ms.load_char(ls.PRIOR_CORNERS / "charset" / "committed", require_feed=False,
                            char_cases={"ideal": None, "q10": 10.0}, require_sweep=False)
        got, em_lq = ms.synthesize(data, le_nh=0.1, candidates={"lp_noise": ms.CANDIDATES["lp_noise"]},
                                   qcases={"q10": ms.QCASES["q10"]}, char_cases={"ideal": None, "q10": 10.0})
        self.assertEqual(got[0]["le_nh"], 0.1)
        self.assertEqual(got[0]["feasibility"]["Le"], ms.feasibility(0.1e-9, em_lq))
        self.assertNotEqual(got[0]["feasibility"]["Le"], ms.feasibility(1e-9, em_lq))


class MissingAndInvalidOutputs(unittest.TestCase):
    def test_char_without_declared_case_is_rejected(self):
        # #193's charsets have no q5 case: loading them with this study's cases must fail
        with self.assertRaises(FileNotFoundError):
            ls.solve_point(ls.PRIOR_CORNERS / "charset" / "committed",
                           {"id": "committed_le1p00", "feed": "committed", "le_nh": 1.0})

    def test_truncated_or_nonfinite_char_tables(self):
        src = ls.PRIOR_CORNERS / "charset" / "committed"
        for how in ("truncate", "nan", "marker"):
            with self.subTest(how=how), tempfile.TemporaryDirectory() as td:
                d = Path(td, "c")
                shutil.copytree(src, d)
                shutil.copy(d / "char_q20_twoport.dat", d / "char_q5_twoport.dat")
                shutil.copy(d / "char_q20_choke.dat", d / "char_q5_choke.dat")
                ls.solve_point(d, {"id": "x", "feed": "committed", "le_nh": 1.0})      # complete: solves
                if how == "truncate":
                    p = d / "char_q10_twoport.dat"
                    p.write_text("\n".join(p.read_text().splitlines()[:-2]) + "\n")
                elif how == "nan":
                    p = d / "char_ideal_twoport.dat"
                    rows = p.read_text().splitlines()
                    rows[2] = rows[2].replace(rows[2].split()[3], "nan", 1)
                    p.write_text("\n".join(rows) + "\n")
                else:
                    p = d / "char.log"
                    p.write_text(p.read_text().replace("BENCH_COMPLETE", "BENCH_DONE"))
                with self.assertRaises(ValueError):
                    ls.solve_point(d, {"id": "x", "feed": "committed", "le_nh": 1.0})

    def test_verify_outputs_missing_or_without_dc_audit(self):
        stem = "match_em5_cideal_lp_noise_q10"
        with tempfile.TemporaryDirectory() as td:
            d = Path(td)
            for suf in (".inband.dat", ".stab.dat", ".nf290.dat", ".log"):
                shutil.copy(ls.PRIOR_CORNERS / f"{stem}{suf}", d)
            e = {"stem": stem}
            with self.assertRaises(ValueError):          # #193 verify logs have no DC audit line
                ls.point_result(d, e, None, 21)
            (d / f"{stem}.nf290.dat").unlink()
            with self.assertRaises(FileNotFoundError):
                ls.point_result(d, e, None, 21)


def _pt(feed, le, nf, flags=(), conv=True, s11=-11.0, mu=1.0000004, status="verified"):
    return {"feed": feed, "le_nh": le, "status": status,
            "scan": {"dc_flags": list(flags), "convergence": {"normal": conv}, "nfmin290_worst_db": nf - 1.0},
            "match": {"nf290_db_worst": nf, "s11_db_worst": s11, "s22_db_worst": -15.0, "s21_db_min": 20.0,
                      "mu_bb_min": mu, "convergence": {"normal": True}}}


class Rules(unittest.TestCase):
    def test_shortlist_rule(self):
        pts = {"a": _pt("em5_cmim", 0.3, 2.4), "b": _pt("em5_cmim", 0.6, 2.5),
               "c": _pt("ideal_choke", 0.3, 1.0), "d": _pt("committed", 0.3, 1.1),       # never selected
               "e": _pt("em5_cmim", 0.1, 2.0, flags=["DC_BIAS_SHIFT_IC1 (-2 %)"]),    # DC-invalid
               "f": _pt("em5_cmim", 1.0, 2.1, conv=False),                              # fallback OP
               "g": _pt("em5_cmim", 0.1, 2.2, s11=-8.0),                                # fails S11
               "h": _pt("em5_cmim", 0.6, 2.0, status="rejected")}
        self.assertEqual(ls.shortlist(pts), ("a", "all non-noise gates"))
        pts["b"] = _pt("em5_cmim", 0.6, 2.4)                                             # tie -> lower Le
        self.assertEqual(ls.shortlist(pts)[0], "a")
        pts["a"]["match"]["s11_db_worst"] = -9.0
        pts["b"]["match"]["mu_bb_min"] = 0.99
        self.assertEqual(ls.shortlist(pts), ("g", "fallback"))                          # none passes: lowest NF
        self.assertEqual(ls.shortlist({"c": _pt("ideal_choke", 0.3, 1.0)}), (None, None))
        # a table-resolution wobble of mu is not a resolved deficit
        self.assertTrue(ls.non_noise_ok(_pt("em5_cmim", 0.3, 2.0, mu=1.0 - 5e-10)["match"]))

    def test_recommend_le(self):
        s, m = _pt("em5_cmim", 0.3, 1.1)["scan"], _pt("em5_cmim", 0.3, 1.1)["match"]
        r = ls.recommend_le(s, m, {"nf290_db_worst": 1.15})
        self.assertEqual((r["verdict"], r["binding"]), ("GO", None))
        r = ls.recommend_le(s, m, {"nf290_db_worst": 1.25})
        self.assertEqual((r["verdict"], r["failing"]), ("NO-GO", ["le_q_bracket"]))
        r = ls.recommend_le(s, m, None)
        self.assertEqual(r["binding"], "le_q_bracket")
        r = ls.recommend_le({**s, "nfmin290_worst_db": 1.3}, {**m, "nf290_db_worst": 2.4}, {"nf290_db_worst": 2.5})
        self.assertEqual(r["binding"], "noise_floor")
        self.assertEqual(r["failing"], ["noise_floor", "le_q_bracket"])
        r = ls.recommend_le(None, None, None)
        self.assertEqual((r["verdict"], r["binding"]), ("NO-GO", "dc_validity"))

    def test_control_rows(self):
        m = {"nf290_db_worst": 2.61, "nf290_db_mid": 2.58, "s11_db_worst": -11.4, "s22_db_worst": -15.6,
             "s21_db_min": 22.96, "mu_bb_min": 1.0000003575, "ic1": 3.9369e-3}
        rows = ls.control_rows("x", m, dict(m), (7e-9, 4.8e-13), (7e-9, 4.8e-13))
        self.assertEqual(len(rows), 9)
        self.assertTrue(all(r[-1] for r in rows))
        bad = ls.control_rows("x", {**m, "nf290_db_worst": 2.612, "mu_bb_min": 1.0000003595},
                              m, (7.0001e-9, 4.8e-13), (7e-9, 4.8e-13))
        self.assertEqual({r[1] for r in bad if not r[-1]}, {"nf290_db_worst", "mu_bb_min", "input_series_rel"})

    def test_nf_split_sums(self):
        cs = {"ideal": {"nfmin290_mid_db": 1.4}, "q10": {"nfmin290_mid_db": 1.45}}
        e = {"predicted_twoport_nf290_mid_db": 2.0, "predicted": [{"nf290_db": 2.5}] * ms.N_BAND}
        s = ls.nf_split(cs, e, 2.55)
        parts = s["le_loss_db"] + s["mismatch_pred_db"] + s["network_loss_pred_db"] + s["residual_db"]
        self.assertAlmostEqual(parts, s["total_over_floor_db"])
        self.assertAlmostEqual(s["floor_ideal_le_db"] + parts, 2.55)


def committed_le_record() -> str:
    ids = sorted(p.name[: -len("-le-points.csv")] for p in (EXP / "records").glob("*-le-points.csv"))
    assert ids, "no committed Le-study record"
    return ids[-1]


class CommittedRecord(unittest.TestCase):
    """Deterministic replay of the committed #198 record from its retained
    data, and the declared policy re-checked on that evidence."""

    RID = committed_le_record()
    SNAP = EXP / "netlist-snapshots" / RID
    CORN = EXP / "corners" / RID

    def _copy(self, td):
        corn, snap = Path(td, "corners"), Path(td, "snap")
        shutil.copytree(self.CORN, corn)
        shutil.copytree(self.SNAP, snap)
        return snap, corn

    def test_reduce_and_control_replay_byte_for_byte(self):
        rec = EXP / "records"
        for _ in range(2):
            with tempfile.TemporaryDirectory() as td:
                snap, corn = self._copy(td)
                self.assertEqual(ls.main(["control-check", "--snapdir", str(snap), "--corners", str(corn),
                                          "--csv", f"{td}/c.csv"]), 0)
                self.assertEqual(Path(td, "c.csv").read_bytes(), (rec / f"{self.RID}-le-control.csv").read_bytes())
                self.assertEqual(ls.main(["reduce", "--snapdir", str(snap), "--corners", str(corn),
                                          "--csv", f"{td}/p.csv", "--control-csv", f"{td}/c.csv",
                                          "--markdown", f"{td}/h.md"]), 0)
                self.assertEqual(Path(td, "p.csv").read_bytes(), (rec / f"{self.RID}-le-points.csv").read_bytes())
                self.assertEqual(Path(td, "h.md").read_bytes(), (self.CORN / "le_headlines.md").read_bytes())
                self.assertEqual((corn / "recommendation.json").read_bytes(),
                                 (self.CORN / "recommendation.json").read_bytes())
        self.assertIn((self.CORN / "le_headlines.md").read_text(), (rec / f"{self.RID}.md").read_text())

    def test_synthesis_replays_from_retained_characterizations(self):
        doc = json.loads((self.SNAP / "le_match_plan.json").read_text())
        plan = json.loads((self.SNAP / "le_plan.json").read_text())
        self.assertEqual(plan["points"], ls.study_points())
        self.assertEqual(plan["prior_feed_plan_sha256"], ls.sha256(ls.PRIOR_SNAP / "feed_plan.json"))
        self.assertEqual(doc["rejected"], [])
        self.assertEqual(len(doc["candidates"]), len(plan["points"]))
        for e in doc["candidates"]:
            p = next(x for x in plan["points"] if x["id"] == e["point"])
            got, _ = ls.solve_point(self.CORN / "charset" / p["id"], p)
            for k in ("input_values", "zs_target"):
                for x, y in zip(got[k], e[k]):
                    self.assertTrue(math.isclose(x, y, rel_tol=1e-12), (p["id"], k))
            for k in ("cp_out", "cs_out"):
                self.assertTrue(math.isclose(got[k], e[k], rel_tol=1e-12), (p["id"], k))

    def test_every_retained_deck_targets_its_declared_le(self):
        plan = json.loads((self.SNAP / "le_plan.json").read_text())
        for p in plan["points"]:
            ls.check_le_deck((self.SNAP / f"char_{p['id']}.spice").read_text(), p["le_nh"], "char")
            ls.check_le_deck((self.SNAP / f"verify_{p['id']}.spice").read_text(), p["le_nh"], "verify", ls.Q_LE)
        sl = json.loads((self.SNAP / "le_shortlist.json").read_text())
        self.assertEqual(len(sl["brackets"]), 2)
        for b in sl["brackets"]:
            ls.check_le_deck((self.SNAP / f"{b['stem']}.spice").read_text(), b["le_nh"], "verify",
                             b["le_q"], b["le_loss"])
        n = len(list(self.SNAP.glob("*.spice")))
        self.assertEqual(n, ls.planned_decks())
        self.assertLessEqual(n, ls.DECK_BUDGET)

    def test_evidence_honors_the_declared_rules(self):
        doc, pts, base = ls.collect(self.SNAP, self.CORN)
        sl = json.loads((self.SNAP / "le_shortlist.json").read_text())
        self.assertEqual(list(ls.shortlist(pts)), [sl["shortlisted"], sl["rule"]])
        for k, p in pts.items():
            self.assertTrue(p["scan"]["convergence"]["normal"], k)
            self.assertTrue(p["match"]["convergence"]["normal"], k)
        # the 1 nH finite-feed point reproduces the #193 em5_cmim scan floor (ideal Le) to the printed digits
        prior = json.loads((ls.PRIOR_CORNERS / "scan_summary.json").read_text())["variants"]
        for feed in ("committed", "ideal_choke", "em5_cmim"):
            got = pts[ls.point_id(feed, 1.0)]["entry"]["char"]["ideal"]
            self.assertAlmostEqual(got["nfmin290_mid_db"], prior[feed]["nfmin290_mid_db"], delta=5e-4)
        rj = json.loads((self.CORN / "recommendation.json").read_text())
        self.assertEqual(rj["shortlisted"], sl["shortlisted"])
        self.assertIn(rj["recommendation"]["verdict"], ("GO", "NO-GO"))

    def test_missing_or_malformed_outputs_rejected(self):
        sl = json.loads((self.SNAP / "le_shortlist.json").read_text())
        stem = f"verify_{sl['shortlisted']}"
        for victim in (f"{stem}.inband.dat", f"{stem}.stab.dat", f"{stem}.nf290.dat", f"{stem}.log"):
            with self.subTest(missing=victim), tempfile.TemporaryDirectory() as td:
                snap, corn = self._copy(td)
                (corn / victim).unlink()
                with self.assertRaises(FileNotFoundError):
                    ls.collect(snap, corn)
        with self.subTest("no-dc-audit"), tempfile.TemporaryDirectory() as td:
            snap, corn = self._copy(td)
            p = corn / f"{stem}.log"
            p.write_text(re.sub(r"^DC .*\n", "", p.read_text(), flags=re.M))
            with self.assertRaises(ValueError):
                ls.collect(snap, corn)
        with self.subTest("nonfinite"), tempfile.TemporaryDirectory() as td:
            snap, corn = self._copy(td)
            p = corn / f"{stem}.inband.dat"
            rows = p.read_text().splitlines()
            rows[4] = rows[4].replace(rows[4].split()[1], "nan", 1)
            p.write_text("\n".join(rows) + "\n")
            with self.assertRaises(ValueError):
                ls.collect(snap, corn)
        with self.subTest("fallback-excluded"), tempfile.TemporaryDirectory() as td:
            snap, corn = self._copy(td)
            p = corn / f"{stem}.log"
            p.write_text(p.read_text() + "\nNote: Transient op started\n")
            _, pts, _ = ls.collect(snap, corn)
            self.assertNotEqual(ls.shortlist(pts)[0], sl["shortlisted"])
        with self.subTest("control-drift"), tempfile.TemporaryDirectory() as td:
            snap, corn = self._copy(td)
            p = corn / f"verify_{ls.point_id('committed', 1.0)}.nf290.dat"
            rows = p.read_text().splitlines()
            mid = 1 + (ms.N_NF_DEFAULT - 1) // 2                     # header + band-centre sample
            f, v = (float(x) for x in rows[mid].split())
            rows[mid] = f"{f:.10e} {v + 0.01:.10e}"                    # 10 x the declared tolerance
            p.write_text("\n".join(rows) + "\n")
            self.assertEqual(ls.main(["control-check", "--snapdir", str(snap), "--corners", str(corn),
                                      "--csv", f"{td}/c.csv"]), 1)


if __name__ == "__main__":
    unittest.main()
