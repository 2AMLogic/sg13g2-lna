#!/usr/bin/env python3
"""Inductor-loss variant campaign for design/lna.sch (issue #56).

Companion to run_lna_variant.sh. Two subcommands:

  gen        write, for one record id, every variant's bench netlists and
             `klt sim` request files under netlist-snapshots/<record-id>/
  summarize  turn the `klt sim` JSON reports under corners/<record-id>/ into
             records/<record-id>-{summary,compare}.csv and the headline
             numbers the record .md quotes

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
  noise     noise v(nfout) vin lin 3 2.4e9 2.4835e9   (NF at T0 = 290 K)

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

LABELS = ["typ", "bcs", "wcs", "sf", "fs"]
HBT = {"typ": "hbt_typ", "bcs": "hbt_bcs", "wcs": "hbt_wcs", "sf": "hbt_typ", "fs": "hbt_typ"}
MOS = {"typ": "mos_tt", "bcs": "mos_ff", "wcs": "mos_ss", "sf": "mos_sf", "fs": "mos_fs"}
TEMPS = [-40, 27, 125]
VDDS = [1.62, 1.80, 1.98]
NOMINAL = ("typ", 27, 1.80)

F_LO, F_MID, F_HI = 2.4e9, 2.44175e9, 2.4835e9
N_BAND = 11  # index 5 is exactly F_MID
F_STAB_LO, F_STAB_HI, N_STAB_DEC = 1e7, 3e10, 40

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
    "lc_em_le_q10": ("Lc = EM 5-turn model AND Le Q=10", "em", 10),
}
ANALYSES = ["sp_band", "sp_stab", "noise"]

LE_LINE = "Le e1 vss 1n m=1"
LC_LINE = "Lc vdd outn 5n m=1"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def dut_subckt(lc: str, le_q) -> str:
    """design/netlist/lna.spice as run_lna_sweep.sh inlines it, plus the one
    inductor edit the variant names. Returns the subckt text."""
    text = DESIGN_NETLIST.read_text()
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
        f"* DUT: design/netlist/lna.spice sha256 {sha256(DESIGN_NETLIST)}, inlined verbatim\n"
        "*   except the inductor edit(s) marked 'VARIANT EDIT'.\n"
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
    if analysis.startswith("sp"):
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


def measurements(analysis: str):
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
        add("nf290_db_lo", f"({nf})[0]", "dB")
        add("nf290_db_mid", f"({nf})[1]", "dB")
        add("nf290_db_hi", f"({nf})[2]", "dB")
        add("nf290_db_worst", f"vecmax({nf})", "dB")
    return m


def analysis_card(analysis: str) -> dict:
    if analysis == "sp_band":
        return {"kind": "sp", "args": f"lin {N_BAND} {F_LO:g} {F_HI:g} 1"}
    if analysis == "sp_stab":
        return {"kind": "sp", "args": f"dec {N_STAB_DEC} {F_STAB_LO:g} {F_STAB_HI:g}"}
    return {"kind": "noise", "args": f"v(nfout) vin lin 3 {F_LO:g} {F_HI:g}"}


def request(variant: str, analysis: str, netlist_name: str, smoke: bool, backend: str | None) -> dict:
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
        "analysis": analysis_card(analysis),
        "measurements": measurements(analysis),
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
        for an in ANALYSES:
            nl = out / f"{v}_{an}.spice"
            nl.write_text(netlist(v, an, rel_model))
            rq = out / f"{v}_{an}.request.json"
            rq.write_text(json.dumps(request(v, an, nl.name, a.smoke, a.backend), indent=2) + "\n")
    print(f"gen: wrote {len(names) * len(ANALYSES)} request/netlist pairs in {out}")


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


def cmd_summarize(a):
    cdir = Path(a.corners_dir)
    rows = {}  # (variant, label, temp, vdd) -> merged dict
    status = {}
    for rep in sorted(cdir.glob("*.report.json")):
        stem = rep.name[: -len(".report.json")]
        analysis = next(an for an in ANALYSES if stem.endswith("_" + an))
        variant = stem[: -len(analysis) - 1]
        data = load_report(rep)
        for c in data.get("corners", []):
            key = (variant,) + corner_key(c)
            rows.setdefault(key, {})
            rows[key].update({k: v for k, v in corner_values(c).items()})
            status.setdefault(key, {})[analysis] = c.get("status")
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
                ("nfmin_sp_db_mid", "d_nfmin_db"), ("s11_db_mid", "d_s11_db"),
                ("s22_db_mid", "d_s22_db"), ("mu_band_min", "d_mu_band")]
    with open(a.compare_csv, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["variant", "corner_label", "temp_c", "vdd_v"]
                   + [c for _, c in cmp_cols] + ["mu_min_ideal", "mu_min_variant",
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

            w.writerow([key[0], key[1], int(key[2]), f"{key[3]:.2f}"]
                       + [d(n) for n, _ in cmp_cols]
                       + [g(base, "mu_min"), g(r, "mu_min"), g(base, "n_mu_lt1"), g(r, "n_mu_lt1"),
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

    for v in variants:
        n = len({k for k in rows if k[0] == v})
        lines.append(f"### Variant `{v}` -- {VARIANTS[v][0]} ({n} cells)")
        lines.append("")
        for name, label in [("s21_db_mid", "|S21| mid-band [dB]"), ("nf290_db_mid", "NF @290 K mid-band [dB]"),
                            ("nfmin_sp_db_mid", "NFmin (sp) mid-band [dB]"),
                            ("s11_db_mid", "|S11| mid-band [dB]"), ("s22_db_mid", "|S22| mid-band [dB]"),
                            ("mu_min", "mu min 10 MHz..30 GHz"), ("s22_mag_max", "max |S22| 10 MHz..30 GHz")]:
            lines.append(f"- {label}: {span(v, name, 4 if 'mu' in name or 'mag' in name else 3)}")
        lines.append("")
    open(a.headlines_md, "w").write("\n".join(lines) + "\n")
    print(f"summarize: wrote {a.headlines_md}")


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    g = sub.add_parser("gen")
    g.add_argument("--outdir", required=True)
    g.add_argument("--variants", default="")
    g.add_argument("--smoke", action="store_true", help="single nominal cell")
    g.add_argument("--backend", default="")
    g.set_defaults(fn=cmd_gen)
    s = sub.add_parser("summarize")
    s.add_argument("--corners-dir", required=True)
    s.add_argument("--summary-csv", required=True)
    s.add_argument("--compare-csv", required=True)
    s.add_argument("--headlines-md", required=True)
    s.set_defaults(fn=cmd_summarize)
    a = p.parse_args()
    a.fn(a)


if __name__ == "__main__":
    main()
