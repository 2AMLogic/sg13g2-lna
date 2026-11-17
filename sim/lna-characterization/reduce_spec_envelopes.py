#!/usr/bin/env python3
"""Reduce the issue-231 `klt sim` corner-envelope reports into the verdict
record (PDK-free, ngspice-free -- reads only the committed report JSONs).

For each of the four reports in <snapshot-dir>/reports/ this emits

* ``<record-id>-envelope-verdict.csv`` -- one row per graded measurement
  per corner (corner-level value, margin, status) plus the per-measurement
  rollup rows (worst value, binding corner, limits, status);
* ``<record-id>-envelope-verdict.md`` -- the per-ratified-row verdict
  table (covered row, worst value over the 27-cell box, binding corner,
  pass/fail), the envelope-to-row mapping, and the comparison anchors
  against PR #334's 45-cell matched-DUT verdict.

"Binding corner" is the corner that produces the row's worst value: the
``min``/``max`` rollup corner of the graded measurement, exactly as the
report records it (``klt sim`` resolves ties to the first corner in
expansion order).

Usage::

    python3 -I sim/lna-characterization/reduce_spec_envelopes.py \
        --snapshot-dir sim/lna-characterization/netlist-snapshots/<record-id> [--check]

``--check`` recomputes and byte-compares the verdict files against the
committed ones (the PDK-free replay check of this bench) instead of
writing.

Exit 0 ok, 1 on mismatch/missing input, 2 usage.
"""

import argparse
import csv
import io
import json
import sys
from pathlib import Path

# Analysis stem -> the graded measurements this bench reads, with the
# ratified row each grades and which rollup extreme is the binding value.
GRADED = {
    "matched_op": [
        ("ic1", "ic1", "max"),
        ("pdc", "power", "max"),
    ],
    "matched_sp_band": [
        ("s21_db_min", "gain", "min"),
        ("s11_db_worst", "s11", "max"),
        ("s22_db_worst", "s22", "max"),
    ],
    "matched_sp_stab": [
        ("mu_min", "mu", "min"),
        ("s11_mag_max", "negres", "max"),
        ("s22_mag_max", "negres", "max"),
    ],
    "matched_noise": [
        ("nf290_db_worst", "nf", "max"),
    ],
}
STEMS = ("matched_op", "matched_sp_band", "matched_sp_stab", "matched_noise")
STEM_TITLE = {
    "matched_op": "DC operating point (op)",
    "matched_sp_band": "In-band S-parameters (sp, 11 pts, 2.4-2.4835 GHz)",
    "matched_sp_stab": "Broadband stability (sp, dec 40, 10 MHz-30 GHz)",
    "matched_noise": "Noise (290 K-referred, 11 pts in band)",
}

# PR #334's 45-cell matched-DUT verdict (sim/lna-characterization/records/
# issue-27-matched-pvt-verdict.md): worst value and binding cell per row,
# for the bench-equivalence comparison. The 45-cell box includes the
# sf/fs labels these envelopes do not re-run, so the comparison reads
# "envelope worst vs 45-cell worst over the shared ratified HBT corners".
P334 = {
    ("matched_sp_band", "s11_db_worst"): ("-11.1124 dB", "bcs/-40C/1.98V"),
    ("matched_sp_band", "s22_db_worst"): ("-14.9653 dB", "wcs/125C/1.62V"),
    ("matched_sp_band", "s21_db_min"): ("18.7163 dB", "wcs/125C/1.62V"),
    ("matched_sp_stab", "mu_min"): ("1.000000370", "identical at every cell (numerical resolution)"),
    ("matched_sp_stab", "s11_mag_max"): ("0.998996", "bcs/-40C/1.98V"),
    ("matched_sp_stab", "s22_mag_max"): ("0.999999631", "identical at every cell"),
    ("matched_noise", "nf290_db_worst"): ("4.3779 dB", "wcs/125C/1.98V"),
    ("matched_op", "pdc"): ("9.7611 mW", "bcs/27C/1.98V (125C slice ran no op request there)"),
    ("matched_op", "ic1"): ("4.151 mA", "pre-match record 20260926-122301-088c734 box"),
}


def fmt(value):
    if value is None:
        return ""
    return f"{value:.10g}"


def reduce_snapshot(snap):
    snap = Path(snap)
    rec_id = snap.name
    reports = {}
    for stem in STEMS:
        path = snap / "reports" / f"{stem}.report.json"
        reports[stem] = json.loads(path.read_text(encoding="utf-8"))

    rows = []       # csv rows: per-corner graded measurements
    rollups = []    # md table rows
    summary = {}
    for stem in STEMS:
        rep = reports[stem]
        by_name = {m["name"]: m for m in rep["measurements"]}
        corners_by_id = {c["corner_id"]: c for c in rep["corners"]}
        summary[stem] = {
            "status": rep["status"],
            "passed": rep["passed"],
            "failed": rep["failed"],
            "corner_count": rep["corner_count"],
        }
        for meas_name, row_id, extreme in GRADED[stem]:
            roll = by_name[meas_name]
            side = roll[extreme]
            limits = roll.get("limits", {})
            rollups.append({
                "stem": stem,
                "row": row_id,
                "measurement": meas_name,
                "unit": roll.get("unit") or "",
                "limits": json.dumps(limits) if limits else "",
                "status": roll["status"],
                "binding_corner": side["corner_id"] if side else "",
                "worst_value": fmt(side["value"]) if side else "",
                "corner_status": roll["status"],
            })
            for cid, corner in corners_by_id.items():
                for m in corner["measurements"]:
                    if m["name"] == meas_name:
                        rows.append({
                            "analysis": stem,
                            "measurement": meas_name,
                            "spec_row": roll.get("spec_row", ""),
                            "corner_id": cid,
                            "value": fmt(m.get("value")),
                            "unit": m.get("unit") or "",
                            "status": m.get("status", ""),
                            "margin": fmt(m.get("margin")),
                        })
    return rec_id, reports, summary, rollups, rows


def build_md(rec_id, reports, summary, rollups):
    lines = []
    lines.append(f"# Issue #231 -- ratified-row `klt sim` envelope verdicts ({rec_id})")
    lines.append("")
    lines.append("Reduced by `sim/lna-characterization/reduce_spec_envelopes.py` from the four")
    lines.append("committed report envelopes in `reports/` (do not edit by hand; re-run the")
    lines.append("reducer with `--check` to replay). Corner box per request: process")
    lines.append("{typ, bcs, wcs} x VDD {1.62, 1.80, 1.98} V x T {-40, 27, 125} C = 27 cells.")
    lines.append("")
    lines.append("## Run provenance (per envelope)")
    lines.append("")
    lines.append("| analysis | engine | PDK | klt (collector) | backend |")
    lines.append("|---|---|---|---|---|")
    for stem in STEMS:
        env = reports[stem]["environment"]
        prov = reports[stem]["provenance"]
        remote = env.get("remote") or {}
        backend = "batch" if remote else "local"
        lines.append(f"| `{stem}` | ngspice {env.get('engine_version')} | "
                     f"{(prov.get('pdk') or {}).get('name')} {(prov.get('pdk') or {}).get('version')} | "
                     f"{prov.get('klt_version')} | {backend} |")
    lines.append("")
    lines.append("## Per-envelope verdict")
    lines.append("")
    lines.append("| analysis | envelope status | corners passed | corners failed |")
    lines.append("|---|---|---|---|")
    for stem in STEMS:
        s = summary[stem]
        lines.append(f"| `{stem}` ({STEM_TITLE[stem]}) | **{s['status']}** | {s['passed']}/{s['corner_count']} | {s['failed']}/{s['corner_count']} |")
    lines.append("")
    lines.append("## Per-ratified-row verdict (binding corner = worst-value corner)")
    lines.append("")
    lines.append("| ratified row | measurement | limits | worst value | binding corner | verdict |")
    lines.append("|---|---|---|---|---|---|")
    for r in rollups:
        verdict = "**fail**" if r["status"] != "pass" else "pass"
        lines.append(f"| `{r['row']}` | `{r['stem']}.{r['measurement']}` | `{r['limits']}` | {r['worst_value']} {r['unit']} | `{r['binding_corner']}` | {verdict} |")
    lines.append("")
    lines.append("## Bench-equivalence anchors (PR #334 45-cell matched-DUT verdict)")
    lines.append("")
    lines.append("The 45-cell box of `issue-27-matched-pvt-verdict.md` includes the `sf`/`fs`")
    lines.append("labels (ratified duplicates of `typ` at the HBT) which these envelopes do not")
    lines.append("re-run; where the benches are equivalent the numbers must agree to the")
    lines.append("committed record's printed precision, modulo the ngspice 46/47 note in the")
    lines.append("bench README.")
    lines.append("")
    lines.append("| measurement | PR #334 worst (45 cells) | this envelope worst (27 cells) |")
    lines.append("|---|---|---|")
    for r in rollups:
        anchor = P334.get((r["stem"], r["measurement"]))
        if anchor:
            lines.append(f"| `{r['stem']}.{r['measurement']}` | {anchor[0]} ({anchor[1]}) | {r['worst_value']} {r['unit']} at `{r['binding_corner']}` |")
    lines.append("")
    lines.append("## Reading notes")
    lines.append("")
    lines.append("- The `mu` row's margin over 1 sits at the 10 MHz sweep floor at")
    lines.append("  numerical resolution (~4e-7 in PR #334, identical at every cell): the")
    lines.append("  Edwards-Sinsky denominator collapses onto |S22| there, so the margin is")
    lines.append("  the low-frequency asymptote of the Q~10 lossy output network, not a")
    lines.append("  transistor-physics margin. A value below 1 at that floor is a")
    lines.append("  numerical-resolution event, not a demonstrated instability dip; the")
    lines.append("  fine-resolution probe in the committed verdict record covers this.")
    lines.append("- `nf` is expected to fail at every cell until #58 lands (DR-0004);")
    lines.append("  nothing here relaxes the ratified row.")
    lines.append("- The 125 C `pdc`/`ic1` cells fill the gap PR #334 recorded (its 125 C")
    lines.append("  slice ran no op request; the envelope's op request covers all 27 cells).")
    lines.append("")
    return "\n".join(lines) + "\n"


def build_csv(rec_id, rollups, rows):
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(["# record", rec_id])
    w.writerow(["analysis", "measurement", "spec_row", "unit", "limits", "status",
                "binding_corner", "worst_value"])
    for r in rollups:
        w.writerow([r["stem"], r["measurement"], "", r["unit"], r["limits"], r["status"],
                    r["binding_corner"], r["worst_value"]])
    w.writerow([])
    w.writerow(["# per-corner graded measurements"])
    w.writerow(["analysis", "measurement", "spec_row", "corner_id", "value", "unit",
                "status", "margin"])
    for r in rows:
        w.writerow([r["analysis"], r["measurement"], r["spec_row"], r["corner_id"],
                    r["value"], r["unit"], r["status"], r["margin"]])
    return buf.getvalue()


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--snapshot-dir", required=True)
    ap.add_argument("--check", action="store_true",
                    help="recompute and byte-compare against the committed verdict files")
    args = ap.parse_args()

    snap = Path(args.snapshot_dir)
    rec_id, reports, summary, rollups, rows = reduce_snapshot(snap)
    md = build_md(rec_id, reports, summary, rollups)
    csv_text = build_csv(rec_id, rollups, rows)
    md_path = snap / f"{rec_id}-envelope-verdict.md"
    csv_path = snap / f"{rec_id}-envelope-verdict.csv"

    if args.check:
        ok = True
        for path, text in ((md_path, md), (csv_path, csv_text)):
            if not path.exists():
                print(f"FAIL: missing {path}")
                ok = False
            elif path.read_text(encoding="utf-8") != text:
                print(f"FAIL: {path} does not match a fresh reduction")
                ok = False
            else:
                print(f"OK: {path}")
        return 0 if ok else 1

    md_path.write_text(md, encoding="utf-8")
    csv_path.write_text(csv_text, encoding="utf-8")
    print(f"wrote {md_path}")
    print(f"wrote {csv_path}")
    for stem in STEMS:
        s = summary[stem]
        print(f"{stem}: status={s['status']} passed={s['passed']}/{s['corner_count']} "
              f"failed={s['failed']}/{s['corner_count']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
