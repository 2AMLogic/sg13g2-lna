#!/usr/bin/env python3
"""Re-derive the fixed-T0 NF columns of the committed hbt-characterization
records (issue #25).

No simulation runs here. This is the exact algebraic re-referencing the
issue describes: ngspice-46 computes a resistor's thermal-noise source at
the ANALYSIS temperature regardless of any per-instance `temp=` override
(measured, not assumed: see
sim/lna-characterization/testbench/tb_resistor_noise_temp_probe.spice, which
lands with issue #18's PR), so the committed NF cells at -40 C and 125 C
carry the 50 Ohm source's thermal noise at the swept AMBIENT temperature,
not at the fixed T0 = 300.15 K the records claim
(sim/hbt-characterization/README.md, "NF" bench definition).

Re-referencing the same input-referred noise density to the declared T0 is
exact because noise powers from uncorrelated sources add:

    committed inoise^2   = N_rest + 4*k*T_amb*RS
    corrected  inoise^2  = N_rest + 4*k*T0*RS      (T0 = 300.15 K)
                        = 10^(NF_committed/10) * 4*k*T0*RS
                          + 4*k*RS*(T0 - T_amb)

where NF_committed is the published nf_db of the source row, N_rest is the
input-referred contribution of everything except RS's own thermal noise
(HBT, RL -- which this bench deliberately keeps at ambient -- bias tees),
and T_amb = temp_c + 273.15. The committed 27 C cells need no correction
(T_amb == T0 there); every other row in this correction record states its
own nf_delta_db = NF_corrected - NF_committed so the size of the
correction is auditable per point.

Regeneration (no PDK, no ngspice, deterministic):

    sim/hbt-characterization/rederive_nf_fixed_t0.py \
        --record-id <id> \
        --record-id-csv sim/hbt-characterization/records/<id>-corrected.csv \
        --summary-csv sim/hbt-characterization/records/<id>-summary.csv

Every number the correction record quotes is either copied from a source
row, or this one documented formula applied to it -- there is no fitting
and no modelling here. The round-trip identity (recover inoise^2, correct to
T_amb again, get the committed NF back to <1e-9 dB) and the reproduction of
record 20260918-203652-4293920's committed validity_flags column by the
same three model-card limits its README documents are asserted below, so
the derivation cannot silently drift from the source pipeline that
produced the committed data.
"""
from __future__ import annotations

import argparse
import csv
import math
import os
import subprocess
import sys
import time

KB = 1.380649e-23  # Boltzmann constant, J/K (exact SI)
T0 = 300.15  # K -- the source reference temperature both records declare
RS = 50.0  # Ohm -- the NF bench's source resistance, per README.md
AFFECTED_TEMPS = (-40, 125)  # temp_c cells whose T_amb != T0; 27 C is identity

# The model-card validity limits sg13g2_hbt_mod.lib states and the README's
# "Model-card validity box" section documents. Record 20260918's per-row
# validity_flags column was produced from these same limits; the script
# asserts its re-derivation reproduces that committed column exactly, then
# applies the same classification to record 20260910 (which has no such
# column -- "its rows can be classified after the fact with the same three
# limits", per the README).
IC_LIMIT_FACTOR = 0.003  # ic < 0.003*Nx A
VBE_MIN = 0.65  # vbe 0.65 - 0.96 V
VBE_MAX = 0.96
VCE_MIN = 0.4  # vce 0.4 - 2.0 V
VCE_MAX = 2.0


def source_row_iter(path: str):
    with open(path, newline="") as f:
        for row in csv.DictReader(f):
            yield row


def classify_validity(ic_a: float, vbe_v: float, vce_v: float, nx: int) -> str:
    flags = []
    if ic_a >= IC_LIMIT_FACTOR * nx:
        flags.append("ic_high")
    if vbe_v < VBE_MIN:
        flags.append("vbe_low")
    if vbe_v > VBE_MAX:
        flags.append("vbe_high")
    if vce_v < VCE_MIN:
        flags.append("vce_low")
    if vce_v > VCE_MAX:
        flags.append("vce_high")
    return ";".join(flags)


def float_or_none(s: str):
    if s is None or s.strip() == "":
        return None
    return float(s)


def corrected_nf_db(nf_committed_db: float, temp_c: float):
    """The exact algebraic re-referencing, in dB, and its round-trip check.

    Returns (nf_corrected_db, roundtrip_error_db). roundtrip_error_db is
    |10*log10(...) back at T_amb minus nf_committed_db| -- a pure floating
    point residue; anything above 1e-9 dB would mean the algebra or the
    constants are wrong, and the caller asserts on it.
    """
    t_amb = temp_c + 273.15
    floor = 4.0 * KB * T0 * RS  # V^2/Hz available input noise at T0
    noise = (10.0 ** (nf_committed_db / 10.0)) * floor  # committed inoise^2
    noise_fixed = noise + 4.0 * KB * RS * (T0 - t_amb)  # corrected inoise^2
    nf_fixed = 10.0 * math.log10(noise_fixed / floor)
    # Round trip: reverse the same substitution and demand the committed
    # value back (guards the algebra, not the data).
    noise_back = noise_fixed - 4.0 * KB * RS * (T0 - t_amb)
    roundtrip = 10.0 * math.log10(noise_back / floor)
    return nf_fixed, abs(nf_committed_db - roundtrip)


def mint_record_id() -> str:
    head = subprocess.run(
        ["git", "rev-parse", "--short", "HEAD"],
        capture_output=True, text=True, check=True,
    ).stdout.strip()
    return time.strftime("%Y%m%d-%H%M%S", time.gmtime()) + "-" + head


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    ap.add_argument("--record-id", default=None,
                    help="record id for this correction record "
                         "(default: <UTC now>-<short git-sha>, matching "
                         "sim/README.md's <YYYYMMDD>-<HHMMSS>-<short-git-"
                         "sha> UTC convention)")
    ap.add_argument("--record-id-csv", default=None,
                    help="output: per-point corrected CSV path")
    ap.add_argument("--summary-csv", default=None,
                    help="output: per-cell corrected noise-optimum CSV path")
    ap.add_argument("--repo-root", default=None,
                    help="repo root to resolve the default record paths "
                         "(default: git toplevel of this file's worktree)")
    args = ap.parse_args()

    repo_root = args.repo_root
    if repo_root is None:
        repo_root = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            capture_output=True, text=True, check=True,
        ).stdout.strip()

    rec = args.record_id or mint_record_id()
    out_points = args.record_id_csv or os.path.join(
        repo_root, "sim/hbt-characterization", "records",
        rec + "-corrected.csv")
    out_summary = args.summary_csv or os.path.join(
        repo_root, "sim/hbt-characterization", "records",
        rec + "-summary.csv")

    sources = [
        ("20260910-200059-7da7038",
         os.path.join(repo_root, "sim/hbt-characterization/records",
                      "20260910-200059-7da7038.csv")),
        ("20260918-203652-4293920",
         os.path.join(repo_root, "sim/hbt-characterization/records",
                      "20260918-203652-4293920.csv")),
    ]

    point_header = [
        "source_record", "point_id", "corner_label", "hbt_section",
        "temp_c", "nx", "vce_v", "vbe_v", "ic_a", "jc_ma_um2",
        "ft_hz", "gain_db", "nf_db_committed_ambient_source",
        "nf_db_corrected_fixed_t0", "nf_delta_db", "validity_flags",
    ]

    worst_roundtrip = 0.0
    flag_mismatches = 0  # vs record 20260918's committed column
    rows_out = []
    per_row = []  # (source, row dict, nf_fixed, flags) for the summary pass
    for source_id, path in sources:
        for row in source_row_iter(path):
            temp_c = int(row["temp_c"])
            if temp_c not in AFFECTED_TEMPS:
                continue
            nf_src = float_or_none(row["nf_db"])
            ic_a = float_or_none(row["ic_a"])
            vbe_v = float_or_none(row["vbe_v"])
            vce_v = float_or_none(row["vce_v"])
            flags = classify_validity(ic_a, vbe_v, vce_v, int(row["nx"]))
            committed_flags = (row.get("validity_flags") or "").strip()
            if committed_flags and committed_flags != flags:
                flag_mismatches += 1
                print(f"FLAG MISMATCH {row['point_id']}: committed "
                      f"{committed_flags!r} vs derived {flags!r}",
                      file=sys.stderr)
            if nf_src is None:
                # A source row with no NF (a dropped operating point)
                # passes through untouched; it was never a claim.
                nf_fixed = None
                delta = None
            else:
                nf_fixed, rt = corrected_nf_db(nf_src, temp_c)
                worst_roundtrip = max(worst_roundtrip, rt)
                delta = nf_fixed - nf_src
            out = {
                "source_record": source_id,
                "point_id": row["point_id"],
                "corner_label": row["corner_label"],
                "hbt_section": row["hbt_section"],
                "temp_c": row["temp_c"],
                "nx": row["nx"],
                "vce_v": row["vce_v"],
                "vbe_v": row["vbe_v"],
                "ic_a": row["ic_a"],
                "jc_ma_um2": row["jc_ma_um2"],
                "ft_hz": row["ft_hz"],
                "gain_db": row["gain_db"],
                "nf_db_committed_ambient_source": row["nf_db"],
                "nf_db_corrected_fixed_t0":
                    "" if nf_fixed is None else f"{nf_fixed:.6f}",
                "nf_delta_db": "" if delta is None else f"{delta:.6f}",
                "validity_flags": flags,
            }
            rows_out.append(out)
            per_row.append((source_id, out, flags))

    assert worst_roundtrip < 1e-9, (
        f"algebra round-trip residue too large: {worst_roundtrip} dB")
    assert flag_mismatches == 0, (
        "derived validity flags disagree with record 20260918's committed "
        "validity_flags column -- do not ship this derivation")

    # Per-(source, corner, temp, nx, vce) corrected noise optima.
    cells = {}
    for source_id, out, flags in per_row:
        key = (source_id, out["corner_label"], out["temp_c"], out["nx"],
               out["vce_v"])
        cells.setdefault(key, []).append((out, flags))

    summary_rows = []
    for (source_id, corner, temp_c, nx, vce), pts in sorted(
            cells.items(), key=lambda kv: (
                kv[0][0], kv[0][1], int(kv[0][2]), int(kv[0][3]),
                float(kv[0][4]))):
        def optimum(pool):
            valid = [p for p in pool
                     if p[0]["nf_db_corrected_fixed_t0"] != ""]
            if not valid:
                return None
            best = min(valid, key=lambda p: float(
                p[0]["nf_db_corrected_fixed_t0"]))
            return best[0]
        in_box = [p for p in pts if p[1] == ""]
        for scope, pool in (("all", pts), ("in_box", in_box)):
            best = optimum(pool)
            summary_rows.append({
                "source_record": source_id,
                "corner_label": corner,
                "temp_c": temp_c,
                "nx": nx,
                "vce_v": vce,
                "scope": scope,
                "n_points": len(pool),
                "noise_optimum_jc_ma_um2":
                    "" if best is None else best["jc_ma_um2"],
                "noise_optimum_nf_db_committed_ambient_source":
                    "" if best is None
                    else best["nf_db_committed_ambient_source"],
                "noise_optimum_nf_db_corrected_fixed_t0":
                    "" if best is None
                    else best["nf_db_corrected_fixed_t0"],
                "noise_optimum_nf_delta_db":
                    "" if best is None else best["nf_delta_db"],
                "noise_optimum_gain_db":
                    "" if best is None else best["gain_db"],
                "noise_optimum_ft_hz":
                    "" if best is None else best["ft_hz"],
                "noise_optimum_validity_flags":
                    "" if best is None else best["validity_flags"],
            })

    os.makedirs(os.path.dirname(out_points), exist_ok=True)
    # LF line endings, matching the committed source record CSVs so a
    # reviewer's re-derivation is byte-identical (same pin as
    # sim/lna-characterization's parser).
    with open(out_points, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=point_header, lineterminator="\n")
        w.writeheader()
        w.writerows(rows_out)
    with open(out_summary, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(summary_rows[0].keys()),
                           lineterminator="\n")
        w.writeheader()
        w.writerows(summary_rows)

    affected_temps_seen = sorted(set(int(r["temp_c"]) for r in rows_out))
    print(f"corrected points: {len(rows_out)} rows "
          f"(affected temps only: {affected_temps_seen}; "
          f"27 C rows are identity and stay only in the source records)")
    print(f"corrected cells: {len(cells)}")
    print(f"worst algebra round-trip residue: {worst_roundtrip:.3e} dB")
    print(f"validity-flag reproduction mismatches vs 20260918: "
          f"{flag_mismatches}")

    # Headline corrected figures, mechanically, for the record .md:
    # the corrected whole-grid and in-box noise optima per (source, nx,
    # scope), and the previously binding wcs/125C corners.
    def grid_optima(source_id, nx, in_box_only):
        pool = [(o, fl) for s, o, fl in per_row
                if s == source_id and int(o["nx"]) == nx
                and (not in_box_only or fl == "")
                and o["nf_db_corrected_fixed_t0"] != ""]
        if not pool:
            return None
        best, fl = min(pool, key=lambda p: float(
            p[0]["nf_db_corrected_fixed_t0"]))
        return best, fl

    print("\n== headline corrected noise optima ==")
    for source_id in ("20260910-200059-7da7038", "20260918-203652-4293920"):
        for nx in (1, 8):
            for in_box_only in (False, True):
                got = grid_optima(source_id, nx, in_box_only)
                if got is None:
                    print(f"{source_id} nx={nx} "
                          f"in_box={in_box_only}: no rows")
                    continue
                b, _ = got
                print(
                    f"{source_id} nx={nx} in_box={in_box_only}: "
                    f"J_C={b['jc_ma_um2']} mA/um^2 at corner={b['corner_label']}, "
                    f"{b['temp_c']} C, V_CE={b['vce_v']} V, V_BE={b['vbe_v']} V -> "
                    f"NF committed {b['nf_db_committed_ambient_source']} dB, "
                    f"NF corrected {b['nf_db_corrected_fixed_t0']} dB "
                    f"(delta {b['nf_delta_db']} dB), "
                    f"gain {b['gain_db']} dB, flags '{b['validity_flags']}'")

    def binding(source_id, nx, in_box_only):
        pool = [(o, fl) for s, o, fl in per_row
                if s == source_id and int(o["nx"]) == nx
                and o["corner_label"] == "wcs" and o["temp_c"] == "125"
                and (not in_box_only or fl == "")
                and o["nf_db_corrected_fixed_t0"] != ""]
        if not pool:
            return None
        best, fl = min(pool, key=lambda p: float(
            p[0]["nf_db_corrected_fixed_t0"]))
        return best

    print("\n== corrected noise optima at the previously binding corner "
          "(wcs/125C) ==")
    for source_id in ("20260910-200059-7da7038", "20260918-203652-4293920"):
        for nx in (1, 8):
            for in_box_only in (False, True):
                b = binding(source_id, nx, in_box_only)
                if b is None:
                    print(f"{source_id} nx={nx} in_box={in_box_only}: "
                          "no rows")
                    continue
                print(
                    f"{source_id} nx={nx} in_box={in_box_only}: "
                    f"J_C={b['jc_ma_um2']} at V_CE={b['vce_v']} V, "
                    f"V_BE={b['vbe_v']} V -> "
                    f"NF committed {b['nf_db_committed_ambient_source']} dB, "
                    f"NF corrected {b['nf_db_corrected_fixed_t0']} dB "
                    f"(delta {b['nf_delta_db']} dB)")

    print(f"\nrecord id: {rec}")
    print(f"wrote {out_points}")
    print(f"wrote {out_summary}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
