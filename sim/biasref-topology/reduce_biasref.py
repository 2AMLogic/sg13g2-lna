#!/usr/bin/env python3
"""Validate and reduce the biasref-topology phase logs (issue #149).

Stdlib-only, no simulator, no PDK. This is the five-phase CSV reduction that
run_biasref_sweep.sh used to do in embedded awk, pulled out so it can be
unit-tested and replayed against retained logs. The shell runner keeps the
orchestration and every ngspice call; it hands this tool the corners/
directory it just filled.

Input contract (the `echo` lines of testbench/*.spice.tmpl), one per log:

    MPADIODE veb <v> [id <v>]                           phase A  mpa_*
    BIASREF  iq3 iqa vbref vna vsdb  (key/value pairs)  phase B  core_*
    STARTUP  iq3_end iq3_s2 iq3_s3                      phase C  startup_*
    SERVO    iq3 iv iref vbg vl gsvo vbref cb3 idd      phase D  servo_*
    STARTUP  (as phase C)                               phase E  servo_startup_*

Validation (any failure exits 2 naming the file and key, and NOTHING is
written):

  * inventory: exactly the expected log files for the selected phases exist
    -- none missing, none unexpected;
  * each log carries exactly one result line of the expected tag, made of
    key/value pairs, with no repeated key and no odd trailing token;
  * every required key is present and every value matches a strict finite
    decimal grammar (nan/inf, overflow, trailing junk such as `1garbage`,
    and non-numeric text are malformed, never read as a number or a zero);
  * every startup cell has its matching op cell (core_* for phase C, servo_*
    for phase E) in the validated op rows.

A genuine startup failure (NO-RINGING-FAIL, OP-MISMATCH-FAIL, LATCHED-ZERO)
is a LEGITIMATE result: it is written as the verdict, not rejected. Only
malformed evidence is rejected.

Numeric conventions are those of the old awk: op/mpa values are copied as
the verbatim log tokens; startup iq3_end/iq3_op print as %.6g and the two
percentages as %.3f; thresholds (spread > 2 %, |end vs op| > 5 %, end <= 0)
are unchanged.

--phases stage1 reduces only phases A-C (the PR #38 Stage-1 records, which
have no servo logs); --phases all (default) adds D-E. --smoke selects the
BIASREF_SMOKE inventory (nominal cell only).

Replay a committed record into scratch paths (outputs are created
exclusively, so a landed record can never be overwritten; exit 4 if present):

    sim/biasref-topology/reduce_biasref.py \
        --corners-dir sim/biasref-topology/corners/<id> --phases all \
        --out-dir /tmp/replay --prefix <id>

Exit codes: 0 ok, 2 malformed/incomplete input, 4 output already exists.
"""
from __future__ import annotations

import argparse
import importlib.util
import math
import os
import re
import sys

# Shared helpers, loaded by explicit path so `python3 -I` works (isolated mode
# does not put the script directory on sys.path). Issue #160.
_spec = importlib.util.spec_from_file_location(
    "reducer_common",
    os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir,
                 "tools", "reducer_common.py"))
_rc = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_rc)
ReductionError, parse_kv_line, read_text, write_exclusive = (
    _rc.ReductionError, _rc.parse_kv_line, _rc.read_text, _rc.write_exclusive)

SPREAD_LIMIT_PCT = 2.0
OP_MISMATCH_LIMIT_PCT = 5.0

CORNER_LABELS = ("typ", "bcs", "wcs")
MOS_SECTION_OF = {"typ": "mos_tt", "bcs": "mos_ff", "wcs": "mos_ss"}
TEMPS = ("-40", "27", "125")
VDDS = ("1.62", "1.80", "1.98")
MPA_FEEDS = ("0.52m", "100u", "20u")
STARTUP_CELLS = (("bcs", "125", "1.98"), ("wcs", "-40", "1.62"),
                 ("typ", "27", "1.80"))
SMOKE_CELL = ("typ", "27", "1.80")

STARTUP_KEYS = ("iq3_end", "iq3_s2", "iq3_s3")

# phase -> (csv suffix, header)
HEADERS = {
    "mpa-diode": "point_id,corner_label,temp_c,feed_i,v_eb_v",
    "core-minigrid": ("point_id,corner_label,mos_section,temp_c,vdd_v,iq3_a,"
                      "iqa_a,vbref_v,vna_v,vsdb_v"),
    "core-startup": ("point_id,corner_label,temp_c,vdd_v,iq3_end_a,iq3_op_a,"
                     "end_vs_op_pct,settled_spread_pct,verdict"),
    "servo-minigrid": ("point_id,corner_label,mos_section,temp_c,vdd_v,"
                       "iq3_a,iref_a,iqc_a,vbg_v,vl_v,gsvo_v,vbref_v,cb3_v,"
                       "idd_a"),
    "servo-startup": ("point_id,corner_label,temp_c,vdd_v,iq3_end_a,"
                      "iq3_op_a,end_vs_op_pct,settled_spread_pct,verdict"),
}
STAGE1_PHASES = ("mpa-diode", "core-minigrid", "core-startup")
ALL_PHASES = STAGE1_PHASES + ("servo-minigrid", "servo-startup")

MPA_KEYS = ("veb",)
CORE_KEYS = ("iq3", "iqa", "vbref", "vna", "vsdb")
# CSV column order of the servo grid (log key `iv` is the Qc current iqc_a).
SERVO_KEYS = ("iq3", "iref", "iv", "vbg", "vl", "gsvo", "vbref", "cb3", "idd")

NUMBER_RE = re.compile(r"[+-]?(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?\Z")
LOG_RE = re.compile(r"(mpa|core|startup|servo|servo_startup)_.*\.log\Z")


def mpa_id(label, temp, feed):
    return "mpa_%s_%sc_i%s" % (label, temp, feed)


def core_id(cell):
    return "core_%s_%sc_vdd%sv" % cell


def startup_id(cell):
    return "startup_%s_%sc_vdd%sv" % cell


def servo_id(cell):
    return "servo_%s_%sc_vdd%sv" % cell


def servo_startup_id(cell):
    return "servo_startup_%s_%sc_vdd%sv" % cell


def grids(smoke):
    if smoke:
        return ([SMOKE_CELL[0]], [SMOKE_CELL[1]], [SMOKE_CELL[2]],
                [MPA_FEEDS[0]], [SMOKE_CELL])
    return (list(CORNER_LABELS), list(TEMPS), list(VDDS), list(MPA_FEEDS),
            list(STARTUP_CELLS))


def finite(raw, key, source):
    if not NUMBER_RE.match(raw):
        raise ReductionError("%s: key %r value %r is not a finite decimal "
                             "number" % (source, key, raw))
    val = float(raw)
    if not math.isfinite(val):
        raise ReductionError("%s: key %r value %r overflows (not finite)"
                             % (source, key, raw))
    return val


def require(kv, keys, tag, source):
    missing = [k for k in keys if k not in kv]
    if missing:
        raise ReductionError("%s: %s line missing required key(s): %s"
                             % (source, tag, ", ".join(missing)))
    return {k: finite(kv[k], k, source) for k in keys}


def read_row(corners_dir, pid, tag, keys):
    src = os.path.join(corners_dir, pid + ".log")
    kv = parse_kv_line(read_text(src), tag, src)
    require(kv, keys, tag, src)
    return {k: kv[k] for k in keys}


def expected_ids(phases, smoke):
    labels, temps, vdds, feeds, su_cells = grids(smoke)
    grid = [(l, t, v) for l in labels for t in temps for v in vdds]
    ids = []
    for l in labels:
        for t in temps:
            for f in feeds:
                ids.append(mpa_id(l, t, f))
    ids += [core_id(c) for c in grid]
    ids += [startup_id(c) for c in su_cells]
    if "servo-minigrid" in phases:
        ids += [servo_id(c) for c in grid]
        ids += [servo_startup_id(c) for c in su_cells]
    return ids


def check_inventory(corners_dir, phases, smoke):
    try:
        names = set(os.listdir(corners_dir))
    except OSError as exc:
        raise ReductionError("%s: cannot list corners dir (%s)"
                             % (corners_dir, exc)) from None
    want = {i + ".log" for i in expected_ids(phases, smoke)}
    missing = sorted(want - names)
    if missing:
        raise ReductionError("missing log(s): " + ", ".join(missing))
    extra = sorted(n for n in names - want if LOG_RE.match(n))
    if extra:
        raise ReductionError("unexpected log(s) outside the expected "
                             "inventory: " + ", ".join(extra))


def startup_verdict(end, s2, s3, opic):
    mx, mn = max(end, s2, s3), min(end, s2, s3)
    mean = (end + s2 + s3) / 3.0
    spread = 100.0 * (mx - mn) / mean if mean > 0 else 999
    dvsop = 100.0 * (end - opic) / opic if opic > 0 else 999
    verdict = "PASS"
    if spread > SPREAD_LIMIT_PCT:
        verdict = "NO-RINGING-FAIL"
    if dvsop > OP_MISMATCH_LIMIT_PCT or dvsop < -OP_MISMATCH_LIMIT_PCT:
        verdict = "OP-MISMATCH-FAIL"
    if end <= 0:
        verdict = "LATCHED-ZERO"
    return spread, dvsop, verdict


def startup_rows(corners_dir, su_cells, sid, op_rows, op_idf, op_name):
    rows = []
    for cell in su_cells:
        pid = sid(cell)
        src = os.path.join(corners_dir, pid + ".log")
        kv = parse_kv_line(read_text(src), "STARTUP", src)
        v = require(kv, STARTUP_KEYS, "STARTUP", src)
        partner = op_idf(cell)
        if partner not in op_rows:
            raise ReductionError("%s: no matching %s point %s in the "
                                 "inventory" % (src, op_name, partner))
        opraw = op_rows[partner]["iq3"]
        opic = finite(opraw, "iq3", partner)
        spread, dvsop, verdict = startup_verdict(
            v["iq3_end"], v["iq3_s2"], v["iq3_s3"], opic)
        label, temp, vdd = cell
        rows.append("%s,%s,%s,%s,%.6g,%.6g,%.3f,%.3f,%s" % (
            pid, label, temp, vdd, v["iq3_end"], opic, dvsop, spread,
            verdict))
    return rows


def reduce_all(corners_dir, phases=ALL_PHASES, smoke=False):
    """Validate everything and return {phase: csv_text}. Raises
    ReductionError before any text is produced."""
    check_inventory(corners_dir, phases, smoke)
    labels, temps, vdds, feeds, su_cells = grids(smoke)
    out = {}

    rows = [HEADERS["mpa-diode"]]
    for l in labels:
        for t in temps:
            for f in feeds:
                pid = mpa_id(l, t, f)
                r = read_row(corners_dir, pid, "MPADIODE", MPA_KEYS)
                rows.append(",".join([pid, l, t, f, r["veb"]]))
    out["mpa-diode"] = rows

    core = {}
    rows = [HEADERS["core-minigrid"]]
    for l in labels:
        for t in temps:
            for v in vdds:
                pid = core_id((l, t, v))
                r = read_row(corners_dir, pid, "BIASREF", CORE_KEYS)
                core[pid] = r
                rows.append(",".join([pid, l, MOS_SECTION_OF[l], t, v]
                                     + [r[k] for k in CORE_KEYS]))
    out["core-minigrid"] = rows
    out["core-startup"] = [HEADERS["core-startup"]] + startup_rows(
        corners_dir, su_cells, startup_id, core, core_id, "core")

    if "servo-minigrid" in phases:
        servo = {}
        rows = [HEADERS["servo-minigrid"]]
        for l in labels:
            for t in temps:
                for v in vdds:
                    pid = servo_id((l, t, v))
                    r = read_row(corners_dir, pid, "SERVO", SERVO_KEYS)
                    servo[pid] = r
                    rows.append(",".join([pid, l, MOS_SECTION_OF[l], t, v]
                                         + [r[k] for k in SERVO_KEYS]))
        out["servo-minigrid"] = rows
        out["servo-startup"] = [HEADERS["servo-startup"]] + startup_rows(
            corners_dir, su_cells, servo_startup_id, servo, servo_id, "servo")
    return {k: "\n".join(v) + "\n" for k, v in out.items()}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--corners-dir", required=True)
    ap.add_argument("--out-dir", required=True,
                    help="directory receiving <prefix>-<phase>.csv files")
    ap.add_argument("--prefix", required=True, help="record id prefix")
    ap.add_argument("--phases", choices=("stage1", "all"), default="all")
    ap.add_argument("--smoke", action="store_true",
                    help="nominal cell only (BIASREF_SMOKE inventory)")
    a = ap.parse_args(argv)
    phases = STAGE1_PHASES if a.phases == "stage1" else ALL_PHASES
    paths = {p: os.path.join(a.out_dir, "%s-%s.csv" % (a.prefix, p))
             for p in phases}
    for p in paths.values():
        if os.path.exists(p):
            print("reduce_biasref: refusing to overwrite %s" % p,
                  file=sys.stderr)
            return 4
    try:
        texts = reduce_all(a.corners_dir, phases, a.smoke)
    except ReductionError as exc:
        print("reduce_biasref: MALFORMED EVIDENCE: %s" % exc, file=sys.stderr)
        return 2
    for p in phases:
        write_exclusive(paths[p], texts[p])
    return 0


if __name__ == "__main__":
    sys.exit(main())
