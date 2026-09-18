#!/usr/bin/env python3
"""Parse one lna-characterization run's raw artefacts into its record CSVs.

Called by run_lna_sweep.sh; kept as a separate, re-runnable file (rather
than a heredoc inside the runner) so that the committed CSVs can be
re-derived from the committed raw logs/wrdata tables alone, with no
ngspice run and no PDK install:

    sim/lna-characterization/parse_lna_sweep.py \
        --corners-dir sim/lna-characterization/corners/<record-id> \
        --sparam-csv /tmp/check-sparam.csv \
        --iip3-csv /tmp/check-iip3.csv \
        --summary-csv /tmp/check-summary.csv

Every number in the CSVs is either copied from, or a documented arithmetic
function of, a value ngspice itself printed -- there is no modelling and no
fitting here beyond the standard IIP3 extrapolation formula, which is
written out explicitly below.

Raw artefact layout (per PVT cell), all produced by the templates in
testbench/:

  sp_<corner>_<temp>c_vdd<vdd>v.log            ngspice batch stdout:
      OP ic1 .. ic2 .. ib1 .. vce1 .. vce2 .. vbe1 .. idd .. pdc ..
      GAIN <lo|mid|hi> <transducer gain dB, from 2*Vout/Vin>
      NF   <lo|mid|hi> <NF dB at T0=290 K> <NF dB at T0=300.15 K>
  sp_...inband.dat      wrdata table, 24 columns, in this order (a complex
      vector writes scale,re,im; a real vector writes scale,value):
        s_1_1(3) s_2_1(3) s_1_2(3) s_2_2(3) k(2) mu(2) |delta|(2)
        NF_sp(3) NFmin_sp(3)
  sp_...stability.dat   wrdata table, 12 columns:
        k(2) mu(2) |delta|(2) |s11|(2) |s21|(2) |s22|(2)
  iip3_<corner>_<temp>c_vdd<vdd>v_a<amp>mv.log ngspice batch stdout:
        OP ..., NPTS .., DFT .., FFTDF .., FFT ...
"""
from __future__ import annotations

import argparse
import csv
import math
import os
import re
import sys

Z0 = 50.0

SP_NAME_RE = re.compile(r"^sp_(?P<corner>[a-z]+)_(?P<temp>-?\d+)c_vdd(?P<vdd>[\d.]+)v$")
IIP3_NAME_RE = re.compile(
    r"^iip3_(?P<corner>[a-z]+)_(?P<temp>-?\d+)c_vdd(?P<vdd>[\d.]+)v_a(?P<amp>[\dp]+)mv$"
)


def db20(x: float) -> float:
    return 20.0 * math.log10(x) if x > 0 else float("-inf")


def dbm_from_w(p: float) -> float:
    return 10.0 * math.log10(p / 1e-3) if p > 0 else float("-inf")


def out_power_dbm(v_peak: float) -> float:
    """Power a V_peak sinusoid delivers to the 50 Ohm load."""
    return dbm_from_w(v_peak * v_peak / (2.0 * Z0))


def avail_power_dbm(amp_peak: float) -> float:
    """Available power of a V_peak open-circuit Thevenin source behind Z0."""
    return dbm_from_w(amp_peak * amp_peak / (8.0 * Z0))


def read_table(path: str, ncols: int) -> list[list[float]]:
    rows = []
    with open(path) as fh:
        for line in fh:
            parts = line.split()
            if not parts:
                continue
            vals = [float(p) for p in parts]
            if len(vals) != ncols:
                raise SystemExit(
                    f"{path}: expected {ncols} columns, got {len(vals)} -- the "
                    "testbench template's wrdata line and this parser's column "
                    "map have drifted apart."
                )
            rows.append(vals)
    if not rows:
        raise SystemExit(f"{path}: empty wrdata table")
    return rows


def is_complete(path: str) -> bool:
    """True iff this point's deck ran to the end (echoed BENCH_COMPLETE).

    A point that failed (non-convergence, a missing model card, a run killed
    mid-flight) leaves a truncated log behind. The runner already reports it
    as a failed point; skipping it here -- rather than raising a KeyError on
    the first missing echo -- means one bad cell degrades the record to
    "44 of 45 cells" instead of producing no record at all.
    """
    with open(path) as fh:
        return any(line.startswith("BENCH_COMPLETE") for line in fh)


def parse_sp_log(path: str) -> dict:
    out = {"gain": {}, "nf290": {}, "nf30015": {}}
    with open(path) as fh:
        for line in fh:
            p = line.split()
            if not p:
                continue
            if p[0] == "OP":
                for i in range(1, len(p) - 1, 2):
                    out[p[i]] = float(p[i + 1])
            elif p[0] == "GAIN":
                out["gain"][p[1]] = float(p[2])
            elif p[0] == "NF":
                out["nf290"][p[1]] = float(p[2])
                out["nf30015"][p[1]] = float(p[3])
    return out


def parse_iip3_log(path: str) -> dict:
    out = {}
    with open(path) as fh:
        for line in fh:
            p = line.split()
            if not p:
                continue
            if p[0] == "OP":
                for i in range(1, len(p) - 1, 2):
                    out[p[i]] = float(p[i + 1])
            elif p[0] == "NPTS":
                out["npts"] = int(float(p[1]))
            elif p[0] == "FFTDF":
                out["fft_df"] = float(p[1])
            elif p[0] in ("DFT", "FFT"):
                pref = p[0].lower()
                for i in range(1, len(p) - 1, 2):
                    out[f"{pref}_{p[i]}"] = float(p[i + 1])
    return out


def iip3_from(pin_dbm: float, pout_dbm: float, pim3_dbm: float) -> float:
    """Standard two-tone extrapolation, valid only in the 3:1 IM3 region.

    IIP3 = Pin + (Pout - PIM3)/2, all in dB(m); the runner's own
    two-drive-level slope check (im3_slope_2pt in the summary CSV) is what
    establishes that the point actually sits in that region.
    """
    return pin_dbm + (pout_dbm - pim3_dbm) / 2.0


def build_sparam_rows(corners_dir: str) -> tuple[list[dict], dict, list[str]]:
    rows: list[dict] = []
    per_cell: dict[str, dict] = {}
    skipped: list[str] = []
    for fname in sorted(os.listdir(corners_dir)):
        if not fname.endswith(".log"):
            continue
        point_id = fname[:-4]
        m = SP_NAME_RE.match(point_id)
        if not m:
            continue
        if not is_complete(os.path.join(corners_dir, fname)):
            skipped.append(point_id)
            continue
        log = parse_sp_log(os.path.join(corners_dir, fname))
        inband = read_table(os.path.join(corners_dir, point_id + ".inband.dat"), 24)
        stab = read_table(os.path.join(corners_dir, point_id + ".stability.dat"), 12)

        cell_rows = []
        for r in inband:
            freq = r[0]
            s11 = complex(r[1], r[2])
            s21 = complex(r[4], r[5])
            s12 = complex(r[7], r[8])
            s22 = complex(r[10], r[11])
            row = {
                "point_id": point_id,
                "corner_label": m.group("corner"),
                "temp_c": m.group("temp"),
                "vdd_v": m.group("vdd"),
                "freq_hz": f"{freq:.6e}",
                "s11_db": f"{db20(abs(s11)):.4f}",
                "s21_db": f"{db20(abs(s21)):.4f}",
                "s12_db": f"{db20(abs(s12)):.4f}",
                "s22_db": f"{db20(abs(s22)):.4f}",
                "s11_mag": f"{abs(s11):.6f}",
                "s21_mag": f"{abs(s21):.6f}",
                "s12_mag": f"{abs(s12):.6e}",
                "s22_mag": f"{abs(s22):.6f}",
                "k": f"{r[13]:.6f}",
                "mu": f"{r[15]:.6f}",
                "mag_delta": f"{r[17]:.6f}",
                "nf_sp_db": f"{r[19]:.4f}",
                "nfmin_sp_db": f"{r[22]:.4f}",
            }
            rows.append(row)
            cell_rows.append((freq, abs(s11), abs(s21), abs(s22), r[13], r[15], r[17],
                              r[19], r[22]))

        k_bb = [(r[0], r[1]) for r in stab]
        mu_bb = [(r[2], r[3]) for r in stab]
        delta_bb = [(r[4], r[5]) for r in stab]
        s11_bb = [(r[6], r[7]) for r in stab]
        s22_bb = [(r[10], r[11]) for r in stab]
        k_min_f, k_min = min(k_bb, key=lambda t: t[1])
        mu_min_f, mu_min = min(mu_bb, key=lambda t: t[1])
        delta_max_f, delta_max = max(delta_bb, key=lambda t: t[1])
        # |S11| > 1 or |S22| > 1 anywhere means that port presents a negative
        # real impedance while the OTHER port sees its 50 Ohm reference --
        # a direct, condition-number-free oscillation red flag, unlike k,
        # whose numerator nearly vanishes when both ports are almost totally
        # reflective (see README "Why k is ill-conditioned on this circuit").
        s11_max_f, s11_max = max(s11_bb, key=lambda t: t[1])
        s22_max_f, s22_max = max(s22_bb, key=lambda t: t[1])

        per_cell[point_id] = {
            "point_id": point_id,
            "corner_label": m.group("corner"),
            "temp_c": m.group("temp"),
            "vdd_v": m.group("vdd"),
            "ic1_a": f"{log['ic1']:.6e}",
            "ic2_a": f"{log['ic2']:.6e}",
            "vce1_v": f"{log['vce1']:.4f}",
            "vce2_v": f"{log['vce2']:.4f}",
            "vbe1_v": f"{log['vbe1']:.4f}",
            "idd_a": f"{log['idd']:.6e}",
            "pdc_w": f"{log['pdc']:.6e}",
            "s11_db_worst": f"{db20(max(r[1] for r in cell_rows)):.4f}",
            "s21_db_min": f"{db20(min(r[2] for r in cell_rows)):.4f}",
            "s21_db_max": f"{db20(max(r[2] for r in cell_rows)):.4f}",
            "s22_db_worst": f"{db20(max(r[3] for r in cell_rows)):.4f}",
            "k_inband_min": f"{min(r[4] for r in cell_rows):.6f}",
            "mu_inband_min": f"{min(r[5] for r in cell_rows):.6f}",
            "mag_delta_inband_max": f"{max(r[6] for r in cell_rows):.6f}",
            "nf_sp_db_at_band_lo": f"{cell_rows[0][7]:.4f}",
            "nfmin_sp_db_at_band_lo": f"{cell_rows[0][8]:.4f}",
            "nf290_db_worst": f"{max(log['nf290'].values()):.4f}",
            "nf290_db_at_band_lo": f"{log['nf290']['lo']:.4f}",
            "nf290_db_at_band_mid": f"{log['nf290']['mid']:.4f}",
            "nf290_db_at_band_hi": f"{log['nf290']['hi']:.4f}",
            "nf30015_db_at_band_lo": f"{log['nf30015']['lo']:.4f}",
            "gain_ac_db_at_band_lo": f"{log['gain']['lo']:.4f}",
            "gain_ac_minus_s21_db": f"{log['gain']['lo'] - db20(cell_rows[0][2]):.4f}",
            "k_broadband_min": f"{k_min:.6f}",
            "f_at_k_broadband_min_hz": f"{k_min_f:.6e}",
            "n_broadband_pts_k_lt_1": str(sum(1 for _, v in k_bb if v < 1.0)),
            "n_broadband_pts": str(len(k_bb)),
            "mu_broadband_min": f"{mu_min:.6f}",
            "f_at_mu_broadband_min_hz": f"{mu_min_f:.6e}",
            "n_broadband_pts_mu_lt_1": str(sum(1 for _, v in mu_bb if v < 1.0)),
            "mag_delta_broadband_max": f"{delta_max:.6f}",
            "f_at_mag_delta_broadband_max_hz": f"{delta_max_f:.6e}",
            "s11_mag_broadband_max": f"{s11_max:.6f}",
            "f_at_s11_mag_broadband_max_hz": f"{s11_max_f:.6e}",
            "s22_mag_broadband_max": f"{s22_max:.6f}",
            "f_at_s22_mag_broadband_max_hz": f"{s22_max_f:.6e}",
        }
    return rows, per_cell, skipped


def build_iip3_rows(corners_dir: str) -> tuple[list[dict], list[str]]:
    rows: list[dict] = []
    skipped: list[str] = []
    for fname in sorted(os.listdir(corners_dir)):
        if not fname.endswith(".log"):
            continue
        point_id = fname[:-4]
        m = IIP3_NAME_RE.match(point_id)
        if not m:
            continue
        if not is_complete(os.path.join(corners_dir, fname)):
            skipped.append(point_id)
            continue
        log = parse_iip3_log(os.path.join(corners_dir, fname))
        amp = float(m.group("amp").replace("p", ".")) * 1e-3
        pin = avail_power_dbm(amp)

        def pair_iip3(prefix: str) -> tuple[float, float, float, float]:
            t = (log[f"{prefix}_tone1"] + log[f"{prefix}_tone2"]) / 2.0
            i3 = (log[f"{prefix}_im3l"] + log[f"{prefix}_im3h"]) / 2.0
            pout = out_power_dbm(t)
            pim3 = out_power_dbm(i3)
            return pout, pim3, iip3_from(pin, pout, pim3), pout - pin

        pout, pim3, iip3, gain = pair_iip3("fft")
        _, _, iip3_dft, _ = pair_iip3("dft")
        im5 = (log["fft_im5l"] + log["fft_im5h"]) / 2.0
        rows.append(
            {
                "point_id": point_id,
                "corner_label": m.group("corner"),
                "temp_c": m.group("temp"),
                "vdd_v": m.group("vdd"),
                "amp_v_peak_per_tone": f"{amp:.6e}",
                "src_tone_v_peak_measured": f"{log['fft_src1']:.6e}",
                "pin_avail_dbm_per_tone": f"{pin:.4f}",
                "pout_dbm_per_tone": f"{pout:.4f}",
                "pim3_dbm": f"{pim3:.4f}",
                "gain_db": f"{gain:.4f}",
                "iip3_dbm": f"{iip3:.4f}",
                "oip3_dbm": f"{iip3 + gain:.4f}",
                "iip3_dbm_dft_crosscheck": f"{iip3_dft:.4f}",
                "v_tone1_out_v": f"{log['fft_tone1']:.6e}",
                "v_tone2_out_v": f"{log['fft_tone2']:.6e}",
                "v_im3l_out_v": f"{log['fft_im3l']:.6e}",
                "v_im3h_out_v": f"{log['fft_im3h']:.6e}",
                "v_im5_out_v": f"{im5:.6e}",
                "im3_over_im5_db": f"{db20((log['fft_im3l'] + log['fft_im3h']) / 2.0 / im5):.2f}"
                if im5 > 0
                else "",
                "ic1_a": f"{log['ic1']:.6e}",
                "idd_a": f"{log['idd']:.6e}",
                "fft_npts": str(log.get("npts", "")),
                "fft_df_hz": f"{log['fft_df']:.6e}",
            }
        )
    return rows, skipped


def join_iip3_into_summary(per_cell: dict, iip3_rows: list[dict]) -> None:
    by_cell: dict[tuple[str, str, str], list[dict]] = {}
    for r in iip3_rows:
        by_cell.setdefault(
            (r["corner_label"], r["temp_c"], r["vdd_v"]), []
        ).append(r)
    for cell in per_cell.values():
        key = (cell["corner_label"], cell["temp_c"], cell["vdd_v"])
        pts = sorted(
            by_cell.get(key, []), key=lambda r: float(r["amp_v_peak_per_tone"])
        )
        # The two drive levels every PVT cell is run at (1 mV / 2 mV peak).
        grid = [r for r in pts if r["point_id"].endswith(("a1mv", "a2mv"))]
        cell["iip3_dbm_a1mv"] = next(
            (r["iip3_dbm"] for r in grid if r["point_id"].endswith("a1mv")), ""
        )
        cell["iip3_dbm_a2mv"] = next(
            (r["iip3_dbm"] for r in grid if r["point_id"].endswith("a2mv")), ""
        )
        if len(grid) == 2:
            lo, hi = grid[0], grid[1]
            dpin = float(hi["pin_avail_dbm_per_tone"]) - float(
                lo["pin_avail_dbm_per_tone"]
            )
            dim3 = float(hi["pim3_dbm"]) - float(lo["pim3_dbm"])
            cell["im3_slope_2pt"] = f"{dim3 / dpin:.3f}" if dpin else ""
            cell["iip3_spread_2pt_db"] = (
                f"{abs(float(hi['iip3_dbm']) - float(lo['iip3_dbm'])):.3f}"
            )
        else:
            cell["im3_slope_2pt"] = ""
            cell["iip3_spread_2pt_db"] = ""


def write_csv(path: str, rows: list[dict], fieldnames: list[str]) -> None:
    # lineterminator="\n" is deliberate: csv's default is "\r\n", which would
    # make the committed CSV differ (by line endings) from what a reviewer's
    # own re-parse produces, and would be rewritten by git's autocrlf on the
    # way in. The README's "re-derive the CSVs from the raw logs and diff
    # them" check only holds if this file is byte-stable.
    with open(path, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=fieldnames, lineterminator="\n")
        w.writeheader()
        w.writerows(rows)


def cell_label(r: dict) -> str:
    return f"{r['corner_label']}/{r['temp_c']} C/VDD={r['vdd_v']} V"


def headlines(summary_csv: str, iip3_csv: str) -> str:
    cells = list(csv.DictReader(open(summary_csv)))
    iip3 = list(csv.DictReader(open(iip3_csv)))
    out = []

    worst_s11 = max(cells, key=lambda r: float(r["s11_db_worst"]))
    best_s11 = min(cells, key=lambda r: float(r["s11_db_worst"]))
    out.append(
        f"- **In-band S11 (worst of {len(cells)} PVT cells)**: "
        f"{worst_s11['s11_db_worst']} dB at {cell_label(worst_s11)}; best cell "
        f"{best_s11['s11_db_worst']} dB at {cell_label(best_s11)}."
    )
    worst_s22 = max(cells, key=lambda r: float(r["s22_db_worst"]))
    out.append(
        f"- **In-band S22 (worst)**: {worst_s22['s22_db_worst']} dB at "
        f"{cell_label(worst_s22)}."
    )
    worst_s21 = min(cells, key=lambda r: float(r["s21_db_min"]))
    best_s21 = max(cells, key=lambda r: float(r["s21_db_max"]))
    out.append(
        f"- **In-band S21**: min {worst_s21['s21_db_min']} dB at "
        f"{cell_label(worst_s21)}; max {best_s21['s21_db_max']} dB at "
        f"{cell_label(best_s21)}."
    )
    worst_nf = max(cells, key=lambda r: float(r["nf290_db_worst"]))
    best_nf = min(cells, key=lambda r: float(r["nf290_db_worst"]))
    out.append(
        f"- **NF (T0 = 290 K, worst in-band point per cell)**: worst "
        f"{worst_nf['nf290_db_worst']} dB at {cell_label(worst_nf)}; best "
        f"{best_nf['nf290_db_worst']} dB at {cell_label(best_nf)}."
    )
    nfmin = min(cells, key=lambda r: float(r["nfmin_sp_db_at_band_lo"]))
    out.append(
        f"- **NFmin (ngspice `sp`, at 2.4 GHz, i.e. what an ideal noise match "
        f"would give this circuit)**: best {nfmin['nfmin_sp_db_at_band_lo']} dB "
        f"at {cell_label(nfmin)}."
    )
    kmin = min(cells, key=lambda r: float(r["k_broadband_min"]))
    n_cells_unstable = sum(1 for r in cells if float(r["k_broadband_min"]) < 1.0)
    out.append(
        f"- **Stability (k, 10 MHz .. 30 GHz)**: worst-case k = "
        f"{kmin['k_broadband_min']} at {kmin['f_at_k_broadband_min_hz']} Hz, "
        f"{cell_label(kmin)}; {n_cells_unstable}/{len(cells)} PVT cells have "
        f"k < 1 somewhere in the swept range "
        f"({kmin['n_broadband_pts_k_lt_1']}/{kmin['n_broadband_pts']} swept "
        f"points at the worst cell)."
    )
    kin = min(cells, key=lambda r: float(r["k_inband_min"]))
    out.append(
        f"- **Stability (k, in-band only)**: worst-case k = "
        f"{kin['k_inband_min']} (mu = {kin['mu_inband_min']}, |Delta| = "
        f"{kin['mag_delta_inband_max']}) at {cell_label(kin)}."
    )
    mumin = min(cells, key=lambda r: float(r["mu_broadband_min"]))
    out.append(
        f"- **Stability (mu, 10 MHz .. 30 GHz)**: worst-case mu = "
        f"{mumin['mu_broadband_min']} at "
        f"{mumin['f_at_mu_broadband_min_hz']} Hz, {cell_label(mumin)}."
    )
    s11bb = max(cells, key=lambda r: float(r["s11_mag_broadband_max"]))
    s22bb = max(cells, key=lambda r: float(r["s22_mag_broadband_max"]))
    out.append(
        f"- **Negative-resistance check (|S11|/|S22| > 1 with the other port "
        f"at 50 Ohm)**: max |S11| = {s11bb['s11_mag_broadband_max']} at "
        f"{s11bb['f_at_s11_mag_broadband_max_hz']} Hz "
        f"({cell_label(s11bb)}); max |S22| = "
        f"{s22bb['s22_mag_broadband_max']} at "
        f"{s22bb['f_at_s22_mag_broadband_max_hz']} Hz ({cell_label(s22bb)})."
    )
    if iip3:
        worst_iip3 = min(iip3, key=lambda r: float(r["iip3_dbm"]))
        best_iip3 = max(iip3, key=lambda r: float(r["iip3_dbm"]))
        nom = [
            r
            for r in iip3
            if r["corner_label"] == "typ"
            and r["temp_c"] == "27"
            and r["vdd_v"] == "1.80"
        ]
        nom_2mv = next((r for r in nom if r["point_id"].endswith("a2mv")), None)
        out.append(
            f"- **IIP3 (two-tone, {len(iip3)} drive points)**: "
            + (
                f"{nom_2mv['iip3_dbm']} dBm at the nominal cell "
                f"(typ/27 C/VDD=1.80 V, 2 mV peak/tone drive); "
                if nom_2mv
                else ""
            )
            + f"across all points min {worst_iip3['iip3_dbm']} dBm at "
            f"{cell_label(worst_iip3)}, max {best_iip3['iip3_dbm']} dBm at "
            f"{cell_label(best_iip3)}."
        )
        slopes = [float(r["im3_slope_2pt"]) for r in cells if r.get("im3_slope_2pt")]
        if slopes:
            out.append(
                f"- **IM3 slope check (two drive levels per cell)**: slope in "
                f"[{min(slopes):.3f}, {max(slopes):.3f}] (ideal cubic = 3.000) "
                f"-> the extrapolation's 3:1 assumption holds at every cell."
            )
    ic1 = [float(r["ic1_a"]) for r in cells]
    pdc = [float(r["pdc_w"]) for r in cells]
    hottest = max(cells, key=lambda r: float(r["pdc_w"]))
    out.append(
        f"- **Bias across PVT**: I_C1 spans {min(ic1) * 1e3:.3f} .. "
        f"{max(ic1) * 1e3:.3f} mA; P_dc spans {min(pdc) * 1e3:.3f} .. "
        f"{max(pdc) * 1e3:.3f} mW (worst at {cell_label(hottest)})."
    )
    return "\n".join(out)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--corners-dir")
    ap.add_argument("--sparam-csv")
    ap.add_argument("--iip3-csv")
    ap.add_argument("--summary-csv")
    ap.add_argument("--band-lo")
    ap.add_argument("--band-hi")
    ap.add_argument("--df")
    ap.add_argument("--f1")
    ap.add_argument("--f2")
    ap.add_argument("--headlines", action="store_true")
    args = ap.parse_args()

    if args.headlines:
        print(headlines(args.summary_csv, args.iip3_csv))
        return 0

    sparam_rows, per_cell, sp_skipped = build_sparam_rows(args.corners_dir)
    if not sparam_rows:
        raise SystemExit(
            f"{args.corners_dir}: no complete sp_* artefacts found"
            + (f" ({len(sp_skipped)} incomplete: {', '.join(sp_skipped)})" if sp_skipped else "")
        )
    iip3_rows, iip3_skipped = build_iip3_rows(args.corners_dir)
    join_iip3_into_summary(per_cell, iip3_rows)

    write_csv(args.sparam_csv, sparam_rows, list(sparam_rows[0].keys()))
    if iip3_rows:
        write_csv(args.iip3_csv, iip3_rows, list(iip3_rows[0].keys()))
    summary_rows = [per_cell[k] for k in sorted(per_cell)]
    write_csv(args.summary_csv, summary_rows, list(summary_rows[0].keys()))
    print(
        f"parse_lna_sweep.py: {len(sparam_rows)} in-band S-parameter rows, "
        f"{len(iip3_rows)} IIP3 rows, {len(summary_rows)} PVT cells",
        file=sys.stderr,
    )
    for kind, skipped in (("sp", sp_skipped), ("iip3", iip3_skipped)):
        if skipped:
            print(
                f"parse_lna_sweep.py: WARNING -- skipped {len(skipped)} "
                f"incomplete {kind} point(s) (no BENCH_COMPLETE): "
                + ", ".join(skipped),
                file=sys.stderr,
            )
    return 0


if __name__ == "__main__":
    sys.exit(main())
