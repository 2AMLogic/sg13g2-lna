#!/usr/bin/env python3
"""Nominal-cell matching-network feasibility study for design/lna.sch (issue #186).

Companion to run_matching_study.sh. Subcommands:

  gen-char   write the single characterization deck (nominal cell only)
  solve      read the characterization data, synthesize every candidate
             matching network for every Q case, write candidates.json and
             one verification deck per (candidate, Q case)
  sensitivity  compare DC-reference decks (--xout-rdc) with the historical
             floating-xout baseline (issue #190)
  reduce     read the verification decks' wrdata/logs, compute the per-
             candidate metrics, rank the topologies, write the record CSVs
             and a markdown fragment for the record

Method (stated in full in README.md):

* The DUT is treated through the two quantities a matching network sees: its
  input impedance Zin(f) at `rfin` (Cin, the base-bias resistor R3b and Q1
  included) and its collector-node admittance Ydev(f) (Lc removed, Cout
  de-embedded). Both come from ONE ngspice run at the nominal cell. The
  cascode's reverse isolation (|S12| ~ -95 dB) makes the unilateral split
  exact for practical purposes; the verification decks are fully bilateral.
* Input: a two-element L-section, series element on the 50 Ohm side and
  shunt element at `rfin`. Closed-form lossless values (Pozar's L-section
  equations) start a damped Newton refinement that includes the inductor's
  series loss resistor R = w_mid*L/Q. Two targets: a conjugate power match
  (Zs = Zin*), and a noise-weighted compromise (the source impedance with
  the lowest two-port F that still keeps the band-centre mismatch at or
  below MISMATCH_TARGET_DB).
* Output: the cascode's collector tank (Lc, shunt to the AC-grounded VDD)
  plus a series C to the 50 Ohm port (O1, Lc free), or -- when Lc is a fixed
  EM-extracted geometry -- a shunt C at `rfout` plus a series C (O2).
* Every candidate is then re-simulated (sp, broadband stability, .noise at
  T0 = 290 K) with the real DUT; the solver's own predictions are recorded
  next to the simulated numbers as a cross-check, never in place of them.

Stdlib only (cmath/math/json/csv), so the unit tests run PDK-free in CI.
"""
from __future__ import annotations

import argparse
import cmath
import csv
import hashlib
import json
import math
import os
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
DESIGN_NETLIST = REPO / "design" / "netlist" / "lna.spice"
EM_MODEL = REPO / "sim" / "models" / "sg13g2_inductor_em.spice"
TB_CHAR = HERE / "testbench" / "tb_match_char.spice.tmpl"
TB_VERIFY = HERE / "testbench" / "tb_match_verify.spice.tmpl"
TB_FEED = HERE / "testbench" / "tb_match_feedprobe.spice.tmpl"

# --- bench constants (same grid as sim/lna-characterization) ---------------
Z0 = 50.0
F_LO, F_HI = 2.4e9, 2.4835e9
N_BAND = 11                       # index 5 is exactly F_MID
F_MID = 2.44175e9
MID = (N_BAND - 1) // 2
F_STAB_LO, F_STAB_HI, N_STAB_DEC = 1e7, 3e10, 40
N_NF_DEFAULT = 21                 # dense 290 K NF grid (odd, >= 11)
T0 = 290.0
T_ANALYSIS = 300.15               # 27 C: the nominal cell's analysis temperature
COUT = 100e-12                    # committed series DC block at the output
LE_NH = 1.0                       # committed degeneration inductor
LC_NH = 5.0                       # committed collector inductor
CHOKE = 1e-6                      # ideal RF choke used to expose Ydev
R_IDEAL_PLACEHOLDER = 1e12        # Le parallel loss resistor standing for "ideal" (open) in the char deck
MISMATCH_TARGET_DB = -12.0        # noise-compromise candidate: |S11| at f_mid (2 dB inside the -10 dB row)

# Ratified rows (spec/target-spec.md), restated only to classify nominal-cell
# numbers; nothing here is a conformance verdict.
ROW_S11_DB = -10.0
ROW_S22_DB = -10.0
ROW_S21_DB = 15.0
ROW_NF_DB = 1.5
ROW_MU = 1.0

# EM-extracted geometries of sim/models/sg13g2_inductor_em.spice (the model
# header's "Extracted" line). Outer diameter is the area proxy.
EM_GEOMS = {
    "em1": {"nr_r": 1, "w_um": 8.22, "s_um": 3.29, "d_um": 47.65},
    "em4": {"nr_r": 4, "w_um": 8.22, "s_um": 3.74, "d_um": 141.975},
    "em5": {"nr_r": 5, "w_um": 6.10, "s_um": 3.29, "d_um": 110.11},
}
EM_LC_PREFERENCE = ["em5", "em4", "em1"]   # issue #186: the 5-turn model for Lc first

# Q cases. q = None means ideal (infinite Q). lc_em: Lc is a fixed EM geometry.
QCASES = {
    "ideal": {"q": None, "lc_em": False,
              "desc": "all inductors ideal (infinite Q)"},
    "q20": {"q": 20.0, "lc_em": False,
            "desc": "Le (parallel R), Lc and the input matching inductor (series R) at Q = 20 at 2.44175 GHz"},
    "q10": {"q": 10.0, "lc_em": False,
            "desc": "Le (parallel R), Lc and the input matching inductor (series R) at Q = 10 at 2.44175 GHz"},
    "em": {"q": 10.0, "lc_em": True,
           "desc": "Lc = EM-extracted spiral (fixed geometry, sim/models/sg13g2_inductor_em.spice); "
                   "Le and the input matching inductor at Q = 10"},
}
CHAR_CASES = {"ideal": None, "q20": 20.0, "q10": 10.0}   # Le-loss cases measured in the char deck

# Candidate topologies.
CANDIDATES = {
    "lp_power": {"input": "lowpass", "target": "power",
                 "desc": "input: series Lb + shunt Cp at rfin (low-pass L), conjugate power match; "
                         "output: Lc tank + shunt C at rfout + series C"},
    "hp_power": {"input": "highpass", "target": "power",
                 "desc": "input: series C + shunt Lp at rfin (high-pass L), conjugate power match; "
                         "output: Lc tank + shunt C at rfout + series C"},
    "lp_noise": {"input": "lowpass", "target": "noise",
                 "desc": "input: series Lb + shunt Cp at rfin (low-pass L), lowest-F source impedance "
                         f"with |S11(f_mid)| <= {MISMATCH_TARGET_DB:g} dB; output: Lc tank + shunt C at rfout + series C"},
}
LE_SWEEP_NH = [0.1, 0.2, 0.3, 0.5, 0.7, 1.0, 1.5, 2.0, 3.0]

LE_LINE = "Le e1 vss 1n m=1"
LC_LINE = "Lc vdd outn 5n m=1"
R3B_LINE = "R3b bref b1 330 m=1"
FEED_CHOKE = 1e-6                 # what-if only: ideal choke in series with R3b
W_MID = 2 * math.pi * F_MID


# ===========================================================================
# Pure RF helpers (unit-tested)
# ===========================================================================

def band_freqs(n: int = N_BAND) -> list[float]:
    return [F_LO + (F_HI - F_LO) * i / (n - 1) for i in range(n)]


def check_nf_npts(n: int) -> int:
    if not isinstance(n, int) or n < N_BAND or n % 2 == 0:
        raise ValueError(f"nf-npts must be an odd integer >= {N_BAND} (got {n!r})")
    return n


def z_from_s(s: complex, z0: float = Z0) -> complex:
    return z0 * (1 + s) / (1 - s)


def gamma(z: complex, z0: float = Z0) -> complex:
    return (z - z0) / (z + z0)


def db20(x: float) -> float:
    """20*log10(x), floored at -300 dB so an exact (lossless, closed-form)
    match does not raise on log10(0)."""
    return 20 * math.log10(max(x, 1e-15))


def q_series_r(l_h: float, q, w: float = W_MID) -> float:
    """Series loss resistor giving Q = w*L/R at the band centre; 0 when ideal."""
    if q is None:
        return 0.0
    if q <= 0:
        raise ValueError("Q must be positive")
    return w * l_h / q


def q_parallel_r(l_h: float, q, w: float = W_MID) -> float:
    """Parallel loss resistor giving Q = R/(w*L) at the band centre. Used for
    Le only: it carries no DC current, so the loss does not also shift the
    mirror-set emitter bias (a series R does -- see README)."""
    if q is None or q <= 0:
        raise ValueError("Q must be positive")
    return q * w * l_h


def z_ind(l_h: float, r: float, f: float) -> complex:
    return complex(r, 2 * math.pi * f * l_h)


def z_cap(c_f: float, f: float) -> complex:
    return complex(0.0, -1.0 / (2 * math.pi * f * c_f))


def par(za: complex, zb: complex) -> complex:
    return za * zb / (za + zb)


def stability(s11: complex, s21: complex, s12: complex, s22: complex):
    """(mu, k, |Delta|): Edwards-Sinsky mu, Rollett k, determinant magnitude."""
    dlt = s11 * s22 - s12 * s21
    mu = (1 - abs(s11) ** 2) / (abs(s22 - s11.conjugate() * dlt) + abs(s12 * s21))
    den = 2 * abs(s12 * s21)
    k = (1 - abs(s11) ** 2 - abs(s22) ** 2 + abs(dlt) ** 2) / den if den > 0 else math.inf
    return mu, k, abs(dlt)


def nf_reref(nf_db: float, t_ref_k: float, t_new_k: float = T0) -> float:
    """Re-reference a noise figure from source temperature t_ref to t_new
    (the equivalent noise temperature (F-1)*T is invariant)."""
    f = 10 ** (nf_db / 10)
    return 10 * math.log10(1 + (f - 1) * t_ref_k / t_new_k)


def two_port_f(zs: complex, fmin: float, rn: float, gopt: complex, z0: float = Z0) -> float:
    """Linear noise factor F = Fmin + Rn/Gs*|Ys - Yopt|^2 (Yopt from Gamma_opt)."""
    ys = 1 / zs
    yopt = (1 - gopt) / (1 + gopt) / z0
    return fmin + rn / ys.real * abs(ys - yopt) ** 2


def lsection_closed_form(zl: complex, z0: float = Z0):
    """Lossless L-section matching load zl to z0, series element on the z0
    side and shunt element across the load (Pozar 5.1, R_L > Z0 form).

    Returns a list of (x_series_ohm, b_shunt_siemens) solutions; each
    satisfies j*x + 1/(j*b + 1/zl) == z0. Empty when this orientation
    cannot match zl.
    """
    rl, xl = zl.real, zl.imag
    if rl <= 0:
        return []
    arg = rl * rl + xl * xl - z0 * rl
    if arg < 0:
        return []
    out = []
    for sgn in (+1, -1):
        b = (xl + sgn * math.sqrt(rl / z0) * math.sqrt(arg)) / (rl * rl + xl * xl)
        if b == 0:
            continue
        x = 1 / b + xl * z0 / rl - z0 / (b * rl)
        out.append((x, b))
    return out


def reactances_to_elements(x: float, b: float, w: float = W_MID):
    """Map (series reactance, shunt susceptance) to (topology, series value, shunt value).

    lowpass  = series L (H) + shunt C (F); highpass = series C (F) + shunt L (H).
    """
    if x > 0 and b > 0:
        return "lowpass", x / w, b / w
    if x < 0 and b < 0:
        return "highpass", -1 / (w * x), -1 / (w * b)
    return "mixed", x, b


# --- input network ----------------------------------------------------------
# Generic two-element input network: source (50 Ohm) -> series Z1 -> node
# rfin <- shunt Z2 to ground -> DUT. Values: (series, shunt) element values.

def input_z12(topology: str, vals, q, f: float):
    a, b = vals
    if topology == "lowpass":          # series Lb (+loss), shunt Cp
        return z_ind(a, q_series_r(a, q), f), z_cap(b, f)
    if topology == "highpass":         # series Cs, shunt Lp (+loss)
        return z_cap(a, f), z_ind(b, q_series_r(b, q), f)
    raise ValueError(f"unknown input topology {topology!r}")


def input_zlook(topology, vals, q, f, zin_dut, z0=Z0):
    """Impedance seen by the 50 Ohm port looking into network + DUT."""
    z1, z2 = input_z12(topology, vals, q, f)
    return z1 + par(z2, zin_dut)


def input_zs(topology, vals, q, f, z0=Z0):
    """Source impedance the network presents to the DUT (50 Ohm behind it)."""
    z1, z2 = input_z12(topology, vals, q, f)
    return par(z2, z0 + z1)


def input_avail_gain(topology, vals, q, f, z0=Z0):
    """Available power gain of the (lossy) input network from a z0 source."""
    z1, z2 = input_z12(topology, vals, q, f)
    vth = z2 / (z0 + z1 + z2)          # per volt of source EMF
    zs = par(z2, z0 + z1)
    return (abs(vth) ** 2 / (4 * zs.real)) / (1 / (4 * z0))


def predicted_nf290(topology, vals, q, f, noise, t_phys=T_ANALYSIS, z0=Z0):
    """Friis cascade of the lossy input network (thermal, at t_phys) and the
    DUT two-port (noise parameters referenced to the analysis temperature),
    expressed at T0 = 290 K. Prediction only -- the .noise run is the number."""
    zs = input_zs(topology, vals, q, f, z0)
    f_dut_t = two_port_f(zs, noise["fmin"], noise["rn"], noise["gopt"], z0)
    te_dut = (f_dut_t - 1) * T_ANALYSIS
    ga = input_avail_gain(topology, vals, q, f, z0)
    te_net = (1 / ga - 1) * t_phys
    te = te_net + te_dut / ga
    return 10 * math.log10(1 + te / T0)


def newton2(fun, x0, tol=1e-10, maxit=200):
    """Solve complex fun(v1, v2) = 0 for two positive reals (log-space,
    damped Newton, numerical Jacobian). Raises RuntimeError on failure."""
    u = [math.log(x0[0]), math.log(x0[1])]

    def res(uu):
        r = fun(math.exp(uu[0]), math.exp(uu[1]))
        return [r.real, r.imag]

    r = res(u)
    for _ in range(maxit):
        nr = math.hypot(*r)
        if nr < tol:
            return math.exp(u[0]), math.exp(u[1])
        h = 1e-7
        j = [[0.0, 0.0], [0.0, 0.0]]
        for c in range(2):
            up = list(u)
            up[c] += h
            rp = res(up)
            j[0][c] = (rp[0] - r[0]) / h
            j[1][c] = (rp[1] - r[1]) / h
        det = j[0][0] * j[1][1] - j[0][1] * j[1][0]
        if det == 0:
            raise RuntimeError("newton2: singular Jacobian")
        du = [(-r[0] * j[1][1] + r[1] * j[0][1]) / det,
              (-j[0][0] * r[1] + j[1][0] * r[0]) / det]
        lam = 1.0
        while lam > 1e-6:
            un = [u[0] + lam * du[0], u[1] + lam * du[1]]
            rn = res(un)
            if math.hypot(*rn) < nr:
                u, r = un, rn
                break
            lam /= 2
        else:
            raise RuntimeError("newton2: no descent step")
    raise RuntimeError("newton2: no convergence")


def closed_form_start(topology: str, zl: complex, f: float = F_MID, z0: float = Z0):
    """Lossless L-section element values (series, shunt) of `topology`
    matching load zl to z0, or ValueError."""
    for x, b in lsection_closed_form(zl, z0):
        topo, a, c = reactances_to_elements(x, b, 2 * math.pi * f)
        if topo == topology:
            return (a, c)
    raise ValueError(f"no lossless {topology} L-section matches {zl:.4g} to {z0:g} Ohm")


def solve_input(topology: str, zs_target: complex, q, f: float = F_MID, z0: float = Z0):
    """Element values (series, shunt) whose network presents zs_target to the
    DUT. Closed-form lossless start, then Newton with the inductor's loss."""
    start = closed_form_start(topology, zs_target.conjugate(), f, z0)
    if q is None:
        vals = start
    else:
        vals = newton2(lambda a, c: input_zs(topology, (a, c), q, f, z0) - zs_target, start)
    return {"closed_form": start, "values": vals}


def solve_input_power(topology: str, zin: complex, q, f: float = F_MID, z0: float = Z0):
    """Port power match: element values with input_zlook(...) == z0 at f,
    the inductor's loss included (closed-form lossless start, then Newton)."""
    start = closed_form_start(topology, zin, f, z0)
    if q is None:
        vals = start
    else:
        vals = newton2(lambda a, c: input_zlook(topology, (a, c), q, f, zin, z0) - z0, start)
    return {"closed_form": start, "values": vals}


def solve_input_noise(topology: str, zin: complex, noise, q, f: float = F_MID,
                      mismatch_db: float = MISMATCH_TARGET_DB, z0: float = Z0,
                      span: float = 3.0, n: int = 161, refine: int = 3):
    """Noise-weighted compromise: element values minimizing the predicted NF
    at T0 = 290 K (lossy network + DUT noise parameters) subject to the port
    mismatch |S11(f)| <= 10^(mismatch_db/20), the inductor's loss included.

    Start: the lossless boundary optimum (noise_compromise_zs). Search: a
    deterministic log-spaced grid of (series, shunt) values within a factor
    `span` of the start, then `refine` successively finer grids around the
    best point. Returns {'closed_form', 'values', 'zs_target'}.
    """
    zs0, _, _ = noise_compromise_zs(zin, noise, mismatch_db, z0=z0)
    start = closed_form_start(topology, zs0.conjugate(), f, z0)
    g = 10 ** (mismatch_db / 20)

    def score(vals):
        if abs(gamma(input_zlook(topology, vals, q, f, zin, z0), z0)) > g:
            return math.inf
        return predicted_nf290(topology, vals, q, f, noise, z0=z0)

    center = [math.log(start[0]), math.log(start[1])]
    half = math.log(span)
    best = (math.inf, start)
    for _ in range(refine + 1):
        for i in range(n):
            for j in range(n):
                u = (center[0] - half + 2 * half * i / (n - 1), center[1] - half + 2 * half * j / (n - 1))
                vals = (math.exp(u[0]), math.exp(u[1]))
                s = score(vals)
                if s < best[0]:
                    best = (s, vals)
        if not math.isfinite(best[0]):
            raise ValueError("solve_input_noise: no grid point meets the mismatch bound")
        center = [math.log(best[1][0]), math.log(best[1][1])]
        half = 4 * half / (n - 1)
    return {"closed_form": start, "values": best[1], "zs_target": zs0}


def noise_compromise_zs(zin: complex, noise, mismatch_db: float = MISMATCH_TARGET_DB,
                        n: int = 7200, z0: float = Z0):
    """Lowest-F source impedance with |Gamma_mis| = |(Zs - Zin*)/(Zs + Zin)|
    <= 10^(mismatch_db/20). Returns (zs, F_linear, on_boundary)."""
    g = 10 ** (mismatch_db / 20)
    zopt = z0 * (1 + noise["gopt"]) / (1 - noise["gopt"])
    if abs((zopt - zin.conjugate()) / (zopt + zin)) <= g:
        return zopt, noise["fmin"], False
    best = None
    for i in range(n):
        gm = g * cmath.exp(1j * 2 * math.pi * i / n)
        zs = (zin.conjugate() + gm * zin) / (1 - gm)
        if zs.real <= 0:
            continue
        fl = two_port_f(zs, noise["fmin"], noise["rn"], noise["gopt"], z0)
        if best is None or fl < best[1]:
            best = (zs, fl)
    if best is None:
        raise ValueError("noise_compromise_zs: empty constraint boundary")
    return best[0], best[1], True


# --- output network ---------------------------------------------------------
# DUT collector node (Ydev) || Lc (to AC ground) -> series Cout (100 pF, in
# the DUT) -> rfout <- shunt Cp (optional, external) -> series Cs -> 50 Ohm.

def output_zlook(ydev: complex, ylc: complex, cp: float, cs: float, f: float,
                 cout: float = COUT) -> complex:
    za = 1 / (ydev + ylc) + z_cap(cout, f)
    yb = 1 / za + (complex(0, 2 * math.pi * f * cp) if cp > 0 else 0)
    return 1 / yb + z_cap(cs, f)


def ydev_from_choke_s22(s22: complex, f: float, choke: float = CHOKE, cout: float = COUT) -> complex:
    """Collector-node device admittance from S22 measured with Lc -> ideal choke."""
    z_node = z_from_s(s22) - z_cap(cout, f)
    return 1 / z_node - 1 / complex(0, 2 * math.pi * f * choke)


def solve_output_free_lc(ydev: complex, q, f: float = F_MID, cout: float = COUT,
                         lo: float = 0.05e-9, hi: float = 100e-9, n: int = 4000):
    """O1: choose Lc (with loss R = w_mid*Lc/Q) so the node impedance seen
    through Cout has Re = 50 on the inductive side; series Cs cancels the
    remaining reactance. Returns {'lc', 'cs', 'r_lc'}."""
    w = 2 * math.pi * f

    def node_after_cout(lc):
        ylc = 1 / z_ind(lc, q_series_r(lc, q), f)
        return 1 / (ydev + ylc) + z_cap(cout, f)

    def fobj(lc):
        return node_after_cout(lc).real - Z0

    grid = [lo * (hi / lo) ** (i / (n - 1)) for i in range(n)]
    root = None
    for a, b in zip(grid, grid[1:]):
        fa, fb = fobj(a), fobj(b)
        if fa == 0 or fa * fb < 0:
            # bisection
            for _ in range(200):
                m = math.sqrt(a * b)
                fm = fobj(m)
                if fa * fm <= 0:
                    b = m
                else:
                    a, fa = m, fm
            cand = math.sqrt(a * b)
            if node_after_cout(cand).imag > 0:   # inductive: a series C can cancel it
                root = cand
                break
    if root is None:
        raise ValueError("solve_output_free_lc: no inductive Re = 50 Ohm crossing")
    x = node_after_cout(root).imag
    cs = 1 / (w * x)
    return {"lc": root, "cs": cs, "r_lc": q_series_r(root, q, w)}


def solve_output_fixed_lc(ydev: complex, ylc: complex, f: float = F_MID, cout: float = COUT):
    """O2: Lc fixed (admittance ylc at f). Shunt Cp at rfout + series Cs.
    Returns {'cp', 'cs', 'feasible', 'cp_raw'}; infeasible when Cp < 0."""
    w = 2 * math.pi * f
    za = 1 / (ydev + ylc) + z_cap(cout, f)
    ya = 1 / za
    ga, ba = ya.real, ya.imag
    if not 0 < ga < 1 / Z0:
        return {"cp": None, "cs": None, "feasible": False, "cp_raw": None}
    bb = -math.sqrt(ga / Z0 - ga * ga)
    cp = (bb - ba) / w
    x = -bb / (ga * ga + bb * bb)
    cs = 1 / (w * x)
    return {"cp": max(cp, 0.0), "cs": cs, "feasible": cp >= 0, "cp_raw": cp}


# ===========================================================================
# Data I/O
# ===========================================================================

def read_wrdata(path: Path):
    """wrdata with wr_singlescale + wr_vecnames: a header of names, then rows.
    Returns (names, rows). Rejects ragged rows and non-finite values."""
    lines = [ln.split() for ln in Path(path).read_text().splitlines() if ln.strip()]
    if not lines:
        raise ValueError(f"{path}: empty")
    names = lines[0]
    rows = []
    for k, ln in enumerate(lines[1:], 2):
        if len(ln) != len(names):
            raise ValueError(f"{path}:{k}: {len(ln)} columns, header has {len(names)}")
        vals = [float(x) for x in ln]
        if not all(math.isfinite(v) for v in vals):
            raise ValueError(f"{path}:{k}: non-finite value")
        rows.append(vals)
    return names, rows


def columns(path: Path, expect_rows=None, freqs=None):
    names, rows = read_wrdata(path)
    if expect_rows is not None and len(rows) != expect_rows:
        raise ValueError(f"{path}: {len(rows)} rows, expected {expect_rows}")
    cols = {nm: [r[i] for r in rows] for i, nm in enumerate(names)}
    if freqs is not None:
        got = cols[names[0]]
        for a, b in zip(got, freqs):
            if abs(a - b) > 1e-6 * b:
                raise ValueError(f"{path}: frequency {a} != expected {b}")
    return names[0], cols


def cplx(cols, name):
    return [complex(r, i) for r, i in zip(cols[f"real({name})"], cols[f"imag({name})"])]


def sha256(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


# ===========================================================================
# Netlist generation
# ===========================================================================

def dut_base() -> str:
    text = DESIGN_NETLIST.read_text()
    out = []
    for line in text.splitlines():
        if line.startswith("**.subckt") or line.startswith("**.ends"):
            line = line[2:]
        elif line == ".end":
            continue
        out.append(line)
    body = "\n".join(out) + "\n"
    if body.count(LE_LINE) != 1 or body.count(LC_LINE) != 1:
        raise SystemExit(f"design netlist no longer carries '{LE_LINE}' / '{LC_LINE}' exactly once")
    return body


def em_instance(geom: str) -> str:
    g = EM_GEOMS[geom]
    return (f"inductor w={g['w_um']:.3f}u s={g['s_um']:.3f}u d={g['d_um']:.3f}u "
            f"nr_r={g['nr_r']} mc_rsh=1.0 mc_rsub=1.0")


def em_outer_diameter_um(geom: str) -> float:
    g = EM_GEOMS[geom]
    n = g["nr_r"]
    return g["d_um"] + 2 * (n - 1) * (g["s_um"] + g["w_um"] + 0.01) + 2 * g["w_um"]


def dut_text(le_rp, lc) -> str:
    """DUT with BENCH EDITs. le_rp: None (committed ideal Le) or a parallel
    loss resistor across Le (DC-transparent, see q_parallel_r).
    lc: ('ideal', L, R) or ('em', geom) or None (committed Lc)."""
    body = dut_base()
    if le_rp is not None:
        body = body.replace(
            LE_LINE,
            f"* BENCH EDIT: Le loss as a parallel resistor (R = {le_rp:.6g} Ohm, DC-transparent)\n"
            f"{LE_LINE}\nRle e1 vss {le_rp:.6g}")
    if lc is not None:
        if lc[0] == "ideal":
            _, l_h, r = lc
            if r > 0:
                rep = (f"* BENCH EDIT: Lc = {l_h * 1e9:.6g} nH with series loss R = {r:.6g} Ohm\n"
                       f"Lc vdd lc_x {l_h:.6g} m=1\nRlc lc_x outn {r:.6g}")
            else:
                rep = f"* BENCH EDIT: Lc = {l_h * 1e9:.6g} nH (ideal)\nLc vdd outn {l_h:.6g} m=1"
        elif lc[0] == "em":
            rep = (f"* BENCH EDIT: Lc = EM-extracted geometry {lc[1]} (sim/models/sg13g2_inductor_em.spice)\n"
                   f"XLc vdd outn vss {em_instance(lc[1])}")
        else:
            raise ValueError(lc)
        body = body.replace(LC_LINE, rep)
    return body


def render(tmpl: Path, subs: dict) -> str:
    text = tmpl.read_text()
    for k, v in subs.items():
        text = text.replace(f"@@{k}@@", str(v))
    left = re.findall(r"@@[A-Z_]+@@", text)
    if left:
        raise SystemExit(f"{tmpl.name}: unsubstituted placeholders {sorted(set(left))}")
    return text


def pdk_subs(a) -> dict:
    return {"MODELS_LIB": a.models_lib, "MOS_LIB": a.mos_lib, "OSDI_DIR": a.osdi_dir}


LESWEEP_FIELDS = ["le_nh", "zin_r", "zin_i", "s21_mag", "nfmin_t_db", "rn", "gopt_r", "gopt_i"]


def le_sweep_text(tag: str, title: str) -> str:
    """Ideal-Le sweep at the band centre, one echo line per Le value."""
    sweep = [title]
    for le in LE_SWEEP_NH:
        sweep.append(
            f"alter l.xa.le = {le * 1e-9:g}\n"
            f"sp lin 1 {F_MID:g} {F_MID:g} 1\n"
            "let zin_r = real(50*(1+s_1_1)/(1-s_1_1))\n"
            "let zin_i = imag(50*(1+s_1_1)/(1-s_1_1))\n"
            "let s21m = abs(s_2_1)\n"
            "let nfmin_r = real(NFmin)\n"
            "let rn_r = real(Rn)\n"
            "let gopt_r = real(SOpt)\n"
            "let gopt_i = imag(SOpt)\n"
            f"echo \"{tag} {le:g} $&zin_r $&zin_i $&s21m $&nfmin_r $&rn_r $&gopt_r $&gopt_i\"")
    sweep.append(f"alter l.xa.le = {LE_NH * 1e-9:g}")
    return "\n".join(sweep)


def parse_le_sweep(log: Path, tag: str):
    sweep = []
    for line in Path(log).read_text().splitlines():
        if line.startswith(tag + " "):
            vals = [float(x) for x in line.split()[1:]]
            if len(vals) != len(LESWEEP_FIELDS) or not all(math.isfinite(v) for v in vals):
                raise ValueError(f"bad {tag} line: {line!r}")
            sweep.append(dict(zip(LESWEEP_FIELDS, vals)))
    if [s["le_nh"] for s in sweep] != [float(x) for x in LE_SWEEP_NH]:
        raise ValueError(f"{log}: {tag} sweep incomplete or out of order")
    return sweep


def parse_op(log: Path) -> dict:
    m = re.search(r"^OP ic1 (\S+) ic2 (\S+) idd (\S+)", Path(log).read_text(), re.M)
    if not m:
        raise ValueError(f"{log}: no OP line")
    return dict(zip(["ic1", "ic2", "idd"], (float(x) for x in m.groups())))


def feed_deck(a) -> str:
    body = dut_base()
    if body.count(R3B_LINE) != 1:
        raise SystemExit(f"design netlist no longer carries '{R3B_LINE}' exactly once")
    body = body.replace(
        R3B_LINE,
        f"* BENCH EDIT (what-if probe only): R3b's RF path isolated by an ideal {FEED_CHOKE:g} H choke\n"
        f"R3b bref b1f 330 m=1\nLfeed b1f b1 {FEED_CHOKE:g}")
    return render(TB_FEED, {
        **pdk_subs(a), "F_MID": f"{F_MID:g}", "DUT": body,
        "LE_SWEEP": le_sweep_text("FEEDSWEEP", "* --- ideal-Le sweep, R3b feed choked ---"),
    })


def char_deck(a) -> str:
    blocks = []
    for case, q in CHAR_CASES.items():
        r = R_IDEAL_PLACEHOLDER if q is None else q_parallel_r(LE_NH * 1e-9, q)
        blocks.append(
            f"* --- A/B. Le-loss case '{case}' (Rle = {r:.6g} Ohm) ---\n"
            f"alter r.xa.rle = {r:.6g}\n"
            f"alter l.xa.lc = {LC_NH * 1e-9:g}\n"
            f"sp lin {N_BAND} {F_LO:g} {F_HI:g} 1\n"
            f"wrdata {a.outdir}/char_{case}_twoport.dat real(s_1_1) imag(s_1_1) real(s_2_1) imag(s_2_1) "
            "real(s_1_2) imag(s_1_2) real(s_2_2) imag(s_2_2) real(NF) real(NFmin) real(Rn) real(SOpt) imag(SOpt)\n"
            f"echo \"DAT_WRITTEN char_{case}_twoport.dat\"\n"
            f"alter l.xa.lc = {CHOKE:g}\n"
            f"sp lin {N_BAND} {F_LO:g} {F_HI:g}\n"
            f"wrdata {a.outdir}/char_{case}_choke.dat real(s_2_2) imag(s_2_2) real(s_1_1) imag(s_1_1)\n"
            f"echo \"DAT_WRITTEN char_{case}_choke.dat\"\n")
    blocks.append(f"alter r.xa.rle = {R_IDEAL_PLACEHOLDER:g}\nalter l.xa.lc = {LC_NH * 1e-9:g}\n")
    sweep = le_sweep_text("LESWEEP", "* --- C. ideal-Le sweep at the band centre ---")
    em_lines, em_vecs = [], []
    for g in EM_GEOMS:
        em_lines.append(f"X{g} 0 {g}_b 0 {em_instance(g)}\nI{g} 0 {g}_b dc 0 ac 1")
        em_vecs += [f"real(v({g}_b))", f"imag(v({g}_b))"]
    return render(TB_CHAR, {
        **pdk_subs(a),
        "CASE_LIST": ", ".join(CHAR_CASES),
        "EM_MODEL": os.path.relpath(EM_MODEL, a.deckdir) if a.relative_em else str(EM_MODEL),
        "DUT": dut_text(R_IDEAL_PLACEHOLDER, None),
        "RIDEAL": f"{R_IDEAL_PLACEHOLDER:g}",
        "EM_ONEPORTS": "\n".join(em_lines),
        "CHAR_CASES": "\n".join(blocks),
        "LE_SWEEP": sweep,
        "N_BAND": N_BAND, "F_LO": f"{F_LO:g}", "F_HI": f"{F_HI:g}",
        "OUTDIR": a.outdir,
        "EM_VECS": " ".join(em_vecs),
    })


# ===========================================================================
# Characterization data -> solver inputs
# ===========================================================================

def load_char(cdir: Path, require_feed: bool = True):
    """Read a characterization directory. `require_feed=False` (issue #193)
    skips the R3b-choked what-if probe (char_feed.log), for characterization
    directories of a different feed variant that have no such probe."""
    freqs = band_freqs()
    data = {"cases": {}, "em": {}}
    for case in CHAR_CASES:
        _, tp = columns(cdir / f"char_{case}_twoport.dat", N_BAND, freqs)
        _, ck = columns(cdir / f"char_{case}_choke.dat", N_BAND, freqs)
        s11, s21, s12, s22 = (cplx(tp, n) for n in ("s_1_1", "s_2_1", "s_1_2", "s_2_2"))
        s22c = cplx(ck, "s_2_2")
        rows = []
        for i, f in enumerate(freqs):
            nfmin_t = tp["real(NFmin)"][i]
            rows.append({
                "f": f, "s11": s11[i], "s21": s21[i], "s12": s12[i], "s22": s22[i],
                "zin": z_from_s(s11[i]),
                "ydev": ydev_from_choke_s22(s22c[i], f),
                "nf_sp_db": tp["real(NF)"][i],
                "nfmin_t_db": nfmin_t,
                "noise": {"fmin": 10 ** (nfmin_t / 10), "rn": tp["real(Rn)"][i],
                          "gopt": complex(tp["real(SOpt)"][i], tp["imag(SOpt)"][i])},
            })
        data["cases"][case] = rows
    _, em = columns(cdir / "char_em.dat", N_BAND, freqs)
    for g in EM_GEOMS:
        zs = [complex(r, i) for r, i in zip(em[f"real(v({g}_b))"], em[f"imag(v({g}_b))"])]
        data["em"][g] = zs
    logs = ("char.log", "char_feed.log") if require_feed else ("char.log",)
    for log in logs:
        if not re.search(r"^BENCH_COMPLETE", (cdir / log).read_text(), re.M):
            raise ValueError(f"{log}: no BENCH_COMPLETE marker")
    data["le_sweep"] = parse_le_sweep(cdir / "char.log", "LESWEEP")
    data["op"] = parse_op(cdir / "char.log")
    if require_feed:
        data["feed_sweep"] = parse_le_sweep(cdir / "char_feed.log", "FEEDSWEEP")
        data["feed_op"] = parse_op(cdir / "char_feed.log")
    return data


def em_l_q(z: complex, f: float):
    w = 2 * math.pi * f
    return z.imag / w, (z.imag / z.real if z.real > 0 else math.inf)


def char_case_for(qcase: str) -> str:
    """Which characterized Le-loss case a Q case's DUT corresponds to."""
    q = QCASES[qcase]["q"]
    for c, cq in CHAR_CASES.items():
        if cq == q:
            return c
    raise KeyError(qcase)


def feasibility(l_h: float, em_lq: dict) -> str:
    """Compare a required inductance with the EM-extracted geometries' L at f_mid."""
    near = min(em_lq, key=lambda g: abs(math.log(l_h / em_lq[g][0])))
    ratio = l_h / em_lq[near][0]
    lmin = min(v[0] for v in em_lq.values())
    lmax = max(v[0] for v in em_lq.values())
    if abs(ratio - 1) <= 0.15:
        return f"near {near} (L ratio {ratio:.2f}; EM-backed geometry)"
    if lmin <= l_h <= lmax:
        return (f"inside the extracted L range, nearest {near} (L ratio {ratio:.2f}); "
                "needs a non-extracted geometry (EM-corrected analytic extrapolation)")
    if l_h < lmin:
        return f"below the smallest extracted L ({lmin * 1e9:.2f} nH); short trace / non-extracted geometry"
    return (f"above the largest extracted L ({lmax * 1e9:.2f} nH, ratio {l_h / lmax:.2f}); "
            "larger spiral (unextracted), bondwire or off-chip")


def synthesize(data: dict):
    """All (candidate, Q case) networks. Returns a list of dicts (JSON-able)."""
    freqs = band_freqs()
    em_lq = {g: em_l_q(data["em"][g][MID], F_MID) for g in EM_GEOMS}
    out = []
    for cand, cdef in CANDIDATES.items():
        for qcase, qdef in QCASES.items():
            q = qdef["q"]
            rows = data["cases"][char_case_for(qcase)]
            mid = rows[MID]
            entry = {"candidate": cand, "qcase": qcase, "q": q, "input_topology": cdef["input"],
                     "target": cdef["target"], "notes": []}
            # ---- input ----
            if cdef["target"] == "power":
                sol = solve_input_power(cdef["input"], mid["zin"], q)
            else:
                sol = solve_input_noise(cdef["input"], mid["zin"], mid["noise"], q)
            vin = sol["values"]
            zs_t = input_zs(cdef["input"], vin, q, F_MID)   # what the network actually presents
            f_pred_lin = two_port_f(zs_t, mid["noise"]["fmin"], mid["noise"]["rn"], mid["noise"]["gopt"])
            entry["zs_target"] = [zs_t.real, zs_t.imag]
            entry["input_closed_form"] = list(sol["closed_form"])
            entry["input_values"] = list(vin)
            l_in = vin[0] if cdef["input"] == "lowpass" else vin[1]
            entry["input_l"] = l_in
            entry["input_r"] = q_series_r(l_in, q)
            # ---- output ----
            # Informational only: the two-element "Lc + series C" match (O1)
            # needs Lc ~ 50*Q/w on this collector node; recorded, not verified.
            try:
                o1 = solve_output_free_lc(mid["ydev"], q)
                entry["o1_lc_required_nh"] = o1["lc"] * 1e9
            except ValueError as ex:
                entry["o1_lc_required_nh"] = None
                entry["notes"].append(f"O1: {ex}")
            if not qdef["lc_em"]:
                lc_h = LC_NH * 1e-9
                r_lc = q_series_r(lc_h, q)
                ylc_f = [1 / z_ind(lc_h, r_lc, f) for f in freqs]
                o = solve_output_fixed_lc(mid["ydev"], ylc_f[MID])
                if not o["feasible"]:
                    entry.update({"output": "O2", "infeasible": f"Cp < 0 ({o['cp_raw']!r})"})
                    out.append(entry)
                    continue
                entry.update({"output": "O2", "lc": lc_h, "r_lc": r_lc, "cp_out": o["cp"],
                              "cs_out": o["cs"], "lc_em": None})
            else:
                chosen = None
                tried = []
                for g in EM_LC_PREFERENCE:
                    ylc = 1 / data["em"][g][MID]
                    o = solve_output_fixed_lc(mid["ydev"], ylc)
                    tried.append(f"{g}: Cp={o['cp_raw']!r}")
                    if o["feasible"]:
                        chosen = (g, o)
                        break
                if chosen is None:
                    entry.update({"output": "O2", "infeasible": "no extracted geometry admits Cp >= 0",
                                  "tried": tried})
                    out.append(entry)
                    continue
                g, o = chosen
                entry.update({"output": "O2", "lc": em_lq[g][0], "r_lc": None, "cp_out": o["cp"],
                              "cs_out": o["cs"], "lc_em": g, "lc_em_tried": tried})
                ylc_f = [1 / z for z in data["em"][g]]
            # ---- predictions across the band (unilateral) ----
            pred = []
            for i, f in enumerate(freqs):
                r = rows[i]
                zl = input_zlook(cdef["input"], vin, q, f, r["zin"])
                zo = output_zlook(r["ydev"], ylc_f[i], entry["cp_out"], entry["cs_out"], f)
                pred.append({"f": f, "s11_db": db20(abs(gamma(zl))), "s22_db": db20(abs(gamma(zo))),
                             "nf290_db": predicted_nf290(cdef["input"], vin, q, f, r["noise"])})
            entry["predicted"] = pred
            entry["predicted_twoport_nf290_mid_db"] = nf_reref(10 * math.log10(f_pred_lin), T_ANALYSIS)
            # ---- inductor feasibility ----
            entry["feasibility"] = {
                "Le": feasibility(LE_NH * 1e-9, em_lq),
                ("Lb" if cdef["input"] == "lowpass" else "Lp"): feasibility(l_in, em_lq),
                "Lc": (f"EM geometry {entry['lc_em']} (extracted)" if entry["lc_em"]
                       else feasibility(entry["lc"], em_lq)),
            }
            out.append(entry)
    return out, em_lq


def input_net_text(entry) -> str:
    a, b = entry["input_values"]
    r = entry["input_r"]
    if entry["input_topology"] == "lowpass":
        lines = [f"* input network: series Lb = {a * 1e9:.6g} nH (loss R = {r:.6g} Ohm), "
                 f"shunt Cp = {b * 1e12:.6g} pF at rfin"]
        if r > 0:
            lines += [f"Lb in lb_x {a:.6g}", f"Rlb lb_x xin {r:.6g}"]
        else:
            lines += [f"Lb in xin {a:.6g}"]
        lines += [f"Cpin xin vss {b:.6g}"]
    else:
        lines = [f"* input network: series Cs = {a * 1e12:.6g} pF, shunt Lp = {b * 1e9:.6g} nH "
                 f"(loss R = {r:.6g} Ohm) at rfin"]
        lines += [f"Csin in xin {a:.6g}"]
        if r > 0:
            lines += [f"Lp xin lp_x {b:.6g}", f"Rlp lp_x vss {r:.6g}"]
        else:
            lines += [f"Lp xin vss {b:.6g}"]
    return "\n".join(lines)


def output_net_text(entry) -> str:
    lines = [f"* output network: series Cs = {entry['cs_out'] * 1e12:.6g} pF"
             + (f", shunt Cp = {entry['cp_out'] * 1e12:.6g} pF at rfout" if entry["cp_out"] > 0 else "")]
    if entry["cp_out"] > 0:
        lines.append(f"Cpout xout vss {entry['cp_out']:.6g}")
    lines.append(f"Csout xout out {entry['cs_out']:.6g}")
    return "\n".join(lines)


def xout_dc_text(rdc) -> str:
    """The explicit DC reference on the DUT's rfout node, or a comment for the
    historical (floating-xout) bench. `rdc` is ohms or None."""
    if rdc is None:
        return "* (no DC reference on xout: historical floating-xout bench)"
    return ("* BENCH ELEMENT (not part of the DUT or the matching network): DC reference\n"
            f"* for the otherwise capacitor-only rfout node, {rdc:g} Ohm, noiseless.\n"
            f"Rxoutdc xout vss {rdc:g} noisy=0")


def rdc_tag(rdc) -> str:
    """Filename-safe tag of a DC-reference value: 1e9 -> 'rdc1e9'."""
    return "" if rdc is None else "_rdc" + f"{rdc:g}".replace("+", "")


def parse_rdc_list(text) -> list:
    """'1e9,1e12' -> [1e9, 1e12]; '' / None -> [None] (historical bench)."""
    if not text:
        return [None]
    out = []
    for tok in str(text).split(","):
        v = float(tok)
        if not (math.isfinite(v) and v >= 1e6):
            raise ValueError(f"--xout-rdc {tok}: a DC reference must be a finite, very large resistance "
                             f"(>= 1e6 Ohm)")
        out.append(v)
    if len(set(out)) != len(out):
        raise ValueError("--xout-rdc: duplicate values")
    return out


def verify_deck(a, entry, stem: str) -> str:
    q = entry["q"]
    le_rp = None if q is None else q_parallel_r(LE_NH * 1e-9, q)
    if entry["lc_em"]:
        lc = ("em", entry["lc_em"])
    else:
        lc = ("ideal", entry["lc"], entry["r_lc"])
    notes = [f"* {CANDIDATES[entry['candidate']]['desc']}",
             f"* Q case: {QCASES[entry['qcase']]['desc']}",
             f"* Target source impedance at 2.44175 GHz: {entry['zs_target'][0]:.4f} "
             f"{entry['zs_target'][1]:+.4f}j Ohm"]
    em_inc = f'.include "{EM_MODEL}"' if entry["lc_em"] else "* (no EM inductor in this candidate)"
    return render(TB_VERIFY, {
        **pdk_subs(a),
        "CANDIDATE": entry["candidate"], "QCASE": entry["qcase"],
        "CANDIDATE_NOTES": "\n".join(notes),
        "EM_INCLUDE": em_inc,
        "DUT": dut_text(le_rp, lc),
        "INPUT_NET": input_net_text(entry),
        "OUTPUT_NET": output_net_text(entry),
        "XOUT_DC": xout_dc_text(entry.get("xout_rdc_ohm")),
        "N_BAND": N_BAND, "F_LO": f"{F_LO:g}", "F_HI": f"{F_HI:g}", "F_MID": f"{F_MID:g}",
        "N_STAB_DEC": N_STAB_DEC, "F_STAB_LO": f"{F_STAB_LO:g}", "F_STAB_HI": f"{F_STAB_HI:g}",
        "N_NF": a.nf_npts, "OUTDIR": a.outdir, "STEM": stem,
    })


def stem_of(entry) -> str:
    return f"verify_{entry['candidate']}_{entry['qcase']}{rdc_tag(entry.get('xout_rdc_ohm'))}"


# ===========================================================================
# Reduction
# ===========================================================================

def parse_log(path: Path) -> dict:
    text = Path(path).read_text()
    if not re.search(r"^BENCH_COMPLETE", text, re.M):
        raise ValueError(f"{path}: no BENCH_COMPLETE marker")
    out = {}
    m = re.search(r"^OP ic1 (\S+) ic2 (\S+) idd (\S+) pdc (\S+)", text, re.M)
    if not m:
        raise ValueError(f"{path}: no OP line")
    out.update(zip(["ic1", "ic2", "idd", "pdc"], (float(x) for x in m.groups())))
    m = re.search(r"^GAIN mid (\S+)", text, re.M)
    if not m:
        raise ValueError(f"{path}: no GAIN line")
    out["gt_mid_db"] = float(m.group(1))
    for k, v in out.items():
        if not math.isfinite(v):
            raise ValueError(f"{path}: non-finite {k}")
    return out


def classify_convergence(path: Path) -> dict:
    """Classify the operating-point convergence of one ngspice log.

    BENCH_COMPLETE alone is NOT convergence evidence: the historical floating-
    xout decks print it after a transient-op fallback. A log is 'normal' only
    if it shows no singular-matrix warning, no failed gmin/source stepping and
    no transient-op fallback.
    """
    text = Path(path).read_text()
    n_singular = len(re.findall(r"singular matrix", text, re.I))
    flags = {
        "singular_matrix": n_singular,
        "gmin_stepping_failed": len(re.findall(r"(?:dynamic|true) gmin stepping failed", text, re.I)),
        "source_stepping_failed": len(re.findall(r"source stepping failed", text, re.I)),
        "transient_op_fallback": len(re.findall(r"transient op started", text, re.I)),
    }
    flags["bench_complete"] = bool(re.search(r"^BENCH_COMPLETE", text, re.M))
    flags["normal"] = flags["bench_complete"] and not any(
        flags[k] for k in ("singular_matrix", "gmin_stepping_failed", "source_stepping_failed",
                           "transient_op_fallback"))
    return flags


def stab_freqs() -> list[float]:
    n = int(round(N_STAB_DEC * math.log10(F_STAB_HI / F_STAB_LO))) + 1
    return [F_STAB_LO * 10 ** (i / N_STAB_DEC) for i in range(n)]


def nf_freqs(n: int) -> list[float]:
    check_nf_npts(n)
    return [F_LO + (F_HI - F_LO) * i / (n - 1) for i in range(n)]


def reduce_one(cdir: Path, stem: str, nf_npts: int) -> dict:
    freqs = band_freqs()
    _, ib = columns(cdir / f"{stem}.inband.dat", N_BAND, freqs)
    s = {n: cplx(ib, n) for n in ("s_1_1", "s_2_1", "s_1_2", "s_2_2")}
    band = []
    for i, f in enumerate(freqs):
        mu, k, d = stability(s["s_1_1"][i], s["s_2_1"][i], s["s_1_2"][i], s["s_2_2"][i])
        band.append({"f": f, "s11_db": db20(abs(s["s_1_1"][i])), "s21_db": db20(abs(s["s_2_1"][i])),
                     "s12_db": db20(abs(s["s_1_2"][i])), "s22_db": db20(abs(s["s_2_2"][i])),
                     "nf_sp_db": ib["real(NF)"][i], "nfmin_sp_db": ib["real(NFmin)"][i],
                     "nfmin290_db": nf_reref(ib["real(NFmin)"][i], T_ANALYSIS),
                     "mu": mu, "k": k, "delta": d})
    sf = stab_freqs()
    _, st = columns(cdir / f"{stem}.stab.dat", len(sf), sf)
    ss = {n: cplx(st, n) for n in ("s_1_1", "s_2_1", "s_1_2", "s_2_2")}
    mus, ks = [], []
    for i in range(len(sf)):
        mu, k, _ = stability(ss["s_1_1"][i], ss["s_2_1"][i], ss["s_1_2"][i], ss["s_2_2"][i])
        mus.append(mu)
        ks.append(k)
    imu = min(range(len(sf)), key=lambda i: mus[i])
    nfq = nf_freqs(nf_npts)
    nfname, nf = columns(cdir / f"{stem}.nf290.dat", nf_npts, nfq)
    nf290 = nf["nf290"]
    inf = max(range(nf_npts), key=lambda i: nf290[i])
    op = parse_log(cdir / f"{stem}.log")
    m = {
        "s11_db_worst": max(b["s11_db"] for b in band),
        "s22_db_worst": max(b["s22_db"] for b in band),
        "s21_db_min": min(b["s21_db"] for b in band),
        "s21_db_max": max(b["s21_db"] for b in band),
        "s21_db_mid": band[MID]["s21_db"],
        "s12_db_max": max(b["s12_db"] for b in band),
        "s11_db_mid": band[MID]["s11_db"],
        "s22_db_mid": band[MID]["s22_db"],
        "nf290_db_worst": nf290[inf],
        "nf290_f_worst_hz": nfq[inf],
        "nf290_db_mid": nf290[(nf_npts - 1) // 2],
        "nf_sp_db_mid": band[MID]["nf_sp_db"],
        "nfmin290_db_mid": band[MID]["nfmin290_db"],
        "mu_band_min": min(b["mu"] for b in band),
        "k_band_min": min(b["k"] for b in band),
        "mu_bb_min": mus[imu],
        "mu_bb_f_min_hz": sf[imu],
        "mu_bb_n_lt1": sum(1 for x in mus if x <= 1.0),
        "k_bb_min": min(ks),
        "s11_mag_bb_max": max(abs(x) for x in ss["s_1_1"]),
        "s22_mag_bb_max": max(abs(x) for x in ss["s_2_2"]),
        "n_stab_pts": len(sf),
        "gt_minus_s21_db_mid": op["gt_mid_db"] - band[MID]["s21_db"],
        **op,
    }
    return {"metrics": m, "band": band}


def row_verdicts(m: dict) -> dict:
    return {
        "S11": m["s11_db_worst"] < ROW_S11_DB,
        "S22": m["s22_db_worst"] < ROW_S22_DB,
        "S21": m["s21_db_min"] > ROW_S21_DB,
        "NF": m["nf290_db_worst"] < ROW_NF_DB,
        "mu": m["mu_bb_min"] > ROW_MU,
    }


def rank_topologies(results: dict, basis: str = "q10"):
    """Rank candidates by rows met on the `basis` Q case, then lower worst
    NF290, then higher broadband mu. results[(cand, qcase)] -> metrics."""
    keyed = []
    for cand in CANDIDATES:
        m = results.get((cand, basis))
        if m is None:
            continue
        v = row_verdicts(m)
        keyed.append((-sum(v.values()), m["nf290_db_worst"], -m["mu_bb_min"], cand))
    keyed.sort()
    return [k[-1] for k in keyed]


# ===========================================================================
# CLI
# ===========================================================================

# ===========================================================================
# DC-reference sensitivity (issue #190)
# ===========================================================================

# Table resolution of mu: S-parameters are written with `option numdgt=10`.
MU_RESOLUTION = 1e-9
# A DC reference "materially" changes the stability margin if it moves the
# broadband mu minimum by more than this fraction of the baseline margin
# (mu - 1), drives a resolved margin to the resolution floor, or moves the
# frequency of the minimum. Chosen before the data; stated in the README.
MU_MATERIAL_FRACTION = 0.10

SENS_COLS = ["candidate", "qcase", "xout_rdc_ohm", "case_class",
             "ic1_base_A", "ic1_new_A", "d_ic1_A", "ic2_base_A", "ic2_new_A", "d_ic2_A",
             "s11_mid_base_db", "s11_mid_new_db", "d_s11_mid_db", "s22_mid_base_db", "s22_mid_new_db",
             "d_s22_mid_db", "s21_mid_base_db", "s21_mid_new_db", "d_s21_mid_db", "d_s11_worst_db", "d_s22_worst_db",
             "nf290_mid_base_db", "nf290_mid_new_db", "d_nf290_mid_db",
             "nf290_worst_base_db", "nf290_worst_new_db", "d_nf290_worst_db",
             "mu_bb_min_base", "mu_bb_min_new", "d_mu_bb_min", "mu_bb_f_base_hz", "mu_bb_f_new_hz",
             "margin_base", "margin_new", "d_margin_over_margin", "mu_band_min_base", "mu_band_min_new",
             "mu_verdict", "convergence_new", "convergence_base", "singular_new", "transient_op_new"]


def mu_verdict(base: float, new: float, f_base: float, f_new: float, finite_q: bool) -> str:
    """Classify the RF effect of the DC reference on the mu minimum."""
    mb, mn = base - 1.0, new - 1.0
    below = " (|dmu| below table resolution)" if abs(new - base) < MU_RESOLUTION else ""
    if abs(mb) < MU_RESOLUTION and abs(mn) < MU_RESOLUTION:
        return "mu = 1 to table resolution (lossless limit); no resolved margin to protect"
    if mb <= -MU_RESOLUTION:
        return "baseline mu < 1 (resolved deficit at the sweep edge); change reported, no margin claimed"
    if mb <= MU_RESOLUTION:
        return "baseline margin not resolved; sensitivity not assessable"
    if mn <= MU_RESOLUTION:
        return "MATERIAL: margin driven to table resolution"
    if abs(new - base) > MU_MATERIAL_FRACTION * mb:
        return "MATERIAL: mu minimum moved by more than %d%% of the baseline margin" % round(100 * MU_MATERIAL_FRACTION)
    if abs(math.log10(f_new / f_base)) > 1e-9:
        return "MATERIAL: frequency of the mu minimum moved"
    return "within %d%% of the baseline margin%s" % (round(100 * MU_MATERIAL_FRACTION), below)


def sensitivity_rows(doc: dict, cdir: Path, base_dir: Path) -> tuple[list, list]:
    rows, problems = [], []
    nf_npts = doc["nf_npts"]
    for e in doc["candidates"]:
        rdc = e.get("xout_rdc_ohm")
        if rdc is None or e.get("infeasible"):
            continue
        key = f"{e['candidate']}/{e['qcase']}/rdc{rdc:g}"
        try:
            new = reduce_one(cdir, e["stem"], nf_npts)["metrics"]
            base = reduce_one(base_dir, e["base_stem"], nf_npts)["metrics"]
            cn = classify_convergence(cdir / f"{e['stem']}.log")
            cb = classify_convergence(base_dir / f"{e['base_stem']}.log")
        except (OSError, ValueError, KeyError) as ex:
            problems.append(f"{key}: {ex}")
            continue
        finite_q = e["q"] is not None or bool(e["lc_em"])
        r = {
            "candidate": e["candidate"], "qcase": e["qcase"], "xout_rdc_ohm": rdc,
            "case_class": "finite-Q" if finite_q else "ideal",
            "ic1_base_A": base["ic1"], "ic1_new_A": new["ic1"], "d_ic1_A": new["ic1"] - base["ic1"],
            "ic2_base_A": base["ic2"], "ic2_new_A": new["ic2"], "d_ic2_A": new["ic2"] - base["ic2"],
            "s11_mid_base_db": base["s11_db_mid"], "s11_mid_new_db": new["s11_db_mid"],
            "s22_mid_base_db": base["s22_db_mid"], "s22_mid_new_db": new["s22_db_mid"],
            "s21_mid_base_db": base["s21_db_mid"], "s21_mid_new_db": new["s21_db_mid"],
            "d_s11_mid_db": new["s11_db_mid"] - base["s11_db_mid"],
            "d_s22_mid_db": new["s22_db_mid"] - base["s22_db_mid"],
            "d_s21_mid_db": new["s21_db_mid"] - base["s21_db_mid"],
            "d_s11_worst_db": new["s11_db_worst"] - base["s11_db_worst"],
            "d_s22_worst_db": new["s22_db_worst"] - base["s22_db_worst"],
            "nf290_mid_base_db": base["nf290_db_mid"], "nf290_mid_new_db": new["nf290_db_mid"],
            "d_nf290_mid_db": new["nf290_db_mid"] - base["nf290_db_mid"],
            "nf290_worst_base_db": base["nf290_db_worst"], "nf290_worst_new_db": new["nf290_db_worst"],
            "d_nf290_worst_db": new["nf290_db_worst"] - base["nf290_db_worst"],
            "mu_bb_min_base": base["mu_bb_min"], "mu_bb_min_new": new["mu_bb_min"],
            "d_mu_bb_min": new["mu_bb_min"] - base["mu_bb_min"],
            "mu_bb_f_base_hz": base["mu_bb_f_min_hz"], "mu_bb_f_new_hz": new["mu_bb_f_min_hz"],
            "margin_base": base["mu_bb_min"] - 1.0, "margin_new": new["mu_bb_min"] - 1.0,
            "d_margin_over_margin": ((new["mu_bb_min"] - base["mu_bb_min"]) / (base["mu_bb_min"] - 1.0)
                                     if abs(base["mu_bb_min"] - 1.0) >= MU_RESOLUTION else float("nan")),
            "mu_band_min_base": base["mu_band_min"], "mu_band_min_new": new["mu_band_min"],
            "mu_verdict": mu_verdict(base["mu_bb_min"], new["mu_bb_min"], base["mu_bb_f_min_hz"],
                                     new["mu_bb_f_min_hz"], finite_q),
            "convergence_new": "normal" if cn["normal"] else "FLAGGED",
            "convergence_base": "normal" if cb["normal"] else "fallback/flagged",
            "singular_new": cn["singular_matrix"], "transient_op_new": cn["transient_op_fallback"],
        }
        rows.append(r)
        if not cn["normal"]:
            problems.append(f"{key}: operating-point convergence not normal ({cn})")
    return rows, problems


def _sens_cell(k, v):
    if isinstance(v, str):
        return v
    if isinstance(v, int):
        return str(v)
    if k.endswith("_hz") or k == "xout_rdc_ohm":
        return f"{v:.6g}"
    if k.endswith("_A") or k.startswith("margin") or k == "d_mu_bb_min":
        return f"{v:.6e}"
    if k.startswith("mu_"):
        return f"{v:.10f}"
    return f"{v:.6g}"


def r_dependence(rows) -> list:
    """Per candidate/Q case: metric differences between the largest and the
    smallest DC-reference value (separates the resistor's own effect from the
    change that comes from leaving the transient-op fallback)."""
    groups = {}
    for r in rows:
        groups.setdefault((r["candidate"], r["qcase"]), []).append(r)
    out = []
    for (c, q), g in groups.items():
        if len(g) < 2:
            continue
        lo = min(g, key=lambda r: r["xout_rdc_ohm"])
        hi = max(g, key=lambda r: r["xout_rdc_ohm"])
        out.append({
            "candidate": c, "qcase": q, "r_lo": lo["xout_rdc_ohm"], "r_hi": hi["xout_rdc_ohm"],
            "d_ic1": hi["ic1_new_A"] - lo["ic1_new_A"],
            "d_s11": hi["s11_mid_new_db"] - lo["s11_mid_new_db"],
            "d_s22": hi["s22_mid_new_db"] - lo["s22_mid_new_db"],
            "d_s21": hi["s21_mid_new_db"] - lo["s21_mid_new_db"],
            "d_nf": hi["nf290_worst_new_db"] - lo["nf290_worst_new_db"],
            "d_mu": hi["mu_bb_min_new"] - lo["mu_bb_min_new"],
            "f_same": "yes" if hi["mu_bb_f_new_hz"] == lo["mu_bb_f_new_hz"] else "no",
        })
    return out


def write_sensitivity(csv_path, md_path, rows, problems):
    with open(csv_path, "w", newline="") as fh:
        w = csv.writer(fh, lineterminator="\n")
        w.writerow(SENS_COLS)
        for r in rows:
            w.writerow([_sens_cell(k, r[k]) for k in SENS_COLS])
    L = ["#### DC-reference sensitivity (nominal cell; baseline = historical floating-xout bench, record "
         "`20261010-201010-6aca84c`)", "",
         f"mu resolution floor {MU_RESOLUTION:g} (wrdata `numdgt=10`); a change is MATERIAL if it moves the "
         f"broadband mu minimum by more than {MU_MATERIAL_FRACTION:.0%} of the baseline margin (mu - 1), "
         "drives the margin to the resolution floor, or moves the frequency of the minimum.", ""]
    for cls in ("finite-Q", "ideal"):
        sel = [r for r in rows if r["case_class"] == cls]
        if not sel:
            continue
        L += [f"**{cls} cases**", "",
              "| Candidate | Q case | R_xout (Ohm) | I_C1 base / new (mA) | S11 mid base / new (dB) | S22 mid base / new (dB) | S21 mid base / new (dB) | "
              "dNF290 mid (dB) | dNF290 worst (dB) | mu min base | mu min new | f(mu min) base / new (Hz) | "
              "dmu / margin | verdict | OP convergence (new / base) |",
              "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
        for r in sel:
            L.append("| {c} | {q} | {rdc:g} | {i1b:.5f} / {i1n:.5f} | {a1:.2f} / {b1:.2f} | {a2:.2f} / {b2:.2f} "
                     "| {a3:.4f} / {b3:.4f} | {dn:.3e} | {dnw:.3e} "
                     "| {mb:.10f} | {mn:.10f} | {fb:.6g} / {fn:.6g} | {rel} | {v} | {cn} / {cb} |".format(
                         c=r["candidate"], q=r["qcase"], rdc=r["xout_rdc_ohm"],
                         i1b=r["ic1_base_A"] * 1e3, i1n=r["ic1_new_A"] * 1e3,
                         a1=r["s11_mid_base_db"], b1=r["s11_mid_new_db"],
                         a2=r["s22_mid_base_db"], b2=r["s22_mid_new_db"],
                         a3=r["s21_mid_base_db"], b3=r["s21_mid_new_db"],
                         dn=r["d_nf290_mid_db"], dnw=r["d_nf290_worst_db"], mb=r["mu_bb_min_base"],
                         mn=r["mu_bb_min_new"], fb=r["mu_bb_f_base_hz"], fn=r["mu_bb_f_new_hz"],
                         rel=("n/a" if math.isnan(r["d_margin_over_margin"]) else f"{r['d_margin_over_margin']:.3e}"),
                         v=r["mu_verdict"], cn=r["convergence_new"], cb=r["convergence_base"]))
        L.append("")
    dep = r_dependence(rows)
    if dep:
        L += ["**Dependence on the resistor value** (largest minus smallest R of the same candidate / Q case; "
              "this is the part of the change that the resistor itself can be responsible for)", "",
              "| Candidate | Q case | R pair (Ohm) | dI_C1 (A) | dS11 mid (dB) | dS22 mid (dB) | dS21 mid (dB) | "
              "dNF290 worst (dB) | dmu min | mu-min frequency same |",
              "|---|---|---|---|---|---|---|---|---|---|"]
        for d in dep:
            L.append("| {candidate} | {qcase} | {r_lo:g} / {r_hi:g} | {d_ic1:.2e} | {d_s11:.2e} | {d_s22:.2e} "
                     "| {d_s21:.2e} | {d_nf:.2e} | {d_mu:.2e} | {f_same} |".format(**d))
        L.append("")
    if problems:
        L += ["**Problems**", ""] + [f"- {p}" for p in problems] + [""]
    Path(md_path).write_text("\n".join(L) + "\n")


def cmd_sensitivity(a):
    doc = json.loads(Path(a.candidates).read_text())
    rows, problems = sensitivity_rows(doc, Path(a.corners), Path(a.baseline_corners))
    write_sensitivity(a.csv, a.markdown, rows, problems)
    print(f"sensitivity: {len(rows)} rows")
    for p in problems:
        print(f"sensitivity: PROBLEM {p}", file=sys.stderr)
    return 1 if problems or not rows else 0


def add_pdk_args(p):
    p.add_argument("--models-lib", required=True)
    p.add_argument("--mos-lib", required=True)
    p.add_argument("--osdi-dir", required=True)


def cmd_gen_char(a):
    a.deckdir = a.snapdir
    a.relative_em = False
    Path(a.snapdir, "char.spice").write_text(char_deck(a))
    Path(a.snapdir, "char_feed.spice").write_text(feed_deck(a))
    print(f"gen-char: wrote {a.snapdir}/char.spice and char_feed.spice")


def _fmtc(z: complex) -> str:
    return f"{z.real:.4f}{z.imag:+.4f}j"


def cmd_solve(a):
    check_nf_npts(a.nf_npts)
    rdcs = parse_rdc_list(getattr(a, "xout_rdc", None))
    only = None
    if getattr(a, "only", None):
        only = {tuple(tok.split(":")) for tok in a.only.split(",")}
        for tok in only:
            if len(tok) != 2 or tok[0] not in CANDIDATES or tok[1] not in QCASES:
                raise SystemExit(f"solve: --only entry {':'.join(tok)!r} is not <candidate>:<qcase>")
    # The characterization is unchanged by the DC reference (it has no floating
    # node), so a DC-reference run may re-use a retained characterization dir.
    data = load_char(Path(getattr(a, "char_dir", None) or a.outdir))
    base_entries, em_lq = synthesize(data)
    entries = []
    for e in base_entries:
        if only is not None and (e["candidate"], e["qcase"]) not in only:
            continue
        for rdc in rdcs:
            e2 = dict(e)
            e2["xout_rdc_ohm"] = rdc
            entries.append(e2)
    snap = Path(a.snapdir)
    n = 0
    for e in entries:
        if e.get("infeasible"):
            continue
        stem = stem_of(e)
        e["stem"] = stem
        e["base_stem"] = f"verify_{e['candidate']}_{e['qcase']}"
        (snap / f"{stem}.spice").write_text(verify_deck(a, e, stem))
        n += 1
    char_summary = {
        "op": data["op"],
        "feed_op": data["feed_op"],
        "cases": {
            c: {"zin_mid": _fmtc(rows[MID]["zin"]), "ydev_mid": _fmtc(rows[MID]["ydev"]),
                "zopt_mid": _fmtc(z_from_s(rows[MID]["noise"]["gopt"])),
                "rn_mid": rows[MID]["noise"]["rn"],
                "nfmin290_mid_db": nf_reref(rows[MID]["nfmin_t_db"], T_ANALYSIS),
                "nf_sp_50ohm_mid_db": rows[MID]["nf_sp_db"],
                "s12_db_mid": db20(abs(rows[MID]["s12"])), "s21_db_mid": db20(abs(rows[MID]["s21"]))}
            for c, rows in data["cases"].items()
        },
        "em_mid": {g: {"l_nh": lq[0] * 1e9, "q": lq[1], "outer_d_um": em_outer_diameter_um(g),
                       "nr_r": EM_GEOMS[g]["nr_r"]} for g, lq in em_lq.items()},
        "le_sweep": data["le_sweep"],
        "feed_sweep": data["feed_sweep"],
    }
    doc = {"generator": "sim/lna-matching-feasibility/matching_solver.py solve",
           "design_netlist_sha256": sha256(DESIGN_NETLIST), "em_model_sha256": sha256(EM_MODEL),
           "nf_npts": a.nf_npts, "xout_rdc_ohm_list": rdcs, "f_mid_hz": F_MID, "mismatch_target_db": MISMATCH_TARGET_DB,
           "characterization": char_summary,
           "candidates": [{**e, "zs_target": e["zs_target"]} for e in entries]}
    (snap / "candidates.json").write_text(json.dumps(doc, indent=2, default=str) + "\n")
    print(f"solve: {n} verification decks + candidates.json in {snap}")


def _f(x, nd=4):
    if x is None:
        return ""
    if isinstance(x, bool):
        return "yes" if x else "no"
    if isinstance(x, (int,)) and not isinstance(x, bool):
        return str(x)
    return f"{x:.{nd}f}"


CAND_COLS = ["rank", "candidate", "qcase", "input_topology", "target", "output",
             "zs_target_ohm", "input_series", "input_shunt", "input_l_loss_ohm",
             "lc_nh", "lc_model", "lc_loss_ohm", "cp_out_pf", "cs_out_pf",
             "pred_s11_db_mid", "pred_s22_db_mid", "pred_nf290_db_mid",
             "s11_db_mid", "s11_db_worst", "s22_db_mid", "s22_db_worst", "s21_db_mid", "s21_db_min",
             "s21_db_max", "s12_db_max", "nf290_db_mid", "nf290_db_worst", "nf290_f_worst_hz",
             "nfmin290_db_mid", "mu_band_min", "k_band_min", "mu_bb_min", "mu_bb_f_min_hz",
             "mu_bb_n_lt1", "n_stab_pts", "k_bb_min", "s11_mag_bb_max", "s22_mag_bb_max",
             "gt_minus_s21_db_mid", "ic1_ma", "pdc_mw",
             "row_S11", "row_S22", "row_S21", "row_NF", "row_mu", "rows_met",
             "feas_Le", "feas_Lin", "feas_Lc"]


def _elem_text(e):
    a, b = e["input_values"]
    if e["input_topology"] == "lowpass":
        return f"Lb {a * 1e9:.4f} nH", f"Cp {b * 1e12:.4f} pF"
    return f"Cs {a * 1e12:.4f} pF", f"Lp {b * 1e9:.4f} nH"


def cmd_reduce(a):
    doc = json.loads(Path(a.candidates).read_text())
    nf_npts = doc["nf_npts"]
    cdir = Path(a.corners)
    results, bands, problems = {}, {}, []
    for e in doc["candidates"]:
        if e.get("infeasible"):
            problems.append(f"{e['candidate']}/{e['qcase']}: synthesis infeasible ({e['infeasible']})")
            continue
        try:
            r = reduce_one(cdir, e["stem"], nf_npts)
        except (OSError, ValueError, KeyError) as ex:
            problems.append(f"{e['candidate']}/{e['qcase']}: {ex}")
            continue
        results[(e["candidate"], e["qcase"])] = r["metrics"]
        bands[(e["candidate"], e["qcase"])] = r["band"]
    order = rank_topologies(results)
    rank_of = {c: i + 1 for i, c in enumerate(order)}
    with open(a.candidates_csv, "w", newline="") as fh:
        w = csv.writer(fh, lineterminator="\n")
        w.writerow(CAND_COLS)
        for e in doc["candidates"]:
            key = (e["candidate"], e["qcase"])
            m = results.get(key)
            if m is None:
                continue
            v = row_verdicts(m)
            ser, sh = _elem_text(e)
            p = e["predicted"][MID]
            w.writerow([
                rank_of.get(e["candidate"], ""), e["candidate"], e["qcase"], e["input_topology"],
                e["target"], e["output"], f"{e['zs_target'][0]:.4f}{e['zs_target'][1]:+.4f}j",
                ser, sh, _f(e["input_r"]),
                _f(e["lc"] * 1e9), e["lc_em"] or ("ideal" if e["q"] is None else f"Q={e['q']:g}"),
                _f(e["r_lc"]) if e["r_lc"] is not None else "EM",
                _f(e["cp_out"] * 1e12), _f(e["cs_out"] * 1e12),
                _f(p["s11_db"], 2), _f(p["s22_db"], 2), _f(p["nf290_db"]),
                _f(m["s11_db_mid"], 2), _f(m["s11_db_worst"], 2), _f(m["s22_db_mid"], 2),
                _f(m["s22_db_worst"], 2), _f(m["s21_db_mid"]), _f(m["s21_db_min"]), _f(m["s21_db_max"]),
                _f(m["s12_db_max"], 2), _f(m["nf290_db_mid"]), _f(m["nf290_db_worst"]),
                f"{m['nf290_f_worst_hz']:.6g}", _f(m["nfmin290_db_mid"]), _f(m["mu_band_min"], 9),
                _f(m["k_band_min"], 4), _f(m["mu_bb_min"], 9), f"{m['mu_bb_f_min_hz']:.4g}",
                m["mu_bb_n_lt1"], m["n_stab_pts"], _f(m["k_bb_min"], 4), _f(m["s11_mag_bb_max"], 9),
                _f(m["s22_mag_bb_max"], 9), _f(m["gt_minus_s21_db_mid"], 4),
                _f(m["ic1"] * 1e3), _f(m["pdc"] * 1e3),
                *(_f(v[r]) for r in ("S11", "S22", "S21", "NF", "mu")), sum(v.values()),
                e["feasibility"]["Le"], e["feasibility"].get("Lb", e["feasibility"].get("Lp")),
                e["feasibility"]["Lc"],
            ])
    with open(a.band_csv, "w", newline="") as fh:
        w = csv.writer(fh, lineterminator="\n")
        w.writerow(["candidate", "qcase", "freq_hz", "s11_db", "s21_db", "s12_db", "s22_db",
                    "nf_sp_db", "nfmin290_db", "mu", "k", "delta_mag"])
        for (cand, qc), band in bands.items():
            for b in band:
                w.writerow([cand, qc, f"{b['f']:.6g}", _f(b["s11_db"]), _f(b["s21_db"]), _f(b["s12_db"]),
                            _f(b["s22_db"]), _f(b["nf_sp_db"]), _f(b["nfmin290_db"]), _f(b["mu"], 9),
                            _f(b["k"], 4), _f(b["delta"], 6)])
    write_markdown(a.markdown, doc, results, order, problems)
    print(f"reduce: {len(results)} candidates reduced; ranking (q10 basis): {order}")
    if problems:
        for p in problems:
            print(f"reduce: PROBLEM {p}", file=sys.stderr)
        return 1
    return 0


def write_markdown(path, doc, results, order, problems):
    ch = doc["characterization"]
    L = []
    L.append("#### Characterization (nominal cell, band centre 2.44175 GHz)")
    L.append("")
    L.append("| Le-loss case | Zin at rfin (Ohm) | Zopt (Ohm) | Rn (Ohm) | NFmin @290 K (dB) | NF into 50 Ohm (sp, 300.15 K ref, dB) | Ydev (S) | S12 (dB) |")
    L.append("|---|---|---|---|---|---|---|---|")
    for c, v in ch["cases"].items():
        L.append(f"| {c} | {v['zin_mid']} | {v['zopt_mid']} | {v['rn_mid']:.3f} | {v['nfmin290_mid_db']:.4f} "
                 f"| {v['nf_sp_50ohm_mid_db']:.4f} | {v['ydev_mid']} | {v['s12_db_mid']:.2f} |")
    L.append("")
    L.append("Ideal-Le sweep at the band centre -- degeneration as an input-match lever, as committed "
             "(R3b = 330 Ohm feeds the base from the AC-grounded `bref` node) and in the what-if probe with "
             f"R3b's RF path choked (DC unchanged: I_C1 {ch['op']['ic1'] * 1e3:.4f} mA as committed, "
             f"{ch['feed_op']['ic1'] * 1e3:.4f} mA choked):")
    L.append("")
    L.append("| Le (nH) | Zin, committed (Ohm) | Zopt, committed (Ohm) | NFmin290, committed (dB) "
             "| Zin, R3b choked (Ohm) | Zopt, R3b choked (Ohm) | NFmin290, R3b choked (dB) |")
    L.append("|---|---|---|---|---|---|---|")
    for s, w in zip(ch["le_sweep"], ch["feed_sweep"]):
        zo1 = z_from_s(complex(s["gopt_r"], s["gopt_i"]))
        zo2 = z_from_s(complex(w["gopt_r"], w["gopt_i"]))
        L.append(f"| {s['le_nh']:g} | {s['zin_r']:.1f}{s['zin_i']:+.1f}j | {_fmtc(zo1)[:-1]}j "
                 f"| {nf_reref(s['nfmin_t_db'], T_ANALYSIS):.4f} | {w['zin_r']:.1f}{w['zin_i']:+.1f}j "
                 f"| {_fmtc(zo2)[:-1]}j | {nf_reref(w['nfmin_t_db'], T_ANALYSIS):.4f} |")
    L.append("")
    L.append("EM-extracted inductor geometries at 2.44175 GHz (one-port, la and sub grounded):")
    L.append("")
    L.append("| Geometry | turns | outer diameter (um) | L (nH) | Q |")
    L.append("|---|---|---|---|---|")
    for g, v in ch["em_mid"].items():
        L.append(f"| {g} | {v['nr_r']} | {v['outer_d_um']:.1f} | {v['l_nh']:.4f} | {v['q']:.2f} |")
    L.append("")
    L.append("#### Candidates (verified by single-cell ngspice runs)")
    L.append("")
    L.append("| Candidate | Q case | input elements | Lc | output C | S11 worst | S22 worst | S21 min..max | NF290 worst | mu min 10M-30G | rows met (S11,S22,S21,NF,mu) |")
    L.append("|---|---|---|---|---|---|---|---|---|---|---|")
    for e in doc["candidates"]:
        m = results.get((e["candidate"], e["qcase"]))
        if m is None:
            continue
        v = row_verdicts(m)
        ser, sh = _elem_text(e)
        lc = (f"{e['lc_em']} ({e['lc'] * 1e9:.3f} nH)" if e["lc_em"] else f"{e['lc'] * 1e9:.3f} nH")
        oc = f"Cs {e['cs_out'] * 1e12:.4f} pF" + (f", Cp {e['cp_out'] * 1e12:.4f} pF" if e["cp_out"] > 0 else "")
        flags = ",".join(("Y" if v[r] else "n") for r in ("S11", "S22", "S21", "NF", "mu"))
        L.append(f"| {e['candidate']} | {e['qcase']} | {ser}, {sh} | {lc} | {oc} | {m['s11_db_worst']:.2f} dB "
                 f"| {m['s22_db_worst']:.2f} dB | {m['s21_db_min']:.2f}..{m['s21_db_max']:.2f} dB "
                 f"| {m['nf290_db_worst']:.3f} dB | {m['mu_bb_min']:.9f} @ {m['mu_bb_f_min_hz'] / 1e6:.4g} MHz ({m['mu_bb_n_lt1']}/{m['n_stab_pts']} pts <= 1) "
                 f"| {flags} ({sum(v.values())}/5) |")
    L.append("")
    L.append("Solver prediction (unilateral, from the characterization data) vs. the verification run, band centre:")
    L.append("")
    L.append("| Candidate | Q case | S11 pred / sim (dB) | S22 pred / sim (dB) | NF290 pred / sim (dB) | I_C1 (mA) | P_dc (mW) | max\\|S11\\| / max\\|S22\\| 10M-30G | 2-element Lc+series-C would need Lc (nH) |")
    L.append("|---|---|---|---|---|---|---|---|---|")
    for e in doc["candidates"]:
        m = results.get((e["candidate"], e["qcase"]))
        if m is None:
            continue
        p = e["predicted"][MID]
        o1 = e.get("o1_lc_required_nh")
        L.append(f"| {e['candidate']} | {e['qcase']} | {p['s11_db']:.1f} / {m['s11_db_mid']:.1f} "
                 f"| {p['s22_db']:.1f} / {m['s22_db_mid']:.1f} | {p['nf290_db']:.3f} / {m['nf290_db_mid']:.3f} "
                 f"| {m['ic1'] * 1e3:.4f} | {m['pdc'] * 1e3:.4f} | {m['s11_mag_bb_max']:.9f} / {m['s22_mag_bb_max']:.9f} "
                 f"| {'' if o1 is None else f'{o1:.2f}'} |")
    L.append("")
    L.append("Inductor feasibility against the three EM-extracted geometries (L and Q at 2.44175 GHz above):")
    L.append("")
    L.append("| Candidate | Q case | Le (1 nH) | input matching L | Lc |")
    L.append("|---|---|---|---|---|")
    for e in doc["candidates"]:
        if (e["candidate"], e["qcase"]) not in results or e["qcase"] not in ("q10", "em"):
            continue
        fz = e["feasibility"]
        lin_key = "Lb" if "Lb" in fz else "Lp"
        L.append(f"| {e['candidate']} | {e['qcase']} | {fz['Le']} | {lin_key} {e['input_l'] * 1e9:.3f} nH: {fz[lin_key]} "
                 f"| {fz['Lc']} |")
    L.append("")
    L.append("Ranking (basis: the q10 case -- rows met, then lower worst NF290, then higher broadband mu): "
             + ", ".join(f"{i + 1}. `{c}`" for i, c in enumerate(order)))
    if problems:
        L.append("")
        L.append("**Problems (not silently dropped):**")
        for p in problems:
            L.append(f"- {p}")
    Path(path).write_text("\n".join(L) + "\n")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    g = sub.add_parser("gen-char")
    add_pdk_args(g)
    g.add_argument("--snapdir", required=True)
    g.add_argument("--outdir", required=True, help="corners dir the deck writes its wrdata into")
    s = sub.add_parser("solve")
    add_pdk_args(s)
    s.add_argument("--snapdir", required=True)
    s.add_argument("--outdir", required=True)
    s.add_argument("--nf-npts", type=int, default=N_NF_DEFAULT)
    s.add_argument("--xout-rdc", default="",
                   help="comma list of DC-reference resistances (Ohm) from xout to ground; "
                        "one deck per value (empty: historical floating-xout deck)")
    s.add_argument("--only", default="", help="comma list of <candidate>:<qcase> to render (default: all)")
    s.add_argument("--char-dir", default="",
                   help="read the characterization data from this dir instead of --outdir")
    n = sub.add_parser("sensitivity")
    n.add_argument("--candidates", required=True)
    n.add_argument("--corners", required=True)
    n.add_argument("--baseline-corners", required=True)
    n.add_argument("--csv", required=True)
    n.add_argument("--markdown", required=True)
    r = sub.add_parser("reduce")
    r.add_argument("--candidates", required=True)
    r.add_argument("--corners", required=True)
    r.add_argument("--candidates-csv", required=True)
    r.add_argument("--band-csv", required=True)
    r.add_argument("--markdown", required=True)
    a = ap.parse_args(argv)
    if a.cmd == "gen-char":
        cmd_gen_char(a)
        return 0
    if a.cmd == "solve":
        cmd_solve(a)
        return 0
    if a.cmd == "sensitivity":
        return cmd_sensitivity(a)
    return cmd_reduce(a)


if __name__ == "__main__":
    sys.exit(main())
