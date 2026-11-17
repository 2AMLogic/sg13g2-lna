#!/usr/bin/env bash
# run_spec_envelopes.sh -- run the issue-231 ratified-row `klt sim` corner
# envelopes for one netlist-snapshots record (batch fleet, never local).
#
# Usage:
#   sim/lna-characterization/run_spec_envelopes.sh \
#     sim/lna-characterization/netlist-snapshots/<record-id>
#
# Runs the record's four requests (matched_op, matched_sp_band,
# matched_sp_stab, matched_noise) through `klt sim --backend batch
# --wait-for-capacity 600` -- the full ratified corner box of 27 cells
# each. Per-corner artifacts land under $SIM_ENVELOPE_ARTIFACTS (default
# a /tmp tree) so nothing bulk lands in git; the report envelope of each
# request is written to <record-dir>/reports/<stem>.report.json.
#
# Exit-code semantics: a request exiting 0 passed its grid; 3 means the
# grid RAN and at least one corner failed its limits -- that is a verdict
# (the expected NF result), not a tool failure. The runner reports each
# stem's verdict and exits 0 when every report was produced, 1 when any
# run failed to produce a verdict (exit 4/1/2 from klt sim, missing
# report). Reducing the reports into the verdict record is a separate,
# PDK-free step: reduce_spec_envelopes.py.
#
# Needs: a klt with batch-fleet access (credentials), no local ngspice,
# no PDK (the fleet stages the pinned models; the requests preload the
# OSDI models via options.osdi_preload + stage_model_inputs).

set -u

HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$HERE/../.." && pwd)"
cd "$ROOT" || exit 1

DIR="${1:-}"
[ -n "$DIR" ] || { echo "usage: $0 sim/lna-characterization/netlist-snapshots/<record-id>" >&2; exit 2; }
[ -d "$DIR" ] || { echo "FAIL: no such record dir: $DIR" >&2; exit 2; }

ARTS="${SIM_ENVELOPE_ARTIFACTS:-${TMPDIR:-/tmp}/spec-envelope-artifacts}/$(basename "$DIR")"
mkdir -p "$ARTS"

STEMS="matched_op matched_sp_band matched_sp_stab matched_noise"
rc_all=0
summary=()

for stem in $STEMS; do
  req="$DIR/$stem.request.json"
  [ -f "$req" ] || { echo "FAIL: missing request $req" >&2; exit 2; }
  reports="$DIR/reports"
  mkdir -p "$reports"
  report="$reports/$stem.report.json"
  echo "=== $stem: klt sim --backend batch --wait-for-capacity 600"
  set +e
  klt sim --backend batch --wait-for-capacity 600 \
    -o "$ARTS/$stem" \
    --report-out "$report" \
    --format json \
    "$req" > "$ARTS/$stem.stdout.json" 2> "$ARTS/$stem.stderr.log"
  rc=$?
  set -e
  case $rc in
    0) verdict="pass" ;;
    3) verdict="fail (grid ran; corner(s) missed limits -- a verdict, not a tool failure)" ;;
    *) verdict="NO VERDICT (klt sim exit $rc)"; rc_all=1 ;;
  esac
  if [ -s "$report" ]; then
    summary+=("$stem: report=$report verdict=$verdict")
  else
    summary+=("$stem: NO REPORT -- $verdict")
    rc_all=1
  fi
done

echo
for line in "${summary[@]}"; do echo "$line"; done
if [ "$rc_all" -eq 0 ]; then
  echo "next: python3 -I sim/lna-characterization/reduce_spec_envelopes.py --snapshot-dir $DIR"
fi
exit "$rc_all"
