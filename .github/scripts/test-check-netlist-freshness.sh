#!/usr/bin/env bash
# Self-test for check-netlist-freshness: prove the gate can fail (issue #88).
# Cases (each on a throwaway copy of design/):
#   1. pristine copy                       -> passes
#   2. one schematic value mutated         -> FAILS
#   3. one instance renamed in schematic   -> FAILS
#   4. one instance removed from netlist   -> FAILS
#   5. one model param mutated in netlist  -> FAILS
set -u
HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$HERE/../.." && pwd)"
CHECKER="$HERE/check-netlist-freshness"
[ -x "$CHECKER" ] || { echo "FAIL: $CHECKER not executable" >&2; exit 1; }
TMP="$(mktemp -d)"; trap 'rm -rf "$TMP"' EXIT
pass=0; fail=0
mk() { d="$TMP/$1"; mkdir -p "$d/design/netlist"
  cp "$ROOT/design/lna.sch" "$d/design/"; cp "$ROOT/design/netlist/lna.spice" "$d/design/netlist/"; }
# Exit 1 = drift detected; exit 2 (unparsable input) must NOT satisfy "FAILS".
run() { python3 -I "$CHECKER" --root "$3" >/dev/null 2>&1; got=$?
  if [ "$got" -eq "$2" ]; then echo "PASS: $1"; pass=$((pass+1))
  else echo "FAIL: $1 (got $got, wanted $2)"; fail=$((fail+1)); fi; }

mk ok; run "pristine copy" 0 "$TMP/ok"
mk val; sed -i 's/{name=R2b value=11k/{name=R2b value=12k/' "$TMP/val/design/lna.sch"
run "schematic value mutated" 1 "$TMP/val"
mk inst; sed -i 's/{name=Cvdd value=100p/{name=Cvdd2 value=100p/' "$TMP/inst/design/lna.sch"
run "schematic instance renamed" 1 "$TMP/inst"
mk rm; sed -i '/^Cbref /d' "$TMP/rm/design/netlist/lna.spice"
run "netlist instance removed" 1 "$TMP/rm"
mk par; sed -i 's/^XQ1 \(.*\) Nx=8/XQ1 \1 Nx=4/' "$TMP/par/design/netlist/lna.spice"
run "netlist model param mutated" 1 "$TMP/par"

echo "$pass passed, $fail failed"
[ "$fail" -eq 0 ]
