"""Shared RF arithmetic for the core-envelope postprocessors (issue #94).

Plain experiment-local module: the in-band wrdata schema, the table decoder,
NF re-referencing, the S<->Y conversions (50 Ohm port convention) and the
available-gain / finite-Q-tank gain arithmetic used by BOTH
parse_core_envelope.py and derive_committed_record_envelope.py. It reads no
source analysis itself: each caller feeds it its own data, so the derivation's
`.noise`-vs-`sp` comparison still compares two independently generated columns.
"""

from __future__ import annotations

import math
from pathlib import Path

LC_H = 5e-9  # the committed collector inductor

# wrdata writes one "freq, value(s)" group per vector. The in-band deck
# writes: s_1_1 s_2_1 s_1_2 s_2_2 kfac mufac mag(dlt) NF NFmin -- complex
# vectors as (re, im) pairs, real vectors as a single column, and NF/NFmin
# come back as complex-typed vectors with a zero imaginary part.
INBAND_COLS = [
    ("f", 1), ("s11", 2), ("f", 1), ("s21", 2), ("f", 1), ("s12", 2),
    ("f", 1), ("s22", 2), ("f", 1), ("k", 1), ("f", 1), ("mu", 1),
    ("f", 1), ("mag_delta", 1), ("f", 1), ("nf", 2), ("f", 1), ("nfmin", 2),
]


class TableError(ValueError):
    """The wrdata table violates its numeric contract (invalid evidence).

    Distinct from a valid measurement that fails a target: callers treat this
    as "the point is not complete evidence", never as a spec failure.
    """


def parse_table(path: Path, spec=INBAND_COLS, expected_points=None):
    """Decode a wrdata table, validating it before any arithmetic.

    Requires: the exact schema width per row, finite values (NaN/inf/overflow
    rejected), identical repeated frequency scales within a row, and positive
    strictly increasing frequencies down the table. `expected_points`, when a
    caller knows the declared grid size, must equal the received row count;
    None (historical replay, reduced fixtures) imposes no count.
    """
    width_total = sum(w for _, w in spec)
    rows = []
    prev_f = None
    for lineno, line in enumerate(Path(path).read_text().splitlines(), 1):
        line = line.strip()
        if not line:
            continue
        where = f"{Path(path).name}:{lineno}"
        toks = line.split()
        try:
            vals = [float(x) for x in toks]
        except ValueError as exc:
            raise TableError(f"{where}: non-numeric field ({exc})") from None
        if len(vals) != width_total:
            raise TableError(
                f"{where}: {len(vals)} columns, schema requires {width_total}")
        bad = [i for i, v in enumerate(vals) if not math.isfinite(v)]
        if bad:
            raise TableError(
                f"{where}: non-finite value ({toks[bad[0]]}) in column {bad[0]}")
        rec, i, f_row = {}, 0, None
        for name, width in spec:
            chunk = vals[i:i + width]
            i += width
            if name == "f":
                if f_row is not None and chunk[0] != f_row:
                    raise TableError(
                        f"{where}: inconsistent repeated frequency scale "
                        f"({chunk[0]!r} != {f_row!r})")
                f_row = chunk[0]
                rec["freq_hz"] = chunk[0]
            elif width == 2:
                rec[name] = complex(chunk[0], chunk[1])
            else:
                rec[name] = chunk[0]
        if f_row is not None:
            if f_row <= 0:
                raise TableError(f"{where}: non-positive frequency {f_row!r}")
            if prev_f is not None and f_row <= prev_f:
                raise TableError(
                    f"{where}: frequency {f_row!r} not strictly increasing "
                    f"(previous {prev_f!r})")
            prev_f = f_row
        rows.append(rec)
    if expected_points is not None and len(rows) != expected_points:
        raise TableError(
            f"{Path(path).name}: {len(rows)} points, declared grid has "
            f"{expected_points}")
    return rows


GRID_RTOL = 1e-6  # wrdata prints 9 significant digits


def parse_grid_arg(text: str):
    """Parse a declared-grid CLI value "LO,HI,N" into (lo, hi, n)."""
    parts = text.split(",")
    if len(parts) != 3:
        raise ValueError(f"declared grid {text!r} must be LO,HI,N")
    lo, hi, n = float(parts[0]), float(parts[1]), int(parts[2])
    if not (math.isfinite(lo) and math.isfinite(hi) and 0 < lo < hi and n >= 1):
        raise ValueError(f"declared grid {text!r} needs 0 < LO < HI and N >= 1")
    return lo, hi, n


def _close(a: float, b: float, rtol: float) -> bool:
    return abs(a - b) <= rtol * max(abs(a), abs(b))


def check_declared_grid(rows, name: str, sweep: str, lo: float, hi: float,
                        n: int, rtol: float = GRID_RTOL):
    """Check received rows against the campaign's declared sweep grid.

    sweep="lin" (`sp lin N LO HI`): exactly N points, first == LO, last == HI,
    and every point i on LO + i*(HI-LO)/(N-1).
    sweep="dec" (`sp dec N LO HI`): first == LO, at least
    floor(N*log10(HI/LO)) + 1 points (one spare allowed for ngspice's endpoint
    rounding), every point i on LO * 10**(i/N), and the last point within one
    decade-step below HI, never above it. ngspice's `dec` sweep does not land
    exactly on HI (it stops at the last grid point not above HI), so the end
    is checked by bracket, not equality with HI.

    Every received frequency is compared with its expected grid position
    within `rtol` (wrdata's printed precision), so an off-grid sample standing
    in for a missing grid sample is rejected even when count and endpoints
    agree.

    Raises TableError; the caller treats the point as invalid evidence.
    """
    if not rows:
        raise TableError(f"{name}: no points, declared grid {lo!r}..{hi!r}")
    f0, f1, cnt = rows[0]["freq_hz"], rows[-1]["freq_hz"], len(rows)
    if not _close(f0, lo, rtol):
        raise TableError(
            f"{name}: first frequency {f0!r} != declared start {lo!r}")
    if sweep == "lin":
        if cnt != n:
            raise TableError(
                f"{name}: {cnt} points, declared grid has {n} (lin)")
        if not _close(f1, hi, rtol):
            raise TableError(
                f"{name}: last frequency {f1!r} != declared stop {hi!r}")
    elif sweep == "dec":
        n_min = math.floor(n * math.log10(hi / lo) + 1e-9) + 1
        if not (n_min <= cnt <= n_min + 1):
            raise TableError(
                f"{name}: {cnt} points, declared grid dec {n} over "
                f"{lo!r}..{hi!r} requires {n_min}")
        floor_f = hi / 10 ** (1.0 / n)
        if not (floor_f * (1 - rtol) <= f1 <= hi * (1 + rtol)):
            raise TableError(
                f"{name}: last frequency {f1!r} outside the declared stop "
                f"step [{floor_f!r}, {hi!r}]")
    else:
        raise ValueError(f"unknown sweep type {sweep!r}")
    for i, row in enumerate(rows):
        if sweep == "lin":
            want = lo + i * (hi - lo) / (n - 1) if n > 1 else lo
        else:
            want = lo * 10 ** (i / n)
        got = row["freq_hz"]
        if not _close(got, want, rtol):
            raise TableError(
                f"{name}: point {i} frequency {got!r} off the declared {sweep} "
                f"{n} grid over {lo!r}..{hi!r} (expected {want!r})")
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
