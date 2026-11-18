#!/usr/bin/env python3
"""Report drawn inductance vs netlist value for every inductor in a cell.

    python3 layout/inductance_report.py layout/lna_core

Writes ``<cell-dir>/inductance_report.json`` (issue #347). For each
``inductor2`` instance in ``realization.json`` it

* reads the drawn GDS back and checks the PyCell's own parameter label
  (``width= space= diameter= turns=``, written by the inductor2 PyCell for
  LVS extraction) against the realization's geometry;
* evaluates the inductance of that geometry with ``l_lowfreq`` below, a
  transcription of ``em_ltot`` (``kem_l * ind_lmw``) in
  ``sim/models/sg13g2_inductor_em.spice``;
* reports it against the netlist value.

**Method and its limits (stated in the report too).** ``l_lowfreq`` is the
low-frequency series inductance of the *vendored analytic-plus-EM-correction
model*, not a field solve of the drawn GDS: it is evaluated from the drawn
w/s/d/turns, so it says the drawing matches the model's geometry, not that
silicon would. The EM correction (``kem_l``) is a fit at three extracted
geometries (1, 4, 5 turns; sim/models/SOURCE.md); a geometry not on one of
them is an unvalidated interpolation and is flagged ``em_verified: false``.
klt ``mom`` is not used: it is a static capacitance solve for the MOM/MIM
stack, not an inductance extractor, and the klt sg13g2 extraction deck has no
inductor device class (layout/README.md).
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

MU0 = 1.25663706212e-6
GRID = 0.01e-6

#: EM points the vendored model was fitted at: nr_r -> (w, s, d) in um
#: (sim/models/sg13g2_inductor_em.spice header, "Extracted").
EM_POINTS = {
    "p1": (1, 8.22, 3.29, 47.65),
    "p11": (4, 8.22, 3.74, 141.975),
    "p13": (5, 6.1, 3.29, 110.11),
}


def _um(v: str) -> float:
    v = v.strip().lower()
    if not v.endswith("u"):
        raise SystemExit(f"inductance_report: expected a 'u'-suffixed length, got {v!r}")
    return float(v[:-1])


def l_lowfreq(nr_r: int, w_um: float, s_um: float, d_um: float) -> float:
    """em_ltot of sg13g2_inductor_em.spice, henries."""
    kem_l = 0.94555 if nr_r <= 1 else (0.925549 if nr_r <= 4 else 0.93249)
    w, s, d, n = w_um * 1e-6, s_um * 1e-6, d_um * 1e-6, nr_r
    pitch = s + w + GRID
    dout = d + 2 * (n - 1) * pitch + 2 * w
    davg = (d + dout) / 2
    fill = (dout - d) / (dout + d)
    return kem_l * 2.25 * MU0 * n * n * davg / (1 + 3.55 * fill)


def _nearest_em_point(nr_r: int, w: float, s: float, d: float) -> dict:
    cands = [(k, v) for k, v in EM_POINTS.items() if v[0] == nr_r and v[1] == w and v[2] == s]
    on_grid = [k for k, v in cands if abs(v[3] - d) < 0.5]
    return {
        "same_turns_w_s_point": [k for k, _ in cands],
        "within_0p5um_of_extracted_d": on_grid,
    }


def _drawn_labels(gds: Path) -> list[dict]:
    import klayout.db as pya

    ly = pya.Layout()
    ly.read(str(gds))
    top = ly.top_cell()
    out = []
    for ci in [*top.called_cells(), top.cell_index()]:
        cell = ly.cell(ci)
        for li in ly.layer_indexes():
            for sh in cell.shapes(li).each():
                if sh.is_text() and "turns=" in sh.text.string:
                    m = dict(re.findall(r"(\w+)=([-\d.]+)", sh.text.string))
                    out.append({k: float(v) for k, v in m.items()})
    return out


def _netlist_values(text: str, names) -> dict:
    """Henries of each named card: token 3, lowercased, trailing ``n`` -> 1e-9, else float.

    Raises ValueError on an unparsable value (and IndexError on a card shorter
    than 4 tokens); the gate copy in .github/scripts/inductance_lowfreq.py skips
    those instead (pinned in TestGateCopy).
    """
    out = {}
    for line in text.splitlines():
        t = line.split()
        if t and t[0] in names:
            v = t[3].lower()
            out[t[0]] = float(v.rstrip("n")) * 1e-9 if v.endswith("n") else float(v)
    return out


def build(cell_dir: Path) -> Path:
    rz = json.loads((cell_dir / "realization.json").read_text())
    netlist = (Path(__file__).resolve().parent.parent / rz["netlist"]).read_text()
    inductors = {n for n, sp in rz["in_scope"].items() if sp["pcell"] == "inductor2"}
    nl_val = _netlist_values(netlist, inductors)
    drawn = _drawn_labels(cell_dir / f"{rz['top_cell']}.gds")
    rows = {}
    for inst, spec in rz["in_scope"].items():
        if spec["pcell"] != "inductor2":
            continue
        p = spec["params"]
        n, w, s, d = int(p["nr_r"]), _um(p["w"]), _um(p["s"]), _um(p["d"])
        match = [
            x for x in drawn
            if int(x["turns"]) == n and abs(x["width"] - w) < 0.05 and abs(x["space"] - s) < 0.05
            and abs(x["diameter"] - d) < 0.01
        ]
        if not match:
            raise SystemExit(f"inductance_report: {inst}: no drawn PyCell label matches w={w} s={s} d={d} turns={n}")
        lval = l_lowfreq(n, w, s, d)
        em = _nearest_em_point(n, w, s, d)
        rows[inst] = {
            "netlist_H": nl_val[inst],
            "drawn_lowfreq_H": lval,
            "drawn_over_netlist": round(lval / nl_val[inst], 5),
            "geometry_um": {"w": w, "s": s, "d": d, "turns": n},
            "drawn_cells_matching_label": len(match),
            "em_verified": bool(em["within_0p5um_of_extracted_d"]),
            "em_point_relation": em,
        }
    rep = {
        "_comment": "Written by layout/inductance_report.py; regenerate with layout/run_flow.sh.",
        "method": "low-frequency series L of sim/models/sg13g2_inductor_em.spice (em_ltot = kem_l * ind_lmw) evaluated at the drawn w/s/d/turns; geometry read back from the GDS PyCell label",
        "limits": [
            "A model evaluation at the drawn geometry, not an EM or static solve of the GDS; it is a low-frequency figure (self-resonance and Q are not in it).",
            "kem_l is fitted at three extracted geometries (1, 4, 5 turns); em_verified=false marks a geometry away from them: an unvalidated interpolation.",
            "klt mom is a capacitance solve and the sg13g2 extraction deck has no inductor class, so klt cannot check these devices (layout/README.md).",
        ],
        "inductors": rows,
    }
    out = cell_dir / "inductance_report.json"
    out.write_text(json.dumps(rep, indent=2) + "\n")
    return out


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(__doc__.split("\n\n")[0], file=sys.stderr)
        return 2
    print(f"inductance_report: wrote {build(Path(argv[1]).resolve())}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
