#!/usr/bin/env bash
# Isolation-attribution correction derivation for the #200/#202 requirements
# study (issue #207). NO simulation: no ngspice, no PDK. It re-reduces the
# RETAINED raw inputs of one source record with the corrected attribution
# (q_study.py reduce --attribution corrected) and publishes the result as a NEW
# append-only record. The source record's bytes are never written.
#
#   sim/lna-matching-feasibility/run_q_study_correction.sh [SOURCE_RECORD_ID]
#
# Default source: 20261011-164702-455c67d. Output (new record id, minted like
# sim_record_paths: <UTC date>-<time>-<short sha>):
#   records/<id>.md, records/<id>-isolation.csv, corners/<id>/recommendation.json,
#   corners/<id>/qreq_headlines.md, corners/<id>/source-record.json
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SRC="${1:-20261011-164702-455c67d}"
SRC_SNAP="${SCRIPT_DIR}/netlist-snapshots/${SRC}"
SRC_CORN="${SCRIPT_DIR}/corners/${SRC}"
SRC_REC="${SCRIPT_DIR}/records/${SRC}"
[[ -d "${SRC_SNAP}" && -d "${SRC_CORN}" && -f "${SRC_REC}-qmap.csv" ]] \
  || { echo "run_q_study_correction.sh: source record ${SRC} is incomplete." >&2; exit 3; }
command -v python3 >/dev/null 2>&1 || { echo "run_q_study_correction.sh: python3 not on PATH." >&2; exit 3; }

SHA="$(git -C "${SCRIPT_DIR}" rev-parse --short HEAD 2>/dev/null || echo unknown)"
ID="$(date -u +%Y%m%d-%H%M%S)-${SHA}"
CORN="${SCRIPT_DIR}/corners/${ID}"
if [[ -e "${CORN}" ]] || compgen -G "${SCRIPT_DIR}/records/${ID}*" >/dev/null; then
  echo "run_q_study_correction.sh: record id ${ID} already exists; wait a second and rerun." >&2
  exit 4
fi
mkdir "${CORN}"
REC="${SCRIPT_DIR}/records/${ID}"
TMP="$(mktemp -d)"
trap 'rm -rf "${TMP}"' EXIT

python3 -I "${SCRIPT_DIR}/q_study.py" reduce --snapdir "${SRC_SNAP}" --corners "${SRC_CORN}" \
  --attribution corrected --recommendation-json "${CORN}/recommendation.json" \
  --isolation-csv "${REC}-isolation.csv" --map-csv "${TMP}/qmap.csv" \
  --markdown "${CORN}/qreq_headlines.md"
# the map table is untouched by this correction: prove it
cmp -s "${TMP}/qmap.csv" "${SRC_REC}-qmap.csv" \
  || { echo "run_q_study_correction.sh: re-derived qmap differs from ${SRC}." >&2; exit 5; }

{
  echo "# Record ${ID}"
  echo
  echo "Issue #207: **correction / derivation record** for \`${SRC}\` (the #200/#202 input-Q /"
  echo "feed-isolation requirements study). No simulation was run: this record re-reduces the"
  echo "retained raw inputs of \`${SRC}\` (\`corners/${SRC}/\`, \`netlist-snapshots/${SRC}/\`) with"
  echo "\`q_study.py reduce --attribution corrected\` (\`run_q_study_correction.sh\`). Every artifact of"
  echo "\`${SRC}\` is preserved unchanged (append-only); this record is the corrected view."
  echo
  echo "## What was wrong in \`${SRC}\`"
  echo
  echo "- The reducer iterated both arms but always read the finite \`em5_cmim\` tank probe, so the fresh"
  echo "  ideal-choke control row was given that tank's isolation (797.9 Ohm mid / 733.0 Ohm band-min)."
  echo "  The ideal 1 uH choke is a different feed circuit; it has no finite-tank measurement. The pairing"
  echo "  \"797.9 Ohm with NFmin@290 worst 0.476 dB\" is unsupported (the physical finite feed at that"
  echo "  isolation has 1.545 dB)."
  echo "- The reducer then appended a second \`ideal_choke\` row from the retained #198 characterization"
  echo "  (same numbers, isolation \"infinite\"), so the table held two indistinguishable \`ideal_choke\`"
  echo "  rows. They are the same NFmin values from two sources (fresh #200 control char vs retained"
  echo "  #198 anchor), which is why the values coincide; they are not independent points."
  echo
  echo "## Correction"
  echo
  echo "- Only the finite-feed control (\`em5_cmim\`) and the three bracket proxies carry the measured"
  echo "  tank isolation and form the measured finite isolation curve."
  echo "- The ideal-choke rows are diagnostic bounds with isolation NOT MEASURED (the ideal 1 uH choke is"
  echo "  a bound; this record makes no claim about its actual impedance). They are named"
  echo "  \`ideal_choke_ctl_fresh\` and \`ideal_choke_retained_anchor\`, carry distinct \`source\` values and"
  echo "  are excluded from the finite curve (\`finite_curve_member = no\`)."
  echo "- Unchanged and consistent with the raw inputs: all finite-feed values, the input-Q map"
  echo "  (re-derived qmap table is byte-identical to \`${SRC}-qmap.csv\`), the boundary verifications,"
  echo "  the threshold crossings and the campaign verdict (NO-GO, binding: noise_floor). No spec change."
  echo
  echo "## Corrected tables"
  echo
  sed -n '/^#### Feed-isolation bracket/,/^Probe control arm/p' "${CORN}/qreq_headlines.md" | sed '$d'
  echo "Full corrected headline tables: \`corners/${ID}/qreq_headlines.md\`; machine-readable"
  echo "\`corners/${ID}/recommendation.json\` (\`requirements.isolation.sampled_curve\` holds finite-feed"
  echo "arms only; \`diagnostic_bound_points\` holds the ideal-choke diagnostics)."
  echo
  echo "## Artifacts"
  echo
  echo "- \`records/${ID}-isolation.csv\` (corrected isolation table: adds \`source\`, \`isolation_source\`,"
  echo "  \`isolation_available\`, \`finite_curve_member\`)"
  echo "- \`corners/${ID}/recommendation.json\`, \`corners/${ID}/qreq_headlines.md\`,"
  echo "  \`corners/${ID}/source-record.json\`"
  echo "- Affected (preserved) record: \`records/${SRC}.md\`"
} > "${REC}.md"

printf '{\n  "corrects_record": "%s",\n  "issue": 207,\n  "derivation": "q_study.py reduce --attribution corrected",\n  "simulation_rerun": false\n}\n' \
  "${SRC}" > "${CORN}/source-record.json"
echo "run_q_study_correction.sh: wrote records/${ID}.md"
