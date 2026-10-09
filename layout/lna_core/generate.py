#!/usr/bin/env python3
"""Generate layout/lna_core/lna_core.gds -- the cascode core + DR-0003 bias
island of design/netlist/lna.spice (issue #63, layout/toolchain bring-up).

    layout/tools/fetch-pcell-deps.sh                 # once per checkout
    python3 layout/lna_core/generate.py              # nx=8 (the netlist's Nx)
    python3 layout/lna_core/generate.py --nx 10      # issue #58's knob

Requires the pip ``klayout`` package (``import pya``); the committed GDS was
written with klayout 0.30.12 (the version klt 0.7.0 itself runs).

What is drawn is set by ``realization.json`` (scope + PDK realization of
every in-scope netlist instance); every device is the PDK's OWN PyCell from
``SG13_dev`` (see ``layout/pcell_env.py``) -- nothing device-level is hand
drawn. What this script draws by hand is only the interconnect: Metal1 /
Metal2 / TopMetal1 wiring, a GatPoly bus tying XMis's 32 gate fingers, one
substrate-tap rail, one n-well tap, the shared Metal5 bottom plate of the
Cbref bank, and net labels on the ``<metal>.text`` layers klt's sg13g2
extraction deck reads for net names.

Floorplan (um, global coordinates; XR = 1.85*(nx-1), the HBT stripe span):

* Q1 at (0, 0), Q2 at (0, 12) -- the cascode stack. Q1's collector bar and
  Q2's emitter Metal2 join on a Metal2 riser right of the pair (``casc``).
* Q3 at (-25, 0) -- diode-tied (base + collector bars joined on Metal1 on
  its right, net ``bref``); emitter Metal2 to the ``vss`` rail.
* R3b rotated 90 deg on the y=-1.14 line between Q3 and Q1: ``bref`` enters
  its left pad, ``b1`` (Q1's base bar, extended left) its right pad.
* XMis at (-70, 10): drains bussed on Metal1 below the device into the
  ``bref`` riser, sources + n-well tap bussed above (``vdd``), gate bus on
  GatPoly below the device, contacted at its right end (``gsvo``).
* ``vss`` Metal1 rail at y=-8 over a ptap1 substrate-tap strip.
* Cbref: a 4x4 cmim bank below the core, Metal5 bottom plates merged into
  one ``vss`` plate (via stack to the rail), TopMetal1 top plates strapped
  into one ``bref`` grid (via stack down to Metal1, joined to Q3's riser).

Ports (labels only -- this cell has no pin shapes): vdd, vss, b1, e1, outn,
vb2, gsvo. b1/e1/outn/vb2 connect to out-of-scope devices (realization.json).
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

from pcell_env import load_sg13_dev, pcell_lib_digest  # noqa: E402

# GDS layer numbers, from ihp-sg13g2/libs.tech/klayout/tech/sg13g2.lyp.
ACTIV = (1, 0)
GATPOLY = (5, 0)
CONT = (6, 0)
METAL1 = (8, 0)
METAL1_TEXT = (8, 25)
METAL2 = (10, 0)
METAL2_TEXT = (10, 25)
NWELL = (31, 0)
METAL5 = (67, 0)
TOPMETAL1 = (126, 0)
TOPMETAL1_TEXT = (126, 25)

HBT_STEP_X = 1.85  # npn13G2 emitter pitch (npn13G2_code.py stepX)


def _snap(v: float) -> int:
    """um -> dbu (1 nm), rounded to the 5 nm manufacturing grid."""
    return int(round(v * 200.0)) * 5


class Canvas:
    def __init__(self, pya, top: str):
        self.pya = pya
        self.ly = pya.Layout()
        self.ly.dbu = 0.001
        self.top = self.ly.create_cell(top)
        self._layers: dict[tuple[int, int], int] = {}

    def layer(self, ld: tuple[int, int]) -> int:
        if ld not in self._layers:
            self._layers[ld] = self.ly.layer(ld[0], ld[1])
        return self._layers[ld]

    def box(self, ld, x0, y0, x1, y1) -> None:
        pya = self.pya
        self.top.shapes(self.layer(ld)).insert(
            pya.Box(_snap(min(x0, x1)), _snap(min(y0, y1)), _snap(max(x0, x1)), _snap(max(y0, y1)))
        )

    def label(self, ld, text, x, y) -> None:
        self.top.shapes(self.layer(ld)).insert(self.pya.Text(text, _snap(x), _snap(y)))

    def pcell(self, name: str, params: dict, x: float, y: float, rot: int = 0):
        """Place a SG13_dev PyCell; rot is a multiple of 90 degrees."""
        pya = self.pya
        cell = self.ly.create_cell(name, "SG13_dev", params)
        if cell is None:
            raise SystemExit(f"generate: SG13_dev has no PCell '{name}'")
        if cell.bbox().empty():
            raise SystemExit(f"generate: PCell {name} {params} produced no geometry")
        trans = pya.Trans(rot // 90, False, _snap(x), _snap(y))
        self.top.insert(pya.CellInstArray(cell.cell_index(), trans))
        return cell


def via_stack(cv: Canvas, x, y, top: str, cols=1, rows=1, tcols=1, trows=1):
    """PDK via_stack PyCell from Metal1 up to ``top``, centred on (x, y)."""
    params = {"b_layer": "Metal1", "t_layer": top, "vn_columns": cols, "vn_rows": rows}
    if top == "TopMetal1":
        params.update({"vt1_columns": tcols, "vt1_rows": trows})
    return cv.pcell("via_stack", params, x, y)


def draw(pya, nx: int, realization: dict) -> Canvas:
    rz = realization["in_scope"]
    cv = Canvas(pya, realization["top_cell"])
    xr = HBT_STEP_X * (nx - 1)

    # ------------------------------------------------------------------ HBTs
    def hbt_params(inst: str) -> dict:
        p = dict(rz[inst]["params"])
        p["Nx"] = nx if p["Nx"] == "@nx" else int(p["Nx"])
        return p

    q1, q2, q3 = hbt_params("XQ1"), hbt_params("XQ2"), hbt_params("XQ3")
    if q3["Nx"] != 1:
        raise SystemExit("generate: Q3 geometry below assumes Nx=1")
    cv.pcell("npn13G2", q1, 0.0, 0.0)
    cv.pcell("npn13G2", q2, 0.0, 12.0)
    cv.pcell("npn13G2", q3, -25.0, 0.0)
    # npn13G2 terminal geometry (PyCell-relative, read from the drawn cell):
    #   base bar     Metal1 y[-1.26,-1.02], x[-0.975, XR+0.975]
    #   collector    Metal1 y[ 1.02, 1.46], x[-0.925, XR+0.925]
    #   emitter      Metal2 y[-0.785,0.77], x[-0.925, XR+0.925]

    # Q1: b1 (base bar extended left to R3b), e1 (emitter Metal2 stub left),
    # casc (collector bar extended right to the Metal2 riser).
    cv.box(METAL1, -11.80, -1.26, -0.90, -1.02)
    cv.label(METAL1_TEXT, "b1", -6.0, -1.14)
    cv.box(METAL2, -6.0, -0.40, -0.80, 0.40)
    cv.label(METAL2_TEXT, "e1", -5.5, 0.0)
    cv.box(METAL1, xr + 0.80, 1.02, xr + 4.00, 1.46)
    via_stack(cv, xr + 3.60, 1.24, "Metal2")
    cv.box(METAL2, xr + 3.35, 1.00, xr + 3.85, 12.40)
    cv.label(METAL2_TEXT, "casc", xr + 3.60, 6.0)

    # Q2 (at y=12): casc (emitter Metal2 extended right onto the riser),
    # outn (collector bar right), vb2 (base bar left).
    cv.box(METAL2, xr + 0.80, 11.60, xr + 3.85, 12.40)
    cv.box(METAL1, xr + 0.80, 13.02, xr + 7.00, 13.46)
    cv.label(METAL1_TEXT, "outn", xr + 6.50, 13.24)
    cv.box(METAL1, -6.0, 10.74, -0.90, 10.98)
    cv.label(METAL1_TEXT, "vb2", -5.5, 10.86)

    # Q3 (at x=-25): diode tie on its right (bref riser x[-23.4,-23.0]),
    # emitter to vss.
    cv.box(METAL1, -24.20, -1.26, -23.00, -1.02)
    cv.box(METAL1, -24.20, 1.02, -23.00, 1.46)
    cv.box(METAL1, -23.40, -4.20, -23.00, 9.20)
    cv.label(METAL1_TEXT, "bref", -23.20, 4.0)
    cv.box(METAL2, -30.50, -0.40, -25.80, 0.40)
    cv.box(METAL2, -30.50, -8.50, -30.00, 0.40)
    via_stack(cv, -30.25, -8.0, "Metal2")

    # ------------------------------------------------------------------ R3b
    # rppd PyCell-relative: body x[0,1] y[0,l]; end pads Metal1 at
    # y[-0.43,-0.13] and y[l+0.13,l+0.43]. Rotated 90 deg and displaced to
    # (-12, -1.64), its pads land at x[-11.87,-11.57] (b1) and
    # x[-13.435,-13.135] (bref), both y[-1.62,-0.66].
    cv.pcell("rppd", dict(rz["R3b"]["params"]), -12.0, -1.64, rot=90)
    cv.box(METAL1, -23.40, -1.26, -13.20, -1.02)  # bref -> R3b left pad

    # ------------------------------------------------------------------ vss rail
    rail_x0, rail_x1 = -60.0, xr + 10.0
    cv.pcell("ptap1", {"w": f"{rail_x1 - rail_x0 - 2.0:.3f}u", "l": "0.78u"}, rail_x0 + 1.0, -8.39)
    cv.box(METAL1, rail_x0, -8.50, rail_x1, -7.50)
    cv.label(METAL1_TEXT, "vss", rail_x0 + 5.0, -8.0)

    # ------------------------------------------------------------------ XMis
    mx, my = -70.0, 10.0  # PyCell origin = Activ lower-left
    mp = dict(rz["XMis"]["params"])
    ng = int(mp["ng"])
    cv.pcell("pmosHV", mp, mx, my)
    # pmosHV PyCell-relative (w=512u l=1u ng=32): Activ x[0,44.46] y[0,16];
    # S/D Metal1 strips x[0.07+1.38k, 0.23+1.38k], k=0..ng, y[0,16]
    # (even k = source, odd k = drain); gate fingers GatPoly
    # x[0.34+1.38k, 1.34+1.38k], y[-0.18,16.18].
    pitch = 1.38
    act_w = 0.0 + pitch * ng + 0.3  # = 44.46 for ng=32
    for k in range(ng + 1):
        sx0, sx1 = mx + 0.07 + pitch * k, mx + 0.23 + pitch * k
        if k % 2:  # drain -> bus below
            cv.box(METAL1, sx0, my - 1.20, sx1, my + 0.05)
        else:  # source -> bus above
            cv.box(METAL1, sx0, my + 15.95, sx1, my + 17.0)
    # drain bus (bref), extended right onto Q3's bref riser at x=-23.
    cv.box(METAL1, mx + 1.45, my - 1.20, -23.00, my - 0.80)
    # gate bus: GatPoly under the finger ends, contacted at its right end.
    cv.box(GATPOLY, mx + 0.34, my - 0.60, mx + act_w + 1.55, my - 0.10)
    gx = mx + act_w + 1.02
    cv.box(CONT, gx - 0.08, my - 0.47, gx + 0.08, my - 0.31)
    cv.box(METAL1, gx - 0.18, my - 0.52, gx + 0.18, my - 0.26)
    via_stack(cv, gx, my - 0.39, "Metal2")
    cv.box(METAL2, gx - 0.15, my - 0.55, gx + 4.0, my - 0.23)
    cv.label(METAL2_TEXT, "gsvo", gx + 3.5, my - 0.39)
    # n-well tap above the sources, inside one NWell with the device.
    cv.pcell("ntap1", {"w": f"{act_w:.2f}u", "l": "0.78u"}, mx, my + 18.0)
    cv.box(NWELL, mx - 0.62, my - 0.62, mx + act_w + 0.62, my + 19.20)
    cv.box(METAL1, mx + 0.07, my + 16.80, mx + act_w - 0.07, my + 18.69)  # vdd bus
    cv.label(METAL1_TEXT, "vdd", mx + 2.0, my + 17.2)

    # ------------------------------------------------------------------ Cbref
    cp = dict(rz["Cbref"]["params"])
    side = float(cp["w"].rstrip("u"))
    count = int(rz["Cbref"]["count"])
    ncol = 4
    nrow = count // ncol
    if ncol * nrow != count:
        raise SystemExit("generate: Cbref bank assumes a 4-column grid")
    cpitch = side + 2.0
    bx0, by_top = -140.0, -14.0
    centers = []
    for j in range(nrow):
        for i in range(ncol):
            x = bx0 + cpitch * i
            y = by_top - side - cpitch * j
            cv.pcell("cmim", cp, x, y)
            centers.append((x + side / 2, y + side / 2))
    bx1 = bx0 + cpitch * (ncol - 1) + side
    by_bot = by_top - side - cpitch * (nrow - 1)
    # Bottom plates: one merged Metal5 sheet (>= 0.6 um MIM enclosure), tied
    # to the vss rail through a Metal1->Metal5 via stack.
    cv.box(METAL5, bx0 - 0.6, by_bot - 0.6, bx1 + 0.6, by_top + 0.6)
    via_stack(cv, -50.0, -8.0, "Metal5", cols=2, rows=2)
    cv.box(METAL5, -50.5, by_top + 0.6, -49.5, -7.6)
    # Top plates: TopMetal1 straps along each row and down the first column.
    strap = 4.0
    for j in range(nrow):
        yc = centers[j * ncol][1]
        cv.box(TOPMETAL1, centers[j * ncol][0], yc - strap / 2, centers[j * ncol + ncol - 1][0], yc + strap / 2)
    xc0 = centers[0][0]
    cv.box(TOPMETAL1, xc0 - strap / 2, centers[-ncol][1], xc0 + strap / 2, -4.0)
    via_stack(cv, xc0, -4.0, "TopMetal1", cols=2, rows=2, tcols=2, trows=2)
    cv.label(TOPMETAL1_TEXT, "bref", xc0, -20.0)
    # bref Metal1 from the via stack to Q3's riser (riser spans y>=-4.2).
    cv.box(METAL1, xc0 - 0.5, -4.20, -23.00, -3.80)

    return cv


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--nx", type=int, default=None, help="npn13G2 Nx of Q1/Q2 (default: realization.json)")
    ap.add_argument("-o", "--output", type=Path, default=HERE / "lna_core.gds")
    args = ap.parse_args(argv)

    realization = json.loads((HERE / "realization.json").read_text())
    nx = args.nx if args.nx is not None else int(realization["parameters"]["nx"]["default"])
    if nx < 1:
        ap.error("--nx must be >= 1")

    pya, _lib, pdk_dir = load_sg13_dev()
    cv = draw(pya, nx, realization)

    opt = pya.SaveLayoutOptions()
    opt.format = "GDS2"
    opt.gds2_write_timestamps = False
    opt.write_context_info = False
    cv.ly.write(str(args.output), opt)

    gds_sha = hashlib.sha256(args.output.read_bytes()).hexdigest()
    prov = {
        "_comment": "Written by layout/lna_core/generate.py alongside the GDS; regenerate both together.",
        "gds": args.output.name,
        "gds_sha256": gds_sha,
        "top_cell": realization["top_cell"],
        "nx": nx,
        "klayout_python": importlib.metadata.version("klayout"),
        "pdk_variant": pdk_dir.name,
        "pdk_fetched_version": (pdk_dir / ".fetched-version").read_text().strip()
        if (pdk_dir / ".fetched-version").is_file()
        else None,
        "pcell_lib_sha256": pcell_lib_digest(pdk_dir),
        "pcell_deps": {
            "pypreprocessor": "IHP-GmbH/pypreprocessor@cf1ff9bad0fb5338cf1c5b990b2b816b1ea01a64",
            "pycell4klayout-api": "IHP-GmbH/pycell4klayout-api@4c463c43991fb0967a824906518b66047bfb33c4",
        },
        "bbox_um": [round(v, 3) for v in (lambda b: (b.left, b.bottom, b.right, b.top))(cv.top.dbbox())],
    }
    (args.output.parent / (args.output.stem + ".provenance.json")).write_text(json.dumps(prov, indent=2) + "\n")
    print(f"generate: wrote {args.output} (nx={nx}, sha256 {gds_sha})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
