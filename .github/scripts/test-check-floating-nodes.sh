#!/usr/bin/env bash
# Self-test for check-floating-nodes (issue #258).
# Cases:
#   1. committed netlist                         -> passes
#   2. pre-fix netlist fixture (xout floating)   -> FAILS and names xout
#   3. committed netlist with Rbleed deleted     -> FAILS and names xout
#   4. missing netlist                           -> exit 2 (not a pass)
set -u
HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$HERE/../.." && pwd)"
CHECKER="$HERE/check-floating-nodes"
FIX="$HERE/fixtures/lna-floating-xout.spice"
[ -x "$CHECKER" ] || { echo "FAIL: $CHECKER not executable" >&2; exit 1; }
[ -f "$FIX" ] || { echo "FAIL: $FIX missing" >&2; exit 1; }
TMP="$(mktemp -d)"; trap 'rm -rf "$TMP"' EXIT
pass=0; fail=0
run() { # label want-exit netlist [must-name]
  out="$(python3 -I "$CHECKER" --netlist "$3" 2>&1)"; got=$?
  if [ "$got" -ne "$2" ]; then echo "FAIL: $1 (got $got, wanted $2)"; fail=$((fail+1)); return; fi
  if [ -n "${4:-}" ] && ! grep -qw "$4" <<<"$out"; then
    echo "FAIL: $1 (output does not name $4: $out)"; fail=$((fail+1)); return; fi
  echo "PASS: $1"; pass=$((pass+1))
}
run "committed netlist" 0 "$ROOT/design/netlist/lna.spice"
run "pre-fix fixture rejected, names xout" 1 "$FIX" xout
grep -v '^Rbleed ' "$ROOT/design/netlist/lna.spice" > "$TMP/nobleed.spice"
run "Rbleed removed rejected, names xout" 1 "$TMP/nobleed.spice" xout
run "missing netlist is an error" 2 "$TMP/absent.spice"
echo "$pass passed, $fail failed"
[ "$fail" -eq 0 ]
