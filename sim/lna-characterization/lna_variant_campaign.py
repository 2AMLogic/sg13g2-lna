#!/usr/bin/env python3
"""Inductor-loss variant campaign for design/lna.sch (issue #56), plus the
matched-DUT two-tone IIP3 campaign (issue #337).

Companion to run_lna_variant.sh / run_lna_iip3.sh. Subcommands:

  gen           write, for one record id, every variant's bench netlists and
                `klt sim` request files under netlist-snapshots/<record-id>/
                (--analyses selects a subset of op/sp_band/sp_stab/noise)
  gen-iip3      write the two-tone IIP3 bench (the ratified
                testbench/tb_lna_iip3.spice.tmpl protocol as a `klt sim`
                request; template unchanged) plus the variant's op request,
                for the drive levels run_lna_sweep.sh's phase 2 uses
  collect-set   the single reader of a `klt sim --batch-set` envelope shared
                by run_lna_variant.sh and run_lna_iip3.sh (issue #454): copy
                each member's report to the per-request path the reducers
                read and list the failed members. stdout is the failure list
                (`<stem> <exit_code>` per failed member, envelope order),
                stderr the per-member diagnostics; exit 1 only when the
                envelope itself cannot be read
  summarize     turn the `klt sim` JSON reports under corners/<record-id>/
                into records/<record-id>-{summary,compare}.csv and the
                headline numbers the record .md quotes
  summarize-iip3  turn the IIP3 requests' reports + kept ngspice logs into
                records/<record-id>-iip3.csv (per point),
                records/<record-id>-iip3-summary.csv (per cell, IM3 slope
                check per README policy) and the record's IIP3 headlines

Why `klt sim` and not run_lna_sweep.sh's own ngspice pool: this campaign is a
45-cell PVT grid x several inductor variants, and on the Loom dispatch workers
(KLT_SIM_BACKEND=batch) a grid is expressed as a `klt sim` corners request so
it is submitted to the Spot batch fleet instead of being hand-launched on the
shared host. `klt sim` owns the single .control block and runs ONE analysis per
request, so the three analyses run_lna_sweep.sh does in one deck (in-band sp +
ngspice two-port NF, broadband sp stability, .noise NF at T0 = 290 K) become
three requests per variant:

  sp_band   sp lin 11 2.4e9 2.4835e9 1      (S-params, ngspice sp NF/NFmin)
  sp_stab   sp dec 40 1e7 3e10              (k / mu / |S11| / |S22| sweep)
  noise     noise v(nfout) vin lin 11 2.4e9 2.4835e9  (NF at T0 = 290 K)

The noise request samples the same 11 linear in-band points as sp_band by
default (issue #134; `--nf-npts` selects a denser odd grid for candidate final
matching networks). Every sample is retained as its own measurement
(nf290_db_f00 ..), nf290_db_lo/mid/hi are kept as cross-checks at the grid
points that coincide with the old three-point set, and the reducer reports the
worst SAMPLED NF with its frequency. Records produced before #134 are
three-point (lo/mid/hi) and stay as they are.

Bench definitions (identical to run_lna_sweep.sh / README.md, restated in each
generated netlist header): 50 Ohm at both ports (sp port sources with
portnum/z0, or a 50 Ohm Thevenin source with noiseless Rs/RL for .noise), the
DUT is design/netlist/lna.spice inlined verbatim except for the single
inductor edit each variant names, `.options gmin=1e-10`, same 45 PVT cells
(corner_label x temp x VDD) and the same corner-label -> cornerHBT/cornerMOShv
section map.
"""
from __future__ import annotations

import argparse
import csv
import importlib.util
import json
import math
import os
import re
import shutil
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import parse_lna_sweep as _sweep  # noqa: E402  (shares the #133 grid helpers)
REPO = HERE.parent.parent
DESIGN_NETLIST = REPO / "sim" / "pre-match-dut" / "lna.pre27.spice"
# The live (matched, issue #27) design netlist, used verbatim by the "matched" variant only.
LIVE_NETLIST = REPO / "design" / "netlist" / "lna.spice"
EM_MODEL = REPO / "sim" / "models" / "sg13g2_inductor_em.spice"

LABELS = ["typ", "bcs", "wcs", "sf", "fs"]
HBT = {"typ": "hbt_typ", "bcs": "hbt_bcs", "wcs": "hbt_wcs", "sf": "hbt_typ", "fs": "hbt_typ"}
MOS = {"typ": "mos_tt", "bcs": "mos_ff", "wcs": "mos_ss", "sf": "mos_sf", "fs": "mos_fs"}
TEMPS = [-40, 27, 125]
TEMPS_ALL = list(TEMPS)  # frozen full list; apply_temps filters from it so a slice can always recognize itself (issue #306)
VDDS = [1.62, 1.80, 1.98]
NOMINAL = ("typ", 27, 1.80)

F_LO, F_MID, F_HI = 2.4e9, 2.44175e9, 2.4835e9
N_BAND = 11  # index 5 is exactly F_MID
F_STAB_LO, F_STAB_HI, N_STAB_DEC = 1e7, 3e10, 40
# 290 K NF grid (issue #134): default = the S-parameter grid; denser grids
# must be odd and >= N_BAND so F_MID stays a grid point.
N_NF = N_BAND


def check_nf_npts(n: int) -> int:
    if not isinstance(n, int) or n < N_BAND or n % 2 == 0:
        raise SystemExit(f"nf-npts must be an odd integer >= {N_BAND} (got {n!r})")
    return n


def nf_freqs(n: int = N_NF) -> list[float]:
    """The 290 K NF frequency grid; same generator as the #133 validator."""
    return _sweep.expected_grid({"mode": "lin", "n": check_nf_npts(n), "lo": F_LO, "hi": F_HI})


def nf_sample_names(n: int = N_NF) -> list[str]:
    return [f"nf290_db_f{i:02d}" for i in range(n)]


def nf_grid_text(n: int = N_NF) -> str:
    step = (F_HI - F_LO) / (n - 1) / 1e6
    return (f"noise lin {n} pts {F_LO / 1e9:g}..{F_HI / 1e9:g} GHz ({step:.4g} MHz spacing); "
            "sampled maximum, not a continuous-band bound -- a peak narrower than the spacing can be missed")

# 5-turn device = the sibling extraction's p13 geometry (see sim/models/SOURCE.md
# and the model header's "Extracted" line).
LC_EM_INSTANCE = "inductor w=6.10u s=3.29u d=110.11u nr_r=5 mc_rsh=1.0 mc_rsub=1.0"
LE_NH = 1.0


def le_series_r(q: float) -> float:
    """Series R giving Q = wL/R at F_MID for Le = 1 nH."""
    return 2 * math.pi * F_MID * LE_NH * 1e-9 / q


# variant name -> (description, Lc model, Le Q or None)
VARIANTS = {
    "ideal": ("ideal Le and Lc (as committed)", "ideal", None),
    "lc_em": ("Lc = EM-extracted 5-turn model, Le ideal", "em", None),
    "le_q20": ("Le + series R for Q=20 @ 2.44175 GHz, Lc ideal", "ideal", 20),
    "le_q10": ("Le + series R for Q=10 @ 2.44175 GHz, Lc ideal", "ideal", 10),
    "le_q5": ("Le + series R for Q=5 @ 2.44175 GHz, Lc ideal", "ideal", 5),
    # The committed design/netlist/lna.spice (lp_noise matching network; its Q=10 loss
    # resistors are part of it), inlined verbatim with no variant edit. Run it together
    # with "ideal" (the frozen pre-match DUT) so the compare table has a baseline.
    "matched": ("committed matched DUT (design/netlist/lna.spice, verbatim)", "design", None),
    "lc_em_le_q10": ("Lc = EM 5-turn model AND Le Q=10", "em", 10),
}
ANALYSES = ["op", "sp_band", "sp_stab", "noise"]

# ---------------------------------------------------------------------------
# Two-tone IIP3 (issue #337): the ratified tb_lna_iip3.spice.tmpl protocol,
# expressed as a `klt sim` corner request so the 45-cell grid goes to the Spot
# batch fleet instead of being hand-launched. The template file itself is NOT
# changed (its bench definitions and .control sequence are reproduced verbatim
# below); the FFT-parameter derivation is run_lna_sweep.sh's, single-sourced
# here so the request, the record and the README cannot drift apart.
# ---------------------------------------------------------------------------
IIP3_TSTEP = 4e-12
IIP3_NFFT = 65536
IIP3_TSTART = 1e-6
IIP3_B1, IIP3_B2, IIP3_BIM3L, IIP3_BIM3H, IIP3_BIM5L, IIP3_BIM5H = (
    640, 642, 638, 644, 636, 646)
IIP3_DF = 1.0 / (IIP3_NFFT * IIP3_TSTEP)
IIP3_F1 = IIP3_B1 * IIP3_DF
IIP3_F2 = IIP3_B2 * IIP3_DF
IIP3_FIM3L = IIP3_BIM3L * IIP3_DF
IIP3_FIM3H = IIP3_BIM3H * IIP3_DF
IIP3_FSPACE = IIP3_F2 - IIP3_F1
IIP3_TWINDOW = (IIP3_NFFT - 1) * IIP3_TSTEP
IIP3_TSTOP = IIP3_TSTART + IIP3_TWINDOW
# Drive levels (V peak, open-circuit per tone): the two-level pair every PVT
# cell runs (so the 3:1 IM3 slope the extrapolation assumes is checked at
# every cell, not assumed at one), plus the nominal cell's extra levels for a
# 24 dB drive range at one cell -- run_lna_sweep.sh's AMPS_GRID and
# AMPS_NOMINAL_ONLY, restated.
IIP3_AMPS_GRID = (1e-3, 2e-3)
IIP3_AMPS_NOMINAL_ONLY = (5e-4, 4e-3, 8e-3)


def iip3_amp_label(amp: float) -> str:
    """run_lna_sweep.sh amp_label_of: 2e-3 -> 'a2mv', 5e-4 -> 'a0p5mv'."""
    s = ("%g" % (amp * 1e3)).replace(".", "p")
    return f"a{s}mv"


def iip3_control_kind() -> str:
    """The generated deck's analysis command sequence: the template's own
    .control block, verbatim, minus its `pre_osdi` lines (klt sim emits those
    itself from options.osdi_preload, hoisted ahead of the circuit parse) and
    minus the DUT-independent `set specwindow` (kept here). ngspice executes a
    deck's control lines in file order, and klt sim appends the request's
    measurements[].expr `let`/`print` pairs AFTER this sequence, so the exprs
    evaluate in the spectrum plot the template's `fft` command leaves current
    -- the same bin reads the template performs. `analysis.args` stays empty:
    the sequence rides in `kind` as one multi-line string, which the deck
    writer emits as-is."""
    return "\n".join([
        "set specwindow = none",
        "op",
        "let ic1 = @q.xa.xq1.qnpn13g2[ic]",
        "let ic2 = @q.xa.xq2.qnpn13g2[ic]",
        "let vce1 = v(xa.casc) - v(xa.e1)",
        "let vce2 = v(xa.outn) - v(xa.casc)",
        "let idd = -i(vdd)",
        'echo "OP ic1 $&ic1 ic2 $&ic2 vce1 $&vce1 vce2 $&vce2 idd $&idd"',
        f"tran {IIP3_TSTEP:g} {IIP3_TSTOP:.11g} {IIP3_TSTART:g} {IIP3_TSTEP:g}",
        "linearize v(rfout) v(vin)",
        "let npts = length(v(rfout))",
        'echo "NPTS $&npts"',
        "let tv = time",
        f"let w1 = 2*PI*{IIP3_F1!r}",
        f"let w2 = 2*PI*{IIP3_F2!r}",
        f"let w3 = 2*PI*{IIP3_FIM3L!r}",
        f"let w4 = 2*PI*{IIP3_FIM3H!r}",
        "let d1 = 2*sqrt(mean(v(rfout)*cos(w1*tv))^2 + mean(v(rfout)*sin(w1*tv))^2)",
        "let d2 = 2*sqrt(mean(v(rfout)*cos(w2*tv))^2 + mean(v(rfout)*sin(w2*tv))^2)",
        "let d3 = 2*sqrt(mean(v(rfout)*cos(w3*tv))^2 + mean(v(rfout)*sin(w3*tv))^2)",
        "let d4 = 2*sqrt(mean(v(rfout)*cos(w4*tv))^2 + mean(v(rfout)*sin(w4*tv))^2)",
        "let ds = 2*sqrt(mean(v(vin)*cos(w1*tv))^2 + mean(v(vin)*sin(w1*tv))^2)",
        'echo "DFT tone1 $&d1 tone2 $&d2 im3l $&d3 im3h $&d4 src1 $&ds"',
        "fft v(rfout) v(vin)",
    ])


def iip3_measurements() -> list[dict]:
    """The template's FFT bin reads, as measurements[].expr entries evaluated
    in the spectrum plot. tone1..src2 feed the reducer's IIP3 arithmetic;
    fft_df is the coherence witness (df = 1/(N*tstep), exact)."""
    out = [{"name": "fft_df", "expr": "frequency[1] - frequency[0]"}]
    for name, vec, bin_ in (
        ("tone1", "v(rfout)", IIP3_B1), ("tone2", "v(rfout)", IIP3_B2),
        ("im3l", "v(rfout)", IIP3_BIM3L), ("im3h", "v(rfout)", IIP3_BIM3H),
        ("im5l", "v(rfout)", IIP3_BIM5L), ("im5h", "v(rfout)", IIP3_BIM5H),
        ("src1", "v(vin)", IIP3_B1), ("src2", "v(vin)", IIP3_B2),
    ):
        out.append({"name": name, "expr": f"mag({vec})[{bin_}]"})
    return out


def iip3_netlist(variant: str, amp: float) -> str:
    """The template's port section (two series sin() generators = one
    Thevenin source behind Rs = 50 Ohm, RL = 50 Ohm) around the variant's
    verbatim DUT. Vdd sits at the nominal 1.8 V here; klt sim `alter`s it per
    corner exactly as for every other request."""
    desc, lc, _le_q = VARIANTS[variant]
    parts = [
        f"* sg13g2-lna two-tone IIP3 bench (issue #337): variant={variant} amp={amp:g} V peak/tone\n"
        "* Generated by sim/lna-characterization/lna_variant_campaign.py (gen-iip3) -- do not edit.\n"
        f"* Variant: {desc}\n"
        f"* DUT: {'design/netlist/lna.spice (matched) sha256 ' + sha256(LIVE_NETLIST) if lc == 'design' else 'sim/pre-match-dut/lna.pre27.spice (frozen pre-match) sha256 ' + sha256(DESIGN_NETLIST)}, inlined verbatim\n"
        "*   except the inductor edit(s) marked 'VARIANT EDIT'.\n"
        "* Bench: the ratified testbench/tb_lna_iip3.spice.tmpl protocol (template unchanged).\n"
        f"*   Tones f1 = {IIP3_F1!r} Hz (bin {IIP3_B1}), f2 = {IIP3_F2!r} Hz (bin {IIP3_B2}),\n"
        f"*   spacing {IIP3_FSPACE!r} Hz; IM3 at bins {IIP3_BIM3L}/{IIP3_BIM3H}, IM5 floor sentinels at\n"
        f"*   bins {IIP3_BIM5L}/{IIP3_BIM5H}. FFT: tstep {IIP3_TSTEP:g} s, N = {IIP3_NFFT}, rectangular window,\n"
        f"*   df = 1/(N*tstep) = {IIP3_DF!r} Hz, tstart = {IIP3_TSTART:g} s discarded.\n"
        "*   Powers: available source power per tone A^2/(8*Rs); output V_peak^2/(2*RL);\n"
        "*   IIP3 = Pin + (Pout - PIM3)/2. Port convention: 50 Ohm both ports.\n"
        "* Bias: VDD per corner via klt sim `alter vdd`; corners/sections per the\n"
        f"*   sibling {variant}_iip3_*.request.json. Definitions in full: README.md.\n",
        ".options gmin=1e-10 tnom=27\n",
        dut_subckt(lc, None),
        "Vdd vdd 0 dc 1.8\n",
        "* Two tone generators in series form the Thevenin source; Rs = 50 Ohm.\n",
        f"Vt1 vin va dc 0 sin(0 {amp:g} {IIP3_F1!r} 0 0 0)\n",
        f"Vt2 va 0 dc 0 sin(0 {amp:g} {IIP3_F2!r} 0 0 0)\n",
        "Rs vin rfin 50\n",
        "RL rfout 0 50\n",
        "Xa vdd 0 rfin rfout lna\n",
    ]
    return "".join(parts)


def iip3_request(variant: str, amp: float, netlist_name: str, smoke: bool,
                 backend: str | None, nominal_only: bool = False) -> dict:
    """The IIP3 corner request. `nominal_only` pins the grid to the nominal
    cell (run_lna_sweep.sh's AMPS_NOMINAL_ONLY levels run there alone).
    remote.hosts shards the 45-cell grid into fleet jobs of <= 3 units so one
    job stays inside the fleet's whole-job ceiling (3 x 900 s + overhead)."""
    labels = ["typ"] if smoke or nominal_only else LABELS
    temps = [27] if smoke or nominal_only else TEMPS
    vdds = [1.80] if smoke or nominal_only else VDDS
    process = [
        {
            "name": lab,
            "sections": [
                {"lib": "libs.tech/ngspice/models/cornerHBT.lib", "section": HBT[lab]},
                {"lib": "libs.tech/ngspice/models/cornerMOShv.lib", "section": MOS[lab]},
            ],
        }
        for lab in labels
    ]
    osdi = [f"$PDK_ROOT/ihp-sg13g2/libs.tech/ngspice/osdi/{f}" for f in
            ("psp103.osdi", "psp103_nqs.osdi", "mosvar.osdi")]
    n_units = len(labels) * len(temps) * len(vdds)
    req = {
        "netlist": netlist_name,
        "models": {"pdk": "ihp-sg13g2"},
        "corners": {"process": process, "supply_v": {"vdd": vdds}, "temperature_c": temps},
        "analysis": {"kind": iip3_control_kind(), "args": ""},
        "measurements": iip3_measurements(),
        "options": {
            "timeout_s": 900,
            "keep_artifacts": True,
            "osdi_preload": osdi,
            "stage_model_inputs": True,
            "ngspice_init": ["set numdgt=8"],
        },
        "remote": {"hosts": 1 if n_units <= 3 else 15},
    }
    if backend:
        req["backend"] = backend
    return req


# DC operating point, measured per variant per cell (issue #56, prompted by the
# #186/#188 note on this issue). The `le_q*` variants model Le's loss as a
# SERIES resistor, `Le e1 le_x 1n` + `Rle le_x vss R`, and that resistor carries
# Q1's DC emitter current: it adds real emitter degeneration the mirror
# reference Q3 does not see, so it moves the bias point as well as adding RF
# loss. Without an OP measurement a gain or NF delta from one of those variants
# cannot be attributed to inductor loss alone -- the confound is invisible in
# the sp/noise reports. `ve1` is the measurement that exposes it directly: the
# DC voltage the loss resistor lifts the emitter node to (0 V for every ideal-Le
# variant, since an ideal inductor is a DC short). Instance `Xa` is the DUT in
# every op netlist, as in the sp netlists.
OP_MEASUREMENTS = [
    # name, expr, unit
    ("ic1", "@q.xa.xq1.qnpn13g2[ic]", "A"),
    ("ic2", "@q.xa.xq2.qnpn13g2[ic]", "A"),
    ("ib1", "@q.xa.xq1.qnpn13g2[ib]", "A"),
    ("ve1", "v(xa.e1)", "V"),
    ("vbe1", "v(xa.b1) - v(xa.e1)", "V"),
    ("vce1", "v(xa.casc) - v(xa.e1)", "V"),
    ("vce2", "v(xa.outn) - v(xa.casc)", "V"),
    ("idd", "-i(vdd)", "A"),
    ("pdc", "v(vdd)*(-i(vdd))", "W"),
]

# Bias-attribution bound (README "Bias confound"): if a variant's I_C1 is
# within +/- this many percent of `ideal` at every cell, its RF deltas are
# attributable to inductor loss alone; beyond it they are not. Single-sourced
# here so the threshold comparison and the headline text that quotes it
# cannot drift apart. Changing the value is a spec change (README).
IC1_ATTRIB_PCT = 0.05

LE_LINE = "Le e1 vss 1n m=1"
LC_LINE = "Lc vdd outn 5n m=1"


# Shared file-digest helper, loaded by explicit path so `python3 -I` works
# (isolated mode does not put the script directory on sys.path).
_as_spec = importlib.util.spec_from_file_location(
    "artifact_store", Path(__file__).resolve().parent.parent / "tools" / "artifact_store.py")
_artifact_store = importlib.util.module_from_spec(_as_spec)
_as_spec.loader.exec_module(_artifact_store)
sha256 = _artifact_store.sha256_file


def dut_subckt(lc: str, le_q) -> str:
    """design/netlist/lna.spice as run_lna_sweep.sh inlines it, plus the one
    inductor edit the variant names. Returns the subckt text."""
    text = (LIVE_NETLIST if lc == "design" else DESIGN_NETLIST).read_text()
    out = []
    for line in text.splitlines():
        if line.startswith("**.subckt"):
            line = line[2:]
        elif line.startswith("**.ends"):
            line = line[2:]
        elif line == ".end":
            continue
        out.append(line)
    body = "\n".join(out) + "\n"
    if lc == "design":
        return body
    if body.count(LE_LINE) != 1 or body.count(LC_LINE) != 1:
        raise SystemExit(f"design netlist no longer carries '{LE_LINE}' / '{LC_LINE}' exactly once")
    if lc == "em":
        body = body.replace(
            LC_LINE,
            "* VARIANT EDIT: ideal 'Lc vdd outn 5n' replaced by the EM-extracted 5-turn model\n"
            f"XLc vdd outn vss {LC_EM_INSTANCE}",
        )
    if le_q is not None:
        r = le_series_r(le_q)
        body = body.replace(
            LE_LINE,
            f"* VARIANT EDIT: ideal Le gets a series R = {r:.5f} Ohm (Q = {le_q} at 2.44175 GHz)\n"
            "Le e1 le_x 1n m=1\n"
            f"Rle le_x vss {r:.5f}",
        )
    return body


def header(variant: str, analysis: str) -> str:
    desc, lc, le_q = VARIANTS[variant]
    return (
        f"* sg13g2-lna inductor-loss variant bench (issue #56): variant={variant} analysis={analysis}\n"
        "* Generated by sim/lna-characterization/lna_variant_campaign.py (gen) -- do not edit.\n"
        f"* Variant: {desc}\n"
        + (f"* DUT: design/netlist/lna.spice (matched) sha256 {sha256(LIVE_NETLIST)}, inlined verbatim.\n"
           if lc == "design" else
           f"* DUT: sim/pre-match-dut/lna.pre27.spice (frozen pre-match) sha256 {sha256(DESIGN_NETLIST)}, inlined verbatim\n"
           "*   except the inductor edit(s) marked 'VARIANT EDIT'.\n")
        +
        "* Port convention: 50 Ohm at both ports. Bias: VDD per corner via klt sim `alter vdd`.\n"
        "* Analysis, corners, model sections: see the sibling <variant>_<analysis>.request.json.\n"
        "* Bench definitions in full: sim/lna-characterization/README.md.\n"
    )


def netlist(variant: str, analysis: str, rel_model: str) -> str:
    desc, lc, le_q = VARIANTS[variant]
    parts = [header(variant, analysis), ".options gmin=1e-10 tnom=27\n"]
    if lc == "em":
        parts.append(f'.include "{rel_model}"\n')
    parts.append(dut_subckt(lc, le_q))
    parts.append("Vdd vdd 0 dc 1.8\n")
    if analysis.startswith("sp") or analysis == "op":
        parts.append(
            "Vp1 pin 0 dc 0 ac 1 portnum 1 z0 50\n"
            "Vp2 pout 0 dc 0 ac 0 portnum 2 z0 50\n"
            "Xa vdd 0 pin pout lna\n"
        )
    else:
        parts.append(
            "Vin vin 0 dc 0 ac 1\n"
            "Rs vin nfin 50 noisy=0\n"
            "RL nfout 0 50 noisy=0\n"
            "Xb vdd 0 nfin nfout lna\n"
        )
    return "".join(parts)


S = "s_1_1 s_2_1 s_1_2 s_2_2".split()
DLT = "(s_1_1*s_2_2 - s_1_2*s_2_1)"
MU = f"((1 - mag(s_1_1)^2)/(mag(s_2_2 - conj(s_1_1)*{DLT}) + mag(s_1_2*s_2_1)))"
K = f"((1 - mag(s_1_1)^2 - mag(s_2_2)^2 + mag({DLT})^2)/(2*mag(s_1_2*s_2_1)))"
MID = (N_BAND - 1) // 2


def measurements(analysis: str, nf_npts: int = N_NF):
    if analysis == "op":
        return [{"name": n, "expr": e, "unit": u} for n, e, u in OP_MEASUREMENTS]
    m = []

    def add(name, expr, unit=""):
        d = {"name": name, "expr": expr}
        if unit:
            d["unit"] = unit
        m.append(d)

    if analysis == "sp_band":
        add("s21_db_mid", f"db(s_2_1)[{MID}]", "dB")
        add("s21_db_min", "vecmin(db(s_2_1))", "dB")
        add("s21_db_max", "vecmax(db(s_2_1))", "dB")
        add("s11_db_mid", f"db(s_1_1)[{MID}]", "dB")
        add("s11_db_worst", "vecmax(db(s_1_1))", "dB")
        add("s22_db_mid", f"db(s_2_2)[{MID}]", "dB")
        add("s22_db_worst", "vecmax(db(s_2_2))", "dB")
        add("s12_db_mid", f"db(s_1_2)[{MID}]", "dB")
        add("mu_band_min", f"vecmin({MU})")
        add("k_band_min", f"vecmin({K})")
        add("nf_sp_db_mid", f"real(NF[{MID}])", "dB")
        add("nf_sp_db_worst", "vecmax(real(NF))", "dB")
        add("nfmin_sp_db_mid", f"real(NFmin[{MID}])", "dB")
    elif analysis == "sp_stab":
        add("mu_min", f"vecmin({MU})")
        add("n_mu_lt1", f"mean({MU} lt 1)*length(frequency)")
        add("f_mu_lt1_lo_hz", f"vecmin(mag(frequency) + 1e12*({MU} ge 1))", "Hz")
        add("f_mu_lt1_hi_hz", f"vecmax(mag(frequency)*({MU} lt 1))", "Hz")
        add("k_min", f"vecmin({K})")
        add("n_k_lt1", f"mean({K} lt 1)*length(frequency)")
        add("s11_mag_max", "vecmax(mag(s_1_1))")
        add("s22_mag_max", "vecmax(mag(s_2_2))")
        add("n_s22_gt1", "mean(mag(s_2_2) gt 1.000001)*length(frequency)")
        add("s11_mag_gt1_n", "mean(mag(s_1_1) gt 1.000001)*length(frequency)")
        add("n_pts", "length(frequency)")
    elif analysis == "noise":
        nf = "10*log10(1 + (noise1.inoise_spectrum^2)/(4*1.380649e-23*290*50))"
        n = check_nf_npts(nf_npts)
        add("nf290_db_lo", f"({nf})[0]", "dB")
        add("nf290_db_mid", f"({nf})[{(n - 1) // 2}]", "dB")
        add("nf290_db_hi", f"({nf})[{n - 1}]", "dB")
        add("nf290_db_worst", f"vecmax({nf})", "dB")
        for i, name in enumerate(nf_sample_names(n)):
            add(name, f"({nf})[{i}]", "dB")
    return m


def analysis_card(analysis: str, nf_npts: int = N_NF) -> dict:
    if analysis == "op":
        return {"kind": "op", "args": ""}
    if analysis == "sp_band":
        return {"kind": "sp", "args": f"lin {N_BAND} {F_LO:g} {F_HI:g} 1"}
    if analysis == "sp_stab":
        return {"kind": "sp", "args": f"dec {N_STAB_DEC} {F_STAB_LO:g} {F_STAB_HI:g}"}
    return {"kind": "noise", "args": f"v(nfout) vin lin {check_nf_npts(nf_npts)} {F_LO:g} {F_HI:g}"}


def request(variant: str, analysis: str, netlist_name: str, smoke: bool, backend: str | None,
            nf_npts: int = N_NF) -> dict:
    labels = ["typ"] if smoke else LABELS
    temps = [27] if smoke else TEMPS
    vdds = [1.80] if smoke else VDDS
    process = [
        {
            "name": lab,
            "sections": [
                {"lib": "libs.tech/ngspice/models/cornerHBT.lib", "section": HBT[lab]},
                {"lib": "libs.tech/ngspice/models/cornerMOShv.lib", "section": MOS[lab]},
            ],
        }
        for lab in labels
    ]
    osdi = [f"$PDK_ROOT/ihp-sg13g2/libs.tech/ngspice/osdi/{f}" for f in
            ("psp103.osdi", "psp103_nqs.osdi", "mosvar.osdi")]
    req = {
        "netlist": netlist_name,
        "models": {"pdk": "ihp-sg13g2"},
        "corners": {"process": process, "supply_v": {"vdd": vdds}, "temperature_c": temps},
        "analysis": analysis_card(analysis, nf_npts),
        "measurements": measurements(analysis, nf_npts),
        "options": {
            "timeout_s": 900,
            "keep_artifacts": True,
            "osdi_preload": osdi,
            "stage_model_inputs": True,
            "ngspice_init": ["set numdgt=8"],
        },
    }
    if backend:
        req["backend"] = backend
    return req


def cmd_gen(a):
    out = Path(a.outdir)
    out.mkdir(parents=True, exist_ok=True)
    rel_model = os.path.relpath(EM_MODEL, out)
    names = a.variants.split(",") if a.variants else list(VARIANTS)
    for v in names:
        if v not in VARIANTS:
            raise SystemExit(f"unknown variant {v}")
    analyses = [x for x in (getattr(a, "analyses", "") or "").split(",") if x]
    bad = [x for x in analyses if x not in ANALYSES]
    if bad:
        raise SystemExit(f"gen: unknown analysis(es) {bad}; choose from {ANALYSES}")
    for v in names:
        for an in (analyses or ANALYSES):
            nl = out / f"{v}_{an}.spice"
            nl.write_text(netlist(v, an, rel_model))
            rq = out / f"{v}_{an}.request.json"
            rq.write_text(json.dumps(request(v, an, nl.name, a.smoke, a.backend, a.nf_npts), indent=2) + "\n")
    print(f"gen: wrote {len(names) * len(analyses or ANALYSES)} request/netlist pairs in {out}")


def _parse_amps(spec: str, what: str) -> list[float]:
    amps = []
    for tok in (spec or "").split(","):
        if not tok:
            continue
        try:
            v = float(tok)
        except ValueError:
            raise SystemExit(f"{what}: not a number: {tok!r}")
        if not 0 < v <= 0.1:
            raise SystemExit(f"{what}: {v!r} is not a plausible per-tone V peak (0, 0.1]")
        amps.append(v)
    if not amps:
        raise SystemExit(f"{what}: at least one level is required")
    return amps


def cmd_gen_iip3(a):
    out = Path(a.outdir)
    out.mkdir(parents=True, exist_ok=True)
    names = a.variants.split(",") if a.variants else ["matched"]
    for v in names:
        if v not in VARIANTS:
            raise SystemExit(f"unknown variant {v}")
    grid_amps = _parse_amps(a.amps, "--amps")
    extra_amps = _parse_amps(a.amps_nominal_only, "--amps-nominal-only") if a.amps_nominal_only else []
    clash = sorted(set(grid_amps) & set(extra_amps))
    if clash:
        raise SystemExit(f"gen-iip3: level(s) {clash} declared both per-cell and nominal-only")
    n = 0
    for v in names:
        if a.op:
            nl = out / f"{v}_op.spice"
            nl.write_text(netlist(v, "op", os.path.relpath(EM_MODEL, out)))
            rq = out / f"{v}_op.request.json"
            rq.write_text(json.dumps(request(v, "op", nl.name, a.smoke, a.backend), indent=2) + "\n")
            n += 1
        for amp in grid_amps + extra_amps:
            label = iip3_amp_label(amp)
            nl = out / f"{v}_iip3_{label}.spice"
            nl.write_text(iip3_netlist(v, amp))
            rq = out / f"{v}_iip3_{label}.request.json"
            rq.write_text(json.dumps(
                iip3_request(v, amp, nl.name, a.smoke, a.backend,
                             nominal_only=amp in extra_amps), indent=2) + "\n")
            n += 1
    print(f"gen-iip3: wrote {n} request/netlist pairs in {out}"
          f" (per-cell levels {[iip3_amp_label(x) for x in grid_amps]},"
          f" nominal-only {[iip3_amp_label(x) for x in extra_amps]})")


# ---------------------------------------------------------------------------
# summarize
# ---------------------------------------------------------------------------

def load_report(path: Path) -> dict:
    return json.loads(path.read_text())


def corner_key(c: dict):
    """Normalise a report corner to (label, temp, vdd)."""
    proc = c.get("process")
    if isinstance(proc, dict):
        proc = proc.get("name")
    temp = c.get("temperature_c", c.get("temp_c"))
    sup = c.get("supply_v")
    if isinstance(sup, dict):
        sup = sup.get("vdd")
    return proc, float(temp), float(sup)


def corner_values(c: dict) -> dict:
    out = {}
    for m in c.get("measurements", []):
        out[m["name"]] = m.get("value")
    return out


def fmt(x, nd=4):
    if x is None:
        return ""
    return f"{x:.{nd}f}"


# --- expected grid, validation and ideal-baseline row coverage (issue #87) ---

OK_STATUSES = {"ok", "pass", "passed", "success", "succeeded", "completed", "complete"}
GRID_FULL = "full"
GRID_SMOKE = "smoke"


def norm_key(label, temp, vdd):
    return (label, float(temp), round(float(vdd), 4))


def expected_grid(grid: str = GRID_FULL):
    """Expected (label, temp, vdd) cells, derived from the generator constants
    (the same ones request() uses), in canonical order."""
    if grid == GRID_SMOKE:
        return [norm_key(*NOMINAL)]
    return [norm_key(lab, t, v) for lab in LABELS for t in TEMPS for v in VDDS]


def cell_text(key):
    return f"{key[0]}/{key[1]:g}C/{key[2]:.2f}V"


def is_finite_number(x):
    return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)


def cell_status_ok(c: dict):
    """(ok, detail). A cell is failed on a non-ok status string or an error field."""
    st = c.get("status")
    if c.get("error"):
        return False, f"error={c.get('error')!r}"
    if st is not None and str(st).strip().lower() not in OK_STATUSES:
        return False, f"status={st!r}"
    return True, ""


def validate_report_cells(corners, expected_keys, expected_measurements, emit, check_cell=None):
    """Shared two-pass `klt sim` corner-report cell validator (issue #480);
    used by this campaign's collect_reports and by the core-envelope
    reducer's read_requests.

    Pass 1 indexes `corners` against set(expected_keys): malformed_cell (an
    unindexable corner, including a measurement without a "name"),
    unexpected_cell, duplicate_cell (first occurrence retained, the
    duplicated key excluded from reduction; emitted in expected_keys
    order). Pass 2, only when `expected_measurements` is not None, walks
    each expected key: missing_cell, failed_cell, missing_measurement
    (absent name or null value), non_finite_value, duplicate_measurement,
    then optional `check_cell(key, values, emit) -> bool` when those checks
    all passed; a cell is valid only with no finding and no duplicated key.

    emit(kind, cell=None, measurement=None, detail="") records one issue;
    `cell` is the normalized key tuple, or a "corners[N]" string for
    malformed_cell. Returns (cells, valid_count), where cells maps each
    expected key present in the report to its first occurrence
    {values, status, ok, dup_meas[, valid]}.
    """
    keyset = set(expected_keys)
    cells, dups = {}, set()
    for idx, c in enumerate(corners):
        try:
            key = norm_key(*corner_key(c))
            values = corner_values(c)
        except Exception as e:  # noqa: BLE001
            emit("malformed_cell", cell=f"corners[{idx}]", detail=str(e))
            continue
        if key not in keyset:
            emit("unexpected_cell", cell=key)
            continue
        if key in cells:
            dups.add(key)
            continue
        names = [m.get("name") for m in c.get("measurements", [])]
        cells[key] = {"values": values, "status": c.get("status"), "ok": cell_status_ok(c),
                      "dup_meas": sorted({n for n in names if names.count(n) > 1})}
    for key in expected_keys:
        if key in dups:
            emit("duplicate_cell", cell=key,
                 detail="cell appears more than once; excluded from reduction")
    valid_count = 0
    if expected_measurements is None:
        return cells, valid_count
    for key in expected_keys:
        cell = cells.get(key)
        if cell is None:
            emit("missing_cell", cell=key)
            continue
        good = True
        ok, detail = cell["ok"]
        if not ok:
            emit("failed_cell", cell=key, detail=detail)
            good = False
        for n in expected_measurements:
            v = cell["values"].get(n)
            if n not in cell["values"]:
                emit("missing_measurement", cell=key, measurement=n)
                good = False
            elif v is None:
                emit("missing_measurement", cell=key, measurement=n, detail="value is null")
                good = False
            elif not is_finite_number(v):
                emit("non_finite_value", cell=key, measurement=n, detail=f"value={v!r}")
                good = False
        for n in cell["dup_meas"]:
            emit("duplicate_measurement", cell=key, measurement=n,
                 detail="measurement appears more than once in the cell")
            good = False
        if good and check_cell is not None and not check_cell(key, cell["values"], emit):
            good = False
        if key in dups:
            good = False
        cell["valid"] = good
        valid_count += good
    return cells, valid_count


_PASS1_CELL_KINDS = frozenset(("malformed_cell", "unexpected_cell", "duplicate_cell"))


def collect_reports(cdir: Path, required_variants, grid: str, nf_npts: int = N_NF):
    """Read *.report.json and validate each (variant, analysis) separately.

    Returns (cells, issues, counts):
      cells[(variant, analysis)] -> {key: {"values": {...}, "status": s}} for
          cells that are in the grid, first occurrences only (valid or not);
      issues -> list of dicts {kind, variant, analysis, cell, measurement, detail};
      counts[(variant, analysis)] -> {"expected", "valid"}.
    Nothing is dropped silently: every anomaly is an issue.
    """
    issues = []

    def make_issue(kind, variant, analysis, cell=None, measurement=None, detail=""):
        return {"kind": kind, "variant": variant, "analysis": analysis,
                "cell": cell_text(cell) if isinstance(cell, tuple) else cell,
                "measurement": measurement, "detail": detail}

    def check_nf(key, values, emit_fn):
        samples = [values[n] for n in nf_sample_names(nf_npts)]
        if abs(max(samples) - values["nf290_db_worst"]) > 1e-6:
            emit_fn("inconsistent_nf_worst", cell=key, measurement="nf290_db_worst",
                    detail=f"reported worst {values['nf290_db_worst']!r} != "
                           f"max of {nf_npts} retained samples {max(samples)!r}")
            return False
        return True

    grid_keys = expected_grid(grid)
    cells = {}
    seen_reports = set()
    pass2_issues = {}
    valid_counts = {}
    for rep in sorted(cdir.glob("*.report.json")):
        stem = rep.name[: -len(".report.json")]
        analysis = next((an for an in ANALYSES if stem.endswith("_" + an)), None)
        variant = stem[: -len(analysis) - 1] if analysis else None
        if analysis is None or variant not in VARIANTS:
            issues.append(make_issue("unexpected_report", variant, analysis, detail=rep.name))
            continue
        seen_reports.add((variant, analysis))
        try:
            data = load_report(rep)
            corners = data.get("corners", [])
            if not isinstance(corners, list):
                raise ValueError("'corners' is not a list")
        except Exception as e:  # unreadable/malformed report
            issues.append(make_issue("unreadable_report", variant, analysis, detail=f"{rep.name}: {e}"))
            continue

        names = ([m["name"] for m in measurements(analysis, nf_npts)]
                 if variant in required_variants else None)
        buf = pass2_issues.setdefault((variant, analysis), []) if names is not None else None

        def emit(kind, cell=None, measurement=None, detail=""):
            target = issues if (buf is None or kind in _PASS1_CELL_KINDS) else buf
            target.append(make_issue(kind, variant, analysis, cell=cell,
                                     measurement=measurement, detail=detail))

        cmap, valid = validate_report_cells(
            corners, grid_keys, names, emit,
            check_cell=check_nf if analysis == "noise" else None)
        cells[(variant, analysis)] = cmap
        if names is not None:
            valid_counts[(variant, analysis)] = valid
    counts = {}
    for variant in required_variants:
        for analysis in ANALYSES:
            if (variant, analysis) not in seen_reports:
                issues.append(make_issue("missing_report", variant, analysis,
                                         detail=f"no {variant}_{analysis}.report.json (or unreadable)"))
            elif (variant, analysis) in pass2_issues:
                issues.extend(pass2_issues[(variant, analysis)])
            else:
                # Report was present on disk but unreadable in pass 1: fan out
                # missing_cell across expected grid keys so uncovered cells are named.
                validate_report_cells(
                    [], grid_keys, [m["name"] for m in measurements(analysis, nf_npts)],
                    lambda kind, cell=None, measurement=None, detail="", v=variant, an=analysis:
                        issues.append(make_issue(kind, v, an, cell=cell,
                                                 measurement=measurement, detail=detail)))
            counts[(variant, analysis)] = {"expected": len(grid_keys),
                                           "valid": valid_counts.get((variant, analysis), 0)}
    return cells, issues, counts


# Ratified-row reductions of the ideal baseline: (row id, label, analysis,
# measurement, reduce, target text, comparator, threshold, sampling, spec row)
def row_reductions(nf_npts: int = N_NF):
    return [
        ("gain", "In-band minimum |S21| [dB]", "sp_band", "s21_db_min", "min",
         "> 15 dB", lambda v: v > 15.0,
         "sp lin 11 pts 2.4-2.4835 GHz; vecmin(db(s_2_1)) over the 11 points", "Gain (S21)"),
        ("s11", "Worst in-band |S11| [dB]", "sp_band", "s11_db_worst", "max",
         "< -10 dB", lambda v: v < -10.0,
         "sp lin 11 pts 2.4-2.4835 GHz; vecmax(db(s_1_1)) over the 11 points", "Input match (S11)"),
        ("s22", "Worst in-band |S22| [dB]", "sp_band", "s22_db_worst", "max",
         "< -10 dB", lambda v: v < -10.0,
         "sp lin 11 pts 2.4-2.4835 GHz; vecmax(db(s_2_2)) over the 11 points", "Output match (S22)"),
        ("stability", "Broadband minimum mu (Edwards-Sinsky)", "sp_stab", "mu_min", "min",
         "> 1", lambda v: v > 1.0,
         f"sp dec {N_STAB_DEC} pts/decade 10 MHz-30 GHz; vecmin(mu) over the sweep", "Stability"),
        ("nf290", f"NF at T0 = 290 K, band maximum of {nf_npts} sampled points [dB]", "noise", "nf290_db_worst", "max",
         "< 1.5 dB", lambda v: v < 1.5,
         nf_grid_text(nf_npts),
         "Noise figure (NF)"),
    ]


ROW_REDUCTIONS = row_reductions()
PORT_CONVENTION = ("50 Ohm reference at both ports (sp port sources with portnum/z0; "
                   "50 Ohm Thevenin source with noiseless Rs/RL for .noise)")

DISCLOSURES = [
    "NF290 is the maximum over a discrete frequency grid (the same grid for every variant; see the row's "
    "sampling text); a peak narrower than the grid spacing can be missed, so this is not continuous-band coverage. "
    "Records produced before issue #134 are three-point (lo/mid/hi) and are not comparable as full-grid results.",
    "ngspice sp-analysis port NF / NFmin (nf_sp_db_*, nfmin_sp_db_*) are distinct from the ratified T0 = 290 K "
    "value (nf290_db_*); only nf290_db_worst is compared with the NF target.",
    "DC bias current and DC power are NOT measured by these three requests; the Power and bias rows are not covered.",
    "Two-tone IIP3 is NOT measured by these three requests; the IIP3 row is not covered.",
    "Supply (VDD) and band are configured bench conditions, not independently measured compliance results.",
    "Comparisons describe sampled bench results only (the `ideal` variant is the frozen UNMATCHED pre-#27 DUT with ideal passives; `matched` is the committed design/netlist/lna.spice with its modelled finite-Q passives). A numeric pass "
    "does not establish matched physical performance, complete spec compliance, signoff, or T1 item 5.",
    "No missing observable is inferred from another campaign or DUT.",
]


def nf_worst_frequency(values: dict, nf_npts: int):
    """(frequency_hz, NF) of the first-maximum retained NF sample."""
    freqs = nf_freqs(nf_npts)
    i = max(range(nf_npts), key=lambda j: (values[nf_sample_names(nf_npts)[j]], -j))
    return freqs[i], values[nf_sample_names(nf_npts)[i]]


def ideal_row_coverage(cells, counts, grid: str, nf_npts: int = N_NF, variant: str = "ideal"):
    grid_keys = expected_grid(grid)
    rows = []
    for rid, label, analysis, meas, how, target, cmp_, sampling, specrow in row_reductions(nf_npts):
        c = counts.get((variant, analysis), {"expected": len(grid_keys), "valid": 0})
        cm = cells.get((variant, analysis), {})
        vals = [(cm[k]["values"][meas], k) for k in grid_keys
                if k in cm and cm[k].get("valid")]
        worst = None
        for v, k in vals:  # first cell in canonical order wins ties
            if worst is None or (v < worst[0] if how == "min" else v > worst[0]):
                worst = (v, k)
        complete = c["valid"] == c["expected"] and worst is not None
        if not complete:
            verdict = "NOT EVALUATED (coverage incomplete)"
        else:
            verdict = ("meets target at all sampled cells" if cmp_(worst[0])
                       else "FAILS target at the worst sampled cell")
        rows.append({
            "row": rid, "spec_row": f"spec/target-spec.md: {specrow}", "label": label,
            "analysis": analysis, "measurement": meas, "reduction": how,
            "frequency_sampling": sampling, "port_convention": PORT_CONVENTION,
            "target": target + " (strict inequality; equality fails)",
            "worst_value": None if worst is None else worst[0],
            "worst_cell": None if worst is None else cell_text(worst[1]),
            "valid_cells": c["valid"], "expected_cells": c["expected"],
            "coverage_complete": complete, "verdict": verdict,
        })
        if rid == "nf290":
            rows[-1]["nf_grid"] = {"mode": "lin", "n": nf_npts, "lo_hz": F_LO, "hi_hz": F_HI}
            if worst is not None:
                rows[-1]["worst_frequency_hz"], _ = nf_worst_frequency(
                    cm[worst[1]]["values"], nf_npts) if complete else (None, None)
    return rows


def coverage_markdown(rows, grid, complete, issues, title="Ideal-baseline"):
    out = [f"## {title} ratified-row coverage (sampled bench results only)", ""]
    out.append(f"- Coverage: **{'COMPLETE' if complete else 'INCOMPLETE'}** "
               f"(grid `{grid}`, {len(expected_grid(grid))} expected cells per analysis; "
               f"{len(issues)} validation issue(s))")
    if grid == GRID_SMOKE:
        out.append("- SMOKE grid (single nominal cell): not a PVT campaign, not a corner-box result.")
    if TEMPS != TEMPS_ALL:
        # Name the temperatures the grid actually contains, not the requested
        # slice: expected_grid(GRID_SMOKE) is the nominal 27 C cell regardless of
        # TEMPS, so a smoke+slice run must disclose [27], not the slice (issue #329).
        shown = ", ".join(f"{t:g}" for t in sorted({t for _, t, _ in expected_grid(grid)}))
        out.append(f"- TEMPERATURE SLICE: expected grid covers only [{shown}] of {TEMPS_ALL} "
                   f"({len(expected_grid(grid))} of {len(LABELS) * len(TEMPS_ALL) * len(VDDS)} cells); "
                   "a partial PVT grid, not a full corner-box result.")
    out.append("")
    for r in rows:
        w = "n/a" if r["worst_value"] is None else f"{r['worst_value']:.6g} @ {r['worst_cell']}"
        out.append(f"- **{r['label']}** -- {r['verdict']}")
        out.append(f"  - target: {r['target']} ({r['spec_row']})")
        if r.get("worst_frequency_hz") is not None:
            w += f" at {r['worst_frequency_hz'] / 1e9:.6g} GHz"
        out.append(f"  - worst: {w}; valid/expected cells {r['valid_cells']}/{r['expected_cells']}")
        out.append(f"  - measurement: `{r['analysis']}.{r['measurement']}` ({r['reduction']} over cells); "
                   f"sampling: {r['frequency_sampling']}")
        out.append(f"  - ports: {r['port_convention']}")
    out += ["", "### Not covered / disclosures", ""] + [f"- {d}" for d in DISCLOSURES] + [""]
    return out


def cmd_summarize(a):
    cdir = Path(a.corners_dir)
    grid = getattr(a, "grid", GRID_FULL)
    req = [v for v in (getattr(a, "variants", "") or "").split(",") if v]
    for v in req:
        if v not in VARIANTS:
            raise SystemExit(f"summarize: unknown variant {v}")
    if not req:
        names = set()
        for rep in cdir.glob("*.report.json"):
            stem = rep.name[: -len(".report.json")]
            an = next((x for x in ANALYSES if stem.endswith("_" + x)), None)
            if an and stem[: -len(an) - 1] in VARIANTS:
                names.add(stem[: -len(an) - 1])
        req = [v for v in VARIANTS if v in names or v == "ideal"]
    nf_npts = check_nf_npts(getattr(a, "nf_npts", N_NF))
    cells, issues, counts = collect_reports(cdir, req, grid, nf_npts)
    rows = {}  # (variant, label, temp, vdd) -> merged dict
    status = {}
    for (variant, analysis), cmap in cells.items():
        for key, cell in cmap.items():
            k = (variant,) + key
            rows.setdefault(k, {}).update(cell["values"])
            status.setdefault(k, {})[analysis] = cell["status"]
            if analysis == "noise" and cell.get("valid"):
                f_w, _ = nf_worst_frequency(cell["values"], nf_npts)
                rows[k]["nf290_f_at_worst_hz"] = f_w
                rows[k]["nf290_n_samples"] = nf_npts
    if not rows:
        raise SystemExit("summarize: no reports found")
    variants = [v for v in VARIANTS if any(k[0] == v for k in rows)]
    allcols = []
    for r in rows.values():
        for k in r:
            if k not in allcols:
                allcols.append(k)
    with open(a.summary_csv, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["variant", "corner_label", "temp_c", "vdd_v"] + allcols + ["status"])
        for key in sorted(rows, key=lambda k: (list(VARIANTS).index(k[0]), LABELS.index(k[1]), k[2], k[3])):
            r = rows[key]
            st = ";".join(f"{an}={s}" for an, s in sorted(status[key].items()))
            w.writerow([key[0], key[1], int(key[2]), f"{key[3]:.2f}"] + [r.get(c, "") for c in allcols] + [st])
    print(f"summarize: wrote {a.summary_csv} ({len(rows)} rows)")

    # ideal-vs-variant comparison, one row per (variant != ideal, cell)
    cmp_cols = [("s21_db_mid", "d_s21_db"), ("nf290_db_mid", "d_nf290_db"),
                ("nf290_db_worst", "d_nf290_worst_db"), ("nfmin_sp_db_mid", "d_nfmin_db"), ("s11_db_mid", "d_s11_db"),
                ("s22_db_mid", "d_s22_db"), ("mu_band_min", "d_mu_band"),
                # Bias deltas: a non-zero d_ic1_a means this variant's RF deltas
                # above are NOT attributable to inductor loss alone (see
                # OP_MEASUREMENTS). d_ve1_v is the DC lift of the emitter node.
                ("ic1", "d_ic1_a"), ("ve1", "d_ve1_v"), ("vce1", "d_vce1_v"),
                ("idd", "d_idd_a")]
    with open(a.compare_csv, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["variant", "corner_label", "temp_c", "vdd_v"]
                   + [c for _, c in cmp_cols] + ["ic1_pct", "mu_min_ideal", "mu_min_variant",
                                                  "n_mu_lt1_ideal", "n_mu_lt1_variant",
                                                  "s22_mag_max_ideal", "s22_mag_max_variant",
                                                  "n_s22_gt1_ideal", "n_s22_gt1_variant"])
        for key in sorted(rows, key=lambda k: (list(VARIANTS).index(k[0]), LABELS.index(k[1]), k[2], k[3])):
            if key[0] == "ideal":
                continue
            base = rows.get(("ideal",) + key[1:])
            if not base:
                continue
            r = rows[key]

            def d(n):
                x, y = r.get(n), base.get(n)
                return "" if x is None or y is None else f"{x - y:.5f}"

            def g(dct, n):
                x = dct.get(n)
                return "" if x is None else f"{x:.6g}"

            def pct(n):
                x, y = r.get(n), base.get(n)
                if x is None or y is None or not y:
                    return ""
                return f"{100.0 * (x - y) / y:+.2f}"

            w.writerow([key[0], key[1], int(key[2]), f"{key[3]:.2f}"]
                       + [d(n) for n, _ in cmp_cols]
                       + [pct("ic1"),
                          g(base, "mu_min"), g(r, "mu_min"), g(base, "n_mu_lt1"), g(r, "n_mu_lt1"),
                          g(base, "s22_mag_max"), g(r, "s22_mag_max"),
                          g(base, "n_s22_gt1"), g(r, "n_s22_gt1")])
    print(f"summarize: wrote {a.compare_csv}")

    # headline text, markdown
    lines = []

    def agg(variant, name):
        vals = [(r[name], k) for k, r in rows.items() if k[0] == variant and r.get(name) is not None]
        return vals

    def span(variant, name, nd=3):
        v = agg(variant, name)
        if not v:
            return "n/a"
        lo = min(v, key=lambda t: t[0]); hi = max(v, key=lambda t: t[0])
        return (f"min {lo[0]:.{nd}f} @ {lo[1][1]}/{lo[1][2]:g}C/{lo[1][3]:.2f}V, "
                f"max {hi[0]:.{nd}f} @ {hi[1][1]}/{hi[1][2]:g}C/{hi[1][3]:.2f}V")

    def span_scaled(variant, name, scale, nd=3):
        v = agg(variant, name)
        if not v:
            return "n/a"
        lo = min(v, key=lambda t: t[0]); hi = max(v, key=lambda t: t[0])
        return (f"min {lo[0] * scale:.{nd}f} @ {lo[1][1]}/{lo[1][2]:g}C/{lo[1][3]:.2f}V, "
                f"max {hi[0] * scale:.{nd}f} @ {hi[1][1]}/{hi[1][2]:g}C/{hi[1][3]:.2f}V")

    for v in variants:
        n = len({k for k in rows if k[0] == v})
        lines.append(f"### Variant `{v}` -- {VARIANTS[v][0]} ({n} cells)")
        lines.append("")
        for name, label in [("s21_db_mid", "|S21| mid-band [dB]"), ("nf290_db_mid", "NF @290 K mid-band [dB]"),
                            ("nfmin_sp_db_mid", "NFmin (sp) mid-band [dB]"),
                            ("s11_db_mid", "|S11| mid-band [dB]"), ("s22_db_mid", "|S22| mid-band [dB]"),
                            ("mu_min", "mu min 10 MHz..30 GHz"), ("s22_mag_max", "max |S22| 10 MHz..30 GHz")]:
            lines.append(f"- {label}: {span(v, name, 4 if 'mu' in name or 'mag' in name else 3)}")
        nfw = [(r["nf290_db_worst"], r["nf290_f_at_worst_hz"], k) for k, r in rows.items()
               if k[0] == v and r.get("nf290_db_worst") is not None and "nf290_f_at_worst_hz" in r]
        if nfw:
            w = max(nfw, key=lambda t: t[0])
            lines.append(f"- NF @290 K worst SAMPLED point [dB]: max {w[0]:.3f} at {w[1] / 1e9:.6g} GHz, "
                         f"{w[2][1]}/{w[2][2]:g}C/{w[2][3]:.2f}V -- {nf_grid_text(nf_npts)}")
        # Bias attribution (issue #56, #186/#188 note): state I_C1 and the DC
        # emitter lift, and whether this variant's RF deltas are confounded by a
        # bias shift rather than being inductor loss alone.
        if agg(v, "ic1"):
            lines.append(f"- I_C1 [mA]: {span_scaled(v, 'ic1', 1e3, 4)}")
            lines.append(f"- DC emitter lift v(e1) [mV]: {span_scaled(v, 've1', 1e3, 3)}")
            if v != "ideal":
                base_ic1 = [r["ic1"] for k, r in rows.items()
                            if k[0] == "ideal" and r.get("ic1") is not None]
                mine = [(r["ic1"], k) for k, r in rows.items()
                        if k[0] == v and r.get("ic1") is not None]
                pcts = []
                for val, k in mine:
                    b = rows.get(("ideal",) + k[1:], {}).get("ic1")
                    if b:
                        pcts.append((100.0 * (val - b) / b, k))
                if pcts:
                    worst = max(pcts, key=lambda t: abs(t[0]))
                    if abs(worst[0]) < IC1_ATTRIB_PCT:
                        lines.append(f"- Bias attribution: I_C1 within +/-{IC1_ATTRIB_PCT} % of `ideal` at every cell "
                                     "-- the deltas above are inductor loss, not a bias shift.")
                    else:
                        lines.append(
                            f"- Bias attribution: **I_C1 shifts up to {worst[0]:+.2f} % vs `ideal`** "
                            f"(worst {worst[1][1]}/{worst[1][2]:g}C/{worst[1][3]:.2f}V). The RF deltas "
                            "above are NOT inductor loss alone -- this variant's loss resistor is in "
                            "series with Le and carries Q1's DC emitter current, adding real emitter "
                            "degeneration. See README 'Bias confound'.")
                elif base_ic1:
                    lines.append("- Bias attribution: no per-cell `ideal` I_C1 to compare against.")
                else:
                    lines.append("- Bias attribution: I_C1 not computed -- no `ideal` `op` I_C1 "
                                 "to attribute against; the RF deltas above are unattributed.")
        lines.append("")
    complete = not issues
    banner = []
    if not complete:
        banner = [f"**COVERAGE INCOMPLETE** -- {len(issues)} validation issue(s); "
                  "no complete-grid or pass claim may be drawn from this summary.", ""]
    cov_rows = None
    mcov_rows = None
    if "ideal" in req:
        cov_rows = ideal_row_coverage(cells, counts, grid, nf_npts)
        lines = banner + lines + coverage_markdown(cov_rows, grid, complete, issues)
        if "matched" in req:
            mcov_rows = ideal_row_coverage(cells, counts, grid, nf_npts, "matched")
            mcov = coverage_markdown(mcov_rows, grid, complete, issues, "Matched-DUT (design/netlist/lna.spice)")
            # the shared disclosures were already emitted once, after the ideal block
            lines += [""] + mcov[: mcov.index("### Not covered / disclosures")]
    else:
        lines = banner + lines + ["Ideal baseline not requested; no ratified-row coverage summary.", ""]
    if issues:
        lines += ["## Validation issues", ""]
        for i in issues:
            lines.append("- " + _issue_text(i))
        lines.append("")
    open(a.headlines_md, "w").write("\n".join(lines) + "\n")
    print(f"summarize: wrote {a.headlines_md}")
    cj = getattr(a, "coverage_json", "")
    if cj:
        doc = {"coverage": "complete" if complete else "incomplete", "grid": grid,
               "expected_cells_per_analysis": len(expected_grid(grid)),
               "temps": list(TEMPS),
               "requested_variants": req, "nf290_grid": nf_grid_text(nf_npts),
               "nf290_npts": nf_npts,
               "counts": {f"{v}/{an}": c for (v, an), c in sorted(counts.items())},
               "ideal_rows": cov_rows, "matched_rows": mcov_rows, "disclosures": DISCLOSURES, "issues": issues}
        Path(cj).write_text(json.dumps(doc, indent=2, sort_keys=True) + "\n")
        print(f"summarize: wrote {cj}")
    if not complete:
        print(f"summarize: COVERAGE INCOMPLETE: {len(issues)} issue(s)", file=sys.stderr)
        for i in issues:
            print("summarize: " + _issue_text(i), file=sys.stderr)
        return 2
    return 0


# ---------------------------------------------------------------------------
# summarize-iip3 (issue #337): reduce `klt sim` two-tone IIP3 reports into the
# record's per-point CSV, per-cell summary CSV and headline text.
# ---------------------------------------------------------------------------

IIP3_BIN_KEYS = ("tone1", "tone2", "im3l", "im3h", "im5l", "im5h", "src1", "src2")
IIP3_LOG_OP_KEYS = ("ic1", "idd")
IIP3_LOG_DFT_KEYS = ("tone1", "tone2", "im3l", "im3h", "src1")
VARIANTS_ORDER = {v: i for i, v in enumerate(VARIANTS)}


def _iip3_issue(issues: list, kind: str, cell=None, amp=None, detail=""):
    issues.append({"kind": kind,
                   "cell": cell_text(cell) if isinstance(cell, tuple) else (cell or ""),
                   "amp": amp or "", "detail": detail})


def _load_klt_cells(path: Path):
    """(report_doc, {norm_key: {"values","status","ok","artifacts"}},
    [duplicate keys]) for one `klt sim` report; first occurrence per cell
    wins, duplicates are returned so the caller can fail loudly rather than
    silently prefer one."""
    data = json.loads(path.read_text())
    cells: dict = {}
    dup: list = []
    for c in data.get("corners", []):
        try:
            key = norm_key(*corner_key(c))
        except Exception:
            continue
        if key in cells:
            dup.append(key)
            continue
        cells[key] = {"values": corner_values(c), "status": c.get("status"),
                      "ok": cell_status_ok(c),
                      "artifacts": c.get("artifacts") or {}}
    return data, cells, dup


def _read_slice_s11_csvs(spec: str) -> dict:
    """{norm_key: s11_db_mid} from committed present-dut slice summary CSVs
    (the device-plane conversion's per-cell |S11| source)."""
    out: dict = {}
    for p in [x for x in spec.split(",") if x]:
        path = Path(p)
        if not path.is_file():
            raise SystemExit(f"--s11-csv: no such file: {p}")
        with open(path) as fh:
            for r in csv.DictReader(fh):
                try:
                    key = norm_key(r["corner_label"], float(r["temp_c"]), float(r["vdd_v"]))
                    val = float(r["s11_db_mid"])
                except (KeyError, ValueError, TypeError):
                    continue
                out[key] = val
    return out


def iip3_mismatch_term_db(s11_db: float) -> float:
    """The available-vs-device-plane inflation term, -10*log10(1 - |S11|^2)
    (spec/target-spec.md "IIP3 mismatch-inflation note")."""
    mag = 10.0 ** (s11_db / 20.0)
    if not 0.0 <= mag < 1.0:
        raise ValueError(f"|S11| out of range for the mismatch term: {s11_db} dB")
    return -10.0 * math.log10(1.0 - mag * mag)


def _resolve_iip3_log(recorded, corners_dir):
    """The corner's ngspice log path, resolved against this checkout.

    `klt sim` reports record `artifacts.log` as an absolute path into the
    worktree that submitted the run -- a path that stops existing once that
    worktree is reaped and never existed on any other checkout. When the
    recorded path is absent, re-root the suffix after `corners/<record-id>/`
    onto `--corners-dir` (the committed evidence layout). Returns None when
    neither resolves, so a genuinely missing log still fails loudly as
    `missing_log_echoes`."""
    if not recorded:
        return None
    p = Path(str(recorded))
    if p.is_file():
        return p
    cdir = Path(corners_dir)
    if not p.is_absolute():
        cand = cdir / p
        if cand.is_file():
            return cand
    parts = p.parts
    for i in range(len(parts) - 2):
        if parts[i] == "corners" and parts[i + 1] == cdir.name:
            cand = cdir.joinpath(*parts[i + 2:])
            if cand.is_file():
                return cand
    return None


def cmd_summarize_iip3(a):
    cdir = Path(a.corners_dir)
    variant = a.variant
    grid_amps = _parse_amps(a.amps, "--amps")
    extra_amps = (_parse_amps(a.amps_nominal_only, "--amps-nominal-only")
                  if a.amps_nominal_only else [])
    grid = getattr(a, "grid", GRID_FULL)
    grid_keys = expected_grid(grid)
    issues: list = []
    rows: list = []

    # Per-cell DC bias from the variant's own op request -- the record carries
    # the bias point beside every IIP3 number.
    op_cells: dict = {}
    if a.op_report:
        op_path = Path(a.op_report)
        if not op_path.is_file():
            raise SystemExit(f"summarize-iip3: --op-report: no such file: {a.op_report}")
        _, opc, odup = _load_klt_cells(op_path)
        for k in odup:
            _iip3_issue(issues, "duplicate_op_cell", cell=k)
        op_cells = opc

    # Per-cell |S11| for the device-plane conversion.
    s11 = _read_slice_s11_csvs(a.s11_csv) if a.s11_csv else {}

    for amp in grid_amps + extra_amps:
        label = iip3_amp_label(amp)
        path = cdir / f"{variant}_iip3_{label}.report.json"
        expected_keys = grid_keys if amp in grid_amps else [norm_key(*NOMINAL)]
        if not path.is_file():
            _iip3_issue(issues, "missing_report", amp=label, detail=path.name)
            continue
        _doc, cells, dup = _load_klt_cells(path)
        for k in dup:
            _iip3_issue(issues, "duplicate_cell", amp=label, cell=k)
        for key in expected_keys:
            if key not in cells:
                _iip3_issue(issues, "missing_cell", amp=label, cell=key)
                continue
            cell = cells[key]
            ok, okdetail = cell["ok"]
            if not ok:
                _iip3_issue(issues, "failed_cell", amp=label, cell=key, detail=okdetail)
                continue
            vals = cell["values"]
            bad = [n for n in IIP3_BIN_KEYS if not is_finite_number(vals.get(n))]
            if bad:
                _iip3_issue(issues, "missing_measurement", amp=label, cell=key,
                            detail=f"non-finite or absent FFT bins: {','.join(bad)}")
                continue
            if abs(vals["fft_df"] - IIP3_DF) > 1.0:
                _iip3_issue(issues, "incoherent_fft_df", amp=label, cell=key,
                            detail=f"fft_df {vals['fft_df']!r} != 1/(N*tstep) {IIP3_DF!r}")
                continue
            # The per-corner ngspice log keeps the template's OP/DFT echoes.
            # The report records it as an absolute path into the submitting
            # worktree; re-root onto --corners-dir when that path is gone.
            recorded_log = (cell["artifacts"] or {}).get("log")
            log_file = _resolve_iip3_log(recorded_log, cdir)
            parsed_log = {}
            npts = None
            if log_file:
                parsed_log = _sweep.parse_iip3_log(str(log_file))
                npts = parsed_log.get("npts")
            if not parsed_log:
                _iip3_issue(issues, "missing_log_echoes", amp=label, cell=key,
                            detail=f"OP/NPTS/DFT echoes unreadable ({recorded_log})")
                continue
            bad_log = [k for k in IIP3_LOG_OP_KEYS
                       if not is_finite_number(parsed_log.get(k))]
            bad_log += [f"dft_{k}" for k in IIP3_LOG_DFT_KEYS
                        if not is_finite_number(parsed_log.get(f"dft_{k}"))]
            if npts != IIP3_NFFT:
                bad_log.append(f"npts={npts!r} (expected {IIP3_NFFT})")
            if bad_log:
                _iip3_issue(issues, "invalid_log_echoes", amp=label, cell=key,
                            detail="; ".join(bad_log))
                continue
            fields, iip3, iip3_dft = _sweep.iip3_measurement_fields(
                amp, vals, parsed_log)
            row = {
                "point_id": f"iip3_{variant}_{key[0]}_{key[1]:g}c_vdd{key[2]:.2f}v_{label}",
                "variant": variant,
                "corner_label": key[0], "temp_c": key[1], "vdd_v": key[2],
            }
            for name, value in fields.items():
                row[name] = value
                if name == "iip3_dbm_dft_crosscheck":
                    # the campaign-only agreement column follows the
                    # cross-check it compares, and keeps the unrounded
                    # intercepts as its inputs
                    row["dft_fft_iip3_agreement_db"] = f"{abs(iip3 - iip3_dft):.4f}"
            rows.append(row)
    # Extra (non-declared) reports present on disk are reported, not folded in.
    declared = {f"{variant}_iip3_{iip3_amp_label(x)}.report.json"
                for x in grid_amps + extra_amps}
    for rep in sorted(cdir.glob(f"{variant}_iip3_*.report.json")):
        if rep.name not in declared:
            _iip3_issue(issues, "unexpected_report", detail=rep.name)

    if not rows:
        raise SystemExit("summarize-iip3: no IIP3 rows reduced; nothing to write")

    with open(a.iip3_csv, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        w.writeheader()
        for r in sorted(rows, key=lambda r: (VARIANTS_ORDER.get(r["variant"], 9),
                                             LABELS.index(r["corner_label"]),
                                             float(r["temp_c"]), float(r["vdd_v"]),
                                             float(r["amp_v_peak_per_tone"]))):
            w.writerow(r)
    print(f"summarize-iip3: wrote {a.iip3_csv} ({len(rows)} points)")

    # --- per-cell summary: intercepts only where the 3:1 slope check passes ---
    by_cell: dict = {}
    for r in rows:
        by_cell.setdefault((r["corner_label"], r["temp_c"], r["vdd_v"]), []).append(r)
    tol = a.slope_tol
    summary: list = []
    for key in sorted(by_cell, key=lambda k: (LABELS.index(k[0]), float(k[1]), float(k[2]))):
        pts = sorted(by_cell[key], key=lambda r: float(r["amp_v_peak_per_tone"]))
        validity, reason = _sweep.classify_iip3_cell(pts, tol)
        row = {"variant": variant, "corner_label": key[0], "temp_c": key[1], "vdd_v": key[2]}
        opv = (op_cells.get(norm_key(*key)) or {}).get("values") or {}
        for m in OP_MEASUREMENTS:
            v = opv.get(m[0])
            row[m[0]] = "" if v is None else f"{v:.6g}"
        lo = next((r for r in pts if r["point_id"].endswith("a1mv")), None)
        hi = next((r for r in pts if r["point_id"].endswith("a2mv")), None)
        row["iip3_dbm_a1mv"] = lo["iip3_dbm"] if lo else ""
        row["iip3_dbm_a2mv"] = hi["iip3_dbm"] if hi else ""
        row["oip3_dbm_a2mv"] = hi["oip3_dbm"] if hi else ""
        row["gain_db_a2mv"] = hi["gain_db"] if hi else ""
        row["iip3_spread_2pt_db"] = (
            f"{abs(float(hi['iip3_dbm']) - float(lo['iip3_dbm'])):.3f}"
            if lo and hi else "")
        slope = ""
        if lo and hi:
            dpin = (float(hi["pin_avail_dbm_per_tone"])
                    - float(lo["pin_avail_dbm_per_tone"]))
            if dpin:
                slope = (round((float(hi["pim3_dbm"]) - float(lo["pim3_dbm"])) / dpin, 3))
                slope = f"{slope:.3f}"
        row["im3_slope_2pt"] = slope
        row["iip3_validity"] = validity
        row["iip3_validity_reason"] = reason
        s11_db = s11.get(norm_key(*key))
        if s11_db is not None:
            term = iip3_mismatch_term_db(s11_db)
            row["iip3_mismatch_term_db"] = f"{term:.4f}"
            row["iip3_device_plane_dbm_a1mv"] = (
                f"{float(lo['iip3_dbm']) - term:.4f}" if lo else "")
            row["iip3_device_plane_dbm_a2mv"] = (
                f"{float(hi['iip3_dbm']) - term:.4f}" if hi else "")
        else:
            row["iip3_mismatch_term_db"] = ""
            row["iip3_device_plane_dbm_a1mv"] = ""
            row["iip3_device_plane_dbm_a2mv"] = ""
        summary.append(row)
    with open(a.summary_csv, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(summary[0].keys()))
        w.writeheader()
        w.writerows(summary)
    print(f"summarize-iip3: wrote {a.summary_csv} ({len(summary)} cells)")

    # --- headlines (the record embeds this verbatim) ------------------------
    lines: list = []
    valid = [r for r in summary if r["iip3_validity"] == _sweep.IIP3_VALID]
    invalid = [r for r in summary if r["iip3_validity"] == _sweep.IIP3_INVALID]
    unknown = [r for r in summary if r["iip3_validity"] == _sweep.IIP3_UNKNOWN]
    lines.append("## Two-tone IIP3 reduction (issue #337)")
    lines.append("")
    complete = not issues
    lines.append(f"- Coverage: **{'COMPLETE' if complete else 'INCOMPLETE'}** "
                 f"({len(summary)} cells x {[iip3_amp_label(x) for x in grid_amps]} per-cell levels"
                 + (f" + nominal-only {[iip3_amp_label(x) for x in extra_amps]}" if extra_amps else "")
                 + f"; {len(issues)} validation issue(s))")
    lines.append(f"- IM3 slope check (3 +/- {tol:g}, README policy): valid {len(valid)}, "
                 f"invalid {len(invalid)}, unknown {len(unknown)} of {len(summary)} cells.")
    if len(valid) == len(summary):
        lines.append("- The 3:1 IM3 slope assumption holds at every cell; "
                     "every intercept below is accepted.")
    elif not valid:
        lines.append("- **No intercept accepted**: zero cells passed the slope check.")
    else:
        lines.append("- Headline intercepts are restricted to the valid cells; "
                     "raw per-point `iip3_dbm` values in the IIP3 CSV are never altered or dropped.")
    for r in invalid + unknown:
        lines.append(f"  - {r['corner_label']}/{float(r['temp_c']):g}C/{float(r['vdd_v']):.2f}V: "
                     f"{r['iip3_validity']} ({r['iip3_validity_reason']}) -- no intercept accepted")

    def span(col, rows_, nd=4):
        vals = [(float(r[col]), r) for r in rows_ if r.get(col)]
        if not vals:
            return "n/a"
        lo = min(vals, key=lambda t: t[0])
        hi = max(vals, key=lambda t: t[0])
        return (f"{lo[0]:.{nd}f} @ {lo[1]['corner_label']}/{float(lo[1]['temp_c']):g}C/"
                f"{float(lo[1]['vdd_v']):.2f}V .. "
                f"{hi[0]:.{nd}f} @ {hi[1]['corner_label']}/{float(hi[1]['temp_c']):g}C/"
                f"{float(hi[1]['vdd_v']):.2f}V")

    if valid:
        lines.append(f"- Available-power-referred IIP3, 2 mV/tone [dBm] over valid cells: {span('iip3_dbm_a2mv', valid)}")
        lines.append(f"- Available-power-referred IIP3, 1 mV/tone [dBm] over valid cells: {span('iip3_dbm_a1mv', valid)}")
        nom = next((r for r in valid
                    if norm_key(r["corner_label"], float(r["temp_c"]), float(r["vdd_v"])) == norm_key(*NOMINAL)), None)
        if nom:
            lines.append(f"- Nominal cell (typ/27C/1.80V): IIP3 {nom['iip3_dbm_a1mv']} dBm at 1 mV/tone, "
                         f"{nom['iip3_dbm_a2mv']} dBm at 2 mV/tone, IM3 slope {nom['im3_slope_2pt'] or 'n/a'}, "
                         f"I_C1 {nom.get('ic1', '')} A, P_dc {nom.get('pdc', '')} W.")
        if any(r.get("iip3_device_plane_dbm_a2mv") for r in valid):
            terms = [float(r["iip3_mismatch_term_db"]) for r in valid if r.get("iip3_mismatch_term_db")]
            lines.append(f"- Device-plane conversion (matched |S11| per cell, "
                         f"term -10*log10(1-|S11|^2) = {min(terms):+.4f}..{max(terms):+.4f} dB): "
                         f"device-plane IIP3, 2 mV/tone [dBm]: {span('iip3_device_plane_dbm_a2mv', valid)}")
        else:
            lines.append("- Device-plane conversion: NOT computed (--s11-csv not given or cells unmatched).")
        bar = [r for r in valid if float(r["iip3_dbm_a2mv"]) > 0.0]
        lines.append(f"- Draft > 0 dBm value (NOT a ratified target): {len(bar)} of {len(valid)} "
                     f"valid cells reach 0 dBm at 2 mV/tone. Observation only -- the IIP3 numeric "
                     "row stays DRAFT; binding requires a decision record of its own.")
    lines.append("")
    lines.append("### Bench definition (carried beside every number)")
    lines.append("")
    lines.append(f"- Tones: f1 = {IIP3_F1!r} Hz (bin {IIP3_B1}), f2 = {IIP3_F2!r} Hz (bin {IIP3_B2}), "
                 f"spacing = {IIP3_FSPACE!r} Hz; IM3 products at bins {IIP3_BIM3L}/{IIP3_BIM3H}, "
                 f"IM5 floor sentinels at bins {IIP3_BIM5L}/{IIP3_BIM5H}.")
    lines.append(f"- FFT: uniform tstep = {IIP3_TSTEP:g} s, N = {IIP3_NFFT} samples "
                 f"(tstop = {IIP3_TSTOP:.11g} s), rectangular window (`set specwindow=none`), "
                 f"df = 1/(N*tstep) = {IIP3_DF!r} Hz, tstart = {IIP3_TSTART:g} s discarded; "
                 "NPTS and the bin-resolution witness (fft_df) are recorded per point.")
    lines.append("- Ports: 50 Ohm at both ends (Rs = RL = 50 Ohm); input power is the AVAILABLE "
                 "source power per tone A^2/(8*Rs); output power per tone and per product is "
                 "V_peak^2/(2*RL); IIP3 = Pin + (Pout - PIM3)/2.")
    lines.append(f"- Drive levels: {[iip3_amp_label(x) + f' ({x:g} V)' for x in grid_amps]} at every PVT cell; "
                 + (f"nominal cell additionally {[iip3_amp_label(x) for x in extra_amps]}." if extra_amps else "no nominal-only extra levels."))
    lines.append("- Extraction: the deck reproduces testbench/tb_lna_iip3.spice.tmpl's control sequence "
                 "verbatim (op -> OP echo -> tran -> linearize v(rfout) v(vin) -> NPTS -> coherent-DFT "
                 "projection -> DFT echo -> fft), carried as a klt sim request; the FFT bin magnitudes "
                 "return in the klt report (measurements[].expr read in the spectrum plot the template's "
                 "own `fft` leaves current) and the template's OP/DFT echoes stay in the kept ngspice log. "
                 "Primary IIP3 = FFT bins; `iip3_dbm_dft_crosscheck` = the template's independent "
                 "coherent-DFT projection from the same log; `dft_fft_iip3_agreement_db` per point.")
    lines.append("- ngspice: version/build per klt report `environment` (fleet runner); the DUT is "
                 "design/netlist/lna.spice inlined verbatim (sha256 recorded in the record header).")
    lines.append("")
    lines.append("### Stated limits of this method (README 'IIP3', restated)")
    lines.append("")
    lines.append("1. Extrapolation, not a measured intercept: meaningful only while IM3 rises 3:1 with "
                 "drive; cells failing the slope check contribute NO accepted intercept.")
    lines.append("2. IM5 bins are numerical-floor sentinels; `im3_over_im5_db` is committed per point "
                 "and the bench is not to be driven lower without re-checking that margin.")
    lines.append("3. Clean harmonic/intermod separation comes from the wide 7.63 MHz spacing; narrowing "
                 "it needs a proportionally longer record (wall-clock, not methodology).")
    lines.append("4. tstep = 4 ps => 125 GHz Nyquist (~51x the tone), so transient truncation does not "
                 "synthesize its own intermodulation; ngspice default reltol sets the floor in (2).")
    lines.append("5. Steady state after tstart = 1 us is an argument (ns-scale poles), not a measurement.")
    lines.append("6. Single-ended, single tone pair, in-band only: no blocker, out-of-band IM, AM-PM, P1dB.")
    lines.append("")
    if issues:
        lines.append("## Validation issues")
        lines.append("")
        for i in issues:
            parts = [i["kind"]]
            if i.get("cell"):
                parts.append(f"cell={i['cell']}")
            if i.get("amp"):
                parts.append(f"amp={i['amp']}")
            if i.get("detail"):
                parts.append(i["detail"])
            lines.append("- " + " ".join(parts))
        lines.append("")
    open(a.headlines_md, "w").write("\n".join(lines) + "\n")
    print(f"summarize-iip3: wrote {a.headlines_md}")
    if issues:
        print(f"summarize-iip3: COVERAGE INCOMPLETE: {len(issues)} issue(s)", file=sys.stderr)
        for i in issues:
            parts = [i["kind"]]
            if i.get("cell"):
                parts.append(f"cell={i['cell']}")
            if i.get("amp"):
                parts.append(f"amp={i['amp']}")
            if i.get("detail"):
                parts.append(i["detail"])
            print("summarize-iip3: " + " ".join(parts), file=sys.stderr)
        return 2
    return 0


def _issue_text(i):
    parts = [i["kind"], f"variant={i['variant']}", f"analysis={i['analysis']}"]
    if i.get("cell"):
        parts.append(f"cell={i['cell']}")
    if i.get("measurement"):
        parts.append(f"measurement={i['measurement']}")
    if i.get("detail"):
        parts.append(i["detail"])
    return " ".join(parts)


def apply_temps(spec: str) -> None:
    """Restrict the campaign to a temperature slice (issue #258): request() and
    expected_grid() both read TEMPS, so gen and summarize stay in agreement as
    long as they are given the same --temps. Empty spec = all of TEMPS.
    Validation and filtering run against the frozen TEMPS_ALL (issue #306), so
    the valid set does not shrink under an already-applied slice."""
    global TEMPS
    if not spec:
        return
    want = [int(t) for t in spec.split(",") if t]
    bad = [t for t in want if t not in TEMPS_ALL]
    if bad or not want:
        raise SystemExit(f"--temps must be a comma list drawn from {TEMPS_ALL} (got {spec!r})")
    TEMPS = [t for t in TEMPS_ALL if t in want]


def collect_batch_set(runner, envelope, corners_out):
    """Collect one `klt sim --batch-set` run's member reports (issue #454).

    The single reader of the set envelope on the batch path of
    run_lna_variant.sh and run_lna_iip3.sh. For each member of the
    envelope's `requests` list, in envelope order: derive the request stem
    ONCE (basename with the whole ".request.json" suffix removed, so
    `ideal_noise.request.json` -> `ideal_noise` and the dot inside
    `matched_iip3_a0.5mv` survives), copy the member's report to
    <corners_out>/<stem>.report.json -- the path the reducers, the coverage
    validator and the record provenance read, identical to what the serial
    (non-set) loop writes -- and print a missing-report diagnostic to stderr
    when there is nothing to copy. The source path is the envelope's own
    requests[].report field, never a guessed directory name: klt names a
    member's directory after the request file with only the LAST suffix
    removed, so `ideal_noise.request.json` lands in `ideal_noise.request/`,
    not `ideal_noise/`.

    Returns the per-member failure entries [(stem, exit_code), ...] in
    envelope order: a non-zero member exit is a failure even when the set as
    a whole returned 0. Raises SystemExit(1) with the runner-tagged
    diagnostic when the envelope itself cannot be read -- before any report
    is copied.
    """
    try:
        with open(envelope) as f:
            d = json.load(f)
    except Exception as exc:
        raise SystemExit(f"{runner}: cannot read set envelope {envelope}: {exc}")
    entries = []
    for r in d.get("requests") or []:
        stem = re.sub(r"\.request\.json$", "", os.path.basename(r.get("request") or ""))
        if stem:
            src = r.get("report")
            if src and os.path.isfile(src):
                shutil.copyfile(src, os.path.join(corners_out, f"{stem}.report.json"))
            else:
                print(f"{runner}: {stem}: no report to collect "
                      f"({'missing ' + src if src else 'member never produced one'})",
                      file=sys.stderr)
        if r.get("exit_code"):
            entries.append((stem or "<unknown>", r["exit_code"]))
    return entries


def cmd_collect_set(a):
    for stem, rc in collect_batch_set(a.runner, a.envelope, a.corners_out):
        print("%s %s" % (stem, rc))
    return 0


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    temps_help = ("temperature slice, e.g. --temps=125 (default: all of -40,27,125). Pass the same "
                  "value to gen and summarize; a slice is a partial grid, not a PVT campaign")
    sub = p.add_subparsers(dest="cmd", required=True)
    g = sub.add_parser("gen")
    g.add_argument("--outdir", required=True)
    g.add_argument("--variants", default="")
    g.add_argument("--analyses", default="",
                   help=f"comma list from {ANALYSES} (default: all)")
    g.add_argument("--smoke", action="store_true", help="single nominal cell")
    g.add_argument("--backend", default="")
    g.add_argument("--nf-npts", type=int, default=N_NF,
                   help=f"points of the 290 K NF sweep (odd, >= {N_BAND}); default {N_NF}")
    g.add_argument("--temps", default="", help=temps_help)
    g.set_defaults(fn=cmd_gen)
    gi = sub.add_parser("gen-iip3")
    gi.add_argument("--outdir", required=True)
    gi.add_argument("--variants", default="matched",
                    help="comma list; default matched (issue #337 runs the matched DUT)")
    gi.add_argument("--amps", default=",".join(f"{x:g}" for x in IIP3_AMPS_GRID),
                    help="per-cell drive levels, V peak/tone (default the ratified pair)")
    gi.add_argument("--amps-nominal-only",
                    default=",".join(f"{x:g}" for x in IIP3_AMPS_NOMINAL_ONLY),
                    help="extra drive levels run at the nominal cell alone, V peak/tone "
                         "(default the ratified 0.5/4/8 mV set; pass '' for none)")
    gi.add_argument("--op", action="store_true", default=True,
                    help="also write the variant's op request pair (default)")
    gi.add_argument("--no-op", dest="op", action="store_false")
    gi.add_argument("--smoke", action="store_true", help="single nominal cell")
    gi.add_argument("--backend", default="")
    gi.add_argument("--temps", default="", help=temps_help)
    gi.set_defaults(fn=cmd_gen_iip3)
    cs = sub.add_parser("collect-set")
    cs.add_argument("--runner", required=True,
                    help="runner label for the diagnostics (e.g. run_lna_variant.sh)")
    cs.add_argument("--envelope", required=True,
                    help="the klt sim --batch-set set-report.json to read")
    cs.add_argument("--corners-out", required=True,
                    help="record corners dir to materialise <stem>.report.json into")
    cs.set_defaults(fn=cmd_collect_set)
    s = sub.add_parser("summarize")
    s.add_argument("--corners-dir", required=True)
    s.add_argument("--summary-csv", required=True)
    s.add_argument("--compare-csv", required=True)
    s.add_argument("--headlines-md", required=True)
    s.add_argument("--coverage-json", default="", help="optional machine-readable coverage summary")
    s.add_argument("--grid", choices=[GRID_FULL, GRID_SMOKE], default=GRID_FULL,
                   help="expected grid: full 45-cell PVT box (default) or single nominal smoke cell")
    s.add_argument("--nf-npts", type=int, default=N_NF,
                   help="NF grid the reports were generated with (must match gen)")
    s.add_argument("--variants", default="",
                   help="comma list of variants that must be complete (default: ideal + any present)")
    s.add_argument("--temps", default="", help=temps_help)
    s.set_defaults(fn=cmd_summarize)
    si = sub.add_parser("summarize-iip3")
    si.add_argument("--corners-dir", required=True)
    si.add_argument("--iip3-csv", required=True)
    si.add_argument("--summary-csv", required=True)
    si.add_argument("--headlines-md", required=True)
    si.add_argument("--variant", default="matched")
    si.add_argument("--amps", default=",".join(f"{x:g}" for x in IIP3_AMPS_GRID),
                    help="per-cell drive levels the reports were generated with (must match gen-iip3)")
    si.add_argument("--amps-nominal-only",
                    default=",".join(f"{x:g}" for x in IIP3_AMPS_NOMINAL_ONLY),
                    help="extra nominal-cell drive levels (must match gen-iip3; pass '' for none)")
    si.add_argument("--op-report", default="",
                    help="<variant>_op.report.json for the per-cell bias join (recommended)")
    si.add_argument("--s11-csv", default="",
                    help="comma list of committed present-dut slice summary CSVs carrying "
                         "per-cell s11_db_mid, for the device-plane conversion")
    si.add_argument("--slope-tol", type=float, default=_sweep.IIP3_SLOPE_TOL,
                    help=f"IM3 2-point slope tolerance (default {_sweep.IIP3_SLOPE_TOL}, README policy)")
    si.add_argument("--grid", choices=[GRID_FULL, GRID_SMOKE], default=GRID_FULL,
                    help="expected grid: full 45-cell PVT box (default) or single nominal smoke cell")
    si.add_argument("--temps", default="", help=temps_help)
    si.set_defaults(fn=cmd_summarize_iip3)
    a = p.parse_args()
    # collect-set reads no temperature slice; every temperature-aware
    # subcommand (gen, gen-iip3, summarize, summarize-iip3) carries --temps.
    apply_temps(getattr(a, "temps", ""))
    sys.exit(a.fn(a) or 0)


if __name__ == "__main__":
    main()
