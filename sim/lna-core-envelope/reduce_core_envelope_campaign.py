#!/usr/bin/env python3
"""Reducer for the issue-#58 emitter-array / cascode-split campaign.

Sibling of core_envelope_campaign.py (the generator); deliberately a separate
file so it does not collide with the bias-evidence reducer work tracked in #117
(sim/lna-characterization). It reuses the shared per-cell status helpers from
lna_variant_campaign.py (read-only) rather than redefining them.

Input : a request snapshot directory (with campaign-manifest.json) and the
        directory of `klt sim` JSON reports named <request-stem>.report.json.
Output: <out-dir>/<record-id>-cells.csv, -split.csv, -summary.json, -summary.md

Failure policy (nothing is dropped silently): every missing / failed / duplicate
/ unexpected / non-finite / version-mismatched item is a recorded issue, the
case is marked INCOMPLETE and no "N/45" or pass claim is printed for it as if it
were complete. Cells whose bias point leaves the forward-active region are
RETAINED, flagged, and excluded from pass counts. Exit codes: 0 complete,
2 incomplete or invalid input, 3 control-replay drift beyond the tolerance.

Reports carrying `"synthetic_fixture": true` are test fixtures: outputs are
stamped SYNTHETIC and refused under sim/lna-core-envelope/records/ so a fixture
can never become evidence.

NF quantities (kept distinct, per the ratified NF row at T0 = 290 K):
  nf290_db_worst     50 Ohm-source NF at 290 K from the .noise bench, band max of
                     the 11 sampled points. This is the quantity compared with
                     the NF < 1.5 dB row.
  nfmin290_db_worst  ngspice sp-analysis NFmin (referenced to the analysis
                     temperature) re-referenced algebraically to 290 K, band
                     max. A noise-match bound, NOT the 50 Ohm-source NF.

Hot-cell gap (per grid case): over ALL 15 grid cells at 125 C (decision record
0004), never only the 3 divider-sweep cells. Reported separately as
worst_hot_gap_nf290_db/_cell and worst_hot_gap_nfmin290_db/_cell (quantity minus
1.5 dB; > 0 fails), with hot_cells_counted_<q> out of hot_cells_expected.
"""
from __future__ import annotations

import argparse
import csv
import importlib.util
import json
import math
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SIM_DIR = HERE.parent

_spec = importlib.util.spec_from_file_location("core_envelope_campaign", HERE / "core_envelope_campaign.py")
CAMP = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(CAMP)
LVC = CAMP.LVC

# Shared RF helper, loaded by explicit path so `python3 -I` works.
_rf_spec = importlib.util.spec_from_file_location("envelope_rf", HERE / "envelope_rf.py")
_rf = importlib.util.module_from_spec(_rf_spec)
_rf_spec.loader.exec_module(_rf)
nf_reref = _rf.nf_reref

# Ratified rows this campaign is read against (spec/target-spec.md, unchanged).
NF_LIMIT_DB = 1.5
GAIN_MIN_DB = 15.0
PDC_LIMIT_MW = 10.0
T0_K = 290.0
# Hot cells for the NF gap (decision record 0004): ALL grid cells at this
# temperature (5 labels x 3 supplies = 15), NOT the 3 divider-sweep cells.
HOT_TEMP_C = 125
AE_UNIT_UM2 = 0.1152   # npn13G2 single-finger emitter area (same constant as parse_core_envelope.py)

# Control-replay tolerance: the one parse_core_envelope.py applies (relative,
# 1e-6). Investigate a difference; do not relax this.
REPLAY_REL_TOL = 1e-6
# (reducer column, reference-summary column)
REPLAY_COLUMNS = [
    ("s21_db_min", "s21_db_min"), ("s11_db_worst", "s11_db_worst"),
    ("nfmin_sp_db_lo", "nfmin_sp_db_at_band_lo"), ("nf290_db_3pt_worst", "nf290_db_worst"),
    ("pdc", "pdc_w"), ("ic1", "ic1_a"),
]

# Bias classification thresholds (bench definitions, stated in the README).
VBE_ON_MIN_V = 0.5      # below this the device is not conducting meaningfully
VBC_FWD_MAX_V = 0.3     # forward-active: collector-base junction not appreciably forward biased
VBC_SAT_V = 0.5         # above this the device is saturated
VCE_BOX_MIN_V = 0.4     # model-card validity box (sg13g2_hbt_mod.lib), flagged only
VCE_BOX_MAX_V = 2.0

BIAS_CLASSES = ("forward_active", "marginal", "saturated", "cutoff", "reverse", "nonfinite", "missing")


def finite(x) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)


# =============================================================================
# bias classification
# =============================================================================

def classify_device(ic, vbe, vbc, vce):
    if not all(finite(x) for x in (ic, vbe, vbc, vce)):
        return "nonfinite"
    if vce <= 0:
        return "reverse"
    if ic <= 0 or vbe < VBE_ON_MIN_V:
        return "cutoff"
    if vbc > VBC_SAT_V:
        return "saturated"
    if vbc > VBC_FWD_MAX_V:
        return "marginal"
    return "forward_active"


def classify_bias(op: dict) -> dict:
    """Classify BOTH HBTs from the measured op values. `op` may lack keys (class
    'missing'). The cell class is the worse of the two devices; only
    forward_active is `valid`."""
    need = ("ic1", "ic2", "vbe1", "vbe2", "vbc1", "vbc2", "vce1", "vce2")
    if not op or any(k not in op or op[k] is None for k in need):
        return {"class1": "missing", "class2": "missing", "class": "missing", "valid": False,
                "vce_box_flag": ""}
    c1 = classify_device(op["ic1"], op["vbe1"], op["vbc1"], op["vce1"])
    c2 = classify_device(op["ic2"], op["vbe2"], op["vbc2"], op["vce2"])
    order = {c: i for i, c in enumerate(("forward_active", "marginal", "saturated", "cutoff",
                                          "reverse", "nonfinite", "missing"))}
    worst = max((c1, c2), key=lambda c: order[c])
    box = [f"vce{i}" for i, k in ((1, "vce1"), (2, "vce2"))
           if finite(op[k]) and not (VCE_BOX_MIN_V <= op[k] <= VCE_BOX_MAX_V)]
    return {"class1": c1, "class2": c2, "class": worst, "valid": worst == "forward_active",
            "vce_box_flag": ",".join(box)}


# =============================================================================
# report reading and validation
# =============================================================================

def read_requests(snapshot_dir: Path, corners_dir: Path, client_version: str | None):
    """-> (data, issues, synthetic). data[(stem)] -> {key: {values, valid}}"""
    man = CAMP.load_manifest(snapshot_dir)
    issues = []
    data = {}
    synthetic = False
    jobs = {}

    def issue(kind, r, cell=None, measurement=None, detail=""):
        issues.append({"kind": kind, "case": r["case"], "analysis": r["analysis"],
                       "stem": r["stem"],
                       "cell": LVC.cell_text(cell) if isinstance(cell, tuple) else cell,
                       "measurement": measurement, "detail": detail})

    for r in man["requests"]:
        expected = [LVC.norm_key(*c) for c in r["expected_cells"]]
        rep = corners_dir / f"{r['stem']}.report.json"
        if not rep.is_file():
            issue("missing_report", r, detail=f"no {rep.name}")
            continue
        try:
            doc = json.loads(rep.read_text())
            corners = doc.get("corners")
            if not isinstance(corners, list):
                raise ValueError("'corners' is not a list")
        except Exception as e:  # noqa: BLE001
            issue("unreadable_report", r, detail=f"{rep.name}: {e}")
            continue
        synthetic = synthetic or bool(doc.get("synthetic_fixture"))
        remote = (doc.get("environment") or {}).get("remote") or {}
        if remote:
            jobs[r["stem"]] = {k: remote.get(k) for k in
                               ("job_id", "instance_type", "runner_klt_version", "state")}
            rv = remote.get("runner_klt_version")
            if client_version and rv and CAMP._semver(rv) != CAMP._semver(client_version):
                issue("version_mismatch", r, detail=f"runner klt {rv} != client klt {client_version}")
        cmap, dups = {}, set()
        for idx, c in enumerate(corners):
            try:
                key = LVC.norm_key(*LVC.corner_key(c))
            except Exception as e:  # noqa: BLE001
                issue("malformed_cell", r, cell=f"corners[{idx}]", detail=str(e))
                continue
            if key not in expected:
                issue("unexpected_cell", r, cell=key)
                continue
            if key in cmap:
                dups.add(key)
                continue
            names = [m.get("name") for m in c.get("measurements", [])]
            cmap[key] = {"values": LVC.corner_values(c), "ok": LVC.cell_status_ok(c),
                         "dup_meas": sorted({n for n in names if names.count(n) > 1})}
        for key in sorted(dups):
            issue("duplicate_cell", r, cell=key, detail="cell appears more than once; excluded")
        out = {}
        for key in expected:
            if key not in cmap:
                issue("missing_cell", r, cell=key)
                continue
            cell = cmap[key]
            good = key not in dups
            ok, detail = cell["ok"]
            if not ok:
                issue("failed_cell", r, cell=key, detail=detail)
                good = False
            for n in r["expected_measurements"]:
                v = cell["values"].get(n, "__absent__")
                if v == "__absent__":
                    issue("missing_measurement", r, cell=key, measurement=n)
                    good = False
                elif v is None:
                    issue("missing_measurement", r, cell=key, measurement=n, detail="value is null")
                    good = False
                elif not finite(v):
                    issue("non_finite_value", r, cell=key, measurement=n, detail=f"value={v!r}")
                    good = False
            for n in cell["dup_meas"]:
                issue("duplicate_measurement", r, cell=key, measurement=n)
                good = False
            out[key] = {"values": cell["values"], "valid": good}
        data[r["stem"]] = out
    return man, data, issues, synthetic, jobs


# =============================================================================
# reduction
# =============================================================================

def sizing_units(man, sizing):
    s = man["sizing"][sizing]
    return (s["nx"] or 8) * (s["m"] or 1)


def reduce_cells(man, data):
    """One row per (case, cell). `complete` = every analysis of the case valid."""
    by_case = {}
    for r in man["requests"]:
        by_case.setdefault(r["case"], []).append(r)
    rows = []
    for cid, reqs in by_case.items():
        head = reqs[0]
        cells = [LVC.norm_key(*c) for c in head["expected_cells"]]
        for key in cells:
            vals, complete = {}, True
            for r in reqs:
                ent = (data.get(r["stem"]) or {}).get(key)
                if ent is None or not ent["valid"]:
                    complete = False
                    if ent is not None:
                        vals.update({k: v for k, v in ent["values"].items() if finite(v)})
                    continue
                vals.update(ent["values"])
            row = {"case": cid, "kind": head["kind"], "sizing": head["sizing"], "loss": head["loss"],
                   "divider_k": head["divider_k"], "divider": CAMP.divider_label(head["divider_k"]),
                   "r2a_ohm": head["divider_ohm"][0], "r2b_ohm": head["divider_ohm"][1],
                   "corner_label": key[0], "temp_c": int(key[1]), "vdd_v": key[2],
                   "complete": complete}
            row.update(derive(vals, key, complete))
            rows.append(row)
    return rows


def derive(vals, key, complete):
    d = {}
    for n in ("ic1", "ic2", "vb2", "vce1", "vce2", "vbc1", "vbc2", "vbe1", "vbe2", "idd", "pdc",
              "s21_db_min", "s11_db_worst", "s22_db_worst", "mu_band_min", "mu_min", "k_band_min",
              "nf290_db_worst", "nfmin_sp_db_lo", "nfmin_sp_db_worst", "cin_ff_mid"):
        d[n] = vals.get(n)
    d["pdc_mw"] = vals["pdc"] * 1e3 if finite(vals.get("pdc")) else None
    t_k = key[1] + 273.15
    d["nfmin290_db_worst"] = (nf_reref(vals["nfmin_sp_db_worst"], t_k, T0_K)
                              if finite(vals.get("nfmin_sp_db_worst")) else None)
    three = [vals.get(n) for n in ("nf290_db_lo", "nf290_db_mid", "nf290_db_hi")]
    d["nf290_db_3pt_worst"] = max(three) if all(finite(x) for x in three) else None
    op = {k: vals.get(k) for k in ("ic1", "ic2", "vbe1", "vbe2", "vbc1", "vbc2", "vce1", "vce2")}
    cls = classify_bias(op if any(finite(v) for v in op.values()) else {})
    d["bias_class1"], d["bias_class2"], d["bias_class"] = cls["class1"], cls["class2"], cls["class"]
    d["bias_valid"] = cls["valid"]
    d["vce_box_flag"] = cls["vce_box_flag"]

    def margin(limit, v, sign):
        return None if not finite(v) else sign * (limit - v)

    d["nf_margin_db"] = margin(NF_LIMIT_DB, d["nf290_db_worst"], 1)       # >0 passes
    d["nfmin_budget_db"] = margin(NF_LIMIT_DB, d["nfmin290_db_worst"], 1)  # loss left for the match
    d["gain_margin_db"] = None if not finite(d["s21_db_min"]) else d["s21_db_min"] - GAIN_MIN_DB
    d["pdc_margin_mw"] = margin(PDC_LIMIT_MW, d["pdc_mw"], 1)
    d["counts_for_pass"] = bool(complete and d["bias_valid"])
    d["nf_pass"] = (d["counts_for_pass"] and d["nf_margin_db"] is not None and d["nf_margin_db"] > 0)
    d["nfmin_pass"] = (d["counts_for_pass"] and d["nfmin_budget_db"] is not None
                       and d["nfmin_budget_db"] > 0)
    return d


def case_summaries(man, rows, issues):
    bad_cases = {}
    for i in issues:
        bad_cases.setdefault(i["case"], []).append(i)
    out = {}
    cases = {}
    for r in rows:
        cases.setdefault(r["case"], []).append(r)
    for cid, rs in cases.items():
        h = rs[0]
        n = len(rs)
        n_complete = sum(r["complete"] for r in rs)
        complete = n_complete == n and cid not in bad_cases
        s = {"case": cid, "kind": h["kind"], "sizing": h["sizing"], "loss": h["loss"],
             "n_expected": n, "n_complete": n_complete, "campaign_complete": complete,
             "n_bias_invalid": sum(1 for r in rs if r["complete"] and not r["bias_valid"]),
             "n_issues": len(bad_cases.get(cid, [])),
             "emitter_units": sizing_units(man, h["sizing"]),
             "emitter_area_um2": sizing_units(man, h["sizing"]) * AE_UNIT_UM2}
        if h["kind"] == "grid":
            ok = [r for r in rs if r["counts_for_pass"]]
            s["n_nf290_pass"] = sum(r["nf_pass"] for r in rs)
            s["n_nfmin290_pass"] = sum(r["nfmin_pass"] for r in rs)
            s["n_counted"] = len(ok)
            s["claim"] = (f"{s['n_nf290_pass']}/{n} cells with nf290 < {NF_LIMIT_DB} dB (50 Ohm source, "
                          "T0 = 290 K)" if complete else
                          f"INCOMPLETE: {len(ok)}/{n} cells valid; no N/{n} claim")
            # Hot cells = EVERY grid cell at HOT_TEMP_C (15 of the 45; DR-0004),
            # not the 3 divider-sweep cells. Gap = quantity - NF limit (>0 fails),
            # reported separately for the 50 Ohm-source NF and for NFmin@290.
            hot_all = [r for r in rs if r["temp_c"] == HOT_TEMP_C]
            s["hot_cells_expected"] = len(hot_all)
            for col, tag in (("nf290_db_worst", "nf290"), ("nfmin290_db_worst", "nfmin290")):
                hr = [r for r in hot_all if r["counts_for_pass"] and finite(r[col])]
                s[f"hot_cells_counted_{tag}"] = len(hr)
                if hr:
                    r = max(hr, key=lambda x: x[col])
                    s[f"worst_hot_gap_{tag}_db"] = r[col] - NF_LIMIT_DB
                    s[f"worst_hot_gap_{tag}_cell"] = LVC.cell_text(
                        LVC.norm_key(r["corner_label"], r["temp_c"], r["vdd_v"]))
            for col, how in (("nf290_db_worst", max), ("nfmin290_db_worst", max), ("s21_db_min", min),
                             ("pdc_mw", max), ("nfmin_budget_db", min)):
                vs = [(r[col], r) for r in ok if finite(r[col])]
                if vs:
                    v, r = how(vs, key=lambda t: t[0])
                    s["worst_" + col] = v
                    s["worst_" + col + "_cell"] = LVC.cell_text(
                        LVC.norm_key(r["corner_label"], r["temp_c"], r["vdd_v"]))
            nom = [r for r in rs if (r["corner_label"], r["temp_c"], r["vdd_v"]) == ("typ", 27, 1.8)]
            if nom and finite(nom[0]["cin_ff_mid"]):
                s["cin_ff_mid_typ_27c_1p80v"] = nom[0]["cin_ff_mid"]
        out[cid] = s
    return out


def split_rows(rows):
    """Rows of the divider sweep with dNF against the same-cell committed (d0) point."""
    base = {}
    for r in rows:
        if r["kind"] == "split" and r["divider_k"] == 0:
            base[(r["sizing"], r["corner_label"], r["temp_c"], r["vdd_v"])] = r
    out = []
    for r in rows:
        if r["kind"] != "split":
            continue
        b = base.get((r["sizing"], r["corner_label"], r["temp_c"], r["vdd_v"]))
        d_nf = None
        note = ""
        if b is None or not finite(b["nf290_db_worst"]) or not b["complete"]:
            note = "baseline d0 missing or incomplete"
        elif finite(r["nf290_db_worst"]):
            d_nf = r["nf290_db_worst"] - b["nf290_db_worst"]
        out.append({**r, "d_nf290_db_vs_d0": d_nf, "dnf_note": note})
    return out


def control_replay(rows, reference_csv: Path):
    """Compare grid__s_ctrl_a8__ideal against the committed reference summary at the
    existing tolerance. -> (note, issues)."""
    ref = {}
    with open(reference_csv) as fh:
        for rr in csv.DictReader(fh):
            ref[(rr["corner_label"], float(rr["temp_c"]), round(float(rr["vdd_v"]), 4))] = rr
    worst, where, n, issues = 0.0, None, 0, []
    for r in rows:
        if r["case"] != "grid__s_ctrl_a8__ideal":
            continue
        key = (r["corner_label"], float(r["temp_c"]), round(float(r["vdd_v"]), 4))
        if key not in ref:
            issues.append(f"control cell {key} absent from the reference summary")
            continue
        if not r["complete"]:
            continue
        n += 1
        for mine, theirs in REPLAY_COLUMNS:
            a, b = r.get(mine), float(ref[key][theirs])
            if not finite(a):
                issues.append(f"control cell {key} column {mine} not finite")
                continue
            rel = abs(a - b) / max(abs(b), 1e-30)
            if rel > worst:
                worst, where = rel, (key, mine, a, b)
            if rel > REPLAY_REL_TOL:
                issues.append(f"control drift at {key} column {mine}: {a!r} vs reference {b!r} "
                              f"(rel {rel:.3e} > {REPLAY_REL_TOL:g})")
    note = (f"{n} control cells compared; worst relative difference {worst:.3e}"
            + (f" on {where[1]} at {where[0]}" if where else ""))
    return note, issues


# =============================================================================
# output
# =============================================================================

CELL_COLS = ["case", "kind", "sizing", "loss", "divider", "r2a_ohm", "r2b_ohm", "corner_label",
             "temp_c", "vdd_v", "complete", "bias_class1", "bias_class2", "bias_class", "bias_valid",
             "vce_box_flag", "ic1", "ic2", "vce1", "vce2", "vbc1", "vbc2", "vbe1", "vbe2", "vb2", "idd",
             "pdc_mw", "s21_db_min", "s11_db_worst", "s22_db_worst", "mu_band_min", "mu_min",
             "nf290_db_worst", "nfmin290_db_worst", "cin_ff_mid", "nf_margin_db", "nfmin_budget_db",
             "gain_margin_db", "pdc_margin_mw", "counts_for_pass", "nf_pass", "nfmin_pass"]


def fmtv(v):
    if v is None:
        return ""
    if isinstance(v, float):
        return f"{v:.8g}"
    return v


def write_csv(path, cols, rows):
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(cols)
        for r in rows:
            w.writerow([fmtv(r.get(c)) for c in cols])


def markdown(summary, cases, splits, issues, replay_note, synthetic):
    L = []
    if synthetic:
        L += ["**SYNTHETIC FIXTURE OUTPUT -- NOT EVIDENCE. Numbers are invented by a test.**", ""]
    L += [f"# Core-envelope campaign reduction: {summary['record_id']} (set `{summary['set']}`)", ""]
    if summary["complete"]:
        L.append("Coverage: COMPLETE (every expected request, cell and measurement present and finite).")
    else:
        L.append(f"**COVERAGE INCOMPLETE** -- {len(issues)} issue(s); no complete-campaign claim "
                 "may be drawn from this reduction.")
    L += ["", "Bench: see sim/lna-core-envelope/README.md (issue #58 section). nf290 = 50 Ohm-source NF "
          "at T0 = 290 K (.noise); nfmin290 = ngspice sp NFmin re-referenced to 290 K. Bias class from "
          "measured op values, not from the divider ratio.", ""]
    if replay_note:
        L += [f"Control replay: {replay_note}", ""]
    for cid, s in cases.items():
        if s["kind"] != "grid":
            continue
        L.append(f"- `{cid}`: {s['claim']}; complete {s['n_complete']}/{s['n_expected']}; "
                 f"bias-invalid {s['n_bias_invalid']}; worst {HOT_TEMP_C} C hot-cell gap to "
                 f"{NF_LIMIT_DB} dB: nf290 {fmtv(s.get('worst_hot_gap_nf290_db', 'n/a'))} at "
                 f"{s.get('worst_hot_gap_nf290_cell', 'n/a')} "
                 f"({s['hot_cells_counted_nf290']}/{s['hot_cells_expected']} hot cells counted), "
                 f"nfmin290 {fmtv(s.get('worst_hot_gap_nfmin290_db', 'n/a'))} at "
                 f"{s.get('worst_hot_gap_nfmin290_cell', 'n/a')} "
                 f"({s['hot_cells_counted_nfmin290']}/{s['hot_cells_expected']} counted); "
                 f"min NFmin budget {s.get('worst_nfmin_budget_db', 'n/a')}; "
                 f"emitter area {s['emitter_area_um2']:.4g} um^2 ({s['emitter_units']} units; device area, "
                 "not extracted layout)")
    if splits:
        L += ["", "## Divider sweep (all points retained; invalid flagged)", ""]
        for r in splits:
            L.append(f"- {r['sizing']} {r['divider']} {r['corner_label']}/{r['temp_c']}C/{r['vdd_v']:.2f}V: "
                     f"vce1={fmtv(r['vce1'])} vce2={fmtv(r['vce2'])} class={r['bias_class']} "
                     f"nf290={fmtv(r['nf290_db_worst'])} dNF={fmtv(r['d_nf290_db_vs_d0'])}"
                     + ("" if r["bias_valid"] else "  [INVALID BIAS POINT]"))
    if issues:
        L += ["", "## Issues", ""] + [f"- {i['kind']} {i['stem']} cell={i['cell']} "
                                       f"meas={i['measurement']} {i['detail']}".rstrip() for i in issues]
    L += ["", "Not claimed: IIP3; matching-network performance; any specification change; "
          "layout/interconnect/base-resistance parasitics.", ""]
    return "\n".join(L)


def run(snapshot_dir, corners_dir, out_dir, client_version=None, reference_csv=None) -> int:
    snapshot_dir, corners_dir, out_dir = Path(snapshot_dir), Path(corners_dir), Path(out_dir)
    man, data, issues, synthetic, jobs = read_requests(snapshot_dir, corners_dir, client_version)
    problems = CAMP.verify_snapshot(snapshot_dir)
    for p in problems:
        issues.append({"kind": "snapshot_drift", "case": "-", "analysis": "-", "stem": "-",
                       "cell": None, "measurement": None, "detail": p})
    if synthetic and str(out_dir.resolve()).startswith(str((HERE / "records").resolve())):
        print("reduce: refusing to write synthetic-fixture output under records/", file=sys.stderr)
        return 2
    rid = man["record_id"]
    targets = [out_dir / f"{rid}-{s}" for s in ("cells.csv", "split.csv", "summary.json", "summary.md")]
    for t in targets:
        if t.exists():
            print(f"reduce: {t} exists; outputs are append-only (mint a new record id)", file=sys.stderr)
            return 2
    rows = reduce_cells(man, data)
    cases = case_summaries(man, rows, issues)
    splits = split_rows(rows)
    replay_note, drift = "", []
    if reference_csv:
        replay_note, drift = control_replay(rows, Path(reference_csv))
    complete = not issues and all(s["campaign_complete"] for s in cases.values())
    summary = {"schema": "core-envelope-campaign-summary/1", "record_id": rid, "set": man["set"],
               "complete": complete, "synthetic_fixture": synthetic, "n_issues": len(issues),
               "issues": issues, "cases": cases, "control_replay": replay_note,
               "control_drift": drift, "jobs": jobs, "client_version_checked": client_version,
               "nf_limit_db": NF_LIMIT_DB, "gain_min_db": GAIN_MIN_DB, "pdc_limit_mw": PDC_LIMIT_MW,
               "bias_thresholds": {"vbe_on_min_v": VBE_ON_MIN_V, "vbc_fwd_max_v": VBC_FWD_MAX_V,
                                   "vbc_sat_v": VBC_SAT_V}}
    out_dir.mkdir(parents=True, exist_ok=True)
    write_csv(targets[0], CELL_COLS, rows)
    write_csv(targets[1], CELL_COLS + ["d_nf290_db_vs_d0", "dnf_note"], splits)
    targets[2].write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n")
    targets[3].write_text(markdown(summary, cases, splits, issues, replay_note, synthetic))
    print(f"reduce: wrote {targets[0].name}, split, summary.json, summary.md in {out_dir}")
    if drift:
        for x in drift:
            print("reduce: " + x, file=sys.stderr)
        return 3
    if not complete:
        print(f"reduce: COVERAGE INCOMPLETE: {len(issues)} issue(s)", file=sys.stderr)
        for i in issues:
            print(f"reduce: {i['kind']} {i['stem']} cell={i['cell']} meas={i['measurement']} {i['detail']}",
                  file=sys.stderr)
        return 2
    return 0


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--snapshot-dir", required=True)
    p.add_argument("--corners-dir", required=True)
    p.add_argument("--out-dir", required=True)
    p.add_argument("--client-version", default="", help="`klt --version` text; enables the runner/client check")
    p.add_argument("--reference-summary", default="",
                   help="committed control reference (lna-characterization *-summary.csv) for the replay")
    a = p.parse_args(argv)
    return run(a.snapshot_dir, a.corners_dir, a.out_dir, a.client_version or None, a.reference_summary or None)


if __name__ == "__main__":
    sys.exit(main())
