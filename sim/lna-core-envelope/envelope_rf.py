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


def parse_table(path: Path, spec=INBAND_COLS):
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
