#!/usr/bin/env python3
"""Parse sim/lna-core-envelope/ raw ngspice output into a per-point CSV + record.

Invoked by run_core_envelope.sh; see sim/lna-core-envelope/README.md for the
bench definitions every column below carries, and for what this experiment
does and does not claim.

Two things this parser does that the lna-characterization parser does not,
both of them load-bearing for issue #52:

1. **It re-references ngspice's own `sp` NF/NFmin to T0 = 290 K.** ngspice's
   two-port `sp` noise figure is referenced to the ANALYSIS temperature, not
   to a fixed source reference temperature -- verified against the committed
   record 20260926-122301-088c734, whose independent `.noise`-based nf290
   column re-references to the analysis temperature to 4 decimal places at
   every one of its 45 cells (see README "NF conventions on this bench").
   `spec/target-spec.md`'s NF row is RATIFIED at T0 = 290 K, so the raw
   `nfmin_sp_db` column is NOT the quantity that row binds. The exact
   algebraic re-reference -- the same identity
   `sim/hbt-characterization/rederive_nf_fixed_t0.py` uses for the #25
   correction -- is
       F(T0) - 1 = (F(T_a) - 1) * T_a / T0
   and its result is emitted as `nfmin290_db`, beside the raw
   `nfmin_sp_db` and the delta, so nothing is silently replaced.

2. **It reports a Q-parameterized available-gain envelope.** The
   "available-gain basis" the issue-#52 discussion uses -- |S21| plus the
   ideal-conjugate-input-match uplift -- holds the OUTPUT at 50 Ohm, i.e. it
   assumes no output matching network at all. That is not the bound it is
   sometimes read as: an output network is part of #27's scope and the
   RATIFIED S22 row requires one. This parser therefore emits both, plus the
   two-port available gain with the collector tank degraded to a finite
   inductor Q (`ga_max_q10_db`), which is the honest middle case given the
   PDK ships no inductor model. See README "Three gain metrics, and which
   one binds what".

3. **It counts stability violations from the RAW sweep points, never from a
   rounded summary column.** mu on this topology sits within parts-per-
   billion of 1 out of band (|S12| ~ -95 dB makes mu ~ 1/|S22|, and Lc is an
   ideal infinite-Q primitive, so |S22| -> 1), so a `mu_broadband_min`
   column rounded to 8 decimals prints `1.00000000` for cells that DO dip
   below 1 at some frequency. `spec/target-spec.md`'s S22 row records the
   same trap on the same bench ("the summary CSV's `s22_mag_broadband_max`
   column carries six decimals and rounds +0.18 ppm to `1.000000` ... count
   from the raw tables"). The `mu_ib_viol` / `mu_bb_viol` roll-up counts
   here are therefore derived from `n_*_pts_mu_lt_1`, which is computed on
   the unrounded sweep values, and the rounded `mu_*_lo` columns are kept
   only as a magnitude indication.

Everything else -- column meanings, the wrdata layout, the corner labels --
matches sim/lna-characterization/parse_lna_sweep.py so the two experiments'
records can be read side by side.

Structure: `main()` is argparse plus orchestration; each stage it drives is a
module-level function so the arithmetic above is unit-addressable without
building a fixture campaign on disk (issue #276). The staging/publication
order is itself load-bearing -- see `main()`.
"""

from __future__ import annotations

import argparse
import os
import csv
import importlib.util
import re
import sys
from pathlib import Path

# Load the shared helper by explicit path so this works under `python3 -I`
# (isolated mode does not put the script directory on sys.path).
_spec = importlib.util.spec_from_file_location(
    "envelope_rf", Path(__file__).resolve().with_name("envelope_rf.py"))
_rf = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_rf)
(INBAND_COLS, parse_table, db20, nf_reref, gain_in_match_db, ga_max_db,
 ga_max_with_tank_q) = (
    _rf.INBAND_COLS, _rf.parse_table, _rf.db20, _rf.nf_reref,
    _rf.gain_in_match_db, _rf.ga_max_db, _rf.ga_max_with_tank_q)

# The broadband deck writes: kfacb mufacb mag(dltb) mag(s11) mag(s21) mag(s22)
STAB_COLS = [
    ("f", 1), ("k", 1), ("f", 1), ("mu", 1), ("f", 1), ("mag_delta", 1),
    ("f", 1), ("s11_mag", 1), ("f", 1), ("s21_mag", 1), ("f", 1), ("s22_mag", 1),
]

AE_UNIT_UM2 = 0.1152  # npn13G2 single-finger emitter area, le=0.96u * we=0.12u
F_BAND_MID = 2.44175e9
T0_IEEE = 290.0       # spec/target-spec.md's RATIFIED NF reference temperature

# Model-card validity box (sg13g2_hbt_mod.lib), the same three limits
# sim/hbt-characterization/README.md documents.
VBE_MIN, VBE_MAX = 0.65, 0.96
VCE_MIN, VCE_MAX = 0.4, 2.0


OP_RE = re.compile(
    r"OP ic1 (\S+) ic2 (\S+) ib1 (\S+) vce1 (\S+) vce2 (\S+) vbe1 (\S+) idd (\S+) pdc (\S+)")
NF_RE = re.compile(r"NF (lo|mid|hi) (\S+) (\S+)")
GAIN_RE = re.compile(r"GAIN (lo|mid|hi) (\S+)")

# The control variant is the committed design/netlist/lna.spice, so its cells
# must reproduce the reference record this bench claims to extend.
CONTROL_VARIANT = "s_ctrl_a8"
CONTROL_COLS = ("s21_db_min", "s11_db_worst", "nfmin_sp_db_at_band_lo",
                "nf290_db_worst", "pdc_w", "ic1_a")
CONTROL_RTOL = 1e-6


def build_arg_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser()
    ap.add_argument("--record-id", required=True)
    ap.add_argument("--corners-dir", required=True)
    ap.add_argument("--records-dir", required=True)
    ap.add_argument("--manifest", required=True)
    ap.add_argument("--design-netlist-sha", default="unknown")
    ap.add_argument("--ngspice-version", default="unknown")
    ap.add_argument("--pdk-root", default="unknown")
    ap.add_argument("--pdk-release", default=None,
                    help="verified installed PDK release (from sim_require_pdk)")
    ap.add_argument("--pdk-provenance", default=None,
                    help="records/<id>.pdk-provenance.json path to cite")
    ap.add_argument("--reference-summary", default=None,
                    help="lna-characterization summary CSV the s_ctrl_a8 control "
                         "variant must reproduce (the runner's regression check)")
    ap.add_argument("--inband-grid", default=None, metavar="LO,HI,N",
                    help="declared in-band `sp lin N LO HI` grid; when given, "
                         "every in-band table must match it exactly")
    ap.add_argument("--stab-grid", default=None, metavar="LO,HI,NDEC",
                    help="declared stability `sp dec NDEC LO HI` grid; when "
                         "given, every stability table must cover it")
    ap.add_argument("--require-all-points", action="store_true",
                    help="strict mode (used by run_core_envelope.sh): exit 5 "
                         "BEFORE staging or publishing anything if any "
                         "manifest point failed to reduce. Default (absent): "
                         "partial reduction, exit 0 with a warning")
    return ap


def declared_grids(ap: argparse.ArgumentParser, args):
    """Resolve the declared-grid CLI args (#165).

    Absent args = historical replay and reduced fixtures: only the per-row
    integrity checks apply. A malformed value is a usage error (exit 2), not a
    failed point.
    """
    try:
        inband_grid = (_rf.parse_grid_arg(args.inband_grid)
                       if args.inband_grid else None)
        stab_grid = (_rf.parse_grid_arg(args.stab_grid)
                     if args.stab_grid else None)
    except ValueError as exc:
        ap.error(str(exc))
    return inband_grid, stab_grid


# --- Exclusive publication (issue #126) ----------------------------------
# The three published files are append-only evidence. Refuse BEFORE reducing
# anything if any already exists; otherwise stage every output under a temp
# name and publish by hard link (atomic, never replaces an existing name)
# only once all three were produced.

def published_names(record_id: str):
    """The three append-only artifacts a finished record publishes."""
    return [f"{record_id}.csv",
            f"{record_id}-variant-summary.csv",
            f"{record_id}.md"]


def refuse_existing_publication(records: Path, names) -> bool:
    """True (after a diagnostic on stderr) if any name is already published."""
    for n in names:
        if os.path.lexists(records / n):
            print(f"parse_core_envelope.py: CORE_ENV_PUBLICATION_EXISTS: "
                  f"{records / n} already exists; published summaries are "
                  "never overwritten. Mint a new CORE_ENV_RECORD_ID.",
                  file=sys.stderr)
            return True
    return False


def stage_paths(records: Path, names):
    """Temp staging path per final name, in this process's own namespace."""
    return {n: records / f".{n}.tmp{os.getpid()}" for n in names}


def publish(records: Path, names, stage) -> bool:
    """Hard-link every staged file to its final name; True on full success.

    Never replaces an existing name. A partial link set leaves the record NOT
    finalized, and the staged temps are removed either way.
    """
    done = []
    try:
        for n in names:
            os.link(stage[n], records / n)
            done.append(n)
    except OSError as e:
        print(f"parse_core_envelope.py: CORE_ENV_PUBLICATION_FAILED: {e}; "
              f"partially published: {done or 'nothing'}. The record is "
              "NOT finalized; mint a new CORE_ENV_RECORD_ID.",
              file=sys.stderr)
        return False
    finally:
        for t in stage.values():
            try:
                os.unlink(t)
            except OSError:
                pass
    return True


# --- Per-point reduction -------------------------------------------------

class PointError(Exception):
    """This manifest point is not complete evidence.

    Carries the reason the caller records in the failed-point list and in the
    record's "Failed points" section. Distinct from a valid measurement that
    fails a target: a PointError means the point is not evidence at all.
    """


def manifest_points(manifest):
    """Yield each manifest line's 13 pipe-separated fields.

    A line with the wrong field count raises ValueError rather than reducing a
    partial point.
    """
    for line in Path(manifest).read_text().splitlines():
        if not line.strip():
            continue
        (pid, vid, family, kind, nx1, m1, nx2, m2, area,
         wis, corner, temp, vdd) = line.split("|")
        yield (pid, vid, family, kind, nx1, m1, nx2, m2, area,
               wis, corner, temp, vdd)


def point_row(fields, corners: Path, inband_grid, stab_grid) -> dict:
    """Reduce one manifest point to its per-point CSV row.

    `fields` is one `manifest_points` tuple. Raises PointError when the point
    is not complete evidence. The returned dict's key order IS the published
    CSV column order.
    """
    (pid, vid, family, kind, nx1, m1, nx2, m2, area,
     wis, corner, temp, vdd) = fields
    log = corners / f"{pid}.log"
    inband = corners / f"{pid}.inband.dat"
    stab = corners / f"{pid}.stability.dat"
    if not (log.exists() and inband.exists() and stab.exists()):
        raise PointError("missing output")
    text = log.read_text()
    if "BENCH_COMPLETE" not in text:
        raise PointError("no BENCH_COMPLETE")
    m = OP_RE.search(text)
    if not m:
        raise PointError("no OP line")
    ic1, ic2, ib1, vce1, vce2, vbe1, idd, pdc = (float(x) for x in m.groups())
    nf = {k: (float(a), float(b)) for k, a, b in NF_RE.findall(text)}
    gain = {k: float(v) for k, v in GAIN_RE.findall(text)}

    try:
        ib = parse_table(inband, INBAND_COLS,
                         expected_points=inband_grid[2] if inband_grid else None)
        sb = parse_table(stab, STAB_COLS)
        if inband_grid:
            _rf.check_declared_grid(ib, inband.name, "lin", *inband_grid)
        if stab_grid:
            _rf.check_declared_grid(sb, stab.name, "dec", *stab_grid)
    except _rf.TableError as exc:
        raise PointError(f"invalid table: {exc}") from None
    if not ib or not sb:
        raise PointError("empty table")

    t_a = float(temp) + 273.15
    area_i = int(area)
    jc = ic1 / (area_i * AE_UNIT_UM2) * 1e3 if area_i else float("nan")

    s21_db = [db20(abs(r["s21"])) for r in ib]
    s11_db = [db20(abs(r["s11"])) for r in ib]
    s12_db = [db20(abs(r["s12"])) for r in ib]
    s22_db = [db20(abs(r["s22"])) for r in ib]
    gin_basis = [gain_in_match_db(r["s11"], r["s21"]) for r in ib]
    gmax_ideal = [ga_max_db(r["s11"], r["s12"], r["s21"], r["s22"]) for r in ib]
    gmax_q10 = [ga_max_with_tank_q(r["s11"], r["s12"], r["s21"], r["s22"],
                                   10.0, r["freq_hz"]) for r in ib]
    nfmin_sp = [r["nfmin"].real for r in ib]
    nf_sp = [r["nf"].real for r in ib]
    nfmin290 = [nf_reref(v, t_a, T0_IEEE) for v in nfmin_sp]

    flags = []
    if not (VBE_MIN <= vbe1 <= VBE_MAX):
        flags.append(f"vbe1={vbe1:.4f}_outside_{VBE_MIN}-{VBE_MAX}")
    if not (VCE_MIN <= vce1 <= VCE_MAX):
        flags.append(f"vce1={vce1:.4f}_outside_{VCE_MIN}-{VCE_MAX}")
    # Model-card current limit: ic < 0.003 * Nx (A) per DEVICE instance.
    ic_per_device = ic1 / int(m1)
    if ic_per_device >= 0.003 * int(nx1):
        flags.append(f"ic_per_device={ic_per_device:.4g}_over_0.003*Nx")

    return {
        "point_id": pid, "variant": vid, "family": family, "topology": kind,
        "nx1": nx1, "m1": m1, "nx2": nx2, "m2": m2,
        "emitter_units_stage1": area_i,
        "emitter_area_um2_stage1": round(area_i * AE_UNIT_UM2, 6),
        "xmis_w_um": wis,
        "corner_label": corner, "temp_c": temp, "vdd_v": vdd,
        "ic1_a": f"{ic1:.6e}", "ic2_a": f"{ic2:.6e}", "ib1_a": f"{ib1:.6e}",
        "jc1_ma_um2": round(jc, 4),
        "vce1_v": round(vce1, 4), "vce2_v": round(vce2, 4),
        "vbe1_v": round(vbe1, 4),
        "idd_a": f"{idd:.6e}", "pdc_w": f"{pdc:.6e}",
        "pdc_violates_10mw": int(pdc >= 10e-3),
        "ic1_violates_4p5ma": int(ic1 >= 4.5e-3),
        "s11_db_worst": round(max(s11_db), 4),
        "s21_db_min": round(min(s21_db), 4),
        "s21_db_max": round(max(s21_db), 4),
        "s12_db_max": round(max(s12_db), 4),
        "s22_db_worst": round(max(s22_db), 4),
        "gain_in_match_basis_db_min": round(min(gin_basis), 4),
        "ga_max_ideal_db_min": round(min(gmax_ideal), 4),
        "ga_max_q10_db_min": round(min(gmax_q10), 4),
        "nf_sp_db_at_band_lo": round(nf_sp[0], 4),
        "nfmin_sp_db_at_band_lo": round(nfmin_sp[0], 4),
        "nfmin290_db_at_band_lo": round(nfmin290[0], 4),
        "nfmin290_db_worst": round(max(nfmin290), 4),
        "nfmin_reref_delta_db": round(nfmin290[0] - nfmin_sp[0], 4),
        "nf290_db_at_band_lo": round(nf["lo"][0], 4),
        "nf290_db_worst": round(max(v[0] for v in nf.values()), 4),
        "nf30015_db_at_band_lo": round(nf["lo"][1], 4),
        "gain_ac_db_at_band_lo": round(gain["lo"], 4),
        "k_inband_min": round(min(r["k"] for r in ib), 8),
        "mu_inband_min": round(min(r["mu"] for r in ib), 8),
        # Counted on the UNROUNDED sweep values -- see docstring note 3.
        # These, not the rounded mu_*_min columns, are what the roll-up's
        # violation counts and every mu claim in the record are built on.
        "n_inband_pts_mu_lt_1": sum(1 for r in ib if r["mu"] < 1.0),
        "n_inband_pts": len(ib),
        "mag_delta_inband_max": round(max(r["mag_delta"] for r in ib), 6),
        "k_broadband_min": round(min(r["k"] for r in sb), 8),
        "mu_broadband_min": round(min(r["mu"] for r in sb), 8),
        "f_at_mu_broadband_min_hz": f"{min(sb, key=lambda r: r['mu'])['freq_hz']:.6e}",
        "n_broadband_pts_mu_lt_1": sum(1 for r in sb if r["mu"] < 1.0),
        "n_broadband_pts": len(sb),
        "s11_mag_broadband_max": round(max(r["s11_mag"] for r in sb), 6),
        "s22_mag_broadband_max": round(max(r["s22_mag"] for r in sb), 6),
        "model_card_flags": ";".join(flags) if flags else "in_box",
    }


def reduce_points(manifest, corners: Path, inband_grid, stab_grid):
    """Reduce every manifest point; return (rows, failed).

    `failed` is a list of (point_id, reason) in manifest order. A point that
    is not evidence is skipped, never silently reduced -- the caller decides
    whether a partial campaign may publish (`--require-all-points`).
    """
    rows, failed = [], []
    for fields in manifest_points(manifest):
        try:
            rows.append(point_row(fields, corners, inband_grid, stab_grid))
        except PointError as exc:
            failed.append((fields[0], str(exc)))
    return rows, failed


# --- Control-variant regression check ------------------------------------

def control_check(rows, reference_summary):
    """Compare the control variant's cells against the committed reference.

    Returns (note, drifted). `drifted` True means this run must NOT publish:
    `s_ctrl_a8` is the committed `design/netlist/lna.spice`, so a relative
    difference above CONTROL_RTOL on any compared column means this bench no
    longer reproduces the record it claims to extend.
    """
    if not reference_summary:
        return "not checked (no --reference-summary given)", False
    ref = {}
    with open(reference_summary) as fh:
        for r in csv.DictReader(fh):
            ref[(r["corner_label"], r["temp_c"], r["vdd_v"])] = r
    worst, worst_key, n = 0.0, None, 0
    for r in rows:
        if r["variant"] != CONTROL_VARIANT:
            continue
        key = (r["corner_label"], r["temp_c"], r["vdd_v"])
        if key not in ref:
            continue
        n += 1
        for col in CONTROL_COLS:
            a, b = float(r[col]), float(ref[key][col])
            rel = abs(a - b) / max(abs(b), 1e-30)
            if rel > worst:
                worst, worst_key = rel, (key, col, a, b)
    if not n:
        return "control variant not present in this run", False
    note = (
        f"{n} control cells compared against "
        f"{Path(reference_summary).name}; worst relative "
        f"difference {worst:.3e}"
        + (f" on {worst_key[1]} at {worst_key[0]} "
           f"({worst_key[2]} vs {worst_key[3]})" if worst_key else ""))
    return note, worst > CONTROL_RTOL


# --- Published artifacts -------------------------------------------------

def write_point_csv(path, rows) -> None:
    """Stage the per-point CSV; the row dicts' own key order is the header."""
    with open(path, "x", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)


def group_variants(rows):
    """Group rows by variant, preserving first-seen (manifest) order."""
    variants = {}
    for r in rows:
        variants.setdefault(r["variant"], []).append(r)
    return variants


def rollup(vrows) -> dict:
    """One variant's roll-up: the record's headline table row."""
    return {
        "family": vrows[0]["family"],
        "topology": vrows[0]["topology"],
        "geom": (f"{vrows[0]['nx1']}x{vrows[0]['m1']}"
                 + ("" if vrows[0]["topology"] == "1stage"
                    else f" + {vrows[0]['nx2']}x{vrows[0]['m2']}")),
        "xmis": vrows[0]["xmis_w_um"],
        "n": len(vrows),
        "jc_lo": min(r["jc1_ma_um2"] for r in vrows),
        "jc_hi": max(r["jc1_ma_um2"] for r in vrows),
        "ic_lo": min(float(r["ic1_a"]) for r in vrows) * 1e3,
        "ic_hi": max(float(r["ic1_a"]) for r in vrows) * 1e3,
        "pdc_lo": min(float(r["pdc_w"]) for r in vrows) * 1e3,
        "pdc_hi": max(float(r["pdc_w"]) for r in vrows) * 1e3,
        "pdc_viol": sum(r["pdc_violates_10mw"] for r in vrows),
        "ic_viol": sum(r["ic1_violates_4p5ma"] for r in vrows),
        "s21_lo": min(r["s21_db_min"] for r in vrows),
        "gin_lo": min(r["gain_in_match_basis_db_min"] for r in vrows),
        "gq10_lo": min(r["ga_max_q10_db_min"] for r in vrows),
        "gq10_viol": sum(1 for r in vrows if r["ga_max_q10_db_min"] <= 15.0),
        "nfmin290_lo": min(r["nfmin290_db_at_band_lo"] for r in vrows),
        "nfmin290_hi": max(r["nfmin290_db_worst"] for r in vrows),
        "nfmin290_viol": sum(1 for r in vrows if r["nfmin290_db_worst"] >= 1.5),
        "nf290_hi": max(r["nf290_db_worst"] for r in vrows),
        "mu_ib_lo": min(r["mu_inband_min"] for r in vrows),
        "mu_bb_lo": min(r["mu_broadband_min"] for r in vrows),
        # From the raw per-point sub-unity counts, NOT from the rounded
        # mu_*_min columns above (docstring note 3): a cell counts as
        # violating if ANY swept frequency has mu < 1.
        "mu_ib_viol": sum(1 for r in vrows if r["n_inband_pts_mu_lt_1"] > 0),
        "mu_bb_viol": sum(1 for r in vrows if r["n_broadband_pts_mu_lt_1"] > 0),
        "mu_bb_pts_lt_1": sum(r["n_broadband_pts_mu_lt_1"] for r in vrows),
        "mu_bb_pts": sum(r["n_broadband_pts"] for r in vrows),
        "oob": sum(1 for r in vrows if r["model_card_flags"] != "in_box"),
    }


SUMMARY_KEYS = ["variant", "family", "topology", "geom", "xmis", "n", "jc_lo",
                "jc_hi", "ic_lo", "ic_hi", "pdc_lo", "pdc_hi", "pdc_viol",
                "ic_viol", "s21_lo", "gin_lo", "gq10_lo", "gq10_viol",
                "nfmin290_lo", "nfmin290_hi", "nfmin290_viol", "nf290_hi",
                "mu_ib_lo", "mu_bb_lo", "mu_ib_viol", "mu_bb_viol",
                "mu_bb_pts_lt_1", "mu_bb_pts", "oob"]


def write_variant_summary(path, variants) -> None:
    """Stage the per-variant roll-up CSV."""
    with open(path, "x", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=SUMMARY_KEYS)
        w.writeheader()
        for vid, vrows in variants.items():
            rec = rollup(vrows)
            rec["variant"] = vid
            w.writerow({k: rec[k] for k in SUMMARY_KEYS})


def markdown(args, rows, variants, failed, control_note):
    """Build the record's markdown body as a list of lines.

    Carries the bench definitions every number in the record is read against,
    including the explicit warning to read the `mu viol` columns rather than
    the rounded `mu min` ones (docstring note 3).
    """
    md = [f"# Record {args.record_id}", ""]
    md += [
        "- **Experiment**: lna-core-envelope (issue #52) -- the achievable",
        "  (gain, NF, P_dc) envelope of the `npn13G2` cascode core, measured",
        "  by re-running `sim/lna-characterization/`'s own sp/NF/stability",
        "  bench over DUT VARIANTS across the same 45-cell PVT grid.",
        "- **Claim**: per-variant, per-cell 50 Ohm-port S-parameters, noise",
        "  figure (at the RATIFIED T0 = 290 K reference as well as raw), mu/k",
        "  stability and DC bias. **Not** a conformance claim for any variant:",
        "  every variant except `s_ctrl_a8` is a PROBE, not a design, and",
        "  nothing under `design/` changes because of this record.",
        f"- **Control**: `s_ctrl_a8` is the committed `design/netlist/lna.spice`",
        f"  (sha256 `{args.design_netlist_sha}`). Regression check: {control_note}.",
        "- **Bench definitions**: see `README.md`. Short summary: 50 Ohm",
        "  reference impedance at both ports (`sp` port sources); NF from an",
        "  input-referred `.noise` measurement with NOISELESS Rs/RL and the",
        "  source term re-introduced analytically at T0 = 290 K and 300.15 K;",
        "  ngspice's own two-port `sp` NF/NFmin reported raw AND re-referenced",
        "  to T0 = 290 K (`nfmin290_db_*`), because the raw `sp` figure is",
        "  referenced to the ANALYSIS temperature.",
        (f"- **PDK**: `{args.pdk_root}` -- verified installed release "
         f"`{args.pdk_release}`; model hashes in `{args.pdk_provenance}`."
         if args.pdk_release else
         f"- **PDK**: `{args.pdk_root}` -- identity not verified by this "
         "invocation (no --pdk-release given)."),
        f"- **ngspice**: `{args.ngspice_version}`, `.options gmin=1e-10` in",
        "  every deck (identical to the lna-characterization bench).",
        "- **Ideal-passive assumption**: `Le`/`Lc`/`Cc` are ideal infinite-Q",
        "  SPICE primitives -- SG13G2 ships no simulatable inductor model",
        "  (issue #5, upstream `2AMLogic/klayout-tools#1519`). Every gain",
        "  number here is the MOST OPTIMISTIC case and every stability number",
        "  the LEAST-DAMPED case. The `ga_max_q10_db_min` column is the one",
        "  finite-Q figure, and it is ARITHMETIC on the measured",
        "  S-parameters (a shunt `Q*omega*Lc` loss at the output node), not a",
        "  passive model.",
        "- **PVT grid**: corner_label {typ,bcs,wcs,sf,fs} x temp {-40,27,125} C",
        "  x VDD {1.62,1.80,1.98} V = 45 cells per variant. `sf`/`fs` are",
        "  documented DUPLICATES of `typ` (`cornerHBT.lib` ships three real HBT",
        "  sections -- see #41), so the HBT axis is three real corners, not five.",
        f"- **Result**: {len(rows)} points across {len(variants)} variants"
        + (f"; {len(failed)} failed" if failed else "; no failed points") + ".",
        "",
        "## Per-variant roll-up (worst cell of 45 unless stated)",
        "",
        "Bars quoted against `spec/target-spec.md`'s RATIFIED rows: Gain > 15 dB,",
        "NF < 1.5 dB at T0 = 290 K, P_dc < 10 mW, mu > 1 over 10 MHz-30 GHz.",
        "",
        "**Read the `mu viol` columns, not the `mu min` ones, for pass/fail.**",
        "The minima are rounded to 6 decimals for display and mu sits within",
        "parts-per-billion of 1 out of band on this topology, so a printed",
        "`1.000000` does NOT mean the cell held mu >= 1 -- the violation counts",
        "are computed from the unrounded sweep points (a cell counts as",
        "violating if ANY of its 140 broadband / 11 in-band frequencies has",
        "mu < 1). Same trap `spec/target-spec.md`'s S22 row records for",
        "`s22_mag_broadband_max` on this bench.",
        "",
        "| variant | geom (Nx x m) | XMis | I_C1 (mA) | J_C (mA/um^2) | P_dc (mW) | P_dc viol | S21 min (dB) | G_in-match (dB) | G_A@Q=10 (dB) | NFmin@290 (dB) | NF290 worst | mu in-band min | mu in-band viol | mu 10M-30G min | mu 10M-30G viol | sub-unity mu pts | out-of-box cells |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for vid, vrows in variants.items():
        r = rollup(vrows)
        md.append(
            f"| `{vid}` | {r['geom']} | {r['xmis']}u | {r['ic_lo']:.3f}-{r['ic_hi']:.3f} "
            f"| {r['jc_lo']:.2f}-{r['jc_hi']:.2f} | {r['pdc_lo']:.2f}-{r['pdc_hi']:.2f} "
            f"| {r['pdc_viol']}/{r['n']} | {r['s21_lo']:.2f} | {r['gin_lo']:.2f} "
            f"| {r['gq10_lo']:.2f} | {r['nfmin290_lo']:.3f}-{r['nfmin290_hi']:.3f} "
            f"| {r['nf290_hi']:.3f} | {r['mu_ib_lo']:.6f} | {r['mu_ib_viol']}/{r['n']} "
            f"| {r['mu_bb_lo']:.6f} | {r['mu_bb_viol']}/{r['n']} "
            f"| {r['mu_bb_pts_lt_1']}/{r['mu_bb_pts']} "
            f"| {r['oob']}/{r['n']} |")
    md += [
        "",
        "## Links",
        "",
        "- Template: `testbench/tb_core_envelope.spice.tmpl`",
        "- Two-stage probe DUT: `dut/lna_2stage.spice.tmpl`",
        "- Runner: `run_core_envelope.sh` (serial, one ngspice at a time)",
        "- Parser: `parse_core_envelope.py`",
        f"- Per-point generated netlists: `netlist-snapshots/{args.record_id}/`",
        f"- Per-point raw ngspice logs and wrdata tables: `corners/{args.record_id}/`",
        f"- Per-point CSV: `records/{args.record_id}.csv`",
        f"- Per-variant roll-up CSV: `records/{args.record_id}-variant-summary.csv`",
    ]
    if failed:
        md += ["", "## Failed points", ""]
        md += [f"- `{p}`: {why}" for p, why in failed]
    return md


def main() -> int:
    ap = build_arg_parser()
    args = ap.parse_args()
    inband_grid, stab_grid = declared_grids(ap, args)

    corners = Path(args.corners_dir)
    records = Path(args.records_dir)

    # Exclusive publication (#126): refuse before reducing anything.
    final_names = published_names(args.record_id)
    if refuse_existing_publication(records, final_names):
        return 4
    stage = stage_paths(records, final_names)

    rows, failed = reduce_points(args.manifest, corners, inband_grid, stab_grid)

    for p, why in failed:
        print(f"parse_core_envelope.py: failed point {p}: {why}", file=sys.stderr)
    if not rows:
        print("parse_core_envelope.py: no parsable points", file=sys.stderr)
        return 1
    if failed and args.require_all_points:
        # Gate before any staging/publication so an incomplete campaign stays
        # resumable (#128): nothing is written under records/.
        print(f"parse_core_envelope.py: --require-all-points: {len(failed)} of "
              f"{len(failed) + len(rows)} points failed; nothing published",
              file=sys.stderr)
        return 5

    control_note, drifted = control_check(rows, args.reference_summary)
    if drifted:
        print("parse_core_envelope.py: CONTROL VARIANT DRIFTED from "
              f"the committed reference record -- {control_note}",
              file=sys.stderr)
        return 2

    csv_path = records / f"{args.record_id}.csv"
    write_point_csv(stage[csv_path.name], rows)

    variants = group_variants(rows)
    summary_path = records / f"{args.record_id}-variant-summary.csv"
    write_variant_summary(stage[summary_path.name], variants)

    md = markdown(args, rows, variants, failed, control_note)
    with open(stage[f"{args.record_id}.md"], "x") as fh:
        fh.write("\n".join(md) + "\n")
    if not publish(records, final_names, stage):
        return 4

    print(f"parse_core_envelope.py: {len(rows)} points -> {csv_path.name}")
    print(f"parse_core_envelope.py: control check -- {control_note}")
    if failed:
        print(f"parse_core_envelope.py: {len(failed)} failed points", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
