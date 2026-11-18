"""Gate-side copy of the low-frequency inductor model (issue #400).

``check-layout-freshness`` re-evaluates ``layout/inductance_report.py``'s
``l_lowfreq`` here instead of importing it: operator ruling (rjwalters,
2026-11-17, issue #359) — the gate executes only code from its own directory
and must not import from ``layout/``, the directory whose output it judges.

The two copies are kept equal by ``layout/tests/test_inductance_report.py``
(``TestGateCopy``), which may import across directories. Change them together.
Stdlib only; transcription of ``em_ltot`` (``kem_l * ind_lmw``) in
``sim/models/sg13g2_inductor_em.spice``.
"""

MU0 = 1.25663706212e-6
GRID = 0.01e-6


def l_lowfreq(nr_r: int, w_um: float, s_um: float, d_um: float) -> float:
    """em_ltot of sg13g2_inductor_em.spice, henries."""
    kem_l = 0.94555 if nr_r <= 1 else (0.925549 if nr_r <= 4 else 0.93249)
    w, s, d, n = w_um * 1e-6, s_um * 1e-6, d_um * 1e-6, nr_r
    pitch = s + w + GRID
    dout = d + 2 * (n - 1) * pitch + 2 * w
    davg = (d + dout) / 2
    fill = (dout - d) / (dout + d)
    return kem_l * 2.25 * MU0 * n * n * davg / (1 + 3.55 * fill)


def netlist_values(netlist_text: str, inductors) -> dict:
    """Henries of each named inductor2 card, parsed as build() does (issue #403).

    ``layout/inductance_report.py`` ``build()``: token 3 of the card, lowercased,
    trailing ``n`` -> 1e-9, else ``float``. Only names in ``inductors`` are read.
    A card whose value does not parse is omitted (the caller reports it).
    """
    out = {}
    for line in netlist_text.splitlines():
        t = line.split()
        if t and t[0] in inductors and len(t) > 3:
            v = t[3].lower()
            try:
                out[t[0]] = float(v.rstrip("n")) * 1e-9 if v.endswith("n") else float(v)
            except ValueError:
                pass
    return out
