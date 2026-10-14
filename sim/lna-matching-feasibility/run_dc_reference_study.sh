#!/usr/bin/env bash
# DC-reference sensitivity study for the matching verification decks (issue #190).
#
#   MATCH_NGSPICE=/path/to/ngspice-46/bin/ngspice \
#     sim/lna-matching-feasibility/run_dc_reference_study.sh
#
# The #186 verification decks leave the DUT's rfout node (xout) connected only
# through capacitors, so every operating point is reached through ngspice's
# transient-op fallback (README.md "DC operating point"). This runner re-renders
# a bounded set of those decks with ONE explicit, noiseless bench resistor from
# xout to ground at each of several large values, runs them, and compares each
# against the retained historical (floating-xout) result of the same
# candidate / Q-case, so the resistor's RF effect is measured and not assumed.
#
# ONE PVT cell only (typ / 27 C / 1.80 V), nominal-cell exploration. No corner
# grid and no knob that adds one; the full-PVT confirmation stays with #27 and
# `klt sim` corners requests.
#
# Stages (DCREF_STAGE; default `all`):
#   gen     mint the record id, render the decks, print the exact ngspice
#           command for each deck, stop. For a shared host where the decks
#           are launched one at a time by the operator.
#   run     (needs DCREF_RECORD_ID) run each deck, strictly sequentially.
#   finish  (needs DCREF_RECORD_ID) classify convergence, build the
#           sensitivity table and write the record.
#   all     gen + run + finish.
#
# Environment knobs (all optional):
#   MATCH_NGSPICE=<path>   ngspice >= 46 (PSP103 OSDI v0.4).
#   DCREF_RDC=1e9,1e11     DC-reference values (Ohm), comma list.
#   DCREF_POINTS=lp_noise:q10,hp_power:q10,lp_noise:ideal,hp_power:ideal
#                          <candidate>:<qcase> points compared.
#   DCREF_BASELINE=20261010-201010-6aca84c
#                          historical record whose corners/ + characterization are the baseline.
#   MATCH_NF_NPTS=<n>      must equal the baseline's (default 21).
#   DCREF_RECORD_ID=<id>   record to run/finish (stages run, finish).
#
# Output (append-only, sim/README.md layout):
#   netlist-snapshots/<id>/  verify_*_rdc*.spice, candidates.json
#   corners/<id>/            ngspice logs + wrdata tables, sensitivity.md
#   records/<id>{.md,-sensitivity.csv,.pdk-provenance.json}
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SIM_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
STAGE="${DCREF_STAGE:-all}"
case "${STAGE}" in gen|run|finish|all) ;; *) echo "run_dc_reference_study.sh: bad DCREF_STAGE=${STAGE}" >&2; exit 2;; esac

if [[ -n "${MATCH_NGSPICE:-}" ]]; then
  if [[ ! -x "${MATCH_NGSPICE}" ]]; then
    echo "run_dc_reference_study.sh: MATCH_NGSPICE=${MATCH_NGSPICE} is not executable." >&2
    exit 3
  fi
  PATH="$(cd "$(dirname "${MATCH_NGSPICE}")" && pwd):${PATH}"
  export PATH
fi

# shellcheck source-path=SCRIPTDIR
# shellcheck source=../env.sh
source "${SIM_DIR}/env.sh"

sim_require_pdk run_dc_reference_study.sh --osdi
command -v python3 >/dev/null 2>&1 || { echo "run_dc_reference_study.sh: python3 not on PATH." >&2; exit 3; }
NGSPICE_MAJOR="$(printf '%s\n' "${NGSPICE_VERSION}" | sed -n 's/.*ngspice-\([0-9][0-9]*\).*/\1/p')"
if [[ -z "${NGSPICE_MAJOR}" ]] || (( NGSPICE_MAJOR < 46 )); then
  echo "run_dc_reference_study.sh: need ngspice >= 46 (found '${NGSPICE_VERSION}'); set MATCH_NGSPICE." >&2
  exit 3
fi
"${SIM_DIR}/models/check_sources.sh" || { echo "run_dc_reference_study.sh: sim/models hash check failed." >&2; exit 3; }

RDC="${DCREF_RDC:-1e9,1e11}"
POINTS="${DCREF_POINTS:-lp_noise:q10,hp_power:q10,lp_noise:ideal,hp_power:ideal}"
BASELINE="${DCREF_BASELINE:-20261010-201010-6aca84c}"
NF_NPTS="${MATCH_NF_NPTS:-21}"
BASE_CORNERS="${SCRIPT_DIR}/corners/${BASELINE}"
[[ -d "${BASE_CORNERS}" ]] || { echo "run_dc_reference_study.sh: baseline ${BASE_CORNERS} missing." >&2; exit 3; }

SOLVER=(python3 -I "${SCRIPT_DIR}/matching_solver.py")
PDK_ARGS=(--models-lib "${MODELS_LIB}" --mos-lib "${MOS_LIB}" --osdi-dir "${OSDI_DIR}")

if [[ "${STAGE}" == gen || "${STAGE}" == all ]]; then
  sim_record_paths
else
  RECORD_ID="${DCREF_RECORD_ID:?stage ${STAGE} needs DCREF_RECORD_ID}"
  SNAPSHOTS_OUT="${SCRIPT_DIR}/netlist-snapshots/${RECORD_ID}"
  CORNERS_OUT="${SCRIPT_DIR}/corners/${RECORD_ID}"
  RECORDS_DIR="${SCRIPT_DIR}/records"
  [[ -d "${SNAPSHOTS_OUT}" && -d "${CORNERS_OUT}" ]] || { echo "run_dc_reference_study.sh: record ${RECORD_ID} not found." >&2; exit 3; }
fi

run_deck() {
  local stem="$1" rc=0
  ( cd "${CORNERS_OUT}" && ngspice -b "${SNAPSHOTS_OUT}/${stem}.spice" > "${CORNERS_OUT}/${stem}.log" 2>&1 ) || rc=$?
  if (( rc != 0 )) || ! grep -q '^BENCH_COMPLETE' "${CORNERS_OUT}/${stem}.log"; then
    echo "run_dc_reference_study.sh: ${stem} FAILED (rc=${rc}) -- see corners/${RECORD_ID}/${stem}.log" >&2
    return 1
  fi
}

if [[ "${STAGE}" == gen || "${STAGE}" == all ]]; then
  echo "run_dc_reference_study.sh: record ${RECORD_ID}; ${NGSPICE_VERSION}; nominal cell only; R_xout in {${RDC}}; points ${POINTS}"
  "${SOLVER[@]}" solve "${PDK_ARGS[@]}" --snapdir "${SNAPSHOTS_OUT}" --outdir "${CORNERS_OUT}" \
    --char-dir "${BASE_CORNERS}" --nf-npts "${NF_NPTS}" --xout-rdc "${RDC}" --only "${POINTS}"
  if [[ "${STAGE}" == gen ]]; then
    echo "run_dc_reference_study.sh: DCREF_RECORD_ID=${RECORD_ID}; decks to run (cwd ${CORNERS_OUT}):"
    for deck in "${SNAPSHOTS_OUT}"/verify_*.spice; do
      echo "  ngspice -b ${deck} > ${CORNERS_OUT}/$(basename "${deck}" .spice).log 2>&1"
    done
  fi
fi

FAILED=()
N_RUN=0
if [[ "${STAGE}" == run || "${STAGE}" == all ]]; then
  for deck in "${SNAPSHOTS_OUT}"/verify_*.spice; do
    stem="$(basename "${deck}" .spice)"
    N_RUN=$(( N_RUN + 1 ))
    run_deck "${stem}" || FAILED+=("${stem}")
  done
fi

if [[ "${STAGE}" == finish || "${STAGE}" == all ]]; then
  for deck in "${SNAPSHOTS_OUT}"/verify_*.spice; do
    stem="$(basename "${deck}" .spice)"
    N_RUN=$(( N_RUN + 1 ))
    grep -q '^BENCH_COMPLETE' "${CORNERS_OUT}/${stem}.log" 2>/dev/null || FAILED+=("${stem}")
  done
  SENS_RC=0
  "${SOLVER[@]}" sensitivity --candidates "${SNAPSHOTS_OUT}/candidates.json" --corners "${CORNERS_OUT}" \
    --baseline-corners "${BASE_CORNERS}" --csv "${RECORDS_DIR}/${RECORD_ID}-sensitivity.csv" \
    --markdown "${CORNERS_OUT}/sensitivity.md" || SENS_RC=$?
  DESIGN_NETLIST_SHA="$(sha256sum "${REPO_ROOT}/design/netlist/lna.spice" | awk '{print $1}')"
  NGSPICE_SHA="$(sha256sum "$(command -v ngspice)" | awk '{print $1}')"
  {
    echo "# Record ${RECORD_ID}"
    echo
    echo "- **Experiment**: lna-matching-feasibility, DC-reference sensitivity of the matching verification decks (issue #190)."
    echo "- **Standing**: **NOMINAL-CELL EXPLORATION, NOT A RESULT.** One PVT cell (typ / 27 C / 1.80 V)."
    echo "  No number below is a conformance claim against any \`spec/target-spec.md\` row, and nothing here is a"
    echo "  stability claim: the mu gate at every ratified cell stays with #27."
    echo "- **Claim under test**: an explicit noiseless resistor from xout to ground, added as a bench element,"
    echo "  gives the verification decks a normal operating-point convergence; how much it changes the"
    echo "  operating point, S-parameters, NF290 and the ppm-scale mu margin of the #186 decks."
    echo "- **Baseline**: historical record \`${BASELINE}\` (floating xout, transient-op fallback), same candidate / Q"
    echo "  points, same nominal cell, same netlist generator, characterization data re-used unchanged."
    echo "- **Bench element**: \`Rxoutdc xout vss <R> noisy=0\` inside the \`lnam\` subcircuit, R in {${RDC}} Ohm."
    echo "  Points: ${POINTS}. Bench definitions otherwise exactly as README.md \"Bench definitions\" (50 Ohm \`sp\`"
    echo "  ports, \`sp lin 11\`, \`sp dec 40 1e7 3e10\`, \`.noise\` at T0 = 290 K, \`.options gmin=1e-10\`)."
    echo "- **DUT**: \`design/netlist/lna.spice\` sha256 \`${DESIGN_NETLIST_SHA}\`, unmodified apart from the \`BENCH EDIT\` lines;"
    echo "  \`design/\` and \`spec/\` are not modified."
    echo "- **PDK**: \`${PDK}\` at \`${PDK_ROOT}\`; \`hbt_typ\` + \`mos_tt\`; ${SIM_PDK_RELEASE} via ${SIM_PDK_ID_ROUTE}."
    echo "- **Simulator**: ${NGSPICE_VERSION}; binary sha256 \`${NGSPICE_SHA}\`; ${N_RUN} single-process nominal-cell decks, no grid."
    if [[ ${#FAILED[@]} -gt 0 ]]; then echo "- **Failed decks**: ${FAILED[*]}"; else echo "- **Failed decks**: none."; fi
    if (( SENS_RC != 0 )); then echo "- **Reduction**: FAILED or flagged (exit ${SENS_RC}) -- see the problems list below."; else echo "- **Reduction**: ok; every new deck shows normal OP convergence."; fi
    echo
    echo "### Machine-generated sensitivity table"
    echo
    cat "${CORNERS_OUT}/sensitivity.md" 2>/dev/null || echo "(none)"
    echo
    echo "- **Links**: decks and \`candidates.json\` \`netlist-snapshots/${RECORD_ID}/\`; logs and wrdata \`corners/${RECORD_ID}/\`;"
    echo "  \`records/${RECORD_ID}-sensitivity.csv\` (one row per candidate x Q case x R)."
    echo "- **Timestamp / author**: $(date -u +%Y-%m-%dT%H:%M:%SZ), Loom Builder (agent), issue #190."
  } > "${RECORDS_DIR}/${RECORD_ID}.md"
  echo "run_dc_reference_study.sh: wrote records/${RECORD_ID}.md"
  if [[ ${#FAILED[@]} -gt 0 ]] || (( SENS_RC != 0 )); then exit 1; fi
fi
