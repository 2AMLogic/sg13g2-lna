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
  sp_...nf290.dat      (issue #134; absent from historical records) wrdata
      table, 4 columns: freq NF_290K freq NF_300.15K -- the independent
      `.noise` NF over the full in-band grid (default 11 points, same as the
      S-parameter grid). Records WITHOUT it carry the historical three-point
      (lo/mid/hi) NF only and are labelled as such in the summary.
  sp_...stability.dat   wrdata table, 12 columns:
        k(2) mu(2) |delta|(2) |s11|(2) |s21|(2) |s22|(2)
  iip3_<corner>_<temp>c_vdd<vdd>v_a<amp>mv.log ngspice batch stdout:
        OP ..., NPTS .., DFT .., FFTDF .., FFT ...
"""
from __future__ import annotations

import argparse
import csv
import json
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


# --- 290 K NF grid (issue #134) -------------------------------------------
NF_BAND_LO, NF_BAND_HI = 2.4e9, 2.4835e9
NF_MIN_POINTS = 11  # the S-parameter grid
HIST_3PT = {"lo": 2.4e9, "mid": 2.44175e9, "hi": 2.4835e9}
HIST_3PT_LABEL = "HISTORICAL three-point (lo/mid/hi: 2.4, 2.44175, 2.4835 GHz)"
NF_XCHECK_TOL_DB = 1e-3  # grid sample vs the echoed lo/mid/hi at the same f


def nf_grid_label(n: int, lo: float, hi: float) -> str:
    return f"lin {n} pts {lo / 1e9:.5g}..{hi / 1e9:.5g} GHz"


def nf_sampling_note(n: int, lo: float, hi: float) -> str:
    step = (hi - lo) / (n - 1) / 1e6
    return (f"sampled maximum over {n} points ({step:.4g} MHz spacing); not a"
            " continuous-band bound -- a peak narrower than the spacing can be missed")


def validate_nf_table(path: str, spec: dict | None = None) -> list[str]:
    """Reasons (empty = valid) this nf290.dat is not a complete grid.
    Delegates missing/duplicate/non-finite/ordering checks to the #133
    validate_table. Without a manifest `spec`, the grid is the in-band band
    edges with as many points as the table has, which still catches
    interior gaps/duplicates (uneven spacing) and endpoint loss; the point
    count must be an odd number >= NF_MIN_POINTS."""
    if spec is None:
        try:
            with open(path) as fh:
                n = sum(1 for line in fh if line.split())
        except OSError as exc:
            return [f"unreadable: {exc}"]
        spec = {"mode": "lin", "n": max(n, 2), "lo": NF_BAND_LO, "hi": NF_BAND_HI}
        why = []
        if n < NF_MIN_POINTS or n % 2 == 0:
            why.append(f"{n} NF points; need an odd count >= {NF_MIN_POINTS}")
    else:
        why = []
    return why + validate_table(path, "nf290", spec)


def nf_crosscheck(nf_grid, nf290_log: dict) -> list[str]:
    """The grid samples that coincide with the echoed lo/mid/hi NF values must
    agree with them (same bench, same convention); a mismatch means the two
    noise paths of the deck have drifted apart."""
    why = []
    for tag, f_h in HIST_3PT.items():
        for f, nf, _ in nf_grid:
            if abs(f - f_h) <= FREQ_RTOL * f_h and tag in nf290_log:
                if abs(nf - nf290_log[tag]) > NF_XCHECK_TOL_DB:
                    why.append(f"NF grid sample at {f:.8e} Hz = {nf:.5f} dB disagrees with the"
                               f" echoed {tag} value {nf290_log[tag]:.5f} dB")
    return why


def read_nf_grid(path: str) -> list[tuple[float, float, float]]:
    return [(r[0], r[1], r[3]) for r in read_table(path, 4)]


def build_sparam_rows(
    corners_dir: str, exclude=(), nf_spec=None
) -> tuple[list[dict], dict, list[str], list[dict]]:
    """`exclude`: points whose tables failed grid validation; they are skipped
    (reported as skipped) so their extrema never enter an aggregate.
    `nf_spec`: manifest grid contract for nf290.dat (None = derive)."""
    rows: list[dict] = []
    nf_rows: list[dict] = []
    per_cell: dict[str, dict] = {}
    skipped: list[str] = []
    for fname in sorted(os.listdir(corners_dir)):
        if not fname.endswith(".log"):
            continue
        point_id = fname[:-4]
        m = SP_NAME_RE.match(point_id)
        if not m:
            continue
        if point_id in exclude or not is_complete(os.path.join(corners_dir, fname)) or any(
            not os.path.isfile(os.path.join(corners_dir, point_id + d))
            for d in (".inband.dat", ".stability.dat")
        ):
            skipped.append(point_id)
            continue
        log = parse_sp_log(os.path.join(corners_dir, fname))
        nf_path = os.path.join(corners_dir, point_id + ".nf290.dat")
        nf_grid = None
        if os.path.isfile(nf_path) or nf_spec is not None:
            bad = validate_nf_table(nf_path, nf_spec)
            if bad:
                skipped.append(point_id)
                print(f"parse_lna_sweep.py: {point_id}: invalid 290 K NF grid: "
                      + "; ".join(bad), file=sys.stderr)
                continue
            nf_grid = read_nf_grid(nf_path)
            xbad = nf_crosscheck(nf_grid, log["nf290"])
            if xbad:
                skipped.append(point_id)
                print(f"parse_lna_sweep.py: {point_id}: " + "; ".join(xbad), file=sys.stderr)
                continue
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
        cell = per_cell[point_id]
        cell["_nf_grid"] = nf_grid
        cell["_nf_3pt"] = log["nf290"]
        if nf_grid is not None:
            for f, nf, nf15 in nf_grid:
                nf_rows.append({
                    "point_id": point_id, "corner_label": m.group("corner"),
                    "temp_c": m.group("temp"), "vdd_v": m.group("vdd"),
                    "freq_hz": f"{f:.6e}", "nf290_db": f"{nf:.4f}",
                    "nf30015_db": f"{nf15:.4f}",
                })
    finalize_nf_columns(per_cell)
    return rows, per_cell, skipped, nf_rows


def finalize_nf_columns(per_cell: dict) -> None:
    """Replace nf290_db_worst by the grid maximum and add its frequency, the
    grid definition and the sampling limit -- but only if at least one cell
    carries a grid table. A directory of purely historical points keeps the
    exact original column set (byte-identical re-derivation)."""
    have = any(c["_nf_grid"] is not None for c in per_cell.values())
    for c in per_cell.values():
        grid, three = c.pop("_nf_grid"), c.pop("_nf_3pt")
        if not have:
            continue
        if grid is not None:
            f_w, nf_w, _ = max(grid, key=lambda t: t[1])  # first max wins ties
            n = len(grid)
            c["nf290_db_worst"] = f"{nf_w:.4f}"
            c["nf290_f_at_worst_hz"] = f"{f_w:.6e}"
            c["nf290_n_samples"] = str(n)
            c["nf290_grid"] = nf_grid_label(n, grid[0][0], grid[-1][0])
            c["nf290_sampling"] = nf_sampling_note(n, grid[0][0], grid[-1][0])
        else:
            tag = max(three, key=three.get)
            c["nf290_f_at_worst_hz"] = f"{HIST_3PT[tag]:.6e}"
            c["nf290_n_samples"] = "3"
            c["nf290_grid"] = HIST_3PT_LABEL
            c["nf290_sampling"] = ("three samples only; interior peaks between"
                                   " them are NOT checked")


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


# --- IIP3 method validity (issue #137) -----------------------------------
# IIP3 is an extrapolation that is meaningful only while IM3 rises 3:1 with
# drive. Each PVT cell is classified from its 1 mV / 2 mV drive pair:
#   valid   : |slope - 3| <= IIP3_SLOPE_TOL (inclusive; slope rounded to the
#             3 decimals the summary CSV records, so the boundary is exact)
#   invalid : finite slope with |slope - 3| >  IIP3_SLOPE_TOL
#   unknown : slope cannot be formed (a drive level missing/duplicated, a
#             nonfinite input, or zero Pin step)
# The tolerance is a measurement-method policy, NOT a ratified spec limit; see
# README "Stated limits of this IIP3 method". Raw intercepts are never
# altered; this only gates which ones headlines() accepts. Coverage (are the
# points present) stays separate: compute_coverage / --strict are unchanged.
IIP3_SLOPE_TOL = 0.15
IIP3_VALID, IIP3_INVALID, IIP3_UNKNOWN = "valid", "invalid", "unknown"
_PAIR_FIELDS = ("pin_avail_dbm_per_tone", "pim3_dbm", "iip3_dbm")


def classify_iip3_cell(
    cell_rows: list[dict], tol: float = IIP3_SLOPE_TOL
) -> tuple[str, str]:
    """Return (validity, reason) for one cell's IIP3 rows. Never raises."""
    lo = [r for r in cell_rows if r["point_id"].endswith("a1mv")]
    hi = [r for r in cell_rows if r["point_id"].endswith("a2mv")]
    missing = [n for n, g in (("a1mv", lo), ("a2mv", hi)) if len(g) != 1]
    if missing:
        return IIP3_UNKNOWN, (
            "drive level(s) missing or duplicated: " + ", ".join(missing)
        )
    vals = {}
    for name, r in (("a1mv", lo[0]), ("a2mv", hi[0])):
        for f in _PAIR_FIELDS:
            try:
                v = float(r.get(f, ""))
            except (TypeError, ValueError):
                v = float("nan")
            if not math.isfinite(v):
                return IIP3_UNKNOWN, f"nonfinite or unparsable {f} at {name}"
            vals[name, f] = v
    dpin = vals["a2mv", _PAIR_FIELDS[0]] - vals["a1mv", _PAIR_FIELDS[0]]
    if dpin == 0:
        return IIP3_UNKNOWN, "zero Pin step between drive levels"
    slope = round((vals["a2mv", "pim3_dbm"] - vals["a1mv", "pim3_dbm"]) / dpin, 3)
    if not math.isfinite(slope):
        return IIP3_UNKNOWN, "nonfinite slope"
    if round(abs(slope - 3.0), 6) <= tol:
        return IIP3_VALID, f"slope {slope:.3f} within 3 +/- {tol:g}"
    return IIP3_INVALID, f"slope {slope:.3f} outside 3 +/- {tol:g}"


def iip3_validity_by_cell(
    cells: list[dict], iip3_rows: list[dict], tol: float = IIP3_SLOPE_TOL
) -> dict:
    """{(corner, temp, vdd): (validity, reason)} for every summary cell."""
    by_cell: dict[tuple[str, str, str], list[dict]] = {}
    for r in iip3_rows:
        by_cell.setdefault((r["corner_label"], r["temp_c"], r["vdd_v"]), []).append(r)
    out = {}
    for c in cells:
        key = (c["corner_label"], c["temp_c"], c["vdd_v"])
        out[key] = classify_iip3_cell(by_cell.get(key, []), tol)
    return out


# --- Expected-point coverage ---------------------------------------------
# Exit codes of `--strict` (only meaningful with --manifest): 0 when every
# expected point is complete and every required drive pair is intact, else
# STRICT_EXIT_BASE plus a bitmask of what is wrong, so each failure mode has
# its own exit: 1 = expected log absent, 2 = log present but truncated or
# missing its wrdata tables, 4 = a mandatory IIP3 drive pair is not intact.
STRICT_EXIT_BASE = 16
EXIT_MISSING, EXIT_FAILED, EXIT_PAIR = 1, 2, 4
# 8 = a retained sp wrdata table exists but violates the frequency-grid
# contract in the manifest (see validate_sp_tables).
EXIT_GRID = 8

# --- Frequency-grid contract ---------------------------------------------
# The grids are generated by testbench/tb_lna_sparam.spice.tmpl:
#   in-band   : `sp lin N LO HI`  -> N points, f_i = LO + i*(HI-LO)/(N-1)
#   stability : `sp dec P LO HI`   -> ngspice emits floor(P*log10(HI/LO))+1
#               points f_i = LO*10^(i/P); the last point is therefore BELOW
#               HI unless P*log10(HI/LO) is an integer (committed deck:
#               140 points, 1e7 .. 2.985e10 Hz for HI = 3e10).
# wrdata prints 9 significant digits (%.8e), so a frequency can differ from
# the ideal grid by ~5e-9 relative; FREQ_RTOL leaves two decades of margin.
# Repeated scale columns come from the same vector and were bit-identical in
# every committed table; SCALE_RTOL only absorbs print formatting.
FREQ_RTOL = 1e-6
SCALE_RTOL = 1e-7
# wrdata column layout: indices of the (repeated) frequency-scale columns.
SCALE_COLS = {
    "inband": (24, [0, 3, 6, 9, 12, 14, 16, 18, 21], ".inband.dat"),
    "stability": (12, [0, 2, 4, 6, 8, 10], ".stability.dat"),
    # issue #134: independent 290 K .noise sweep (freq NF290 freq NF300.15).
    # Optional in a manifest (historical manifests have no such grid).
    "nf290": (4, [0, 2], ".nf290.dat"),
}
REQUIRED_GRIDS = {"inband", "stability"}


def expected_grid(spec: dict) -> list[float]:
    """Ideal frequency list for one manifest `grid` contract."""
    n, lo, hi = spec["n"], spec["lo"], spec["hi"]
    if spec["mode"] == "lin":
        return [lo + i * (hi - lo) / (n - 1) for i in range(n)] if n > 1 else [lo]
    npts = int(math.floor(n * math.log10(hi / lo) + 1e-9)) + 1
    return [lo * 10.0 ** (i / n) for i in range(npts)]


def validate_table(path: str, kind: str, spec: dict) -> list[str]:
    """Reasons (empty = valid) this retained wrdata table breaks its grid
    contract. Never raises on bad content; the point of the check is to
    report it."""
    ncols, scale_cols, _ = SCALE_COLS[kind]
    rows: list[list[float]] = []
    try:
        with open(path) as fh:
            for ln, line in enumerate(fh, 1):
                parts = line.split()
                if not parts:
                    continue
                try:
                    vals = [float(x) for x in parts]
                except ValueError:
                    return [f"line {ln}: non-numeric token"]
                if len(vals) != ncols:
                    return [f"line {ln}: expected {ncols} columns, got {len(vals)}"]
                rows.append(vals)
    except OSError as exc:
        return [f"unreadable: {exc}"]
    want = expected_grid(spec)
    why: list[str] = []
    if len(rows) != len(want):
        why.append(f"{len(rows)} frequency points, expected {len(want)}")
    bad = next(((i, c) for i, r in enumerate(rows) for c, v in enumerate(r)
                if not math.isfinite(v)), None)
    if bad:
        why.append(f"non-finite value (NaN/Inf) at row {bad[0] + 1}, column {bad[1]}")
        return why
    freqs = [r[0] for r in rows]
    for i in range(1, len(freqs)):
        if freqs[i] == freqs[i - 1]:
            why.append(f"duplicate frequency {freqs[i]:.8e} Hz at row {i + 1}")
            break
        if freqs[i] < freqs[i - 1]:
            why.append(f"frequencies not increasing at row {i + 1}")
            break
    if rows:
        if abs(freqs[0] - want[0]) > FREQ_RTOL * want[0]:
            why.append(f"lower endpoint {freqs[0]:.8e} Hz, expected {want[0]:.8e} Hz")
        if abs(freqs[-1] - want[-1]) > FREQ_RTOL * want[-1]:
            why.append(f"upper endpoint {freqs[-1]:.8e} Hz, expected {want[-1]:.8e} Hz")
    # First divergence from the ideal grid (a deleted interior row shows up
    # here as every later row shifting by one grid step).
    for i, (f, w) in enumerate(zip(freqs, want)):
        if abs(f - w) > FREQ_RTOL * w:
            why.append(f"first grid mismatch at row {i + 1}: {f:.8e} Hz,"
                       f" expected {w:.8e} Hz")
            break
    for i, r in enumerate(rows):
        off = next((c for c in scale_cols
                    if abs(r[c] - r[0]) > SCALE_RTOL * abs(r[0])), None)
        if off is not None:
            why.append(f"row {i + 1}: repeated frequency column {off} = {r[off]:.8e}"
                       f" disagrees with column 0 = {r[0]:.8e}")
            break
    return why


def read_manifest(path: str) -> dict:
    """Parse an expected-point manifest (written by run_lna_sweep.sh).

    Line format (blank lines and '#' comments ignored):
        kind <campaign|smoke>
        sp <point_id>
        iip3 <point_id>
        pair <point_id_lo> <point_id_hi>   # mandatory two-level drive pair
        grid <inband|stability> <lin|dec> <n_or_pts_per_dec> <f_lo> <f_hi>
    `grid` lines are the frequency-grid contract every sp point's tables are
    validated against (smoke and campaign alike). A manifest without them is a
    legacy manifest: coverage then says the grids were NOT validated.
    Nominal-only extra drive levels appear only as `iip3` lines, so they are
    expected to exist but are never part of a required pair.
    """
    man = {"kind": "campaign", "sp": [], "iip3": [], "pairs": [], "grids": {}}
    with open(path) as fh:
        for n, line in enumerate(fh, 1):
            parts = line.split("#", 1)[0].split()
            if not parts:
                continue
            key, args = parts[0], parts[1:]
            if key == "kind" and len(args) == 1 and args[0] in ("campaign", "smoke"):
                man["kind"] = args[0]
            elif key in ("sp", "iip3") and len(args) == 1:
                man[key].append(args[0])
            elif key == "pair" and len(args) == 2:
                man["pairs"].append(args)
            elif (key == "grid" and len(args) == 5 and args[0] in SCALE_COLS
                  and args[1] in ("lin", "dec")):
                try:
                    spec = {"mode": args[1], "n": int(args[2]),
                            "lo": float(args[3]), "hi": float(args[4])}
                except ValueError:
                    raise SystemExit(f"{path}:{n}: bad grid numbers: {line.strip()!r}")
                if spec["n"] < 1 or not 0 < spec["lo"] < spec["hi"] or (
                        spec["mode"] == "lin" and spec["n"] < 2):
                    raise SystemExit(f"{path}:{n}: impossible grid: {line.strip()!r}")
                man["grids"][args[0]] = spec
            else:
                raise SystemExit(f"{path}:{n}: unrecognised manifest line: {line.strip()!r}")
    if not man["sp"] and not man["iip3"]:
        raise SystemExit(f"{path}: manifest lists no expected points")
    if man["grids"] and not REQUIRED_GRIDS <= set(man["grids"]):
        raise SystemExit(f"{path}: grid contract must define both "
                         + " and ".join(sorted(REQUIRED_GRIDS)))
    ng = man["grids"].get("nf290")
    if ng and (ng["mode"] != "lin" or ng["n"] < NF_MIN_POINTS or ng["n"] % 2 == 0):
        raise SystemExit(f"{path}: nf290 grid must be lin with an odd point count"
                         f" >= {NF_MIN_POINTS}")
    known = set(man["iip3"])
    for pair in man["pairs"]:
        for pid in pair:
            if pid not in known:
                raise SystemExit(f"{path}: pair member {pid} is not a listed iip3 point")
    return man


def compute_coverage(corners_dir: str, man: dict) -> dict:
    """Compare the expected inventory with what is on disk."""

    def state(point_id: str, dats: tuple[str, ...]) -> str:
        log = os.path.join(corners_dir, point_id + ".log")
        if not os.path.isfile(log):
            return "missing"
        if not is_complete(log):
            return "failed"
        if any(not os.path.isfile(os.path.join(corners_dir, point_id + d)) for d in dats):
            return "failed"
        return "completed"

    states: dict[str, str] = {}
    invalid_grids: list[dict] = []
    for pid in man["sp"]:
        dats = (".inband.dat", ".stability.dat") + (
            (".nf290.dat",) if "nf290" in man.get("grids", {}) else ())
        states[pid] = state(pid, dats)
        if states[pid] == "completed" and man.get("grids"):
            for kind in man["grids"]:
                ext = SCALE_COLS[kind][2]
                tbl = os.path.join(corners_dir, pid + ext)
                reasons = validate_table(tbl, kind, man["grids"][kind])
                if kind == "nf290" and not reasons:
                    reasons = nf_crosscheck(
                        read_nf_grid(tbl),
                        parse_sp_log(os.path.join(corners_dir, pid + ".log"))["nf290"])
                for reason in reasons:
                    invalid_grids.append(
                        {"point": pid, "artifact": pid + ext, "reason": reason}
                    )
            if any(g["point"] == pid for g in invalid_grids):
                states[pid] = "invalid"
    for pid in man["iip3"]:
        states[pid] = state(pid, ())
    expected = list(man["sp"]) + list(man["iip3"])
    broken_pairs = []
    for pair in man["pairs"]:
        bad = [pid for pid in pair if states[pid] != "completed"]
        if bad:
            broken_pairs.append({"points": list(pair), "unavailable": bad})
    on_disk = {f[:-4] for f in os.listdir(corners_dir) if f.endswith(".log")}
    cov = {
        "inventory_kind": man["kind"],
        "expected": expected,
        "completed": [p for p in expected if states[p] == "completed"],
        "missing": [p for p in expected if states[p] == "missing"],
        "failed": [p for p in expected if states[p] == "failed"],
        "invalid_grids": invalid_grids,
        "frequency_grid_contract": man.get("grids") or "absent (legacy manifest)",
        "missing_drive_pairs": broken_pairs,
        "unexpected": sorted(on_disk - set(expected)),
    }
    cov["status"] = (
        "complete"
        if not (cov["missing"] or cov["failed"] or invalid_grids or broken_pairs)
        else "partial"
    )
    return cov


def strict_exit_code(cov: dict) -> int:
    if cov["status"] == "complete":
        return 0
    mask = 0
    if cov["missing"]:
        mask |= EXIT_MISSING
    if cov["failed"]:
        mask |= EXIT_FAILED
    if cov["missing_drive_pairs"]:
        mask |= EXIT_PAIR
    if cov.get("invalid_grids"):
        mask |= EXIT_GRID
    return STRICT_EXIT_BASE + mask


def coverage_prose(cov: dict | None) -> list[str]:
    """Record-prose lines stating the coverage result. A partial inventory is
    never described as a full campaign; a smoke inventory is never described
    as a PVT campaign even when complete."""
    if cov is None:
        return [
            "- **Coverage**: no expected-point manifest (historical replay);"
            " completeness NOT established."
        ]
    n_exp, n_done = len(cov["expected"]), len(cov["completed"])
    smoke = cov["inventory_kind"] == "smoke"
    if isinstance(cov.get("frequency_grid_contract"), dict):
        grid_note = "; sp frequency grids validated against the manifest contract"
    else:
        grid_note = ("; sp frequency grids NOT validated (legacy manifest without"
                     " a grid contract)")
    if cov["status"] == "complete":
        what = (
            "smoke inventory complete -- a plumbing check, NOT a PVT campaign"
            if smoke
            else "campaign inventory complete"
        )
        return [f"- **Coverage**: {what}; {n_done}/{n_exp} expected points completed,"
                " every mandatory IIP3 drive pair intact" + grid_note + "."]
    lines = [
        f"- **Coverage**: PARTIAL INVENTORY -- {n_done}/{n_exp} expected points"
        " completed. This record is NOT a full campaign; every aggregate"
        " below covers only the completed points."
    ]
    for key, label in (("missing", "Missing (no log)"), ("failed", "Failed (incomplete)")):
        if cov[key]:
            lines.append(f"  - {label}: {', '.join(cov[key])}")
    for ig in cov.get("invalid_grids", []):
        lines.append(
            f"  - Invalid frequency grid: {ig['point']} / {ig['artifact']}: {ig['reason']}"
        )
    for bp in cov["missing_drive_pairs"]:
        lines.append(
            "  - Broken mandatory drive pair (no IM3 slope check): "
            + " + ".join(bp["points"])
            + f" (unavailable: {', '.join(bp['unavailable'])})"
        )
    return lines


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


def headlines(
    summary_csv: str, iip3_csv: str, slope_tol: float = IIP3_SLOPE_TOL
) -> str:
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
    if "nf290_grid" in worst_nf:
        n_hist = sum(1 for r in cells if r["nf290_n_samples"] == "3")
        out.append(
            f"- **NF (T0 = 290 K, worst SAMPLED in-band point per cell)**: worst "
            f"{worst_nf['nf290_db_worst']} dB at {worst_nf['nf290_f_at_worst_hz']} Hz,"
            f" {cell_label(worst_nf)}; best-cell worst "
            f"{best_nf['nf290_db_worst']} dB at {cell_label(best_nf)}. Grid:"
            f" {worst_nf['nf290_grid']}; {worst_nf['nf290_sampling']}."
            + (f" ({n_hist} cell(s) are HISTORICAL three-point only.)" if n_hist else "")
        )
    else:
        # Historical (three-point) records: wording kept byte-identical so
        # the committed record re-derives unchanged; the committed record's
        # own text states these are three samples (lo/mid/hi).
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
        verdict = iip3_validity_by_cell(cells, iip3, slope_tol)
        counts = {
            k: sum(1 for v, _ in verdict.values() if v == k)
            for k in (IIP3_VALID, IIP3_INVALID, IIP3_UNKNOWN)
        }
        all_valid = counts[IIP3_VALID] == len(cells)
        # Accepted intercepts: every IIP3 point (including the nominal
        # cell's extra drive levels) of a cell whose 1/2 mV pair is valid.
        acc = [
            r
            for r in iip3
            if verdict.get((r["corner_label"], r["temp_c"], r["vdd_v"]),
                           (IIP3_UNKNOWN, ""))[0] == IIP3_VALID
        ]
        if acc:
            worst_iip3 = min(acc, key=lambda r: float(r["iip3_dbm"]))
            best_iip3 = max(acc, key=lambda r: float(r["iip3_dbm"]))
            nom = [
                r
                for r in acc
                if r["corner_label"] == "typ"
                and r["temp_c"] == "27"
                and r["vdd_v"] == "1.80"
            ]
            nom_2mv = next((r for r in nom if r["point_id"].endswith("a2mv")), None)
            scope = (
                f"{len(acc)} drive points"
                if all_valid
                else f"{len(acc)} drive points of {counts[IIP3_VALID]} "
                f"method-valid cell(s) only"
            )
            out.append(
                f"- **IIP3 (two-tone, {scope})**: "
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
        else:
            out.append(
                "- **IIP3 (two-tone)**: NO accepted intercept -- no PVT cell "
                f"passed the IM3 slope validity check (3 +/- {slope_tol:g}); "
                "raw extrapolated values remain in the IIP3 CSV but are not "
                "claims."
            )
        slopes = [
            float(r["im3_slope_2pt"])
            for r in cells
            if r.get("im3_slope_2pt")
            and verdict[(r["corner_label"], r["temp_c"], r["vdd_v"])][0]
            == IIP3_VALID
        ]
        if all_valid:
            out.append(
                f"- **IM3 slope check (two drive levels per cell)**: slope in "
                f"[{min(slopes):.3f}, {max(slopes):.3f}] (ideal cubic = 3.000) "
                f"-> the extrapolation's 3:1 assumption holds at every cell."
            )
        else:
            inv = "; ".join(
                f"{k[0]}/{k[1]} C/VDD={k[2]} V: {why}"
                for k, (v, why) in sorted(verdict.items())
                if v != IIP3_VALID
            )
            rng = (
                f"slope over valid cells in [{min(slopes):.3f}, {max(slopes):.3f}]"
                if slopes
                else "no cell has a validated slope"
            )
            out.append(
                f"- **IM3 slope check (two drive levels per cell)**: tolerance "
                f"3 +/- {slope_tol:g}; {counts[IIP3_VALID]} valid / "
                f"{counts[IIP3_INVALID]} invalid / {counts[IIP3_UNKNOWN]} "
                f"unknown of {len(cells)} cells; {rng}. The 3:1 assumption is "
                f"claimed only at the valid cells; the other cells' IIP3 is "
                f"discarded (not accepted). Not valid -- {inv}."
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
    ap.add_argument("--nf-csv", help="raw per-(cell, frequency) 290 K NF table")
    ap.add_argument("--summary-csv")
    ap.add_argument("--band-lo")
    ap.add_argument("--band-hi")
    ap.add_argument("--df")
    ap.add_argument("--f1")
    ap.add_argument("--f2")
    ap.add_argument("--headlines", action="store_true")
    ap.add_argument(
        "--iip3-slope-tol",
        type=float,
        default=IIP3_SLOPE_TOL,
        help="headlines: accept a cell's IIP3 only if |IM3 slope - 3| <= this"
        f" (default {IIP3_SLOPE_TOL}; measurement policy, see README)",
    )
    ap.add_argument("--manifest", help="expected-point manifest; enables coverage")
    ap.add_argument("--coverage-json", help="write the coverage sidecar here")
    ap.add_argument(
        "--strict",
        action="store_true",
        help="with --manifest: exit nonzero (16+mask) if any expected point or"
        " mandatory drive pair is incomplete; reduction still runs and is"
        " marked partial",
    )
    ap.add_argument("--coverage-prose", action="store_true",
                    help="print record prose for --coverage-json (or historical)")
    ap.add_argument("--coverage-status", action="store_true",
                    help="print complete|partial|unknown for --coverage-json")
    args = ap.parse_args()

    if args.coverage_prose or args.coverage_status:
        cov = None
        if args.coverage_json and os.path.isfile(args.coverage_json):
            with open(args.coverage_json) as fh:
                cov = json.load(fh)
        if args.coverage_status:
            print(cov["status"] if cov else "unknown")
        else:
            print("\n".join(coverage_prose(cov)))
        return 0

    if args.headlines:
        print(headlines(args.summary_csv, args.iip3_csv, args.iip3_slope_tol))
        return 0

    cov = None
    if args.manifest:
        cov = compute_coverage(args.corners_dir, read_manifest(args.manifest))
        if args.coverage_json:
            with open(args.coverage_json, "w") as fh:
                json.dump(cov, fh, indent=2, sort_keys=True)
                fh.write("\n")
        print(
            f"parse_lna_sweep.py: coverage {cov['status'].upper()} -- "
            f"{len(cov['completed'])}/{len(cov['expected'])} expected points "
            f"({len(cov['missing'])} missing, {len(cov['failed'])} failed, "
            f"{len(cov['invalid_grids'])} invalid-grid finding(s), "
            f"{len(cov['missing_drive_pairs'])} broken drive pair(s))",
            file=sys.stderr,
        )
    elif args.strict:
        raise SystemExit("--strict requires --manifest")

    man_grids = read_manifest(args.manifest)["grids"] if args.manifest else {}
    sparam_rows, per_cell, sp_skipped, nf_rows = build_sparam_rows(
        args.corners_dir,
        exclude={g["point"] for g in cov["invalid_grids"]} if cov else (),
        nf_spec=man_grids.get("nf290"),
    )
    if not sparam_rows and cov is not None and args.strict:
        print(f"parse_lna_sweep.py: {args.corners_dir}: no complete sp_* artefacts",
              file=sys.stderr)
        return strict_exit_code(cov)
    if not sparam_rows:
        raise SystemExit(
            f"{args.corners_dir}: no complete sp_* artefacts found"
            + (f" ({len(sp_skipped)} incomplete: {', '.join(sp_skipped)})" if sp_skipped else "")
        )
    iip3_rows, iip3_skipped = build_iip3_rows(args.corners_dir)
    join_iip3_into_summary(per_cell, iip3_rows)

    write_csv(args.sparam_csv, sparam_rows, list(sparam_rows[0].keys()))
    if nf_rows and args.nf_csv:
        write_csv(args.nf_csv, nf_rows, list(nf_rows[0].keys()))
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
    if cov is not None and args.strict:
        return strict_exit_code(cov)
    return 0


if __name__ == "__main__":
    sys.exit(main())
