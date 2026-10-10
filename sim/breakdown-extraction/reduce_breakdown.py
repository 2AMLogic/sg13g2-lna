#!/usr/bin/env python3
"""Breakdown summary reduction (issue #145). Stdlib only; no PDK/ngspice/klt.

Reduces the two retained raw CSVs of a breakdown-extraction record
(Bench A forced-current locus, Bench B held-base V_CE sweep) to the two
summary CSVs. run_breakdown_sweep.sh imports this module, and the PDK-free
replay (tests/check_breakdown_replay.py) calls the same code, so the
production reduction and its test cannot drift.

CLI (explicit paths only; nothing is inferred from timestamps):
  python3 -I reduce_breakdown.py --locus L.csv --sweep S.csv \
      --out-locus-summary A.csv --out-sweep-summary B.csv
Exit 0 ok, 2 malformed/missing input (diagnostic on stderr).
"""
import argparse
import csv
import math
import sys
from collections import defaultdict

# Bench A extraction criteria, in A PER FINGER (Nx-invariant by
# construction -- the forced-current grid is scaled by Nx in the
# template). 5e-4 A/finger is DR-0001's nominal operating current
# (I_C = 4.0 mA at Nx = 8).
A_CRITERIA = [("1ua", 1e-6), ("10ua", 1e-5), ("100ua", 1e-4), ("500ua", 5e-4)]
# Bench B: leakage read-out voltages, and the current criteria at which a
# held-base breakdown voltage would be declared (per finger).
B_READOUT_V = [("1p12", 1.12), ("1p40", 1.40), ("1p60", 1.60), ("2p00", 2.00)]
B_CRITERIA = [("1ua", 1e-6), ("10ua", 1e-5)]

META = ["point_id", "role", "corner_label", "hbt_section", "temp_c", "nx",
        "selft", "rb_label", "rb_ohm"]
REQ_A = META + ["ic_per_nx_a", "vce_v"]
REQ_B = META + ["ic_per_nx_a", "vce_v"]

FIELDS_A = META + ["n_points", "n_converged"] + \
    [f"vce_at_{n}_per_nx_v" for n, _ in A_CRITERIA] + \
    ["locus_min_vce_v", "locus_min_at_ic_per_nx_a", "locus_has_foldback"]
FIELDS_B = META + ["n_points", "v_last_v", "ic_per_nx_max_a", "ic_monotone_in_vce"] + \
    [f"vce_at_{n}_per_nx_v" for n, _ in B_CRITERIA] + \
    [f"ic_per_nx_at_{n}v_a" for n, _ in B_READOUT_V]


class ReductionError(Exception):
    """Malformed or missing input."""


def interp_x_at_y(pts, target):
    """Linear-in-log(y) interpolation of x at a target y, over an
    ascending-in-y run of (y, x) pairs."""
    prev = None
    for y, x in pts:
        if prev is not None and prev[0] <= target <= y:
            if y == prev[0]:
                return x
            f = (math.log(target) - math.log(prev[0])) / (math.log(y) - math.log(prev[0]))
            return prev[1] + f * (x - prev[1])
        prev = (y, x)
    return None


def _num(r, col, path, lineno, allow_empty=False):
    raw = r[col]
    if allow_empty and raw in ("", None):
        return None
    try:
        v = float(raw)
    except (TypeError, ValueError):
        raise ReductionError(f"{path}: line {lineno}: column {col!r} is not numeric: {raw!r}")
    if not math.isfinite(v):
        raise ReductionError(f"{path}: line {lineno}: column {col!r} is not finite: {raw!r}")
    return v


def read_rows(path, required):
    """Read a raw CSV, validating header, row shape and non-emptiness."""
    try:
        f = open(path, newline="")
    except OSError as e:
        raise ReductionError(f"cannot read input {path}: {e.strerror}")
    with f:
        rd = csv.DictReader(f)
        if rd.fieldnames is None:
            raise ReductionError(f"{path}: empty file (no header)")
        missing = [c for c in required if c not in rd.fieldnames]
        if missing:
            raise ReductionError(f"{path}: missing required column(s): {', '.join(missing)}")
        rows = []
        for r in rd:
            if None in r or any(v is None for v in r.values()):
                raise ReductionError(f"{path}: line {rd.line_num}: row has wrong field count")
            r["_line"] = rd.line_num
            rows.append(r)
    if not rows:
        raise ReductionError(f"{path}: no data rows")
    return rows


def _meta_row(pid, pts):
    meta = pts[0]
    row = {k: meta[k] for k in META}
    return meta, row


def reduce_bench_a(path):
    rows = read_rows(path, REQ_A)
    groups = defaultdict(list)
    for r in rows:
        groups[r["point_id"]].append(r)
    out = []
    for pid, pts in groups.items():
        meta, row = _meta_row(pid, pts)
        for k in ("temp_c", "nx"):
            if not meta[k].lstrip("-").isdigit():
                raise ReductionError(f"{path}: line {meta['_line']}: column {k!r} is not an integer: {meta[k]!r}")
        good = []
        for p in pts:
            v = _num(p, "vce_v", path, p["_line"], allow_empty=True)
            i = _num(p, "ic_per_nx_a", path, p["_line"], allow_empty=v is None)
            if v is not None:
                good.append((i, v))
        good.sort()
        row["n_points"] = len(pts)
        row["n_converged"] = len(good)
        for name, target in A_CRITERIA:
            v = interp_x_at_y(good, target)
            row[f"vce_at_{name}_per_nx_v"] = f"{v:.4f}" if v is not None else ""
        if good:
            imin, vmin = min(good, key=lambda t: t[1])
            row["locus_min_vce_v"] = f"{vmin:.4f}"
            row["locus_min_at_ic_per_nx_a"] = f"{imin:.4e}"
            # A fold-back (snapback) exists only if the locus minimum is
            # interior to the swept current range; a monotonically rising
            # locus means the low-current end never needed an
            # avalanche-sustained branch (leakage carries it instead), so no
            # sustaining voltage is defined there.
            row["locus_has_foldback"] = "yes" if good[0][0] < imin < good[-1][0] else "no"
        else:
            row["locus_min_vce_v"] = ""
            row["locus_min_at_ic_per_nx_a"] = ""
            row["locus_has_foldback"] = ""
        out.append(row)
    out.sort(key=lambda r: (r["role"], r["rb_label"], r["nx"], r["corner_label"],
                            int(r["temp_c"]), r["selft"]))
    return out


def reduce_bench_b(path):
    rows = read_rows(path, REQ_B)
    groups = defaultdict(list)
    for r in rows:
        groups[r["point_id"]].append(r)
    out = []
    for pid, pts in groups.items():
        meta, row = _meta_row(pid, pts)
        if not meta["temp_c"].lstrip("-").isdigit():
            raise ReductionError(f"{path}: line {meta['_line']}: column 'temp_c' is not an integer: {meta['temp_c']!r}")
        seq = sorted((_num(p, "vce_v", path, p["_line"]),
                      _num(p, "ic_per_nx_a", path, p["_line"])) for p in pts)
        row["n_points"] = len(seq)
        row["v_last_v"] = f"{seq[-1][0]:.2f}"
        row["ic_per_nx_max_a"] = f"{max(i for _, i in seq):.4e}"
        # Monotone in I_C over the swept range? (The property that makes a
        # voltage-driven sweep sound for this cell.)
        mono = all(seq[k][1] >= seq[k - 1][1] * (1 - 1e-9) for k in range(1, len(seq)))
        row["ic_monotone_in_vce"] = "yes" if mono else "no"
        # V_CE at which I_C/finger first crosses each criterion (interpolated).
        iv = [(i, v) for v, i in seq]
        for name, target in B_CRITERIA:
            crossed = [k for k in range(len(seq)) if seq[k][1] >= target]
            if crossed:
                k = crossed[0]
                if k == 0:
                    v = seq[0][0]
                else:
                    v = interp_x_at_y([iv[k - 1], iv[k]], target)
                    v = v if v is not None else seq[k][0]
                row[f"vce_at_{name}_per_nx_v"] = f"{v:.4f}"
            else:
                row[f"vce_at_{name}_per_nx_v"] = ""
        for name, target in B_READOUT_V:
            hit = [i for v, i in seq if abs(v - target) < 1e-9]
            row[f"ic_per_nx_at_{name}v_a"] = f"{hit[0]:.4e}" if hit else ""
        out.append(row)
    out.sort(key=lambda r: (r["role"], r["rb_label"], r["nx"], r["corner_label"], int(r["temp_c"])))
    return out


def write_csv(path, fields, rows):
    # newline="\n", not "": csv's default dialect terminates rows with CRLF,
    # which would make this committed append-only record differ byte-for-byte
    # from every other CSV in sim/ (all LF) and from its own re-run under git's
    # text normalisation. csv.DictWriter's own default lineterminator is
    # "\r\n" and open(newline="\n") does not translate it, so the
    # terminator is set explicitly too (the pre-extraction inline code only
    # set newline and so emitted CRLF; the committed records are LF).
    with open(path, "w", newline="\n") as f:
        w = csv.DictWriter(f, fieldnames=fields, lineterminator="\n")
        w.writeheader()
        w.writerows(rows)


def reduce_files(locus_csv, locus_summary, sweep_csv, sweep_summary):
    """Reduce both raw CSVs; write both summaries only if both reduce."""
    out_a = reduce_bench_a(locus_csv)
    out_b = reduce_bench_b(sweep_csv)
    write_csv(locus_summary, FIELDS_A, out_a)
    write_csv(sweep_summary, FIELDS_B, out_b)
    return out_a, out_b


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--locus", required=True, help="Bench A locus CSV (input)")
    ap.add_argument("--sweep", required=True, help="Bench B held-base sweep CSV (input)")
    ap.add_argument("--out-locus-summary", required=True, help="scratch output path")
    ap.add_argument("--out-sweep-summary", required=True, help="scratch output path")
    a = ap.parse_args(argv)
    try:
        out_a, out_b = reduce_files(a.locus, a.out_locus_summary, a.sweep, a.out_sweep_summary)
    except ReductionError as e:
        print(f"reduce_breakdown: error: {e}", file=sys.stderr)
        return 2
    print(f"wrote {len(out_a)} Bench A summary rows -> {a.out_locus_summary}")
    print(f"wrote {len(out_b)} Bench B summary rows -> {a.out_sweep_summary}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
