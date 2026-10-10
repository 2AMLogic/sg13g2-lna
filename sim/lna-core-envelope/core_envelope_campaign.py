#!/usr/bin/env python3
"""Emitter-array / cascode-split campaign generator (issue #58, milestone A).

OFFLINE ONLY. This module writes `klt sim` request files, bench netlists and a
provenance manifest. It never launches a simulation and never reads a
measured result as evidence; the reducer (reduce_core_envelope_campaign.py)
and the runner (run_core_envelope_campaign.sh) are the other two parts.

What it generates (two sets, both under netlist-snapshots/<record-id>/):

  gate      5 single-cell requests (typ / 27 C / 1.80 V): one per analysis kind
            for the larger-array variant on the ideal-passive basis, plus one
            sp_band request on the lc_em basis (its relative `.include` of the EM
            inductor model must be staged by the batch runner). This is the
            "one-cell gate": a live nominal probe that must succeed on the
            actual client / runner / PDK before the campaign is launched. It
            validates plumbing only, never the 45-cell specification.
  campaign  * grid: 2 sizing variants x 5 loss bases x 45 cells (5 process
              labels x 3 temperatures x 3 supplies) x 4 analyses
              (op, sp_band, sp_stab, noise);
            * split: 2 sizing variants x 7 divider points x the 3 named hot
              cells x 3 analyses (op, sp_band, noise), ideal-passive basis.

Sizing variants (device targeting verified against run_core_envelope.sh's
variant table, and re-checked by a test that parses that table):

  s_ctrl_a8   the committed netlist, byte-identical device lines (control).
  s_fixi_a80  RF cascode pair only: XQ1 and XQ2 get `Nx=10 m=8`; island mirror
              XMis gets w=51.2u. The bias-core HBTs (XQb Nx=8, XQa, XQ3, XQc)
              are NOT touched -- a blanket `Nx=8` substitution would hit XQb.

Loss bases (each stated separately, never combined with another):

  ideal     as committed (ideal Le, Lc)
  lc_em     Lc = EM-extracted 5-turn model (sim/models/sg13g2_inductor_em.spice),
            Le ideal
  le_q20/10/5   Le in series with R giving Q = wL/R at 2.44175 GHz; Lc ideal.
            This is a resistance BRACKET, used because a validated extracted
            Le is unavailable (#56). It does not solve runner compatibility.

Divider sweep: R2a + R2b is held at the committed 12 kOhm; R2a = 1000 - 250 k,
k = -3..+3 (k > 0 raises vb2). Holding the sum constant keeps the divider's
resistive loading of the Q2 base the same order across points; V_CE1 / V_CE2 are
nonetheless MEASURED (op analysis) and classified, never inferred from the ratio.

Idempotence / immutability: `gen` refuses to write into an existing record
directory (evidence and its request set are append-only).
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import math
import os
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SIM_DIR = HERE.parent
REPO = SIM_DIR.parent

# --- reuse (not copy) the established characterization helpers ---------------
_LVC_PATH = SIM_DIR / "lna-characterization" / "lna_variant_campaign.py"
_spec = importlib.util.spec_from_file_location("lna_variant_campaign", _LVC_PATH)
LVC = importlib.util.module_from_spec(_spec)
sys.path.insert(0, str(_LVC_PATH.parent))
_spec.loader.exec_module(LVC)

DESIGN_NETLIST = LVC.DESIGN_NETLIST
EM_MODEL = LVC.EM_MODEL
LABELS, HBT, MOS = LVC.LABELS, LVC.HBT, LVC.MOS
TEMPS, VDDS = LVC.TEMPS, LVC.VDDS
NOMINAL = LVC.NOMINAL
RUN_SCRIPT = HERE / "run_core_envelope.sh"
PDK_JSON = SIM_DIR / "pdk.json"

RECORD_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
SCHEMA = "core-envelope-campaign/1"

# --- sizing variants ---------------------------------------------------------
# id -> dict(nx, m, xmis_w_um). None => leave the committed text verbatim.
SIZING = {
    "s_ctrl_a8": {"nx": None, "m": None, "xmis_w_um": None,
                  "desc": "committed core (control): Nx=8, XMis w=512u, no edit"},
    "s_fixi_a80": {"nx": 10, "m": 8, "xmis_w_um": "51.2",
                   "desc": "larger emitter array: RF cascode pair Nx=10 m=8, XMis w=51.2u"},
}
RUN_SCRIPT_ROWS = {  # the run_core_envelope.sh VARIANTS rows these must equal
    "s_ctrl_a8": "s_ctrl_a8|1stage|8|1|-|-|512|",
    "s_fixi_a80": "s_fixi_a80|1stage|10|8|-|-|51.2|",
}
# Committed device lines, matched whole-line and exactly once.
Q_LINES = {
    "XQ2": "XQ2 outn vb2 casc vss npn13G2 Nx=8",
    "XQ1": "XQ1 casc b1 e1 vss npn13G2 Nx=8",
}
XMIS_LINE = "XMis bref gsvo vdd vdd sg13_hv_pmos w=512u l=1u ng=1 m=1"
R2A_LINE = "R2a vdd vb2 1k m=1"
R2B_LINE = "R2b vb2 vss 11k m=1"
# Lines of the committed netlist a sizing variant must leave alone (bias core).
BIAS_HBT_PREFIXES = ("XQb ", "XQa ", "XQ3 ", "XQc ")

# --- loss bases --------------------------------------------------------------
LOSS_CASES = {  # id -> (Lc model, Le Q or None, description)
    "ideal": ("ideal", None, "ideal Le and Lc (as committed)"),
    "lc_em": ("em", None, "Lc = EM-extracted 5-turn model; Le ideal"),
    "le_q20": ("ideal", 20, "Le + series R, Q=20 at 2.44175 GHz (bracket); Lc ideal"),
    "le_q10": ("ideal", 10, "Le + series R, Q=10 at 2.44175 GHz (bracket); Lc ideal"),
    "le_q5": ("ideal", 5, "Le + series R, Q=5 at 2.44175 GHz (bracket); Lc ideal"),
}

# --- divider sweep -----------------------------------------------------------
R2_SUM_OHM = 12000
R2A_BASE_OHM = 1000
R2_STEP_OHM = 250
SPLIT_K = [-3, -2, -1, 0, 1, 2, 3]
HOT_CELLS = [("wcs", 125, 1.62), ("typ", 125, 1.80), ("bcs", 125, 1.98)]

# --- analyses ----------------------------------------------------------------
GRID_ANALYSES = ["op", "sp_band", "sp_stab", "noise"]
SPLIT_ANALYSES = ["op", "sp_band", "noise"]
GATE_ANALYSES = ["op", "sp_band", "sp_stab", "noise"]
GATE_EM_ANALYSES = ["sp_band"]   # one lc_em request: validates EM-model include staging

OP_MEASUREMENTS = [
    # name, expr, unit.  Instance Xa is the DUT in every op netlist.
    ("ic1", "@q.xa.xq1.qnpn13g2[ic]", "A"),
    ("ic2", "@q.xa.xq2.qnpn13g2[ic]", "A"),
    ("ib1", "@q.xa.xq1.qnpn13g2[ib]", "A"),
    ("ib2", "@q.xa.xq2.qnpn13g2[ib]", "A"),
    ("vb2", "v(xa.vb2)", "V"),
    ("vce1", "v(xa.casc) - v(xa.e1)", "V"),
    ("vce2", "v(xa.outn) - v(xa.casc)", "V"),
    ("vbe1", "v(xa.b1) - v(xa.e1)", "V"),
    ("vbe2", "v(xa.vb2) - v(xa.casc)", "V"),
    ("vbc1", "v(xa.b1) - v(xa.casc)", "V"),
    ("vbc2", "v(xa.vb2) - v(xa.outn)", "V"),
    ("idd", "-i(vdd)", "A"),
    ("pdc", "v(vdd)*(-i(vdd))", "W"),
]
F_MID = LVC.F_MID
# Extra sp_band observables the campaign needs beyond lna_variant_campaign's list
# (kept here so the shared module is not modified).
SP_BAND_EXTRA = [
    # NFmin at the band bottom (replay column of the committed reference) and worst.
    ("nfmin_sp_db_lo", "real(NFmin[0])", "dB"),
    ("nfmin_sp_db_worst", "vecmax(real(NFmin))", "dB"),
    # Input capacitance proxy Im(Y11)/w at the band centre, from the S-parameters
    # (50 Ohm reference), in fF.
    ("cin_ff_mid",
     "1e15*imag(((1-s_1_1)*(1+s_2_2)+s_1_2*s_2_1)/((1+s_1_1)*(1+s_2_2)-s_1_2*s_2_1))"
     f"[{LVC.MID}]/(50*{2 * math.pi * F_MID:.10g})", "fF"),
]


def sha256_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def sha256_file(p: Path) -> str:
    return sha256_bytes(p.read_bytes())


# =============================================================================
# DUT text
# =============================================================================

def _replace_line_once(body: str, old: str, new: str) -> str:
    lines = body.split("\n")
    hits = [i for i, ln in enumerate(lines) if ln == old]
    if len(hits) != 1:
        raise SystemExit(f"design netlist no longer carries the exact line {old!r} once "
                         f"(found {len(hits)}); refusing to guess a variant edit")
    lines[hits[0]] = new
    return "\n".join(lines)


def divider_ohms(k: int) -> tuple[int, int]:
    r2a = R2A_BASE_OHM - R2_STEP_OHM * k
    return r2a, R2_SUM_OHM - r2a


def divider_label(k: int) -> str:
    return "d0" if k == 0 else (f"dp{k}" if k > 0 else f"dm{-k}")


def dut_text(sizing: str, loss: str, divider_k: int = 0) -> str:
    """The committed subckt with exactly the named edits: loss (from the shared
    #56 helper), sizing (XQ1, XQ2, XMis only) and divider (R2a, R2b only)."""
    if sizing not in SIZING:
        raise SystemExit(f"unknown sizing variant {sizing!r}")
    if loss not in LOSS_CASES:
        raise SystemExit(f"unknown loss case {loss!r}")
    if divider_k not in SPLIT_K:
        raise SystemExit(f"unknown divider point {divider_k!r}")
    lc, le_q, _ = LOSS_CASES[loss]
    body = LVC.dut_subckt(lc, le_q)
    s = SIZING[sizing]
    if s["nx"] is not None:
        for ref, old in Q_LINES.items():
            body = _replace_line_once(
                body, old,
                f"* VARIANT EDIT (sizing {sizing}): was '{old}'\n"
                f"{old.rsplit(' Nx=', 1)[0]} Nx={s['nx']} m={s['m']}")
        body = _replace_line_once(
            body, XMIS_LINE,
            f"* VARIANT EDIT (sizing {sizing}): was '{XMIS_LINE}'\n"
            + XMIS_LINE.replace("w=512u", f"w={s['xmis_w_um']}u"))
    if divider_k != 0:
        r2a, r2b = divider_ohms(divider_k)
        body = _replace_line_once(
            body, R2A_LINE,
            f"* VARIANT EDIT (divider {divider_label(divider_k)}): was '{R2A_LINE}'\n"
            f"R2a vdd vb2 {r2a} m=1")
        body = _replace_line_once(
            body, R2B_LINE,
            f"* VARIANT EDIT (divider {divider_label(divider_k)}): was '{R2B_LINE}'\n"
            f"R2b vb2 vss {r2b} m=1")
    return body


def netlist(case: dict, analysis: str, rel_model: str) -> str:
    lc, le_q, ldesc = LOSS_CASES[case["loss"]]
    sz = SIZING[case["sizing"]]
    div = ("committed R2a/R2b = 1k/11k" if case["divider_k"] == 0 else
           "R2a/R2b = %d/%d Ohm (%s)" % (*divider_ohms(case["divider_k"]), divider_label(case["divider_k"])))
    head = (
        f"* sg13g2-lna core-envelope campaign bench (issue #58): case={case['id']} analysis={analysis}\n"
        "* Generated by sim/lna-core-envelope/core_envelope_campaign.py (gen) -- do not edit.\n"
        f"* Sizing: {case['sizing']} -- {sz['desc']}\n"
        f"* Loss basis: {case['loss']} -- {ldesc}\n"
        f"* Divider: {div}\n"
        f"* DUT: design/netlist/lna.spice sha256 {sha256_file(DESIGN_NETLIST)}, inlined verbatim\n"
        "*   except the edits marked 'VARIANT EDIT'. design/ is not modified.\n"
        "* Port convention: 50 Ohm at both ports; VDD per corner via klt sim `alter vdd`.\n"
        "* op: DC operating point only. sp_band/sp_stab: sp with portnum/z0 sources.\n"
        "*   noise: 50 Ohm Thevenin source, noiseless Rs/RL, NF re-referenced to T0 = 290 K.\n"
        "* Analysis, corners, model sections: see the sibling <case>__<analysis>.request.json.\n"
        "* Bench definitions in full: sim/lna-core-envelope/README.md.\n"
    )
    parts = [head, ".options gmin=1e-10 tnom=27\n"]
    if lc == "em":
        parts.append(f'.include "{rel_model}"\n')
    parts.append(dut_text(case["sizing"], case["loss"], case["divider_k"]))
    parts.append("\nVdd vdd 0 dc 1.8\n")
    if analysis == "noise":
        parts.append("Vin vin 0 dc 0 ac 1\nRs vin nfin 50 noisy=0\nRL nfout 0 50 noisy=0\n"
                     "Xb vdd 0 nfin nfout lna\n")
    else:  # op, sp_band, sp_stab share the sp-style two-port bench
        parts.append("Vp1 pin 0 dc 0 ac 1 portnum 1 z0 50\nVp2 pout 0 dc 0 ac 0 portnum 2 z0 50\n"
                     "Xa vdd 0 pin pout lna\n")
    return "".join(parts)


# =============================================================================
# Cases
# =============================================================================

def grid_cells():
    return [LVC.norm_key(lab, t, v) for lab in LABELS for t in TEMPS for v in VDDS]


def hot_cells():
    return [LVC.norm_key(*c) for c in HOT_CELLS]


def case_stem(case_id: str, analysis: str) -> str:
    return f"{case_id}__{analysis}"


def make_case(kind, sizing, loss, divider_k=0, cells=None, analyses=None):
    if kind == "grid":
        cid = f"grid__{sizing}__{loss}"
    elif kind == "split":
        cid = f"split__{sizing}__{divider_label(divider_k)}"
    else:
        cid = f"gate__{sizing}__{loss}"
    return {"id": cid, "kind": kind, "sizing": sizing, "loss": loss, "divider_k": divider_k,
            "cells": cells, "analyses": analyses}


def campaign_cases():
    cases = []
    for sizing in SIZING:
        for loss in LOSS_CASES:
            cases.append(make_case("grid", sizing, loss, 0, grid_cells(), GRID_ANALYSES))
    for sizing in SIZING:
        for k in SPLIT_K:
            cases.append(make_case("split", sizing, "ideal", k, hot_cells(), SPLIT_ANALYSES))
    return cases


def gate_cases():
    nom = [LVC.norm_key(*NOMINAL)]
    return [make_case("gate", "s_fixi_a80", "ideal", 0, nom, GATE_ANALYSES),
            # One lc_em request: its netlist carries a relative `.include` of the EM
            # inductor model, so the gate proves the batch runner stages that file
            # before the 82-request campaign depends on it.
            make_case("gate", "s_fixi_a80", "lc_em", 0, nom, GATE_EM_ANALYSES)]


# =============================================================================
# Requests
# =============================================================================

def measurements(analysis: str):
    if analysis == "op":
        return [{"name": n, "expr": e, "unit": u} for n, e, u in OP_MEASUREMENTS]
    m = LVC.measurements(analysis)
    if analysis == "sp_band":
        m = m + [{"name": n, "expr": e, "unit": u} for n, e, u in SP_BAND_EXTRA]
    return m


def measurement_names(analysis: str):
    return [m["name"] for m in measurements(analysis)]


def analysis_card(analysis: str) -> dict:
    if analysis == "op":
        return {"kind": "op", "args": ""}
    return LVC.analysis_card(analysis)


def _process_entry(lab):
    return {"name": lab, "sections": [
        {"lib": "libs.tech/ngspice/models/cornerHBT.lib", "section": HBT[lab]},
        {"lib": "libs.tech/ngspice/models/cornerMOShv.lib", "section": MOS[lab]},
    ]}


def corners_block(cells):
    """(corners dict, exclude list) reproducing exactly `cells` under klt's
    process x supply x temperature product. A non-product cell set is expressed
    with `exclude` entries, so the request never silently simulates extra cells."""
    labels = [l for l in LABELS if any(c[0] == l for c in cells)]
    temps = sorted({int(c[1]) for c in cells})
    vdds = sorted({c[2] for c in cells})
    want = {(c[0], int(c[1]), round(c[2], 4)) for c in cells}
    exclude = []
    for lab in labels:
        for v in vdds:
            for t in temps:
                if (lab, t, round(v, 4)) not in want:
                    exclude.append({"process": lab, "supply_v": {"vdd": v}, "temperature_c": t})
    corners = {"process": [_process_entry(l) for l in labels],
               "supply_v": {"vdd": vdds}, "temperature_c": temps}
    return corners, exclude


def request(case: dict, analysis: str, netlist_name: str, backend: str | None) -> dict:
    corners, exclude = corners_block(case["cells"])
    osdi = [f"$PDK_ROOT/ihp-sg13g2/libs.tech/ngspice/osdi/{f}" for f in
            ("psp103.osdi", "psp103_nqs.osdi", "mosvar.osdi")]
    req = {
        "netlist": netlist_name,
        "models": {"pdk": "ihp-sg13g2"},
        "corners": corners,
        "analysis": analysis_card(analysis),
        "measurements": measurements(analysis),
        "options": {"timeout_s": 900, "keep_artifacts": True, "osdi_preload": osdi,
                    "stage_model_inputs": True, "ngspice_init": ["set numdgt=8"]},
    }
    if exclude:
        req["exclude"] = exclude
    if backend:
        req["backend"] = backend
    return req


def expand_request_cells(req: dict):
    """Re-derive the (label, temp, vdd) cells a request will simulate, with klt's
    own odometer semantics (process x supply x temperature minus `exclude`)."""
    cs = req["corners"]
    out = []
    for p in cs["process"]:
        lab = p["name"] if isinstance(p, dict) else p
        for v in cs["supply_v"]["vdd"]:
            for t in cs["temperature_c"]:
                if any(e.get("process") == lab and e["supply_v"]["vdd"] == v
                       and e["temperature_c"] == t for e in req.get("exclude", [])):
                    continue
                out.append(LVC.norm_key(lab, t, v))
    return out


# =============================================================================
# gen
# =============================================================================

def generate(record_id: str, which: str, root: Path | None = None, backend: str | None = None,
             git_sha: str = "unknown") -> Path:
    if not RECORD_ID_RE.match(record_id):
        raise SystemExit(f"invalid record id {record_id!r} (letters, digits, . _ - only)")
    if which not in ("gate", "campaign"):
        raise SystemExit("set must be 'gate' or 'campaign'")
    root = Path(root) if root else HERE
    out = root / "netlist-snapshots" / record_id
    if out.exists():
        raise SystemExit(f"{out} already exists: request snapshots are append-only; mint a new record id")
    cases = gate_cases() if which == "gate" else campaign_cases()
    out.mkdir(parents=True)
    rel_model = os.path.relpath(EM_MODEL, out)
    reqs = []
    for case in cases:
        for an in case["analyses"]:
            stem = case_stem(case["id"], an)
            nl = out / f"{stem}.spice"
            nl.write_text(netlist(case, an, rel_model))
            rq = request(case, an, nl.name, backend)
            rq_path = out / f"{stem}.request.json"
            rq_path.write_text(json.dumps(rq, indent=2) + "\n")
            reqs.append({
                "stem": stem, "case": case["id"], "kind": case["kind"], "sizing": case["sizing"],
                "loss": case["loss"], "divider_k": case["divider_k"],
                "divider_ohm": list(divider_ohms(case["divider_k"])),
                "analysis": an, "netlist": nl.name, "netlist_sha256": sha256_file(nl),
                "request": rq_path.name, "request_sha256": sha256_file(rq_path),
                "expected_cells": [list(c) for c in case["cells"]],
                "expected_measurements": measurement_names(an),
            })
    manifest = {
        "schema": SCHEMA, "record_id": record_id, "set": which,
        "status": "request-set-not-run",
        "note": "Generated requests only. Contains no measured result; a record of results exists "
                "only once reports are collected under corners/<record-id>/ and reduced.",
        "issue": 58, "git_sha": git_sha,
        "design_netlist_sha256": sha256_file(DESIGN_NETLIST),
        "em_model_sha256": sha256_file(EM_MODEL),
        "generator_sha256": sha256_file(Path(__file__)),
        "pdk_pin": json.loads(PDK_JSON.read_text()).get("release_tag"),
        "min_klt_version": json.loads(PDK_JSON.read_text())["klt_variant_campaign"]["min_version"],
        "backend_field": backend or None,
        "grid": {"labels": LABELS, "temps_c": TEMPS, "vdds_v": VDDS, "n_cells": len(grid_cells())},
        "hot_cells": [list(c) for c in hot_cells()],
        "sizing": {k: {kk: v for kk, v in s.items()} for k, s in SIZING.items()},
        "loss_cases": {k: {"lc": v[0], "le_q": v[1], "desc": v[2]} for k, v in LOSS_CASES.items()},
        "divider": {"sum_ohm": R2_SUM_OHM, "r2a_base_ohm": R2A_BASE_OHM, "step_ohm": R2_STEP_OHM,
                    "points": {divider_label(k): list(divider_ohms(k)) for k in SPLIT_K}},
        "requests": reqs,
    }
    (out / "campaign-manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    return out


def load_manifest(snapshot_dir: Path) -> dict:
    m = json.loads((Path(snapshot_dir) / "campaign-manifest.json").read_text())
    if m.get("schema") != SCHEMA:
        raise SystemExit(f"unsupported manifest schema {m.get('schema')!r}")
    return m


def verify_snapshot(snapshot_dir: Path) -> list[str]:
    """Problems with an on-disk request set (hash drift, cell drift). Empty = ok."""
    snapshot_dir = Path(snapshot_dir)
    m = load_manifest(snapshot_dir)
    problems = []
    for r in m["requests"]:
        for key, fname in (("request_sha256", r["request"]), ("netlist_sha256", r["netlist"])):
            p = snapshot_dir / fname
            if not p.is_file():
                problems.append(f"missing {fname}")
            elif sha256_file(p) != r[key]:
                problems.append(f"{fname} sha256 differs from the manifest (edited after generation)")
        p = snapshot_dir / r["request"]
        if p.is_file():
            got = sorted(expand_request_cells(json.loads(p.read_text())))
            want = sorted(LVC.norm_key(*c) for c in r["expected_cells"])
            if got != want:
                problems.append(f"{r['request']} expands to {len(got)} cells != manifest {len(want)}")
    return problems


# =============================================================================
# gate verification (reads reports; writes a verdict, not evidence)
# =============================================================================

def _finite(x):
    return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)


GATE_SCHEMA = "core-envelope-gate/2"


def _problem_corner(stem, corners, want_cell, problems):
    """Validate the single returned corner; return its measurement dict or None."""
    if not isinstance(corners, list) or len(corners) != 1:
        problems.append(f"{stem}: expected exactly 1 corner, got "
                        f"{len(corners) if isinstance(corners, list) else 'none'}")
        return None
    c = corners[0]
    if not isinstance(c, dict):
        problems.append(f"{stem}: malformed corner object ({type(c).__name__})")
        return None
    try:
        got = LVC.norm_key(*LVC.corner_key(c))
    except Exception as e:  # noqa: BLE001
        problems.append(f"{stem}: corner identity missing or malformed ({e!r})")
    else:
        if got != want_cell:
            problems.append(f"{stem}: corner identity mismatch: returned {got}, expected {want_cell}")
    if c.get("error") or str(c.get("status", "ok")).lower() not in LVC.OK_STATUSES:
        problems.append(f"{stem}: corner status={c.get('status')!r} error={c.get('error')!r}")
    ms = c.get("measurements", [])
    if not isinstance(ms, list):
        problems.append(f"{stem}: malformed measurements (not a list)")
        return None
    vals, dups = {}, set()
    for x in ms:
        if not isinstance(x, dict) or not isinstance(x.get("name"), str):
            problems.append(f"{stem}: malformed measurement object {x!r}")
            continue
        if x["name"] in vals:
            dups.add(x["name"])
        vals[x["name"]] = x.get("value")
    for n in sorted(dups):
        problems.append(f"{stem}: duplicate measurement name {n!r}")
    return vals


def verify_gate(snapshot_dir: Path, corners_dir: Path, client_version: str) -> dict:
    """Judge the one-cell gate. Returns a verdict dict with `pass`, `problems` and
    `provenance` ('live' | 'synthetic' | 'mixed' | 'unknown'). A pass establishes
    plumbing only; only provenance 'live' may authorize a campaign."""
    m = load_manifest(snapshot_dir)
    problems, jobs, prov = [], {}, set()
    if m["set"] != "gate":
        problems.append(f"manifest set is {m['set']!r}, not 'gate'")
    for r in m["requests"]:
        rep = Path(corners_dir) / f"{r['stem']}.report.json"
        if not rep.is_file():
            problems.append(f"{r['stem']}: no report")
            continue
        try:
            d = json.loads(rep.read_text())
        except Exception as e:  # noqa: BLE001
            problems.append(f"{r['stem']}: unreadable report ({e})")
            continue
        if not isinstance(d, dict):
            problems.append(f"{r['stem']}: malformed report (top level is {type(d).__name__})")
            continue
        # Anything other than an absent/false flag is treated as synthetic.
        prov.add("live" if d.get("synthetic_fixture") in (None, False) else "synthetic")
        env = d.get("environment")
        remote = env.get("remote") if isinstance(env, dict) else None
        if not isinstance(remote, dict):
            remote = {}
        if not remote.get("job_id"):
            problems.append(f"{r['stem']}: no environment.remote.job_id (not a batch run)")
        rv = remote.get("runner_klt_version")
        if not rv:
            problems.append(f"{r['stem']}: runner_klt_version not reported")
        elif _semver(rv) != _semver(client_version):
            problems.append(f"{r['stem']}: runner klt {rv} != client klt {client_version}")
        if remote.get("state") not in (None, "done"):
            problems.append(f"{r['stem']}: remote state {remote.get('state')!r}")
        want = sorted(LVC.norm_key(*c) for c in r["expected_cells"])
        if len(want) != 1:
            problems.append(f"{r['stem']}: manifest expects {len(want)} cells, gate needs exactly 1")
            continue
        vals = _problem_corner(r["stem"], d.get("corners"), want[0], problems)
        if vals is None:
            continue
        for n in r["expected_measurements"]:
            if not _finite(vals.get(n)):
                problems.append(f"{r['stem']}: measurement {n} missing or non-finite ({vals.get(n)!r})")
        jobs[r["stem"]] = {k: remote.get(k) for k in
                           ("job_id", "instance_type", "runner_klt_version", "state")}
        jobs[r["stem"]].update({k: v for k, v in remote.items() if "image" in k.lower()})
    provenance = (next(iter(prov)) if len(prov) == 1 else "mixed" if prov else "unknown")
    return {
        "schema": GATE_SCHEMA, "gate_record_id": m["record_id"],
        "client_klt_version": client_version, "pdk_pin": m["pdk_pin"],
        "provenance": provenance,
        "pass": not problems, "problems": problems, "jobs": jobs,
        "scope": "plumbing only: one nominal cell per analysis; says nothing about the 45-cell "
                 "specification or NF performance",
    }


def authorizes_campaign(verdict, client_version: str) -> str:
    """Production campaign-authorization predicate. Returns '' if the verdict
    authorizes a campaign, else a reason. Legacy (/1) verdicts, synthetic or
    mixed provenance, and client-version drift all refuse."""
    if not isinstance(verdict, dict) or verdict.get("schema") != GATE_SCHEMA:
        got = verdict.get("schema") if isinstance(verdict, dict) else None
        return f"gate verdict schema is {got!r}, need {GATE_SCHEMA}; rerun the gate"
    if verdict.get("pass") is not True:
        return f"gate verdict is not a passing {GATE_SCHEMA} document"
    if verdict.get("provenance") != "live":
        return f"gate verdict provenance is {verdict.get('provenance')!r}, not 'live'"
    if verdict.get("client_klt_version") != client_version:
        return (f"gate verdict was produced by client {verdict.get('client_klt_version')!r}, "
                f"current client is {client_version!r}; rerun the gate")
    return ""


def _semver(s: str):
    mt = re.search(r"(\d+)\.(\d+)\.(\d+)", s or "")
    return tuple(int(x) for x in mt.groups()) if mt else None


def check_client_floor(version_text: str) -> None:
    floor = json.loads(PDK_JSON.read_text())["klt_variant_campaign"]["min_version"]
    have, need = _semver(version_text), _semver(floor)
    if have is None:
        raise SystemExit(f"cannot parse a klt version from {version_text!r}; need >= {floor}")
    if have < need:
        raise SystemExit(f"klt {'.'.join(map(str, have))} is older than the floor {floor} "
                         "(sim/pdk.json klt_variant_campaign.min_version)")


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    g = sub.add_parser("gen", help="write the request set for one record id (offline)")
    g.add_argument("--record-id", required=True)
    g.add_argument("--set", choices=["gate", "campaign"], required=True)
    g.add_argument("--root", default="", help="parent of netlist-snapshots/ (default: this directory)")
    g.add_argument("--backend", default="", help="optional `backend` field to embed in each request")
    g.add_argument("--git-sha", default="unknown")
    v = sub.add_parser("verify-snapshot", help="check an on-disk request set against its manifest")
    v.add_argument("--snapshot-dir", required=True)
    gv = sub.add_parser("verify-gate", help="judge the one-cell gate reports; write a verdict JSON")
    gv.add_argument("--snapshot-dir", required=True)
    gv.add_argument("--corners-dir", required=True)
    gv.add_argument("--client-version", required=True, help="output of `klt --version`")
    gv.add_argument("--out", required=True)
    ag = sub.add_parser("check-gate-verdict", help="exit nonzero unless the verdict authorizes a campaign")
    ag.add_argument("verdict")
    ag.add_argument("client_version")
    cf = sub.add_parser("check-client", help="exit nonzero if `klt --version` text is below the floor")
    cf.add_argument("version_text")
    a = p.parse_args(argv)
    if a.cmd == "gen":
        out = generate(a.record_id, a.set, Path(a.root) if a.root else None, a.backend or None, a.git_sha)
        n = len(load_manifest(out)["requests"])
        print(f"gen: wrote {n} request/netlist pairs and campaign-manifest.json in {out}")
        return 0
    if a.cmd == "verify-snapshot":
        probs = verify_snapshot(Path(a.snapshot_dir))
        for x in probs:
            print("verify-snapshot: " + x, file=sys.stderr)
        return 1 if probs else 0
    if a.cmd == "check-gate-verdict":
        try:
            v = json.loads(Path(a.verdict).read_text())
        except Exception as e:  # noqa: BLE001
            print(f"check-gate-verdict: unreadable verdict ({e})", file=sys.stderr)
            return 1
        why = authorizes_campaign(v, a.client_version)
        if why:
            print("check-gate-verdict: " + why, file=sys.stderr)
        return 1 if why else 0
    if a.cmd == "check-client":
        check_client_floor(a.version_text)
        return 0
    verdict = verify_gate(Path(a.snapshot_dir), Path(a.corners_dir), a.client_version)
    Path(a.out).write_text(json.dumps(verdict, indent=2, sort_keys=True) + "\n")
    for x in verdict["problems"]:
        print("verify-gate: " + x, file=sys.stderr)
    print(f"verify-gate: {'PASS (plumbing only)' if verdict['pass'] else 'FAIL'}; "
          f"provenance {verdict['provenance']}"
          + ("" if verdict["provenance"] == "live" else " (will NOT authorize a campaign)"))
    return 0 if verdict["pass"] else 2


if __name__ == "__main__":
    sys.exit(main())
