#!/usr/bin/env python3
"""Finite resonant base-bias feed vs. the ideal-choke noise bound (issue #193).

Companion to run_feed_study.sh; builds on matching_solver.py (same bench, same
nominal cell, same RF helpers, same input/output synthesis and verification
decks). Subcommands, in run order:

  declare       print the candidate-set / provenance / policy declaration
                (committed BEFORE any run: feed-study-declaration.md)
  tune-gen      write the EM-inductor series-admittance deck
  plan          read the tuning data, size each tank capacitor (parasitics of
                the EM model already inside Yser), write the cap probe deck
                and one feed-scan deck per declared variant
  scan-reduce   DC audit + validity flags, NFmin@290 / 50-ohm NF@290, Zin,
                Zopt, S-parameters, broadband mu/k/|Delta|, tank resonances;
                pick the best DC-valid finite feed
  match-gen     characterization decks for the committed feed, the ideal
                choke and the best valid feed (the #186 characterization,
                R3b line swapped)
  match-solve   re-synthesize the existing noise-weighted input match
                (lp_noise, Q = 10) per feed and write the verification decks
                (DC reference on xout per #190)
  match-reduce  verified NF/gain/S11/S22/mu per feed, go/no-go

This is a NOMINAL-CELL bench exploration. Nothing here edits design/ or
spec/, and no number is a conformance claim. Stdlib only, so the unit tests
run PDK-free in CI.
"""
from __future__ import annotations

import argparse
import cmath
import csv
import json
import math
import re
import sys
from pathlib import Path
from types import SimpleNamespace

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import matching_solver as ms  # noqa: E402

TB_TUNE = HERE / "testbench" / "tb_feed_tune.spice.tmpl"
TB_CMIM = HERE / "testbench" / "tb_feed_cmimprobe.spice.tmpl"
TB_SCAN = HERE / "testbench" / "tb_feed_scan.spice.tmpl"

R3B_OHM = 330.0
XOUT_RDC = 1e11            # DC reference convention measured in #190 (R-independent 1e9..1e11)
TUNE_PER_DEC = 200
CMIM_CJ = 1.5e-15          # cornerCAP.lib cap_typ: cap_carea [F per (m-as-um)^2]
CMIM_CJSW = 40e-18         # capacitors_mod.lib cmim_core CJSW
CMIM_SIZE_TOL = 0.005      # realised-C tolerance vs. the tuned target
WINDOW = (ms.F_LO, ms.F_HI)

# --- bench policy (declared before the run; NOT ratified) -------------------
IC1_SHIFT_FLAG = 0.01      # |IC1/IC1_committed - 1| above this is a DC bias shift
VCE_MIN = 0.30             # V: below this a cascode device is near saturation
VBC_MAX = 0.40             # V: base-collector forward bias above this is near saturation
PVT_NF_MARGIN_DB = 0.30    # nominal-cell allowance for process/temp/supply/passive spread
SOURCE_Q_CASE = "q10"
MATCH_CANDIDATE = "lp_noise"
NOISE_BAND_TOL_DB = 0.05   # sp-NF vs .noise-NF agreement tolerated before a flag

# ---------------------------------------------------------------------------
# Declared candidate set
# ---------------------------------------------------------------------------
VARIANTS = {
    "committed": {
        "kind": "committed", "role": "baseline",
        "desc": "committed feed: R3b = 330 Ohm from bref to b1, unmodified"},
    "ideal_choke": {
        "kind": "choke", "role": "diagnostic bound",
        "desc": "ideal 1 uH choke in series with R3b (the #186 what-if; NOT a realizable on-chip part)"},
    "em5_cideal": {
        "kind": "tank", "role": "finite candidate", "geom": "em5", "cap": "ideal",
        "desc": "EM 5-turn spiral (5.52 nH) in parallel with an ideal tuning C, in series with R3b"},
    "em5_cmim": {
        "kind": "tank", "role": "finite candidate", "geom": "em5", "cap": "cmim",
        "desc": "EM 5-turn spiral in parallel with the pinned PDK cap_cmim, in series with R3b"},
    "em5_cmim_bp10": {
        "kind": "tank", "role": "bracket", "geom": "em5", "cap": "cmim", "bp_frac": 0.10,
        "desc": "as em5_cmim plus a 10 % bottom-plate parasitic to ground at the base node "
                "(ASSUMED bracket: the PDK cap_cmim model carries no bottom-plate capacitance)"},
    "em5_cq30": {
        "kind": "tank", "role": "bracket", "geom": "em5", "cap": "esr", "cap_q": 30.0,
        "desc": "as em5_cideal with the tuning C given a series ESR for Q_C = 30 at 2.44175 GHz "
                "(bracket for unknown capacitor loss; the PDK cap_cmim ESR is 55 mOhm)"},
    "em4_cideal": {
        "kind": "tank", "role": "finite candidate", "geom": "em4", "cap": "ideal",
        "desc": "EM 4-turn spiral (4.49 nH) in parallel with an ideal tuning C, in series with R3b"},
    "em4_cmim": {
        "kind": "tank", "role": "finite candidate", "geom": "em4", "cap": "cmim",
        "desc": "EM 4-turn spiral in parallel with the pinned PDK cap_cmim, in series with R3b"},
}
# The 1-turn geometry (0.097 nH, Q 4.1) is excluded from the simulated set on
# a measured-parameter argument: see EXCLUDED and the tuning table.
EXCLUDED = {"em1": "L = 0.097 nH, Q = 4.1 at 2.44175 GHz: a tank resonant there needs tens of pF "
                   "(tuning table) and its peak impedance Q*w*L is a few Ohm, far below R3b; "
                   "it cannot isolate R3b."}
FINITE_FOR_BEST = ("finite candidate",)       # best-valid selection pool (brackets are not selected)
TUNE_GEOMS = ("em1", "em4", "em5")


def cmim_cap_f(side_um: float) -> float:
    """cap_cmim realised C for a square side (um), cornerCAP.lib cap_typ:
    C = CJ*W*L + 2*CJSW*(W+L) with W = L = side (the PDK's `l/sf` unit trick)."""
    return CMIM_CJ * side_um ** 2 + 2 * CMIM_CJSW * (2 * side_um)


def cmim_side_for(c_f: float) -> float:
    """Square side (um) whose closed-form C equals c_f (positive root)."""
    if not (c_f > 0 and math.isfinite(c_f)):
        raise ValueError(f"cmim target C must be positive and finite (got {c_f!r})")
    a, b = CMIM_CJ, 4 * CMIM_CJSW
    return (-b + math.sqrt(b * b + 4 * a * c_f)) / (2 * a)


# ---------------------------------------------------------------------------
# Tank analysis (pure)
# ---------------------------------------------------------------------------
def tune_c(yser: complex, f: float) -> float:
    """Tuning C (F) that makes Im(Yser + jwC) = 0 at f. The inductor's own
    Cser is already inside Yser. Raises when the series branch is not
    inductive at f (no positive C resonates it)."""
    w = 2 * math.pi * f
    c = -yser.imag / w
    if not (c > 0 and math.isfinite(c)):
        raise ValueError(f"series branch not inductive at {f:g} Hz (Im Y = {yser.imag:g} S); no tuning C")
    return c


def esr_for_q(c_f: float, q: float, f: float = ms.F_MID) -> float:
    if not (q > 0 and c_f > 0):
        raise ValueError("Q and C must be positive")
    return 1.0 / (2 * math.pi * f * c_f * q)


def tank_admittance(yser: complex, c_f: float, f: float, esr: float = 0.0) -> complex:
    w = 2 * math.pi * f
    zc = complex(esr, -1.0 / (w * c_f))
    return yser + 1.0 / zc


def tank_resonances(freqs, ysers, c_f: float, esr: float = 0.0):
    """Zero crossings of Im(Y_tank) on the grid, log-f interpolated. kind is
    'parallel' (Im Y rises through 0: impedance peak) or 'series' (falls:
    impedance null). z_mag is |1/Y| interpolated at the crossing."""
    if len(freqs) != len(ysers) or len(freqs) < 2:
        raise ValueError("tank_resonances: need matching grids of >= 2 points")
    ys = [tank_admittance(y, c_f, f, esr) for f, y in zip(freqs, ysers)]
    out = []
    for i in range(len(freqs) - 1):
        a, b = ys[i].imag, ys[i + 1].imag
        if a == 0 or (a < 0) != (b < 0):
            t = 0.0 if a == b else a / (a - b)
            lf = math.log(freqs[i]) + t * (math.log(freqs[i + 1]) - math.log(freqs[i]))
            ya = ys[i]
            yb = ys[i + 1]
            y0 = ya + t * (yb - ya)
            out.append({"f_hz": math.exp(lf), "kind": "parallel" if b > a else "series",
                        "z_mag_ohm": 1.0 / abs(y0) if abs(y0) > 0 else math.inf,
                        "re_y_s": y0.real})
    return out


def inductor_srf(freqs, ysers):
    """First frequency where Im(Yser) rises through zero (self-resonance of
    the inductor alone), or None."""
    for r in tank_resonances(freqs, ysers, 1e-30):
        if r["kind"] == "parallel":
            return r["f_hz"]
    return None


def inductor_l_q(yser: complex, f: float):
    """(L_eff [H], Q) of the series branch at f from its admittance."""
    z = 1.0 / yser
    return z.imag / (2 * math.pi * f), (z.imag / z.real if z.real > 0 else math.inf)


# ---------------------------------------------------------------------------
# Feed netlist edits
# ---------------------------------------------------------------------------
def variant_plan_check(plan: dict) -> None:
    for k in ("c_tune_f", "cmim_side_um"):
        if k not in plan or not isinstance(plan[k], dict):
            raise ValueError(f"feed plan lacks '{k}'")


def feed_lines(name: str, plan: dict | None) -> str:
    """Replacement text for the DUT's R3b line. R3b and the bref reference are
    always retained; DC bias is never retuned."""
    v = VARIANTS[name]
    if v["kind"] == "committed":
        return ms.R3B_LINE
    head = [f"* BENCH EDIT (issue #193, variant {name}: {v['role']}): {v['desc']}",
            f"R3b bref b1f {R3B_OHM:g} m=1"]
    if v["kind"] == "choke":
        return "\n".join(head + [f"Lfeed b1f b1 {ms.FEED_CHOKE:g}"])
    if plan is None:
        raise ValueError(f"variant {name} needs a feed plan")
    variant_plan_check(plan)
    g = v["geom"]
    c = plan["c_tune_f"][g]
    lines = head + [f"XLfeed b1f b1 vss {ms.em_instance(g)}"]
    cap = v["cap"]
    if cap == "ideal":
        lines.append(f"Cfeed b1f b1 {c:.8g}")
    elif cap == "esr":
        esr = esr_for_q(c, v["cap_q"])
        lines += [f"Cfeed b1f cf_x {c:.8g}", f"Rcfeed cf_x b1 {esr:.6g}"]
    elif cap == "cmim":
        s = plan["cmim_side_um"][g]
        lines.append(f"XCfeed b1f b1 cap_cmim w={s:.6g}u l={s:.6g}u")
    else:
        raise ValueError(f"unknown cap kind {cap!r}")
    if v.get("bp_frac"):
        lines.append(f"Cbpfeed b1 vss {v['bp_frac'] * c:.8g}")
    return "\n".join(lines)


def feed_includes(name: str, cap_lib: str) -> str:
    v = VARIANTS[name]
    lines = []
    if v["kind"] == "tank":
        lines.append(f'.include "{ms.EM_MODEL}"')
        if v["cap"] == "cmim":
            lines.append(f'.lib "{cap_lib}" cap_typ')
    return "\n".join(lines) if lines else "* (no EM inductor / MIM capacitor in this variant)"


def apply_feed(text: str, name: str, plan: dict | None, cap_lib: str) -> str:
    """Swap the feed into an already-rendered deck (char or verify): exactly one
    R3b line, model includes added before `.options` unless already present."""
    if text.count(ms.R3B_LINE) != 1:
        raise ValueError(f"deck carries '{ms.R3B_LINE}' {text.count(ms.R3B_LINE)} times, expected once")
    text = text.replace(ms.R3B_LINE, feed_lines(name, plan))
    inc = [ln for ln in feed_includes(name, cap_lib).splitlines() if ln.startswith(".")]
    inc = [ln for ln in inc if ln not in text]
    if inc:
        anchor = ".options temp=27 tnom=27 gmin=1e-10"
        if text.count(anchor) != 1:
            raise ValueError("deck lacks a unique .options anchor")
        text = text.replace(anchor, "\n".join(inc) + "\n\n" + anchor)
    return text


def dc_connected(netlist: str, a: str, b: str) -> bool:
    """DC-path continuity between nodes a and b over R, L, V and EM-inductor
    subcircuit instances (capacitors, transistors and everything else are
    DC-open here -- a conservative, PDK-free check of the feed path)."""
    parent: dict = {}

    def find(x):
        parent.setdefault(x, x)
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(x, y):
        parent[find(x)] = find(y)

    for raw in netlist.splitlines():
        ln = raw.split("$")[0].strip().lower()
        if not ln or ln[0] in "*.+":
            continue
        tok = ln.split()
        c = tok[0][0]
        if c in "rlv" and len(tok) >= 3:
            union(tok[1], tok[2])
        elif c == "x" and "inductor" in tok and len(tok) >= 4:
            union(tok[1], tok[2])
    return find(a.lower()) == find(b.lower())


def assert_feed_dc_path(text: str) -> None:
    if not dc_connected(text, "bref", "b1"):
        raise ValueError("feed has no DC path from bref to b1 (no DC current for Q1's base)")


# ---------------------------------------------------------------------------
# DC audit
# ---------------------------------------------------------------------------
DC_KEYS = ["ic1", "ic2", "ib1", "vb1", "ve1", "vcasc", "voutn", "vb2", "vbref", "idd", "pdc"]


def parse_dc_audit(log: Path) -> dict:
    text = Path(log).read_text()
    if not re.search(r"^BENCH_COMPLETE", text, re.M):
        raise ValueError(f"{log}: no BENCH_COMPLETE marker")
    m = re.search(r"^DC (.*)$", text, re.M)
    if not m:
        raise ValueError(f"{log}: no DC audit line")
    tok = m.group(1).split()
    if len(tok) % 2:
        raise ValueError(f"{log}: odd DC audit token count")
    kv = dict(zip(tok[0::2], tok[1::2]))
    out = {}
    for k in DC_KEYS:
        if k not in kv:
            raise ValueError(f"{log}: DC audit lacks '{k}'")
        v = float(kv[k])
        if not math.isfinite(v):
            raise ValueError(f"{log}: non-finite DC audit value {k}")
        out[k] = v
    out["vbe1"] = out["vb1"] - out["ve1"]
    out["vce1"] = out["vcasc"] - out["ve1"]
    out["vce2"] = out["voutn"] - out["vcasc"]
    out["vbc1"] = out["vb1"] - out["vcasc"]
    out["vbc2"] = out["vb2"] - out["voutn"]
    out["vfeed_drop"] = out["vbref"] - out["vb1"]
    return out


def dc_flags(audit: dict, base: dict) -> list:
    """Flags (empty = DC-valid). Bias shifts are FLAGGED against the committed
    feed's own audit; nothing is retuned."""
    f = []
    for key, tag in (("ic1", "IC1"), ("idd", "IDD")):
        rel = audit[key] / base[key] - 1.0
        if abs(rel) > IC1_SHIFT_FLAG:
            f.append(f"DC_BIAS_SHIFT_{tag} ({rel * 100:+.2f} %)")
    if audit["ic1"] <= 0 or audit["ic2"] <= 0:
        f.append("INVALID_OP_NONPOSITIVE_IC")
    for k, name in (("vce1", "Q1"), ("vce2", "Q2")):
        if audit[k] < VCE_MIN:
            f.append(f"NEAR_SATURATION_{name} (VCE {audit[k]:.3f} V < {VCE_MIN:g} V)")
    for k, name in (("vbc1", "Q1"), ("vbc2", "Q2")):
        if audit[k] > VBC_MAX:
            f.append(f"BC_FORWARD_{name} (VBC {audit[k]:.3f} V > {VBC_MAX:g} V)")
    return f


# ---------------------------------------------------------------------------
# Deck generation
# ---------------------------------------------------------------------------
def n_dec_points(per_dec: int, lo: float, hi: float) -> int:
    return int(round(per_dec * math.log10(hi / lo))) + 1


def dec_freqs(per_dec: int, lo: float, hi: float) -> list:
    """ngspice `ac dec N lo hi` grid: n points log-spaced from lo EXACTLY to hi
    (the step is (hi/lo)**(1/(n-1)), not 10**(1/N))."""
    n = n_dec_points(per_dec, lo, hi)
    return [lo * (hi / lo) ** (i / (n - 1)) for i in range(n)]


def tune_deck(a) -> str:
    ports, vecs = [], []
    for g in TUNE_GEOMS:
        ports.append(f"X{g} la_{g} lb_{g} 0 {ms.em_instance(g)}\n"
                     f"V{g}a la_{g} 0 dc 0 ac 1\nV{g}m lb_{g} 0 dc 0")
        vecs += [f"real(i(v{g}m))", f"imag(i(v{g}m))"]
    return ms.render(TB_TUNE, {
        "EM_MODEL": ms.EM_MODEL, "ONEPORTS": "\n".join(ports), "VECS": " ".join(vecs),
        "N_PER_DEC": TUNE_PER_DEC, "F_LO": f"{ms.F_STAB_LO:g}", "F_HI": f"{ms.F_STAB_HI:g}",
        "F_MID": f"{ms.F_MID:g}", "OUTDIR": a.outdir})


def load_tune(cdir: Path) -> dict:
    """{geom: {'freqs','y','y_mid'}} from the tuning deck's two tables."""
    fr = dec_freqs(TUNE_PER_DEC, ms.F_STAB_LO, ms.F_STAB_HI)
    _, cols = ms.columns(cdir / "tune_yser.dat", len(fr), fr)
    _, mid = ms.columns(cdir / "tune_yser_mid.dat", 1, [ms.F_MID])
    log = (cdir / "tune.log").read_text()
    if not re.search(r"^BENCH_COMPLETE", log, re.M):
        raise ValueError("tune.log: no BENCH_COMPLETE marker")
    out = {}
    for g in TUNE_GEOMS:
        re_k, im_k = f"real(i(v{g}m))", f"imag(i(v{g}m))"
        y = [complex(r, i) for r, i in zip(cols[re_k], cols[im_k])]
        ym = complex(mid[re_k][0], mid[im_k][0])
        # current INTO the 0 V source: positive real part for a passive branch
        if not (ym.real > 0):
            raise ValueError(f"tune data for {g}: Re(Yser) <= 0 at f_mid (sign/convention error)")
        out[g] = {"freqs": fr, "y": y, "y_mid": ym}
    return out


def make_plan(tune: dict) -> dict:
    """Tuning table + tank capacitor sizes from the measured series admittance."""
    rows, c_tune, sides = {}, {}, {}
    for g in TUNE_GEOMS:
        ym = tune[g]["y_mid"]
        l_eff, q = inductor_l_q(ym, ms.F_MID)
        srf = inductor_srf(tune[g]["freqs"], tune[g]["y"])
        row = {"l_nh": l_eff * 1e9, "q": q, "srf_hz": srf,
               "rp_alone_ohm": q * 2 * math.pi * ms.F_MID * l_eff,
               "outer_d_um": ms.em_outer_diameter_um(g)}
        try:
            c = tune_c(ym, ms.F_MID)
            row["c_tune_pf"] = c * 1e12
            if g in {v.get("geom") for v in VARIANTS.values()}:
                c_tune[g] = c
                sides[g] = cmim_side_for(c)
                row["cmim_side_um"] = sides[g]
        except ValueError as ex:
            row["c_tune_pf"] = None
            row["note"] = str(ex)
        res = tank_resonances(tune[g]["freqs"], tune[g]["y"], c_tune[g]) if g in c_tune else []
        row["tank_resonances"] = res
        rows[g] = row
    return {"f_tune_hz": ms.F_MID, "c_tune_f": c_tune, "cmim_side_um": sides, "geoms": rows}


def cmim_probe_deck(a, plan: dict) -> str:
    ports, vecs = [], []
    for g, s in sorted(plan["cmim_side_um"].items()):
        ports.append(f"Xc{g} cp_{g} 0 cap_cmim w={s:.6g}u l={s:.6g}u\nIc{g} 0 cp_{g} dc 0 ac 1")
        vecs += [f"real(v(cp_{g}))", f"imag(v(cp_{g}))"]
    return ms.render(TB_CMIM, {
        "CAP_LIB": a.cap_lib, "ONEPORTS": "\n".join(ports), "VECS": " ".join(vecs),
        "F_MID": f"{ms.F_MID:g}", "OUTDIR": a.outdir})


def read_cmim_probe(cdir: Path, plan: dict) -> dict:
    _, cols = ms.columns(cdir / "cmim_probe.dat", 1, [ms.F_MID])
    out = {}
    w = 2 * math.pi * ms.F_MID
    for g, s in sorted(plan["cmim_side_um"].items()):
        z = complex(cols[f"real(v(cp_{g}))"][0], cols[f"imag(v(cp_{g}))"][0])
        if not (z.imag < 0):
            raise ValueError(f"cmim probe {g}: not capacitive")
        c = -1.0 / (w * z.imag)
        target = plan["c_tune_f"][g]
        out[g] = {"side_um": s, "c_pf": c * 1e12, "target_pf": target * 1e12,
                  "err_frac": c / target - 1.0, "esr_ohm": z.real,
                  "within_tol": abs(c / target - 1.0) <= CMIM_SIZE_TOL}
    return out


def scan_deck(a, name: str, plan: dict) -> str:
    entry = VARIANTS[name]
    body = ms.dut_base()
    if body.count(ms.R3B_LINE) != 1:
        raise ValueError(f"DUT carries '{ms.R3B_LINE}' {body.count(ms.R3B_LINE)} times, expected once")
    body = body.replace(ms.R3B_LINE, feed_lines(name, plan))
    assert_feed_dc_path(body)
    notes = [f"* {entry['desc']}"]
    if entry["kind"] == "tank":
        notes.append(f"* Tank C = {plan['c_tune_f'][entry['geom']] * 1e12:.5g} pF "
                     f"(tuned at {ms.F_MID:g} Hz on the EM Yser, parasitic Cser included)")
    return ms.render(TB_SCAN, {
        **ms.pdk_subs(a), "VARIANT": name, "ROLE": entry["role"],
        "VARIANT_NOTES": "\n".join(notes),
        "FEED_INCLUDES": feed_includes(name, a.cap_lib),
        "DUT": body, "STEM": f"scan_{name}", "OUTDIR": a.outdir,
        "N_BAND": ms.N_BAND, "F_LO": f"{ms.F_LO:g}", "F_HI": f"{ms.F_HI:g}",
        "N_STAB_DEC": ms.N_STAB_DEC, "F_STAB_LO": f"{ms.F_STAB_LO:g}", "F_STAB_HI": f"{ms.F_STAB_HI:g}",
        "N_NF": a.nf_npts})


# ---------------------------------------------------------------------------
# Scan reduction
# ---------------------------------------------------------------------------
def reduce_scan_variant(cdir: Path, name: str, nf_npts: int) -> dict:
    stem = f"scan_{name}"
    freqs = ms.band_freqs()
    _, ib = ms.columns(cdir / f"{stem}.inband.dat", ms.N_BAND, freqs)
    s = {n: ms.cplx(ib, n) for n in ("s_1_1", "s_2_1", "s_1_2", "s_2_2")}
    sopt = [complex(r, i) for r, i in zip(ib["real(SOpt)"], ib["imag(SOpt)"])]
    nfq = ms.nf_freqs(nf_npts)
    _, nf = ms.columns(cdir / f"{stem}.nf290.dat", nf_npts, nfq)
    nf290 = nf["nf290"]
    band = []
    for i, f in enumerate(freqs):
        zin = ms.z_from_s(s["s_1_1"][i])
        zopt = ms.z_from_s(sopt[i])
        j = 2 * i if nf_npts == 2 * (ms.N_BAND - 1) + 1 else None
        band.append({
            "f": f, "s11_db": ms.db20(abs(s["s_1_1"][i])), "s21_db": ms.db20(abs(s["s_2_1"][i])),
            "s12_db": ms.db20(abs(s["s_1_2"][i])), "s22_db": ms.db20(abs(s["s_2_2"][i])),
            "zin": zin, "zopt": zopt, "rn": ib["real(Rn)"][i],
            "nfmin290_db": ms.nf_reref(ib["real(NFmin)"][i], ms.T_ANALYSIS),
            "nf50_290_sp_db": ms.nf_reref(ib["real(NF)"][i], ms.T_ANALYSIS),
            "nf50_290_noise_db": nf290[j] if j is not None else None})
    sf = ms.stab_freqs()
    _, st = ms.columns(cdir / f"{stem}.stab.dat", len(sf), sf)
    ss = {n: ms.cplx(st, n) for n in ("s_1_1", "s_2_1", "s_1_2", "s_2_2")}
    mus, ks, ds = [], [], []
    for i in range(len(sf)):
        mu, k, d = ms.stability(ss["s_1_1"][i], ss["s_2_1"][i], ss["s_1_2"][i], ss["s_2_2"][i])
        mus.append(mu)
        ks.append(k)
        ds.append(d)
    m11 = [abs(x) for x in ss["s_1_1"]]
    m22 = [abs(x) for x in ss["s_2_2"]]
    imu = min(range(len(sf)), key=lambda i: mus[i])
    ik = min(range(len(sf)), key=lambda i: ks[i])
    k_lt1 = [sf[i] for i in range(len(sf)) if ks[i] < 1.0]
    audit = parse_dc_audit(cdir / f"{stem}.log")
    conv = ms.classify_convergence(cdir / f"{stem}.log")
    i11 = max(range(len(sf)), key=lambda i: m11[i])
    i22 = max(range(len(sf)), key=lambda i: m22[i])
    summ = {
        "variant": name, "audit": audit, "convergence": conv,
        "nfmin290_mid_db": band[ms.MID]["nfmin290_db"],
        "nfmin290_worst_db": max(b["nfmin290_db"] for b in band),
        "nfmin290_best_db": min(b["nfmin290_db"] for b in band),
        "nf50_290_sp_mid_db": band[ms.MID]["nf50_290_sp_db"],
        "nf50_290_sp_worst_db": max(b["nf50_290_sp_db"] for b in band),
        "nf50_290_noise_mid_db": nf290[(nf_npts - 1) // 2],
        "nf50_290_noise_worst_db": max(nf290),
        "zin_mid": [band[ms.MID]["zin"].real, band[ms.MID]["zin"].imag],
        "zopt_mid": [band[ms.MID]["zopt"].real, band[ms.MID]["zopt"].imag],
        "rn_mid": band[ms.MID]["rn"],
        "s11_db_mid": band[ms.MID]["s11_db"], "s22_db_mid": band[ms.MID]["s22_db"],
        "s21_db_mid": band[ms.MID]["s21_db"], "s21_db_min": min(b["s21_db"] for b in band),
        "mu_bb_min": mus[imu], "mu_bb_f_min_hz": sf[imu],
        "mu_bb_n_lt1": sum(1 for x in mus if x <= 1.0),
        "mu_bb_n_resolved_lt1": sum(1 for x in mus if x < 1.0 - ms.MU_RESOLUTION),
        "mu_bb_n_unresolved": sum(1 for x in mus if abs(x - 1.0) <= ms.MU_RESOLUTION),
        "k_bb_min": ks[ik], "k_bb_f_min_hz": sf[ik],
        "k_bb_n_lt1": len(k_lt1),
        "k_lt1_f_lo_hz": min(k_lt1) if k_lt1 else None, "k_lt1_f_hi_hz": max(k_lt1) if k_lt1 else None,
        "delta_bb_min": min(ds), "delta_bb_max": max(ds),
        "s11_mag_bb_max": m11[i11], "s11_mag_bb_f_hz": sf[i11],
        "s22_mag_bb_max": m22[i22], "s22_mag_bb_f_hz": sf[i22],
        "n_stab_pts": len(sf),
        "sp_vs_noise_nf_maxdiff_db": (max(abs(b["nf50_290_sp_db"] - b["nf50_290_noise_db"]) for b in band)
                                      if band[0]["nf50_290_noise_db"] is not None else None),
    }
    return {"summary": summ, "band": band, "stab": {"f": sf, "mu": mus, "k": ks, "delta": ds,
                                                      "m11": m11, "m22": m22}}


def feed_area_um2(name: str, plan: dict) -> float:
    """Bounding-box area of the added feed parts (spiral outer square + square
    MIM capacitor). A lower bound: no keep-out, guard ring or routing."""
    v = VARIANTS[name]
    if v["kind"] != "tank":
        return 0.0
    area = ms.em_outer_diameter_um(v["geom"]) ** 2
    if v["cap"] == "cmim":
        area += plan["cmim_side_um"][v["geom"]] ** 2
    return area


def select_best(results: dict, plan: dict):
    """Lowest worst-in-band NFmin@290 among DC-valid, convergent, finite
    candidates (the rule declared before the run). None when there is none."""
    pool = []
    for name, r in results.items():
        if VARIANTS[name]["role"] not in FINITE_FOR_BEST:
            continue
        s = r["summary"]
        if s["dc_flags"] or not s["convergence"]["normal"]:
            continue
        pool.append((s["nfmin290_worst_db"], name))
    return min(pool)[1] if pool else None


SCAN_COLS = ["variant", "role", "ic1_ma", "ib1_ua", "idd_ma", "pdc_mw", "vbe1_v", "vce1_v", "vce2_v",
             "vbc1_v", "vbc2_v", "vfeed_drop_mv", "dc_valid", "dc_flags", "op_converged_normal",
             "nfmin290_mid_db", "nfmin290_worst_db", "nf50_290_noise_mid_db", "nf50_290_noise_worst_db",
             "nf50_290_sp_mid_db", "zin_mid_r", "zin_mid_i", "zopt_mid_r", "zopt_mid_i", "rn_mid_ohm",
             "s11_mid_db", "s22_mid_db", "s21_mid_db", "s21_min_db", "mu_bb_min", "mu_bb_f_min_hz",
             "mu_bb_n_resolved_lt1", "mu_bb_n_unresolved", "k_bb_min", "k_bb_n_lt1", "delta_bb_max",
             "s11_mag_bb_max", "s11_mag_bb_f_hz", "s22_mag_bb_max", "s22_mag_bb_f_hz", "feed_area_um2"]


def scan_row(name: str, s: dict, area: float) -> list:
    a = s["audit"]
    flags = s["dc_flags"]
    fmt = lambda x, nd=6: f"{x:.{nd}g}"  # noqa: E731
    return [name, VARIANTS[name]["role"], fmt(a["ic1"] * 1e3), fmt(a["ib1"] * 1e6), fmt(a["idd"] * 1e3),
            fmt(a["pdc"] * 1e3), fmt(a["vbe1"]), fmt(a["vce1"]), fmt(a["vce2"]), fmt(a["vbc1"]),
            fmt(a["vbc2"]), fmt(a["vfeed_drop"] * 1e3), "yes" if not flags else "NO",
            ";".join(flags) if flags else "", "yes" if s["convergence"]["normal"] else "NO",
            fmt(s["nfmin290_mid_db"]), fmt(s["nfmin290_worst_db"]), fmt(s["nf50_290_noise_mid_db"]),
            fmt(s["nf50_290_noise_worst_db"]), fmt(s["nf50_290_sp_mid_db"]),
            fmt(s["zin_mid"][0]), fmt(s["zin_mid"][1]), fmt(s["zopt_mid"][0]), fmt(s["zopt_mid"][1]),
            fmt(s["rn_mid"]), fmt(s["s11_db_mid"]), fmt(s["s22_db_mid"]), fmt(s["s21_db_mid"]),
            fmt(s["s21_db_min"]), f"{s['mu_bb_min']:.10f}", fmt(s["mu_bb_f_min_hz"]),
            str(s["mu_bb_n_resolved_lt1"]), str(s["mu_bb_n_unresolved"]), fmt(s["k_bb_min"]),
            str(s["k_bb_n_lt1"]), fmt(s["delta_bb_max"]), fmt(s["s11_mag_bb_max"]), fmt(s["s11_mag_bb_f_hz"]),
            fmt(s["s22_mag_bb_max"]), fmt(s["s22_mag_bb_f_hz"]), fmt(area)]


BAND_COLS = ["variant", "f_hz", "s11_db", "s21_db", "s12_db", "s22_db", "zin_r", "zin_i", "zopt_r", "zopt_i",
             "rn_ohm", "nfmin290_db", "nf50_290_sp_db", "nf50_290_noise_db"]


def band_rows(name: str, band: list) -> list:
    out = []
    for b in band:
        nfn = b["nf50_290_noise_db"]
        out.append([name, f"{b['f']:.9g}", f"{b['s11_db']:.6f}", f"{b['s21_db']:.6f}", f"{b['s12_db']:.6f}",
                    f"{b['s22_db']:.6f}", f"{b['zin'].real:.6f}", f"{b['zin'].imag:.6f}",
                    f"{b['zopt'].real:.6f}", f"{b['zopt'].imag:.6f}", f"{b['rn']:.6f}",
                    f"{b['nfmin290_db']:.6f}", f"{b['nf50_290_sp_db']:.6f}",
                    "" if nfn is None else f"{nfn:.6f}"])
    return out


def reduce_scan(cdir: Path, plan: dict, nf_npts: int, base_name: str = "committed"):
    """All variants -> (results, problems). Raises on missing/malformed data."""
    results, problems = {}, []
    for name in VARIANTS:
        results[name] = reduce_scan_variant(cdir, name, nf_npts)
    base = results[base_name]["summary"]["audit"]
    for name, r in results.items():
        s = r["summary"]
        s["dc_flags"] = dc_flags(s["audit"], base)
        if not s["convergence"]["normal"]:
            problems.append(f"{name}: operating-point convergence fallback/warning in the log")
        d = s["sp_vs_noise_nf_maxdiff_db"]
        if d is not None and d > NOISE_BAND_TOL_DB:
            problems.append(f"{name}: sp-derived and .noise 50-ohm NF290 differ by {d:.3f} dB (> {NOISE_BAND_TOL_DB} dB)")
    return results, problems


# ---------------------------------------------------------------------------
# Go / no-go
# ---------------------------------------------------------------------------
GATES = ["dc_validity", "convergence", "noise_floor", "noise_match_penalty", "noise_margin",
         "s11", "s22", "s21", "stability"]


def recommend(scan: dict | None, match: dict | None, margin_db: float = PVT_NF_MARGIN_DB) -> dict:
    """Deterministic go/no-go from the best valid feed's scan summary and its
    verified matched metrics (policy declared before the run). `scan`: the
    scan summary (with dc_flags/convergence); `match`: ms.reduce_one metrics
    plus 'convergence'. Returns {'verdict','binding','failing','limit_db',...}."""
    limit = ms.ROW_NF_DB - margin_db
    if scan is None or match is None:
        return {"verdict": "NO-GO", "binding": "dc_validity", "failing": ["dc_validity"],
                "limit_db": limit, "reason": "no DC-valid, convergent finite feed was available to match"}
    failing = []
    if scan["dc_flags"]:
        failing.append("dc_validity")
    if not scan["convergence"]["normal"] or not match["convergence"]["normal"]:
        failing.append("convergence")
    nf = match["nf290_db_worst"]
    if scan["nfmin290_worst_db"] > limit:
        failing.append("noise_floor")
    elif nf > ms.ROW_NF_DB:
        failing.append("noise_match_penalty")
    elif nf > limit:
        failing.append("noise_margin")
    if not match["s11_db_worst"] < ms.ROW_S11_DB:
        failing.append("s11")
    if not match["s22_db_worst"] < ms.ROW_S22_DB:
        failing.append("s22")
    if not match["s21_db_min"] > ms.ROW_S21_DB:
        failing.append("s21")
    if match["mu_bb_min"] < 1.0 - ms.MU_RESOLUTION:
        failing.append("stability")
    failing = [g for g in GATES if g in failing]
    return {"verdict": "GO" if not failing else "NO-GO", "binding": failing[0] if failing else None,
            "failing": failing, "limit_db": limit,
            "nf290_worst_db": nf, "nf_budget_left_db": ms.ROW_NF_DB - nf,
            "nfmin290_worst_db": scan["nfmin290_worst_db"]}


# ---------------------------------------------------------------------------
# Declaration (printed, committed before the run)
# ---------------------------------------------------------------------------
def declaration_text() -> str:
    L = []
    L.append("# Feed-study declaration (issue #193)")
    L.append("")
    L.append("Committed BEFORE any simulation of this study. Generated by")
    L.append("`python3 -I sim/lna-matching-feasibility/feed_study.py declare`; a unit test")
    L.append("checks that this file equals that output, so it cannot drift from the code.")
    L.append("")
    L.append("**NOMINAL-CELL EXPLORATION.** One PVT cell (hbt_typ / mos_tt, 27 C, 1.80 V). No")
    L.append("ratified-row or final-stability claim; `design/` and `spec/` are not modified.")
    L.append("")
    L.append("## Question")
    L.append("")
    L.append("Can a finite, model-backed parallel-LC tank in series with R3b (330 Ohm, DR-0003")
    L.append("reference retained, bias NOT retuned) recover a useful part of the noise")
    L.append("headroom that the ideal 1 uH choke exposes (NFmin@290 2.445 -> 0.467 dB in the")
    L.append("#186 what-if), on the unresized DUT?")
    L.append("")
    L.append("## Candidate set")
    L.append("")
    L.append("| Variant | Role | Definition |")
    L.append("|---|---|---|")
    for n, v in VARIANTS.items():
        L.append(f"| `{n}` | {v['role']} | {v['desc']} |")
    L.append("")
    L.append("Excluded without simulation: " + "; ".join(f"`{g}`: {why}" for g, why in EXCLUDED.items()))
    L.append("")
    L.append("Topology: `bref -R3b- b1f -[ XLfeed (EM spiral, DC path) || C ]- b1`. The spiral's")
    L.append("`sub` terminal is the DUT `vss`. Tuning C is chosen so Im(Yser + jwC) = 0 at")
    L.append(f"{ms.F_MID:g} Hz, where Yser is the MEASURED series-branch admittance of the EM model")
    L.append("(its self-capacitance Cser is inside Yser; the substrate shunts are not part of the")
    L.append("tank and load b1f / b1 in the simulation). Tuning is done once per geometry, not")
    L.append("per-variant optimized.")
    L.append("")
    L.append("## Model provenance")
    L.append("")
    L.append("- Inductors: `sim/models/sg13g2_inductor_em.spice` (stamped from sg13g2-vco; see")
    L.append("  `sim/models/SOURCE.md`; hash-checked by `sim/models/check_sources.sh`). Three")
    L.append("  extracted geometries, one process point, one temperature; `mc_rsh = mc_rsub = 1`.")
    L.append("  No arbitrary scaled ideal inductor is used for any finite candidate.")
    L.append("- Capacitor: PDK `cap_cmim` (`cornerCAP.lib` section `cap_typ`, `capacitors_mod.lib`),")
    L.append(f"  sized square by C = {CMIM_CJ:g}*S^2 + 2*{CMIM_CJSW:g}*(2S) (S in um) and then")
    L.append("  MEASURED as a one-port; the model has a 55 mOhm top-plate resistor and NO")
    L.append("  bottom-plate parasitic capacitance (its header defers that to extraction). That")
    L.append("  evidence is missing and is bracketed (`em5_cmim_bp10`: ASSUMED 10 %), not claimed.")
    L.append("  Generic ideal C with a Q_C = 30 ESR (`em5_cq30`) brackets unknown capacitor loss.")
    L.append("- Transistors / MOS: unchanged `hbt_typ` and `mos_tt` sections; simulator ngspice-46.")
    L.append("- The `ideal_choke` variant is a DIAGNOSTIC BOUND, never a design candidate.")
    L.append("")
    L.append("## Policy declared before running (bench policy, NOT ratified)")
    L.append("")
    L.append(f"- DC bias shift flag: |IC1 / IC1(committed) - 1| or the same for IDD > {IC1_SHIFT_FLAG:.0%}.")
    L.append(f"- Operating-point validity flags: VCE < {VCE_MIN:g} V or VBC > {VBC_MAX:g} V on Q1/Q2;")
    L.append("  non-positive collector current; any non-normal ngspice convergence (singular")
    L.append("  matrix, failed gmin/source stepping, transient-op fallback). Flags are reported;")
    L.append("  the bias is never retuned to hide them.")
    L.append("- Best valid feed: lowest worst-in-band NFmin@290 among `finite candidate` variants")
    L.append("  with no DC flag and normal convergence (brackets are reported, not selected).")
    L.append(f"- Matching verification: the existing `{MATCH_CANDIDATE}` noise-weighted input match,")
    L.append(f"  Q = 10 case, re-synthesized from each feed's own characterization; DC reference")
    L.append(f"  `Rxoutdc = {XOUT_RDC:g}` Ohm on xout (the #190 convention, R-independent 1e9..1e11).")
    L.append("  The committed feed and the ideal choke are matched the same way for comparison.")
    L.append(f"- Go/no-go for a later full-PVT campaign: GO only if, for the best valid feed, the")
    L.append(f"  VERIFIED matched worst-in-band NF@290 <= {ms.ROW_NF_DB:g} - {PVT_NF_MARGIN_DB:g} dB (an allowance")
    L.append("  for process/temperature/supply/passive spread that a nominal cell cannot measure),")
    L.append("  S11 and S22 < -10 dB, |S21| > 15 dB across the band, no resolved mu < 1 over")
    L.append("  10 MHz-30 GHz, DC-valid, convergent. Otherwise NO-GO, and the first failing gate in")
    L.append(f"  the order {' > '.join(GATES)} is reported as the binding constraint.")
    L.append("")
    L.append("## Run budget")
    L.append("")
    L.append("Single-process `ngspice -b` decks, strictly sequential, nominal cell only: 1 tuning,")
    L.append("1 capacitor probe, 8 feed scans, 3 characterizations, 3 verifications = 16. No")
    L.append("corner grid, no Monte Carlo, no fleet submission (and no local-grid fallback).")
    L.append("")
    return "\n".join(L) + "\n"


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def add_pdk_args(p):
    p.add_argument("--models-lib", required=True)
    p.add_argument("--mos-lib", required=True)
    p.add_argument("--osdi-dir", required=True)
    p.add_argument("--cap-lib", required=True, help="cornerCAP.lib (section cap_typ)")


def _wr(path, text):
    Path(path).write_text(text)


def cmd_tune_gen(a):
    _wr(Path(a.snapdir) / "tune.spice", tune_deck(a))
    print(f"tune-gen: wrote {a.snapdir}/tune.spice")


def cmd_plan(a):
    check = ms.check_nf_npts(a.nf_npts)
    tune = load_tune(Path(a.outdir))
    plan = make_plan(tune)
    snap = Path(a.snapdir)
    _wr(snap / "cmim_probe.spice", cmim_probe_deck(a, plan))
    for name in VARIANTS:
        _wr(snap / f"scan_{name}.spice", scan_deck(a, name, plan))
    doc = {"generator": "sim/lna-matching-feasibility/feed_study.py plan",
           "design_netlist_sha256": ms.sha256(ms.DESIGN_NETLIST), "em_model_sha256": ms.sha256(ms.EM_MODEL),
           "nf_npts": check, "variants": VARIANTS, "excluded": EXCLUDED, "plan": plan}
    _wr(snap / "feed_plan.json", json.dumps(doc, indent=2, default=str) + "\n")
    print(f"plan: {len(VARIANTS)} scan decks + cmim_probe.spice + feed_plan.json in {snap}")


def _load_plan(snapdir) -> dict:
    return json.loads((Path(snapdir) / "feed_plan.json").read_text())["plan"]


def _json_safe(o):
    if isinstance(o, complex):
        return [o.real, o.imag]
    raise TypeError(type(o))


def cmd_scan_reduce(a):
    plan = _load_plan(a.snapdir)
    results, problems = reduce_scan(Path(a.corners), plan, a.nf_npts)
    probe = read_cmim_probe(Path(a.corners), plan)
    for g, p in probe.items():
        if not p["within_tol"]:
            problems.append(f"cmim probe {g}: realised C {p['c_pf']:.4f} pF is {p['err_frac'] * 100:+.2f} % from the tuned "
                            f"{p['target_pf']:.4f} pF (> {CMIM_SIZE_TOL * 100:g} %)")
    best = select_best(results, plan)
    with open(a.csv, "w", newline="") as fh:
        w = csv.writer(fh, lineterminator="\n")
        w.writerow(SCAN_COLS)
        for name, r in results.items():
            w.writerow(scan_row(name, r["summary"], feed_area_um2(name, plan)))
    with open(a.band_csv, "w", newline="") as fh:
        w = csv.writer(fh, lineterminator="\n")
        w.writerow(BAND_COLS)
        for name, r in results.items():
            w.writerows(band_rows(name, r["band"]))
    summary = {"best_valid_feed": best, "problems": problems,
               "variants": {n: r["summary"] for n, r in results.items()}, "cmim_probe": probe}
    _wr(Path(a.corners) / "scan_summary.json", json.dumps(summary, indent=2, default=_json_safe) + "\n")
    _wr(a.markdown, scan_markdown(results, plan, probe, best, problems))
    print(f"scan-reduce: best valid feed = {best}; {len(problems)} problem(s)")
    return 1 if problems else 0


def _fz(z):
    return f"{z[0]:.2f}{z[1]:+.2f}j"


def scan_markdown(results, plan, probe, best, problems) -> str:
    L = ["#### Tuning table (measured EM series branch at 2.44175 GHz; nominal cell)", "",
         "| Geometry | L (nH) | Q | Rp alone (Ohm) | SRF alone (GHz) | Tuning C (pF) | cmim side (um) | outer D (um) | Tank resonances with tuning C (GHz: kind, |Z| Ohm) |",
         "|---|---|---|---|---|---|---|---|---|"]
    for g, r in plan["geoms"].items():
        res = "; ".join(f"{x['f_hz'] / 1e9:.3f}: {x['kind']}, {x['z_mag_ohm']:.0f}" for x in r["tank_resonances"]) or "-"
        c = f"{r['c_tune_pf']:.4f}" if r.get("c_tune_pf") is not None else "n/a"
        srf = f"{r['srf_hz'] / 1e9:.2f}" if r.get("srf_hz") else "none <= 30 GHz"
        L.append(f"| {g} | {r['l_nh']:.3f} | {r['q']:.2f} | {r['rp_alone_ohm']:.0f} | {srf} | {c} | "
                 f"{('%.2f' % r['cmim_side_um']) if 'cmim_side_um' in r else '-'} | {r['outer_d_um']:.1f} | {res} |")
    L += ["", "#### PDK cap_cmim one-port probe (measured at 2.44175 GHz)", "",
          "| Geometry | side (um) | realised C (pF) | target C (pF) | error | ESR (Ohm) | within tol |", "|---|---|---|---|---|---|---|"]
    for g, p in probe.items():
        L.append(f"| {g} | {p['side_um']:.3f} | {p['c_pf']:.4f} | {p['target_pf']:.4f} | {p['err_frac'] * 100:+.3f} % | "
                 f"{p['esr_ohm']:.4f} | {'yes' if p['within_tol'] else 'NO'} |")
    L += ["", "#### DC audit and validity (nominal cell; bias NOT retuned)", "",
          "| Variant | Role | IC1 (mA) | IB1 (uA) | IDD (mA) | Pdc (mW) | VBE1 (V) | VCE1 / VCE2 (V) | VBC1 / VBC2 (V) | R3b+feed drop (mV) | dIC1 vs committed | Flags | OP convergence |",
          "|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    base = results["committed"]["summary"]["audit"]
    for n, r in results.items():
        s = r["summary"]
        a = s["audit"]
        L.append(f"| {n} | {VARIANTS[n]['role']} | {a['ic1'] * 1e3:.5f} | {a['ib1'] * 1e6:.3f} | {a['idd'] * 1e3:.4f} | "
                 f"{a['pdc'] * 1e3:.4f} | {a['vbe1']:.4f} | {a['vce1']:.3f} / {a['vce2']:.3f} | {a['vbc1']:.3f} / {a['vbc2']:.3f} | "
                 f"{a['vfeed_drop'] * 1e3:.3f} | {(a['ic1'] / base['ic1'] - 1) * 100:+.3f} % | "
                 f"{'; '.join(s['dc_flags']) or 'none'} | {'normal' if s['convergence']['normal'] else 'FALLBACK'} |")
    L += ["", "#### Noise, input and optimum-source impedance at 2.44175 GHz (T0 = 290 K; 50-ohm NF is NOT NFmin)", "",
          "| Variant | NFmin@290 mid / worst (dB) | NF 50-ohm@290 (.noise) mid / worst (dB) | NF 50-ohm@290 (sp, re-ref.) mid (dB) | Zin (Ohm) | Zopt (Ohm) | Rn (Ohm) | S11 / S22 / S21 mid (dB) |",
          "|---|---|---|---|---|---|---|---|"]
    for n, r in results.items():
        s = r["summary"]
        L.append(f"| {n} | {s['nfmin290_mid_db']:.3f} / {s['nfmin290_worst_db']:.3f} | {s['nf50_290_noise_mid_db']:.3f} / "
                 f"{s['nf50_290_noise_worst_db']:.3f} | {s['nf50_290_sp_mid_db']:.3f} | {_fz(s['zin_mid'])} | {_fz(s['zopt_mid'])} | "
                 f"{s['rn_mid']:.2f} | {s['s11_db_mid']:.2f} / {s['s22_db_mid']:.2f} / {s['s21_db_mid']:.2f} |")
    L += ["", "#### Broadband stability, 10 MHz - 30 GHz (140 points; table resolution of mu 1e-9; k is ill-conditioned for |S12| ~ -95 dB)", "",
          "| Variant | mu min (f) | mu <= 1 pts / resolved mu < 1 / unresolved | k min (f) | k < 1 pts (f range, GHz) | |Delta| min..max | max |S11| (f GHz) | max |S22| (f GHz) |",
          "|---|---|---|---|---|---|---|---|"]
    for n, r in results.items():
        s = r["summary"]
        kr = (f"{s['k_lt1_f_lo_hz'] / 1e9:.3g}-{s['k_lt1_f_hi_hz'] / 1e9:.3g}" if s["k_bb_n_lt1"] else "-")
        L.append(f"| {n} | {s['mu_bb_min']:.10f} ({s['mu_bb_f_min_hz'] / 1e9:.3g} GHz) | {s['mu_bb_n_lt1']} / "
                 f"{s['mu_bb_n_resolved_lt1']} / {s['mu_bb_n_unresolved']} | {s['k_bb_min']:.4g} ({s['k_bb_f_min_hz'] / 1e9:.3g}) | "
                 f"{s['k_bb_n_lt1']} ({kr}) | {s['delta_bb_min']:.4g}..{s['delta_bb_max']:.4g} | "
                 f"{s['s11_mag_bb_max']:.4f} ({s['s11_mag_bb_f_hz'] / 1e9:.3g}) | {s['s22_mag_bb_max']:.4f} ({s['s22_mag_bb_f_hz'] / 1e9:.3g}) |")
    L += ["", f"**Best DC-valid finite feed (rule declared before the run): `{best}`.**", ""]
    if problems:
        L += ["**Problems / flags:**", ""] + [f"- {p}" for p in problems] + [""]
    return "\n".join(L) + "\n"


def cmd_match_gen(a):
    summ = json.loads((Path(a.corners) / "scan_summary.json").read_text())
    best = summ["best_valid_feed"]
    plan = _load_plan(a.snapdir)
    names = ["committed", "ideal_choke"] + ([best] if best else [])
    for n in names:
        sub = Path(a.outdir) / "charset" / n
        sub.mkdir(parents=True, exist_ok=True)
        b = SimpleNamespace(models_lib=a.models_lib, mos_lib=a.mos_lib, osdi_dir=a.osdi_dir, outdir=str(sub),
                            deckdir=a.snapdir, relative_em=False)
        text = apply_feed(ms.char_deck(b), n, plan, a.cap_lib)
        assert_feed_dc_path(text)
        _wr(Path(a.snapdir) / f"char_{n}.spice", text)
    print(f"match-gen: characterization decks for {names}")


def cmd_match_solve(a):
    summ = json.loads((Path(a.corners) / "scan_summary.json").read_text())
    best = summ["best_valid_feed"]
    plan = _load_plan(a.snapdir)
    names = ["committed", "ideal_choke"] + ([best] if best else [])
    entries = []
    for n in names:
        data = ms.load_char(Path(a.outdir) / "charset" / n, require_feed=False)
        base, _ = ms.synthesize(data)
        e = dict(next(x for x in base if x["candidate"] == MATCH_CANDIDATE and x["qcase"] == SOURCE_Q_CASE))
        if e.get("infeasible"):
            raise SystemExit(f"match-solve: {n}: {MATCH_CANDIDATE}:{SOURCE_Q_CASE} infeasible ({e['infeasible']})")
        e["xout_rdc_ohm"] = XOUT_RDC
        e["feed_variant"] = n
        e["stem"] = f"match_{n}_{MATCH_CANDIDATE}_{SOURCE_Q_CASE}"
        e["char_zin_mid"] = [data["cases"]["q10"][ms.MID]["zin"].real, data["cases"]["q10"][ms.MID]["zin"].imag]
        e["char_nfmin290_mid_db"] = ms.nf_reref(data["cases"]["q10"][ms.MID]["nfmin_t_db"], ms.T_ANALYSIS)
        text = apply_feed(ms.verify_deck(a, e, e["stem"]), n, plan, a.cap_lib)
        assert_feed_dc_path(text)
        _wr(Path(a.snapdir) / f"{e['stem']}.spice", text)
        entries.append(e)
    doc = {"generator": "sim/lna-matching-feasibility/feed_study.py match-solve",
           "design_netlist_sha256": ms.sha256(ms.DESIGN_NETLIST), "em_model_sha256": ms.sha256(ms.EM_MODEL),
           "nf_npts": a.nf_npts, "xout_rdc_ohm": XOUT_RDC, "best_valid_feed": best, "candidates": entries}
    _wr(Path(a.snapdir) / "match_plan.json", json.dumps(doc, indent=2, default=str) + "\n")
    print(f"match-solve: {len(entries)} verification decks + match_plan.json")


MATCH_COLS = ["feed_variant", "role", "input_values_nh_pf", "nf290_worst_db", "nf290_mid_db", "nfmin290_dut_mid_db",
              "s11_worst_db", "s22_worst_db", "s21_min_db", "s21_max_db", "mu_bb_min", "mu_bb_f_min_hz",
              "k_bb_min", "s11_mag_bb_max", "s22_mag_bb_max", "ic1_ma", "op_convergence_normal",
              "gt_minus_s21_db_mid", "predicted_nf290_mid_db"]


def cmd_match_reduce(a):
    snap = Path(a.snapdir)
    doc = json.loads((snap / "match_plan.json").read_text())
    summ = json.loads((Path(a.corners) / "scan_summary.json").read_text())
    plan = _load_plan(a.snapdir)
    rows, mets, problems = [], {}, []
    for e in doc["candidates"]:
        n = e["feed_variant"]
        r = ms.reduce_one(Path(a.corners), e["stem"], doc["nf_npts"])
        m = r["metrics"]
        m["convergence"] = ms.classify_convergence(Path(a.corners) / f"{e['stem']}.log")
        if not m["convergence"]["normal"]:
            problems.append(f"{n}: verification OP convergence fallback/warning")
        if abs(m["gt_minus_s21_db_mid"]) > 1e-3:
            problems.append(f"{n}: transducer-gain cross-check off by {m['gt_minus_s21_db_mid']:.4g} dB")
        mets[n] = m
        pred = e["predicted"][ms.MID]["nf290_db"]
        rows.append([n, VARIANTS[n]["role"], "/".join(f"{x:.6g}" for x in e["input_values"]),
                     f"{m['nf290_db_worst']:.4f}", f"{m['nf290_db_mid']:.4f}",
                     f"{e['char_nfmin290_mid_db']:.4f}", f"{m['s11_db_worst']:.3f}", f"{m['s22_db_worst']:.3f}",
                     f"{m['s21_db_min']:.3f}", f"{m['s21_db_max']:.3f}", f"{m['mu_bb_min']:.10f}",
                     f"{m['mu_bb_f_min_hz']:.6g}", f"{m['k_bb_min']:.4g}", f"{m['s11_mag_bb_max']:.4f}",
                     f"{m['s22_mag_bb_max']:.4f}", f"{m['ic1'] * 1e3:.5f}",
                     "yes" if m["convergence"]["normal"] else "NO", f"{m['gt_minus_s21_db_mid']:.2e}",
                     f"{pred:.4f}"])
    with open(a.csv, "w", newline="") as fh:
        w = csv.writer(fh, lineterminator="\n")
        w.writerow(MATCH_COLS)
        w.writerows(rows)
    best = doc["best_valid_feed"]
    rec = recommend(summ["variants"][best] if best else None, mets.get(best) if best else None)
    bound = recommend(summ["variants"]["ideal_choke"], mets["ideal_choke"])
    _wr(Path(a.corners) / "recommendation.json", json.dumps(
        {"best_valid_feed": best, "recommendation": rec, "ideal_bound_gates": bound}, indent=2) + "\n")
    _wr(a.markdown, match_markdown(doc, mets, summ, plan, rec, bound, problems))
    print(f"match-reduce: {rec['verdict']} (binding: {rec['binding']}); {len(problems)} problem(s)")
    return 1 if problems else 0


def match_markdown(doc, mets, summ, plan, rec, bound, problems) -> str:
    L = ["#### Verified matched amplifier (existing noise-weighted `lp_noise` input match, Q = 10, re-synthesized per feed; "
         f"DC reference Rxoutdc = {doc['xout_rdc_ohm']:g} Ohm)", "",
         "| Feed | Input L / C (H, F) | NF290 worst / mid (dB) | DUT NFmin@290 mid (dB) | Predicted NF290 mid (dB) | S11 worst (dB) | S22 worst (dB) | |S21| min..max (dB) | mu bb min (f) | k bb min | max |S11| / |S22| bb | IC1 (mA) | OP convergence |",
         "|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for e in doc["candidates"]:
        n = e["feed_variant"]
        m = mets[n]
        L.append(f"| {n} ({VARIANTS[n]['role']}) | {e['input_values'][0]:.4g} / {e['input_values'][1]:.4g} | "
                 f"{m['nf290_db_worst']:.3f} / {m['nf290_db_mid']:.3f} | {e['char_nfmin290_mid_db']:.3f} | "
                 f"{e['predicted'][ms.MID]['nf290_db']:.3f} | {m['s11_db_worst']:.2f} | {m['s22_db_worst']:.2f} | "
                 f"{m['s21_db_min']:.2f}..{m['s21_db_max']:.2f} | {m['mu_bb_min']:.10f} ({m['mu_bb_f_min_hz'] / 1e9:.3g} GHz) | "
                 f"{m['k_bb_min']:.4g} | {m['s11_mag_bb_max']:.4f} / {m['s22_mag_bb_max']:.4f} | {m['ic1'] * 1e3:.5f} | "
                 f"{'normal' if m['convergence']['normal'] else 'FALLBACK'} |")
    L += ["", "#### Go / no-go recommendation for a subsequent full-PVT campaign", ""]
    best = doc["best_valid_feed"]
    L.append(f"- Best DC-valid finite feed: `{best}`.")
    L.append(f"- Policy limit (declared): matched NF290 worst-in-band <= {ms.ROW_NF_DB:g} - {PVT_NF_MARGIN_DB:g} = {rec['limit_db']:.2f} dB, "
             "plus S11/S22 < -10 dB, |S21| > 15 dB, no resolved mu < 1, DC-valid, convergent.")
    L.append(f"- **Verdict: {rec['verdict']}**" + (f"; binding constraint: `{rec['binding']}`; failing gates: {', '.join(rec['failing'])}." if rec["failing"] else "."))
    if "nf290_worst_db" in rec:
        L.append(f"- Verified matched NF290 worst-in-band {rec['nf290_worst_db']:.3f} dB; DUT NFmin@290 worst-in-band "
                 f"{rec['nfmin290_worst_db']:.3f} dB; remaining budget against the 1.5 dB row {rec['nf_budget_left_db']:+.3f} dB.")
    L.append(f"- Ideal-choke diagnostic bound (same gates, not a design): verdict {bound['verdict']}, failing {bound['failing'] or 'none'}"
             + (f", matched NF290 worst {bound['nf290_worst_db']:.3f} dB." if "nf290_worst_db" in bound else "."))
    if best:
        a = VARIANTS[best]
        L.append(f"- Feed area (lower bound, bounding boxes only): {feed_area_um2(best, plan):.0f} um^2.")
    if problems:
        L += ["", "**Problems / flags:**", ""] + [f"- {p}" for p in problems]
    return "\n".join(L) + "\n"


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("declare")
    t = sub.add_parser("tune-gen")
    t.add_argument("--snapdir", required=True)
    t.add_argument("--outdir", required=True)
    p = sub.add_parser("plan")
    add_pdk_args(p)
    p.add_argument("--snapdir", required=True)
    p.add_argument("--outdir", required=True)
    p.add_argument("--nf-npts", type=int, default=2 * (ms.N_BAND - 1) + 1)
    s = sub.add_parser("scan-reduce")
    s.add_argument("--snapdir", required=True)
    s.add_argument("--corners", required=True)
    s.add_argument("--csv", required=True)
    s.add_argument("--band-csv", required=True)
    s.add_argument("--markdown", required=True)
    s.add_argument("--nf-npts", type=int, default=2 * (ms.N_BAND - 1) + 1)
    g = sub.add_parser("match-gen")
    add_pdk_args(g)
    g.add_argument("--snapdir", required=True)
    g.add_argument("--outdir", required=True)
    g.add_argument("--corners", required=True)
    m = sub.add_parser("match-solve")
    add_pdk_args(m)
    m.add_argument("--snapdir", required=True)
    m.add_argument("--outdir", required=True)
    m.add_argument("--corners", required=True)
    m.add_argument("--nf-npts", type=int, default=ms.N_NF_DEFAULT)
    r = sub.add_parser("match-reduce")
    r.add_argument("--snapdir", required=True)
    r.add_argument("--corners", required=True)
    r.add_argument("--csv", required=True)
    r.add_argument("--markdown", required=True)
    a = ap.parse_args(argv)
    if a.cmd == "declare":
        sys.stdout.write(declaration_text())
        return 0
    return {"tune-gen": cmd_tune_gen, "plan": cmd_plan, "scan-reduce": cmd_scan_reduce,
            "match-gen": cmd_match_gen, "match-solve": cmd_match_solve,
            "match-reduce": cmd_match_reduce}[a.cmd](a) or 0


if __name__ == "__main__":
    sys.exit(main())
