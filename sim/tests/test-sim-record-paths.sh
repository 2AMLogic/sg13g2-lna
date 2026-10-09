#!/usr/bin/env bash
# PDK-free tests for sim_record_paths in sim/env.sh (issue #113).
#
# Everything runs in a mktemp fixture experiment dir. `date` and `git` are
# stubbed on PATH so the record id is fixed (20260101-000000-abc1234);
# no ngspice, PDK, klt or network is used, and nothing under sim/*/ is
# written.
#
# Cases:
#   1. clean fixture: succeeds, sets all six variables, creates the dirs
#   2. 8 concurrent callers, same id: exactly one succeeds, 7 exit 4
#   3. existing netlist-snapshots/<id>, corners/<id>, records-only
#      records/<id>.md / records/<id>-x.csv: each rejected, bytes unchanged,
#      no paths returned, nothing extra created or removed
#   4. directory-creation failures: a file where corners/ should be; and
#      (non-root) an unwritable corners/ -> reservation released
set -u
HERE="$(cd "$(dirname "$0")" && pwd)"
ENV_SH="$(cd "$HERE/.." && pwd)/env.sh"
[ -f "$ENV_SH" ] || { echo "FAIL: $ENV_SH missing" >&2; exit 1; }
TMP="$(mktemp -d)"
trap 'chmod -R u+w "$TMP" 2>/dev/null; rm -rf "$TMP"' EXIT
pass=0; fail=0
ok() { echo "PASS: $1"; pass=$((pass+1)); }
bad() { echo "FAIL: $1"; fail=$((fail+1)); }

ID="20260101-000000-abc1234"
STUBS="$TMP/stubs"; mkdir -p "$STUBS"
cat > "$STUBS/date" <<'STUB'
#!/bin/sh
echo 20260101-000000
STUB
cat > "$STUBS/git" <<'STUB'
#!/bin/sh
echo abc1234
STUB
chmod +x "$STUBS/date" "$STUBS/git"

# run_srp <experiment-dir>: call sim_record_paths in a fresh subshell and
# print "OK <RECORD_ID> <SNAPSHOTS_OUT> <CORNERS_OUT> <RECORDS_DIR>".
run_srp() {
  (
    PATH="$STUBS:$PATH"
    # shellcheck disable=SC1090
    source "$ENV_SH" >/dev/null 2>&1
    # shellcheck disable=SC2034  # read by sim_record_paths
    SCRIPT_DIR="$1"
    sim_record_paths
    echo "OK ${RECORD_ID} ${SNAPSHOTS_OUT} ${CORNERS_OUT} ${RECORDS_DIR} ${EXPERIMENT_DIR} ${REPO_GIT_SHA}"
  )
}
listing() { (cd "$1" && find . | sort); }

# 1. clean fixture
E1="$TMP/e1"; mkdir -p "$E1"
out="$(run_srp "$E1" 2>"$TMP/err1")"; rc=$?
if [ "$rc" -eq 0 ] && [ "$out" = "OK $ID $E1/netlist-snapshots/$ID $E1/corners/$ID $E1/records $E1 abc1234" ] \
   && [ -d "$E1/netlist-snapshots/$ID" ] && [ -d "$E1/corners/$ID" ] && [ -d "$E1/records" ]; then
  ok "clean fixture: ids, variables and directories"
else bad "clean fixture (rc=$rc out=$out)"; fi
# 1b. immediate rerun with the same id is rejected, first run's dirs intact
out="$(run_srp "$E1" 2>"$TMP/err1b")"; rc=$?
if [ "$rc" -ne 0 ] && [ -z "$out" ] && grep -q "$ID" "$TMP/err1b" && [ -d "$E1/netlist-snapshots/$ID" ]; then
  ok "same-id rerun rejected with a message naming the id"
else bad "same-id rerun (rc=$rc out=$out)"; fi

# 2. concurrent reservation
E2="$TMP/e2"; mkdir -p "$E2"
for i in 1 2 3 4 5 6 7 8; do
  ( run_srp "$E2" >"$TMP/c$i.out" 2>"$TMP/c$i.err"; echo $? >"$TMP/c$i.rc" ) &
done
wait
wins=0; losses=0
for i in 1 2 3 4 5 6 7 8; do
  rc="$(cat "$TMP/c$i.rc")"
  if [ "$rc" -eq 0 ] && grep -q '^OK ' "$TMP/c$i.out"; then wins=$((wins+1))
  elif [ "$rc" -eq 4 ] && [ ! -s "$TMP/c$i.out" ]; then losses=$((losses+1)); fi
done
if [ "$wins" -eq 1 ] && [ "$losses" -eq 7 ] \
   && [ -d "$E2/netlist-snapshots/$ID" ] && [ -d "$E2/corners/$ID" ]; then
  ok "8 concurrent callers: exactly one winner, losers exit 4 with no paths, winner's dirs intact"
else bad "concurrency (wins=$wins losses=$losses)"; fi

# 3. pre-existing artifacts
reject_case() { # <label> <setup-cmd...>
  local label="$1"; shift
  local e="$TMP/x-$RANDOM"; mkdir -p "$e"
  ( cd "$e" && "$@" )
  local before after out rc
  before="$(listing "$e"; find "$e" -type f -exec sha256sum {} + | sort)"
  out="$(run_srp "$e" 2>"$TMP/xerr")"; rc=$?
  after="$(listing "$e"; find "$e" -type f -exec sha256sum {} + | sort)"
  if [ "$rc" -ne 0 ] && [ -z "$out" ] && grep -q "$ID" "$TMP/xerr" && [ "$before" = "$after" ]; then
    ok "rejected, nothing altered: $label"
  else bad "$label (rc=$rc out=$out)"; fi
}
reject_case "existing netlist-snapshots/<id>" mkdir -p "netlist-snapshots/$ID"
reject_case "existing corners/<id>" mkdir -p "corners/$ID"
reject_case "records-only records/<id>.md" sh -c "mkdir records && echo old > records/$ID.md"
reject_case "records-only records/<id>-x.csv" sh -c "mkdir records && echo old > records/$ID-x.csv"
reject_case "dangling symlink at corners/<id>" sh -c "mkdir corners && ln -s nowhere corners/$ID"

# 4. creation failures
E4="$TMP/e4"; mkdir -p "$E4"; echo blocker > "$E4/corners"
out="$(run_srp "$E4" 2>"$TMP/err4")"; rc=$?
if [ "$rc" -ne 0 ] && [ -z "$out" ] && [ -s "$TMP/err4" ] && [ ! -e "$E4/netlist-snapshots/$ID" ] \
   && [ "$(cat "$E4/corners")" = blocker ]; then
  ok "directory-creation failure (corners is a file): rejected, no id dir left"
else bad "creation failure (rc=$rc out=$out)"; fi

E5="$TMP/e5"; mkdir -p "$E5/corners" "$E5/netlist-snapshots" "$E5/records"
chmod a-w "$E5/corners"
if [ -w "$E5/corners" ]; then
  echo "SKIP: unwritable corners/ (running as a user that ignores modes)"
else
  out="$(run_srp "$E5" 2>"$TMP/err5")"; rc=$?
  if [ "$rc" -ne 0 ] && [ -z "$out" ] && [ ! -e "$E5/netlist-snapshots/$ID" ] && [ -z "$(ls -A "$E5/corners")" ]; then
    ok "partial failure (corners unwritable): own reservation released"
  else bad "partial failure (rc=$rc out=$out)"; fi
fi

echo "pass=$pass fail=$fail"
[ "$fail" -eq 0 ] && [ "$pass" -ge 10 ]
