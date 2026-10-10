#!/usr/bin/env python3
"""Validate and reduce the lna-bias-pvt DC-op and startup logs (issue #117).

Stdlib-only, no simulator, no PDK. This is the reduction that
run_biasop_sweep.sh used to do in embedded awk, pulled out so it can be
unit-tested and replayed against retained logs. The shell runner keeps the
orchestration and every ngspice call; it hands this tool the corners/
directory it just filled.

Input contract (the `echo` lines of testbench/tb_lna_biasop.spice.tmpl and
tb_lna_startup.spice.tmpl):

    BIASOP ic1 <v> ic2 <v> ic3 <v> ib1 <v> vb1 <v> vbref <v> vce1 <v>
           vce2 <v> vbe1 <v> idd <v> pdc <v> [vbg <v> vl <v> gsvo <v> cb3 <v>]
    STARTUP ic1_end <v> ic1_s2 <v> ic1_s3 <v>

Validation (any failure exits 2 naming the file/key, and NOTHING is written):

  * inventory: exactly the expected op_<label>_<T>c_vdd<V>v.log and
    startup_*.log files exist -- none missing, none unexpected;
  * each log carries exactly one BIASOP (resp. STARTUP) line made of
    key/value pairs, with no repeated key and no odd trailing token;
  * every required key is present and every value is a finite number
    (nan/inf and non-numeric text are malformed, never a zero);
  * the four DR-0003 audit keys (vbg vl gsvo cb3) are all-or-none per point
    and uniform across points; --require-audit insists they are present;
  * every startup cell has its matching op cell in the op inventory, and
    its op I_C1 comes from that validated op row.

A measured bar violation (I_C1 > 4.5 mA, P_dc >= 10 mW, a startup verdict
other than PASS) is a LEGITIMATE result: it is written as `NO` / the
verdict, not rejected. Only malformed evidence is rejected.

Numeric conventions are those of the old awk, so committed CSVs replay
byte-for-byte: op values are copied as the verbatim log tokens, bars compare
numerically (ic1 <= 4.5e-3 inclusive, pdc < 10e-3 strict), startup
ic1_end/ic1_op print as %.6g and the two percentages as %.3f.

Replay a committed record into scratch paths (outputs are created
exclusively, so a landed record can never be overwritten; exit 4 if present):

    sim/lna-bias-pvt/reduce_biasop.py \
        --corners-dir sim/lna-bias-pvt/corners/<id> \
        --summary-csv /tmp/x-summary.csv --startup-csv /tmp/x-startup.csv

Exit codes: 0 ok, 2 malformed/incomplete input, 4 output already exists.
"""
from __future__ import annotations

import argparse
import math
import os
import re
import sys

IC1_LIMIT_A = 4.5e-3
PDC_LIMIT_W = 10e-3
SPREAD_LIMIT_PCT = 2.0
OP_MISMATCH_LIMIT_PCT = 5.0

CORNER_LABELS = ("typ", "bcs", "wcs", "sf", "fs")
TEMPS = ("-40", "27", "125")
VDDS = ("1.62", "1.80", "1.98")
STARTUP_CELLS = (("bcs", "125", "1.98"), ("wcs", "-40", "1.62"),
                 ("typ", "27", "1.80"))
NOMINAL_CELL = ("typ", "27", "1.80")

OP_REQUIRED = ("ic1", "ic2", "ic3", "ib1", "vb1", "vbref", "vce1", "vce2",
               "vbe1", "idd", "pdc")
OP_AUDIT = ("vbg", "vl", "gsvo", "cb3")
STARTUP_REQUIRED = ("ic1_end", "ic1_s2", "ic1_s3")

SUMMARY_HEADER = ("point_id,corner_label,temp_c,vdd_v,ic1_a,ic2_a,ic3_a,"
                  "ib1_a,vb1_v,vbref_v,vce1_v,vce2_v,vbe1_v,idd_a,pdc_w,"
                  "ic1_within_4p5ma,pdc_within_10mw")
STARTUP_HEADER = ("point_id,corner_label,temp_c,vdd_v,ic1_end_a,ic1_op_a,"
                  "end_vs_op_pct,settled_spread_pct,verdict")


class ReductionError(Exception):
    """Malformed or incomplete evidence (never a measured bar violation)."""


def op_id(cell):
    return "op_%s_%sc_vdd%sv" % cell


def startup_id(cell):
    return "startup_%s_%sc_vdd%sv" % cell


def op_cells(smoke=False):
    if smoke:
        return [NOMINAL_CELL]
    return [(l, t, v) for l in CORNER_LABELS for t in TEMPS for v in VDDS]


def startup_cells(smoke=False):
    # The smoke run exercises the nominal cell only; the two extreme startup
    # cells have no op counterpart there, which would be a pair violation.
    return [NOMINAL_CELL] if smoke else list(STARTUP_CELLS)


def parse_kv_line(text, tag, source):
    """Return {key: raw_token} from the single `tag ...` line in text."""
    lines = [ln for ln in text.splitlines() if ln.startswith(tag + " ")]
    if not lines:
        raise ReductionError("%s: no %s line" % (source, tag))
    if len(lines) > 1:
        raise ReductionError("%s: %d %s lines (expected exactly one)"
                             % (source, len(lines), tag))
    tokens = lines[0].split()[1:]
    if len(tokens) % 2:
        raise ReductionError("%s: %s line has an odd token count (key "
                             "without value)" % (source, tag))
    out = {}
    for k, raw in zip(tokens[0::2], tokens[1::2]):
        if k in out:
            raise ReductionError("%s: %s key %r repeated" % (source, tag, k))
        out[k] = raw
    return out


def finite(raw, key, source):
    try:
        val = float(raw)
    except ValueError:
        raise ReductionError("%s: key %r value %r is not a number"
                             % (source, key, raw)) from None
    if not math.isfinite(val):
        raise ReductionError("%s: key %r value %r is not finite"
                             % (source, key, raw))
    return val


def require(kv, keys, tag, source):
    missing = [k for k in keys if k not in kv]
    if missing:
        raise ReductionError("%s: %s line missing required key(s): %s"
                             % (source, tag, ", ".join(missing)))
    return {k: finite(kv[k], k, source) for k in keys}


def read_text(path):
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            return fh.read()
    except OSError as exc:
        raise ReductionError("%s: unreadable (%s)" % (path, exc)) from None


def check_inventory(corners_dir, op_list, su_list):
    try:
        names = set(os.listdir(corners_dir))
    except OSError as exc:
        raise ReductionError("%s: cannot list corners dir (%s)"
                             % (corners_dir, exc)) from None
    want = {op_id(c) + ".log" for c in op_list} | \
           {startup_id(c) + ".log" for c in su_list}
    missing = sorted(want - names)
    if missing:
        raise ReductionError("missing log(s): " + ", ".join(missing))
    extra = sorted(n for n in names - want
                   if re.match(r"(op|startup)_.*\.log$", n))
    if extra:
        raise ReductionError("unexpected log(s) outside the expected "
                             "inventory: " + ", ".join(extra))


def reduce_op(corners_dir, cell, require_audit):
    pid = op_id(cell)
    src = os.path.join(corners_dir, pid + ".log")
    kv = parse_kv_line(read_text(src), "BIASOP", src)
    vals = require(kv, OP_REQUIRED, "BIASOP", src)
    present = [k for k in OP_AUDIT if k in kv]
    if present and len(present) != len(OP_AUDIT):
        raise ReductionError("%s: partial audit keys (have %s, need all of "
                             "%s)" % (src, ",".join(present),
                                      ",".join(OP_AUDIT)))
    if require_audit and not present:
        raise ReductionError("%s: audit keys %s required but absent"
                             % (src, ",".join(OP_AUDIT)))
    audit = {k: finite(kv[k], k, src) for k in present}
    label, temp, vdd = cell
    return {
        "point_id": pid, "label": label, "temp": temp, "vdd": vdd,
        "raw": {k: kv[k] for k in OP_REQUIRED}, "val": vals,
        "audit": audit, "audit_raw": {k: kv[k] for k in present},
        "ic1_ok": "yes" if vals["ic1"] <= IC1_LIMIT_A else "NO",
        "pdc_ok": "yes" if vals["pdc"] < PDC_LIMIT_W else "NO",
    }


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


def reduce_startup(corners_dir, cell, op_rows):
    pid = startup_id(cell)
    src = os.path.join(corners_dir, pid + ".log")
    kv = parse_kv_line(read_text(src), "STARTUP", src)
    v = require(kv, STARTUP_REQUIRED, "STARTUP", src)
    partner = op_id(cell)
    if partner not in op_rows:
        raise ReductionError("%s: no matching op point %s in the inventory"
                             % (src, partner))
    opic = op_rows[partner]["val"]["ic1"]
    spread, dvsop, verdict = startup_verdict(
        v["ic1_end"], v["ic1_s2"], v["ic1_s3"], opic)
    label, temp, vdd = cell
    return {"point_id": pid, "label": label, "temp": temp, "vdd": vdd,
            "end": v["ic1_end"], "opic": opic, "dvsop": dvsop,
            "spread": spread, "verdict": verdict, "partner": partner}


def fmt_g6(x):
    return "%.6g" % x


def summary_text(op_rows, op_list):
    out = [SUMMARY_HEADER]
    for c in op_list:
        r = op_rows[op_id(c)]
        out.append(",".join([r["point_id"], r["label"], r["temp"], r["vdd"]]
                            + [r["raw"][k] for k in OP_REQUIRED]
                            + [r["ic1_ok"], r["pdc_ok"]]))
    return "\n".join(out) + "\n"


def startup_text(su_rows, su_list):
    out = [STARTUP_HEADER]
    for c in su_list:
        r = su_rows[startup_id(c)]
        out.append("%s,%s,%s,%s,%s,%s,%.3f,%.3f,%s" % (
            r["point_id"], r["label"], r["temp"], r["vdd"], fmt_g6(r["end"]),
            fmt_g6(r["opic"]), r["dvsop"], r["spread"], r["verdict"]))
    return "\n".join(out) + "\n"


def facts(op_rows, op_list, su_rows, su_list):
    """Headline numbers the record prose quotes, derived from validated rows
    only (the same quantities the old shell pulled out with awk)."""
    rows = [op_rows[op_id(c)] for c in op_list]
    f = {}
    lo = min(((r['val']['ic1'], r) for r in rows), key=lambda t: t[0])
    plo = min(((r['val']['pdc'], r) for r in rows), key=lambda t: t[0])
    hi = max(((r["val"]["ic1"], r) for r in rows), key=lambda t: t[0])
    phi = max(((r["val"]["pdc"], r) for r in rows), key=lambda t: t[0])
    f["IC1_MIN_CELL"], f["IC1_MIN"] = lo[1]["point_id"], lo[1]["raw"]["ic1"]
    f["IC1_MAX_CELL"], f["IC1_MAX"] = hi[1]["point_id"], hi[1]["raw"]["ic1"]
    f["PDC_MIN_CELL"], f["PDC_MIN"] = plo[1]["point_id"], plo[1]["raw"]["pdc"]
    f["PDC_MAX_CELL"], f["PDC_MAX"] = phi[1]["point_id"], phi[1]["raw"]["pdc"]
    f["N_OP"] = str(len(rows))
    f["N_IC1_OK"] = str(sum(r["ic1_ok"] == "yes" for r in rows))
    f["N_IC1_BAD"] = str(sum(r["ic1_ok"] != "yes" for r in rows))
    f["N_PDC_OK"] = str(sum(r["pdc_ok"] == "yes" for r in rows))
    f["N_PDC_BAD"] = str(sum(r["pdc_ok"] != "yes" for r in rows))
    srows = [su_rows[startup_id(c)] for c in su_list]
    f["N_STARTUP"] = str(len(srows))
    f["N_STARTUP_PASS"] = str(sum(r["verdict"] == "PASS" for r in srows))
    f["STARTUP_VERDICTS"] = " ".join(sorted({r["verdict"] for r in srows}))
    f["STARTUP_ALL_PASS"] = "yes" if all(
        r["verdict"] == "PASS" for r in srows) else "no"
    nom = op_rows.get(op_id(NOMINAL_CELL))
    f["NOMINAL_IC1_A"] = nom["raw"]["ic1"] if nom else ""
    if rows and rows[0]["audit"]:
        f["AUDIT_PRESENT"] = "yes"
        f["SERVO_MAX_ERR_V"] = fmt_g6(max(
            abs(r["audit"]["vl"] - r["audit"]["vbg"]) for r in rows))
        cb3 = [(r["audit"]["cb3"], r["audit_raw"]["cb3"]) for r in rows]
        f["QC_VBE_MIN"] = min(cb3, key=lambda t: t[0])[1]
        f["QC_VBE_MAX"] = max(cb3, key=lambda t: t[0])[1]
    else:
        f["AUDIT_PRESENT"] = "no"
    return f


def reduce_all(corners_dir, smoke=False, require_audit=False):
    """Validate everything and return (summary_text, startup_text, facts).
    Raises ReductionError before any text is produced."""
    op_list, su_list = op_cells(smoke), startup_cells(smoke)
    check_inventory(corners_dir, op_list, su_list)
    op_rows = {}
    for c in op_list:
        op_rows[op_id(c)] = reduce_op(corners_dir, c, require_audit)
    has_audit = {bool(r["audit"]) for r in op_rows.values()}
    if len(has_audit) > 1:
        raise ReductionError("audit keys present at some op points but not "
                             "others")
    su_rows = {}
    for c in su_list:
        su_rows[startup_id(c)] = reduce_startup(corners_dir, c, op_rows)
    return (summary_text(op_rows, op_list), startup_text(su_rows, su_list),
            facts(op_rows, op_list, su_rows, su_list))


def write_exclusive(path, text):
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o666)
    with os.fdopen(fd, "w", encoding="utf-8", newline="") as fh:
        fh.write(text)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--corners-dir", required=True)
    ap.add_argument("--summary-csv", required=True)
    ap.add_argument("--startup-csv", required=True)
    ap.add_argument("--facts", help="write KEY=VALUE headline facts here")
    ap.add_argument("--smoke", action="store_true",
                    help="nominal cell only (BIASOP_SMOKE inventory)")
    ap.add_argument("--require-audit", action="store_true",
                    help="require the DR-0003 audit keys vbg/vl/gsvo/cb3")
    a = ap.parse_args(argv)
    outs = [a.summary_csv, a.startup_csv] + ([a.facts] if a.facts else [])
    for p in outs:
        if os.path.exists(p):
            print("reduce_biasop: refusing to overwrite %s" % p,
                  file=sys.stderr)
            return 4
    try:
        summary, startup, fx = reduce_all(a.corners_dir, a.smoke,
                                          a.require_audit)
    except ReductionError as exc:
        print("reduce_biasop: MALFORMED EVIDENCE: %s" % exc, file=sys.stderr)
        return 2
    write_exclusive(a.summary_csv, summary)
    write_exclusive(a.startup_csv, startup)
    if a.facts:
        write_exclusive(a.facts, "".join("%s=%s\n" % kv for kv in fx.items()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
