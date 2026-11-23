#!/usr/bin/env python3
"""Delete every shape on one GDS layer that interacts with a box -- the
negative-control stream generator for the T1 item-11 ERC evidence (issue #35).

    python3 layout/erc_break.py <in.gds> <out.gds> <layer/datatype> <l,b,r,t>

Flattens the stream's single top cell, subtracts the box from the layer, and
writes the broken copy to ``<out.gds>``. The control streams live in
gitignored scratch (``layout/build/erc/``): only their verdicts are committed,
in ``layout/lna_core/erc_control.json``, assembled by ``layout/erc_control.py``
-- which fails unless this edit actually moved the ERC verdict, so a control
whose box touched nothing can never pass silently.

Prints one JSON line ``{"deleted_shapes", "deleted_area_um2"}`` so the caller
can see what was removed. Needs the pip ``klayout`` package (the same one
``generate.py`` uses); no PDK, no display, no network.
"""

from __future__ import annotations

import json
import sys

import klayout.db as db


def main(argv: list[str]) -> int:
    if len(argv) != 5:
        print(__doc__, file=sys.stderr)
        return 2
    gds, out, layer_s, box_s = argv[1:5]
    try:
        layer = tuple(int(p) for p in layer_s.split("/"))
        box_um = [float(p) for p in box_s.split(",")]
        assert len(layer) == 2 and len(box_um) == 4
        assert box_um[0] < box_um[2] and box_um[1] < box_um[3]
    except (ValueError, AssertionError):
        print(f"erc_break: bad layer '{layer_s}' or box '{box_s}'", file=sys.stderr)
        return 2

    ly = db.Layout()
    ly.read(gds)
    tops = ly.top_cells()
    if len(tops) != 1:
        print(f"erc_break: expected exactly one top cell, found {len(tops)}", file=sys.stderr)
        return 1
    top = tops[0]
    top.flatten(-1, True)  # one flat shape pool: subtraction cannot miss a child cell

    li = ly.find_layer(*layer)
    if li is None:
        print(f"erc_break: layer {layer_s} not in stream", file=sys.stderr)
        return 1
    reg = db.Region(top.begin_shapes_rec(li))
    if reg.is_empty():
        print(f"erc_break: layer {layer_s} is empty", file=sys.stderr)
        return 1
    box = db.Region(db.Box(*[int(round(v / ly.dbu)) for v in box_um]))
    keep = reg.not_(box)
    deleted = reg.not_(keep)
    top.shapes(li).clear()
    for poly in keep.each():
        top.shapes(li).insert(poly)
    ly.write(out)
    print(
        json.dumps(
            {
                "deleted_shapes": deleted.count(),
                "deleted_area_um2": round(deleted.area() * ly.dbu * ly.dbu, 4),
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
