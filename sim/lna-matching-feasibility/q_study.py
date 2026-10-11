#!/usr/bin/env python3
"""Feed-isolation / input-Q requirements map after the Le-study NO-GO (issue #200).

Companion to run_q_study.sh. The #198 record (20261011-101454-3ec590d) rejected
a full-PVT campaign on emitter degeneration: on the finite `em5_cmim` feed at
Le = 0.6 nH the verified matched NF290 worst-in-band is 2.570 dB, the DUT
NFmin@290 worst is 1.545 dB, and even the ideal-choke diagnostic verifies
1.763 dB. Optimizing Le moved the finite-feed result by only 0.043 dB. This
study quantifies the two requirements that record left unmeasured -- feed
isolation and input-network Q -- instead of another unguided topology search.

It builds on matching_solver.py (bench, synthesis, predictions), feed_study.py
(feed definitions, DC audit, gates) and le_study.py (the retained #198
characterization conventions). Subcommands, in run order:

  declare          print the pre-run declaration (q-study-declaration.md)
  control-gen      render the char control decks (byte-checked against the
                   retained #198 decks), the tank-probe deck, the control
                   verification decks and the bracket char decks
  stems            print deck stems of one group (ctlchar / probe / ctlverify /
                   bracket / boundary), in run order, for the runner
  control-check    compare the re-run char controls and the probe control arm
                   with the retained evidence (non-zero exit: STOP)
  ctl-verify-check compare the re-run control verification metrics with the
                   retained record (non-zero exit: STOP)
  qmap             compute the input-Q requirements map (PREDICTIONS ONLY) from
                   the RETAINED characterization, replay the retained Q = 10
                   entries, select the declared boundary points and write their
                   verification decks + qreq_map.json
  reduce           isolation table (probe + bracket char), the map, threshold
                   crossings, boundary prediction-vs-verification residuals and
                   the separate verdicts

POINT ROLES (declared before the run; every consumer must keep them apart):

  prediction      a map cell: solver synthesis + Friis prediction from the
                  RETAINED characterization. Never evidence of feasibility.
  control         a reproduction deck pair anchored to the retained record.
  bracket         a HYPOTHETICAL REQUIREMENT PROXY: one noisy, DC-transparent
                  parallel resistor across the retained tank, lowering its
                  isolation. Never an extracted geometry, never a design.
  diagnostic      the ideal-choke arm (unrealizable by construction).
  physical        an unmodified-model verified point; the ONLY class that can
                  carry a campaign GO, and it cannot come from this study's
                  hypothetical cells.

NOMINAL-CELL bench exploration. Nothing here edits design/ or spec/, and no
number is a conformance claim. Stdlib only, so the unit tests run PDK-free
in CI.
"""
from __future__ import annotations

import argparse
import bisect
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
import le_study as ls  # noqa: E402
import matching_solver as ms  # noqa: E402

# --- retained evidence this study reuses (never edited) ----------------------
RETAINED_RID = "20261011-101454-3ec590d"        # #198: char tables + match plan
TUNE_RID = "20261010-233800-d1312cc"            # #193: Yser grid, feed plan, cmim probe
RETAINED_SNAP = HERE / "netlist-snapshots" / RETAINED_RID
RETAINED_CORNERS = HERE / "corners" / RETAINED_RID
TUNE_SNAP = HERE / "netlist-snapshots" / TUNE_RID
TUNE_CORNERS = HERE / "corners" / TUNE_RID

# --- declared map ------------------------------------------------------------
LE_STUDY_NH = 0.6                    # Le fixed for the main comparison (#198 shortlist)
Q_LE_FIXED = 10.0                    # emitter loss fixed at the assumed Q (#198 convention)
ARMS = {"em5_cmim": "finite candidate", "ideal_choke": "diagnostic bound"}
Q_IN_CASES = (("q5", 5.0), ("q10", 10.0), ("q20", 20.0), ("q40", 40.0), ("lossless", None))
Q_IN_FINITE = tuple(q for _, q in Q_IN_CASES if q is not None)
INPUT_TOPOLOGY = "lowpass"           # the retained lp_noise input network
MATCH_CANDIDATE = fs.MATCH_CANDIDATE  # lp_noise
SOURCE_Q_CASE = fs.SOURCE_Q_CASE      # q10
CHAR_CASES_LE = ls.CHAR_CASES_LE     # {"ideal": None, "q10": 10.0, "q5": 5.0}

# --- declared feed-loss bracket ----------------------------------------------
TANK_GEOM = "em5"
TANK_Z_RET_OHM = 798.0               # |Ztank| at f_mid derived from the RETAINED
                                     # #193 Yser grid + tuning C + measured cmim ESR
                                     # (the #193 tuning table's 803 Ohm peak agrees);
                                     # frozen here so the bracket is predeclared.
RPAR_OHM = (400.0, 200.0, 100.0)     # ~ TANK_Z_RET_OHM / {2, 4, 8}: thermal-noisy,
                                     # DC-transparent parallel resistors across the tank
RPAR_TAG = {400.0: "r400", 200.0: "r200", 100.0: "r100"}

# --- declared policy (bench policy, NOT ratified) ----------------------------
THRESH_ROW_DB = ms.ROW_NF_DB                       # 1.5 dB ratified row
THRESH_PLAN_DB = ms.ROW_NF_DB - fs.PVT_NF_MARGIN_DB  # 1.2 dB planning limit
XOUT_RDC = fs.XOUT_RDC
BUDGET_CHAR = 8
BUDGET_VERIFY = 8
CONTROL_TOL_DB = 1e-3        # NF290 / S-param dB quantities vs the retained record
CONTROL_TOL_MU = 1e-9        # broadband mu minimum
CONTROL_TOL_IC1_REL = 1e-5   # OP currents
CONTROL_TOL_VAL_REL = 1e-6   # synthesized Lb / Cp, char S-params / impedances
CONTROL_TOL_Z_REL = 0.01     # probe control arm vs the retained-derived tank |Z|
REPLAY_TOL_REL = 1e-9        # Q = 10 replay of the retained synthesis / predictions


def point_id(feed: str) -> str:
    return ls.point_id(feed, LE_STUDY_NH)


def rpar_tag(r: float) -> str:
    if not math.isfinite(r) or r <= 0:
        raise ValueError(f"bracket resistance must be positive and finite (got {r!r})")
    return RPAR_TAG[r]


def sha256(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def retained_entry(feed: str) -> dict:
    """The retained #198 match-plan entry for one arm (input + output network
    and the per-frequency predictions at the retained Q = 10 convention)."""
    doc = json.loads((RETAINED_SNAP / "le_match_plan.json").read_text())
    return dict(next(e for e in doc["candidates"] if e["point"] == point_id(feed)))


def retained_plan() -> dict:
    """The #193 feed plan embedded in the retained #198 le_plan.json."""
    return json.loads((RETAINED_SNAP / "le_plan.json").read_text())["feed_plan"]


def retained_nf_npts() -> int:
    return int(json.loads((RETAINED_SNAP / "le_match_plan.json").read_text())["nf_npts"])


def load_char_dir(cdir: Path) -> dict:
    return ms.load_char(cdir, require_feed=False, char_cases=CHAR_CASES_LE, require_sweep=False)


def retained_char(feed: str) -> dict:
    return load_char_dir(RETAINED_CORNERS / "charset" / point_id(feed))


def nfmin290_worst(rows: list) -> float:
    return max(ms.nf_reref(r["nfmin_t_db"], ms.T_ANALYSIS) for r in rows)


# ---------------------------------------------------------------------------
# Input-network synthesis at an arbitrary input Q (pure)
# ---------------------------------------------------------------------------
def classify_synth_error(exc: Exception) -> str:
    """A synthesis ValueError is a SEARCH failure (the grid found no admissible
    point; retrying is meaningful) unless it is a topology-infeasible start
    (no lossless L-section can begin from the noise-compromise target)."""
    return "infeasible" if "no lossless" in str(exc) else "search_failed"


def synth_input(rows: list, q_in):
    """The lp_noise input network re-synthesized at input-network Q = q_in from
    one characterization's own noise parameters (the retained convention:
    |S11(f_mid)| <= -12 dB, minimum predicted NF290). Status distinguishes a
    SEARCH failure from a TOPOLOGY-infeasible target. A solved network is
    still only a prediction row, never evidence."""
    mid = rows[ms.MID]
    try:
        sol = ms.solve_input_noise(INPUT_TOPOLOGY, mid["zin"], mid["noise"], q_in)
    except ValueError as ex:
        return {"status": classify_synth_error(ex), "reason": str(ex)}
    vin = sol["values"]
    zs_t = ms.input_zs(INPUT_TOPOLOGY, vin, q_in, ms.F_MID)
    return {"status": "solved", "values": list(vin), "closed_form": list(sol["closed_form"]),
            "zs_target": [zs_t.real, zs_t.imag],
            "input_r": ms.q_series_r(vin[0], q_in)}


def predict_band(rows: list, vin: list, q_in, ylc_f: list, cp: float, cs: float) -> list:
    """Predicted in-band NF290 / S11 / S22 at EVERY retained frequency (the
    unilateral solver chain of #186/#198; output network fixed at its retained
    Q = 10 loss). Predictions, not simulations."""
    out = []
    for i, f in enumerate(ms.band_freqs()):
        r = rows[i]
        zl = ms.input_zlook(INPUT_TOPOLOGY, vin, q_in, f, r["zin"])
        zo = ms.output_zlook(r["ydev"], ylc_f[i], cp, cs, f)
        out.append({"f": f, "s11_db": ms.db20(abs(ms.gamma(zl))),
                    "s22_db": ms.db20(abs(ms.gamma(zo))),
                    "nf290_db": ms.predicted_nf290(INPUT_TOPOLOGY, vin, q_in, f, r["noise"])})
    return out


def output_ylc(entry: dict) -> list:
    """The retained output network's Lc admittance across the band (fixed Q =
    10 loss, value from the retained entry)."""
    return [1 / ms.z_ind(entry["lc"], entry["r_lc"], f) for f in ms.band_freqs()]


def map_rows() -> list:
    """One row per (arm, input Q). The q = 10 row is REPLAYED against the
    retained #198 entry (values and predictions must reproduce within
    REPLAY_TOL_REL) so a code or data drift cannot silently move the map."""
    out = []
    for feed in ARMS:
        rows = retained_char(feed)["cases"]["q10"]
        ent = retained_entry(feed)
        ylc_f = output_ylc(ent)
        for tag, q_in in Q_IN_CASES:
            sol = synth_input(rows, q_in)
            row = {"arm": feed, "arm_role": ARMS[feed], "q_in_tag": tag, "q_in": q_in,
                   "le_nh": LE_STUDY_NH, "le_q": Q_LE_FIXED, "status": sol["status"]}
            if sol["status"] != "solved":
                row["reason"] = sol["reason"]
                out.append(row)
                continue
            pred = predict_band(rows, sol["values"], q_in, ylc_f,
                                ent["cp_out"], ent["cs_out"])
            row.update({"input_values": sol["values"], "input_r": sol["input_r"],
                        "zs_target": sol["zs_target"],
                        "pred_nf290_mid_db": pred[ms.MID]["nf290_db"],
                        "pred_nf290_worst_db": max(p["nf290_db"] for p in pred),
                        "pred_s11_mid_db": pred[ms.MID]["s11_db"],
                        "pred_s11_worst_db": max(p["s11_db"] for p in pred),
                        "pred_s22_mid_db": pred[ms.MID]["s22_db"],
                        "pred_nf290": pred,
                        "output_reused": {"lc": ent["lc"], "r_lc": ent["r_lc"],
                                          "cp_out": ent["cp_out"], "cs_out": ent["cs_out"]}})
            if q_in == Q_LE_FIXED:
                replay_check(row, ent)
                row["replay"] = "ok"
            out.append(row)
    return out


def replay_check(row: dict, ent: dict) -> None:
    """The retained Q = 10 replay: at the retained convention this study's
    synthesis and predictions must equal the retained #198 entry. Raises on
    drift -- the map would otherwise silently re-base its predictions."""
    for got, want, what in ((row["input_values"], ent["input_values"], "input_values"),):
        for a, b in zip(got, want):
            if abs(a / b - 1.0) > REPLAY_TOL_REL:
                raise ValueError(f"Q = 10 replay drifted ({what}): {a!r} vs retained {b!r}")
    rp = ent["predicted"][ms.MID]["nf290_db"]
    if abs(row["pred_nf290_mid_db"] / rp - 1.0) > REPLAY_TOL_REL:
        raise ValueError(f"Q = 10 replay drifted (predicted NF290 mid): "
                         f"{row['pred_nf290_mid_db']!r} vs retained {rp!r}")


def crossings(rows: list) -> dict:
    """Minimum TESTED input Q whose PREDICTED worst-in-band NF290 is at or
    below each threshold -- a statement inside this sampled topology/search,
    never a universal lower bound or a feasibility claim. 'not reached within
    tested range' when no tested Q crosses; the lossless bound is reported
    separately from the finite tested set."""
    out = {}
    solved = {r["q_in"]: r for r in rows if r.get("status") == "solved"}
    for name, thresh in (("nf290_worst_le_1p5", THRESH_ROW_DB), ("nf290_worst_le_1p2", THRESH_PLAN_DB)):
        crossed = [q for q in Q_IN_FINITE if q in solved and solved[q]["pred_nf290_worst_db"] <= thresh]
        lossless = solved.get(None)
        out[name] = {
            "threshold_db": thresh,
            "min_tested_q": crossed[0] if crossed else None,
            "tested_finite_qs": list(Q_IN_FINITE),
            "not_reached": not crossed,
            "lossless_crosses": bool(lossless and lossless["pred_nf290_worst_db"] <= thresh),
        }
    return out


def select_boundary(rows: list) -> list:
    """Declared boundary rule, resolved deterministically from the map:
    B1 the finite feed at the lossless input bound (always; the best this
    feed could ever do in this search), B2 the ideal choke at the lowest
    tested finite Q crossing the planning limit, else the row threshold,
    else the lossless point, B3 the ideal choke at the lossless bound
    (always, dropped when identical to B2)."""
    by_q = {r["q_in"]: r for r in rows if r["arm"] == "ideal_choke" and r.get("status") == "solved"}
    picks = [("cmim_lossless", "em5_cmim", None)]
    q = None
    for thresh in (THRESH_PLAN_DB, THRESH_ROW_DB):
        crossed = [x for x in Q_IN_FINITE if x in by_q and by_q[x]["pred_nf290_worst_db"] <= thresh]
        if crossed:
            q = crossed[0]
            break
    picks.append(("choke_" + (f"q{q:g}".replace(".", "p") if q is not None else "lossless"),
                  "ideal_choke", q))
    if q is not None:
        picks.append(("choke_lossless", "ideal_choke", None))
    seen, out = set(), []
    for tag, arm, qq in picks:
        key = (arm, qq)
        if key in seen:
            continue
        seen.add(key)
        out.append({"tag": tag, "arm": arm, "q_in": qq})
    return out


# ---------------------------------------------------------------------------
# Retained-data derivations for the probe control (pure)
# ---------------------------------------------------------------------------
def retained_yser_grid() -> tuple:
    """(freqs, Yser) of the retained #193 tuning deck for the tank geometry."""
    fr = fs.dec_freqs(fs.TUNE_PER_DEC, ms.F_STAB_LO, ms.F_STAB_HI)
    _, ty = ms.columns(TUNE_CORNERS / "tune_yser.dat", len(fr), fr)
    key = f"real(i(v{TANK_GEOM}m))"
    ki = f"imag(i(v{TANK_GEOM}m))"
    y = [complex(r, i) for r, i in zip(ty[key], ty[ki])]
    if not all(z.real > 0 for z in y):
        raise ValueError("retained Yser: non-passive sign convention")
    return fr, y


def retained_cmim_esr() -> float:
    _, cols = ms.columns(TUNE_CORNERS / "cmim_probe.dat", 1, [ms.F_MID])
    z = complex(cols[f"real(v(cp_{TANK_GEOM}))"][0], cols[f"imag(v(cp_{TANK_GEOM}))"][0])
    if not (z.real > 0 and z.imag < 0):
        raise ValueError("retained cmim probe: not a lossy capacitor")
    return z.real


def derived_ytank(freqs: list) -> list:
    """Ytank(f) of the UNMODIFIED retained tank from RETAINED measurements:
    the tuning grid (log-frequency interpolated) plus the tuning C with its
    measured (f_mid, treated constant) series ESR. The probe's control arm is
    checked against this."""
    fr, y = retained_yser_grid()
    c = retained_plan()["c_tune_f"][TANK_GEOM]
    esr = retained_cmim_esr()
    out = []
    for f in freqs:
        i = bisect.bisect_left(fr, f)
        if i == 0:
            i = 1
        lo, hi = fr[i - 1], fr[i]
        t = (math.log(f) - math.log(lo)) / (math.log(hi) - math.log(lo))
        yser = y[i - 1] + (y[i] - y[i - 1]) * t
        w = 2 * math.pi * f
        out.append(yser + 1 / (esr + 1 / (1j * w * c)))
    return out


# ---------------------------------------------------------------------------
# Deck checks (pure)
# ---------------------------------------------------------------------------
_RQBR_RE = re.compile(r"^Rqbr b1f b1 (\S+)$", re.M)


def normalize_deck_paths(text: str) -> str:
    """Absolute checkout / PDK paths are environment, not deck content: the
    retained decks carry the paths of the checkout they were generated in.
    Normalizing them lets a re-render compare equal across checkouts while any
    generator, template, DUT or analysis drift still fails the comparison."""
    text = re.sub(r"\S*/sim/models/sg13g2_inductor_em\.spice", "<EM_MODEL>", text)
    text = re.sub(r"\S*/charset/[A-Za-z0-9_.]+", "<CHARSET>", text)
    text = re.sub(r"\S*/sim/lna-matching-feasibility/corners/" + RETAINED_RID, "<CORNERS>", text)
    text = re.sub(r"\S*/sim/lna-matching-feasibility", "<EXP>", text)
    text = re.sub(r"\S*/cornerHBT\.lib", "<MODELS_LIB>", text)
    text = re.sub(r"\S*/cornerMOShv\.lib", "<MOS_LIB>", text)
    text = re.sub(r"\S*/cornerCAP\.lib", "<CAP_LIB>", text)
    text = re.sub(r"\S*/psp103_nqs\.osdi", "<OSDI>", text)
    text = re.sub(r"\S*/psp103\.osdi", "<OSDI>", text)
    text = re.sub(r"\S*/mosvar\.osdi", "<OSDI>", text)
    return text


def check_bracket_deck(text: str, r: float) -> None:
    """The bracket edit is EXACTLY one noisy, DC-transparent parallel resistor
    of value r across the tank, on top of the retained em5_cmim feed."""
    els = _RQBR_RE.findall(text)
    if len(els) != 1 or not math.isclose(float(els[0]), r, rel_tol=1e-9):
        raise ValueError(f"bracket deck must carry exactly one Rqbr b1f b1 {r:g} (got {els})")
    if re.search(r"^Rqbr .+noisy=0", text, re.M):
        raise ValueError("the bracket resistor must stay thermal-noisy (noisy=0 forbidden)")
    if "XCfeed b1f b1 cap_cmim" not in text:
        raise ValueError("bracket deck lost the retained cmim tank capacitor")
    if ".include" not in text or "sg13g2_inductor_em.spice" not in text:
        raise ValueError("bracket deck lost the retained EM model include")
    if re.search(r"alter\s+\S*rqbr", text, re.I):
        raise ValueError("bracket deck alters Rqbr")
    fs.assert_feed_dc_path(text)
    ls.check_le_deck(text, LE_STUDY_NH, "char")


def check_ctl_char_deck(text: str, feed: str) -> None:
    """The control char deck must be the RETAINED deck byte for byte (checked
    by the caller); this check pins the structure independently."""
    ls.check_le_deck(text, LE_STUDY_NH, "char")
    fs.assert_feed_dc_path(text)


def q_case_note_line() -> str:
    return f"* Q case: {ms.QCASES[SOURCE_Q_CASE]['desc']}"


def boundary_note(q_in) -> str:
    qq = "infinity (lossless bound)" if q_in is None else f"Q = {q_in:g}"
    return ("* INPUT-Q REQUIREMENT BOUNDARY (issue #200): the INPUT network is\n"
            f"* synthesized at input-network {qq} from the RETAINED #198\n"
            "* characterization (prediction-boundary verification). The Le / Lc loss\n"
            "* convention above is the retained Q = 10 one, reused unchanged. This is a\n"
            "* HYPOTHETICAL REQUIREMENT-PROXY network, not an extracted geometry.")


def check_bound_deck(text: str, q_in, vals: list, feed: str) -> None:
    """Boundary verify deck: input network exactly at (vals, q_in), Le and Lc
    at the retained Q = 10 convention, no bracket resistor, the arm's feed."""
    ls.check_le_deck(text, LE_STUDY_NH, "verify", Q_LE_FIXED, "parallel")
    if _RQBR_RE.search(text):
        raise ValueError("boundary deck must not carry a bracket resistor")
    l_in = vals[0] if INPUT_TOPOLOGY == "lowpass" else vals[1]
    rp = re.findall(r"^Rlb lb_x xin (\S+)$", text, re.M)
    if q_in is None:
        if rp or "Rlb" in text:
            raise ValueError("lossless boundary deck carries an input loss resistor")
    else:
        want = ms.q_series_r(l_in, q_in)
        if len(rp) != 1 or not math.isclose(float(rp[0]), want, rel_tol=1e-5):
            raise ValueError(f"input loss should be one Rlb = {want:.6g} Ohm (got {rp})")
    want_note = q_case_note_line()
    if want_note in text or "* Q case:" in text:
        raise ValueError("boundary deck kept the unqualified retained Q-case note")
    if boundary_note(q_in).splitlines()[1] not in text:
        raise ValueError("boundary deck lacks the issue-#200 boundary note")
    if f"Rxoutdc xout vss {XOUT_RDC:g} noisy=0" not in text:
        raise ValueError("boundary deck lacks the #190 DC reference")
    if feed == "em5_cmim":
        if "XCfeed b1f b1 cap_cmim" not in text:
            raise ValueError("boundary deck lost the finite-feed tank")
    elif feed == "ideal_choke":
        if f"Lfeed b1f b1 {ms.FEED_CHOKE:g}" not in text:
            raise ValueError("boundary deck lost the ideal-choke feed")
    else:
        raise ValueError(f"unknown arm {feed!r}")
    fs.assert_feed_dc_path(text)


def probe_admittance(i_sense: complex, v_drive: float = None) -> complex:
    """Tank admittance from the sensing-source current: Ytank = i_sense / v_drive.
    The voltage drive pins the tank voltage regardless of any drive-side shunt;
    the division is explicit, not left to the unit amplitude."""
    v = PROBE_V_AC if v_drive is None else v_drive
    if not (math.isfinite(v) and v != 0):
        raise ValueError("probe drive voltage must be finite and nonzero")
    return i_sense / v


def parse_probe(path: Path) -> dict:
    """{arm_tag: [Ytank(f)]} from the probe deck's wrdata table."""
    freqs = ms.band_freqs()
    _, cols = ms.columns(path, ms.N_BAND, freqs)
    out = {}
    for tag in ("ctl",) + tuple(RPAR_TAG.values()):
        rk, ik = f"real(i(v{tag}m))", f"imag(i(v{tag}m))"
        # sensed current into the 0 V source (b1 side, same polarity as the
        # retained tune deck) divided by the drive voltage: Ytank = i / v
        y = [probe_admittance(complex(r, i)) for r, i in zip(cols[rk], cols[ik])]
        for z in y:
            if not math.isfinite(z.real) or not math.isfinite(z.imag):
                raise ValueError(f"probe arm {tag}: non-finite admittance")
        out[tag] = y
    log = path.parent / "probe_tank.log"
    if not re.search(r"^BENCH_COMPLETE", log.read_text(), re.M):
        raise ValueError("probe_tank.log: no BENCH_COMPLETE marker")
    return out


# ---------------------------------------------------------------------------
# Declaration (printed, committed before the run)
# ---------------------------------------------------------------------------
def planned_char_decks() -> int:
    return 2 + 1 + len(RPAR_OHM)          # char controls + probe + brackets


def planned_verify_decks() -> int:
    return 2 + 3                          # verify controls + at most 3 boundary points


def declaration_text() -> str:
    L = ["# Input-Q / feed-isolation requirements declaration (issue #200)", "",
         "Committed BEFORE any simulation of this study. Generated by",
         "`python3 -I sim/lna-matching-feasibility/q_study.py declare`; a unit test",
         "checks that this file equals that output, so it cannot drift from the code.", "",
         "**Declaration revision 2 (issue #202, continuing #200).** Revision 1 (commit",
         "`9abe609`) drove the tank probe with a 1 A AC current source at b1f. The EM",
         "model's b1f-side substrate shunt is in parallel with the tank, so the current",
         "source divided between tank and shunt and the sensed current was a divider",
         "output, not Ytank; run `20261011-120758-9abe609` stopped at the level-1 probe",
         "control (1.113 Ohm vs 797.9 Ohm) and is retained unchanged as stopped-run",
         "evidence. Revision 2 changes ONLY the probe drive/measurement (see the tank",
         "probe bench below). Every tolerance, the map, arms, bracket, policies and the",
         "deck budget are unchanged; the fresh run repeats ALL ordered control gates",
         "(previously matching characterizations do not waive them).", "",
         "**NOMINAL-CELL EXPLORATION.** One PVT cell (hbt_typ / mos_tt, 27 C, 1.80 V). No",
         "ratified-row, conformance or final-stability claim; `design/` and `spec/` are not",
         "modified. This study MAPS REQUIREMENTS; it does not select or adopt a physical",
         "feed or matching topology, and it authorizes no production or PVT work.", "",
         "## Question", "",
         "Record `20261011-101454-3ec590d` (#198) ended NO-GO: finite-feed verified NF290",
         "worst-in-band 2.570 dB, DUT NFmin@290 worst 1.545 dB, ideal-choke diagnostic",
         "1.763 dB at Le = 0.6 nH, with the decomposition separating feed floor from",
         "matching penalty. What input-network Q and what feed isolation would the 1.5 dB",
         "row and the 1.2 dB planning limit require? The unresized DUT is the control;",
         "the bias is never retuned; emitter sizing / cascode split stay with #58.", "",
         "## Map, arms and bracket", "",
         f"- Le is FIXED at {LE_STUDY_NH:g} nH (the #198 shortlist value) and its loss at Q =",
         f"  {Q_LE_FIXED:g} (parallel, the retained convention), for the main comparison. The",
         "  retained 1 nH controls of #198 (which reproduce #193) are replayed OFFLINE in",
         "  the unit tests against the retained record; this study spends no new decks on",
         "  them.",
         "- Arms (characterization reused from the RETAINED #198 record, never re-measured):",
         "  `em5_cmim` (the finite feed, tank + PDK cap_cmim) and `ideal_choke` (the",
         "  1 uH DIAGNOSTIC BOUND, unrealizable by construction).",
         "- Input-network Q, the only varied lever:",
         "  " + ", ".join(f"{q:g}" if q is not None else "lossless (ideal, the bound)"
                                   for _, q in Q_IN_CASES) + ".",
         "  The input network is RE-SYNTHESIZED per case from that arm's own retained",
         "  noise parameters (the `lp_noise` rule: lowest predicted NF290 subject to",
         f"  |S11(f_mid)| <= {ms.MISMATCH_TARGET_DB:g} dB). Emitter loss (Le Q = {Q_LE_FIXED:g}), the output",
         "  network (Lc 5 nH with its retained Q = 10 series loss + shunt C + series C,",
         "  reused unchanged from the retained entries), and the source temperature",
         "  convention (noise parameters at the 300.15 K analysis temperature, reported",
         "  at T0 = 290 K) are FIXED and identical across all cases.",
         "- Feed-loss bracket on the SAME resonant feed (`em5_cmim`): one parallel",
         "  resistor Rqbr across the tank (b1f to b1), in",
         "  {" + ", ".join(f"{r:g}" for r in RPAR_OHM) + "} Ohm ~ the retained tank",
         f"  impedance ({TANK_Z_RET_OHM:g} Ohm at f_mid, derived from the retained #193 Yser grid,",
         "  tuning C and measured cmim ESR; the #193 tuning table's 803 Ohm peak agrees)",
         "  divided by 2, 4, 8. The resistor is a plain ngspice resistor (THERMAL-NOISY;",
         "  `noisy=0` forbidden) and DC-transparent (it carries no bias current), so the",
         "  DC operating point, the substrate shunts, the DC resistance and the capacitor",
         "  parasitics stay exactly as the retained models have them. The EM model itself",
         "  is NOT edited; the unmodified retained tank is the control arm. Every bracket",
         "  point is a HYPOTHETICAL REQUIREMENT PROXY, never an extracted geometry.",
         "  Direction limit (a model limit, stated up front): a passive add-on can only",
         "  LOWER the isolation, so isolation above the retained model is sampled only by",
         "  the ideal-choke diagnostic bound; no interpolation between sampled points is",
         "  claimed.", "",
         "## Bench per deck class", "",
         "- Characterization (controls and brackets): the #186/#198 char deck",
         "  (`tb_match_char`, Le-loss cases ideal / Q = 10 / Q = 5, no Le sweep) with the",
         "  arm's feed, Le = 0.6 nH explicit, plus the print-only DC audit line (the #193",
         "  audit, char-deck hierarchy).",
         "- Tank probe: ONE one-port deck (`tb_qreq_tankprobe`), four arms (control +",
         f"  three bracket resistors): b1f is driven by a {PROBE_V_AC:g} V AC VOLTAGE source, b1 is held at",
         "  0 V by a 0 V sensing source (same current polarity as the retained tune deck),",
         "  and Ytank = i(sense) / v(drive) with the division explicit in the reducer. A",
         "  voltage drive pins the tank voltage, so the b1f-side substrate shunt (and any",
         "  drive-side shunt) cannot change the sensed admittance; an offline regression",
         "  checks this against a known admittance with a varying drive-side shunt, for",
         "  all four arms, with the bracket resistor a noisy plain ngspice resistor.",
         "  Ytank(f) over the 11 retained in-band frequencies;",
         "  isolation = |Ztank(f)| = 1/|Ytank(f)|, reported at f_mid and band-min.",
         "- Verification (controls and boundary points only): the #186/#198 verify deck",
         f"  (`tb_match_verify`) with Rxoutdc = {XOUT_RDC:g} Ohm on xout (#190) and the DC audit;",
         "  in-band S11/S22/S21/NF, broadband mu/k/Delta, NF290 on the 21-point grid.",
         "- PDK / models: as retained (`hbt_typ` / `mos_tt`, ngspice >= 46,",
         "  `sim/models/sg13g2_inductor_em.spice`, PDK `cap_cmim`), hashes recorded in the",
         "  run record.", "",
         "## Reused retained evidence (provenance)", "",
         f"- Characterization tables: `corners/{RETAINED_RID}/charset/",
         "  {em5_cmim_le0p60,ideal_choke_le0p60}/` (record #198).",
         f"- Match plan (input/output networks and Q = 10 predictions):",
         f"  `netlist-snapshots/{RETAINED_RID}/le_match_plan.json`.",
         f"- Feed plan and Yser grid: `netlist-snapshots/{TUNE_RID}/feed_plan.json`,",
         f"  `corners/{TUNE_RID}/tune_yser.dat`, `corners/{TUNE_RID}/cmim_probe.dat` (record #193).",
         f"- Retained deck hashes: char control decks sha256 `{sha256(RETAINED_SNAP / 'char_em5_cmim_le0p60.spice')}`",
         f"  and `{sha256(RETAINED_SNAP / 'char_ideal_choke_le0p60.spice')}`; the re-rendered control",
         "  decks must equal them byte for byte after normalizing absolute checkout / PDK paths",
         "  (checked at generation time; any generator, template or DUT drift fails).", "",
         "## Policy declared before running (bench policy, NOT ratified)", "",
         "1. Controls, level 1 (char + probe): the two re-run char control decks render",
         "   byte-identical to the retained decks; their tables must reproduce the",
         f"   retained characterization (S-parameters / impedances within {CONTROL_TOL_VAL_REL:g} relative,",
         f"   NFmin within {CONTROL_TOL_DB:g} dB, OP currents within {CONTROL_TOL_IC1_REL:g} relative), and the probe's",
         f"   control arm must reproduce the retained-derived |Ztank(f_mid)| within {CONTROL_TOL_Z_REL:g}"
         "   relative (the derivation treats the measured cmim ESR as frequency-constant).",
         "   STOPPING RULE: outside tolerance, the run stops before any bracket or",
         "   boundary deck; the discrepancy is investigated, never widened.",
         "2. Controls, level 2 (verify): the two control verification decks (networks",
         "   re-synthesized from the FRESH control characterization, exactly the #198",
         "   path) must reproduce the retained verified metrics: NF290 worst and mid,",
         f"   S11 / S22 worst, |S21| min within {CONTROL_TOL_DB:g} dB; broadband mu minimum within",
         f"   {CONTROL_TOL_MU:g}; IC1 within {CONTROL_TOL_IC1_REL:g} relative; synthesized Lb / Cp within",
         f"   {CONTROL_TOL_VAL_REL:g} relative. STOPPING RULE: as above.",
         "3. Q = 10 replay: the map's Q = 10 row must equal the retained entry's input",
         f"   values and band-centre prediction within {REPLAY_TOL_REL:g} relative; a drift aborts the",
         "   map (the predictions would be re-based on moved code, not retained evidence).",
         "4. Map semantics: every map cell is a PREDICTION of this sampled topology and",
         "   search, never a universal lower bound and never a feasibility claim. A cell",
         "   whose synthesis fails is classified `search_failed` (the grid found no",
         "   admissible point; retrying is meaningful) or `infeasible` (no lossless",
         "   L-section can start from the noise-compromise target); failed cells stay",
         "   visible with their reason and cannot enter any crossing or frontier.",
         "5. Threshold crossings: evaluated on the PREDICTED worst-in-band NF290 over",
         "   the 11 retained in-band frequencies, solved cells only; reported as the",
         "   minimum TESTED finite Q at or below 1.5 dB and 1.2 dB, or 'not reached",
         "   within tested range', with the lossless bound reported separately.",
         "6. Boundary verification (the only new verify decks): B1 the finite feed at",
         "   the lossless input bound (always); B2 the ideal choke at the lowest tested",
         "   finite Q whose predicted worst-in-band NF290 is at or below the 1.2 dB",
         "   planning limit, else below the 1.5 dB row, else at the lossless bound;",
         "   B3 the ideal choke at the lossless bound (always, dropped when identical",
         "   to B2). Boundary decks reuse the retained output network unchanged, fix",
         "   Le / Lc at the retained Q = 10 convention, and carry the #190 DC reference",
         "   and the #193 DC audit. Their verified numbers are compared with their own",
         "   predictions (residuals reported); a verified boundary point remains a",
         "   hypothetical requirement proxy, never a design.",
         "7. DC validity: the #193 flags (|dIC1| or |dIDD| > 1 % vs the study's own",
         "   `em5_cmim` control audit, VCE < 0.3 V, VBC > 0.4 V, non-positive IC),",
         "   convergence: no singular matrix, failed gmin/source stepping or",
         "   transient-op fallback in any log. Missing, non-finite, invalid or",
         "   non-convergent points remain visible in the tables and cannot enter the",
         "   verified frontier.",
         "8. Verdicts, kept separate:",
         "   (a) REQUIREMENTS (the product): per arm, the threshold-crossing summary",
         "   of policy 5, plus the isolation-bracket direction from the measured",
         "   NFmin@290 vs isolation curve (sampled crossings only, no interpolation);",
         "   every statement labelled a prediction or a sampled measurement.",
         "   (b) CAMPAIGN (go/no-go for a later full-PVT campaign): GO only if a",
         "   VERIFIED, DC-valid, convergent point built ONLY from unmodified retained",
         "   / PDK models at the retained finite-Q conventions (this study's",
         "   `em5_cmim` control) meets verified NF290 worst-in-band <= 1.5 - 0.3 dB,",
         "   DUT NFmin@290 worst <= the same limit, S11 / S22 < -10 dB, |S21| > 15 dB,",
         "   no resolved mu < 1, and no DC flags; otherwise NO-GO with the first",
         "   failing gate in the order " + " > ".join(fs.GATES) + ".",
         "   Predictions, diagnostic bounds, bracket proxies and boundary points",
         "   CANNOT produce a GO; even a diagnostic point meeting every nominal gate",
         "   is no production / PVT authorization.", "",
         "## Run budget", "",
         f"Single-process `ngspice -b` decks, strictly sequential, nominal cell only:",
         f"{planned_char_decks()} characterization-class decks (2 char controls + 1 tank probe +",
         f"{len(RPAR_OHM)} bracket chars) <= {BUDGET_CHAR}, and at most {2 + 3} verification decks (2 controls +",
         f"up to 3 boundary points) <= {BUDGET_VERIFY}: 11 decks planned, 16 hard cap. No corner",
         "grid, no Monte Carlo, no fleet submission and no local-grid fallback.", ""]
    return "\n".join(L) + "\n"


# ---------------------------------------------------------------------------
# CLI helpers shared with the runner
# ---------------------------------------------------------------------------
def _wr(path, text):
    Path(path).write_text(text)


def _ns(a, outdir: str):
    return SimpleNamespace(models_lib=a.models_lib, mos_lib=a.mos_lib, osdi_dir=a.osdi_dir,
                           outdir=outdir, deckdir=a.snapdir, relative_em=False,
                           nf_npts=getattr(a, "nf_npts", retained_nf_npts()))


def _feed_plan():
    return retained_plan()


def render_ctl_char(a, feed: str) -> str:
    """The char control deck, path-normalized-checked against the retained file."""
    p = {"id": point_id(feed), "feed": feed, "le_nh": LE_STUDY_NH}
    sub = str(Path(a.outdir) / "charset" / p["id"])
    text = ms.char_deck(_ns(a, sub), le_nh=LE_STUDY_NH, char_cases=CHAR_CASES_LE, le_sweep=False)
    text = fs.apply_feed(text, feed, _feed_plan(), a.cap_lib)
    fs.assert_feed_dc_path(text)
    check_ctl_char_deck(text, feed)
    want = (RETAINED_SNAP / f"char_{p['id']}.spice").read_text()
    if normalize_deck_paths(text) != normalize_deck_paths(want):
        raise ValueError(f"control char deck for {feed} is not identical (modulo checkout paths) to "
                         f"the retained {RETAINED_RID} deck (generator, template or DUT drifted)")
    return text


def render_bracket_char(a, r: float) -> str:
    p = {"id": f"bracket_{rpar_tag(r)}", "feed": "em5_cmim", "le_nh": LE_STUDY_NH}
    sub = str(Path(a.outdir) / "charset" / p["id"])
    text = ms.char_deck(_ns(a, sub), le_nh=LE_STUDY_NH, char_cases=CHAR_CASES_LE, le_sweep=False)
    text = fs.apply_feed(text, "em5_cmim", _feed_plan(), a.cap_lib)
    cap_line = next(ln for ln in text.splitlines() if ln.startswith("XCfeed b1f b1 cap_cmim"))
    text = text.replace(cap_line, cap_line + f"\nRqbr b1f b1 {r:g}")
    fs.assert_feed_dc_path(text)
    check_bracket_deck(text, r)
    return text


PROBE_ARMS = ("ctl",) + tuple(RPAR_TAG.values())
# Tank probe drive (declaration revision 2, issue #202): an AC VOLTAGE source of
# this amplitude at b1f, b1 held at 0 V by the sensing source. The sensed
# current is divided by this amplitude explicitly: Ytank = i_sense / v_drive.
PROBE_V_AC = 1.0


def render_probe(a) -> str:
    plan = _feed_plan()
    s = plan["cmim_side_um"][TANK_GEOM]
    tag_r = {t: r for r, t in RPAR_TAG.items()}
    ports, vecs = [], []
    for tag in PROBE_ARMS:
        # source named V<tag>m so the wrdata vectors are real/imag(i(v<tag>m)),
        # the feed_study tune-deck convention
        r = (f"\nRqbr_{tag} b1f_{tag} b1_{tag} {tag_r[tag]:g}"
             if tag in tag_r else "")
        ports.append(
            f"* probe arm `{tag}`" + ("" if tag == "ctl" else " (HYPOTHETICAL REQUIREMENT PROXY)")
            + f"\nXtank_{tag} b1f_{tag} b1_{tag} 0 {ms.em_instance(TANK_GEOM)}\n"
            f"Xcfeed_{tag} b1f_{tag} b1_{tag} cap_cmim w={s:.6g}u l={s:.6g}u" + r +
            f"\nV_{tag} b1f_{tag} 0 dc 0 ac {PROBE_V_AC:g}\nV{tag}m b1_{tag} 0 dc 0 ac 0")
        vecs += [f"real(i(v{tag}m))", f"imag(i(v{tag}m))"]
    return ms.render(HERE / "testbench" / "tb_qreq_tankprobe.spice.tmpl", {
        "EM_MODEL": ms.EM_MODEL, "CAP_LIB": a.cap_lib, "ONEPORTS": "\n\n".join(ports),
        "VECS": " ".join(vecs), "CTL_TAG": "ctl",
        "N_BAND": ms.N_BAND, "F_LO": f"{ms.F_LO:g}", "F_HI": f"{ms.F_HI:g}",
        "OUTDIR": a.outdir})


CHAR_OP_ANCHOR = 'echo "OP ic1 $&ic1 ic2 $&ic2 idd $&idd"\n'
CHAR_DC_AUDIT = (
    "* DC audit (issue #200): node voltages of the characterized DUT Xa\n"
    "let ib1 = @q.xa.xq1.qnpn13g2[ib]\n"
    "let vb1 = v(xa.b1)\n"
    "let ve1 = v(xa.e1)\n"
    "let vcasc = v(xa.casc)\n"
    "let voutn = v(xa.outn)\n"
    "let vb2 = v(xa.vb2)\n"
    "let vbref = v(xa.bref)\n"
    "let pdc = 1.8 * (-i(vdda))\n"
    'echo "DC ic1 $&ic1 ic2 $&ic2 ib1 $&ib1 vb1 $&vb1 ve1 $&ve1 vcasc $&vcasc voutn $&voutn '
    'vb2 $&vb2 vbref $&vbref idd $&idd pdc $&pdc"\n')


def add_char_dc_audit(text: str) -> str:
    """Add the char-hierarchy DC audit after the char deck's OP echo line
    (print-only: no element or analysis changes; refusing a second audit)."""
    if text.count(CHAR_OP_ANCHOR) != 1:
        raise ValueError("char deck lacks a unique OP echo line")
    if CHAR_DC_AUDIT.splitlines()[0] in text:
        raise ValueError("char deck already carries the DC audit")
    return text.replace(CHAR_OP_ANCHOR, CHAR_OP_ANCHOR + CHAR_DC_AUDIT)


def entry_for(feed: str, q_in, stem: str) -> dict:
    """A boundary verify-deck entry: input network re-synthesized at input
    Q = q_in from the RETAINED characterization (the same data the map's
    prediction used), output network and Le / Lc loss conventions reused
    unchanged from the retained entry, #190 DC reference, #198 Le plumbing."""
    data = retained_char(feed)
    crows = data["cases"]["q10"]
    ent = retained_entry(feed)
    sol = synth_input(crows, q_in)
    if sol["status"] != "solved":
        raise ValueError(f"boundary point {feed} Q={q_in}: {sol['status']} ({sol.get('reason')})")
    e = {"candidate": MATCH_CANDIDATE, "qcase": SOURCE_Q_CASE, "q": Q_LE_FIXED,
         "input_topology": INPUT_TOPOLOGY, "target": "noise",
         "input_values": sol["values"], "input_r": sol["input_r"],
         "input_l": sol["values"][0] if INPUT_TOPOLOGY == "lowpass" else sol["values"][1],
         "zs_target": sol["zs_target"],
         "output": "O2", "lc": ent["lc"], "r_lc": ent["r_lc"],
         "cp_out": ent["cp_out"], "cs_out": ent["cs_out"], "lc_em": None,
         "le_nh": LE_STUDY_NH, "le_q": Q_LE_FIXED, "le_loss": "parallel",
         "feed_variant": feed, "point": point_id(feed), "xout_rdc_ohm": XOUT_RDC,
         "stem": stem, "q_in": q_in, "q_in_tag": next(t for t, x in Q_IN_CASES if x == q_in)}
    e["char"] = ls.char_summary(data)
    e["char_op"] = data["op"]
    return e


def render_verify(a, e: dict) -> str:
    """Verification deck for a control or boundary entry, with the boundary
    note replacing the retained Q-case line when the input Q is a study input."""
    plan = _feed_plan()
    text = fs.apply_feed(ms.verify_deck(_ns(a, a.outdir), e, e["stem"]), e["feed_variant"],
                         plan, a.cap_lib)
    fs.assert_feed_dc_path(text)
    if e.get("q_in", Q_LE_FIXED) == Q_LE_FIXED and e.get("boundary") is None:
        ls.check_le_deck(text, LE_STUDY_NH, "verify", e.get("le_q", Q_LE_FIXED), e.get("le_loss", "parallel"))
        return ls.add_dc_audit(text)
    stale = q_case_note_line()
    if text.count(stale) != 1:
        raise ValueError("boundary deck lacks a unique retained Q-case note line")
    text = text.replace(stale, boundary_note(e["q_in"]))
    check_bound_deck(text, e["q_in"], e["input_values"], e["feed_variant"])
    return ls.add_dc_audit(text)


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------
def cmd_declare(_a):
    sys.stdout.write(declaration_text())
    return 0


def cmd_control_gen(a):
    snap = Path(a.snapdir)
    snap.mkdir(parents=True, exist_ok=True)
    (Path(a.outdir) / "charset" / point_id("em5_cmim")).mkdir(parents=True, exist_ok=True)
    (Path(a.outdir) / "charset" / point_id("ideal_choke")).mkdir(parents=True, exist_ok=True)
    (Path(a.outdir) / "charset" / "bracket_r400").mkdir(parents=True, exist_ok=True)
    (Path(a.outdir) / "charset" / "bracket_r200").mkdir(parents=True, exist_ok=True)
    (Path(a.outdir) / "charset" / "bracket_r100").mkdir(parents=True, exist_ok=True)
    for feed in ARMS:
        _wr(snap / f"char_ctl_{point_id(feed)}.spice", render_ctl_char(a, feed))
    for r in RPAR_OHM:
        _wr(snap / f"char_bracket_{rpar_tag(r)}.spice", render_bracket_char(a, r))
    _wr(snap / "probe_tank.spice", render_probe(a))
    doc = {"generator": "sim/lna-matching-feasibility/q_study.py control-gen",
           "declaration_sha256": sha256(HERE / "q-study-declaration.md"),
           "design_netlist_sha256": ms.sha256(ms.DESIGN_NETLIST),
           "em_model_sha256": ms.sha256(ms.EM_MODEL),
           "retained_record": RETAINED_RID, "tune_record": TUNE_RID,
           "retained_le_plan_sha256": sha256(RETAINED_SNAP / "le_plan.json"),
           "retained_le_match_plan_sha256": sha256(RETAINED_SNAP / "le_match_plan.json"),
           "retained_feed_plan_sha256": sha256(TUNE_SNAP / "feed_plan.json"),
           "le_study_nh": LE_STUDY_NH, "q_in_cases": {t: q for t, q in Q_IN_CASES},
           "rpar_ohm": list(RPAR_OHM), "tank_z_ret_ohm_declared": TANK_Z_RET_OHM}
    _wr(snap / "qreq_plan.json", json.dumps(doc, indent=2) + "\n")
    print(f"control-gen: {2} control + {len(RPAR_OHM)} bracket char decks, probe deck, qreq_plan.json")
    return 0


def cmd_stems(a):
    snap = Path(a.snapdir)
    g = a.group
    if g == "ctlchar":
        stems = [f"char_ctl_{point_id(f)}" for f in ARMS]
    elif g == "probe":
        stems = ["probe_tank"]
    elif g == "bracket":
        stems = [f"char_bracket_{rpar_tag(r)}" for r in RPAR_OHM]
    elif g == "ctlverify":
        f = snap / "qreq_ctl_verify.json"
        stems = [e["stem"] for e in json.loads(f.read_text())["candidates"]] if f.exists() else []
    elif g == "boundary":
        f = snap / "qreq_map.json"
        stems = [b["stem"] for b in json.loads(f.read_text())["boundary"]] if f.exists() else []
    else:
        raise SystemExit(f"unknown stems group {g!r}")
    print("\n".join(stems))
    return 0


def char_compare(fresh_dir: Path, ret_dir: Path) -> list:
    """[(quantity, fresh, retained, diff, tol, ok)] between two characterization
    directories of the SAME deck."""
    a, b = load_char_dir(fresh_dir), load_char_dir(ret_dir)
    rows = []
    for case in CHAR_CASES_LE:
        for i in range(ms.N_BAND):
            ra, rb = a["cases"][case][i], b["cases"][case][i]
            for name, x, y, tol, rel in (
                    ("nfmin_t_db", ra["nfmin_t_db"], rb["nfmin_t_db"], CONTROL_TOL_DB, False),
                    ("rn", ra["noise"]["rn"], rb["noise"]["rn"], CONTROL_TOL_VAL_REL, True)):
                d = abs(x - y) if not rel else abs(x / y - 1.0)
                rows.append((f"{case}[{i}].{name}", x, y, d, tol, d <= tol))
            for name, z1, z2 in (("s11", ra["s11"], rb["s11"]), ("s21", ra["s21"], rb["s21"]),
                                 ("s12", ra["s12"], rb["s12"]), ("s22", ra["s22"], rb["s22"]),
                                 ("gopt", ra["noise"]["gopt"], rb["noise"]["gopt"])):
                d = abs(z1 - z2)
                rows.append((f"{case}[{i}].{name}", abs(z1), abs(z2), d, CONTROL_TOL_VAL_REL,
                             d <= CONTROL_TOL_VAL_REL))
            for name, z1, z2 in (("zin", ra["zin"], rb["zin"]), ("ydev", ra["ydev"], rb["ydev"])):
                d = abs(z1 / z2 - 1.0) if abs(z2) > 0 else math.inf
                rows.append((f"{case}[{i}].{name}", abs(z1), abs(z2), d, CONTROL_TOL_VAL_REL,
                             d <= CONTROL_TOL_VAL_REL))
    for k in ("ic1", "ic2", "idd"):
        x, y = a["op"][k], b["op"][k]
        d = abs(x / y - 1.0)
        rows.append((f"op.{k}", x, y, d, CONTROL_TOL_IC1_REL, d <= CONTROL_TOL_IC1_REL))
    return rows


def cmd_control_check(a):
    rows, problems = [], []
    for feed in ARMS:
        pid = point_id(feed)
        rows += [(feed,) + r for r in char_compare(Path(a.corners) / "charset" / pid,
                                                   RETAINED_CORNERS / "charset" / pid)]
    ymeas = parse_probe(Path(a.corners) / "tank_y.dat")["ctl"]
    yder = derived_ytank(ms.band_freqs())
    im = ms.MID
    d = abs(abs(1 / ymeas[im]) / abs(1 / yder[im]) - 1.0)
    rows.append(("probe", "|Ztank|_mid", abs(1 / ymeas[im]), abs(1 / yder[im]), d,
                 CONTROL_TOL_Z_REL, d <= CONTROL_TOL_Z_REL))
    bad = [r for r in rows if not r[-1]]
    for r in bad:
        print(f"control-check: {r[0]} {r[1]} {r[2]:.10g} vs retained {r[3]:.10g} "
              f"(|d| {r[4]:.3e} > {r[5]:g})", file=sys.stderr)
    _write_csv(a.csv, ["control", "quantity", "this_study", "retained", "abs_diff", "tolerance",
                       "within"], rows)
    print(f"control-check: {len(rows)} comparisons, {len(bad)} outside tolerance")
    return 1 if bad else 0


def _write_csv(path, header, rows):
    with open(path, "w", newline="") as fh:
        w = csv.writer(fh, lineterminator="\n")
        w.writerow(header)
        for r in rows:
            w.writerow([r[0], r[1]] + [f"{x:.10g}" if isinstance(x, float) else x for x in r[2:-1]]
                       + ["yes" if r[-1] else "NO"])


def ctl_verify_entries(a) -> list:
    """Control verification entries, synthesized from the FRESH control
    characterization (the #198 path), with the feed and Le plumbing applied."""
    out = []
    for feed in ARMS:
        pid = point_id(feed)
        cdir = Path(a.corners) / "charset" / pid
        data = load_char_dir(cdir)
        cs = ls.char_summary(data)
        entries, _ = ms.synthesize(data, le_nh=LE_STUDY_NH,
                                   candidates={MATCH_CANDIDATE: ms.CANDIDATES[MATCH_CANDIDATE]},
                                   qcases={SOURCE_Q_CASE: ms.QCASES[SOURCE_Q_CASE]},
                                   char_cases=CHAR_CASES_LE)
        e = dict(entries[0])
        if e.get("infeasible"):
            raise ValueError(f"control {feed}: {MATCH_CANDIDATE}:{SOURCE_Q_CASE} infeasible "
                             f"({e['infeasible']})")
        e.update({"le_nh": LE_STUDY_NH, "feed_variant": feed, "point": pid,
                  "xout_rdc_ohm": XOUT_RDC, "stem": f"verify_ctl_{pid}",
                  "char": cs, "char_op": data["op"], "control": True, "role": "control",
                  "q_in": Q_LE_FIXED})
        out.append(e)
    return out


def cmd_ctl_verify_gen(a):
    entries = ctl_verify_entries(a)
    plan = _feed_plan()
    for e in entries:
        _wr(Path(a.snapdir) / f"{e['stem']}.spice", render_verify(a, e))
    _wr(Path(a.snapdir) / "qreq_ctl_verify.json", json.dumps(
        {"generator": "sim/lna-matching-feasibility/q_study.py ctl-verify-gen",
         "nf_npts": a.nf_npts, "xout_rdc_ohm": XOUT_RDC, "candidates": entries},
        indent=2, default=str) + "\n")
    print(f"ctl-verify-gen: {len(entries)} control verification decks")
    return 0


def _reduced(a, stem) -> dict:
    log = Path(a.corners) / f"{stem}.log"
    m = ms.reduce_one(Path(a.corners), stem, a.nf_npts)["metrics"]
    m["convergence"] = ms.classify_convergence(log)
    return m


def cmd_ctl_verify_check(a):
    doc = json.loads((Path(a.snapdir) / "qreq_ctl_verify.json").read_text())
    a.nf_npts = ms.check_nf_npts(doc["nf_npts"])    # the subcommand has no --nf-npts flag
    rows, missing = [], []
    for e in doc["candidates"]:
        feed = e["feed_variant"]
        stem = f"verify_{e['point']}"
        try:
            prior = ms.reduce_one(RETAINED_CORNERS, stem, doc["nf_npts"])["metrics"]
        except (OSError, ValueError) as ex:
            missing.append(f"{stem}: {ex}")
            continue
        new = _reduced(a, e["stem"])
        for k in ("nf290_db_worst", "nf290_db_mid", "s11_db_worst", "s22_db_worst", "s21_db_min"):
            d = abs(new[k] - prior[k])
            rows.append((feed, k, new[k], prior[k], d, CONTROL_TOL_DB, d <= CONTROL_TOL_DB))
        d = abs(new["mu_bb_min"] - prior["mu_bb_min"])
        rows.append((feed, "mu_bb_min", new["mu_bb_min"], prior["mu_bb_min"], d,
                     CONTROL_TOL_MU, d <= CONTROL_TOL_MU))
        d = abs(new["ic1"] / prior["ic1"] - 1.0)
        rows.append((feed, "ic1_rel", new["ic1"], prior["ic1"], d, CONTROL_TOL_IC1_REL,
                     d <= CONTROL_TOL_IC1_REL))
        rent = retained_entry(feed)
        for name, x, y in (("input_series", e["input_values"][0], rent["input_values"][0]),
                           ("input_shunt", e["input_values"][1], rent["input_values"][1])):
            d = abs(x / y - 1.0)
            rows.append((feed, name + "_rel", x, y, d, CONTROL_TOL_VAL_REL, d <= CONTROL_TOL_VAL_REL))
    bad = [r for r in rows if not r[-1]]
    for r in bad:
        print(f"ctl-verify-check: {r[0]} {r[1]} {r[2]:.10g} vs retained {r[3]:.10g} "
              f"(|d| {r[4]:.3e} > {r[5]:g})", file=sys.stderr)
    for m in missing:
        print(f"ctl-verify-check: retained reference unavailable: {m}", file=sys.stderr)
    _write_csv(a.csv, ["control", "quantity", "this_study", "retained", "abs_diff", "tolerance",
                       "within"], rows)
    print(f"ctl-verify-check: {len(rows)} comparisons, {len(bad)} outside tolerance, "
          f"{len(missing)} missing")
    return 1 if bad or missing else 0


def cmd_qmap(a):
    rows = map_rows()
    summary = {}
    for feed in ARMS:
        arm_rows = [r for r in rows if r["arm"] == feed]
        summary[feed] = {"arm_role": ARMS[feed], "le_nh": LE_STUDY_NH,
                         "crossings": crossings(arm_rows)}
    boundary = select_boundary(rows)
    entries = []
    for b in boundary:
        tag = b["tag"]
        stem = f"verify_bound_{tag}"
        try:
            e = entry_for(b["arm"], b["q_in"], stem)
        except ValueError as ex:
            entries.append({"tag": tag, "arm": b["arm"], "q_in": b["q_in"], "stem": stem,
                            "status": "not_renderable", "reason": str(ex), "boundary": True})
            continue
        arm_row = next(r for r in rows if r["arm"] == b["arm"] and r["q_in"] == b["q_in"]
                       and r["status"] == "solved")
        e["boundary"] = True
        e["boundary_tag"] = tag
        e["pred_nf290_worst_db"] = arm_row["pred_nf290_worst_db"]
        e["pred_nf290_mid_db"] = arm_row["pred_nf290_mid_db"]
        _wr(Path(a.snapdir) / f"{stem}.spice", render_verify(a, e))
        entries.append({k: v for k, v in e.items() if k not in ("char", "char_op", "predicted")})
    out = {"generator": "sim/lna-matching-feasibility/q_study.py qmap",
           "retained_record": RETAINED_RID, "le_study_nh": LE_STUDY_NH,
           "q_in_cases": {t: q for t, q in Q_IN_CASES},
           "summary": summary, "boundary": entries,
           "rows": [{k: v for k, v in r.items() if k != "pred_nf290"} for r in rows]}
    _wr(Path(a.snapdir) / "qreq_map.json", json.dumps(out, indent=2, default=str) + "\n")
    nsolved = sum(1 for r in rows if r["status"] == "solved")
    print(f"qmap: {nsolved}/{len(rows)} cells solved; {len(entries)} boundary deck(s): "
          + ", ".join(e["stem"] for e in entries))
    return 0


# ---------------------------------------------------------------------------
# Reduction
# ---------------------------------------------------------------------------
ISO_COLS = ["arm", "role", "rpar_ohm", "status", "reason", "z_tank_mid_ohm", "z_tank_bandmin_ohm",
            "nfmin290_ideal_mid_db", "nfmin290_ideal_worst_db", "nfmin290_q10_mid_db",
            "nfmin290_q10_worst_db", "nf290_sp50_q10_mid_db", "ic1_ma", "dic1_vs_ctl_pct",
            "vbe1_v", "ve1_mv", "pdc_mw", "dc_flags", "char_convergence"]


def _g(x, nd=6):
    return "" if x is None else f"{x:.{nd}g}"


def cmd_reduce(a):
    problems = []
    snap, corners = Path(a.snapdir), Path(a.corners)
    mapdoc = json.loads((snap / "qreq_map.json").read_text())
    probe = parse_probe(corners / "tank_y.dat")
    derived = derived_ytank(ms.band_freqs())

    ctl_audit = fs.parse_dc_audit(corners / "charset" / point_id("em5_cmim") / "char.log")
    ctl_data = load_char_dir(corners / "charset" / point_id("em5_cmim"))
    iso_rows, iso_tables = [], {}
    for feed in ARMS:
        pid = point_id(feed)
        data = load_char_dir(corners / "charset" / pid)
        audit = fs.parse_dc_audit(corners / "charset" / pid / "char.log")
        flags = fs.dc_flags(audit, ctl_audit)
        conv = ms.classify_convergence(corners / "charset" / pid / "char.log")
        cs = ls.char_summary(data)
        y = probe["ctl"]
        iso_rows.append({"arm": feed, "role": ARMS[feed], "rpar_ohm": None, "status": "verified",
                         "z_tank_mid_ohm": abs(1 / y[ms.MID]),
                         "z_tank_bandmin_ohm": min(abs(1 / x) for x in y),
                         "cs": cs, "audit": audit, "dc_flags": flags, "conv": conv,
                         "dic1": audit["ic1"] / ctl_audit["ic1"] - 1.0,
                         "control": True})
    for r in RPAR_OHM:
        tag = rpar_tag(r)
        cdir = corners / "charset" / f"bracket_{tag}"
        try:
            data = load_char_dir(cdir)
            cs = ls.char_summary(data)
            audit = fs.parse_dc_audit(cdir / "char.log")
            conv = ms.classify_convergence(cdir / "char.log")
            flags = fs.dc_flags(audit, ctl_audit)
            y = probe[tag]
            iso_rows.append({"arm": f"bracket_{tag}", "role": "hypothetical requirement proxy",
                             "rpar_ohm": r, "status": "verified",
                             "z_tank_mid_ohm": abs(1 / y[ms.MID]),
                             "z_tank_bandmin_ohm": min(abs(1 / x) for x in y),
                             "cs": cs, "audit": audit, "dc_flags": flags, "conv": conv,
                             "dic1": audit["ic1"] / ctl_audit["ic1"] - 1.0,
                             "control": False})
        except (OSError, ValueError) as ex:
            iso_rows.append({"arm": f"bracket_{tag}", "role": "hypothetical requirement proxy",
                             "rpar_ohm": r, "status": "invalid", "reason": str(ex),
                             "control": False})
            problems.append(f"bracket_{tag}: unusable ({ex})")
    # ideal-choke anchor from the RETAINED record (diagnostic, no new deck)
    ck = ls.char_summary(retained_char("ideal_choke"))
    iso_rows.append({"arm": "ideal_choke", "role": "diagnostic bound (retained #198, no new deck)",
                     "rpar_ohm": None, "status": "retained", "cs": ck, "control": False,
                     "z_tank_mid_ohm": None, "z_tank_bandmin_ohm": None})

    with open(a.isolation_csv, "w", newline="") as fh:
        w = csv.writer(fh, lineterminator="\n")
        w.writerow(ISO_COLS)
        for r in iso_rows:
            cs = r.get("cs", {})
            w.writerow([r["arm"], r["role"], _g(r.get("rpar_ohm")), r["status"], r.get("reason", ""),
                        _g(r.get("z_tank_mid_ohm")), _g(r.get("z_tank_bandmin_ohm")),
                        _g(cs.get("ideal", {}).get("nfmin290_mid_db")),
                        _g(cs.get("ideal", {}).get("nfmin290_worst_db")),
                        _g(cs.get("q10", {}).get("nfmin290_mid_db")),
                        _g(cs.get("q10", {}).get("nfmin290_worst_db")),
                        _g(cs.get("q10", {}).get("nf50_290_sp_mid_db")),
                        _g(r["audit"]["ic1"] * 1e3) if "audit" in r else "",
                        _g(r["dic1"] * 100) if "dic1" in r else "",
                        _g(r["audit"]["vbe1"]) if "audit" in r else "",
                        _g(r["audit"]["ve1"] * 1e3) if "audit" in r else "",
                        _g(r["audit"]["pdc"] * 1e3) if "audit" in r else "",
                        ";".join(r.get("dc_flags", [])) or "none",
                        "normal" if r.get("conv", {}).get("normal", True) else "FLAGGED"])

    # boundary verification vs prediction
    bnd = []
    for b in mapdoc["boundary"]:
        stem = b["stem"]
        try:
            m = _reduced(a, stem)
        except (OSError, ValueError) as ex:
            problems.append(f"{stem}: unusable ({ex})")
            bnd.append({"tag": b["boundary_tag"], "arm": b["feed_variant"], "q_in": b["q_in"],
                        "status": "invalid", "reason": str(ex)})
            continue
        band = ms.reduce_one(corners, stem, a.nf_npts)["band"]
        v11 = max(ms.nf_reref(x["nf_sp_db"], ms.T_ANALYSIS) for x in band)
        bnd.append({"tag": b["boundary_tag"], "arm": b["feed_variant"], "q_in": b["q_in"],
                    "status": "verified", "pred_nf290_worst_db": b["pred_nf290_worst_db"],
                    "pred_nf290_mid_db": b["pred_nf290_mid_db"],
                    "verified_nf290_worst_db": m["nf290_db_worst"],
                    "verified_nf290_mid_db": m["nf290_db_mid"],
                    "verified_nf290_worst_11f_db": v11,
                    "residual_worst_11f_db": v11 - b["pred_nf290_worst_db"],
                    "s11_db_worst": m["s11_db_worst"], "s22_db_worst": m["s22_db_worst"],
                    "s21_db_min": m["s21_db_min"], "mu_bb_min": m["mu_bb_min"],
                    "convergence": m["convergence"]})
        if not m["convergence"]["normal"]:
            problems.append(f"{stem}: operating-point convergence fallback/warning")
        if abs(m["gt_minus_s21_db_mid"]) > 1e-3:
            problems.append(f"{stem}: transducer-gain cross-check off by "
                            f"{m['gt_minus_s21_db_mid']:.4g} dB")

    # campaign verdict: ONLY the unmodified-model em5_cmim control is a
    # physical candidate; everything else in this study is predictive,
    # diagnostic or a hypothetical proxy.
    phys = next(r for r in iso_rows if r["arm"] == "em5_cmim")
    ctlv = next(e for e in json.loads((snap / "qreq_ctl_verify.json").read_text())["candidates"]
                if e["feed_variant"] == "em5_cmim")
    scan = {"dc_flags": phys["dc_flags"],
            "nfmin290_worst_db": phys["cs"]["q10"]["nfmin290_worst_db"],
            "convergence": {"normal": phys["conv"]["normal"]}}
    match = _reduced(a, ctlv["stem"])
    rec = fs.recommend(scan, match)
    rec["physical_candidate_pool"] = ["verify_ctl_" + point_id("em5_cmim")]
    rec["note"] = ("Only the unmodified-model em5_cmim control verification is a physical "
                   "candidate. Predictions, the ideal-choke diagnostic, bracket proxies and "
                   "boundary verifications cannot produce a GO; this study maps requirements.")

    req = {}
    for feed in ARMS:
        s = mapdoc["summary"][feed]
        req[feed] = {"arm_role": s["arm_role"], "crossings": s["crossings"]}
    zmid_ctl = next(r["z_tank_mid_ohm"] for r in iso_rows if r["arm"] == "em5_cmim")
    req["isolation"] = {
        "metric": "|Ztank(f_mid)| of the retained em5_cmim tank",
        "current_ohm_measured": zmid_ctl,
        "current_ohm_retained_derived": abs(1 / derived[ms.MID]),
        "nfmin290_worst_le_1p2": ("not reached at any sampled finite isolation (the "
                                  "unbracketed retained tank included); the only sampled point "
                                  "at or below the planning limit is the ideal-choke diagnostic "
                                  "bound"),
        "sampled_curve": [{"arm": r["arm"], "rpar_ohm": r.get("rpar_ohm"),
                           "z_tank_mid_ohm": r.get("z_tank_mid_ohm"),
                           "nfmin290_q10_worst_db": r.get("cs", {}).get("q10", {}).get("nfmin290_worst_db")}
                          for r in iso_rows],
        "note": "sampled crossings only; no interpolation between sampled isolations"}

    rj = {"generator": "sim/lna-matching-feasibility/q_study.py reduce",
          "campaign": rec, "requirements": req, "boundary": bnd,
          "probe_control": {"z_mid_measured": abs(1 / probe["ctl"][ms.MID]),
                            "z_mid_derived": abs(1 / derived[ms.MID])},
          "problems": problems}
    _wr(corners / "recommendation.json", json.dumps(rj, indent=2, default=str) + "\n")

    with open(a.map_csv, "w", newline="") as fh:
        w = csv.writer(fh, lineterminator="\n")
        w.writerow(["arm", "arm_role", "q_in_tag", "q_in", "status", "reason", "replay",
                    "input_lb_nh", "input_cp_pf", "pred_nf290_mid_db", "pred_nf290_worst_db",
                    "pred_s11_mid_db", "pred_s11_worst_db", "pred_s22_mid_db",
                    "crosses_1p5_worst", "crosses_1p2_worst"])
        for r in mapdoc["rows"]:
            solved = r["status"] == "solved"
            w.writerow([r["arm"], r["arm_role"], r["q_in_tag"],
                        "inf" if r["q_in"] is None else _g(r["q_in"]), r["status"],
                        r.get("reason", ""), r.get("replay", ""),
                        _g(r["input_values"][0] * 1e9) if solved else "",
                        _g(r["input_values"][1] * 1e12) if solved else "",
                        _g(r.get("pred_nf290_mid_db")), _g(r.get("pred_nf290_worst_db")),
                        _g(r.get("pred_s11_mid_db")), _g(r.get("pred_s11_worst_db")),
                        _g(r.get("pred_s22_mid_db")),
                        ("yes" if r.get("pred_nf290_worst_db") <= THRESH_ROW_DB else "no") if solved else "",
                        ("yes" if r.get("pred_nf290_worst_db") <= THRESH_PLAN_DB else "no") if solved else ""])
    _wr(a.markdown, markdown(mapdoc, iso_rows, bnd, req, rec, probe, derived, problems))
    print(f"reduce: campaign {rec['verdict']} (binding: {rec['binding']}); {len(problems)} problem(s)")
    return 1 if problems else 0


def _fz(z):
    return f"{z[0]:.1f}{z[1]:+.1f}j"


def markdown(mapdoc, iso_rows, bnd, req, rec, probe, derived, problems) -> str:
    L = ["#### Input-Q requirements map (PREDICTIONS; retained #198 characterization, "
         "Le = 0.6 nH, Le/Lc/output loss fixed at the retained Q = 10 convention)", "",
         "| Arm | Input Q | Lb / Cp | pred NF290 mid / worst (dB) | pred S11 mid / worst (dB) | "
         "crosses 1.5 / 1.2 (worst) |", "|---|---|---|---|---|---|"]
    for r in mapdoc["rows"]:
        q = "lossless" if r["q_in"] is None else f"{r['q_in']:g}"
        if r["status"] != "solved":
            L.append(f"| `{r['arm']}` | {q} | {r['status']}: {r['reason']} | | | |")
            continue
        cr15 = "yes" if r["pred_nf290_worst_db"] <= THRESH_ROW_DB else "no"
        cr12 = "yes" if r["pred_nf290_worst_db"] <= THRESH_PLAN_DB else "no"
        rp = " (Q10 replay ok)" if r.get("replay") == "ok" else ""
        L.append(f"| `{r['arm']}` | {q}{rp} | {r['input_values'][0] * 1e9:.3f} nH / "
                 f"{r['input_values'][1] * 1e12:.3f} pF | {r['pred_nf290_mid_db']:.3f} / "
                 f"**{r['pred_nf290_worst_db']:.3f}** | {r['pred_s11_mid_db']:.2f} / "
                 f"{r['pred_s11_worst_db']:.2f} | {cr15} / {cr12} |")
    L += ["", "#### Threshold crossings (predictions within the sampled topology/search)", ""]
    for feed in ARMS:
        c = mapdoc["summary"][feed]["crossings"]
        for k in ("nf290_worst_le_1p5", "nf290_worst_le_1p2"):
            v = c[k]
            stmt = (f"min tested Q {v['min_tested_q']:g}" if not v["not_reached"]
                    else "not reached within tested range")
            L.append(f"- `{feed}` {k.replace('nf290_worst_le_1p', 'NF290 worst <= 1.')}: {stmt}"
                     + (f"; lossless bound crosses: {'yes' if v['lossless_crosses'] else 'no'}" if v["not_reached"] else ""))
    L += ["", "#### Feed-isolation bracket (measured; brackets are HYPOTHETICAL REQUIREMENT "
          "PROXIES, the retained EM model is the control)", "",
          "| Arm | Rqbr (Ohm) | isolation \\|Ztank\\| mid / band-min (Ohm) | NFmin@290 Q10 mid / worst "
          "(dB) | IC1 (mA) | dIC1 vs control | DC flags |", "|---|---|---|---|---|---|---|"]
    for r in iso_rows:
        if r["status"] == "invalid":
            L.append(f"| `{r['arm']}` | {r.get('rpar_ohm') or ''} | INVALID: {r['reason']} | | | | |")
            continue
        cs = r["cs"]
        ic = f"{r['audit']['ic1'] * 1e3:.5f}" if "audit" in r else "(retained)"
        dic = f"{r['dic1'] * 100:+.3f} %" if "dic1" in r else ""
        iso = (f"{r['z_tank_mid_ohm']:.1f} / {r['z_tank_bandmin_ohm']:.1f}"
               if r.get("z_tank_mid_ohm") is not None else "infinite (ideal 1 uH)")
        L.append(f"| `{r['arm']}` | {r.get('rpar_ohm') or ''} | {iso} | "
                 f"{cs['q10']['nfmin290_mid_db']:.3f} / **{cs['q10']['nfmin290_worst_db']:.3f}** | "
                 f"{ic} | {dic} | {'; '.join(r.get('dc_flags', [])) or 'none'} |")
    L += ["", f"Probe control arm vs retained-derived tank: |Z| mid "
          f"{abs(1 / probe['ctl'][ms.MID]):.1f} Ohm measured vs "
          f"{abs(1 / derived[ms.MID]):.1f} Ohm derived (declared tolerance "
          f"{CONTROL_TOL_Z_REL:.0%}).", "",
          "#### Boundary verification (declared rule; verified numbers, still hypothetical "
          "requirement proxies)", "",
          "| Boundary | Arm | Input Q | pred NF290 worst (11f) | verified NF290 mid / worst (21f) "
          "| verified worst (11f) | residual (11f) | S11 / S22 worst | \\|S21\\| min | mu bb min |",
          "|---|---|---|---|---|---|---|---|---|---|"]
    for b in bnd:
        if b["status"] != "verified":
            L.append(f"| `{b['tag']}` | `{b['arm']}` | | INVALID: {b['reason']} | | | | | | |")
            continue
        q = "lossless" if b["q_in"] is None else f"{b['q_in']:g}"
        L.append(f"| `{b['tag']}` | `{b['arm']}` | {q} | {b['pred_nf290_worst_db']:.3f} | "
                 f"{b['verified_nf290_mid_db']:.3f} / {b['verified_nf290_worst_db']:.3f} | "
                 f"{b['verified_nf290_worst_11f_db']:.3f} | {b['residual_worst_11f_db']:+.3f} | "
                 f"{b['s11_db_worst']:.2f} / {b['s22_db_worst']:.2f} | {b['s21_db_min']:.2f} | "
                 f"{b['mu_bb_min']:.10f} |")
    L += ["", "#### Requirements summary (sampled; predictions and proxies, not feasibility)", ""]
    for feed in ARMS:
        c = req[feed]["crossings"]
        for k, thresh in (("nf290_worst_le_1p5", "1.5 dB row"), ("nf290_worst_le_1p2", "1.2 dB planning limit")):
            v = c[k]
            stmt = (f"input Q >= {v['min_tested_q']:g} (tested)" if not v["not_reached"]
                    else "not reached within the tested input-Q range")
            L.append(f"- `{feed}` at the {thresh}: {stmt}"
                     + (f"; the lossless bound {'crosses' if v['lossless_crosses'] else 'does not cross'}."
                        if v["not_reached"] else "."))
    L.append(f"- Feed isolation at the 1.2 dB planning limit (DUT NFmin@290 worst): "
             f"{req['isolation']['nfmin290_worst_le_1p2']}.")
    L += ["", "#### Campaign verdict (bench policy; only an unmodified-model verified point can GO)", "",
          f"- Policy limit (declared): verified matched NF290 worst-in-band <= {ms.ROW_NF_DB:g} - "
          f"{fs.PVT_NF_MARGIN_DB:g} = {rec['limit_db']:.2f} dB; the ratified row is {ms.ROW_NF_DB:g} dB.",
          f"- **Verdict: {rec['verdict']}**" + (f"; binding constraint: `{rec['binding']}`; failing gates: "
                                                f"{', '.join(rec['failing'])}." if rec["failing"] else ".")]
    if "nf290_worst_db" in rec:
        L.append(f"- Physical candidate (the `em5_cmim` control verification): NF290 worst "
                 f"{rec['nf290_worst_db']:.3f} dB, DUT NFmin@290 worst {rec['nfmin290_worst_db']:.3f} dB, "
                 f"budget against the {ms.ROW_NF_DB:g} dB row {rec['nf_budget_left_db']:+.3f} dB.")
    if problems:
        L += ["", "**Problems / flags:**", ""] + [f"- {x}" for x in problems]
    return "\n".join(L) + "\n"


def add_pdk_args(p):
    fs.add_pdk_args(p)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("declare")
    g = sub.add_parser("control-gen")
    add_pdk_args(g)
    g.add_argument("--snapdir", required=True)
    g.add_argument("--outdir", required=True)
    s = sub.add_parser("stems")
    s.add_argument("--snapdir", required=True)
    s.add_argument("group", choices=("ctlchar", "probe", "ctlverify", "bracket", "boundary"))
    c = sub.add_parser("control-check")
    c.add_argument("--snapdir", required=True)
    c.add_argument("--corners", required=True)
    c.add_argument("--csv", required=True)
    v = sub.add_parser("ctl-verify-gen")
    add_pdk_args(v)
    v.add_argument("--snapdir", required=True)
    v.add_argument("--outdir", required=True)
    v.add_argument("--corners", required=True)
    v.add_argument("--nf-npts", type=int, default=None)
    k = sub.add_parser("ctl-verify-check")
    k.add_argument("--snapdir", required=True)
    k.add_argument("--corners", required=True)
    k.add_argument("--csv", required=True)
    q = sub.add_parser("qmap")
    add_pdk_args(q)
    q.add_argument("--snapdir", required=True)
    q.add_argument("--outdir", required=True)
    q.add_argument("--nf-npts", type=int, default=None)
    r = sub.add_parser("reduce")
    r.add_argument("--snapdir", required=True)
    r.add_argument("--corners", required=True)
    r.add_argument("--isolation-csv", required=True)
    r.add_argument("--map-csv", required=True)
    r.add_argument("--markdown", required=True)
    r.add_argument("--nf-npts", type=int, default=None)
    a = ap.parse_args(argv)
    if a.cmd in ("ctl-verify-gen", "qmap", "reduce"):
        a.nf_npts = ms.check_nf_npts(a.nf_npts if a.nf_npts is not None else retained_nf_npts())
    return globals()[f"cmd_{a.cmd.replace('-', '_')}"](a)


if __name__ == "__main__":
    sys.exit(main())
