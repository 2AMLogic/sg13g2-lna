#!/usr/bin/env python3
"""Parse sim/lna-core-envelope/ raw ngspice output into a per-point CSV + record.

Invoked by run_core_envelope.sh; see sim/lna-core-envelope/README.md for the
bench definitions every column below carries, and for what this experiment
does and does not claim.

Two things this parser does that the lna-characterization parser does not,
both of them load-bearing for issue #52:

1. **It re-references ngspice's own `sp` NF/NFmin to T0 = 290 K.** ngspice's
   two-port `sp` noise figure is referenced to the ANALYSIS temperature, not
   to a fixed source reference temperature -- verified against the committed
   record 20260926-122301-088c734, whose independent `.noise`-based nf290
   column re-references to the analysis temperature to 4 decimal places at
   every one of its 45 cells (see README "NF conventions on this bench").
   `spec/target-spec.md`'s NF row is RATIFIED at T0 = 290 K, so the raw
   `nfmin_sp_db` column is NOT the quantity that row binds. The exact
   algebraic re-reference -- the same identity
   `sim/hbt-characterization/rederive_nf_fixed_t0.py` uses for the #25
   correction -- is
       F(T0) - 1 = (F(T_a) - 1) * T_a / T0
   and its result is emitted as `nfmin290_db`, beside the raw
   `nfmin_sp_db` and the delta, so nothing is silently replaced.

2. **It reports a Q-parameterized available-gain envelope.** The
   "available-gain basis" the issue-#52 discussion uses -- |S21| plus the
   ideal-conjugate-input-match uplift -- holds the OUTPUT at 50 Ohm, i.e. it
   assumes no output matching network at all. That is not the bound it is
   sometimes read as: an output network is part of #27's scope and the
   RATIFIED S22 row requires one. This parser therefore emits both, plus the
   two-port available gain with the collector tank degraded to a finite
   inductor Q (`ga_max_q10_db`), which is the honest middle case given the
   PDK ships no inductor model. See README "Three gain metrics, and which
   one binds what".

3. **It counts stability violations from the RAW sweep points, never from a
   rounded summary column.** mu on this topology sits within parts-per-
   billion of 1 out of band (|S12| ~ -95 dB makes mu ~ 1/|S22|, and Lc is an
   ideal infinite-Q primitive, so |S22| -> 1), so a `mu_broadband_min`
   column rounded to 8 decimals prints `1.00000000` for cells that DO dip
   below 1 at some frequency. `spec/target-spec.md`'s S22 row records the
   same trap on the same bench ("the summary CSV's `s22_mag_broadband_max`
   column carries six decimals and rounds +0.18 ppm to `1.000000` ... count
   from the raw tables"). The `mu_ib_viol` / `mu_bb_viol` roll-up counts
   here are therefore derived from `n_*_pts_mu_lt_1`, which is computed on
   the unrounded sweep values, and the rounded `mu_*_lo` columns are kept
   only as a magnitude indication.

Everything else -- column meanings, the wrdata layout, the corner labels --
matches sim/lna-characterization/parse_lna_sweep.py so the two experiments'
records can be read side by side.
"""

from __future__ import annotations

import argparse
import csv
import math
import re
import sys
from pathlib import Path

# wrdata writes one "freq, value(s)" group per vector. The in-band deck
# writes: s_1_1 s_2_1 s_1_2 s_2_2 kfac mufac mag(dlt) NF NFmin -- complex
# vectors as (re, im) pairs, real vectors as a single column, and NF/NFmin
# come back as complex-typed vectors with a zero imaginary part.
INBAND_COLS = [
    ("f", 1), ("s11", 2), ("f", 1), ("s21", 2), ("f", 1), ("s12", 2),
    ("f", 1), ("s22", 2), ("f", 1), ("k", 1), ("f", 1), ("mu", 1),
    ("f", 1), ("mag_delta", 1), ("f", 1), ("nf", 2), ("f", 1), ("nfmin", 2),
]
# The broadband deck writes: kfacb mufacb mag(dltb) mag(s11) mag(s21) mag(s22)
STAB_COLS = [
    ("f", 1), ("k", 1), ("f", 1), ("mu", 1), ("f", 1), ("mag_delta", 1),
    ("f", 1), ("s11_mag", 1), ("f", 1), ("s21_mag", 1), ("f", 1), ("s22_mag", 1),
]

AE_UNIT_UM2 = 0.1152  # npn13G2 single-finger emitter area, le=0.96u * we=0.12u
LC_H = 5e-9           # the committed collector inductor
F_BAND_MID = 2.44175e9
T0_IEEE = 290.0       # spec/target-spec.md's RATIFIED NF reference temperature

# Model-card validity box (sg13g2_hbt_mod.lib), the same three limits
# sim/hbt-characterization/README.md documents.
VBE_MIN, VBE_MAX = 0.65, 0.96
VCE_MIN, VCE_MAX = 0.4, 2.0


def parse_table(path: Path, spec):
    rows = []
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        vals = [float(x) for x in line.split()]
        rec, i = {}, 0
        for name, width in spec:
            chunk = vals[i:i + width]
            i += width
            if name == "f":
                rec["freq_hz"] = chunk[0]
            elif width == 2:
                rec[name] = complex(chunk[0], chunk[1])
            else:
                rec[name] = chunk[0]
        rows.append(rec)
    return rows


def db20(x: float) -> float:
    return 20 * math.log10(x)


def nf_reref(nf_db: float, t_from: float, t_to: float) -> float:
    """Re-reference a noise figure from source temperature t_from to t_to."""
    f_from = 10 ** (nf_db / 10.0)
    return 10 * math.log10(1 + (f_from - 1) * t_from / t_to)


def s_to_y(s11, s12, s21, s22, y0=1 / 50.0):
    dn = (1 + s11) * (1 + s22) - s12 * s21
    return (
        y0 * ((1 - s11) * (1 + s22) + s12 * s21) / dn,
        y0 * (-2 * s12) / dn,
        y0 * (-2 * s21) / dn,
        y0 * ((1 + s11) * (1 - s22) + s12 * s21) / dn,
    )


def y_to_s(y11, y12, y21, y22, y0=1 / 50.0):
    dn = (y0 + y11) * (y0 + y22) - y12 * y21
    return (
        ((y0 - y11) * (y0 + y22) + y12 * y21) / dn,
        (-2 * y12 * y0) / dn,
        (-2 * y21 * y0) / dn,
        ((y0 + y11) * (y0 - y22) + y12 * y21) / dn,
    )


def ga_max_db(s11, s12, s21, s22) -> float:
    """Unilateral maximum available gain, both ports conjugate matched."""
    return (db20(abs(s21))
            - 10 * math.log10(1 - abs(s11) ** 2)
            - 10 * math.log10(1 - abs(s22) ** 2))


def ga_max_with_tank_q(s11, s12, s21, s22, q: float, freq: float) -> float:
    """Same, with the ideal collector inductor degraded to quality factor q.

    A finite-Q inductor of reactance X = 2*pi*f*Lc presents a parallel loss
    resistance Rp = q*X at the output node (the standard series->parallel
    equivalence, exact to O(1/q^2)). The DUT's Lc is an ideal SPICE `L`, so
    embedding that shunt conductance at port 2 turns the measured two-port
    into the same circuit with a Q-limited tank -- arithmetic on committed
    S-parameters, NOT a new simulation and NOT an inductor model. It is an
    UPPER bound on what an output network can deliver: it charges the tank's
    own loss but not the matching network's.
    """
    x = 2 * math.pi * freq * LC_H
    y11, y12, y21, y22 = s_to_y(s11, s12, s21, s22)
    return ga_max_db(*y_to_s(y11, y12, y21, y22 + 1.0 / (q * x)))


OP_RE = re.compile(
    r"OP ic1 (\S+) ic2 (\S+) ib1 (\S+) vce1 (\S+) vce2 (\S+) vbe1 (\S+) idd (\S+) pdc (\S+)")
NF_RE = re.compile(r"NF (lo|mid|hi) (\S+) (\S+)")
GAIN_RE = re.compile(r"GAIN (lo|mid|hi) (\S+)")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--record-id", required=True)
    ap.add_argument("--corners-dir", required=True)
    ap.add_argument("--records-dir", required=True)
    ap.add_argument("--manifest", required=True)
    ap.add_argument("--design-netlist-sha", default="unknown")
    ap.add_argument("--ngspice-version", default="unknown")
    ap.add_argument("--pdk-root", default="unknown")
    ap.add_argument("--reference-summary", default=None,
                    help="lna-characterization summary CSV the s_ctrl_a8 control "
                         "variant must reproduce (the runner's regression check)")
    args = ap.parse_args()

    corners = Path(args.corners_dir)
    records = Path(args.records_dir)
    rows = []
    failed = []

    for line in Path(args.manifest).read_text().splitlines():
        if not line.strip():
            continue
        (pid, vid, family, kind, nx1, m1, nx2, m2, area,
         wis, corner, temp, vdd) = line.split("|")
        log = corners / f"{pid}.log"
        inband = corners / f"{pid}.inband.dat"
        stab = corners / f"{pid}.stability.dat"
        if not (log.exists() and inband.exists() and stab.exists()):
            failed.append((pid, "missing output"))
            continue
        text = log.read_text()
        if "BENCH_COMPLETE" not in text:
            failed.append((pid, "no BENCH_COMPLETE"))
            continue
        m = OP_RE.search(text)
        if not m:
            failed.append((pid, "no OP line"))
            continue
        ic1, ic2, ib1, vce1, vce2, vbe1, idd, pdc = (float(x) for x in m.groups())
        nf = {k: (float(a), float(b)) for k, a, b in NF_RE.findall(text)}
        gain = {k: float(v) for k, v in GAIN_RE.findall(text)}

        ib = parse_table(inband, INBAND_COLS)
        sb = parse_table(stab, STAB_COLS)
        if not ib or not sb:
            failed.append((pid, "empty table"))
            continue

        t_a = float(temp) + 273.15
        area_i = int(area)
        jc = ic1 / (area_i * AE_UNIT_UM2) * 1e3 if area_i else float("nan")

        s21_db = [db20(abs(r["s21"])) for r in ib]
        s11_db = [db20(abs(r["s11"])) for r in ib]
        s12_db = [db20(abs(r["s12"])) for r in ib]
        s22_db = [db20(abs(r["s22"])) for r in ib]
        gin_basis = [db20(abs(r["s21"])) - 10 * math.log10(1 - abs(r["s11"]) ** 2)
                     for r in ib]
        gmax_ideal = [ga_max_db(r["s11"], r["s12"], r["s21"], r["s22"]) for r in ib]
        gmax_q10 = [ga_max_with_tank_q(r["s11"], r["s12"], r["s21"], r["s22"],
                                       10.0, r["freq_hz"]) for r in ib]
        nfmin_sp = [r["nfmin"].real for r in ib]
        nf_sp = [r["nf"].real for r in ib]
        nfmin290 = [nf_reref(v, t_a, T0_IEEE) for v in nfmin_sp]

        flags = []
        if not (VBE_MIN <= vbe1 <= VBE_MAX):
            flags.append(f"vbe1={vbe1:.4f}_outside_{VBE_MIN}-{VBE_MAX}")
        if not (VCE_MIN <= vce1 <= VCE_MAX):
            flags.append(f"vce1={vce1:.4f}_outside_{VCE_MIN}-{VCE_MAX}")
        # Model-card current limit: ic < 0.003 * Nx (A) per DEVICE instance.
        ic_per_device = ic1 / int(m1)
        if ic_per_device >= 0.003 * int(nx1):
            flags.append(f"ic_per_device={ic_per_device:.4g}_over_0.003*Nx")

        rows.append({
            "point_id": pid, "variant": vid, "family": family, "topology": kind,
            "nx1": nx1, "m1": m1, "nx2": nx2, "m2": m2,
            "emitter_units_stage1": area_i,
            "emitter_area_um2_stage1": round(area_i * AE_UNIT_UM2, 6),
            "xmis_w_um": wis,
            "corner_label": corner, "temp_c": temp, "vdd_v": vdd,
            "ic1_a": f"{ic1:.6e}", "ic2_a": f"{ic2:.6e}", "ib1_a": f"{ib1:.6e}",
            "jc1_ma_um2": round(jc, 4),
            "vce1_v": round(vce1, 4), "vce2_v": round(vce2, 4),
            "vbe1_v": round(vbe1, 4),
            "idd_a": f"{idd:.6e}", "pdc_w": f"{pdc:.6e}",
            "pdc_violates_10mw": int(pdc >= 10e-3),
            "ic1_violates_4p5ma": int(ic1 >= 4.5e-3),
            "s11_db_worst": round(max(s11_db), 4),
            "s21_db_min": round(min(s21_db), 4),
            "s21_db_max": round(max(s21_db), 4),
            "s12_db_max": round(max(s12_db), 4),
            "s22_db_worst": round(max(s22_db), 4),
            "gain_in_match_basis_db_min": round(min(gin_basis), 4),
            "ga_max_ideal_db_min": round(min(gmax_ideal), 4),
            "ga_max_q10_db_min": round(min(gmax_q10), 4),
            "nf_sp_db_at_band_lo": round(nf_sp[0], 4),
            "nfmin_sp_db_at_band_lo": round(nfmin_sp[0], 4),
            "nfmin290_db_at_band_lo": round(nfmin290[0], 4),
            "nfmin290_db_worst": round(max(nfmin290), 4),
            "nfmin_reref_delta_db": round(nfmin290[0] - nfmin_sp[0], 4),
            "nf290_db_at_band_lo": round(nf["lo"][0], 4),
            "nf290_db_worst": round(max(v[0] for v in nf.values()), 4),
            "nf30015_db_at_band_lo": round(nf["lo"][1], 4),
            "gain_ac_db_at_band_lo": round(gain["lo"], 4),
            "k_inband_min": round(min(r["k"] for r in ib), 8),
            "mu_inband_min": round(min(r["mu"] for r in ib), 8),
            # Counted on the UNROUNDED sweep values -- see docstring note 3.
            # These, not the rounded mu_*_min columns, are what the roll-up's
            # violation counts and every mu claim in the record are built on.
            "n_inband_pts_mu_lt_1": sum(1 for r in ib if r["mu"] < 1.0),
            "n_inband_pts": len(ib),
            "mag_delta_inband_max": round(max(r["mag_delta"] for r in ib), 6),
            "k_broadband_min": round(min(r["k"] for r in sb), 8),
            "mu_broadband_min": round(min(r["mu"] for r in sb), 8),
            "f_at_mu_broadband_min_hz": f"{min(sb, key=lambda r: r['mu'])['freq_hz']:.6e}",
            "n_broadband_pts_mu_lt_1": sum(1 for r in sb if r["mu"] < 1.0),
            "n_broadband_pts": len(sb),
            "s11_mag_broadband_max": round(max(r["s11_mag"] for r in sb), 6),
            "s22_mag_broadband_max": round(max(r["s22_mag"] for r in sb), 6),
            "model_card_flags": ";".join(flags) if flags else "in_box",
        })

    if not rows:
        print("parse_core_envelope.py: no parsable points", file=sys.stderr)
        return 1

    # --- Control-variant regression check --------------------------------
    control_note = "not checked (no --reference-summary given)"
    if args.reference_summary:
        ref = {}
        with open(args.reference_summary) as fh:
            for r in csv.DictReader(fh):
                ref[(r["corner_label"], r["temp_c"], r["vdd_v"])] = r
        worst, worst_key, n = 0.0, None, 0
        for r in rows:
            if r["variant"] != "s_ctrl_a8":
                continue
            key = (r["corner_label"], r["temp_c"], r["vdd_v"])
            if key not in ref:
                continue
            n += 1
            for col in ("s21_db_min", "s11_db_worst", "nfmin_sp_db_at_band_lo",
                        "nf290_db_worst", "pdc_w", "ic1_a"):
                a, b = float(r[col]), float(ref[key][col])
                rel = abs(a - b) / max(abs(b), 1e-30)
                if rel > worst:
                    worst, worst_key = rel, (key, col, a, b)
        if n:
            control_note = (
                f"{n} control cells compared against "
                f"{Path(args.reference_summary).name}; worst relative "
                f"difference {worst:.3e}"
                + (f" on {worst_key[1]} at {worst_key[0]} "
                   f"({worst_key[2]} vs {worst_key[3]})" if worst_key else ""))
            if worst > 1e-6:
                print("parse_core_envelope.py: CONTROL VARIANT DRIFTED from "
                      f"the committed reference record -- {control_note}",
                      file=sys.stderr)
                return 2
        else:
            control_note = "control variant not present in this run"

    fieldnames = list(rows[0].keys())
    csv_path = records / f"{args.record_id}.csv"
    with open(csv_path, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(rows)

    # --- Per-variant roll-up (the record's headline table) ---------------
    variants = {}
    for r in rows:
        variants.setdefault(r["variant"], []).append(r)

    def rollup(vrows):
        return {
            "family": vrows[0]["family"],
            "topology": vrows[0]["topology"],
            "geom": (f"{vrows[0]['nx1']}x{vrows[0]['m1']}"
                     + ("" if vrows[0]["topology"] == "1stage"
                        else f" + {vrows[0]['nx2']}x{vrows[0]['m2']}")),
            "xmis": vrows[0]["xmis_w_um"],
            "n": len(vrows),
            "jc_lo": min(r["jc1_ma_um2"] for r in vrows),
            "jc_hi": max(r["jc1_ma_um2"] for r in vrows),
            "ic_lo": min(float(r["ic1_a"]) for r in vrows) * 1e3,
            "ic_hi": max(float(r["ic1_a"]) for r in vrows) * 1e3,
            "pdc_lo": min(float(r["pdc_w"]) for r in vrows) * 1e3,
            "pdc_hi": max(float(r["pdc_w"]) for r in vrows) * 1e3,
            "pdc_viol": sum(r["pdc_violates_10mw"] for r in vrows),
            "ic_viol": sum(r["ic1_violates_4p5ma"] for r in vrows),
            "s21_lo": min(r["s21_db_min"] for r in vrows),
            "gin_lo": min(r["gain_in_match_basis_db_min"] for r in vrows),
            "gq10_lo": min(r["ga_max_q10_db_min"] for r in vrows),
            "gq10_viol": sum(1 for r in vrows if r["ga_max_q10_db_min"] <= 15.0),
            "nfmin290_lo": min(r["nfmin290_db_at_band_lo"] for r in vrows),
            "nfmin290_hi": max(r["nfmin290_db_worst"] for r in vrows),
            "nfmin290_viol": sum(1 for r in vrows if r["nfmin290_db_worst"] >= 1.5),
            "nf290_hi": max(r["nf290_db_worst"] for r in vrows),
            "mu_ib_lo": min(r["mu_inband_min"] for r in vrows),
            "mu_bb_lo": min(r["mu_broadband_min"] for r in vrows),
            # From the raw per-point sub-unity counts, NOT from the rounded
            # mu_*_min columns above (docstring note 3): a cell counts as
            # violating if ANY swept frequency has mu < 1.
            "mu_ib_viol": sum(1 for r in vrows if r["n_inband_pts_mu_lt_1"] > 0),
            "mu_bb_viol": sum(1 for r in vrows if r["n_broadband_pts_mu_lt_1"] > 0),
            "mu_bb_pts_lt_1": sum(r["n_broadband_pts_mu_lt_1"] for r in vrows),
            "mu_bb_pts": sum(r["n_broadband_pts"] for r in vrows),
            "oob": sum(1 for r in vrows if r["model_card_flags"] != "in_box"),
        }

    summary_path = records / f"{args.record_id}-variant-summary.csv"
    keys = ["variant", "family", "topology", "geom", "xmis", "n", "jc_lo", "jc_hi",
            "ic_lo", "ic_hi", "pdc_lo", "pdc_hi", "pdc_viol", "ic_viol", "s21_lo",
            "gin_lo", "gq10_lo", "gq10_viol", "nfmin290_lo", "nfmin290_hi",
            "nfmin290_viol", "nf290_hi", "mu_ib_lo", "mu_bb_lo", "mu_ib_viol",
            "mu_bb_viol", "mu_bb_pts_lt_1", "mu_bb_pts", "oob"]
    with open(summary_path, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=keys)
        w.writeheader()
        for vid, vrows in variants.items():
            rec = rollup(vrows)
            rec["variant"] = vid
            w.writerow({k: rec[k] for k in keys})

    md = [f"# Record {args.record_id}", ""]
    md += [
        "- **Experiment**: lna-core-envelope (issue #52) -- the achievable",
        "  (gain, NF, P_dc) envelope of the `npn13G2` cascode core, measured",
        "  by re-running `sim/lna-characterization/`'s own sp/NF/stability",
        "  bench over DUT VARIANTS across the same 45-cell PVT grid.",
        "- **Claim**: per-variant, per-cell 50 Ohm-port S-parameters, noise",
        "  figure (at the RATIFIED T0 = 290 K reference as well as raw), mu/k",
        "  stability and DC bias. **Not** a conformance claim for any variant:",
        "  every variant except `s_ctrl_a8` is a PROBE, not a design, and",
        "  nothing under `design/` changes because of this record.",
        f"- **Control**: `s_ctrl_a8` is the committed `design/netlist/lna.spice`",
        f"  (sha256 `{args.design_netlist_sha}`). Regression check: {control_note}.",
        "- **Bench definitions**: see `README.md`. Short summary: 50 Ohm",
        "  reference impedance at both ports (`sp` port sources); NF from an",
        "  input-referred `.noise` measurement with NOISELESS Rs/RL and the",
        "  source term re-introduced analytically at T0 = 290 K and 300.15 K;",
        "  ngspice's own two-port `sp` NF/NFmin reported raw AND re-referenced",
        "  to T0 = 290 K (`nfmin290_db_*`), because the raw `sp` figure is",
        "  referenced to the ANALYSIS temperature.",
        f"- **PDK**: `{args.pdk_root}` -- pinned release: see `sim/pdk.json`.",
        f"- **ngspice**: `{args.ngspice_version}`, `.options gmin=1e-10` in",
        "  every deck (identical to the lna-characterization bench).",
        "- **Ideal-passive assumption**: `Le`/`Lc`/`Cc` are ideal infinite-Q",
        "  SPICE primitives -- SG13G2 ships no simulatable inductor model",
        "  (issue #5, upstream `2AMLogic/klayout-tools#1519`). Every gain",
        "  number here is the MOST OPTIMISTIC case and every stability number",
        "  the LEAST-DAMPED case. The `ga_max_q10_db_min` column is the one",
        "  finite-Q figure, and it is ARITHMETIC on the measured",
        "  S-parameters (a shunt `Q*omega*Lc` loss at the output node), not a",
        "  passive model.",
        "- **PVT grid**: corner_label {typ,bcs,wcs,sf,fs} x temp {-40,27,125} C",
        "  x VDD {1.62,1.80,1.98} V = 45 cells per variant. `sf`/`fs` are",
        "  documented DUPLICATES of `typ` (`cornerHBT.lib` ships three real HBT",
        "  sections -- see #41), so the HBT axis is three real corners, not five.",
        f"- **Result**: {len(rows)} points across {len(variants)} variants"
        + (f"; {len(failed)} failed" if failed else "; no failed points") + ".",
        "",
        "## Per-variant roll-up (worst cell of 45 unless stated)",
        "",
        "Bars quoted against `spec/target-spec.md`'s RATIFIED rows: Gain > 15 dB,",
        "NF < 1.5 dB at T0 = 290 K, P_dc < 10 mW, mu > 1 over 10 MHz-30 GHz.",
        "",
        "**Read the `mu viol` columns, not the `mu min` ones, for pass/fail.**",
        "The minima are rounded to 6 decimals for display and mu sits within",
        "parts-per-billion of 1 out of band on this topology, so a printed",
        "`1.000000` does NOT mean the cell held mu >= 1 -- the violation counts",
        "are computed from the unrounded sweep points (a cell counts as",
        "violating if ANY of its 140 broadband / 11 in-band frequencies has",
        "mu < 1). Same trap `spec/target-spec.md`'s S22 row records for",
        "`s22_mag_broadband_max` on this bench.",
        "",
        "| variant | geom (Nx x m) | XMis | I_C1 (mA) | J_C (mA/um^2) | P_dc (mW) | P_dc viol | S21 min (dB) | G_in-match (dB) | G_A@Q=10 (dB) | NFmin@290 (dB) | NF290 worst | mu in-band min | mu in-band viol | mu 10M-30G min | mu 10M-30G viol | sub-unity mu pts | out-of-box cells |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for vid, vrows in variants.items():
        r = rollup(vrows)
        md.append(
            f"| `{vid}` | {r['geom']} | {r['xmis']}u | {r['ic_lo']:.3f}-{r['ic_hi']:.3f} "
            f"| {r['jc_lo']:.2f}-{r['jc_hi']:.2f} | {r['pdc_lo']:.2f}-{r['pdc_hi']:.2f} "
            f"| {r['pdc_viol']}/{r['n']} | {r['s21_lo']:.2f} | {r['gin_lo']:.2f} "
            f"| {r['gq10_lo']:.2f} | {r['nfmin290_lo']:.3f}-{r['nfmin290_hi']:.3f} "
            f"| {r['nf290_hi']:.3f} | {r['mu_ib_lo']:.6f} | {r['mu_ib_viol']}/{r['n']} "
            f"| {r['mu_bb_lo']:.6f} | {r['mu_bb_viol']}/{r['n']} "
            f"| {r['mu_bb_pts_lt_1']}/{r['mu_bb_pts']} "
            f"| {r['oob']}/{r['n']} |")
    md += [
        "",
        "## Links",
        "",
        "- Template: `testbench/tb_core_envelope.spice.tmpl`",
        "- Two-stage probe DUT: `dut/lna_2stage.spice.tmpl`",
        "- Runner: `run_core_envelope.sh` (serial, one ngspice at a time)",
        "- Parser: `parse_core_envelope.py`",
        f"- Per-point generated netlists: `netlist-snapshots/{args.record_id}/`",
        f"- Per-point raw ngspice logs and wrdata tables: `corners/{args.record_id}/`",
        f"- Per-point CSV: `records/{args.record_id}.csv`",
        f"- Per-variant roll-up CSV: `records/{args.record_id}-variant-summary.csv`",
    ]
    if failed:
        md += ["", "## Failed points", ""]
        md += [f"- `{p}`: {why}" for p, why in failed]
    (records / f"{args.record_id}.md").write_text("\n".join(md) + "\n")

    print(f"parse_core_envelope.py: {len(rows)} points -> {csv_path.name}")
    print(f"parse_core_envelope.py: control check -- {control_note}")
    if failed:
        print(f"parse_core_envelope.py: {len(failed)} failed points", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
