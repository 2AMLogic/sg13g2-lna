#!/usr/bin/env bash
# PDK-free tests for sim_run_deck in sim/env.sh (issue #300).
#
# Everything runs in a mktemp fixture. `ngspice` is stubbed on PATH --
# its behaviour (exit code, BENCH_COMPLETE marker) is driven by SDT_*
# env vars -- so no simulator, PDK, klt or network is used and nothing
# under sim/*/ is written. The deck-budget cases extract the real
# run_deck() wrappers from the le/q runners with awk and eval them in a
# stubbed harness, so the wrappers' own counter/cap logic is what runs.
#
# Cases:
#   1. pass: stub rc 0 + line-start BENCH_COMPLETE -> returns 0, silent
#   2. stub rc != 0 -> returns 1, exact runner-format stderr line
#   3. stub rc 0, marker missing -> returns 1
#   4. marker present but not at line start -> returns 1 (the ^ anchor)
#   5. see-path echoed verbatim (the corners/${RECORD_ID}/... form)
#   6. helper never exits: a failing call with || true under set -e lets
#      the caller continue
#   7. budget cap in the le wrapper (BUDGET=32): fires at N_RUN > 32 with
#      the current message and exits 1 (not a plain return)
#   8. budget cap in the q wrapper (BUDGET=16): fires at N_RUN > 16 likewise
set -u
HERE="$(cd "$(dirname "$0")" && pwd)"
ENV_SH="$(cd "$HERE/.." && pwd)/env.sh"
[ -f "$ENV_SH" ] || { echo "FAIL: $ENV_SH missing" >&2; exit 1; }
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
pass=0; fail=0
ok() { echo "PASS: $1"; pass=$((pass+1)); }
bad() { echo "FAIL: $1"; fail=$((fail+1)); }

STUBS="$TMP/stubs"; mkdir -p "$STUBS"
cat > "$STUBS/ngspice" <<'STUB'
#!/bin/sh
# Stub ngspice: exit code in $SDT_RC (default 0); marker on stdout per
# $SDT_MARKER -- complete (default: line-start BENCH_COMPLETE), anchored
# (BENCH_COMPLETE mid-line), missing (no marker). Arguments are ignored;
# the caller redirects stdout into the deck log.
rc="${SDT_RC:-0}"
case "${SDT_MARKER:-complete}" in
  complete) printf 'run complete\nBENCH_COMPLETE\n' ;;
  anchored) printf 'run complete, BENCH_COMPLETE not anchored\n' ;;
  missing)  printf 'run complete\n' ;;
esac
exit "$rc"
STUB
chmod +x "$STUBS/ngspice"

# fixture: corners/ + snapshots/ + one deck (the stub never reads it)
FIX="$TMP/fix"; mkdir -p "$FIX/corners" "$FIX/snapshots"
printf '* deck\n.end\n' > "$FIX/snapshots/deck1.spice"

# run_helper <see-path>: call sim_run_deck in a fresh subshell with the
# stubbed PATH; SDT_* pick the stub behaviour. Prints "RC <rc>" on stdout;
# the helper's own output lands on the captured stderr.
run_helper() {
  (
    PATH="$STUBS:$PATH"
    # shellcheck disable=SC1090
    source "$ENV_SH" >/dev/null 2>&1
    SIM_SCRIPT_NAME="run_feed_study.sh"
    # shellcheck disable=SC2034  # read by sim_run_deck
    CORNERS_OUT="$FIX/corners"
    # shellcheck disable=SC2034  # read by sim_run_deck
    SNAPSHOTS_OUT="$FIX/snapshots"
    sim_run_deck deck1 "$CORNERS_OUT/deck1.log" "$1"
    echo "RC $?"
  )
}

# 1. pass case: rc 0 + anchored marker -> 0, nothing on stderr
out="$(SDT_RC=0 SDT_MARKER=complete run_helper "$FIX/corners/deck1.log" 2>"$TMP/e1")"
if [ "$out" = "RC 0" ] && [ ! -s "$TMP/e1" ] \
   && grep -q '^BENCH_COMPLETE' "$FIX/corners/deck1.log"; then
  ok "pass case: returns 0, silent on stderr, marker reaches the log"
else bad "pass case (out=[$out] err=[$(cat "$TMP/e1")])"; fi

# 2. rc != 0 -> 1 and the exact runner-format line (FAILED after the stem)
out="$(SDT_RC=3 run_helper "$FIX/corners/deck1.log" 2>"$TMP/e2")"
expect="run_feed_study.sh: deck1 FAILED (rc=3) -- see $FIX/corners/deck1.log"
if [ "$out" = "RC 1" ] && [ "$(cat "$TMP/e2")" = "$expect" ]; then
  ok "rc != 0: returns 1, stderr line byte-identical to the runner format"
else bad "rc != 0 (out=[$out] err=[$(cat "$TMP/e2")])"; fi

# 3. rc 0 but no BENCH_COMPLETE -> 1
out="$(SDT_RC=0 SDT_MARKER=missing run_helper "$FIX/corners/deck1.log" 2>"$TMP/e3")"
expect="run_feed_study.sh: deck1 FAILED (rc=0) -- see $FIX/corners/deck1.log"
if [ "$out" = "RC 1" ] && [ "$(cat "$TMP/e3")" = "$expect" ]; then
  ok "missing marker: returns 1 with rc=0 in the message"
else bad "missing marker (out=[$out] err=[$(cat "$TMP/e3")])"; fi

# 4. marker present but not at line start -> 1 (the ^ anchor is load-bearing)
out="$(SDT_RC=0 SDT_MARKER=anchored run_helper "$FIX/corners/deck1.log" 2>"$TMP/e4")"
if [ "$out" = "RC 1" ] && [ -s "$TMP/e4" ]; then
  ok "unanchored marker: returns 1"
else bad "unanchored marker (out=[$out] err=[$(cat "$TMP/e4")])"; fi

# 5. see-path echoed verbatim: the dc_reference/matching record-relative form
out="$(SDT_RC=0 SDT_MARKER=missing run_helper "corners/REC-1234/deck1.log" 2>"$TMP/e5")"
expect="run_feed_study.sh: deck1 FAILED (rc=0) -- see corners/REC-1234/deck1.log"
if [ "$out" = "RC 1" ] && [ "$(cat "$TMP/e5")" = "$expect" ]; then
  ok "see-path echoed verbatim (corners/\${RECORD_ID}/... form survives)"
else bad "see-path passthrough (out=[$out] err=[$(cat "$TMP/e5")])"; fi

# 6. the helper returns, never exits: a failing call under set -e with
#    || true lets the caller continue (an internal exit would end the shell
#    and CONTINUED would never print)
noexit_out="$( (
    PATH="$STUBS:$PATH"
    # shellcheck disable=SC1090
    source "$ENV_SH" >/dev/null 2>&1
    SIM_SCRIPT_NAME="run_feed_study.sh"
    # shellcheck disable=SC2034  # read by sim_run_deck
    CORNERS_OUT="$FIX/corners"
    # shellcheck disable=SC2034  # read by sim_run_deck
    SNAPSHOTS_OUT="$FIX/snapshots"
    set -e
    SDT_RC=1
    export SDT_RC
    sim_run_deck deck1 "$CORNERS_OUT/deck1.log" "see-path" || true
    echo "CONTINUED"
  ) 2>"$TMP/e6" )"
noexit_rc=$?
if [ "$noexit_rc" -eq 0 ] && [ "$noexit_out" = "CONTINUED" ] && [ -s "$TMP/e6" ]; then
  ok "no-exit contract: failing call with || true under set -e continues"
else bad "no-exit contract (rc=$noexit_rc out=[$noexit_out])"; fi

# 7./8. the budget caps live in the le/q runner wrappers; extract the real
# run_deck() and drive it against the stub so the cap firing (and that it
# exits rather than returns) is asserted on the shipped code.
RUNNERS_DIR="$(cd "$HERE/.." && pwd)/lna-matching-feasibility"
budget_case() { # <runner-file> <budget> <script-name>
  local runner="$1" budget="$2" name="$3" fn rc
  fn="$(awk '/^run_deck\(\)/{f=1} f{print} f&&/^\}$/{exit}' "$runner")"
  if [ -z "$fn" ]; then bad "budget $name: run_deck() not extracted"; return; fi
  (
    PATH="$STUBS:$PATH"
    # shellcheck disable=SC1090
    source "$ENV_SH" >/dev/null 2>&1
    # shellcheck disable=SC2034  # read by sim_run_deck
    SIM_SCRIPT_NAME="$name"
    # shellcheck disable=SC2034  # read by the extracted run_deck
    CORNERS_OUT="$TMP/budget-$name/corners"
    # shellcheck disable=SC2034  # read by the extracted run_deck
    SNAPSHOTS_OUT="$TMP/budget-$name/snapshots"
    mkdir -p "$CORNERS_OUT" "$SNAPSHOTS_OUT"
    # shellcheck disable=SC2034  # incremented/read by the extracted run_deck
    N_RUN=0
    # shellcheck disable=SC2034  # read by the extracted run_deck
    BUDGET="$budget"
    eval "$fn"
    i=1
    while [ "$i" -le "$budget" ]; do
      run_deck "s$i" >/dev/null 2>&1 || { echo "UNEXPECTED-FAIL at s$i"; exit 9; }
      i=$(( i + 1 ))
    done
    run_deck "over-budget"   # must terminate here with the budget message
    echo "NOT-REACHED"
  ) >"$TMP/budget-$name.out" 2>"$TMP/budget-$name.err"
  rc=$?
  if [ "$rc" -eq 1 ] \
     && grep -qF "${name}: deck budget ${budget} exceeded at over-budget" "$TMP/budget-$name.err" \
     && [ ! -s "$TMP/budget-$name.out" ]; then
    ok "budget cap ($name, BUDGET=$budget): fires at N_RUN > $budget with the current message, exits 1"
  else
    bad "budget cap $name (rc=$rc out=[$(cat "$TMP/budget-$name.out")] err=[$(cat "$TMP/budget-$name.err")])"
  fi
}
budget_case "$RUNNERS_DIR/run_le_study.sh" 32 run_le_study.sh
budget_case "$RUNNERS_DIR/run_q_study.sh" 16 run_q_study.sh

echo "pass=$pass fail=$fail"
[ "$fail" -eq 0 ] && [ "$pass" -ge 8 ]
