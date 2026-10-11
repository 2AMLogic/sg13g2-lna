"""Unit tests for sim/lna-matching-feasibility/q_study.py (issue #200).

Stdlib-only, PDK-free, no ngspice, single process. Covers: the committed
declaration, the declared map / bracket / budget, the Q = 10 replay of the
retained #198 synthesis and predictions (0.6 nH arms and the retained 1 nH
controls), the search-failure vs infeasible classification, reference-
temperature anchoring, decoupling of the input-Q lever from the Le / Lc loss,
deck checks (byte-identical char controls, bracket composition, boundary
composition, probe arms), the retained-derived tank control, malformed /
incomplete retained data, invalid-point selection, and -- once the record
exists -- a deterministic byte-for-byte replay of the committed evidence.
Never writes under sim/.
"""
from __future__ import annotations

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
import q_study as qs  # noqa: E402

def _paths(text):
    g = lambda rx: re.search(rx, text, re.M).group(1)  # noqa: E731
    return SimpleNamespace(models_lib=g(r'^\.lib "(\S+)" hbt_typ$'), mos_lib=g(r'^\.lib "(\S+)" mos_tt$'),
                           osdi_dir=g(r"^pre_osdi (\S+)/psp103\.osdi$"),
                           cap_lib=g(r'^\.lib "(\S+)" cap_typ$'),
                           wr=g(r"^wrdata (\S+)/\S+ "))


def _retained_args():
    """PDK paths taken from the retained deck itself, so the re-render
    comparison works on any checkout (checkout-local paths are normalized)."""
    want = (qs.RETAINED_SNAP / f"char_{qs.point_id('em5_cmim')}.spice").read_text()
    p = _paths(want)
    return SimpleNamespace(models_lib=p.models_lib, mos_lib=p.mos_lib, osdi_dir=p.osdi_dir,
                           cap_lib=p.cap_lib, outdir="/c", snapdir="/s", deckdir="/s",
                           relative_em=False)


ARGS = _retained_args()
ARGS_NF = SimpleNamespace(**{**ARGS.__dict__, "nf_npts": qs.retained_nf_npts()})


def retained_entry(feed):
    return qs.retained_entry(feed)


def q_record() -> str:
    ids = sorted(p.name[: -len("-qmap.csv")] for p in (EXP / "records").glob("*-qmap.csv"))
    return ids[-1] if ids else ""


class Declaration(unittest.TestCase):
    def test_committed_declaration_matches_code(self):
        self.assertEqual((EXP / "q-study-declaration.md").read_text(), qs.declaration_text())

    def test_map_constants_and_budget(self):
        self.assertEqual(qs.LE_STUDY_NH, 0.6)
        self.assertEqual(qs.Q_LE_FIXED, 10.0)
        self.assertEqual([q for _, q in qs.Q_IN_CASES], [5.0, 10.0, 20.0, 40.0, None])
        self.assertEqual(qs.Q_IN_FINITE, (5.0, 10.0, 20.0, 40.0))
        self.assertEqual(set(qs.ARMS), {"em5_cmim", "ideal_choke"})
        self.assertEqual(qs.ARMS["ideal_choke"], "diagnostic bound")
        self.assertEqual(qs.RPAR_OHM, (400.0, 200.0, 100.0))
        self.assertEqual(sorted(qs.RPAR_TAG.values()), ["r100", "r200", "r400"])
        self.assertEqual(qs.retained_nf_npts(), 21)
        self.assertLessEqual(qs.planned_char_decks(), qs.BUDGET_CHAR)
        self.assertLessEqual(qs.planned_verify_decks(), qs.BUDGET_VERIFY)
        self.assertEqual(qs.planned_char_decks() + qs.planned_verify_decks(), 11)
        # thresholds are the ratified row and the declared planning limit
        self.assertEqual(qs.THRESH_ROW_DB, ms.ROW_NF_DB)
        self.assertEqual(qs.THRESH_PLAN_DB, ms.ROW_NF_DB - fs.PVT_NF_MARGIN_DB)
        self.assertEqual(qs.XOUT_RDC, fs.XOUT_RDC)

    def test_retained_evidence_present(self):
        for feed in qs.ARMS:
            ent = retained_entry(feed)
            self.assertEqual(ent["point"], qs.point_id(feed))
            self.assertEqual(ent["le_nh"], 0.6)
            self.assertEqual(ent["feed_variant"], feed)
            self.assertTrue((qs.RETAINED_SNAP / f"char_{qs.point_id(feed)}.spice").exists())
            self.assertTrue((qs.RETAINED_CORNERS / f"verify_{qs.point_id(feed)}.log").exists())


class Q10Replay(unittest.TestCase):
    """The map at the retained convention must BE the retained study: synthesis
    and predictions reproduce the #198 entries (search failure must never be
    silently re-based onto moved code)."""

    def test_arms_replay_retained_entries(self):
        for feed in qs.ARMS:
            rows = qs.retained_char(feed)["cases"]["q10"]
            ent = retained_entry(feed)
            sol = qs.synth_input(rows, 10.0)
            self.assertEqual(sol["status"], "solved", feed)
            for a, b in zip(sol["values"], ent["input_values"]):
                self.assertTrue(math.isclose(a, b, rel_tol=1e-12), feed)
            pred = qs.predict_band(rows, sol["values"], 10.0, qs.output_ylc(ent),
                                   ent["cp_out"], ent["cs_out"])
            self.assertTrue(math.isclose(pred[ms.MID]["nf290_db"],
                                         ent["predicted"][ms.MID]["nf290_db"], rel_tol=1e-12), feed)
            # the map itself replays and records it
            row = next(r for r in qs.map_rows() if r["arm"] == feed and r["q_in"] == 10.0)
            self.assertEqual(row["replay"], "ok")

    def test_retained_one_nh_controls_replay(self):
        """The retained 1 nH controls (committed / ideal_choke / em5_cmim),
        reused from #198, replay offline: no new decks are spent on them."""
        mp = json.loads((qs.RETAINED_SNAP / "le_match_plan.json").read_text())
        for feed in ("committed", "ideal_choke", "em5_cmim"):
            rows = qs.load_char_dir(qs.RETAINED_CORNERS / "charset" / ls.point_id(feed, 1.0)
                                    )["cases"]["q10"]
            ent = next(e for e in mp["candidates"] if e["point"] == ls.point_id(feed, 1.0))
            sol = qs.synth_input(rows, 10.0)
            self.assertEqual(sol["status"], "solved", feed)
            for a, b in zip(sol["values"], ent["input_values"]):
                self.assertTrue(math.isclose(a, b, rel_tol=1e-12), feed)

    def test_replay_detects_drift(self):
        rows = qs.retained_char("em5_cmim")["cases"]["q10"]
        ent = retained_entry("em5_cmim")
        drifted = dict(ent)
        drifted["input_values"] = [ent["input_values"][0] * 1.001, ent["input_values"][1]]
        sol = qs.synth_input(rows, 10.0)
        row = {"input_values": sol["values"], "pred_nf290_mid_db": 2.0}
        with self.assertRaises(ValueError):
            qs.replay_check(row, drifted)


class PredictionSemantics(unittest.TestCase):
    def test_reference_temperature_anchor(self):
        """NFmin is measured at the 300.15 K analysis temperature and re-
        referenced to T0 = 290 K; the wrong direction must not be confused
        with it."""
        x = 1.5
        up = ms.nf_reref(x, ms.T_ANALYSIS)                  # analysis -> 290 K
        self.assertAlmostEqual(up, 10 * math.log10(1 + (10 ** (x / 10) - 1) * ms.T_ANALYSIS / ms.T0))
        self.assertNotAlmostEqual(up, ms.nf_reref(x, ms.T0, ms.T_ANALYSIS))
        self.assertEqual(qs.nfmin290_worst([{"nfmin_t_db": x}] * 3), up)

    def test_lossless_network_zero_excess_noise(self):
        rows = qs.retained_char("em5_cmim")["cases"]["q10"]
        # a noiseless DUT (Fmin = 1) behind a lossless network stays at 0 dB
        noiseless = [dict(r, noise={"fmin": 1.0, "rn": 0.0, "gopt": complex(0)}) for r in rows]
        vin = list(ms.closed_form_start("lowpass", rows[ms.MID]["zin"].conjugate()))
        pred = qs.predict_band(noiseless, vin, None, qs.output_ylc(retained_entry("em5_cmim")),
                               retained_entry("em5_cmim")["cp_out"], retained_entry("em5_cmim")["cs_out"])
        for p in pred:
            self.assertAlmostEqual(p["nf290_db"], 0.0, places=12)

    def test_input_q_decoupled_from_le_and_lc_loss(self):
        """Varying the input-Q lever must move ONLY the input network: the
        Le loss resistor (Rle) and the Lc loss resistor (Rlc) are identical
        across input-Q cases, on the decks and in the entries."""
        ent = retained_entry("em5_cmim")
        rlc_want = f"Rlc lc_x outn {ent['r_lc']:.6g}"
        rle_want = f"Rle e1 vss {ms.q_parallel_r(0.6e-9, 10.0):.6g}"
        decks = {}
        for q_in in (5.0, 20.0, None):
            e = qs.entry_for("em5_cmim", q_in, f"t{q_in}")
            text = qs.render_verify(ARGS_NF, e)
            decks[q_in] = text
            self.assertIn(rlc_want, text, f"q_in={q_in}: Lc loss moved")
            self.assertIn(rle_want, text, f"q_in={q_in}: Le loss moved")
            self.assertEqual(qs._RQBR_RE.findall(text), [], f"q_in={q_in}: bracket resistor leaked")
        # and the input loss resistor DOES move with q_in
        r5 = ms.q_series_r(decks and qs.entry_for("em5_cmim", 5.0, "x")["input_l"], 5.0)
        self.assertIn(f"Rlb lb_x xin {r5:.6g}", decks[5.0])
        self.assertNotIn("Rlb lb_x xin", decks[None])
        # output admittance used by the predictions is the retained one at every q_in
        ylc = qs.output_ylc(ent)
        self.assertAlmostEqual(ylc[ms.MID], 1 / ms.z_ind(ent["lc"], ent["r_lc"], ms.F_MID),
                               places=15)


class SearchFailureVsInfeasible(unittest.TestCase):
    def test_classification(self):
        rows = qs.retained_char("em5_cmim")["cases"]["q10"]
        self.assertEqual(qs.synth_input(rows, 10.0)["status"], "solved")
        # the classifier: a topology-infeasible START vs a search failure
        self.assertEqual(qs.classify_synth_error(
            ValueError("no lossless lowpass L-section matches 1 - 2j to 50 Ohm")), "infeasible")
        self.assertEqual(qs.classify_synth_error(
            ValueError("solve_input_noise: no grid point meets the mismatch bound")), "search_failed")
        # an impossible mismatch bound raises and classifies as a SEARCH failure
        mid = rows[ms.MID]
        with self.assertRaises(ValueError) as ctx:
            ms.solve_input_noise("lowpass", mid["zin"], mid["noise"], 10.0, mismatch_db=-200.0)
        self.assertEqual(qs.classify_synth_error(ctx.exception), "search_failed")

    def test_invalid_cells_stay_visible_and_out_of_the_map(self):
        rows = list(qs.map_rows())
        by = {(r["arm"], r["q_in"]): r for r in rows}
        self.assertEqual(len(rows), 2 * len(qs.Q_IN_CASES))
        # inject search failures on the crossing cells and re-check the logic
        choke = [dict(r) for r in rows if r["arm"] == "ideal_choke"]
        for r in choke:
            if r["q_in"] in (20.0, 40.0):
                r["status"], r["reason"] = "search_failed", "injected"
                r.pop("pred_nf290_worst_db", None)
        c = qs.crossings(choke)
        self.assertTrue(c["nf290_worst_le_1p5"]["not_reached"])
        self.assertIsNone(c["nf290_worst_le_1p5"]["min_tested_q"])
        self.assertTrue(c["nf290_worst_le_1p5"]["lossless_crosses"])
        # with every finite cell failed the crossing is honestly 'not reached'
        allbad = [dict(r, status="search_failed", reason="injected") for r in choke]
        for r in allbad:
            r.pop("pred_nf290_worst_db", None)
        c = qs.crossings(allbad)
        self.assertTrue(c["nf290_worst_le_1p5"]["not_reached"])
        self.assertFalse(c["nf290_worst_le_1p5"]["lossless_crosses"])
        self.assertIs(by[("em5_cmim", None)]["q_in"], None)


class CrossingRules(unittest.TestCase):
    def test_threshold_semantics_on_real_map(self):
        rows = [r for r in qs.map_rows() if r["arm"] == "ideal_choke"]
        c = qs.crossings(rows)
        worst = {r["q_in"]: r["pred_nf290_worst_db"] for r in rows if r["status"] == "solved"}
        for key in ("nf290_worst_le_1p5", "nf290_worst_le_1p2"):
            v = c[key]
            if not v["not_reached"]:
                self.assertLessEqual(worst[v["min_tested_q"]], v["threshold_db"])
                lower = [q for q in qs.Q_IN_FINITE if q < v["min_tested_q"]]
                for q in lower:
                    self.assertGreater(worst[q], v["threshold_db"], (key, q))

    def test_boundary_selection_rule(self):
        rows = qs.map_rows()
        sel = qs.select_boundary(rows)
        tags = [b["tag"] for b in sel]
        self.assertEqual(tags[0], "cmim_lossless")
        self.assertIn(tags[-1], ("choke_lossless",))
        # B2 is the lowest tested finite choke Q at/below 1.2, else 1.5, else lossless
        by = {r["q_in"]: r for r in rows if r["arm"] == "ideal_choke" and r["status"] == "solved"}
        want = None
        for thresh in (qs.THRESH_PLAN_DB, qs.THRESH_ROW_DB):
            crossed = [q for q in qs.Q_IN_FINITE if q in by and by[q]["pred_nf290_worst_db"] <= thresh]
            if crossed:
                want = crossed[0]
                break
        b2 = next(b for b in sel if b["arm"] == "ideal_choke" and b["tag"] != "choke_lossless")
        self.assertEqual(b2["q_in"], want)
        if want is not None:
            self.assertIn("choke_lossless", tags)      # B3 kept, distinct from B2
            self.assertEqual(len(sel), 3)
        else:
            self.assertEqual(len(sel), 2)              # B3 == B2, deduplicated
        # a full search failure on the choke arm still selects (lossless-only) or reports
        bad = [dict(r, status="search_failed", reason="x") for r in rows
               if r["arm"] == "ideal_choke"]
        for r in bad:
            r.pop("pred_nf290_worst_db", None)
        sel2 = qs.select_boundary([r for r in rows if r["arm"] == "em5_cmim"] + bad)
        self.assertEqual([b["tag"] for b in sel2], ["cmim_lossless", "choke_lossless"])


class Decks(unittest.TestCase):
    def test_ctl_char_decks_are_the_retained_decks(self):
        for feed in qs.ARMS:
            text = qs.render_ctl_char(ARGS, feed)
            want = (qs.RETAINED_SNAP / f"char_{qs.point_id(feed)}.spice").read_text()
            self.assertEqual(qs.normalize_deck_paths(text), qs.normalize_deck_paths(want), feed)

    def test_ctl_char_check_fires_on_drift(self):
        real_retained = qs.RETAINED_SNAP
        with tempfile.TemporaryDirectory() as td:
            snap = Path(td)
            text = qs.render_ctl_char(ARGS, "em5_cmim")
            (snap / "char_em5_cmim_le0p60.spice").write_text(
                text.replace("sp lin 11", "sp lin 12"))       # any analysis drift
            shutil.copy(real_retained / "le_match_plan.json", snap / "le_match_plan.json")
            shutil.copy(real_retained / "le_plan.json", snap / "le_plan.json")
            qs.RETAINED_SNAP = snap
            try:
                with self.assertRaises(ValueError):
                    qs.render_ctl_char(ARGS, "em5_cmim")
            finally:
                qs.RETAINED_SNAP = real_retained
        self.assertTrue(real_retained.exists())

    def test_bracket_deck_composition(self):
        base = qs.normalize_deck_paths(
            (qs.RETAINED_SNAP / "char_em5_cmim_le0p60.spice").read_text())
        for r in qs.RPAR_OHM:
            text = qs.render_bracket_char(ARGS, r)
            qs.check_bracket_deck(text, r)
            stripped = qs.normalize_deck_paths(re.sub(r"\nRqbr b1f b1 \S+", "", text))
            self.assertEqual(stripped, base, f"r={r}: bracket deck is not the retained feed + one Rqbr")
            self.assertIn(f"\nRqbr b1f b1 {r:g}\n", text)
            self.assertNotIn(f"Rqbr b1f b1 {r:g} noisy=0", text)
        # DC path survives (the resistor is parallel to a DC-carrying tank)
        self.assertTrue(fs.dc_connected(text, "bref", "b1"))

    def test_bracket_deck_check_rejects_wrong_edits(self):
        good = qs.render_bracket_char(ARGS, 400.0)
        with self.assertRaises(ValueError):
            qs.check_bracket_deck(good.replace("Rqbr b1f b1 400", "Rqbr b1f b1 401"), 400.0)
        with self.assertRaises(ValueError):
            qs.check_bracket_deck(good.replace("Rqbr b1f b1 400", "Rqbr b1f b1 400 noisy=0"), 400.0)
        with self.assertRaises(ValueError):
            qs.check_bracket_deck(re.sub(r"^Rqbr .*\n", "", good, flags=re.M), 400.0)
        two = good.replace("XCfeed b1f b1", "XCfeed b1f b1\nRqbr b1f b1 400")
        with self.assertRaises(ValueError):
            qs.check_bracket_deck(two, 400.0)

    def test_boundary_verify_decks(self):
        for tag, feed, q_in in (("choke_q40", "ideal_choke", 40.0),
                                ("choke_lossless", "ideal_choke", None),
                                ("cmim_lossless", "em5_cmim", None)):
            e = qs.entry_for(feed, q_in, f"verify_bound_{tag}")
            text = qs.render_verify(ARGS_NF, e)
            qs.check_bound_deck(text, q_in, e["input_values"], feed)
            self.assertIn(ls.DC_AUDIT.splitlines()[0], text)      # the #193 DC audit
            self.assertIn(f"verify_bound_{tag}", text)            # stem in wrdata names

    def test_boundary_check_rejects_bad_edits(self):
        e = qs.entry_for("ideal_choke", 40.0, "verify_bound_choke_q40")
        good = qs.render_verify(ARGS_NF, e)
        rlb = ms.q_series_r(e["input_l"], 40.0)
        with self.assertRaises(ValueError):
            qs.check_bound_deck(good.replace(f"Rlb lb_x xin {rlb:.6g}", f"Rlb lb_x xin {rlb * 2:.6g}"),
                                40.0, e["input_values"], "ideal_choke")
        with self.assertRaises(ValueError):     # a stale retained Q-case note
            qs.check_bound_deck(good.replace(qs.boundary_note(40.0).splitlines()[1],
                                             qs.q_case_note_line().strip("* ")),
                                40.0, e["input_values"], "ideal_choke")
        with self.assertRaises(ValueError):     # a leaked bracket resistor
            qs.check_bound_deck(good + "\nRqbr b1f b1 400\n", 40.0, e["input_values"], "ideal_choke")
        lossless = qs.entry_for("ideal_choke", None, "verify_bound_choke_lossless")
        ltext = qs.render_verify(ARGS_NF, lossless)
        with self.assertRaises(ValueError):     # lossless deck must not carry Rlb
            qs.check_bound_deck(ltext.replace("* (no EM inductor", "* Rlb lb_x xin 1\n* (no EM inductor"),
                                None, lossless["input_values"], "ideal_choke")

    def test_probe_deck_arms_and_vectors(self):
        text = qs.render_probe(ARGS)
        for tag in qs.PROBE_ARMS:
            self.assertIn(f"Xtank_{tag} b1f_{tag} b1_{tag} 0 ", text)
            self.assertIn(f"Xcfeed_{tag} b1f_{tag} b1_{tag} cap_cmim ", text)
            self.assertIn(f"\nV_{tag} b1f_{tag} 0 dc 0 ac {qs.PROBE_V_AC:g}\n", text)
            self.assertIn(f"\nV{tag}m b1_{tag} 0 dc 0 ac 0", text)
            self.assertNotIn(f"I_{tag} ", text)
            self.assertIn(f"real(i(v{tag}m))", text)
            self.assertIn(f"imag(i(v{tag}m))", text)
        for r in qs.RPAR_OHM:
            self.assertIn(f"Rqbr_{qs.rpar_tag(r)} b1f_{qs.rpar_tag(r)} b1_{qs.rpar_tag(r)} {r:g}\n", text)
        self.assertNotIn("Rqbr_ctl", text)
        self.assertNotIn("noisy=0", text)
        self.assertNotIn("@@", text)
        # the probe keeps the retained geometry and the pinned cmim size
        s = qs.retained_plan()["cmim_side_um"]["em5"]
        self.assertIn(f"w={s:.6g}u l={s:.6g}u", text)
        self.assertIn(ms.em_instance("em5"), text)

    def test_probe_recovers_known_admittance_independent_of_drive_shunt(self):
        """Mini nodal model of the RENDERED probe topology: tank Y between b1f
        and b1 (b1 at 0 V through the sensing source), a separate shunt Ys at
        b1f, driven exactly as each arm's rendered source line says. The
        sensed current must give back the known tank admittance for every arm
        and every shunt value; the old current drive must NOT (it divides)."""
        text = qs.render_probe(ARGS)
        ytank = complex(1.25e-3, -3.1e-4)
        ybr = {t: 1.0 / r for r, t in qs.RPAR_TAG.items()}
        for tag in qs.PROBE_ARMS:
            m = re.search(rf"^V_{tag} b1f_{tag} 0 dc 0 ac (\S+)$", text, re.M)
            self.assertIsNotNone(m, tag)          # voltage drive on every arm
            vdrive = float(m.group(1))
            self.assertEqual(vdrive, qs.PROBE_V_AC)
            self.assertRegex(text, rf"(?m)^V{tag}m b1_{tag} 0 dc 0 ac 0$")
            yt = ytank + ybr.get(tag, 0.0)        # bracket resistor in parallel
            for ys in (0.0, 1e-5, 3e-3 + 2e-3j, 0.5):
                # b1f is forced to vdrive: shunt current never reaches the sense
                i_sense = vdrive * yt             # polarity: b1f -> b1 -> sense
                got = qs.probe_admittance(i_sense)
                self.assertAlmostEqual(got.real, yt.real, places=12)
                self.assertAlmostEqual(got.imag, yt.imag, places=12)
                # the discarded current drive: divider error that grows with Ys
                i_div = 1.0 * yt / (yt + ys)
                if ys:
                    self.assertGreater(abs(qs.probe_admittance(i_div) - yt), 1e-6 * abs(yt))
            # sensing polarity: the reversed sign is detected as non-passive
            self.assertLess(qs.probe_admittance(-vdrive * yt).real, 0)
        # explicit division by the drive voltage (not an implicit unit amplitude)
        self.assertAlmostEqual(qs.probe_admittance(2e-3 + 1e-3j, 2.0), 1e-3 + 0.5e-3j)
        for bad in (0.0, float("nan")):
            with self.assertRaises(ValueError):
                qs.probe_admittance(1e-3, bad)

    def test_probe_bracket_resistor_stays_noisy_and_parallel(self):
        text = qs.render_probe(ARGS)
        for r, t in qs.RPAR_TAG.items():
            m = re.search(rf"^Rqbr_{t} b1f_{t} b1_{t} (\S+)\s*$", text, re.M)
            self.assertIsNotNone(m)
            self.assertAlmostEqual(float(m.group(1)), r)
        self.assertNotRegex(text, r"(?i)noisy\s*=\s*0")

    def test_parse_probe_divides_by_drive_voltage(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td, "tank_y.dat")
            Path(td, "probe_tank.log").write_text("BENCH_COMPLETE\n")
            names = ["frequency"] + [c for t in qs.PROBE_ARMS for c in (f"real(i(v{t}m))", f"imag(i(v{t}m))")]
            y0 = complex(2e-3, -1e-3)
            with open(p, "w") as fh:
                fh.write("  ".join(names) + "\n")
                for f in ms.band_freqs():
                    row = [f] + [v for _ in qs.PROBE_ARMS for v in (y0.real * qs.PROBE_V_AC, y0.imag * qs.PROBE_V_AC)]
                    fh.write("  ".join(f"{v:.10e}" for v in row) + "\n")
            out = qs.parse_probe(p)
            for t in qs.PROBE_ARMS:
                self.assertAlmostEqual(out[t][0], y0 / qs.PROBE_V_AC)

    def test_char_dc_audit_is_print_only(self):
        text = qs.render_ctl_char(ARGS, "em5_cmim")
        audited = qs.add_char_dc_audit(text)
        self.assertEqual(audited.count(qs.CHAR_OP_ANCHOR), 1)
        self.assertIn('echo "DC ic1', audited)
        self.assertEqual(audited.replace(qs.CHAR_DC_AUDIT, ""), text)
        with self.assertRaises(ValueError):
            qs.add_char_dc_audit(audited)


class RetainedDerivations(unittest.TestCase):
    def test_derived_tank_matches_the_declared_value(self):
        y = qs.derived_ytank(ms.band_freqs())
        for z in y:
            self.assertGreater(z.real, 0)
        zmid = abs(1 / y[ms.MID])
        self.assertAlmostEqual(zmid, qs.TANK_Z_RET_OHM, delta=qs.TANK_Z_RET_OHM * 0.02)
        # consistent with the #193 tuning table's peak (803 Ohm) to 2 %
        self.assertAlmostEqual(zmid, 803.0, delta=803.0 * 0.02)

    def test_malformed_retained_data_rejected(self):
        with _bad_probe_fixture() as p:
            with self.assertRaises(ValueError):
                qs.parse_probe(p)

    def test_parse_probe(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td, "tank_y.dat")
            log = Path(td, "probe_tank.log")
            freqs = ms.band_freqs()
            names = ["frequency"] + [c for t in qs.PROBE_ARMS for c in (f"real(i(v{t}m))", f"imag(i(v{t}m))")]
            rows = []
            for i, f in enumerate(freqs):
                row = [f]
                for t in qs.PROBE_ARMS:
                    y = complex(1.2e-3 + i * 1e-9, -4e-4)
                    row += [y.real, y.imag]
                rows.append(row)
            with open(p, "w") as fh:
                fh.write("  ".join(f"{n:18s}" for n in names) + "\n")
                for row in rows:
                    fh.write("  ".join(f"{v:18.10e}" for v in row) + "\n")
            log.write_text("BENCH_COMPLETE\n")
            out = qs.parse_probe(p)
            self.assertEqual(set(out), set(qs.PROBE_ARMS))
            self.assertAlmostEqual(abs(1 / out["ctl"][0]), 1 / abs(complex(1.2e-3, -4e-4)))
            # a missing BENCH_COMPLETE marker is rejected
            log.write_text("incomplete\n")
            with self.assertRaises(ValueError):
                qs.parse_probe(p)


def _bad_probe_fixture():
    import contextlib

    @contextlib.contextmanager
    def _ctx():
        with tempfile.TemporaryDirectory() as td:
            p = Path(td, "tank_y.dat")
            p.write_text("frequency real(i(vctlm))\n2.4e9 nan\n")
            log = Path(td, "probe_tank.log")
            log.write_text("BENCH_COMPLETE\n")
            yield p

    return _ctx()


class CommittedRecord(unittest.TestCase):
    """Once the study has run: deterministic replay of the committed evidence
    from its retained data, and the declared policy re-checked on it."""

    def test_record_replay(self):
        rid = q_record()
        if not rid:
            self.skipTest("the #200 record has not been generated yet")
        snap = EXP / "netlist-snapshots" / rid
        corn = EXP / "corners" / rid
        rec = EXP / "records"
        for _ in range(2):
            with tempfile.TemporaryDirectory() as td:
                s2, c2 = Path(td, "snap"), Path(td, "corn")
                shutil.copytree(snap, s2)
                shutil.copytree(corn, c2)
                self.assertEqual(qs.main(["control-check", "--snapdir", str(s2), "--corners", str(c2),
                                          "--csv", f"{td}/c1.csv"]), 0)
                self.assertEqual(Path(td, "c1.csv").read_bytes(),
                                 (rec / f"{rid}-control-char.csv").read_bytes())
                self.assertEqual(qs.main(["ctl-verify-check", "--snapdir", str(s2), "--corners", str(c2),
                                          "--csv", f"{td}/c2.csv"]), 0)
                self.assertEqual(Path(td, "c2.csv").read_bytes(),
                                 (rec / f"{rid}-control-verify.csv").read_bytes())
                self.assertEqual(qs.main(["qmap", "--models-lib", "/m/cornerHBT.lib",
                                          "--mos-lib", "/m/cornerMOShv.lib", "--osdi-dir", "/o",
                                          "--cap-lib", "/m/cornerCAP.lib",
                                          "--snapdir", str(s2), "--outdir", str(c2)]), 0)
                self.assertEqual((s2 / "qreq_map.json").read_bytes(), (snap / "qreq_map.json").read_bytes())
                self.assertEqual(qs.main(["reduce", "--snapdir", str(s2), "--corners", str(c2),
                                          "--isolation-csv", f"{td}/iso.csv",
                                          "--map-csv", f"{td}/map.csv",
                                          "--markdown", f"{td}/h.md"]), 0)
                self.assertEqual(Path(td, "map.csv").read_bytes(), (rec / f"{rid}-qmap.csv").read_bytes())
                self.assertEqual(Path(td, "iso.csv").read_bytes(), (rec / f"{rid}-isolation.csv").read_bytes())
                self.assertEqual(Path(td, "h.md").read_bytes(), (corn / "qreq_headlines.md").read_bytes())
                self.assertEqual((c2 / "recommendation.json").read_bytes(),
                                 (corn / "recommendation.json").read_bytes())
        self.assertIn((corn / "qreq_headlines.md").read_text(), (rec / f"{rid}.md").read_text())

    def test_evidence_honors_the_declared_rules(self):
        rid = q_record()
        if not rid:
            self.skipTest("the #200 record has not been generated yet")
        snap = EXP / "netlist-snapshots" / rid
        corn = EXP / "corners" / rid
        mapdoc = json.loads((snap / "qreq_map.json").read_text())
        rj = json.loads((corn / "recommendation.json").read_text())
        # every solved cell's q = 10 replay marker; crossings match the map
        for feed in qs.ARMS:
            s = mapdoc["summary"][feed]
            rows = [r for r in mapdoc["rows"] if r["arm"] == feed]
            replay_row = next(r for r in rows if r["q_in"] == 10.0)
            self.assertEqual(replay_row.get("replay"), "ok", feed)
            c = qs.crossings(rows)
            self.assertEqual(s["crossings"], c, feed)
        # boundary decks exist and are the declared set
        declared = qs.select_boundary(qs.map_rows())
        self.assertEqual([b["boundary_tag"] for b in mapdoc["boundary"]],
                         [b["tag"] for b in declared])
        for b in mapdoc["boundary"]:
            if b.get("status") == "not_renderable":
                continue
            self.assertTrue((snap / f"{b['stem']}.spice").exists())
            e = qs.entry_for(b["feed_variant"], b["q_in"], b["stem"])
            qs.check_bound_deck((snap / f"{b['stem']}.spice").read_text(), b["q_in"],
                                e["input_values"], b["feed_variant"])
        # the campaign verdict can only come from the physical control
        self.assertEqual(rj["campaign"]["physical_candidate_pool"],
                         ["verify_ctl_" + qs.point_id("em5_cmim")])
        self.assertIn(rj["campaign"]["verdict"], ("GO", "NO-GO"))
        # every bracket deck in the record is the retained feed + exactly one Rqbr
        for r in qs.RPAR_OHM:
            text = (snap / f"char_bracket_{qs.rpar_tag(r)}.spice").read_text()
            qs.check_bracket_deck(text, r)


if __name__ == "__main__":
    unittest.main()
