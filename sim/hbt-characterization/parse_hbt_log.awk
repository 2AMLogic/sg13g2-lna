# parse_hbt_log.awk -- per-point reduction of one hbt-characterization
# ngspice log (one grid cell) into CSV rows. This is THE production parser:
# run_hbt_sweep.sh invokes it through hbt_parse.sh's hbt_parse_log(), and
# tests/test_parse_hbt_log.py drives the very same function, so the tests
# exercise exactly what the runner publishes (issue #144).
#
# Input: the log's PT/IC/FT/GAIN/NF echo sequence, one bias point per
# 5-line block in that fixed order (see testbench/tb_hbt_sweep.spice.tmpl
# "NOTE ON EXECUTION ORDER"), interleaved with ngspice's own chatter.
#
# Required -v variables: point_id corner section temp nx vce ae iclim
# vbemin vbemax vcemin vcemax. Optional: rejects (path that receives one
# "point_id,vbe,reason" line per block that is NOT published; default
# /dev/stderr).
#
# Output (stdout): one CSV row per accepted block, schema
#   point_id,corner_label,hbt_section,temp_c,nx,vce_v,vbe_v,ic_a,
#   jc_ma_um2,ft_hz,gain_db,nf_db,validity_flags
#
# Every block ends in exactly one of three outcomes:
#
#   * published   -- every token passed the strict numeric grammar below
#                    and is finite and in range;
#   * "diverged"  -- ngspice reported an operating-point failure inside the
#                    block (the documented electrothermal-divergence drop,
#                    see README "Per-point convergence gate"): its echoed
#                    gain/NF may be a stale cross-plot value, so the tokens
#                    are not even looked at. The runner counts these as the
#                    established PARTIAL-cell case;
#   * any other named reason -- a malformed block (malformed_/missing_/
#                    nonfinite_/out_of_range_<key>, extra_tokens_<key>,
#                    unexpected_<key>, orphan_<key>, incomplete_block). The
#                    runner never counts these as converged: the cell is
#                    FAILED with the reasons named.
#
# Numeric grammar (no awk string->number coercion of arbitrary text):
#   [+-]? ( digits [. digits*] | . digits ) ( [eE] [+-]? digits )?
# NaN/Inf spellings are rejected as nonfinite_<key>; a grammatical token
# whose value overflows (|x| > 1e300, which includes exponents past the
# double range that strtod turns into inf) or underflows to zero from a
# nonzero mantissa is rejected as out_of_range_<key>.
#
# fT is the one token with a documented "no value" sentinel: below the
# testbench's 1 nA Ic floor it echoes the literal "FT NA" (NaN accepted as
# the same sentinel), and when h21 never crosses 0 dB in the swept range
# ngspice's measure fails ("ftmeas ... out of interval" / "... failed!")
# and the echo is an empty "FT ". Both publish a blank ft_hz with gain/NF
# kept, exactly as before. An empty FT WITHOUT that measure-failure
# diagnostic in its block is not the benign case and is rejected
# (missing_ft).
#
# POSIX awk only (exercised under gawk, mawk and busybox awk by the tests).

function is_num(s) {
  return s ~ /^[+-]?([0-9]+[.]?[0-9]*|[.][0-9]+)([eE][+-]?[0-9]+)?$/
}

# "" when s is a finite, in-range number; otherwise the rejection reason.
function check_num(s, key,    x, m) {
  if (s == "") return "missing_" key
  if (s ~ /^[+-]?([nN][aA][nN]|[iI][nN][fF]([iI][nN][iI][tT][yY])?)$/) return "nonfinite_" key
  if (!is_num(s)) return "malformed_" key
  x = s + 0
  if (x > 1e300 || x < -1e300) return "out_of_range_" key
  if (x == 0) {
    m = s
    sub(/[eE].*$/, "", m)
    if (m ~ /[1-9]/) return "out_of_range_" key
  }
  return ""
}

function safe(s) {
  gsub(/[^0-9A-Za-z.+-]/, "?", s)
  return s
}

function reject(v, reason) {
  print point_id "," safe(v) "," reason > rejects
}

function add_bad(reason) {
  if (bad == "") bad = reason
}

function flag(f, name) {
  return f (f ? ";" : "") name
}

function close_block(fallback,    reason, r, ftout, icv, jc, flags) {
  reason = ""
  if (diverged) reason = "diverged"
  else if (fallback != "") reason = fallback
  else if (bad != "") reason = bad
  if (reason == "") { r = check_num(vbe, "pt");  if (r != "") reason = r }
  if (reason == "") { r = check_num(ic, "ic");   if (r != "") reason = r }
  if (reason == "") {
    if (ft == "NA" || ft ~ /^[nN][aA][nN]$/) ftout = ""
    else if (ft == "") { ftout = ""; if (!ftfail) reason = "missing_ft" }
    else { r = check_num(ft, "ft"); if (r != "") reason = r; ftout = ft }
  }
  if (reason == "") { r = check_num(gain, "gain"); if (r != "") reason = r }
  if (reason == "") { r = check_num(nf, "nf");     if (r != "") reason = r }

  open = 0
  if (reason != "") { reject(vbe, reason); return }

  icv = ic + 0
  jc = icv * 1000.0 / (nx * ae)
  flags = ""
  if (icv >= (iclim + 0) * nx)          flags = flag(flags, "ic_high")
  if ((vbe + 0) <  (vbemin + 0) - 1e-9) flags = flag(flags, "vbe_low")
  if ((vbe + 0) >  (vbemax + 0) + 1e-9) flags = flag(flags, "vbe_high")
  if ((vce + 0) <  (vcemin + 0) - 1e-9) flags = flag(flags, "vce_low")
  if ((vce + 0) >  (vcemax + 0) + 1e-9) flags = flag(flags, "vce_high")
  printf "%s,%s,%s,%s,%s,%s,%s,%.6e,%.6f,%s,%.6f,%.6f,%s\n", point_id, corner, section, temp, nx, vce, vbe, icv, jc, ftout, gain + 0, nf + 0, flags
}

BEGIN {
  if (rejects == "") rejects = "/dev/stderr"
  open = 0
  last_vbe = ""
  next_of["PT"] = "IC"; next_of["IC"] = "FT"; next_of["FT"] = "GAIN"; next_of["GAIN"] = "NF"
}

# Genuine divergence markers (see run_hbt_sweep.sh / README for why these
# three and not a blanket /Error:/).
/operating point failed|The operating point could not be simulated successfully|Timestep too small/ {
  diverged = 1; next
}

# The benign "h21 never crosses 0 dB" measure failure: licenses an empty FT.
/ftmeas/ && /out of interval|failed/ { ftfail = 1; next }

/^(PT|IC|FT|GAIN|NF)([ \t]|$)/ {
  key = $1
  lkey = tolower(key)
  tok = (NF >= 2) ? $2 : ""

  if (key == "PT") {
    if (open) close_block("incomplete_block")
    open = 1; vbe = tok; last_vbe = tok
    ic = ""; ft = ""; gain = ""; nf = ""
    diverged = 0; ftfail = 0; bad = ""
    if (NF > 2) add_bad("extra_tokens_pt")
    expect = "IC"
    next
  }

  if (!open) { reject(last_vbe, "orphan_" lkey); next }

  if (key != expect) add_bad("unexpected_" lkey)
  if (NF > 2) add_bad("extra_tokens_" lkey)
  if (key == "IC") ic = tok
  else if (key == "FT") ft = tok
  else if (key == "GAIN") gain = tok
  if (key == "NF") { nf = tok; close_block(""); next }
  expect = next_of[key]
  next
}

END {
  if (open) close_block("incomplete_block")
}
