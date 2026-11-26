#!/usr/bin/env bash
# Two-tone IIP3 campaign on the MATCHED DUT (issue #337): the ratified
# testbench/tb_lna_iip3.spice.tmpl protocol (template unchanged) as `klt sim`
# corner requests, so the 45-cell PVT grid is submitted to the Spot batch
# fleet instead of being hand-launched on a shared host.
#
#   export PDK_ROOT=/path/to/ihp-open-pdk PDK=ihp-sg13g2   # or let sim/env.sh find it
#   sim/lna-characterization/run_lna_iip3.sh
#
# What runs (lna_variant_campaign.py gen-iip3):
#   matched_op.request.json              the 45-cell DC bias join (I_C1 beside
#                                        every number the record quotes)
#   matched_iip3_a1mv / _a2mv            the ratified two-level pair, every
#                                        PVT cell (so the 3:1 IM3 slope is
#                                        CHECKED per cell, not assumed)
#   matched_iip3_a0p5mv/_a4mv/_a8mv      nominal cell only -- the 24 dB drive
#                                        range at one cell
# Each IIP3 deck reproduces the template's control sequence verbatim (op ->
# OP echo -> tran 4 ps/65536 pts/1 us discarded -> linearize -> coherent-DFT
# projection -> DFT echo -> fft); the FFT bin magnitudes return in the klt
# report and the OP/DFT echoes stay in the kept per-corner ngspice log.
# summarize-iip3 reduces reports+logs into records/<id>-iip3{,-summary}.csv,
# applies the README IM3-slope validity policy (no intercept accepted from a
# cell whose 2-point slope departs from 3 +/- 0.15), and converts to the
# device-plane figure with the matched DUT's own per-cell |S11| (committed
# present-dut slice records). If a batch submit fails this script STOPS and
# records the error; it never falls back to a local grid.
#
# Environment knobs (all optional):
#   LNA_IIP3_VARIANT=matched   which VARIANTS entry to run (default matched)
#   LNA_IIP3_SMOKE=1           single nominal cell per request (plumbing
#                              check only; NOT a PVT campaign -- do not
#                              commit as evidence)
#   LNA_IIP3_TEMPS=125         temperature slice (comma list from
#                              -40,27,125): partial grid, NOT a corner box
#   LNA_IIP3_BACKEND=          override the klt backend (default: whatever
#                              klt picks, i.e. $KLT_SIM_BACKEND)
#   LNA_IIP3_CAPACITY_WAIT_S=  batch submit capacity wait (default 600)
#   LNA_IIP3_MAX_IN_FLIGHT=    --batch-set concurrency (default 2)
#   LNA_IIP3_CAPACITY_RETRIES= batch capacity retries (default 3)
#   LNA_IIP3_S11_CSV=          override the per-cell |S11| slice CSVs (comma
#                              list); default: the three committed
#                              present-dut slice summary records below
#
# Output (append-only, same layout as run_lna_sweep.sh / run_lna_variant.sh):
#   netlist-snapshots/<record-id>/   decks + klt requests
#   corners/<record-id>/             klt reports + per-corner decks/logs
#   records/<record-id>.md           the append-only record
#   records/<record-id>-iip3.csv     one row per (cell x drive level)
#   records/<record-id>-iip3-summary.csv  one row per PVT cell
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SIM_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
# shellcheck source-path=SCRIPTDIR
# shellcheck source=../env.sh
source "${SIM_DIR}/env.sh"
# shellcheck source=campaign_requests.sh
source "${SCRIPT_DIR}/campaign_requests.sh"

sim_require_pdk run_lna_iip3.sh --osdi
command -v klt >/dev/null 2>&1 || { echo "run_lna_iip3.sh: klt not on PATH." >&2; exit 3; }
command -v python3 >/dev/null 2>&1 || { echo "run_lna_iip3.sh: python3 not on PATH." >&2; exit 3; }

# The frozen pre-match DUT copy must still match its recorded provenance hash
# (the campaign module reads it as the non-"design" variant baseline).
"${SIM_DIR}/models/check_sources.sh" || { echo "run_lna_iip3.sh: sim/models hash check failed." >&2; exit 3; }

sim_record_paths
VARIANT="${LNA_IIP3_VARIANT:-matched}"
DESIGN_NETLIST="${REPO_ROOT}/design/netlist/lna.spice"
DESIGN_NETLIST_SHA="$(sha256sum "${DESIGN_NETLIST}" | awk '{print $1}')"
KLT_VERSION="$(klt --version 2>&1 | head -1)"

# klt version-floor preflight: the ONE shared check
# (lna_variant_campaign.py check-client; issue #475) also used by
# run_lna_variant.sh and the core-envelope gate runner -- the IIP3 requests
# use the same features (sim/pdk.json klt_variant_campaign), and the batch
# runner image is checked by klt itself.
python3 -I "${SCRIPT_DIR}/lna_variant_campaign.py" check-client \
  --runner run_lna_iip3.sh -- "${KLT_VERSION}" || exit 3

GEN_ARGS=(--outdir "${SNAPSHOTS_OUT}" --variants "${VARIANT}")
[[ -n "${LNA_IIP3_SMOKE:-}" ]] && { GEN_ARGS+=(--smoke); echo "run_lna_iip3.sh: LNA_IIP3_SMOKE set -- single-cell smoke, NOT a PVT campaign"; }
[[ -n "${LNA_IIP3_TEMPS:-}" ]] && { GEN_ARGS+=(--temps "${LNA_IIP3_TEMPS}"); echo "run_lna_iip3.sh: LNA_IIP3_TEMPS set (${LNA_IIP3_TEMPS}) -- temperature slice, partial PVT grid, NOT a full corner-box campaign"; }
python3 "${SCRIPT_DIR}/lna_variant_campaign.py" gen-iip3 "${GEN_ARGS[@]}"

BACKEND_OVERRIDE="${LNA_IIP3_BACKEND:-}"
EFFECTIVE_BACKEND="${BACKEND_OVERRIDE:-${KLT_SIM_BACKEND:-local}}"
CAPACITY_WAIT="${LNA_IIP3_CAPACITY_WAIT_S:-600}"
# The 45-cell IIP3 requests use remote.hosts = 15 (at most 3 cells per fleet job).
MAX_IN_FLIGHT="${LNA_IIP3_MAX_IN_FLIGHT:-2}"
CAPACITY_RETRIES="${LNA_IIP3_CAPACITY_RETRIES:-3}"

echo "run_lna_iip3.sh: record ${RECORD_ID}; variant ${VARIANT}; DUT sha256 ${DESIGN_NETLIST_SHA}; klt ${KLT_VERSION}; KLT_SIM_BACKEND=${KLT_SIM_BACKEND:-<unset>}"
lna_run_requests "${BACKEND_OVERRIDE}" "${MAX_IN_FLIGHT}" "${CAPACITY_RETRIES}"

# --- reduce ---------------------------------------------------------------
# Per-cell |S11| for the device-plane conversion: the three committed
# present-dut slice records of THIS matched DUT (125/27/-40 C; README table).
# Overridable with LNA_IIP3_S11_CSV.
S11_CSV_DEFAULT="${RECORDS_DIR}/20261106-054735-64b37ae-summary.csv,${RECORDS_DIR}/20261116-022647-eacd53a-summary.csv,${RECORDS_DIR}/20261116-023212-eacd53a-summary.csv"
S11_CSV="${LNA_IIP3_S11_CSV:-${S11_CSV_DEFAULT}}"

SUMMARIZE_ARGS=(--corners-dir "${CORNERS_OUT}"
  --variant "${VARIANT}"
  --iip3-csv "${RECORDS_DIR}/${RECORD_ID}-iip3.csv"
  --summary-csv "${RECORDS_DIR}/${RECORD_ID}-iip3-summary.csv"
  --headlines-md "${CORNERS_OUT}/iip3-headlines.md"
  --op-report "${CORNERS_OUT}/${VARIANT}_op.report.json"
  --s11-csv "${S11_CSV}")
[[ -n "${LNA_IIP3_SMOKE:-}" ]] && SUMMARIZE_ARGS+=(--grid smoke)
[[ -n "${LNA_IIP3_TEMPS:-}" ]] && SUMMARIZE_ARGS+=(--temps "${LNA_IIP3_TEMPS}")
SUMMARIZE_RC=0
python3 "${SCRIPT_DIR}/lna_variant_campaign.py" summarize-iip3 "${SUMMARIZE_ARGS[@]}" || SUMMARIZE_RC=$?
if (( SUMMARIZE_RC != 0 )); then
  echo "run_lna_iip3.sh: reduction FAILED (exit ${SUMMARIZE_RC}); coverage incomplete -- see ${CORNERS_OUT}/iip3-headlines.md" >&2
fi

JOBS="$(lna_job_bullets "${CORNERS_OUT}")"

NGSPICE_VER="$(python3 -I - "${CORNERS_OUT}/${VARIANT}_op.report.json" <<'PYEOF'
import json, sys
try:
    d = json.load(open(sys.argv[1]))
    print(d["environment"].get("engine_version") or "unknown")
except Exception:
    print("unknown")
PYEOF
)"

{
  echo "# Record ${RECORD_ID}"
  echo
  echo "- **Experiment**: lna-characterization, matched-DUT two-tone IIP3 (issue #337)."
  echo "- **Claim**: the post-match IIP3 re-measure issue #27's Test Plan owes: the"
  echo "  RATIFIED two-tone protocol of \`testbench/tb_lna_iip3.spice.tmpl\` (template"
  echo "  unchanged) on the committed matched DUT, across the 45-cell PVT box,"
  echo "  at two drive levels per cell (3:1 IM3 slope CHECKED per cell) plus the"
  echo "  nominal cell's extra levels. Supplies the number \`spec/target-spec.md\`"
  echo "  line 171 binds; the IIP3 numeric row itself stays **DRAFT** -- binding it"
  echo "  (or relaxing it) requires a decision record of its own, which this record"
  echo "  deliberately is not."
  echo "- **DUT**: \`design/netlist/lna.spice\` sha256 \`${DESIGN_NETLIST_SHA}\`, inlined"
  echo "  verbatim in every deck (byte-identical to the matched-DUT verdict's DUT;"
  echo "  verified at generation time by the header stamp and at record time here)."
  echo "  \`design/\` is not modified."
  echo "- **Bench**: tones f1 = 2.44140625 GHz (bin 640), f2 = 2.44903564453125 GHz"
  echo "  (bin 642), spacing 7.62939453125 MHz; IM3 at bins 638/644; IM5 floor"
  echo "  sentinels at bins 636/646. FFT: tstep = 4 ps, N = 65536, rectangular"
  echo "  window, df = 3.814697265625 MHz, tstart = 1 us discarded. 50 Ohm ports;"
  echo "  input power = AVAILABLE source power per tone A^2/(8*Rs); output"
  echo "  V_peak^2/(2*RL); IIP3 = Pin + (Pout - PIM3)/2. Two extractions per"
  echo "  point: ngspice \`fft\` (primary) and the template's independent"
  echo "  coherent-DFT projection (\`iip3_dbm_dft_crosscheck\`), agreement committed"
  echo "  per point (\`dft_fft_iip3_agreement_db\`; README: ~0.01 dB)."
  echo "- **PVT grid**: process (typ/bcs/wcs/sf/fs) x T (-40/27/125 C) x VDD"
  echo "  (1.62/1.80/1.98 V) -- 45 cells, the same box as the matched-DUT verdict."
  echo "- **PDK**: \`${PDK}\` at \`${PDK_ROOT}\`; HBT sections from \`cornerHBT.lib\`, MOS"
  echo "  from \`cornerMOShv.lib\` (same label->section map as \`run_lna_sweep.sh\`);"
  echo "  ngspice ${NGSPICE_VER} (fleet runner; version/build in each report's \`environment\`)."
  echo "- **PDK identity (verified)**: \`${SIM_PDK_RELEASE}\` via ${SIM_PDK_ID_ROUTE}; model hashes in \`records/${RECORD_ID}.pdk-provenance.json\`"
  echo "- **Runner**: client \`${KLT_VERSION}\`; backend \`${EFFECTIVE_BACKEND}\`$([[ "${EFFECTIVE_BACKEND}" == batch ]] && echo " (--wait-for-capacity ${CAPACITY_WAIT} s, --max-in-flight ${MAX_IN_FLIGHT})")."
  echo "  Jobs (klt \`environment.remote\`):"
  echo "${JOBS}"
  if [[ ${#FAILED[@]} -gt 0 ]]; then
    echo "- **Failed requests**: ${FAILED[*]}"
  else
    echo "- **Failed requests**: none."
  fi
  if (( SUMMARIZE_RC != 0 )); then
    echo "- **Reduction**: FAILED (exit ${SUMMARIZE_RC}) -- **coverage incomplete**; not a complete-grid result."
  elif [[ -n "${LNA_IIP3_TEMPS:-}" ]]; then
    echo "- **Reduction**: ok over the TEMPERATURE SLICE ${LNA_IIP3_TEMPS} only -- partial grid, NOT the full 45-cell PVT box."
  else
    echo "- **Reduction**: ok (expected grid complete, all measurements finite)."
  fi
  echo "- **Headlines (machine-generated)**:"
  echo
  cat "${CORNERS_OUT}/iip3-headlines.md" 2>/dev/null || echo "(none -- summarize-iip3 found no reports)"
  echo
  echo "- **Links**: decks+requests \`netlist-snapshots/${RECORD_ID}/\`; klt reports and"
  echo "  per-corner decks/logs (the OP/DFT echoes) \`corners/${RECORD_ID}/\`;"
  echo "  \`records/${RECORD_ID}-iip3.csv\` (every cell x drive level);"
  echo "  \`records/${RECORD_ID}-iip3-summary.csv\` (per-cell intercepts, IM3 slope"
  echo "  check, mismatch term, device-plane figures, bias point)."
  echo "- **Timestamp / author**: $(date -u +%Y-%m-%dT%H:%M:%SZ), Loom Builder (agent), issue #337."
} > "${RECORDS_DIR}/${RECORD_ID}.md"

echo "run_lna_iip3.sh: wrote ${RECORDS_DIR}/${RECORD_ID}.md"
if [[ ${#FAILED[@]} -gt 0 ]]; then
  echo "run_lna_iip3.sh: failed: ${FAILED[*]}" >&2
  exit 1
fi
if (( SUMMARIZE_RC != 0 )); then
  exit 1
fi
