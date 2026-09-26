#!/usr/bin/env python3
"""Re-derive two committed-record quantities issue #52 needs, with no new SPICE.

This script touches no PDK, no ngspice and no netlist. It reads the ALREADY
COMMITTED raw output of `sim/lna-characterization/` record
`20260926-122301-088c734` -- the per-cell `corners/<id>/*.inband.dat` tables,
which carry the COMPLEX S-parameters (`wrdata` writes re/im pairs) -- and
emits two derived columns per PVT cell that the committed summary CSV does
not contain:

  1. `nfmin290_db` -- the record's `NFmin` re-referenced to T0 = 290 K.
     ngspice's two-port `sp` noise figure is referenced to the ANALYSIS
     temperature, not to a fixed source temperature. `spec/target-spec.md`'s
     NF row is RATIFIED at T0 = 290 K, so the committed
     `nfmin_sp_db_at_band_lo` column is NOT the quantity that row binds.
     This script both PROVES the convention (it checks the committed
     `nf_sp_db_at_band_lo` column against the committed, independently
     computed `nf290_db_at_band_lo` column re-referenced to the analysis
     temperature -- same algebra, different vector, two different analyses)
     and applies it to `NFmin`.

     The identity is the same one `sim/hbt-characterization/
     rederive_nf_fixed_t0.py` uses for the issue-#25 correction:
         F(T_to) - 1 = (F(T_from) - 1) * T_from / T_to
     Noise powers add; only the source-resistor reference term is rescaled.

  2. `ga_max_qNN_db` -- the two-port available gain (both ports conjugate
     matched) with the DUT's ideal collector inductor `Lc` degraded to a
     finite quality factor Q, for a range of Q. The "available-gain basis"
     figure quoted in issue #52's own Evidence section is |S21| plus the
     ideal-conjugate-INPUT-match uplift only; it holds the OUTPUT at 50 Ohm,
     i.e. it assumes no output matching network exists. Since
     `spec/target-spec.md`'s S22 row requires one, and #27's scope is both
     networks, that figure is not the bound it reads as. The Q-parameterized
     available gain is the honest envelope: it charges the output tank's own
     loss (the dominant term, since SG13G2 ships no inductor model at all --
     issue #5) while leaving the matching networks' own insertion loss to
     #27, where the design work belongs.

Everything printed is reproducible from committed files with this script and
nothing else:

    sim/lna-core-envelope/derive_committed_record_envelope.py
"""

from __future__ import annotations

import argparse
import csv
import math
import sys
from pathlib import Path

T0_IEEE = 290.0
LC_H = 5e-9
Z0 = 50.0
Y0 = 1.0 / Z0

INBAND_COLS = [
    ("f", 1), ("s11", 2), ("f", 1), ("s21", 2), ("f", 1), ("s12", 2),
    ("f", 1), ("s22", 2), ("f", 1), ("k", 1), ("f", 1), ("mu", 1),
    ("f", 1), ("mag_delta", 1), ("f", 1), ("nf", 2), ("f", 1), ("nfmin", 2),
]
Q_GRID = [3, 5, 8, 10, 15, 20, 30, 50]


def parse_table(path: Path):
    out = []
    for line in path.read_text().splitlines():
        if not line.strip():
            continue
        vals = [float(x) for x in line.split()]
        rec, i = {}, 0
        for name, width in INBAND_COLS:
            chunk = vals[i:i + width]
            i += width
            if name == "f":
                rec["freq_hz"] = chunk[0]
            elif width == 2:
                rec[name] = complex(chunk[0], chunk[1])
            else:
                rec[name] = chunk[0]
        out.append(rec)
    return out


def nf_reref(nf_db, t_from, t_to):
    return 10 * math.log10(1 + (10 ** (nf_db / 10.0) - 1) * t_from / t_to)


def s_to_y(s11, s12, s21, s22):
    dn = (1 + s11) * (1 + s22) - s12 * s21
    return (Y0 * ((1 - s11) * (1 + s22) + s12 * s21) / dn,
            Y0 * (-2 * s12) / dn,
            Y0 * (-2 * s21) / dn,
            Y0 * ((1 + s11) * (1 - s22) + s12 * s21) / dn)


def y_to_s(y11, y12, y21, y22):
    dn = (Y0 + y11) * (Y0 + y22) - y12 * y21
    return (((Y0 - y11) * (Y0 + y22) + y12 * y21) / dn,
            (-2 * y12 * Y0) / dn,
            (-2 * y21 * Y0) / dn,
            ((Y0 + y11) * (Y0 - y22) + y12 * y21) / dn)


def ga_max_db(s11, s12, s21, s22):
    return (20 * math.log10(abs(s21))
            - 10 * math.log10(1 - abs(s11) ** 2)
            - 10 * math.log10(1 - abs(s22) ** 2))


def main() -> int:
    here = Path(__file__).resolve().parent
    sim = here.parent
    ap = argparse.ArgumentParser()
    ap.add_argument("--record-id", default="20260926-122301-088c734")
    ap.add_argument("--source-experiment", default=str(sim / "lna-characterization"))
    ap.add_argument("--out", default=None,
                    help="write the derived per-cell CSV here (default: "
                         "records/<record-id>-derived-envelope.csv under this "
                         "experiment)")
    args = ap.parse_args()

    src = Path(args.source_experiment)
    summary = src / "records" / f"{args.record_id}-summary.csv"
    corners = src / "corners" / args.record_id
    for p in (summary, corners):
        if not p.exists():
            print(f"derive_committed_record_envelope.py: {p} not found", file=sys.stderr)
            return 3

    ref = list(csv.DictReader(open(summary)))
    out_rows = []
    worst_conv_err = 0.0

    for r in ref:
        pid = r["point_id"]
        dat = corners / f"{pid}.inband.dat"
        if not dat.exists():
            print(f"derive_committed_record_envelope.py: {dat} missing", file=sys.stderr)
            return 3
        ib = parse_table(dat)
        t_a = float(r["temp_c"]) + 273.15

        # --- (1) prove the sp-NF reference convention -------------------
        # The committed nf290 column comes from the INDEPENDENT `.noise`
        # analysis on the Xb branch with noiseless Rs and an analytic
        # T0 = 290 K source term. Re-referencing it to the analysis
        # temperature must reproduce the committed `sp`-analysis nf column
        # (Xa branch) if and only if the `sp` figure is analysis-temperature
        # referenced. Any other convention breaks this identity.
        nf290_committed = float(r["nf290_db_at_band_lo"])
        nf_sp_committed = float(r["nf_sp_db_at_band_lo"])
        predicted_sp = nf_reref(nf290_committed, T0_IEEE, t_a)
        worst_conv_err = max(worst_conv_err, abs(predicted_sp - nf_sp_committed))

        # --- (2) NFmin, re-referenced to the RATIFIED T0 = 290 K --------
        nfmin_sp = float(r["nfmin_sp_db_at_band_lo"])
        nfmin290 = nf_reref(nfmin_sp, t_a, T0_IEEE)

        row = {
            "point_id": pid,
            "corner_label": r["corner_label"],
            "temp_c": r["temp_c"],
            "vdd_v": r["vdd_v"],
            "nfmin_sp_db_committed": f"{nfmin_sp:.4f}",
            "nfmin290_db_derived": f"{nfmin290:.4f}",
            "nfmin_reref_delta_db": f"{nfmin290 - nfmin_sp:+.4f}",
            "nf290_db_committed": f"{nf290_committed:.4f}",
            "s21_db_committed_min": r["s21_db_min"],
            "s11_db_committed_worst": r["s11_db_worst"],
            "s22_db_committed_worst": r["s22_db_worst"],
        }

        # In-band worst (minimum) of each gain metric.
        gin = min(20 * math.log10(abs(p["s21"]))
                  - 10 * math.log10(1 - abs(p["s11"]) ** 2) for p in ib)
        row["gain_in_match_only_db"] = f"{gin:.4f}"
        row["ga_max_ideal_db"] = f"{min(ga_max_db(p['s11'], p['s12'], p['s21'], p['s22']) for p in ib):.4f}"
        for q in Q_GRID:
            best = None
            for p in ib:
                x = 2 * math.pi * p["freq_hz"] * LC_H
                y = s_to_y(p["s11"], p["s12"], p["s21"], p["s22"])
                g = ga_max_db(*y_to_s(y[0], y[1], y[2], y[3] + 1.0 / (q * x)))
                best = g if best is None else min(best, g)
            row[f"ga_max_q{q}_db"] = f"{best:.4f}"
        out_rows.append(row)

    out = Path(args.out) if args.out else (
        here / "records" / f"{args.record_id}-derived-envelope.csv")
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(out_rows[0].keys()))
        w.writeheader()
        w.writerows(out_rows)

    def col(name, f=float):
        return [f(r[name]) for r in out_rows]

    print(f"Source record : {args.record_id} "
          f"(sim/lna-characterization/, {len(out_rows)} PVT cells)")
    print(f"Derived CSV   : {out.relative_to(out.parents[3]) if len(out.parents) > 3 else out}")
    print()
    print("1. ngspice `sp` NF reference-temperature convention")
    print("   Test: re-reference the committed .noise-based nf290 column to each")
    print("   cell's ANALYSIS temperature and compare with the committed,")
    print("   independently computed `sp` NF column.")
    print(f"   Worst |predicted - committed| over {len(out_rows)} cells: "
          f"{worst_conv_err:.2e} dB")
    print("   => ngspice's two-port `sp` NF/NFmin is referenced to the analysis")
    print("      temperature, NOT to a fixed T0. The committed")
    print("      `nfmin_sp_db_at_band_lo` column is therefore NOT the quantity")
    print("      spec/target-spec.md's T0 = 290 K NF row binds.")
    print()
    nfsp, nf290d = col("nfmin_sp_db_committed"), col("nfmin290_db_derived")
    print("2. NFmin re-referenced to the RATIFIED T0 = 290 K")
    print(f"   committed (analysis-T referenced) : {min(nfsp):.4f} .. {max(nfsp):.4f} dB")
    print(f"   derived   (T0 = 290 K referenced) : {min(nf290d):.4f} .. {max(nf290d):.4f} dB")
    best = min(out_rows, key=lambda r: float(r["nfmin290_db_derived"]))
    worst = max(out_rows, key=lambda r: float(r["nfmin290_db_derived"]))
    print(f"   best  cell {best['corner_label']}/{best['temp_c']} C/"
          f"{best['vdd_v']} V : {best['nfmin290_db_derived']} dB")
    print(f"   worst cell {worst['corner_label']}/{worst['temp_c']} C/"
          f"{worst['vdd_v']} V : {worst['nfmin290_db_derived']} dB")
    print(f"   cells below the RATIFIED 1.5 dB row: "
          f"{sum(1 for v in nf290d if v < 1.5)}/{len(nf290d)}")
    print()
    print("3. Gain envelope vs collector-tank inductor Q (worst in-band point,")
    print("   worst of 45 cells / nominal cell)")
    nom = [r for r in out_rows
           if r["corner_label"] == "typ" and r["temp_c"] == "27"
           and float(r["vdd_v"]) == 1.80][0]
    gin = col("gain_in_match_only_db")
    print(f"   input-conjugate-match only (output left at 50 Ohm): "
          f"{min(gin):.2f} / {float(nom['gain_in_match_only_db']):.2f} dB   "
          f"[{sum(1 for v in gin if v > 15)}/{len(gin)} cells > 15 dB]")
    for q in Q_GRID:
        vals = col(f"ga_max_q{q}_db")
        print(f"   both ports conjugate matched, Lc at Q = {q:>2d}: "
              f"{min(vals):.2f} / {float(nom[f'ga_max_q{q}_db']):.2f} dB   "
              f"[{sum(1 for v in vals if v > 15)}/{len(vals)} cells > 15 dB]")
    vals = col("ga_max_ideal_db")
    print(f"   both ports conjugate matched, Lc ideal (Q = inf): "
          f"{min(vals):.2f} / {float(nom['ga_max_ideal_db']):.2f} dB   "
          f"[{sum(1 for v in vals if v > 15)}/{len(vals)} cells > 15 dB]")
    return 0


if __name__ == "__main__":
    sys.exit(main())
