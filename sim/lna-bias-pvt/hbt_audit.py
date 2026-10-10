#!/usr/bin/env python3
"""DUT-bound HBT model-validity audit for the lna-bias-pvt DC bench (#155).

Stdlib-only, no simulator, no PDK. Two jobs:

  probes  <netlist>   print the ngspice `let`/`echo` lines that measure every
                      npn13G2 instance found IN THAT NETLIST (the one being
                      simulated). The deck template splices them in, so an
                      added/resized/renamed HBT is probed automatically.
  reduce  ...         check an op-log set against the same netlist and write
                      a per-device / per-cell validity table.

Log contract (one extra line per op log, next to BIASOP):

    HBTAUDIT count <n> <inst>_nx <Nx> <inst>_ic <A> <inst>_vbe <V>
             <inst>_vce <V> ...        (<inst> = lowercase instance name)

Evidence classes, kept separate (never merged into one verdict):

  * MALFORMED  (exit 2, nothing written): an expected instance/probe is
    missing, duplicated, non-finite, an unexpected instance appears, the
    logged Nx or count disagrees with the netlist. Never a result.
  * OUT-OF-RANGE: a finite measurement outside the model validity box. This
    IS a result and is written, with the offending quantities named.
  * UNASSESSED: junction temperature. npn13G2 is a four-terminal VBIC
    instance with no thermal node, so no T_j / self-heating observable is
    exposed. The audit reports `tj_status=UNASSESSED`; ambient temperature
    is a different statement (`ambient_in_model_t_range`) and is never
    promoted to a junction-temperature verdict.

Model validity box (source: header of sg13g2_hbt_mod.lib in the pinned
IHP-Open-PDK, "Valid range for model"): ic < 0.003*Nx A (STRICT), vbe
0.65..0.96 V, vce 0.4..2.0 V (both INCLUSIVE), Temp -40..+125 C, Nx 1..10.
The same header lists "Maximum collector-to-emitter voltage: 1.6" as a
separate datum; it is reported as an informational column
(`vce_above_model_header_max`), is NOT a breakdown/stress rating, is not the
2.0 V upper bound of the validity box, and does not enter the validity
status. Current/power bars (4.5 mA, 10 mW) and spec rows stay in
reduce_biasop.py; they are not audited here.

Old records (no HBTAUDIT line) are reported by `legacy` as INCOMPLETE with
the unmeasured observables named; nothing is fabricated.
"""
from __future__ import annotations

import argparse
import importlib.util
import math
import os
import re
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_rc = _load("reducer_common", os.path.join(_HERE, os.pardir, "tools",
                                           "reducer_common.py"))
ReductionError, parse_kv_line, read_text, write_exclusive = (
    _rc.ReductionError, _rc.parse_kv_line, _rc.read_text, _rc.write_exclusive)

# --- source-pinned model validity box (sg13g2_hbt_mod.lib header) ---------
IC_PER_NX_A = 3.0e-3          # ic < 0.003*Nx (strict)
VBE_RANGE_V = (0.65, 0.96)    # inclusive
VCE_RANGE_V = (0.4, 2.0)      # inclusive
TEMP_RANGE_C = (-40.0, 125.0)  # inclusive, AMBIENT here
NX_RANGE = (1, 10)
VCE_HEADER_MAX_V = 1.6        # header datum, informational only
HBT_MODEL = "npn13g2"

OBSERVABLES = ("ic", "vbe", "vce")

CSV_HEADER = ("point_id,corner_label,temp_c,vdd_v,instance,nx,ic_a,"
              "ic_limit_a,vbe_v,vce_v,ic_in_range,vbe_in_range,"
              "vce_in_range,model_validity,out_of_range,"
              "vce_above_model_header_max,ambient_in_model_t_range,"
              "tj_status")


# --- netlist inventory -----------------------------------------------------
def _logical_lines(text):
    out = []
    for ln in text.splitlines():
        if ln.startswith("+") and out:
            out[-1] += " " + ln[1:]
        else:
            out.append(ln)
    return out


def parse_nx(tokens, source):
    for t in tokens:
        m = re.match(r"(?i)nx=(.+)$", t)
        if m:
            try:
                v = float(m.group(1))
            except ValueError:
                raise ReductionError("%s: Nx=%r is not a number"
                                     % (source, m.group(1))) from None
            if not math.isfinite(v) or v != int(v):
                raise ReductionError("%s: Nx=%r is not a finite integer"
                                     % (source, m.group(1)))
            return int(v)
    return 1  # model default when Nx is not given


def parse_hbts(netlist_text, source="netlist"):
    """Return {lowercase_inst: {name, c, b, e, s, nx}} for every npn13G2
    instance in the netlist, plus the subckt port list."""
    hbts, ports = {}, None
    for ln in _logical_lines(netlist_text):
        s = ln.strip()
        s = re.sub(r"^\*\*(?=\.subckt)", "", s)
        low = s.lower()
        if low.startswith(".subckt") and ports is None:
            ports = [t.lower() for t in s.split()[2:] if "=" not in t]
            continue
        if not s or s[0] in "*;.+":
            continue
        tok = s.split()
        if tok[0][0].lower() != "x":
            continue
        plain = [t for t in tok[1:] if "=" not in t]
        if len(plain) < 5 or plain[4].lower() != HBT_MODEL:
            if len(plain) >= 1 and plain[-1].lower() == HBT_MODEL:
                raise ReductionError(
                    "%s: HBT instance %s has %d nodes, expected 4"
                    % (source, tok[0], len(plain) - 1))
            continue
        name = tok[0].lower()
        if name in hbts:
            raise ReductionError("%s: duplicate HBT instance %s"
                                 % (source, tok[0]))
        nx = parse_nx(tok[1:], source)
        if not NX_RANGE[0] <= nx <= NX_RANGE[1]:
            raise ReductionError("%s: %s Nx=%d outside the model's valid "
                                 "numbers %d..%d" % (source, tok[0], nx,
                                                     *NX_RANGE))
        hbts[name] = {"name": tok[0], "c": plain[0].lower(),
                      "b": plain[1].lower(), "e": plain[2].lower(),
                      "s": plain[3].lower(), "nx": nx}
    if ports is None:
        raise ReductionError("%s: no .subckt line" % source)
    if not hbts:
        raise ReductionError("%s: no npn13G2 instances found (an audit "
                             "with an empty inventory is not coverage)"
                             % source)
    return hbts, ports


def _vref(node, ports):
    if node in ("0", "gnd"):
        return "0"
    return "v(%s)" % (node if node in ports else "xdut." + node)


def probe_lines(hbts, ports):
    """ngspice lines (inside .control, after `op`) measuring every HBT."""
    lines, echo = [], ["HBTAUDIT count %d" % len(hbts)]
    for k, h in sorted(hbts.items()):
        lines.append("let %s_ic = @q.xdut.%s.q%s[ic]" % (k, k, HBT_MODEL))
        lines.append("let %s_vbe = %s - %s" % (
            k, _vref(h["b"], ports), _vref(h["e"], ports)))
        lines.append("let %s_vce = %s - %s" % (
            k, _vref(h["c"], ports), _vref(h["e"], ports)))
        echo.append("%s_nx %d %s_ic $&%s_ic %s_vbe $&%s_vbe %s_vce $&%s_vce"
                    % (k, h["nx"], k, k, k, k, k, k))
    lines.append('echo "%s"' % " ".join(echo))
    return lines


# --- validity classification -----------------------------------------------
def classify(nx, ic, vbe, vce):
    """Per-observable in-range flags and the list of violated quantities.
    Boundary semantics: ic strict (<), vbe/vce inclusive."""
    lim = IC_PER_NX_A * nx
    flags = {"ic": ic < lim,
             "vbe": VBE_RANGE_V[0] <= vbe <= VBE_RANGE_V[1],
             "vce": VCE_RANGE_V[0] <= vce <= VCE_RANGE_V[1]}
    return flags, [k for k in OBSERVABLES if not flags[k]], lim


def ambient_in_range(temp_c):
    return TEMP_RANGE_C[0] <= float(temp_c) <= TEMP_RANGE_C[1]


def _finite(raw, key, source):
    try:
        v = float(raw)
    except ValueError:
        raise ReductionError("%s: key %r value %r is not a number"
                             % (source, key, raw)) from None
    if not math.isfinite(v):
        raise ReductionError("%s: key %r value %r is not finite"
                             % (source, key, raw))
    return v


def audit_log(text, hbts, source="log"):
    """Validate one HBTAUDIT line against the netlist inventory. Returns
    {inst: {nx, ic, vbe, vce, raw}}; raises ReductionError on any defect."""
    kv = parse_kv_line(text, "HBTAUDIT", source)
    if "count" not in kv:
        raise ReductionError("%s: HBTAUDIT line has no count" % source)
    cnt = _finite(kv.pop("count"), "count", source)
    if int(cnt) != len(hbts):
        raise ReductionError("%s: HBTAUDIT count %d != %d HBT(s) in the "
                             "simulated netlist" % (source, int(cnt),
                                                    len(hbts)))
    logged = {m.group(1) for k in kv for m in [re.match(r"(.+)_nx$", k)] if m}
    extra = sorted(logged - set(hbts))
    if extra:
        raise ReductionError("%s: HBTAUDIT instance(s) not in the netlist: "
                             "%s" % (source, ", ".join(extra)))
    out, known = {}, {"count"}
    for inst, h in sorted(hbts.items()):
        need = ["%s_%s" % (inst, s) for s in ("nx",) + OBSERVABLES]
        missing = [k for k in need if k not in kv]
        if missing:
            raise ReductionError("%s: HBTAUDIT missing probe(s): %s"
                                 % (source, ", ".join(missing)))
        nx = _finite(kv[need[0]], need[0], source)
        if nx != h["nx"]:
            raise ReductionError("%s: %s logged Nx=%s but netlist has %d"
                                 % (source, inst, kv[need[0]], h["nx"]))
        vals = {s: _finite(kv["%s_%s" % (inst, s)], "%s_%s" % (inst, s),
                           source) for s in OBSERVABLES}
        out[inst] = {"nx": h["nx"], **vals,
                     "raw": {s: kv["%s_%s" % (inst, s)]
                             for s in OBSERVABLES}}
        known.update(need)
    stray = sorted(set(kv) - known)
    if stray:
        raise ReductionError("%s: unexpected HBTAUDIT key(s): %s"
                             % (source, ", ".join(stray)))
    return out


def _yn(b):
    return "yes" if b else "NO"


def audit_rows(point_id, cell, per_inst, hbts):
    label, temp, vdd = cell
    rows = []
    for inst in sorted(hbts):
        d = per_inst[inst]
        flags, bad, lim = classify(d["nx"], d["ic"], d["vbe"], d["vce"])
        rows.append(",".join([
            point_id, label, temp, vdd, hbts[inst]["name"], str(d["nx"]),
            d["raw"]["ic"], "%.6g" % lim, d["raw"]["vbe"], d["raw"]["vce"],
            _yn(flags["ic"]), _yn(flags["vbe"]), _yn(flags["vce"]),
            "IN-RANGE" if not bad else "OUT-OF-RANGE",
            "+".join(bad) if bad else "none",
            "yes" if d["vce"] > VCE_HEADER_MAX_V else "no",
            _yn(ambient_in_range(temp)), "UNASSESSED"]))
    return rows


def _rb():
    return _load("reduce_biasop", os.path.join(_HERE, "reduce_biasop.py"))


def reduce_dir(corners_dir, netlist_text, smoke=False, source="netlist"):
    """CSV text for a complete op-log set, or ReductionError. Requires an
    HBTAUDIT line in EVERY op log (no partial evidence is tabulated)."""
    rb = _rb()
    hbts, _ = parse_hbts(netlist_text, source)
    rb.check_inventory(corners_dir, rb.op_cells(smoke), rb.startup_cells(smoke))
    out = [CSV_HEADER]
    for cell in rb.op_cells(smoke):
        pid = rb.op_id(cell)
        src = os.path.join(corners_dir, pid + ".log")
        per = audit_log(read_text(src), hbts, src)
        out.extend(audit_rows(pid, cell, per, hbts))
    return "\n".join(out) + "\n"


# --- legacy (pre-#155) coverage -------------------------------------------
# Observables the pre-#155 BIASOP line carries, per instance. Derived from
# the old template: ic1/ic2/ic3, Q1 vbe1+vce1, Q2 vce2, and Q3 (diode-tied,
# emitter on vss) from vbref. Everything else was not measured.
LEGACY_OBSERVED = {"xq1": {"ic", "vbe", "vce"}, "xq2": {"ic", "vce"},
                   "xq3": {"ic", "vbe", "vce"}}


def legacy_coverage(netlist_text, source="netlist"):
    hbts, _ = parse_hbts(netlist_text, source)
    rows = ["instance,nx,ic_measured,vbe_measured,vce_measured,"
            "coverage,unmeasured,tj_status"]
    for inst in sorted(hbts):
        got = LEGACY_OBSERVED.get(inst, set())
        miss = [o for o in OBSERVABLES if o not in got]
        rows.append(",".join([
            hbts[inst]["name"], str(hbts[inst]["nx"]),
            *[_yn(o in got) for o in OBSERVABLES],
            "COMPLETE" if not miss else "INCOMPLETE",
            "+".join(miss) if miss else "none", "UNASSESSED"]))
    return "\n".join(rows) + "\n"


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("probes")
    p.add_argument("netlist")
    r = sub.add_parser("reduce")
    r.add_argument("--netlist", required=True)
    r.add_argument("--corners-dir", required=True)
    r.add_argument("--out-csv", required=True)
    r.add_argument("--smoke", action="store_true")
    g = sub.add_parser("legacy")
    g.add_argument("netlist")
    a = ap.parse_args(argv)
    try:
        text = read_text(a.netlist)
        if a.cmd == "probes":
            hbts, ports = parse_hbts(text, a.netlist)
            print("\n".join(probe_lines(hbts, ports)))
        elif a.cmd == "legacy":
            sys.stdout.write(legacy_coverage(text, a.netlist))
        else:
            if os.path.exists(a.out_csv):
                print("hbt_audit: refusing to overwrite %s" % a.out_csv,
                      file=sys.stderr)
                return 4
            write_exclusive(a.out_csv, reduce_dir(
                a.corners_dir, text, a.smoke, a.netlist))
    except ReductionError as exc:
        print("hbt_audit: MALFORMED EVIDENCE: %s" % exc, file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
