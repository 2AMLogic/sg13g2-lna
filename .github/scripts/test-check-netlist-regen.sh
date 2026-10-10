#!/usr/bin/env bash
# Self-test for check-netlist-regen: prove the gate can fail, and fails for the
# right reason (issue #138). Every case runs on a throwaway copy of the repo
# inputs; nothing under the checkout is written.
#
# Cases using a stub xschem (need no real xschem / PDK beyond a pinned-version
# PDK marker, which the test fabricates):
#   S1. missing xschem                         -> exit 3 (tool setup)
#   S2. xschem exits non-zero                  -> exit 4 (netlisting)
#   S3. xschem exits 0 but writes no netlist   -> exit 4
#   S4. xschem exits 0 with an empty netlist   -> exit 4
#   S5. xschem reports an error on stderr      -> exit 4
#   S6. PDK marker version != sim/pdk.json pin -> exit 3
#   S7. PDK symbol library missing             -> exit 3
# Cases using the real xschem + provisioned PDK:
#   R1. unchanged schematic                    -> 0
#   R2. checkout moved to another path         -> 0 (sch_path header ignored)
#   R3. wiring-only schematic mutation         -> 1, and the inventory
#       check (check-netlist-freshness) still PASSES on it
#   R4. committed netlist: two interface pins swapped      -> 1
#   R5. committed netlist: one device connection changed   -> 1
#   R6. xschem with a PDK lacking the symbol lib           -> not 0 (3 or 4)
#
# Usage: test-check-netlist-regen.sh [--require-tools]
#   Without the flag the R-cases print SKIP when xschem or the PDK is absent
#   (local runs). CI passes --require-tools: absent tools then FAIL the test.
set -u
HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$HERE/../.." && pwd)"
CHECK="$HERE/check-netlist-regen"
INV="$HERE/check-netlist-freshness"
require=0; [ "${1:-}" = "--require-tools" ] && require=1
TMP="$(mktemp -d)"; trap 'rm -rf "$TMP"' EXIT
pass=0; fail=0; skip=0
ok() { echo "PASS: $1"; pass=$((pass+1)); }
bad() { echo "FAIL: $1"; fail=$((fail+1)); }

# mk <name>: copy the check inputs into $TMP/<name>.
mk() { d="$TMP/$1"; mkdir -p "$d/design/netlist" "$d/sim"
  cp "$ROOT/design/lna.sch" "$ROOT/design/lna.sym" "$ROOT/design/xschemrc" "$d/design/"
  cp "$ROOT/design/netlist/lna.spice" "$d/design/netlist/"; cp "$ROOT/sim/pdk.json" "$d/sim/"; }
# expect <label> <want-exit> <root> [extra check args...]
expect() { local label="$1" want="$2" r="$3"; shift 3
  python3 -I "$CHECK" --root "$r" "$@" >"$TMP/out" 2>&1; got=$?
  if [ "$got" -eq "$want" ]; then ok "$label"; else bad "$label (got $got, wanted $want)"; sed 's/^/    /' "$TMP/out"; fi; }

pin="$(python3 -I -c 'import json,sys;print(json.load(open(sys.argv[1]))["release_tag"].lstrip("v"))' "$ROOT/sim/pdk.json")"

# Fake PDK tree (marker + the symbols lna.sch uses) for the stub cases.
FP="$TMP/fakepdk"; mkdir -p "$FP/ihp-sg13g2/libs.tech/xschem/sg13g2_pr"
echo "$pin" > "$FP/ihp-sg13g2/.fetched-version"
echo "# stub" > "$FP/ihp-sg13g2/libs.tech/xschem/xschemrc"
grep -o '^C {sg13g2_pr/[^}]*}' "$ROOT/design/lna.sch" | sed 's/^C {//; s/}$//' | sort -u |
  while read -r s; do : > "$FP/ihp-sg13g2/libs.tech/xschem/$s"; done

# Stub xschem: --version reports the pinned version; netlisting behaviour is
# selected by $STUB_MODE.
STUB="$TMP/xschem-stub"
cat > "$STUB" <<'STUBEOF'
#!/usr/bin/env bash
if [ "${1:-}" = "--version" ]; then echo "XSCHEM V3.4.4"; exit 0; fi
case "$STUB_MODE" in
  fail)     echo "boom" >&2; exit 1 ;;
  nooutput) exit 0 ;;
  empty)    mkdir -p netlist; : > netlist/lna.spice; exit 0 ;;
  stderr)   mkdir -p netlist; cp "$STUB_GOOD" netlist/lna.spice
            echo "xschemrc: /x/libs.tech/xschem/xschemrc not found; symbols unavailable." >&2; exit 0 ;;
esac
STUBEOF
chmod +x "$STUB"
export STUB_GOOD="$ROOT/design/netlist/lna.spice"

mk s; expect "S1 missing xschem is a tool-setup failure" 3 "$TMP/s" --xschem "$TMP/does-not-exist" --pdk-root "$FP"
for m in fail nooutput empty stderr; do
  STUB_MODE=$m expect "S-$m xschem misbehaviour cannot pass (netlisting failure)" 4 "$TMP/s" --xschem "$STUB" --pdk-root "$FP"
done
mkdir -p "$TMP/oldpdk/ihp-sg13g2/libs.tech/xschem"; cp -r "$FP/ihp-sg13g2/libs.tech" "$TMP/oldpdk/ihp-sg13g2/"
echo "0.0.1" > "$TMP/oldpdk/ihp-sg13g2/.fetched-version"
STUB_MODE=fail expect "S6 PDK release differs from sim/pdk.json pin" 3 "$TMP/s" --xschem "$STUB" --pdk-root "$TMP/oldpdk"
mkdir -p "$TMP/nolib/ihp-sg13g2/libs.tech/xschem"; echo "$pin" > "$TMP/nolib/ihp-sg13g2/.fetched-version"
echo "# stub" > "$TMP/nolib/ihp-sg13g2/libs.tech/xschem/xschemrc"
STUB_MODE=fail expect "S7 PDK symbol library missing" 3 "$TMP/s" --xschem "$STUB" --pdk-root "$TMP/nolib"

# --- real-tool cases
REAL_PDK=""
if command -v xschem >/dev/null 2>&1; then
  for c in "${PDK_ROOT:-}" /usr/share/pdk /usr/local/share/pdk "$HOME/share/pdk" "$HOME/.ciel" "$HOME/.volare"; do
    [ -n "$c" ] && [ -f "$c/ihp-sg13g2/libs.tech/xschem/xschemrc" ] && { REAL_PDK="$c"; break; }
  done
fi
if [ -z "$REAL_PDK" ]; then
  if [ "$require" -eq 1 ]; then bad "xschem and the pinned PDK are required (--require-tools) but unavailable"
  else echo "SKIP: R1-R6 (xschem and/or the SG13G2 PDK not available; CI provisions them)"; skip=1; fi
else
  R=(--pdk-root "$REAL_PDK")
  mk r1; expect "R1 unchanged schematic regenerates a matching netlist" 0 "$TMP/r1" "${R[@]}"

  mkdir -p "$TMP/elsewhere/deeper/checkout"; cp -r "$TMP/r1/." "$TMP/elsewhere/deeper/checkout/"
  expect "R2 different checkout path does not drift via the sch_path header" 0 "$TMP/elsewhere/deeper/checkout" "${R[@]}"

  # R3: swap the lab of two label pins (vb2 <-> casc); no device is added,
  # removed or re-valued.
  mk r3
  sed -i -e 's/{name=l2 lab=vb2}/{name=l2 lab=casc}/' -e 's/{name=l3 lab=casc}/{name=l3 lab=vb2}/' "$TMP/r3/design/lna.sch"
  if cmp -s "$ROOT/design/lna.sch" "$TMP/r3/design/lna.sch"; then bad "R3 mutation did not change the schematic (bug in test)"
  else
    python3 -I "$INV" --root "$TMP/r3" >/dev/null 2>&1; inv=$?
    if [ "$inv" -eq 0 ]; then ok "R3 precondition: inventory check cannot see the wiring-only mutation"
    else bad "R3 precondition: mutation is not wiring-only (inventory check exit $inv)"; fi
    expect "R3 wiring-only schematic mutation is detected by regeneration" 1 "$TMP/r3" "${R[@]}"
  fi

  mk r4   # interface order: swap two .iopin lines
  sed -i -e 's/^\*\.iopin vdd$/*.iopin TMPSWAP/' -e 's/^\*\.iopin vss$/*.iopin vdd/' -e 's/^\*\.iopin TMPSWAP$/*.iopin vss/' "$TMP/r4/design/netlist/lna.spice"
  expect "R4a reordered iopin lines in the committed netlist are detected" 1 "$TMP/r4" "${R[@]}"
  mk r4b  # interface order: swap the .subckt pin list
  sed -i 's/^\*\*\.subckt lna vdd vss rfin rfout$/**.subckt lna vss vdd rfin rfout/' "$TMP/r4b/design/netlist/lna.spice"
  expect "R4b reordered .subckt pins in the committed netlist are detected" 1 "$TMP/r4b" "${R[@]}"
  mk r5   # one connection changed
  sed -i 's/^XQ1 casc b1 e1 vss /XQ1 casc b1 vss vss /' "$TMP/r5/design/netlist/lna.spice"
  expect "R5 changed connection in the committed netlist is detected" 1 "$TMP/r5" "${R[@]}"

  # R6: a PDK whose xschem tree lacks the symbols (marker pinned) must not pass.
  mk r6
  python3 -I "$CHECK" --root "$TMP/r6" --pdk-root "$TMP/nolib" >/dev/null 2>&1; got=$?
  if [ "$got" -eq 3 ] || [ "$got" -eq 4 ]; then ok "R6 missing symbol library cannot pass (exit $got)"; else bad "R6 missing symbol library exit $got"; fi

  # Committed netlist bytes are never touched by the check.
  before="$(sha256sum "$ROOT/design/netlist/lna.spice")"
  python3 -I "$CHECK" "${R[@]}" >/dev/null 2>&1
  [ "$(sha256sum "$ROOT/design/netlist/lna.spice")" = "$before" ] && ok "check leaves committed netlist bytes untouched" || bad "committed netlist modified"
fi

echo "passed=$pass failed=$fail skipped=$skip"
[ "$fail" -eq 0 ]
