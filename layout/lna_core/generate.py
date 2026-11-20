#!/usr/bin/env python3
"""Generate layout/lna_core/lna_core.gds -- the whole-block LNA layout of
design/netlist/lna.spice: cascode core + DR-0003 bias island (#63, #346),
matching network (#347) and the top-level assembly of pads and inter-block
routing (#228).

    layout/tools/fetch-pcell-deps.sh                 # once per checkout
    python3 layout/lna_core/generate.py              # nx=8 (the netlist's Nx)
    python3 layout/lna_core/generate.py --nx 10      # issue #58's knob

Requires the pip ``klayout`` package (``import pya``); the committed GDS was
written with klayout 0.30.12 (the version klt 0.9.2 itself runs).

What is drawn is set by ``realization.json`` (scope + PDK realization of
every in-scope netlist instance); every device is the PDK's OWN PyCell from
``SG13_dev`` (see ``layout/pcell_env.py``) -- nothing device-level is hand
drawn. What this script draws by hand is only the interconnect: Metal1 /
Metal2 / TopMetal1 wiring, a GatPoly bus tying XMis's 32 gate fingers, one
substrate-tap rail, one n-well tap, the shared Metal5 bottom plate of the
Cbref bank, net labels on the ``<metal>.text`` layers klt's sg13g2
extraction deck reads for net names, and (issue #228) the top-level
assembly: one TopMetal2 spine per terminal down to one TopMetal1 trunk per
net in the empty channel south of the blocks, and one PDK bondpad PyCell
per realization.json port.

Floorplan (um, global coordinates; XR = 1.85*(nx-1), the HBT stripe span):

* Q1 at (0, 0), Q2 at (0, 12) -- the cascode stack. Q1's collector bar and
  Q2's emitter Metal2 join on a Metal2 riser right of the pair (``casc``).
* Q3 at (-25, 0) -- diode-tied (base + collector bars joined on Metal1 on
  its right, net ``bref``); emitter Metal2 to the ``vss`` rail.
* R3b rotated 90 deg on the y=-1.14 line between Q3 and Q1: ``bref`` enters
  its left pad, ``b1`` (Q1's base bar, extended left) its right pad.
* Rbleed (issue #258's xout -> vss DC bleed): a 386.7 um rppd strip at
  x=-160.5 running south from the vss rail (Metal1 extended west over its
  upper pad) to an ``xout`` pad below the Cbref bank; the assembly lands on
  that pad to join Rbleed into the xout trunk.
* XMis at (-70, 10): drains bussed on Metal1 below the device into the
  ``bref`` riser, sources + n-well tap bussed above (``vdd``), gate bus on
  GatPoly below the device, contacted at its right end (``gsvo``).
* ``vss`` Metal1 rail at y=-8 over a ptap1 substrate-tap strip.
* Cbref: a 4x4 cmim bank below the core, Metal5 bottom plates merged into
  one ``vss`` plate (via stack to the rail), TopMetal1 top plates strapped
  into one ``bref`` grid (via stack down to Metal1, joined to Q3's riser).
* Matching network (#347, ``draw_matching``): Le / Lc / Lb inductor row at
  y=50 (x=-250 / 100 / 470), Cin / Cout cmim banks at x=160 / 480, Cpin /
  Cpout / Csout at y=-330. Terminals carry net labels; the wiring between
  them is the assembly's.
* Bias island (#346, ``draw_bias``): one device row west of the core
  (x in [-1010, -470], baseline y=100) over a Metal2/Metal3 Router channel,
  with Cbyp2 / Cvdd banks below.
* Assembly (#228, ``draw_assembly``): rfin pad east of Lb (760, 50), rfout
  pad south of Csout, vdd / vss pads south of the Cvdd / Cbyp2 banks (all
  PDK bondpad octagons on TopMetal2, labelled on 134/25); every other
  inter-block net reaches a TopMetal1 trunk (y in [-504, -440], one per
  net) by a TopMetal2 spine at unique x; each terminal lands a guard-checked
  via_stack from its own metal up to TopMetal2.

Ports: the netlist's .subckt ports vdd, vss, rfin, rfout (realization.json
``ports.list``), each a labelled bondpad.
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

from lvs_reference import parse_netlist  # noqa: E402
from pcell_env import load_sg13_dev, pcell_lib_digest  # noqa: E402

# GDS layer numbers, from ihp-sg13g2/libs.tech/klayout/tech/sg13g2.lyp.
ACTIV = (1, 0)
GATPOLY = (5, 0)
CONT = (6, 0)
METAL1 = (8, 0)
METAL1_TEXT = (8, 25)
METAL2 = (10, 0)
METAL2_TEXT = (10, 25)
METAL3 = (30, 0)
NWELL = (31, 0)
METAL5 = (67, 0)
TOPMETAL1 = (126, 0)
TOPMETAL1_TEXT = (126, 25)
TOPMETAL2 = (134, 0)
TOPMETAL2_TEXT = (134, 25)

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


def via_stack(cv: Canvas, x, y, top: str, cols=1, rows=1, tcols=1, trows=1, b: str = "Metal1"):
    """PDK via_stack PyCell from ``b`` (default Metal1) up to ``top``, centred on (x, y)."""
    params = {"b_layer": b, "t_layer": top, "vn_columns": cols, "vn_rows": rows}
    if top == "TopMetal1":
        params.update({"vt1_columns": tcols, "vt1_rows": trows})
    return cv.pcell("via_stack", params, x, y)


def cap_bank(cv: Canvas, cp: dict, count: int, x0: float, ytop: float, top_net: str, bot_net: str, ncol: int = 4, wire: bool = False):
    """A ``count``-unit cmim bank (same arithmetic as Cbref): merged Metal5
    bottom sheet (net ``bot_net``, brought to Metal1 by a via stack on a west
    stub, labelled there) and TopMetal1 top-plate straps (net ``top_net``,
    labelled on TopMetal1). Returns the assembly terminals: ``bot`` (the
    Metal1 west-stub pad) and ``top_strap`` (west end of the first row
    strap, on TopMetal1); with ``wire=True`` (issue #346) also ``top``, the
    Metal2 pin north of the bank."""
    side = float(cp["w"].rstrip("u"))
    nrow = count // ncol
    if ncol * nrow != count:
        raise SystemExit("generate: cap bank assumes a full ncol grid")
    pitch = side + 2.0
    centers = []
    for j in range(nrow):
        for i in range(ncol):
            x, y = x0 + pitch * i, ytop - side - pitch * j
            cv.pcell("cmim", cp, x, y)
            centers.append((x + side / 2, y + side / 2))
    x1 = x0 + pitch * (ncol - 1) + side
    y0 = ytop - side - pitch * (nrow - 1)
    cv.box(METAL5, x0 - 0.6, y0 - 0.6, x1 + 0.6, ytop + 0.6)
    ymid = (y0 + ytop) / 2
    cv.box(METAL5, x0 - 6.0, ymid - 1.5, x0 - 0.5, ymid + 1.5)
    via_stack(cv, x0 - 4.0, ymid, "Metal5", cols=2, rows=2)
    # west pad extended further west: the #228 assembly lands its via stack
    # at (x0-9, ymid) on this Metal1 finger, clear of the stub's own
    # Metal1->Metal5 via column and of the bank's TopMetal1 top plates.
    cv.box(METAL1, x0 - 11.0, ymid - 0.5, x0 - 3.6, ymid + 0.5)
    cv.label(METAL1_TEXT, bot_net, x0 - 4.0, ymid)
    strap = 4.0
    for j in range(nrow):
        yc = centers[j * ncol][1]
        cv.box(TOPMETAL1, centers[j * ncol][0], yc - strap / 2, centers[j * ncol + ncol - 1][0], yc + strap / 2)
    xc0 = centers[0][0]
    cv.box(TOPMETAL1, xc0 - strap / 2, centers[-ncol][1], xc0 + strap / 2, centers[0][1])
    cv.label(TOPMETAL1_TEXT, top_net, xc0, centers[0][1])
    pins = {"bot": (x0 - 4.0, ymid), "bot_assembly": (x0 - 9.0, ymid), "top_strap": (centers[0][0], centers[0][1])}
    if not wire:
        return pins
    # wire=True (issue #346): bring both plates out as Metal2 pins. Top: the
    # first-column strap runs north of the Metal5 sheet to a TopMetal1 -> Metal2
    # via stack (as Cbref does); bottom: the Metal1..Metal5 stack on the west stub.
    ytap = ytop + 10.0
    cv.box(TOPMETAL1, xc0 - strap / 2, centers[0][1], xc0 + strap / 2, ytap)
    via_stack(cv, xc0, ytap, "TopMetal1", cols=2, rows=2, tcols=2, trows=2)
    pins["top"] = (xc0, ytap)
    return pins


def small_cap(cv: Canvas, cp: dict, x: float, y: float, top_net: str, bot_net: str) -> dict:
    """One cmim: top plate labelled on TopMetal1, bottom plate (the PyCell's
    own Metal5) strapped west to a via stack and labelled on Metal1. Returns
    the assembly terminals ``top`` (TopMetal1 plate centre) and ``bot`` (the
    Metal1 west pad)."""
    side = float(cp["w"].rstrip("u"))
    cv.pcell("cmim", cp, x, y)
    cv.label(TOPMETAL1_TEXT, top_net, x + side / 2, y + side / 2)
    cv.box(METAL5, x - 6.0, y + side / 2 - 1.5, x - 0.3, y + side / 2 + 1.5)
    via_stack(cv, x - 4.0, y + side / 2, "Metal5", cols=2, rows=2)
    cv.label(METAL1_TEXT, bot_net, x - 4.0, y + side / 2)
    return {"top": (x + side / 2, y + side / 2), "bot": (x - 4.0, y + side / 2)}


def inductor(cv: Canvas, spec: dict, cx: float, y0: float, la: str, lb: str) -> dict:
    """PDK inductor2 PyCell, origin at the bottom-centre of its pin edge.
    Its TopMetal1 pins LA (west) / LB (east) are labelled with the schematic
    nets on TopMetal1.text (positions read from the drawn cell's pin shapes).
    Returns the two pin centres in world coordinates for the assembly."""
    cell = cv.pcell("inductor2", dict(spec["params"]), cx, y0)
    pin = cv.ly.layer(126, 2)
    boxes = sorted((s.bbox() for s in cell.shapes(pin).each()), key=lambda b: b.center().x)
    if len(boxes) != 2:
        raise SystemExit(f"generate: inductor2 {spec['params']} has {len(boxes)} TopMetal1 pins, expected 2")
    out = {}
    for b, net in zip(boxes, (la, lb)):
        px, py = cx + b.center().x * cv.ly.dbu, y0 + b.center().y * cv.ly.dbu
        cv.label(TOPMETAL1_TEXT, net, px, y0 + 3.0)
        out[net] = (px, py)
    return out


def draw_matching(cv: Canvas, rz: dict) -> dict:
    """Issue #347: matching-network devices (inductors, coupling/shunt caps).
    Floorplan (um): inductor row north of the core at y=50 (Le x=-250, Lc
    x=100, Lb x=470); cap banks Cin / Cout east of the Cbref bank at
    x=160 / x=480 (top y=-14); the three small caps below them at y=-330.
    Inter-block wiring is deliberately NOT drawn here: every terminal carries
    a net-name label on the metal layer klt reads, and the shared names
    (e1 vss vdd outn b1 xout) join these devices to the core's nets at
    extraction; routing is pad-ring / top-level assembly (#228). Returns
    every terminal the assembly (#228) is allowed to land a via stack on,
    keyed by net."""
    y_ind = 50.0
    terms: dict[str, list[tuple[float, float, str]]] = {}

    def add(net: str, pt: tuple[float, float], via: str) -> None:
        terms.setdefault(net, []).append((pt[0], pt[1], via))

    le = inductor(cv, rz["Le"], -250.0, y_ind, "e1", "vss")
    lc = inductor(cv, rz["Lc"], 100.0, y_ind, "vdd", "outn")
    lb = inductor(cv, rz["Lb"], 470.0, y_ind, "xin", "rfin")
    for pins in (le, lc, lb):
        for net, pt in pins.items():
            add(net, pt, "TopMetal1")
    for inst, x0, top_net, bot_net in (
        ("Cin", 160.0, "b1", "xin"),
        ("Cout", 480.0, "outn", "xout"),
    ):
        pins = cap_bank(cv, dict(rz[inst]["params"]), int(rz[inst]["count"]), x0, -14.0, top_net, bot_net)
        add(top_net, pins["top_strap"], "TopMetal1")
        # bottom plate: the west-stub Metal1 finger's assembly landing
        add(bot_net, pins["bot_assembly"], "Metal1")
    for inst, x, top_net, bot_net in (
        ("Cpin", 170.0, "xin", "vss"),
        ("Cpout", 230.0, "xout", "vss"),
        ("Csout", 290.0, "xout", "rfout"),
    ):
        pins = small_cap(cv, dict(rz[inst]["params"]), x, -330.0, top_net, bot_net)
        add(top_net, pins["top"], "TopMetal1")
        # bottom: the Metal5 west strap, 1 um west of the pad's via column
        add(bot_net, (pins["bot"][0] - 1.0, pins["bot"][1]), "Metal5")
    return terms


STUB_HALF_WIDTH = 0.2  # um; Router Metal2 stubs / Metal3 trunks are drawn x +- this
# um; sg13g2 Metal2 minimum space, `klt drc --list-rules --deck sg13g2`
# rule metal2.space.1 threshold_um (klt 0.9.3.dev1601+gf6e067c8, klayout 0.30.12).
METAL2_MIN_SPACE = 0.21
# Assembly-channel minimum space: TopMetal2's own rule (topmetal2.space.1).
TOPMETAL2_MIN_SPACE = 2.0


class Router:
    """Channel router: every terminal pin drops a stub on the stub layer
    straight to its net's trunk (one horizontal track per net, tracks
    ``pitch`` apart below ``y_top``), joined by a via stack from the trunk
    layer to the stub layer. Pins are unique in x, so stubs never overlap;
    stubs cross other nets' trunks on a different layer. A pin that is not
    already on the stub layer gets a via stack up to it first.

    The bias island (issue #346) instantiates this with the defaults --
    Metal2 stubs over one Metal3 trunk per net -- where a Metal1 pin gets a
    Metal1->Metal2 via stack first and a Metal2 pin (HBT emitter plate) does
    not. The top-level assembly (issue #228) instantiates the same class
    with TopMetal2 spines over TopMetal1 trunks in the empty channel south
    of the blocks: TM2 spines cross every block and every other net's TM1
    trunk with nothing under them, and each terminal names the metal its
    landing via stack starts from (Metal1/Metal2/TopMetal1).
    """

    def __init__(
        self,
        cv: Canvas,
        y_top: float,
        pitch: float = 1.0,
        *,
        stub_ld: tuple[int, int] = METAL2,
        trunk_ld: tuple[int, int] = METAL3,
        stub_half: float = STUB_HALF_WIDTH,
        trunk_half: float | None = None,
        min_space: float = METAL2_MIN_SPACE,
        stub_via_top: str = "Metal2",
        stub_via_bottom: str = "Metal1",
        join_via_top: str = "Metal3",
        join_via_bottom: str = "Metal2",
    ):
        self.cv, self.y_top, self.pitch = cv, y_top, pitch
        self.stub_ld, self.trunk_ld = stub_ld, trunk_ld
        self.stub_half = stub_half
        self.trunk_half = trunk_half if trunk_half is not None else stub_half
        self.min_space = min_space
        self.stub_via_top, self.stub_via_bottom = stub_via_top, stub_via_bottom
        self.join_via_top, self.join_via_bottom = join_via_top, join_via_bottom
        self.pins: dict[str, list[tuple[float, float, bool, str | None]]] = {}

    def pin(self, net: str, x: float, y: float, metal2: bool = False, via: str | None = None) -> None:
        """Register a terminal. ``metal2`` (a bias-channel leftover name):
        the pin is already on the stub layer, no landing via. Otherwise
        ``via`` names the bottom layer of the landing via stack (default
        ``stub_via_bottom``)."""
        self.pins.setdefault(net, []).append((x, y, metal2, via))

    def check_pin_collisions(self) -> None:
        """Fail loudly if stubs of two *different* nets are too close in x.
        Stubs span x +- stub_half, so |dx| <= 2 * stub_half makes them
        overlap or abut, and `klt extract` merges abutting same-layer metal
        into one net (measured at exactly 0.4 um Metal2: merged_net_labels
        a|b, while `klt drc` reported 0 violations). The bound is therefore
        the stub pitch plus the stub layer's minimum space (0.61 um Metal2,
        6.0 um TopMetal2). Same-net pins sharing an x are legal. Covers the
        stub box only: the via pads are narrower than the stub box
        (Metal1-Metal4 +-0.35, TopMetal1/2 +-1.93 um for 2x2 stacks,
        measured from via_stack), so the stub box dominates."""
        pitch = 2 * self.stub_half + self.min_space
        pts = sorted((x, net) for net, pins in self.pins.items() for x, _y, _m, _v in pins)
        for i, (xa, na) in enumerate(pts):
            for xb, nb in pts[i + 1 :]:
                if xb - xa >= pitch - 1e-9:
                    break
                if nb != na:
                    raise SystemExit(
                        f"generate: pins of nets {na} and {nb} collide at x={xa:g}/{xb:g} "
                        f"(|dx|={xb - xa:g} < stub pitch + min space {pitch:g}); stubs would short"
                    )

    def route(self) -> dict[str, float]:
        cv, tracks = self.cv, {}
        self.check_pin_collisions()
        for i, (net, pins) in enumerate(self.pins.items()):
            if len(pins) < 2:
                raise SystemExit(f"generate: net {net} has a single pin {pins}")
            yt = self.y_top - self.pitch * i
            tracks[net] = yt
            for x, y, metal2, via in pins:
                if not metal2:
                    via_stack(cv, x, y, self.stub_via_top, b=via or self.stub_via_bottom)
                cv.box(self.stub_ld, x - self.stub_half, min(y, yt) - self.stub_half, x + self.stub_half, max(y, yt) + self.stub_half)
                via_stack(cv, x, yt, self.join_via_top, b=self.join_via_bottom)
            xs = [p[0] for p in pins]
            cv.box(self.trunk_ld, min(xs) - self.trunk_half, yt - self.trunk_half, max(xs) + self.trunk_half, yt + self.trunk_half)
        return tracks


def _bias_mos(cv: Canvas, rt: Router, spec: dict, nodes: list[str], x: float, y: float) -> None:
    """One single-finger pmosHV/nmosHV (netlist order d g s b) at (x, y) =
    Activ lower-left. PyCell-relative geometry (w x 1 um, ng=1): source Metal1
    strip x[0.07,0.23] (left), drain strip x[1.45,1.61] (right), both
    y[0,w]; GatPoly x[0.34,1.34], y[-0.18,w+0.18]. The gate is contacted on a
    GatPoly stub below the device (the Cont/Metal1 pad XMis uses). Gate and
    drain are labelled and registered as router pins; the source is the
    caller's (pmos: vdd rail, nmos: ``es`` pin)."""
    d, g, _s, _b = nodes
    cv.pcell(spec["pcell"], dict(spec["params"]), x, y)
    cv.box(GATPOLY, x + 0.34, y - 1.40, x + 1.34, y - 0.10)
    gx = x + 0.84
    cv.box(CONT, gx - 0.08, y - 1.27, gx + 0.08, y - 1.11)
    cv.box(METAL1, gx - 0.18, y - 1.32, gx + 0.18, y - 1.06)
    cv.label(METAL1_TEXT, g, gx, y - 1.19)
    rt.pin(g, gx, y - 1.19)
    cv.label(METAL1_TEXT, d, x + 1.53, y + 0.6)
    rt.pin(d, x + 1.53, y + 0.6)


def _res_pads(cell, trans) -> list:
    """The PyCell's two Metal1 end pads in world coordinates, ordered by
    (x, y) of the *unrotated* cell: terminal a (the netlist's first node) is
    the lower-left pad, b the other. Read from the drawn cell, so rppd (pads
    stacked in y) and rhigh (pads side by side) share one path."""
    ly = cell.layout()
    boxes = [s.dbbox() for s in cell.shapes(ly.layer(*METAL1)).each()]
    if len(boxes) != 2:
        raise SystemExit(f"generate: resistor PyCell has {len(boxes)} Metal1 pads, expected 2")
    boxes.sort(key=lambda b: (b.center().x, b.center().y))
    return [trans * b.center() for b in boxes]


def draw_bias(cv: Canvas, rz: dict, cards: dict) -> tuple[dict, dict[str, float]]:
    """Issue #346: the bias side -- DR-0003 reference core, cascode-base
    divider and the two 100 pF caps -- west of the core, as ONE row of
    devices over a routing channel (um; Yr = 100 is the row baseline):

    * pmos x6 (XMb XMa XMv XMld XMlm XMref) in one NWell; a Metal1 ``vdd`` rail
      over an ntap strip above them joins every source and the well tap.
    * nmos x2 (XMnp1 XMnp2) over a ptap ``vss`` strip.
    * HBTs XQb (Nx=8), XQa, XQc (Nx=1, base/collector tied on Metal1).
    * resistors, rotated 90 deg: rppd for R2a R2b Rp Rsum Rtail Rl, an rhigh
      meander for Rseed.
    * channel (y < Yr - 8): one Metal3 trunk per net, Metal2 stubs from every
      pin (``Router``); Cbyp2 / Cvdd (16-unit cmim banks, Cbref's arithmetic)
      sit below at y=-14 and reach their trunks by Metal2 stubs.

    Nets are those of design/netlist/lna.spice (read, never retyped). The
    wiring to the core / matching network is top-level assembly (#228); the
    return value names the bias-side terminals the assembly may land a via
    stack on, plus the Router's per-net trunk tracks (a Metal3 trunk is a
    landing surface too)."""
    X0, YR = -1000.0, 100.0
    rt = Router(cv, YR - 8.0)

    def label_net(net: str) -> str:
        # klt 0.9.2 cannot write a netlist containing a net labelled
        # ``nc_<letters>`` (klayout-tools#6732); the layout label drops the
        # underscore (nc_a -> nca). LVS compares topology, not names.
        return "nc" + net[3:] if net.startswith("nc_") else net

    def nodes(inst: str, lo: int, hi: int) -> list[str]:
        return [label_net(n) for n in cards[inst][lo:hi]]

    def strap(x0: float, x1: float, yc: float) -> None:
        """ptap strip + Metal1 rail with a ``vss`` label and router pin."""
        cv.pcell("ptap1", {"w": f"{x1 - x0 - 2.0:.3f}u", "l": "0.78u"}, x0 + 1.0, yc - 0.39)
        cv.box(METAL1, x0, yc - 0.5, x1, yc + 0.5)
        cv.label(METAL1_TEXT, "vss", x1 - 0.5, yc)
        rt.pin("vss", x1 - 0.5, yc)  # east end: clear of the pin columns at the west end

    # ------------------------------------------------------------- pmos row
    pm = ["XMb", "XMa", "XMv", "XMld", "XMlm", "XMref"]
    hmax = max(float(rz[i]["params"]["w"].rstrip("u")) for i in pm)
    for k, inst in enumerate(pm):
        x = X0 + 6.0 * k
        _bias_mos(cv, rt, rz[inst], nodes(inst, 1, 5), x, YR)
        h = float(rz[inst]["params"]["w"].rstrip("u"))
        cv.box(METAL1, x + 0.07, YR + h, x + 0.23, YR + hmax + 1.0)  # source -> vdd rail
    xa, xb = X0, X0 + 6.0 * (len(pm) - 1) + 1.68
    cv.pcell("ntap1", {"w": f"{xb - xa:.2f}u", "l": "0.78u"}, xa, YR + hmax + 2.0)
    cv.box(NWELL, xa - 0.62, YR - 0.62, xb + 0.62, YR + hmax + 3.20)
    cv.box(METAL1, xa - 3.0, YR + hmax + 0.80, xb - 0.07, YR + hmax + 2.69)
    cv.label(METAL1_TEXT, "vdd", xa + 2.0, YR + hmax + 1.2)
    rt.pin("vdd", xa - 2.8, YR + hmax + 1.75)

    # ------------------------------------------------------------- nmos row
    nm = ["XMnp1", "XMnp2"]
    nx0 = X0 + 40.0
    for k, inst in enumerate(nm):
        x = nx0 + 6.0 * k
        n = nodes(inst, 1, 5)
        _bias_mos(cv, rt, rz[inst], n, x, YR)
        cv.label(METAL1_TEXT, n[2], x + 0.15, YR + 0.6)  # source (es)
        rt.pin(n[2], x + 0.15, YR + 0.6)

    # ------------------------------------------------------------- HBT row
    yq = YR + 4.0
    qx = {"XQb": nx0 + 24.0, "XQa": nx0 + 70.0, "XQc": nx0 + 85.0}
    for inst, x in qx.items():
        p = dict(rz[inst]["params"])
        xr_q = HBT_STEP_X * (int(p["Nx"]) - 1)
        c, b, e, _s = nodes(inst, 1, 5)
        cv.pcell("npn13G2", p, x, yq)
        cv.label(METAL2_TEXT, e, x, yq)
        rt.pin(e, x, yq, metal2=True)
        if c == b:  # diode-tied: bars joined on a Metal1 riser, one pin
            cv.box(METAL1, x + xr_q + 0.90, yq - 1.26, x + xr_q + 1.60, yq - 1.02)
            cv.box(METAL1, x + xr_q + 0.90, yq + 1.01, x + xr_q + 1.60, yq + 1.25)
            cv.box(METAL1, x + xr_q + 1.20, yq - 1.26, x + xr_q + 1.60, yq + 1.25)
            cv.label(METAL1_TEXT, c, x + xr_q + 1.40, yq)
            rt.pin(c, x + xr_q + 1.40, yq)
        else:  # bars extended east past the emitter plate; separate pin columns
            cv.box(METAL1, x + xr_q + 0.90, yq + 1.01, x + xr_q + 2.30, yq + 1.25)
            cv.box(METAL1, x + xr_q + 0.90, yq - 1.26, x + xr_q + 3.40, yq - 1.02)
            cv.label(METAL1_TEXT, c, x + xr_q + 2.10, yq + 1.13)
            cv.label(METAL1_TEXT, b, x + xr_q + 3.30, yq - 1.14)
            rt.pin(c, x + xr_q + 2.10, yq + 1.13)
            rt.pin(b, x + xr_q + 3.30, yq - 1.14)
    strap(nx0, qx["XQc"] + 4.0, YR - 3.0)  # one ptap rail under the nmos pair and the HBTs

    # ------------------------------------------------------------- resistors
    pya = cv.pya
    xcur = nx0 + 100.0
    for inst in ["R2a", "R2b", "Rp", "Rsum", "Rtail", "Rl"]:
        ln = float(rz[inst]["params"]["l"].rstrip("u"))
        tr = pya.DTrans(1, False, xcur + ln + 0.5, YR)  # rot 90: body x[xcur, xcur+l+1]
        cell = cv.ly.create_cell("rppd", "SG13_dev", dict(rz[inst]["params"]))
        cv.top.insert(pya.DCellInstArray(cell.cell_index(), tr))
        for pt, net in zip(_res_pads(cell, tr), nodes(inst, 1, 3)):
            cv.label(METAL1_TEXT, net, pt.x, pt.y)
            rt.pin(net, pt.x, pt.y)
        xcur += ln + 10.0
    tr = pya.DTrans(0, False, xcur, YR)
    cell = cv.ly.create_cell("rhigh", "SG13_dev", dict(rz["Rseed"]["params"]))
    cv.top.insert(pya.DCellInstArray(cell.cell_index(), tr))
    for pt, net in zip(_res_pads(cell, tr), nodes("Rseed", 1, 3)):
        cv.label(METAL1_TEXT, net, pt.x, pt.y)
        rt.pin(net, pt.x, pt.y)

    # ------------------------------------------------------------- cap banks
    bias_terms: dict[str, list[tuple[float, float, str]]] = {}
    for inst, x0 in (("Cbyp2", X0), ("Cvdd", X0 + 300.0)):
        top_net, bot_net = nodes(inst, 1, 3)
        pins = cap_bank(cv, dict(rz[inst]["params"]), int(rz[inst]["count"]), x0, -14.0, top_net, bot_net, wire=True)
        rt.pin(top_net, *pins["top"], metal2=True)
        rt.pin(bot_net, *pins["bot"], metal2=True)
        # assembly landings: on the cap bank's west-stub Metal1 finger, and
        # on the router's Metal2 stub just above the top pin, where no trunk
        # yet reaches.
        bias_terms.setdefault(bot_net, []).append((*pins["bot_assembly"], "Metal1"))
        bias_terms.setdefault(top_net, []).append((pins["top"][0], 0.0, "Metal2"))
    tracks = rt.route()
    return bias_terms, tracks


#: The assembly via-stack chain, bottom to top; a landing's guard window
#: covers the levels strictly between its bottom layer and TopMetal2.
_STACK_CHAIN = ["Metal1", "Metal2", "Metal3", "Metal4", "Metal5", "TopMetal1", "TopMetal2"]
_STACK_CHAIN_LD = {
    "Metal1": METAL1,
    "Metal2": METAL2,
    "Metal3": METAL3,
    "Metal4": (50, 0),
    "Metal5": METAL5,
    "TopMetal1": TOPMETAL1,
    "TopMetal2": TOPMETAL2,
}
#: 2x2-stack pad half-width on the widest level (TopMetal1/TopMetal2,
#: +-1.93 um, measured from the drawn via_stack PCell) + guard margin.
_LANDING_HALF = 2.5


def _netlist_ports(path) -> list[str]:
    """The port list of the design netlist: its ``*.iopin`` lines in order
    (xschem writes the ``.subckt`` wrapper itself, so the line sits in the
    file only as the commented ``**.subckt`` form)."""
    ports: list[str] = []
    for line in path.read_text().splitlines():
        s = line.strip().lower()
        if s.startswith("*.iopin"):
            name = line.split()[1]
            if name in ports:
                raise SystemExit(f"generate: duplicate *.iopin {name} in {path}")
            ports.append(name)
        elif s.startswith(".subckt") and not ports:
            return line.split()[2:]
    if not ports:
        raise SystemExit(f"generate: {path} declares no ports (*.iopin / .subckt)")
    return ports


def draw_assembly(cv: Canvas, terms: dict, ports: list[str]) -> None:
    """Issue #228: top-level assembly -- the pad ring and the inter-block
    wiring that joins the labelled nets physically.

    * Pads: one PDK bondpad PyCell (TopMetal2 octagon, stack nil) per
      realization.json port -- rfin east of Lb, rfout south of Csout, vdd and
      vss south of the bias cap banks -- each labelled on TopMetal2.text
      (134/25), a layer klt's sg13g2 deck reads.
    * Inter-block routing: TopMetal2 spines (one vertical per terminal, at
      unique x) down to one TopMetal1 trunk per net in the empty channel
      south of every block (y in [-504, -440]), reusing ``Router`` with the
      assembly layer pair. TM2 crosses every block and every other net's TM1
      trunk with nothing under it, so no crossing shorts; spines of
      different nets keep TopMetal2's 2 um minimum space (checked).
    * Every terminal lands a via_stack from its own metal (Metal1 / Metal2 /
      Metal3 / Metal5 / TopMetal1) up to TopMetal2. Each landing column is
      guard-checked first: the levels strictly between its bottom and
      TopMetal2 must be empty in the landing window, so a stack can never
      punch through another net's metal.
    * rfin/rfout are two-terminal nets (device + pad): they take a direct
      TM2 run to their pads and no trunk.
    """
    pya = cv.pya
    # ---------------------------------------------------------------- pads
    # bondpad PyCell params passed explicitly (pcell_env blocks the Tcl
    # parameter callbacks, so no Calculate default is relied on).
    pad_params = {
        "model": "bondpad", "shape": "octagon", "stack": "nil", "fill": "nil",
        "FlipChip": "no", "diameter": "80.00u", "hwquota": "1", "topMetal": "TM2",
        "bottomMetal": "3", "addFillerEx": "nil", "passEncl": "2.1u",
        "padType": "bondpad", "padPin": "PAD",
    }
    rfin_pin = terms["rfin"][0]
    rfout_pin = terms["rfout"][0]
    pads = {
        "rfin": (760.0, 50.0),           # east of Lb, on the pin's y
        "rfout": (rfout_pin[0], -580.0),  # south of Csout, on the pin's x
        "vdd": (-500.0, -580.0),
        "vss": (-600.0, -580.0),
    }
    for net in ports:
        if net not in pads:
            raise SystemExit(f"generate: assembly has no pad position for port {net}")
        x, y = pads[net]
        cv.pcell("bondpad", dict(pad_params), x, y)
        cv.label(TOPMETAL2_TEXT, net, x, y)

    # ------------------------------------------------- guarded via landings
    sites: list[tuple[str, float, float, str]] = [
        (net, x, y, via) for net, pins in terms.items() for x, y, via in pins
    ]
    regions: dict[tuple[int, int], object] = {}
    for net, x, y, b in sites:
        for member in _STACK_CHAIN[_STACK_CHAIN.index(b) + 1 : -1]:
            ld = _STACK_CHAIN_LD[member]
            if ld not in regions:
                regions[ld] = pya.Region(cv.top.begin_shapes_rec(cv.layer(ld)))
            window = pya.Region(
                pya.Box(_snap(x - _LANDING_HALF), _snap(y - _LANDING_HALF), _snap(x + _LANDING_HALF), _snap(y + _LANDING_HALF))
            )
            if not regions[ld].interacting(window).is_empty():
                raise SystemExit(
                    f"generate: assembly landing for net {net} at ({x:g},{y:g}) is not clear on "
                    f"{member}; the via stack up to TopMetal2 would short it. Move the landing or the block."
                )

    # ---------------------------------------------- rfin / rfout direct runs
    for net, (px, py), (tx, ty, via) in (
        ("rfin", pads["rfin"], rfin_pin),
        ("rfout", pads["rfout"], rfout_pin),
    ):
        via_stack(cv, tx, ty, "TopMetal2", b=via)
        cv.box(TOPMETAL2, min(tx, px) - 2.0, min(ty, py) - 2.0, max(tx, px) + 2.0, max(ty, py) + 2.0)

    # ------------------------------------------------------------- channel
    rt = Router(
        cv,
        -440.0,
        pitch=8.0,
        stub_ld=TOPMETAL2,
        trunk_ld=TOPMETAL1,
        stub_half=2.0,
        trunk_half=2.0,
        min_space=TOPMETAL2_MIN_SPACE,
        stub_via_top="TopMetal2",
        stub_via_bottom="Metal1",
        join_via_top="TopMetal2",
        join_via_bottom="TopMetal1",
    )
    for net in sorted(t for t in terms if t not in ("rfin", "rfout")):
        for x, y, via in terms[net]:
            rt.pin(net, x, y, via=via)
    for net in ("vdd", "vss"):
        px, py = pads[net]
        rt.pin(net, px, py + 40.0, metal2=True)  # pad octagon top edge, already TopMetal2
    rt.route()

    # --------------------------------------------------- port label self-check
    have = {s.text.string for s in cv.top.shapes(cv.layer(TOPMETAL2_TEXT)).each() if s.is_text()}
    missing = [p for p in ports if p not in have]
    if missing:
        raise SystemExit(f"generate: port label(s) {missing} missing from the GDS")


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

    # Q1: b1 (base bar extended left to R3b and right to the assembly
    # landing), e1 (emitter Metal2 stub left), casc (collector bar extended
    # right to the Metal2 riser).
    cv.box(METAL1, -11.80, -1.26, -0.90, -1.02)
    cv.label(METAL1_TEXT, "b1", -6.0, -1.14)
    cv.box(METAL1, xr + 0.975, -1.26, xr + 29.0, -1.02)  # b1 -> assembly landing
    cv.box(METAL2, -6.0, -0.40, -0.80, 0.40)
    cv.label(METAL2_TEXT, "e1", -5.5, 0.0)
    cv.box(METAL1, xr + 0.80, 1.02, xr + 4.00, 1.46)
    via_stack(cv, xr + 3.60, 1.24, "Metal2")
    cv.box(METAL2, xr + 3.35, 1.00, xr + 3.85, 12.40)
    cv.label(METAL2_TEXT, "casc", xr + 3.60, 6.0)

    # Q2 (at y=12): casc (emitter Metal2 extended right onto the riser),
    # outn (collector bar right, extended to the assembly landing), vb2
    # (base bar left, extended west to the assembly landing).
    cv.box(METAL2, xr + 0.80, 11.60, xr + 3.85, 12.40)
    cv.box(METAL1, xr + 0.80, 13.02, xr + 19.0, 13.46)
    cv.label(METAL1_TEXT, "outn", xr + 6.50, 13.24)
    cv.box(METAL1, -20.0, 10.74, -0.90, 10.98)
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

    # ------------------------------------------------------------------ Rbleed
    # rppd rot=0 at (-160.5, -395.5), PyCell-relative like R3b: body
    # x[-160.5,-159.5] y[-395.5,-8.850]; end pads Metal1 x[-160.48,-159.52]
    # at y[-395.93,-395.63] (xout, below) and y[-8.718,-8.418] (vss, above).
    cv.pcell("rppd", dict(rz["Rbleed"]["params"]), -160.5, -395.5, rot=0)
    cv.box(METAL1, -165.0, -8.50, -60.0, -7.50)  # vss rail extended west, over the pad
    cv.box(METAL1, -161.2, -8.75, -158.8, -7.50)  # upper pad -> rail tie
    cv.box(METAL1, -161.2, -396.60, -158.8, -395.40)  # lower pad extension
    cv.label(METAL1_TEXT, "xout", -160.0, -396.20)

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

    terms = draw_matching(cv, rz)
    cards = parse_netlist(HERE.parent.parent / realization["netlist"])
    bias_terms, tracks = draw_bias(cv, rz, cards)
    for net, pins in bias_terms.items():
        terms.setdefault(net, []).extend(pins)

    # ------------------------------------------- core-side assembly terminals
    if xr + 29.0 > 155.0:  # b1 landing would run into Cin's Metal5 sheet (x>=159.4)
        raise SystemExit("generate: nx too large for the assembly landing columns")
    mx, my = -70.0, 10.0
    ng = int(rz["XMis"]["params"]["ng"])
    act_w = 1.38 * ng + 0.3
    # the bias Router's gsvo Metal3 trunk, landed 1 um inside its east end
    # (XMnp1's drain pin is the easternmost gsvo pin)
    gsvo_trunk_east = -1000.0 + 40.0 + 6.0 * 0 + 1.53
    core_terms: dict[str, list[tuple[float, float, str]]] = {
        "b1": [(xr + 27.0, -1.14, "Metal1")],
        "outn": [(xr + 17.0, 13.24, "Metal1")],
        "vb2": [(-14.0, 10.86, "Metal1")],
        "e1": [(-5.0, 0.0, "Metal2")],
        "gsvo": [(mx + act_w + 1.32, 9.61, "Metal2"), (gsvo_trunk_east - 1.0, tracks["gsvo"], "Metal3")],
        "vdd": [(-40.0, 27.7, "Metal1"), (-950.0, 111.7, "Metal1")],  # XMis bus, bias vdd rail
        "vss": [(10.0, -8.0, "Metal1"), (-880.0, 97.0, "Metal1")],  # core rail, bias ptap rail
        "xout": [(-160.0, -396.2, "Metal1")],  # Rbleed's xout pad extension
    }
    for net, pins in core_terms.items():
        terms.setdefault(net, []).extend(pins)

    ports = _netlist_ports(HERE.parent.parent / realization["netlist"])
    rz_ports = realization.get("ports", {}).get("list")
    if rz_ports is None:
        raise SystemExit("generate: realization.json has no ports.list for the assembly")
    if list(rz_ports) != ports:
        raise SystemExit(f"generate: realization.json ports {rz_ports} != netlist .subckt ports {ports}")
    draw_assembly(cv, terms, ports)
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
