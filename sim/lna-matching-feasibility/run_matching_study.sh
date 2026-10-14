#!/usr/bin/env bash
# Nominal-cell matching-network feasibility study (issue #186).
#
#   export PDK_ROOT=/path/to/ihp-open-pdk PDK=ihp-sg13g2   # or let sim/env.sh find it
#   MATCH_NGSPICE=/path/to/ngspice-46/bin/ngspice \
#     sim/lna-matching-feasibility/run_matching_study.sh
#
# ONE PVT cell only (typ / 27 C / 1.80 V), by construction: this runner has
# no corner grid and no knob that adds one. It is a design-exploration bench,
# not a PVT campaign -- the 45-cell confirmation of whichever network #27
# adopts belongs to `klt sim` corners requests (sim/lna-characterization/
# run_lna_variant.sh), never to a hand-launched grid on a shared host.
#
# What it runs, strictly one ngspice process at a time:
#   1. char.spice       DUT two-port + noise parameters per Le-loss case,
#                       collector-node admittance (Lc -> ideal choke), an
#                       ideal-Le sweep, and the three EM inductor geometries
#   2. char_feed.spice  what-if probe: the same Le sweep with Q1's base-bias
#                       feed resistor R3b isolated at RF by an ideal choke
#   3. matching_solver.py solve: synthesize each candidate network for each
#                       Q case and render one verification deck per pair
#   4. verify_<candidate>_<qcase>.spice, one at a time: sp (in-band, with
#                       ngspice two-port NF), broadband sp stability
#                       10 MHz..30 GHz, .noise NF at T0 = 290 K
#   5. matching_solver.py reduce: per-candidate metrics, ranking, record
#
# Every deck is a few seconds of single-threaded ngspice; the whole study is
# 14 sequential invocations. Bench definitions: README.md in this directory.
#
# Environment knobs (all optional):
#   MATCH_NGSPICE=<path>  ngspice binary to use (default: `ngspice` on PATH).
#                         Must be ngspice >= 46: the PDK's PSP103 OSDI builds
#                         target OSDI v0.4, which older ngspice cannot load.
#   MATCH_NF_NPTS=<n>     points of the 290 K NF sweep (odd, >= 11; default 21).
#
# Output (append-only, sim/README.md layout):
#   netlist-snapshots/<record-id>/  char*.spice, verify_*.spice, candidates.json
#   corners/<record-id>/            ngspice logs + wrdata tables, headlines.md
#   records/<record-id>{.md,-candidates.csv,-band.csv,.pdk-provenance.json}
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SIM_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"

if [[ -n "${MATCH_NGSPICE:-}" ]]; then
  if [[ ! -x "${MATCH_NGSPICE}" ]]; then
    echo "run_matching_study.sh: MATCH_NGSPICE=${MATCH_NGSPICE} is not executable." >&2
    exit 3
  fi
  PATH="$(cd "$(dirname "${MATCH_NGSPICE}")" && pwd):${PATH}"
  export PATH
fi

# shellcheck source-path=SCRIPTDIR
# shellcheck source=../env.sh
source "${SIM_DIR}/env.sh"

sim_require_pdk run_matching_study.sh --osdi
command -v python3 >/dev/null 2>&1 || { echo "run_matching_study.sh: python3 not on PATH." >&2; exit 3; }

NGSPICE_MAJOR="$(printf '%s\n' "${NGSPICE_VERSION}" | sed -n 's/.*ngspice-\([0-9][0-9]*\).*/\1/p')"
if [[ -z "${NGSPICE_MAJOR}" ]] || (( NGSPICE_MAJOR < 46 )); then
  echo "run_matching_study.sh: need ngspice >= 46 (found '${NGSPICE_VERSION}'); set MATCH_NGSPICE." >&2
  exit 3
fi
NGSPICE_BIN="$(command -v ngspice)"

"${SIM_DIR}/models/check_sources.sh" || { echo "run_matching_study.sh: sim/models hash check failed." >&2; exit 3; }

NF_NPTS="${MATCH_NF_NPTS:-21}"
DESIGN_NETLIST_SHA="$(sha256sum "${REPO_ROOT}/design/netlist/lna.spice" | awk '{print $1}')"
EM_SHA="$(sha256sum "${SIM_DIR}/models/sg13g2_inductor_em.spice" | awk '{print $1}')"

sim_record_paths
SOLVER=(python3 -I "${SCRIPT_DIR}/matching_solver.py")
PDK_ARGS=(--models-lib "${MODELS_LIB}" --mos-lib "${MOS_LIB}" --osdi-dir "${OSDI_DIR}")

run_deck() {
  # run_deck <stem>: one ngspice -b, cwd = the corners dir, log beside it.
  local stem="$1" rc=0
  ( cd "${CORNERS_OUT}" && ngspice -b "${SNAPSHOTS_OUT}/${stem}.spice" > "${CORNERS_OUT}/${stem}.log" 2>&1 ) || rc=$?
  if (( rc != 0 )) || ! grep -q '^BENCH_COMPLETE' "${CORNERS_OUT}/${stem}.log"; then
    echo "run_matching_study.sh: ${stem} FAILED (rc=${rc}) -- see corners/${RECORD_ID}/${stem}.log" >&2
    return 1
  fi
}

echo "run_matching_study.sh: record ${RECORD_ID}; ${NGSPICE_VERSION} (${NGSPICE_BIN}); nominal cell only"
"${SOLVER[@]}" gen-char "${PDK_ARGS[@]}" --snapdir "${SNAPSHOTS_OUT}" --outdir "${CORNERS_OUT}"
run_deck char
run_deck char_feed
"${SOLVER[@]}" solve "${PDK_ARGS[@]}" --snapdir "${SNAPSHOTS_OUT}" --outdir "${CORNERS_OUT}" --nf-npts "${NF_NPTS}"

FAILED=()
N_RUN=2
for deck in "${SNAPSHOTS_OUT}"/verify_*.spice; do
  stem="$(basename "${deck}" .spice)"
  N_RUN=$(( N_RUN + 1 ))
  run_deck "${stem}" || FAILED+=("${stem}")
done

REDUCE_RC=0
"${SOLVER[@]}" reduce --candidates "${SNAPSHOTS_OUT}/candidates.json" --corners "${CORNERS_OUT}" \
  --candidates-csv "${RECORDS_DIR}/${RECORD_ID}-candidates.csv" \
  --band-csv "${RECORDS_DIR}/${RECORD_ID}-band.csv" \
  --markdown "${CORNERS_OUT}/headlines.md" || REDUCE_RC=$?

{
  echo "# Record ${RECORD_ID}"
  echo
  echo "- **Experiment**: lna-matching-feasibility, nominal-cell matching-network feasibility study (issue #186)."
  echo "- **Standing**: **NOMINAL-CELL EXPLORATION, NOT A RESULT.** One PVT cell (typ / 27 C / 1.80 V)."
  echo "  No number below is a conformance claim against any \`spec/target-spec.md\` row: CLAUDE.md"
  echo "  requires PVT corners on every recorded result, and the stability gate (mu at every ratified"
  echo "  cell before a match is final) stays with #27. Row columns only say whether the nominal-cell"
  echo "  number is on the right side of the ratified bar."
  echo "- **Claim under test**: which input/output matching topology and element values the committed"
  echo "  DUT admits at the nominal cell with lossy inductors (ideal, Q = 20, Q = 10, EM-extracted Lc),"
  echo "  and which ratified rows each candidate plausibly meets there."
  echo "- **DUT**: \`design/netlist/lna.spice\` sha256 \`${DESIGN_NETLIST_SHA}\`, inlined verbatim except the"
  echo "  edits marked \`BENCH EDIT\` in each snapshot (Le parallel loss R; Lc loss / EM model; the feed"
  echo "  what-if). \`design/\` and \`spec/\` are not modified."
  echo "- **EM inductor model**: \`sim/models/sg13g2_inductor_em.spice\` sha256 \`${EM_SHA}\` (stamped copy;"
  echo "  one process point, one temperature, three extracted geometries -- see \`sim/models/SOURCE.md\`)."
  echo "- **Bench**: README.md \"Bench definitions\": 50 Ohm \`sp\` ports, \`sp lin 11 2.4e9 2.4835e9 1\`,"
  echo "  \`sp dec 40 1e7 3e10\` (mu, k), \`noise v(nfout) vin lin ${NF_NPTS} 2.4e9 2.4835e9\` with noiseless"
  echo "  50 Ohm Rs/RL and the source term at T0 = 290 K, \`.options gmin=1e-10\`. Restated in every deck header."
  echo "- **PDK**: \`${PDK}\` at \`${PDK_ROOT}\`; \`hbt_typ\` + \`mos_tt\`."
  echo "- **PDK identity (verified)**: \`${SIM_PDK_RELEASE}\` via ${SIM_PDK_ID_ROUTE}; model hashes in \`records/${RECORD_ID}.pdk-provenance.json\`"
  echo "- **Simulator**: ${NGSPICE_VERSION}; ${N_RUN} sequential single-process invocations, no grid."
  if [[ ${#FAILED[@]} -gt 0 ]]; then
    echo "- **Failed decks**: ${FAILED[*]}"
  else
    echo "- **Failed decks**: none."
  fi
  if (( REDUCE_RC != 0 )); then
    echo "- **Reduction**: FAILED (exit ${REDUCE_RC}) -- see the problems list below."
  else
    echo "- **Reduction**: ok."
  fi
  echo
  echo "### Machine-generated tables"
  echo
  cat "${CORNERS_OUT}/headlines.md" 2>/dev/null || echo "(none)"
  echo
  echo "- **Links**: decks and \`candidates.json\` (solver inputs/outputs, element values, predictions,"
  echo "  feasibility) \`netlist-snapshots/${RECORD_ID}/\`; logs and raw wrdata tables \`corners/${RECORD_ID}/\`;"
  echo "  \`records/${RECORD_ID}-candidates.csv\` (one row per candidate x Q case);"
  echo "  \`records/${RECORD_ID}-band.csv\` (per in-band frequency)."
  echo "- **Timestamp / author**: $(date -u +%Y-%m-%dT%H:%M:%SZ), Loom Builder (agent), issue #186."
} > "${RECORDS_DIR}/${RECORD_ID}.md"

echo "run_matching_study.sh: wrote records/${RECORD_ID}.md"
if [[ ${#FAILED[@]} -gt 0 ]] || (( REDUCE_RC != 0 )); then
  exit 1
fi
