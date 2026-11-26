#!/usr/bin/env bash
# Inductor-loss variant campaign (issue #56): re-runs the run_lna_sweep.sh
# phase-1 measurements (50 Ohm S-parameters, ngspice two-port NF, .noise NF at
# T0 = 290 K, 10 MHz..30 GHz k/mu/|S22| stability) over the SAME 45 PVT cells
# for each inductor variant, as `klt sim` corners requests.
#
#   export PDK_ROOT=/path/to/ihp-open-pdk PDK=ihp-sg13g2   # or let sim/env.sh find it
#   sim/lna-characterization/run_lna_variant.sh
#
# Why `klt sim` instead of run_lna_sweep.sh's own ngspice pool: this is a
# multi-corner grid, and on the Loom dispatch workers (KLT_SIM_BACKEND=batch,
# exported by the daemon) a grid is submitted to the Spot batch fleet rather
# than hand-launched on the shared host. `klt sim` runs ONE analysis per
# request, so each variant is three requests (sp_band, sp_stab, noise) -- see
# lna_variant_campaign.py. If a batch submit fails this script STOPS and
# records the error; it never falls back to a local grid.
#
# Variants (lna_variant_campaign.py VARIANTS): ideal, lc_em, le_q20, le_q10,
# le_q5, lc_em_le_q10. The EM model is sim/models/sg13g2_inductor_em.spice
# (stamped copy; hash-checked below, never edited here). design/ is untouched:
# every variant netlist is a generated bench artifact under
# netlist-snapshots/<record-id>/.
#
# Environment knobs (all optional):
#   LNA_VARIANTS=a,b,c    subset of variants (default: all)
#   LNA_NF_NPTS=<n>       points of the 290 K NF sweep (odd, >= 11; default 11 =
#                         the S-parameter grid); identical for every variant.
#   LNA_TEMPS=125         temperature slice (comma list from -40,27,125; issue #258) so
#                         no single request nears the batch job ceiling. A slice is a
#                         partial grid: its record covers only those temperatures.
#   LNA_VARIANT_SMOKE=1   single nominal cell per request (plumbing check only;
#                         NOT a PVT campaign -- do not commit as evidence)
#   LNA_VARIANT_BACKEND=  override the klt backend (default: whatever klt picks,
#                         i.e. $KLT_SIM_BACKEND)
#   LNA_VARIANT_CAPACITY_WAIT_S=<s>  how long a batch submit waits with backoff
#                         for fleet vCPU capacity (default 600; batch only)
#   KLT_NGSPICE_BINARY=   ngspice binary for local-backend runs. The PDK's
#                         PSP103 OSDI builds target OSDI v0.4, so a local run
#                         needs ngspice >= 46 (the worker's /usr/bin/ngspice 42
#                         cannot load them); the fleet image supplies its own.
#
# Output (append-only, same layout as run_lna_sweep.sh):
#   netlist-snapshots/<record-id>/   variant netlists + klt requests
#   corners/<record-id>/             klt reports (+ per-corner decks/logs)
#   records/<record-id>{.md,-summary.csv,-compare.csv}
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SIM_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
# shellcheck source-path=SCRIPTDIR
# shellcheck source=../env.sh
source "${SIM_DIR}/env.sh"
# shellcheck source=campaign_requests.sh
source "${SCRIPT_DIR}/campaign_requests.sh"

sim_require_pdk run_lna_variant.sh --osdi
command -v klt >/dev/null 2>&1 || { echo "run_lna_variant.sh: klt not on PATH." >&2; exit 3; }
command -v python3 >/dev/null 2>&1 || { echo "run_lna_variant.sh: python3 not on PATH." >&2; exit 3; }

# The EM model copy must still match its recorded provenance hash.
"${SIM_DIR}/models/check_sources.sh" || { echo "run_lna_variant.sh: sim/models hash check failed." >&2; exit 3; }

sim_record_paths
DESIGN_NETLIST_SHA="$(sha256sum "${REPO_ROOT}/design/netlist/lna.spice" | awk '{print $1}')"
EM_SHA="$(sha256sum "${SIM_DIR}/models/sg13g2_inductor_em.spice" | awk '{print $1}')"
KLT_VERSION="$(klt --version 2>&1 | head -1)"

# klt version-floor preflight: fail here, not late at the batch runner. The
# check is the ONE shared implementation (lna_variant_campaign.py
# check-client; issue #475) that run_lna_iip3.sh and the core-envelope gate
# runner use too; the floor lives in sim/pdk.json
# (klt_variant_campaign.min_version), the one place it is recorded.
# This checks the CLIENT klt; the batch runner image must carry the same
# features and is checked by klt itself (batch_runner_version_mismatch).
python3 -I "${SCRIPT_DIR}/lna_variant_campaign.py" check-client \
  --runner run_lna_variant.sh -- "${KLT_VERSION}" || exit 3

NF_NPTS="${LNA_NF_NPTS:-11}"
GEN_ARGS=(--outdir "${SNAPSHOTS_OUT}" --nf-npts "${NF_NPTS}")
[[ -n "${LNA_VARIANTS:-}" ]] && GEN_ARGS+=(--variants "${LNA_VARIANTS}")
[[ -n "${LNA_VARIANT_SMOKE:-}" ]] && { GEN_ARGS+=(--smoke); echo "run_lna_variant.sh: LNA_VARIANT_SMOKE set -- single-cell smoke, NOT a PVT campaign"; }
[[ -n "${LNA_TEMPS:-}" ]] && { GEN_ARGS+=("--temps=${LNA_TEMPS}"); echo "run_lna_variant.sh: LNA_TEMPS set (${LNA_TEMPS}) -- temperature slice, partial PVT grid, NOT a full corner-box campaign"; }
python3 "${SCRIPT_DIR}/lna_variant_campaign.py" gen "${GEN_ARGS[@]}"

BACKEND_OVERRIDE="${LNA_VARIANT_BACKEND:-}"
EFFECTIVE_BACKEND="${BACKEND_OVERRIDE:-${KLT_SIM_BACKEND:-local}}"
CAPACITY_WAIT="${LNA_VARIANT_CAPACITY_WAIT_S:-600}"
MAX_IN_FLIGHT="${LNA_VARIANT_MAX_IN_FLIGHT:-7}"
CAPACITY_RETRIES="${LNA_VARIANT_CAPACITY_RETRIES:-3}"

echo "run_lna_variant.sh: record ${RECORD_ID}; klt ${KLT_VERSION}; KLT_SIM_BACKEND=${KLT_SIM_BACKEND:-<unset>}"
lna_run_requests "${BACKEND_OVERRIDE}" "${MAX_IN_FLIGHT}" "${CAPACITY_RETRIES}"

SUMMARIZE_ARGS=(--corners-dir "${CORNERS_OUT}" --nf-npts "${NF_NPTS}"
  --summary-csv "${RECORDS_DIR}/${RECORD_ID}-summary.csv"
  --compare-csv "${RECORDS_DIR}/${RECORD_ID}-compare.csv"
  --headlines-md "${CORNERS_OUT}/headlines.md"
  --coverage-json "${CORNERS_OUT}/coverage.json")
[[ -n "${LNA_VARIANTS:-}" ]] && SUMMARIZE_ARGS+=(--variants "${LNA_VARIANTS}")
[[ -n "${LNA_VARIANT_SMOKE:-}" ]] && SUMMARIZE_ARGS+=(--grid smoke)
[[ -n "${LNA_TEMPS:-}" ]] && SUMMARIZE_ARGS+=("--temps=${LNA_TEMPS}")
# Reduction failure (incomplete/failed/duplicate/non-finite coverage) is NOT
# masked: diagnostics, logs, reports and the record below are still written,
# then the script exits nonzero at the end.
SUMMARIZE_RC=0
python3 "${SCRIPT_DIR}/lna_variant_campaign.py" summarize "${SUMMARIZE_ARGS[@]}" || SUMMARIZE_RC=$?
if (( SUMMARIZE_RC != 0 )); then
  echo "run_lna_variant.sh: reduction FAILED (exit ${SUMMARIZE_RC}); coverage incomplete -- see ${CORNERS_OUT}/headlines.md" >&2
fi

JOBS="$(lna_job_bullets "${CORNERS_OUT}")"

{
  echo "# Record ${RECORD_ID}"
  echo
  echo "- **Experiment**: lna-characterization, inductor-loss variants (issue #56)."
  echo "- **Claim**: what replacing the ideal \`Le\`/\`Lc\` of \`design/lna.sch\` with lossy"
  if [[ -n "${LNA_VARIANT_SMOKE:-}" ]]; then
    SMOKE_SLICE_NOTE=""
    [[ -n "${LNA_TEMPS:-}" ]] && SMOKE_SLICE_NOTE="; the requested temperature slice ${LNA_TEMPS} was ignored"
    echo "  models does to gain, noise figure, S11, S22 and the mu stability margin at the"
    echo "  single nominal 27 C smoke cell (plumbing check, NOT a PVT campaign${SMOKE_SLICE_NOTE}),"
    echo "  versus the ideal baseline run through the identical harness."
  elif [[ -n "${LNA_TEMPS:-}" ]]; then
    echo "  models does to gain, noise figure, S11, S22 and the mu stability margin at the"
    echo "  TEMPERATURE SLICE ${LNA_TEMPS} of the 45 PVT cells (partial grid, NOT the full"
    echo "  corner box), versus the ideal baseline run through the identical harness."
  else
    echo "  models does to gain, noise figure, S11, S22 and the mu stability margin at the"
    echo "  45 PVT cells, versus the ideal baseline run through the identical harness."
  fi
  echo "  Not a conformance claim against any \`spec/target-spec.md\` row."
  echo "- **DUT**: \`design/netlist/lna.spice\` sha256 \`${DESIGN_NETLIST_SHA}\`, inlined verbatim"
  echo "  except the single inductor edit per variant (marked \`VARIANT EDIT\` in each"
  echo "  netlist snapshot). \`design/\` is not modified."
  echo "- **EM inductor model**: \`sim/models/sg13g2_inductor_em.spice\` sha256 \`${EM_SHA}\`"
  echo "  (stamped copy, provenance in \`sim/models/SOURCE.md\`)."
  echo "- **Bench definitions**: see \`README.md\` section \"Inductor-loss variants\"; every"
  echo "  generated netlist snapshot header and request JSON carries the exact analysis."
  echo "- **PDK**: \`${PDK}\` at \`${PDK_ROOT}\`; HBT sections from \`cornerHBT.lib\`, MOS from"
  echo "  \`cornerMOShv.lib\` with the same label->section map as \`run_lna_sweep.sh\`."
  echo "- **PDK identity (verified)**: \`${SIM_PDK_RELEASE}\` via ${SIM_PDK_ID_ROUTE}; model hashes in \`records/${RECORD_ID}.pdk-provenance.json\`"
  echo "- **Runner**: client \`${KLT_VERSION}\`; backend \`${EFFECTIVE_BACKEND}\`$([[ "${EFFECTIVE_BACKEND}" == batch ]] && echo " (--wait-for-capacity ${CAPACITY_WAIT} s)")."
  echo "  Jobs (klt \`environment.remote\`):"
  echo "${JOBS}"
  if [[ ${#FAILED[@]} -gt 0 ]]; then
    echo "- **Failed requests**: ${FAILED[*]}"
  else
    echo "- **Failed requests**: none."
  fi
  if (( SUMMARIZE_RC != 0 )); then
    echo "- **Reduction**: FAILED (exit ${SUMMARIZE_RC}) -- **coverage incomplete**; not a complete-grid result."
  elif [[ -n "${LNA_VARIANT_SMOKE:-}" ]]; then
    SMOKE_SLICE_NOTE=""
    [[ -n "${LNA_TEMPS:-}" ]] && SMOKE_SLICE_NOTE="; the requested temperature slice ${LNA_TEMPS} was ignored"
    echo "- **Reduction**: ok over the single nominal 27 C smoke cell only (plumbing check, all measurements finite${SMOKE_SLICE_NOTE}) -- NOT a PVT campaign."
  elif [[ -n "${LNA_TEMPS:-}" ]]; then
    echo "- **Reduction**: ok over the TEMPERATURE SLICE ${LNA_TEMPS} only (expected slice complete, all measurements finite) -- partial grid, NOT the full 45-cell PVT box."
  else
    echo "- **Reduction**: ok (expected grid complete, all measurements finite)."
  fi
  echo "- **Headlines (machine-generated)**:"
  echo
  cat "${CORNERS_OUT}/headlines.md" 2>/dev/null || echo "(none -- summarize found no reports)"
  echo
  echo "- **Links**: netlists+requests \`netlist-snapshots/${RECORD_ID}/\`; klt reports and"
  echo "  artifacts \`corners/${RECORD_ID}/\`; \`records/${RECORD_ID}-summary.csv\` (every"
  echo "  variant x cell x measurement); \`records/${RECORD_ID}-compare.csv\` (variant minus ideal)."
  echo "- **Timestamp / author**: $(date -u +%Y-%m-%dT%H:%M:%SZ), Loom Builder (agent), issue #56."
} > "${RECORDS_DIR}/${RECORD_ID}.md"

echo "run_lna_variant.sh: wrote ${RECORDS_DIR}/${RECORD_ID}.md"
if [[ ${#FAILED[@]} -gt 0 ]]; then
  echo "run_lna_variant.sh: failed: ${FAILED[*]}" >&2
  exit 1
fi
if (( SUMMARIZE_RC != 0 )); then
  exit 1
fi
