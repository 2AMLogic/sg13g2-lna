#!/usr/bin/env python3
"""Joint emitter-degeneration / input-match study on the finite base feed (issue #198).

Companion to run_le_study.sh. Builds on matching_solver.py (bench, nominal
cell, characterization / synthesis / verification decks) and feed_study.py
(feed variants, the retained #193 feed plan, DC audit, go/no-go gates).
Subcommands, in run order:

  declare        print the point set / provenance / policy declaration
                 (committed BEFORE any run: le-study-declaration.md)
  char-gen       one characterization deck per declared (feed, Le) point,
                 Le an explicit input (no 1 nH reset, no Le sweep)
  solve          re-synthesize the existing noise-weighted input match
                 (lp_noise, Q = 10) from each point's own characterization
                 and write its verification deck (DC audit added), or
                 record the point as rejected with the reason
  stems          print deck stems of one group (char / control / rest /
                 bracket), in run order, for the runner
  control-check  compare the 1 nH controls with record 20261010-233800-d1312cc
                 against the declared tolerances (non-zero exit: stop)
  shortlist      pick the finite-feed point by the declared rule, from
                 VERIFIED numbers only, and write its two bracket decks
  reduce         per-point table, NF decomposition, brackets, go/no-go

This is a NOMINAL-CELL bench exploration. Nothing here edits design/ or spec/,
and no number is a conformance claim. Stdlib only, so the unit tests run
PDK-free in CI.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import re
import sys
from pathlib import Path
from types import SimpleNamespace

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import feed_study as fs  # noqa: E402
import matching_solver as ms  # noqa: E402

# --- declared point set ------------------------------------------------------
PRIOR_RID = "20261010-233800-d1312cc"          # #193 record: feed plan source and control reference
PRIOR_SNAP = HERE / "netlist-snapshots" / PRIOR_RID
PRIOR_CORNERS = HERE / "corners" / PRIOR_RID
LE_POINTS_NH = (0.1, 0.3, 0.6, 1.0)
FEEDS = {
    "committed": "baseline",
    "em5_cmim": "finite candidate",
    "ideal_choke": "diagnostic bound",
}
CONTROL_LE_NH = 1.0
CONTROL_FEEDS = ("committed", "ideal_choke", "em5_cideal")   # the three feeds #193 verified
FINITE_FEED = "em5_cmim"
CHAR_CASES_LE = {"ideal": None, "q10": 10.0, "q5": 5.0}      # Le-loss cases per characterization
Q_LE = 10.0                                                  # assumed Le Q (the #186/#193 q10 case)
Q_LE_BRACKET = 5.0                                           # worse-Q bracket on the shortlisted point
MATCH_CANDIDATE = fs.MATCH_CANDIDATE                         # lp_noise
SOURCE_Q_CASE = fs.SOURCE_Q_CASE                             # q10
DECK_BUDGET = 32

# --- declared tolerances / policy (bench policy, NOT ratified) ---------------
CONTROL_TOL_DB = 1e-3        # NF290 worst/mid, S11/S22 worst, |S21| min vs the #193 record
CONTROL_TOL_MU = 1e-9        # broadband mu minimum (the table resolution)
CONTROL_TOL_IC1_REL = 1e-5   # IC1 (printed to ~6 significant digits)
CONTROL_TOL_VAL_REL = 1e-6   # synthesized input Lb / Cp
GATES_LE = fs.GATES + ["le_q_bracket"]


def le_tag(le_nh: float) -> str:
    """0.1 -> 'le0p10'. Filename-safe, fixed width, unambiguous."""
    if not (math.isfinite(le_nh) and le_nh > 0):
        raise ValueError(f"Le must be positive and finite (got {le_nh!r})")
    return "le" + f"{le_nh:.2f}".replace(".", "p")


def point_id(feed: str, le_nh: float) -> str:
    return f"{feed}_{le_tag(le_nh)}"


def study_points() -> list:
    """The declared points, in run order: controls first (so a reproduction
    failure stops the study before the rest of the budget is spent)."""
    pts = []
    for feed in CONTROL_FEEDS:
        role = FEEDS.get(feed, "reproduction control only")
        pts.append({"id": point_id(feed, CONTROL_LE_NH), "feed": feed, "le_nh": CONTROL_LE_NH,
                    "role": role, "control": True})
    for feed, role in FEEDS.items():
        for le in LE_POINTS_NH:
            pid = point_id(feed, le)
            if any(p["id"] == pid for p in pts):
                continue
            pts.append({"id": pid, "feed": feed, "le_nh": le, "role": role, "control": False})
    n_decks = 2 * len(pts) + 2
    if n_decks > DECK_BUDGET:
        raise ValueError(f"declared study needs {n_decks} decks > budget {DECK_BUDGET}")
    return pts


def planned_decks() -> int:
    return 2 * len(study_points()) + 2


def sha256(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def prior_feed_plan() -> dict:
    return json.loads((PRIOR_SNAP / "feed_plan.json").read_text())["plan"]


# ---------------------------------------------------------------------------
# Deck checks (pure): exact Le targeting, consistent loss values
# ---------------------------------------------------------------------------
_LE_RE = re.compile(r"^Le e1 (\S+) (\S+?)n m=1$", re.M)


def le_elements(text: str) -> list:
    """[(node2, value_nH)] of every Le element line in a deck."""
    return [(m.group(1), float(m.group(2))) for m in _LE_RE.finditer(text)]


def check_le_deck(text: str, le_nh: float, kind: str, q=None, loss: str = "parallel") -> None:
    """Raise ValueError unless the deck carries exactly one Le element of
    value le_nh and the loss resistor implied by (q, loss) -- no stale 1 nH
    line, no Le sweep that resets Le, no loss computed from another Le.
    kind: 'char' (parallel placeholder + per-case alters) or 'verify'."""
    els = le_elements(text)
    if len(els) != 1:
        raise ValueError(f"deck carries {len(els)} Le element lines, expected 1")
    node, val = els[0]
    if not math.isclose(val, le_nh, rel_tol=1e-9):
        raise ValueError(f"deck Le = {val:g} nH, declared {le_nh:g} nH")
    if re.search(r"^alter l\.xa\.le\b", text, re.M):
        raise ValueError("deck alters Le (stale Le sweep / 1 nH reset)")
    l_h = le_nh * 1e-9
    if kind == "char":
        if node != "vss" or not re.search(rf"^Rle e1 vss {re.escape(f'{ms.R_IDEAL_PLACEHOLDER:g}')}$", text, re.M):
            raise ValueError("char deck lacks the parallel Le-loss placeholder")
        for case, cq in CHAR_CASES_LE.items():
            r = ms.R_IDEAL_PLACEHOLDER if cq is None else ms.q_parallel_r(l_h, cq)
            if f"alter r.xa.rle = {r:.6g}\n" not in text:
                raise ValueError(f"char deck: Le-loss case {case} not at R = {r:.6g} Ohm for Le = {le_nh:g} nH")
        return
    if kind != "verify":
        raise ValueError(f"unknown deck kind {kind!r}")
    rp = re.findall(r"^Rle e1 vss (\S+)$", text, re.M)
    rs = re.findall(r"^Rles le_x vss (\S+)$", text, re.M)
    if q is None:
        if rp or rs or node != "vss":
            raise ValueError("ideal-Le deck carries an Le loss resistor")
        return
    if loss == "parallel":
        want = ms.q_parallel_r(l_h, q)
        if rs or node != "vss" or len(rp) != 1 or not math.isclose(float(rp[0]), want, rel_tol=1e-5):
            raise ValueError(f"parallel Le loss should be one Rle = {want:.6g} Ohm (got {rp}, series {rs})")
    elif loss == "series":
        want = ms.q_series_r(l_h, q)
        if rp or node != "le_x" or len(rs) != 1 or not math.isclose(float(rs[0]), want, rel_tol=1e-5):
            raise ValueError(f"series Le loss should be one Rles = {want:.6g} Ohm (got {rs}, parallel {rp})")
    else:
        raise ValueError(f"unknown Le loss kind {loss!r}")


OP_ANCHOR = 'echo "OP ic1 $&ic1 ic2 $&ic2 idd $&idd pdc $&pdc"\n'
DC_AUDIT = (
    "* DC audit (issue #198): node voltages of the matched DUT Xa.Xdut\n"
    "let ib1 = @q.xa.xdut.xq1.qnpn13g2[ib]\n"
    "let vb1 = v(xa.xdut.b1)\n"
    "let ve1 = v(xa.xdut.e1)\n"
    "let vcasc = v(xa.xdut.casc)\n"
    "let voutn = v(xa.xdut.outn)\n"
    "let vb2 = v(xa.xdut.vb2)\n"
    "let vbref = v(xa.xdut.bref)\n"
    'echo "DC ic1 $&ic1 ic2 $&ic2 ib1 $&ib1 vb1 $&vb1 ve1 $&ve1 vcasc $&vcasc voutn $&voutn '
    'vb2 $&vb2 vbref $&vbref idd $&idd pdc $&pdc"\n')


def add_dc_audit(text: str) -> str:
    """Add the feed-study DC audit line after the verification deck's OP line
    (print-only: no element or analysis changes)."""
    if text.count(OP_ANCHOR) != 1:
        raise ValueError("verification deck lacks a unique OP echo line")
    return text.replace(OP_ANCHOR, OP_ANCHOR + DC_AUDIT)


# ---------------------------------------------------------------------------
# Characterization summary (pure)
# ---------------------------------------------------------------------------
def char_summary(data: dict) -> dict:
    """Per Le-loss case: NFmin@290 mid / worst-in-band, 50-ohm sp NF@290 mid,
    Zin / Zopt / Rn at the band centre."""
    out = {}
    for case, rows in data["cases"].items():
        nfm = [ms.nf_reref(r["nfmin_t_db"], ms.T_ANALYSIS) for r in rows]
        mid = rows[ms.MID]
        zopt = ms.z_from_s(mid["noise"]["gopt"])
        out[case] = {"nfmin290_mid_db": nfm[ms.MID], "nfmin290_worst_db": max(nfm),
                     "nf50_290_sp_mid_db": ms.nf_reref(mid["nf_sp_db"], ms.T_ANALYSIS),
                     "zin_mid": [mid["zin"].real, mid["zin"].imag], "zopt_mid": [zopt.real, zopt.imag],
                     "rn_mid": mid["noise"]["rn"]}
    return out


def nf_split(cs: dict, entry: dict, nf290_mid: float) -> dict:
    """Band-centre NF decomposition (dB). Two of the four terms are solver
    PREDICTIONS (marked), not simulated: intrinsic floor (ideal Le, measured),
    Le loss (measured NFmin q10 - ideal), mismatch (predicted DUT-only NF at
    the presented Zs - NFmin q10), input-network loss (predicted lossy cascade
    - predicted DUT-only), residual (verified - predicted)."""
    f0 = cs["ideal"]["nfmin290_mid_db"]
    fq = cs["q10"]["nfmin290_mid_db"]
    p_dut = entry["predicted_twoport_nf290_mid_db"]
    p_all = entry["predicted"][ms.MID]["nf290_db"]
    return {"floor_ideal_le_db": f0, "le_loss_db": fq - f0, "mismatch_pred_db": p_dut - fq,
            "network_loss_pred_db": p_all - p_dut, "residual_db": nf290_mid - p_all,
            "total_over_floor_db": nf290_mid - f0}


# ---------------------------------------------------------------------------
# Grading, shortlist, recommendation (pure)
# ---------------------------------------------------------------------------
def non_noise_ok(m: dict) -> bool:
    return (m["s11_db_worst"] < ms.ROW_S11_DB and m["s22_db_worst"] < ms.ROW_S22_DB
            and m["s21_db_min"] > ms.ROW_S21_DB and not m["mu_bb_min"] < 1.0 - ms.MU_RESOLUTION)


def shortlist(points: dict):
    """The finite-feed point with the lowest VERIFIED worst-in-band NF290
    among DC-valid, convergent points that pass the non-noise gates (S11,
    S22, |S21|, mu); if none passes those, among DC-valid convergent points.
    Ties: lower Le. points[pid] -> {'feed','le_nh','status','scan','match'}.
    Returns (pid or None, 'all non-noise gates' | 'fallback' | None)."""
    pool = []
    for pid, p in points.items():
        if p["feed"] != FINITE_FEED or p.get("status") != "verified":
            continue
        s, m = p["scan"], p["match"]
        if s["dc_flags"] or not s["convergence"]["normal"] or not m["convergence"]["normal"]:
            continue
        pool.append((p["match"]["nf290_db_worst"], p["le_nh"], pid, non_noise_ok(m)))
    if not pool:
        return None, None
    good = [x for x in pool if x[3]]
    if good:
        return min(good)[2], "all non-noise gates"
    return min(pool)[2], "fallback"


def recommend_le(scan, match, bracket, margin_db: float = fs.PVT_NF_MARGIN_DB) -> dict:
    """fs.recommend on the shortlisted point, plus the declared worse-Q
    bracket gate: GO additionally needs the same network with Le at
    Q = Q_LE_BRACKET to keep the verified worst-in-band NF290 <= the limit."""
    rec = fs.recommend(scan, match, margin_db)
    if scan is None or match is None:
        return rec
    failing = list(rec["failing"])
    if bracket is None or bracket["nf290_db_worst"] > rec["limit_db"]:
        failing.append("le_q_bracket")
    failing = [g for g in GATES_LE if g in failing]
    rec.update({"verdict": "GO" if not failing else "NO-GO", "binding": failing[0] if failing else None,
                "failing": failing,
                "bracket_nf290_worst_db": None if bracket is None else bracket["nf290_db_worst"]})
    return rec


def control_rows(feed: str, new: dict, prior: dict, new_vals, prior_vals) -> list:
    """[(quantity, new, prior, |diff|, tol, ok)] for one 1 nH control."""
    rows = []
    for k in ("nf290_db_worst", "nf290_db_mid", "s11_db_worst", "s22_db_worst", "s21_db_min"):
        d = abs(new[k] - prior[k])
        rows.append((k, new[k], prior[k], d, CONTROL_TOL_DB, d <= CONTROL_TOL_DB))
    d = abs(new["mu_bb_min"] - prior["mu_bb_min"])
    rows.append(("mu_bb_min", new["mu_bb_min"], prior["mu_bb_min"], d, CONTROL_TOL_MU, d <= CONTROL_TOL_MU))
    d = abs(new["ic1"] / prior["ic1"] - 1.0)
    rows.append(("ic1_rel", new["ic1"], prior["ic1"], d, CONTROL_TOL_IC1_REL, d <= CONTROL_TOL_IC1_REL))
    for name, a, b in zip(("input_series_rel", "input_shunt_rel"), new_vals, prior_vals):
        d = abs(a / b - 1.0)
        rows.append((name, a, b, d, CONTROL_TOL_VAL_REL, d <= CONTROL_TOL_VAL_REL))
    return [(feed,) + r for r in rows]


# ---------------------------------------------------------------------------
# Declaration (printed, committed before the run)
# ---------------------------------------------------------------------------
def declaration_text() -> str:
    pts = study_points()
    L = ["# Le-study declaration (issue #198)", "",
         "Committed BEFORE any simulation of this study. Generated by",
         "`python3 -I sim/lna-matching-feasibility/le_study.py declare`; a unit test",
         "checks that this file equals that output, so it cannot drift from the code.", "",
         "**NOMINAL-CELL EXPLORATION.** One PVT cell (hbt_typ / mos_tt, 27 C, 1.80 V). No",
         "ratified-row, conformance or final-stability claim; `design/` and `spec/` are not",
         "modified; adopting any Le or feed change needs a decision record and full PVT evidence.", "",
         "## Question", "",
         "Record `20261010-233800-d1312cc` (#193) found NO-GO with Le fixed at the committed",
         "1 nH. Does jointly choosing the emitter degeneration Le and the (re-synthesized)",
         "noise-weighted input match reduce the verified matched NF@290 of the finite",
         "base feed enough to justify a later full-PVT campaign? The unresized DUT is the",
         "control (emitter size / cascode split belong to #58); the bias is never retuned.", "",
         "## Point set", "",
         "| Point | Feed | Le (nH) | Role |", "|---|---|---|---|"]
    for p in pts:
        L.append(f"| `{p['id']}` | `{p['feed']}` | {p['le_nh']:g} | {p['role']}"
                 + (" (1 nH control)" if p["control"] and p["feed"] in FEEDS else "") + " |")
    L += ["",
          f"Feeds are the #193 definitions (`feed_study.py` VARIANTS): `committed` (R3b = 330 Ohm),",
          f"`{FINITE_FEED}` (EM 5-turn spiral || PDK `cap_cmim`, in series with R3b; the finite",
          "feed of this study), `ideal_choke` (ideal 1 uH, a DIAGNOSTIC BOUND, never a design) and,",
          "at 1 nH only, `em5_cideal` (the finite feed #193 verified, kept as a reproduction",
          "control). Tank C and `cap_cmim` size are REUSED from the retained #193 feed plan",
          f"(`netlist-snapshots/{PRIOR_RID}/feed_plan.json`, sha256",
          f"`{sha256(PRIOR_SNAP / 'feed_plan.json')}`), not re-measured.", "",
          "## Bench per point", "",
          "- Characterization: the #186 deck (`tb_match_char`) with the feed swapped in and Le",
          "  an EXPLICIT input: the DUT's Le line is replaced by the point's value, the Le-loss",
          "  cases are " + ", ".join(f"`{c}`" for c in CHAR_CASES_LE) + " (parallel loss R = Q*w*Le recomputed",
          "  from the point's own Le), and the ideal-Le sweep (which resets Le to 1 nH) is omitted.",
          f"- Synthesis: the existing `{MATCH_CANDIDATE}` input match, Q = {Q_LE:g} case (Le, Lc and the",
          "  input inductor at Q = 10), re-synthesized from the point's own characterization; the",
          "  committed output network (Lc 5 nH + shunt C + series C), likewise re-solved. A point",
          "  whose synthesis fails or is infeasible is REJECTED with the reason retained.",
          "- Verification: the #186 deck (`tb_match_verify`) with the feed swapped in, Rxoutdc =",
          f"  {fs.XOUT_RDC:g} Ohm on xout (#190), plus a print-only DC audit line (the #193 audit:",
          "  IC1/IC2/IB1, node voltages, IDD, Pdc).", "",
          "## Model provenance and assumptions", "",
          "- DUT `design/netlist/lna.spice` unresized; `hbt_typ` / `mos_tt`; ngspice >= 46.",
          "- Le is an ideal inductor with an ASSUMED loss: no extracted model exists for these",
          "  values (the smallest extracted spiral, em1, is 0.097 nH at Q 4.1). Q = 10 is the",
          f"  assumed case; Q = {Q_LE_BRACKET:g} is the worse-Q bracket. An assumed Le value / Q is",
          "  not a layout feasibility claim.",
          "- The default loss model is a PARALLEL resistor (DC-transparent, as in #186/#193). A",
          "  SERIES-loss implementation carries the emitter current; its DC effect is measured",
          "  once, on the shortlisted point, and reported separately.",
          "- EM spiral model `sim/models/sg13g2_inductor_em.spice` and PDK `cap_cmim`, as in #193",
          "  (one process point; no MIM bottom-plate parasitic in the model).", "",
          "## Policy declared before running (bench policy, NOT ratified)", "",
          f"1. Controls (1 nH; `committed`, `ideal_choke`, `em5_cideal`) must reproduce record",
          f"   `{PRIOR_RID}`: verified NF290 worst and mid, S11 / S22 worst and |S21| min within",
          f"   {CONTROL_TOL_DB:g} dB, broadband mu minimum within {CONTROL_TOL_MU:g}, IC1 within",
          f"   {CONTROL_TOL_IC1_REL:g} relative, synthesized Lb / Cp within {CONTROL_TOL_VAL_REL:g} relative.",
          "   STOPPING RULE: if any control is outside tolerance, the run stops before the",
          "   remaining verification decks; the discrepancy is investigated, not widened.",
          f"2. DC validity: the #193 flags (|dIC1| or |dIDD| > {fs.IC1_SHIFT_FLAG:.0%} vs `committed` at 1 nH,",
          f"   VCE < {fs.VCE_MIN:g} V, VBC > {fs.VBC_MAX:g} V, non-positive IC); convergence: no singular",
          "   matrix, failed gmin/source stepping or transient-op fallback in char or verify log.",
          f"3. Shortlist (selection rule): among `{FINITE_FEED}` points that are verified, DC-valid",
          "   and convergent, the lowest VERIFIED worst-in-band NF290 among those passing",
          "   S11 / S22 < -10 dB, |S21| > 15 dB and no resolved mu < 1 (10 MHz-30 GHz, resolution",
          f"   {ms.MU_RESOLUTION:g}); if none passes those, the lowest NF290 among the DC-valid",
          "   convergent points (reported as a fallback). Ties go to the lower Le. No selection",
          "   uses a solver prediction.",
          "4. Brackets, shortlisted point only, same network (not re-synthesized): (a) Le loss at",
          f"   Q = {Q_LE_BRACKET:g} (parallel); (b) Le loss at Q = {Q_LE:g} as a SERIES resistor (DC effect).",
          "   STOPPING RULE: no shortlisted point -> no bracket decks; verdict NO-GO.",
          f"5. GO / NO-GO for a later full-PVT campaign: GO only if the shortlisted point's",
          f"   VERIFIED matched worst-in-band NF@290 <= {ms.ROW_NF_DB:g} - {fs.PVT_NF_MARGIN_DB:g} dB (the",
          "   nominal-cell allowance for PVT / passive spread, bench policy distinct from the",
          f"   ratified {ms.ROW_NF_DB:g} dB row), its DUT NFmin@290 worst-in-band (Le at Q = 10) is",
          "   below that limit, S11 / S22 < -10 dB, |S21| > 15 dB, no resolved mu < 1, DC-valid,",
          f"   convergent, AND bracket (a) keeps NF290 worst <= the same limit. Otherwise NO-GO;",
          "   the first failing gate in the order " + " > ".join(GATES_LE),
          "   is the binding constraint. Ideal-choke numbers are diagnostic only.",
          "6. Reported per point: NFmin@290 (ideal Le, Le Q = 10, Le Q = 5) separately from the",
          "   verified matched 50-ohm NF@290, and the band-centre split into intrinsic floor, Le",
          "   loss, mismatch penalty (predicted), input-network loss (predicted), residual.", "",
          "## Run budget", "",
          f"Single-process `ngspice -b` decks, strictly sequential, nominal cell only: {len(pts)}",
          f"characterizations + {len(pts)} verifications + 2 brackets = {planned_decks()} <= {DECK_BUDGET}.",
          "No corner grid, no Monte Carlo, no fleet submission and no local-grid fallback.", ""]
    return "\n".join(L) + "\n"


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def _wr(path, text):
    Path(path).write_text(text)


def _ns(a, outdir: str):
    return SimpleNamespace(models_lib=a.models_lib, mos_lib=a.mos_lib, osdi_dir=a.osdi_dir, outdir=outdir,
                           deckdir=a.snapdir, relative_em=False, nf_npts=getattr(a, "nf_npts", ms.N_NF_DEFAULT))


def render_char(a, p: dict, plan: dict) -> str:
    sub = str(Path(a.outdir) / "charset" / p["id"])
    text = ms.char_deck(_ns(a, sub), le_nh=p["le_nh"], char_cases=CHAR_CASES_LE, le_sweep=False)
    text = fs.apply_feed(text, p["feed"], plan, a.cap_lib)
    fs.assert_feed_dc_path(text)
    check_le_deck(text, p["le_nh"], "char")
    return text


def render_verify(a, e: dict, plan: dict) -> str:
    text = fs.apply_feed(ms.verify_deck(_ns(a, a.outdir), e, e["stem"]), e["feed_variant"], plan, a.cap_lib)
    fs.assert_feed_dc_path(text)
    check_le_deck(text, e["le_nh"], "verify", e.get("le_q", e["q"]), e.get("le_loss", "parallel"))
    return add_dc_audit(text)


def cmd_char_gen(a):
    pts = study_points()
    plan = prior_feed_plan()
    snap = Path(a.snapdir)
    for p in pts:
        (Path(a.outdir) / "charset" / p["id"]).mkdir(parents=True, exist_ok=True)
        _wr(snap / f"char_{p['id']}.spice", render_char(a, p, plan))
    doc = {"generator": "sim/lna-matching-feasibility/le_study.py char-gen",
           "design_netlist_sha256": ms.sha256(ms.DESIGN_NETLIST), "em_model_sha256": ms.sha256(ms.EM_MODEL),
           "prior_record": PRIOR_RID, "prior_feed_plan_sha256": sha256(PRIOR_SNAP / "feed_plan.json"),
           "char_cases": CHAR_CASES_LE, "points": pts, "feed_plan": plan}
    _wr(snap / "le_plan.json", json.dumps(doc, indent=2) + "\n")
    print(f"char-gen: {len(pts)} characterization decks + le_plan.json in {snap}")


def _load(snapdir, name):
    return json.loads((Path(snapdir) / name).read_text())


def solve_point(cdir: Path, p: dict):
    """(entry, char_summary) or raises ValueError/RuntimeError (rejection)."""
    data = ms.load_char(cdir, require_feed=False, char_cases=CHAR_CASES_LE, require_sweep=False)
    cs = char_summary(data)
    entries, _ = ms.synthesize(data, le_nh=p["le_nh"],
                               candidates={MATCH_CANDIDATE: ms.CANDIDATES[MATCH_CANDIDATE]},
                               qcases={SOURCE_Q_CASE: ms.QCASES[SOURCE_Q_CASE]}, char_cases=CHAR_CASES_LE)
    e = dict(entries[0])
    if e.get("infeasible"):
        raise ValueError(f"{MATCH_CANDIDATE}:{SOURCE_Q_CASE} infeasible ({e['infeasible']})")
    e.update({"le_nh": p["le_nh"], "feed_variant": p["feed"], "point": p["id"],
              "xout_rdc_ohm": fs.XOUT_RDC, "stem": f"verify_{p['id']}", "char": cs,
              "char_op": data["op"]})
    return e, cs


def cmd_solve(a):
    doc = _load(a.snapdir, "le_plan.json")
    plan = doc["feed_plan"]
    entries, rejected = [], []
    for p in doc["points"]:
        cdir = Path(a.corners) / "charset" / p["id"]
        try:
            e, _ = solve_point(cdir, p)
        except (ValueError, RuntimeError, KeyError) as ex:
            rejected.append({**p, "reason": f"{type(ex).__name__}: {ex}"})
            continue
        e["control"] = p["control"]
        e["role"] = p["role"]
        _wr(Path(a.snapdir) / f"{e['stem']}.spice", render_verify(a, e, plan))
        entries.append(e)
    out = {"generator": "sim/lna-matching-feasibility/le_study.py solve", "nf_npts": a.nf_npts,
           "xout_rdc_ohm": fs.XOUT_RDC, "candidates": entries, "rejected": rejected}
    _wr(Path(a.snapdir) / "le_match_plan.json", json.dumps(out, indent=2, default=str) + "\n")
    print(f"solve: {len(entries)} verification decks, {len(rejected)} rejected point(s)")


def cmd_stems(a):
    snap = Path(a.snapdir)
    if a.group == "char":
        stems = [f"char_{p['id']}" for p in _load(snap, "le_plan.json")["points"]]
    elif a.group in ("control", "rest"):
        want = a.group == "control"
        stems = [e["stem"] for e in _load(snap, "le_match_plan.json")["candidates"] if bool(e["control"]) == want]
    else:
        f = snap / "le_shortlist.json"
        stems = [b["stem"] for b in json.loads(f.read_text())["brackets"]] if f.exists() else []
    print("\n".join(stems))
    return 0


def prior_reference(feed: str):
    stem = f"match_{feed}_{MATCH_CANDIDATE}_{SOURCE_Q_CASE}"
    m = ms.reduce_one(PRIOR_CORNERS, stem, ms.N_NF_DEFAULT)["metrics"]
    mp = json.loads((PRIOR_SNAP / "match_plan.json").read_text())
    vals = next(e["input_values"] for e in mp["candidates"] if e["feed_variant"] == feed)
    return m, vals


def control_check(snapdir, corners):
    doc = _load(snapdir, "le_match_plan.json")
    rows, missing = [], []
    for feed in CONTROL_FEEDS:
        pid = point_id(feed, CONTROL_LE_NH)
        e = next((x for x in doc["candidates"] if x["point"] == pid), None)
        if e is None:
            missing.append(pid)
            continue
        new = ms.reduce_one(Path(corners), e["stem"], doc["nf_npts"])["metrics"]
        prior, pvals = prior_reference(feed)
        rows += control_rows(feed, new, prior, e["input_values"], pvals)
    return rows, missing


CONTROL_COLS = ["control_feed", "quantity", "this_study", "record_" + PRIOR_RID, "abs_diff", "tolerance", "within"]


def write_control_csv(path, rows):
    with open(path, "w", newline="") as fh:
        w = csv.writer(fh, lineterminator="\n")
        w.writerow(CONTROL_COLS)
        for r in rows:
            w.writerow([r[0], r[1], f"{r[2]:.10g}", f"{r[3]:.10g}", f"{r[4]:.3e}", f"{r[5]:g}",
                        "yes" if r[6] else "NO"])


def cmd_control_check(a):
    rows, missing = control_check(a.snapdir, a.corners)
    write_control_csv(a.csv, rows)
    bad = [r for r in rows if not r[6]]
    for r in bad:
        print(f"control-check: {r[0]} {r[1]} {r[2]:.10g} vs {r[3]:.10g} (|d| {r[4]:.3e} > {r[5]:g})", file=sys.stderr)
    for pid in missing:
        print(f"control-check: control {pid} was rejected at synthesis", file=sys.stderr)
    print(f"control-check: {len(rows)} comparisons, {len(bad)} outside tolerance, {len(missing)} missing")
    return 1 if bad or missing else 0


def point_result(corners: Path, e: dict, base_audit: dict | None, nf_npts: int) -> dict:
    """Verified metrics + DC audit + flags for one verification stem."""
    log = corners / f"{e['stem']}.log"
    m = ms.reduce_one(corners, e["stem"], nf_npts)["metrics"]
    m["convergence"] = ms.classify_convergence(log)
    audit = fs.parse_dc_audit(log)
    return {"match": m, "audit": audit,
            "dc_flags": fs.dc_flags(audit, base_audit) if base_audit is not None else []}


def collect(snapdir, corners) -> tuple:
    """Every verified point: {'feed','le_nh','status','scan','match',...}."""
    doc = _load(snapdir, "le_match_plan.json")
    corners = Path(corners)
    by_pid = {e["point"]: e for e in doc["candidates"]}
    base_pid = point_id("committed", CONTROL_LE_NH)
    if base_pid not in by_pid:
        raise ValueError(f"DC reference point {base_pid} was not verified")
    base_audit = fs.parse_dc_audit(corners / f"{by_pid[base_pid]['stem']}.log")
    pts = {}
    for e in doc["candidates"]:
        r = point_result(corners, e, base_audit, doc["nf_npts"])
        conv_char = ms.classify_convergence(corners / "charset" / e["point"] / "char.log")
        scan = {"dc_flags": r["dc_flags"], "nfmin290_worst_db": e["char"]["q10"]["nfmin290_worst_db"],
                "convergence": {"normal": conv_char["normal"], "char": conv_char}}
        pts[e["point"]] = {"feed": e["feed_variant"], "le_nh": e["le_nh"], "role": e["role"],
                           "control": e["control"], "status": "verified", "entry": e, "scan": scan,
                           "match": r["match"], "audit": r["audit"]}
    for rj in doc["rejected"]:
        pts[rj["id"]] = {"feed": rj["feed"], "le_nh": rj["le_nh"], "role": rj["role"], "control": rj["control"],
                         "status": "rejected", "reason": rj["reason"]}
    return doc, pts, base_audit


def cmd_shortlist(a):
    doc, pts, _ = collect(a.snapdir, a.corners)
    pid, how = shortlist(pts)
    brackets = []
    if pid is not None:
        plan = _load(a.snapdir, "le_plan.json")["feed_plan"]
        base = pts[pid]["entry"]
        for tag, q, loss in (("q5par", Q_LE_BRACKET, "parallel"), ("q10ser", Q_LE, "series")):
            e = dict(base)
            e.update({"le_q": q, "le_loss": loss, "stem": f"bracket_{pid}_{tag}", "bracket": tag, "control": False})
            _wr(Path(a.snapdir) / f"{e['stem']}.spice", render_verify(a, e, plan))
            brackets.append(e)
    _wr(Path(a.snapdir) / "le_shortlist.json", json.dumps(
        {"shortlisted": pid, "rule": how, "brackets": brackets}, indent=2, default=str) + "\n")
    print(f"shortlist: {pid} ({how}); {len(brackets)} bracket deck(s)")
    return 0


POINT_COLS = ["point", "feed", "role", "le_nh", "le_q", "le_loss", "status", "reason",
              "input_lb_nh", "input_cp_pf", "output_cp_pf", "output_cs_pf",
              "nfmin290_idealLe_mid_db", "nfmin290_idealLe_worst_db", "nfmin290_q10_mid_db",
              "nfmin290_q10_worst_db", "nfmin290_q5_mid_db", "nf50_290_sp_q10_mid_db",
              "zin_q10_mid_r", "zin_q10_mid_i", "zopt_q10_mid_r", "zopt_q10_mid_i", "rn_q10_mid_ohm",
              "pred_dut_nf290_mid_db", "pred_nf290_mid_db", "nf290_mid_db", "nf290_worst_db",
              "le_loss_db", "mismatch_pred_db", "network_loss_pred_db", "residual_db",
              "s11_worst_db", "s22_worst_db", "s21_min_db", "s21_max_db", "mu_bb_min", "mu_bb_f_min_hz",
              "k_bb_min", "ic1_ma", "idd_ma", "pdc_mw", "vbe1_v", "ve1_mv", "vce1_v", "vce2_v", "vbc1_v",
              "vbc2_v", "dc_flags", "char_convergence", "verify_convergence", "gates_failing", "feas_Le", "feas_Lb"]


def _g(x, nd=6):
    return "" if x is None else f"{x:.{nd}g}"


def point_row(pid, p, rec=None, le_q=Q_LE, le_loss="parallel", bracket: bool = False) -> list:
    """One CSV row. Bracket rows reuse the shortlisted network but not its
    characterization: their NFmin / prediction / decomposition cells are blank."""
    if p["status"] != "verified":
        return [pid, p["feed"], p["role"], _g(p["le_nh"]), _g(le_q), le_loss, p["status"], p["reason"]] + \
               [""] * (len(POINT_COLS) - 8)
    e, m, a, cs = p["entry"], p["match"], p["audit"], p["entry"]["char"]
    sp = nf_split(cs, e, m["nf290_db_mid"])
    row = [pid, p["feed"], p["role"], _g(p["le_nh"]), _g(le_q), le_loss, p["status"], "",
            _g(e["input_values"][0] * 1e9), _g(e["input_values"][1] * 1e12), _g(e["cp_out"] * 1e12),
            _g(e["cs_out"] * 1e12),
            _g(cs["ideal"]["nfmin290_mid_db"]), _g(cs["ideal"]["nfmin290_worst_db"]),
            _g(cs["q10"]["nfmin290_mid_db"]), _g(cs["q10"]["nfmin290_worst_db"]), _g(cs["q5"]["nfmin290_mid_db"]),
            _g(cs["q10"]["nf50_290_sp_mid_db"]),
            _g(cs["q10"]["zin_mid"][0]), _g(cs["q10"]["zin_mid"][1]), _g(cs["q10"]["zopt_mid"][0]),
            _g(cs["q10"]["zopt_mid"][1]), _g(cs["q10"]["rn_mid"]),
            _g(e["predicted_twoport_nf290_mid_db"]), _g(e["predicted"][ms.MID]["nf290_db"]),
            _g(m["nf290_db_mid"]), _g(m["nf290_db_worst"]),
            _g(sp["le_loss_db"]), _g(sp["mismatch_pred_db"]), _g(sp["network_loss_pred_db"]), _g(sp["residual_db"]),
            _g(m["s11_db_worst"]), _g(m["s22_db_worst"]), _g(m["s21_db_min"]), _g(m["s21_db_max"]),
            f"{m['mu_bb_min']:.10f}", _g(m["mu_bb_f_min_hz"]), _g(m["k_bb_min"]),
            _g(a["ic1"] * 1e3), _g(a["idd"] * 1e3), _g(a["pdc"] * 1e3), _g(a["vbe1"]), _g(a["ve1"] * 1e3),
            _g(a["vce1"]), _g(a["vce2"]), _g(a["vbc1"]), _g(a["vbc2"]),
            ";".join(p["scan"]["dc_flags"]), "normal" if p["scan"]["convergence"]["normal"] else "FLAGGED",
            "normal" if m["convergence"]["normal"] else "FLAGGED",
            ";".join(rec["failing"]) if rec else "", e["feasibility"]["Le"], e["feasibility"]["Lb"]]
    if bracket:
        for c in ("nfmin290_idealLe_mid_db", "nfmin290_idealLe_worst_db", "nfmin290_q10_mid_db",
                  "nfmin290_q10_worst_db", "nfmin290_q5_mid_db", "nf50_290_sp_q10_mid_db", "zin_q10_mid_r",
                  "zin_q10_mid_i", "zopt_q10_mid_r", "zopt_q10_mid_i", "rn_q10_mid_ohm", "pred_dut_nf290_mid_db",
                  "pred_nf290_mid_db", "le_loss_db", "mismatch_pred_db", "network_loss_pred_db", "residual_db",
                  "char_convergence"):
            row[POINT_COLS.index(c)] = ""
    return row


def bracket_results(snapdir, corners, pts, base_audit, nf_npts):
    f = Path(snapdir) / "le_shortlist.json"
    sl = json.loads(f.read_text())
    out = {}
    for b in sl["brackets"]:
        r = point_result(Path(corners), b, base_audit, nf_npts)
        out[b["bracket"]] = {"entry": b, **r}
    return sl, out


def cmd_reduce(a):
    doc, pts, base_audit = collect(a.snapdir, a.corners)
    sl, br = bracket_results(a.snapdir, a.corners, pts, base_audit, doc["nf_npts"])
    pid = sl["shortlisted"]
    problems = []
    grades = {}
    for k, p in pts.items():
        if p["status"] != "verified":
            problems.append(f"{k}: rejected at synthesis ({p['reason']})")
            continue
        grades[k] = fs.recommend(p["scan"], p["match"])
        if not p["scan"]["convergence"]["normal"] or not p["match"]["convergence"]["normal"]:
            problems.append(f"{k}: operating-point convergence fallback/warning")
        if abs(p["match"]["gt_minus_s21_db_mid"]) > 1e-3:
            problems.append(f"{k}: transducer-gain cross-check off by {p['match']['gt_minus_s21_db_mid']:.4g} dB")
    for tag, b in br.items():
        if not b["match"]["convergence"]["normal"]:
            problems.append(f"bracket {tag}: operating-point convergence fallback/warning")
    if pid is None:
        rec = recommend_le(None, None, None)
    else:
        q5 = br.get("q5par")
        rec = recommend_le(pts[pid]["scan"], {**pts[pid]["match"]}, q5["match"] if q5 else None)
    bound_pts = [k for k, p in pts.items() if p["feed"] == "ideal_choke" and p["status"] == "verified"]
    bound = min(bound_pts, key=lambda k: (pts[k]["match"]["nf290_db_worst"], pts[k]["le_nh"])) if bound_pts else None
    with open(a.csv, "w", newline="") as fh:
        w = csv.writer(fh, lineterminator="\n")
        w.writerow(POINT_COLS)
        for k, p in pts.items():
            w.writerow(point_row(k, p, grades.get(k)))
        for tag, b in br.items():
            e = b["entry"]
            bp = {**pts[pid], "match": b["match"], "audit": b["audit"],
                  "scan": {**pts[pid]["scan"], "dc_flags": b["dc_flags"]}}
            w.writerow(point_row(e["stem"], bp, None, e["le_q"], e["le_loss"], bracket=True))
    rj = {"shortlisted": pid, "rule": sl["rule"], "recommendation": rec,
          "ideal_bound_best_point": bound, "ideal_bound_gates": grades.get(bound) if bound else None,
          "per_point_gates": grades, "problems": problems}
    _wr(Path(a.corners) / "recommendation.json", json.dumps(rj, indent=2) + "\n")
    _wr(a.markdown, markdown(doc, pts, grades, sl, br, rec, bound, problems, a.control_csv))
    print(f"reduce: shortlisted {pid}; {rec['verdict']} (binding: {rec['binding']}); {len(problems)} problem(s)")
    return 1 if [p for p in problems if "rejected" not in p] else 0


def _fz(z):
    return f"{z[0]:.1f}{z[1]:+.1f}j"


def markdown(doc, pts, grades, sl, br, rec, bound, problems, control_csv) -> str:
    L = ["#### 1 nH controls vs record `" + PRIOR_RID + "` (declared tolerances)", "",
         "| Control | Quantity | This study | Record | abs diff | Tolerance | Within |", "|---|---|---|---|---|---|---|"]
    with open(control_csv) as fh:
        for r in list(csv.reader(fh))[1:]:
            L.append("| " + " | ".join(r) + " |")
    L += ["", "#### Per point: noise floor vs verified matched NF (nominal cell; T0 = 290 K; `lp_noise` Q = 10 re-synthesized per point)", "",
          "| Point | Le (nH) | Lb / Cp | NFmin@290 ideal Le mid / worst | NFmin@290 Le Q10 mid / worst | NFmin@290 Le Q5 mid | "
          "Verified NF290 mid / worst | S11 / S22 worst | \\|S21\\| min | mu bb min | IC1 (mA) | DC flags | Gates failing |",
          "|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for k, p in pts.items():
        if p["status"] != "verified":
            L.append(f"| `{k}` | {p['le_nh']:g} | REJECTED: {p['reason']} | | | | | | | | | | |")
            continue
        e, m, cs = p["entry"], p["match"], p["entry"]["char"]
        L.append(f"| `{k}` | {p['le_nh']:g} | {e['input_values'][0] * 1e9:.3f} nH / {e['input_values'][1] * 1e12:.3f} pF | "
                 f"{cs['ideal']['nfmin290_mid_db']:.3f} / {cs['ideal']['nfmin290_worst_db']:.3f} | "
                 f"{cs['q10']['nfmin290_mid_db']:.3f} / {cs['q10']['nfmin290_worst_db']:.3f} | {cs['q5']['nfmin290_mid_db']:.3f} | "
                 f"{m['nf290_db_mid']:.3f} / **{m['nf290_db_worst']:.3f}** | {m['s11_db_worst']:.2f} / {m['s22_db_worst']:.2f} | "
                 f"{m['s21_db_min']:.2f} | {m['mu_bb_min']:.10f} | {p['audit']['ic1'] * 1e3:.5f} | "
                 f"{'; '.join(p['scan']['dc_flags']) or 'none'} | {', '.join(grades[k]['failing']) or 'none'} |")
    L += ["", "#### Band-centre NF decomposition (dB; `pred` terms are solver predictions, the rest simulated)", "",
          "| Point | Zin (Le Q10) | Zopt (Le Q10) | Intrinsic floor (ideal Le) | + Le loss (Q10) | + mismatch (pred) | "
          "+ input-network loss (pred) | + residual | = verified NF290 mid | Le feasibility |",
          "|---|---|---|---|---|---|---|---|---|---|"]
    for k, p in pts.items():
        if p["status"] != "verified":
            continue
        e, m, cs = p["entry"], p["match"], p["entry"]["char"]
        s = nf_split(cs, e, m["nf290_db_mid"])
        L.append(f"| `{k}` | {_fz(cs['q10']['zin_mid'])} | {_fz(cs['q10']['zopt_mid'])} | {s['floor_ideal_le_db']:.3f} | "
                 f"{s['le_loss_db']:+.3f} | {s['mismatch_pred_db']:+.3f} | {s['network_loss_pred_db']:+.3f} | "
                 f"{s['residual_db']:+.3f} | {m['nf290_db_mid']:.3f} | {e['feasibility']['Le']} |")
    pid = sl["shortlisted"]
    L += ["", "#### Shortlist and brackets", "",
          f"- Shortlisted `{FINITE_FEED}` point (declared rule, verified numbers only): `{pid}` ({sl['rule']})."]
    if pid is not None:
        base = pts[pid]
        L += ["", "| Variant | Le loss | NF290 mid / worst (dB) | S11 / S22 worst (dB) | \\|S21\\| min (dB) | mu bb min | "
              "IC1 (mA) | dIC1 vs committed 1 nH | VBE1 (V) | VE1 (mV) | Pdc (mW) | DC flags |",
              "|---|---|---|---|---|---|---|---|---|---|---|---|"]
        rows = [("shortlisted", f"parallel, Q = {Q_LE:g}", base["match"], base["audit"], base["scan"]["dc_flags"])]
        for tag, b in br.items():
            rows.append((f"bracket `{tag}`", f"{b['entry']['le_loss']}, Q = {b['entry']['le_q']:g}",
                         b["match"], b["audit"], b["dc_flags"]))
        ref = pts[point_id("committed", CONTROL_LE_NH)]["audit"]
        for name, loss, m, au, fl in rows:
            L.append(f"| {name} | {loss} | {m['nf290_db_mid']:.3f} / {m['nf290_db_worst']:.3f} | "
                     f"{m['s11_db_worst']:.2f} / {m['s22_db_worst']:.2f} | {m['s21_db_min']:.2f} | {m['mu_bb_min']:.10f} | "
                     f"{au['ic1'] * 1e3:.5f} | {(au['ic1'] / ref['ic1'] - 1) * 100:+.3f} % | {au['vbe1']:.4f} | "
                     f"{au['ve1'] * 1e3:.3f} | {au['pdc'] * 1e3:.4f} | {'; '.join(fl) or 'none'} |")
    L += ["", "#### Go / no-go for a subsequent full-PVT campaign", "",
          f"- Policy limit (declared, bench policy): verified matched NF290 worst-in-band <= {ms.ROW_NF_DB:g} - "
          f"{fs.PVT_NF_MARGIN_DB:g} = {rec['limit_db']:.2f} dB; the ratified row is {ms.ROW_NF_DB:g} dB.",
          f"- **Verdict: {rec['verdict']}**" + (f"; binding constraint: `{rec['binding']}`; failing gates: "
                                               f"{', '.join(rec['failing'])}." if rec["failing"] else ".")]
    if "nf290_worst_db" in rec:
        L.append(f"- Shortlisted verified NF290 worst-in-band {rec['nf290_worst_db']:.3f} dB; DUT NFmin@290 worst-in-band "
                 f"(Le Q = 10) {rec['nfmin290_worst_db']:.3f} dB; remaining budget against the {ms.ROW_NF_DB:g} dB row "
                 f"{rec['nf_budget_left_db']:+.3f} dB" + (f"; worse-Q bracket NF290 worst {rec['bracket_nf290_worst_db']:.3f} dB."
                                                          if rec.get("bracket_nf290_worst_db") is not None else "."))
    ctl = pts.get(point_id(FINITE_FEED, CONTROL_LE_NH))
    if pid is not None and ctl and ctl["status"] == "verified":
        d = pts[pid]["match"]["nf290_db_worst"] - ctl["match"]["nf290_db_worst"]
        L.append(f"- Effect of choosing Le on the finite feed: shortlisted vs `{point_id(FINITE_FEED, CONTROL_LE_NH)}` "
                 f"(committed 1 nH): {d:+.3f} dB verified NF290 worst-in-band.")
    if bound:
        g = grades[bound]
        L.append(f"- Ideal-choke diagnostic (not a design): best point `{bound}`, verified NF290 worst "
                 f"{pts[bound]['match']['nf290_db_worst']:.3f} dB; gates failing: {', '.join(g['failing']) or 'none'}.")
    if problems:
        L += ["", "**Problems / flags:**", ""] + [f"- {x}" for x in problems]
    return "\n".join(L) + "\n"


def add_pdk_args(p):
    fs.add_pdk_args(p)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("declare")
    g = sub.add_parser("char-gen")
    add_pdk_args(g)
    g.add_argument("--snapdir", required=True)
    g.add_argument("--outdir", required=True)
    s = sub.add_parser("solve")
    add_pdk_args(s)
    s.add_argument("--snapdir", required=True)
    s.add_argument("--outdir", required=True)
    s.add_argument("--corners", required=True)
    s.add_argument("--nf-npts", type=int, default=ms.N_NF_DEFAULT)
    t = sub.add_parser("stems")
    t.add_argument("--snapdir", required=True)
    t.add_argument("group", choices=("char", "control", "rest", "bracket"))
    c = sub.add_parser("control-check")
    c.add_argument("--snapdir", required=True)
    c.add_argument("--corners", required=True)
    c.add_argument("--csv", required=True)
    h = sub.add_parser("shortlist")
    add_pdk_args(h)
    h.add_argument("--snapdir", required=True)
    h.add_argument("--outdir", required=True)
    h.add_argument("--corners", required=True)
    h.add_argument("--nf-npts", type=int, default=ms.N_NF_DEFAULT)
    r = sub.add_parser("reduce")
    r.add_argument("--snapdir", required=True)
    r.add_argument("--corners", required=True)
    r.add_argument("--csv", required=True)
    r.add_argument("--control-csv", required=True)
    r.add_argument("--markdown", required=True)
    a = ap.parse_args(argv)
    if a.cmd == "declare":
        sys.stdout.write(declaration_text())
        return 0
    if a.cmd == "solve":
        ms.check_nf_npts(a.nf_npts)
    return {"char-gen": cmd_char_gen, "solve": cmd_solve, "stems": cmd_stems,
            "control-check": cmd_control_check, "shortlist": cmd_shortlist,
            "reduce": cmd_reduce}[a.cmd](a) or 0


if __name__ == "__main__":
    sys.exit(main())
