#!/usr/bin/env bash
# PDK-free lifecycle tests for sim/lna-core-envelope/run_core_envelope.sh
# (issue #126). A scratch copy of the experiment tree, a fixture PDK, a stub
# ngspice and a stub parser live in a mktemp dir: no real PDK, simulator or
# PVT grid is used (two cells per record). Counts of simulator invocations
# come from the stub's log.
set -u
HERE="$(cd "$(dirname "$0")" && pwd)"
REPO="$(cd "$HERE/../.." && pwd)"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
pass=0; fail=0
ok() { echo "PASS: $1"; pass=$((pass+1)); }
bad() { echo "FAIL: $1"; fail=$((fail+1)); }

STUBS="$TMP/stubs"; mkdir -p "$STUBS"
cat > "$STUBS/ngspice" <<'STUB'
#!/bin/sh
# Stub: `-v` prints a version line 2; `-b deck` logs the deck, writes the
# wrdata targets and BENCH_COMPLETE. STUB_DIE_AT=N kills the PARENT runner
# (STUB_DIE_SIG, default TERM) during the Nth simulation, before output.
if [ "$1" = "-v" ]; then echo "stub"; echo "ngspice-${STUB_NG_VER:-46} stub"; exit 0; fi
deck="$2"
echo "$(basename "$deck")" >> "$STUB_LOG"
n=$(wc -l < "$STUB_LOG")
if [ -n "${STUB_DIE_AT:-}" ] && [ "$n" -eq "$STUB_DIE_AT" ]; then
  kill -"${STUB_DIE_SIG:-TERM}" "$PPID"; exit 1
fi
[ -n "${STUB_SLEEP:-}" ] && sleep "$STUB_SLEEP"
for f in $(awk '/^wrdata/{print $2}' "$deck"); do echo "1 2 3" > "$f"; done
echo BENCH_COMPLETE
STUB
chmod +x "$STUBS/ngspice"

# mkpdk <root> <version>
mkpdk() {
  local m="$1/ihp-sg13g2/libs.tech/ngspice/models"
  mkdir -p "$m" "$1/ihp-sg13g2/libs.tech/ngspice/osdi"
  printf '.lib cur\n.endl\n' > "$m/cornerHBT.lib"
  echo '* mos' > "$m/cornerMOShv.lib"
  for f in psp103 psp103_nqs mosvar; do echo x > "$1/ihp-sg13g2/libs.tech/ngspice/osdi/$f.osdi"; done
  echo "$2" > "$1/ihp-sg13g2/.fetched-version"
}

# mktree <name>: scratch copy of the runner, its templates and a stub parser.
mktree() {
  local t="$TMP/$1"
  mkdir -p "$t/sim/lna-core-envelope" "$t/design/netlist" "$t/sim/lna-characterization/records"
  cp "$REPO/sim/env.sh" "$REPO/sim/pdk.json" "$t/sim/"
  cp -r "$REPO/sim/tools" "$t/sim/"
  cp -r "$REPO/sim/lna-core-envelope/testbench" "$REPO/sim/lna-core-envelope/dut" "$t/sim/lna-core-envelope/"
  cp "$REPO/sim/lna-core-envelope/run_core_envelope.sh" "$REPO/sim/lna-core-envelope/core_envelope_lifecycle.py" "$t/sim/lna-core-envelope/"
  cp "$REPO/design/netlist/lna.spice" "$t/design/netlist/"
  mkdir -p "$t/pdk"; mkpdk "$t/pdk" 0.3.0
  cat > "$t/sim/lna-core-envelope/parse_core_envelope.py" <<'PY'
import argparse, os, sys
ap = argparse.ArgumentParser()
for a in ("record-id", "corners-dir", "records-dir", "manifest", "design-netlist-sha",
          "ngspice-version", "pdk-root", "pdk-release", "pdk-provenance", "reference-summary", "inband-grid", "stab-grid"):
    ap.add_argument("--" + a)
a = ap.parse_args()
if os.environ.get("STUB_PARSE_FAIL"):
    sys.exit(1)
for n in (a.record_id + ".csv", a.record_id + "-variant-summary.csv", a.record_id + ".md"):
    with open(os.path.join(a.records_dir, n), "x") as fh:
        fh.write("stub %s\n" % open(a.manifest).read().count("\n"))
PY
}

# run <tree> <id> [VAR=val ...]: runs the runner; sets RC; stdout/err in files.
run() {
  local name="$1" t="$TMP/$1" id="$2"; shift 2
  env PATH="$STUBS:$PATH" PDK_ROOT="$t/pdk" STUB_LOG="$TMP/$name.stublog" \
      CORE_ENV_SMOKE=1 CORE_ENV_VARIANTS="s_ctrl_a8 s_fixj_a2" CORE_ENV_RECORD_ID="$id" "$@" \
      bash "$t/sim/lna-core-envelope/run_core_envelope.sh" >"$TMP/out" 2>"$TMP/err"
  RC=$?
}
nsim() { [[ -f "$TMP/$1.stublog" ]] && wc -l < "$TMP/$1.stublog" || echo 0; }
# state <tree>: bytes + mtimes of every file the record lifecycle can touch
state() {
  local t="$TMP/$1/sim/lna-core-envelope"
  ( cd "$t" && find corners netlist-snapshots records -print 2>/dev/null | sort \
      | while read -r p; do if [[ -f "$p" ]]; then echo "$p $(sha256sum < "$p") $(stat -c %Y.%y "$p")"; else echo "$p/"; fi; done )
}
errhas() { grep -q "$1" "$TMP/err"; }

# 1. wrong PDK identity: exit 3 before any allocation or simulation
mktree t1; mkpdk "$TMP/t1/pdk" 0.3.1
run t1 rec1
if [[ $RC -eq 3 ]] && errhas PDK_IDENTITY_MISMATCH && [[ ! -e "$TMP/t1/sim/lna-core-envelope/corners" && ! -e "$TMP/t1/sim/lna-core-envelope/netlist-snapshots" && ! -e "$TMP/t1/sim/lna-core-envelope/records" ]] && [[ "$(nsim t1)" == 0 ]]; then
  ok "wrong PDK identity: exit 3, nothing allocated, no simulator call"; else bad "pdk mismatch rc=$RC"; fi

# 2. fresh run completes, publishes, finalizes, cites provenance
mktree t2
run t2 rec2
L="$TMP/t2/sim/lna-core-envelope"
if [[ $RC -eq 0 && -f "$L/corners/rec2/run-fingerprint.json" && -f "$L/corners/rec2/finalized.json" \
      && -f "$L/records/rec2.csv" && -f "$L/records/rec2.md" && -f "$L/records/rec2-variant-summary.csv" \
      && -f "$L/records/rec2.pdk-provenance.json" && ! -e "$L/corners/.rec2.lock" && "$(nsim t2)" == 2 ]] \
   && grep -q '"installed_release_raw"' "$L/records/rec2.pdk-provenance.json"; then
  ok "fresh run: fingerprint, provenance sidecar, 3 summaries, finalized marker, lock released, 2 sims"
else bad "fresh run rc=$RC: $(cat "$TMP/err")"; fi

# 3. finalized record rejects reuse unchanged
before="$(state t2)"
run t2 rec2
if [[ $RC -eq 4 ]] && errhas CORE_ENV_RECORD_FINALIZED && [[ "$(state t2)" == "$before" && "$(nsim t2)" == 2 ]]; then
  ok "finalized record: rejected, bytes unchanged, no simulation"; else bad "finalized reuse rc=$RC"; fi

# 4. legacy directory (no fingerprint) rejects reuse unchanged
mkdir -p "$L/corners/old1" "$L/netlist-snapshots/old1"
echo data > "$L/corners/old1/x.log"; echo deck > "$L/netlist-snapshots/old1/x.spice"
before="$(state t2)"
run t2 old1
if [[ $RC -eq 4 ]] && errhas CORE_ENV_RECORD_LEGACY && [[ "$(state t2)" == "$before" && "$(nsim t2)" == 2 && ! -e "$L/corners/.old1.lock" ]]; then
  ok "legacy record (no fingerprint): rejected, unchanged"; else bad "legacy rc=$RC"; fi

# 5. interrupted run resumes: completed cell untouched, only the missing cell runs
mktree t5
run t5 rec5 STUB_DIE_AT=2
L5="$TMP/t5/sim/lna-core-envelope"
first="$(ls "$L5"/corners/rec5/*.log | head -1)"; first="$(basename "$first" .log)"
if [[ $RC -eq 143 && ! -e "$L5/corners/.rec5.lock" && ! -e "$L5/records/rec5.csv" && -f "$L5/corners/rec5/run-fingerprint.json" ]]; then
  ok "interrupt (SIGTERM): lock released, nothing published"; else bad "interrupt rc=$RC"; fi
snap_first() { ( cd "$L5" && for f in "netlist-snapshots/rec5/$first.spice" corners/rec5/$first.log corners/rec5/$first.inband.dat corners/rec5/$first.stability.dat; do echo "$f $(sha256sum < "$f") $(stat -c %y "$f")"; done ); }
done_cell="$(grep -l BENCH_COMPLETE "$L5"/corners/rec5/*.log | head -1)"
first="$(basename "$done_cell" .log)"
b="$(snap_first)"; n0="$(nsim t5)"
sleep 1.1  # so a rewrite would show in the mtimes
run t5 rec5
if [[ $RC -eq 0 && "$(snap_first)" == "$b" && "$(( $(nsim t5) - n0 ))" == 1 && -f "$L5/corners/rec5/finalized.json" ]] \
   && ! tail -1 "$TMP/t5.stublog" | grep -q "^$first"; then
  ok "matching resume: completed cell bytes+mtimes untouched, exactly the missing cell simulated, finalized"
else bad "resume rc=$RC n=$(( $(nsim t5) - n0 )): $(cat "$TMP/err")"; fi

# 6. changed inputs reject the interrupted record before any mutation
mutcase() {  # name  setup-cmd (run in the tree)  extra run env...
  local name="$1" mut="$2"; shift 2
  mktree "m_$name"
  run "m_$name" rec6 STUB_DIE_AT=2
  local t="$TMP/m_$name" before; local n0
  n0="$(nsim "m_$name")"
  ( cd "$t" && eval "$mut" )
  before="$(state "m_$name")"   # after the mutation: a tampered record file is the input under test
  run "m_$name" rec6 "$@"
  if [[ $RC -eq 4 ]] && errhas "$EXPECT" && [[ "$(state "m_$name")" == "$before" && "$(nsim "m_$name")" == "$n0" ]] \
     && [[ ! -e "$t/sim/lna-core-envelope/corners/.rec6.lock" ]]; then
    ok "changed $name: rejected ($EXPECT), nothing mutated, no simulation"
  else bad "changed $name rc=$RC: $(cat "$TMP/err")"; fi
}
EXPECT=CORE_ENV_FINGERPRINT_MISMATCH
mutcase dut          'echo "* edit" >> design/netlist/lna.spice'
mutcase template     'echo "* edit" >> sim/lna-core-envelope/testbench/tb_core_envelope.spice.tmpl'
mutcase dut2template 'echo "* edit" >> sim/lna-core-envelope/dut/lna_2stage.spice.tmpl'
mutcase variants     ':' CORE_ENV_VARIANTS="s_ctrl_a8"
mutcase modelhash    'echo "* edit" >> pdk/ihp-sg13g2/libs.tech/ngspice/models/cornerHBT.lib'
mutcase simulator    ':' STUB_NG_VER=47
mutcase smoke        ':' CORE_ENV_SMOKE=
EXPECT=CORE_ENV_DECK_MISMATCH
mutcase tamperdeck   'f="$(grep -l BENCH_COMPLETE sim/lna-core-envelope/corners/rec6/*.log | head -1)"; echo "* edit" >> sim/lna-core-envelope/netlist-snapshots/rec6/"$(basename "$f" .log)".spice'

# 7. exclusive ownership: a held lock rejects and is left intact
mktree t7
mkdir -p "$TMP/t7/sim/lna-core-envelope/corners/.rec7.lock"
printf 'tok\npid=1 host=other\n' > "$TMP/t7/sim/lna-core-envelope/corners/.rec7.lock/owner"
before="$(state t7)"
run t7 rec7
if [[ $RC -eq 4 ]] && errhas CORE_ENV_RECORD_BUSY && [[ "$(cat "$TMP/t7/sim/lna-core-envelope/corners/.rec7.lock/owner")" == $'tok\npid=1 host=other' && "$(state t7)" == "$before" ]] \
   && [[ ! -e "$TMP/t7/sim/lna-core-envelope/corners/rec7" && "$(nsim t7)" == 0 ]]; then
  ok "held lock: loser exits CORE_ENV_RECORD_BUSY, lock and record untouched"; else bad "busy rc=$RC"; fi

# 7b. two real concurrent invocations: exactly one wins
mktree t8
L8="$TMP/t8/sim/lna-core-envelope"
( run t8 rec8 STUB_SLEEP=1; echo "$RC" > "$TMP/rc8a"; cp "$TMP/err" "$TMP/err8a" ) &
sleep 0.4
( env PATH="$STUBS:$PATH" PDK_ROOT="$TMP/t8/pdk" STUB_LOG="$TMP/t8.stublog" CORE_ENV_SMOKE=1 \
    CORE_ENV_VARIANTS="s_ctrl_a8 s_fixj_a2" CORE_ENV_RECORD_ID=rec8 \
    bash "$L8/run_core_envelope.sh" >"$TMP/out8b" 2>"$TMP/err8b"; echo "$?" > "$TMP/rc8b" ) &
wait
if [[ "$(cat "$TMP/rc8a")" == 0 && "$(cat "$TMP/rc8b")" == 4 ]] && grep -q CORE_ENV_RECORD_BUSY "$TMP/err8b" \
   && [[ -f "$L8/corners/rec8/finalized.json" && "$(nsim t8)" == 2 && ! -e "$L8/corners/.rec8.lock" ]]; then
  ok "concurrent invocations: loser rejected BUSY, winner finalized intact (2 sims)"; else bad "concurrent rcs=$(cat "$TMP/rc8a") $(cat "$TMP/rc8b")"; fi

# 8. partial publication (no finalized marker) is rejected unchanged
mktree t9
run t9 rec9 STUB_DIE_AT=2
echo "stub" > "$TMP/t9/sim/lna-core-envelope/records/rec9.csv"
before="$(state t9)"; n0="$(nsim t9)"
run t9 rec9
if [[ $RC -eq 4 ]] && errhas CORE_ENV_RECORD_PARTIAL_PUBLICATION && [[ "$(state t9)" == "$before" && "$(nsim t9)" == "$n0" ]]; then
  ok "partial publication: rejected, unchanged"; else bad "partial rc=$RC"; fi

# 9. parser failure: no finalized marker, record not reusable as fresh
mktree t10
run t10 rec10 STUB_PARSE_FAIL=1
L10="$TMP/t10/sim/lna-core-envelope"
if [[ $RC -ne 0 && ! -e "$L10/corners/rec10/finalized.json" && ! -e "$L10/corners/.rec10.lock" ]]; then
  ok "failed reduction: not finalized, lock released"; else bad "parse-fail rc=$RC"; fi
run t10 rec10
if [[ $RC -eq 0 && -f "$L10/corners/rec10/finalized.json" && "$(nsim t10)" == 2 ]]; then
  ok "retry after failed reduction (nothing published): completed cells reused, then finalized"; else bad "retry rc=$RC"; fi

# 10. SIGKILL leaves a lock; it is never broken automatically
mktree t11
run t11 rec11 STUB_DIE_AT=1 STUB_DIE_SIG=KILL
L11="$TMP/t11/sim/lna-core-envelope"
before="$(state t11)"
if [[ $RC -eq 137 && -d "$L11/corners/.rec11.lock" ]]; then
  run t11 rec11
  if [[ $RC -eq 4 ]] && errhas CORE_ENV_RECORD_BUSY && errhas "pid=" && [[ "$(state t11)" == "$before" ]]; then
    ok "stale lock after SIGKILL: rejected naming the holder, not broken automatically"; else bad "stale rc=$RC"; fi
else bad "kill setup rc=$RC"; fi

echo "== ${pass} passed, ${fail} failed"
[[ $fail -eq 0 ]]
