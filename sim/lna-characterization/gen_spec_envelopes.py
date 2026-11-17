#!/usr/bin/env python3
"""Generate the issue-231 ratified-row `klt sim` corner-envelope requests.

Reads the ratified row limits from ``spec/ratified-rows.json`` (never
retyped into this script) and the committed matched-DUT benches from a
reference ``netlist-snapshots`` record, then emits, into a NEW snapshot
directory (refused if any target exists -- ``sim/`` is append-only):

===========================  =========================================
request                      ratified rows graded (measurement, limits)
===========================  =========================================
``matched_op.request``       ``power`` (pdc < 10 mW), ``ic1`` (<= 4.5 mA)
``matched_sp_band.request``  ``gain`` (S21 > 15 dB), ``s11`` (< -10 dB), ``s22`` (< -10 dB)
``matched_sp_stab.request``  ``mu`` (mu > 1), ``negres`` (max|S11|, max|S22| < 1)
``matched_noise.request``    ``nf`` (nf290 < 1.5 dB)
===========================  =========================================

The corner box is the full ratified box of ``spec/target-spec.md``
"Verification corners" narrowed to its three real HBT sections --
process ``{typ, bcs, wcs}`` x temperature ``{-40, 27, 125}`` C x supply
``{1.62, 1.80, 1.98}`` V = 27 cells per analysis. The ratified ``sf``/``fs``
labels are documented duplicates of ``typ`` at the HBT (the binding device
here) and are not separate corners in these envelopes; the mos-section-only
difference they carry is covered by the committed 45-cell records.

Every measurement expression, analysis and option is copied verbatim from
the reference request; the generator only replaces the corner box and
injects ``limits`` / ``spec_row`` on the graded measurements, validating
every injected limit against the parsed ratified row (comparator, limit,
unit) with exact decimal arithmetic. ``nf290_db_worst`` carries its limit
but deliberately no ``spec_row`` tag: the row is expected to fail (issue
#58), and a failing tagged measurement would mark the row *uncovered*
under ``klt signoff``'s derived-coverage rule instead of *covered and
failing*, which would misstate the report.

Usage::

    python3 -I sim/lna-characterization/gen_spec_envelopes.py \
        --ref-dir sim/lna-characterization/netlist-snapshots/<record-id> \
        --out-dir sim/lna-characterization/netlist-snapshots/<new-record-id>

Exit 0 on success, 1 on any validation or refusal.
"""

import argparse
import json
import sys
from decimal import Decimal
from pathlib import Path

# Analysis stem -> [(measurement name, ratified row id, spec_row tag or None,
# expected measurement unit as declared in the reference request)].
GRADED = {
    "matched_op": [
        ("pdc", "power", "power", "W"),
        ("ic1", "ic1", "ic1", "A"),
    ],
    "matched_sp_band": [
        ("s21_db_min", "gain", "gain", "dB"),
        ("s11_db_worst", "s11", "s11", "dB"),
        ("s22_db_worst", "s22", "s22", "dB"),
    ],
    "matched_sp_stab": [
        ("mu_min", "mu", "mu", None),
        ("s11_mag_max", "negres", "negres", None),
        ("s22_mag_max", "negres", "negres", None),
    ],
    "matched_noise": [
        # Honest limit, no spec_row tag (see module docstring).
        ("nf290_db_worst", "nf", None, "dB"),
    ],
}

REQUEST_STEMS = ("matched_op", "matched_sp_band", "matched_sp_stab", "matched_noise")

PROCESS_NAMES = ("typ", "bcs", "wcs")
SUPPLY_V = [1.62, 1.80, 1.98]
TEMPERATURE_C = [-40, 27, 125]

# Unit the ratified limit is written in -> (Decimal scale, measurement unit).
# dB and the dimensionless stability rows pass through unscaled.
UNIT_SCALE = {
    "dB": (Decimal("1"), None),
    "1": (Decimal("1"), None),
    "mW": (Decimal("1e-3"), "W"),
    "mA": (Decimal("1e-3"), "A"),
}


def load_ratified(root):
    """spec/ratified-rows.json -> {row_id: row dict}."""
    path = root / "spec" / "ratified-rows.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    return {row["id"]: row for row in data["rows"]}


def limits_for(row):
    """Ratified comparator/limit/unit -> (klt sim limits dict, measurement unit)."""
    comparator, limit, unit = row["comparator"], Decimal(row["limit"]), row["unit"]
    scale, measured_unit = UNIT_SCALE[unit]
    value = limit * scale
    if comparator == ">":
        key = "min"
    elif comparator in ("<", "≤"):
        key = "max"
    else:
        raise SystemExit(f"ratified row {row['id']}: unsupported comparator {comparator!r}")
    return {"limits": {key: float(value)}}, measured_unit


def build_request(ref_req, rows, stem):
    """One reference request -> the envelope request (validated, deep-copied)."""
    req = json.loads(json.dumps(ref_req))
    process = {p["name"]: p for p in ref_req["corners"]["process"]}
    missing = [n for n in PROCESS_NAMES if n not in process]
    if missing:
        raise SystemExit(f"reference request lacks ratified process corners: {missing}")
    req["corners"] = {
        "process": [json.loads(json.dumps(process[n])) for n in PROCESS_NAMES],
        "supply_v": {"vdd": list(SUPPLY_V)},
        "temperature_c": list(TEMPERATURE_C),
    }
    by_name = {m["name"]: m for m in req["measurements"]}
    for meas_name, row_id, tag, expect_unit in GRADED[stem]:
        row = rows[row_id]
        if row.get("status") != "ratified":
            raise SystemExit(f"row {row_id}: not ratified, refusing to grade it")
        meas = by_name.get(meas_name)
        if meas is None:
            raise SystemExit(f"{stem}: reference request has no measurement {meas_name}")
        if meas.get("unit") != expect_unit:
            raise SystemExit(
                f"{stem}.{meas_name}: unit {meas.get('unit')!r} != expected {expect_unit!r}")
        limits, measured_unit = limits_for(row)
        if measured_unit is not None and expect_unit != measured_unit:
            raise SystemExit(
                f"row {row_id}: ratified unit {row['unit']} scales to {measured_unit}, "
                f"measurement declares {expect_unit}")
        if "limits" in meas or "spec_row" in meas:
            raise SystemExit(f"{stem}.{meas_name}: reference measurement already graded")
        meas.update(limits)
        if tag is not None:
            meas["spec_row"] = tag
    return req


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--ref-dir", required=True,
                    help="reference netlist-snapshots record dir (committed matched decks+requests)")
    ap.add_argument("--out-dir", required=True,
                    help="new netlist-snapshots record dir to write (must be empty or absent)")
    args = ap.parse_args()

    root = Path(__file__).resolve().parents[2]
    ref = Path(args.ref_dir)
    out = Path(args.out_dir)
    if not ref.is_dir():
        raise SystemExit(f"ref dir not found: {ref}")
    expected = {f"{s}.spice" for s in REQUEST_STEMS} | {f"{s}.request.json" for s in REQUEST_STEMS}
    if out.exists():
        strays = sorted(p.name for p in out.iterdir() if p.name not in expected)
        if strays:
            raise SystemExit(f"refusing out dir {out}: unrelated entries {strays} (sim/ is append-only)")
        for stem in REQUEST_STEMS:
            deck, request = out / f"{stem}.spice", out / f"{stem}.request.json"
            if request.exists():
                raise SystemExit(f"refusing to overwrite {request} (sim/ is append-only)")
            if deck.exists() and deck.read_bytes() != (ref / f"{stem}.spice").read_bytes():
                raise SystemExit(f"refusing to replace non-identical deck {deck}")
    rows = load_ratified(root)

    ref_requests = {}
    built = {}
    for stem in REQUEST_STEMS:
        path = ref / f"{stem}.request.json"
        ref_requests[stem] = json.loads(path.read_text(encoding="utf-8"))
        built[stem] = build_request(ref_requests[stem], rows, stem)

    out.mkdir(parents=True, exist_ok=True)
    for stem in REQUEST_STEMS:
        # Decks are copied byte-identical from the reference record: the
        # envelope benches ARE the committed matched-DUT benches.
        (out / f"{stem}.spice").write_bytes((ref / f"{stem}.spice").read_bytes())
        path = out / f"{stem}.request.json"
        path.write_text(json.dumps(built[stem], indent=2) + "\n", encoding="utf-8")
        print(f"wrote {path}")

    n_cells = len(PROCESS_NAMES) * len(SUPPLY_V) * len(TEMPERATURE_C)
    print(f"corner box: {len(PROCESS_NAMES)} process x {len(SUPPLY_V)} supply x "
          f"{len(TEMPERATURE_C)} temperature = {n_cells} cells per analysis")
    print("limits source: spec/ratified-rows.json (validated, not retyped)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
