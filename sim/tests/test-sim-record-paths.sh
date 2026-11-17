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
#   4. directory-creation failures (issue #311): the two failure modes are
#      separate, correctly attributed messages carrying the failing mkdir's
#      errno and the caller PID -- a file where corners/ should be, and
#      (non-root) an unwritable corners/ -- and the reservation is retained
#      in both (monotonic)
#   5. lost race (issue #311's CI shape): corners/<id> appears between the
#      pre-check and the holder's exclusive mkdir -> corners/<id>-mode
#      message, nothing removed; the next second's id still mints
#   6. SIM_PDK_PROVENANCE_JSON set: mint succeeds, sidecar written (the
#      provenance failure rollback is untouched by this change)
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

# run_srp <experiment-dir> [stubs-dir]: call sim_record_paths in a fresh
# subshell and print "OK <RECORD_ID> <SNAPSHOTS_OUT> <CORNERS_OUT> <RECORDS_DIR>".
run_srp() {
  (
    # shellcheck disable=SC2030  # intentional: stubs shadow PATH in this subshell only
    PATH="${2:-$STUBS}:$PATH"
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
c2_ok=1; c2_why=""
if [ "$wins" -ne 1 ] || [ "$losses" -ne 7 ]; then c2_ok=0; c2_why="$c2_why counts(wins=$wins losses=$losses)"; fi
if [ ! -d "$E2/netlist-snapshots/$ID" ]; then c2_ok=0; c2_why="$c2_why missing(netlist-snapshots/$ID)"; fi
if [ ! -d "$E2/corners/$ID" ]; then c2_ok=0; c2_why="$c2_why missing(corners/$ID)"; fi
if [ "$c2_ok" -eq 1 ]; then
  ok "8 concurrent callers: exactly one winner, losers exit 4 with no paths, winner's dirs intact"
else
  bad "concurrency (wins=$wins losses=$losses):$c2_why"
  # Diagnostics only; the assertions above are unchanged.
  for i in 1 2 3 4 5 6 7 8; do
    echo "  caller $i rc=$(cat "$TMP/c$i.rc" 2>/dev/null) stdout=[$(cat "$TMP/c$i.out" 2>/dev/null)] stderr=[$(cat "$TMP/c$i.err" 2>/dev/null)]"
  done
  echo "  listing of $E2:"; listing "$E2" | sed 's/^/    /'
fi

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

# 4. creation failures (issue #311): each mode gets its own message naming
#    the call that actually failed, with its errno and the caller PID, and
#    the reservation is retained (monotonic) in both.
E4="$TMP/e4"; mkdir -p "$E4"; echo blocker > "$E4/corners"
out="$(run_srp "$E4" 2>"$TMP/err4")"; rc=$?
if [ "$rc" -ne 0 ] && [ -z "$out" ] && [ -s "$TMP/err4" ] \
   && [ -d "$E4/netlist-snapshots/$ID" ] \
   && [ "$(cat "$E4/corners")" = blocker ] \
   && grep -q "shared record parents $E4/corners" "$TMP/err4" \
   && grep -q "pid " "$TMP/err4" \
   && ! grep -q "cannot exclusively create" "$TMP/err4"; then
  ok "directory-creation failure (corners is a file): rejected, parents-mode message, reservation retained"
else bad "creation failure (rc=$rc out=$out err=[$(cat "$TMP/err4" 2>/dev/null)])"; fi

E5="$TMP/e5"; mkdir -p "$E5/corners" "$E5/netlist-snapshots" "$E5/records"
chmod a-w "$E5/corners"
if [ -w "$E5/corners" ]; then
  echo "SKIP: unwritable corners/ (running as a user that ignores modes)"
else
  out="$(run_srp "$E5" 2>"$TMP/err5")"; rc=$?
  if [ "$rc" -ne 0 ] && [ -z "$out" ] && [ -d "$E5/netlist-snapshots/$ID" ] \
     && [ -z "$(ls -A "$E5/corners")" ] \
     && grep -q "cannot exclusively create $E5/corners/$ID" "$TMP/err5" \
     && grep -q "Permission denied" "$TMP/err5" \
     && grep -q "pid " "$TMP/err5" \
     && ! grep -q "shared record parents" "$TMP/err5"; then
    ok "partial failure (corners unwritable): rejected, corners/<id>-mode message, reservation retained"
  else bad "partial failure (rc=$rc out=$out err=[$(cat "$TMP/err5" 2>/dev/null)])"; fi
fi

# 5. lost race, issue #311's CI shape: another caller's corners/<id> comes
#    into existence between this holder's pre-check and its exclusive
#    mkdir. A mkdir stub in a dedicated stubs dir pre-creates the directory
#    and then delegates to the real mkdir, so the real mkdir fails EEXIST
#    deterministically -- no sleeps, no real race. The holder must reject
#    with the corners/<id>-mode message and remove NOTHING (the reservation
#    is monotonic), and the fixture must still mint the next second's id.
REAL_MKDIR="$(command -v mkdir)"
STUBS_RACE="$TMP/stubs-race"; mkdir -p "$STUBS_RACE"
cp "$STUBS/date" "$STUBS/git" "$STUBS_RACE/"
cat > "$STUBS_RACE/mkdir" <<STUB
#!/bin/sh
for a in "\$@"; do
  case "\$a" in
    */corners/$ID) "$REAL_MKDIR" -p "\$a" ;;
  esac
done
exec "$REAL_MKDIR" "\$@"
STUB
chmod +x "$STUBS_RACE/mkdir"
E6="$TMP/e6"; mkdir -p "$E6/netlist-snapshots" "$E6/corners" "$E6/records"
out="$(run_srp "$E6" "$STUBS_RACE" 2>"$TMP/err6")"; rc=$?
if [ "$rc" -ne 0 ] && [ -z "$out" ] \
   && [ -d "$E6/netlist-snapshots/$ID" ] && [ -d "$E6/corners/$ID" ] \
   && grep -q "cannot exclusively create $E6/corners/$ID" "$TMP/err6" \
   && grep -q "File exists" "$TMP/err6" \
   && ! grep -q "shared record parents" "$TMP/err6"; then
  ok "lost race (corners/<id> appears under the holder): rejected, nothing removed, reservation retained"
else bad "lost race (rc=$rc out=$out err=[$(cat "$TMP/err6" 2>/dev/null)])"; fi

# 5b. a rejected id's leftovers do not block the next second's id
STUBS2="$TMP/stubs2"; mkdir -p "$STUBS2"
cat > "$STUBS2/date" <<'STUB'
#!/bin/sh
echo 20260101-000001
STUB
cp "$STUBS/git" "$STUBS2/git"; chmod +x "$STUBS2/date" "$STUBS2/git"
ID2="20260101-000001-abc1234"
out="$(run_srp "$E6" "$STUBS2" 2>"$TMP/err6b")"; rc=$?
if [ "$rc" -eq 0 ] && [ "$out" = "OK $ID2 $E6/netlist-snapshots/$ID2 $E6/corners/$ID2 $E6/records $E6 abc1234" ] \
   && [ -d "$E6/netlist-snapshots/$ID2" ] && [ -d "$E6/corners/$ID2" ]; then
  ok "rejected id's leftovers (empty reservation, another caller's corners/<id>) do not block the next second's id"
else bad "next-second id (rc=$rc out=$out)"; fi

# 6. behaviour unchanged when SIM_PDK_PROVENANCE_JSON is set: the mint
#    succeeds and writes the sidecar. (The provenance failure rollback is
#    only reachable through the same lost-race shape as case 5 and is not
#    touched by this change; the pre-check already rejects any pre-existing
#    records/<id>* so a deterministic noclobber collision cannot be staged.)
E8="$TMP/e8"; mkdir -p "$E8"
out="$(
  # shellcheck disable=SC2031  # intentional: same subshell-local stub PATH as run_srp
  PATH="$STUBS:$PATH"
  # shellcheck disable=SC1090
  source "$ENV_SH" >/dev/null 2>&1
  # shellcheck disable=SC2034  # read by sim_record_paths
  SIM_PDK_PROVENANCE_JSON='{"stub":true}'
  # shellcheck disable=SC2034  # read by sim_record_paths
  SCRIPT_DIR="$E8"
  sim_record_paths
  echo "OK ${RECORD_ID} ${SNAPSHOTS_OUT} ${CORNERS_OUT} ${RECORDS_DIR}"
)" 2>"$TMP/err8"; rc=$?
if [ "$rc" -eq 0 ] && [ "$out" = "OK $ID $E8/netlist-snapshots/$ID $E8/corners/$ID $E8/records" ] \
   && [ -d "$E8/netlist-snapshots/$ID" ] && [ -d "$E8/corners/$ID" ] \
   && [ "$(cat "$E8/records/$ID.pdk-provenance.json")" = '{"stub":true}' ]; then
  ok "SIM_PDK_PROVENANCE_JSON set: mint succeeds, sidecar written, dirs intact"
else bad "provenance success path (rc=$rc out=$out err=[$(cat "$TMP/err8" 2>/dev/null)])"; fi

echo "pass=$pass fail=$fail"
[ "$fail" -eq 0 ] && [ "$pass" -ge 10 ]
