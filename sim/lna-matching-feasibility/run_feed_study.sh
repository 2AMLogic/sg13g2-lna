#!/usr/bin/env bash
# Finite resonant base-feed study vs. the ideal-choke noise bound (issue #193).
#
#   export PDK_ROOT=/path/to/ihp-open-pdk PDK=ihp-sg13g2   # or let sim/env.sh find it
#   MATCH_NGSPICE=/path/to/ngspice-46/bin/ngspice \
#     sim/lna-matching-feasibility/run_feed_study.sh
#
# ONE PVT cell only (typ / 27 C / 1.80 V), by construction: no corner grid, no
# Monte Carlo and no knob that adds one. A multi-corner confirmation belongs to
# a `klt sim` corners request on a verified fleet, never to a hand-launched
# grid on a shared host (and never as a local fallback).
#
# The candidate set, model provenance and go/no-go policy are declared in
# feed-study-declaration.md, which is generated from feed_study.py and was
# committed before the first run.
#
# Strictly one ngspice process at a time, 16 decks:
#   1. tune.spice        EM series admittance of em1/em4/em5 -> tank C sizes
#   2. cmim_probe.spice  PDK cap_cmim one-port at the sized dimensions
#   3. scan_<variant>    8 feed variants: DC audit, sp + NF + Zopt, broadband sp,
#                        .noise NF at 290 K
#   4. char_<variant>    #186 characterization with R3b swapped (committed,
#                        ideal_choke, best valid finite feed)
#   5. match_<variant>_lp_noise_q10   re-synthesized input match verification,
#                        Rxoutdc = 1e11 Ohm on xout (#190 convention)
#
# Environment knobs (all optional):
#   MATCH_NGSPICE=<path>  ngspice >= 46 (PSP103 OSDI v0.4).
#
# Output (append-only, sim/README.md layout), one record id for the whole study:
#   netlist-snapshots/<id>/  decks, feed_plan.json, match_plan.json
#   corners/<id>/            logs, wrdata tables, scan_summary.json, recommendation.json
#   records/<id>{.md,-feeds.csv,-feeds-band.csv,-match.csv,.pdk-provenance.json}
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SIM_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"

if [[ -n "${MATCH_NGSPICE:-}" ]]; then
  if [[ ! -x "${MATCH_NGSPICE}" ]]; then
    echo "run_feed_study.sh: MATCH_NGSPICE=${MATCH_NGSPICE} is not executable." >&2
    exit 3
  fi
  PATH="$(cd "$(dirname "${MATCH_NGSPICE}")" && pwd):${PATH}"
  export PATH
fi

# shellcheck source-path=SCRIPTDIR
# shellcheck source=../env.sh
source "${SIM_DIR}/env.sh"

sim_require_pdk run_feed_study.sh --osdi
command -v python3 >/dev/null 2>&1 || { echo "run_feed_study.sh: python3 not on PATH." >&2; exit 3; }
NGSPICE_MAJOR="$(printf '%s\n' "${NGSPICE_VERSION}" | sed -n 's/.*ngspice-\([0-9][0-9]*\).*/\1/p')"
if [[ -z "${NGSPICE_MAJOR}" ]] || (( NGSPICE_MAJOR < 46 )); then
  echo "run_feed_study.sh: need ngspice >= 46 (found '${NGSPICE_VERSION}'); set MATCH_NGSPICE." >&2
  exit 3
fi
CAP_LIB="${SG13G2_NGSPICE_MODELS}/cornerCAP.lib"
CAP_MOD="${SG13G2_NGSPICE_MODELS}/capacitors_mod.lib"
[[ -f "${CAP_LIB}" && -f "${CAP_MOD}" ]] || { echo "run_feed_study.sh: ${CAP_LIB} / capacitors_mod.lib missing." >&2; exit 3; }
"${SIM_DIR}/models/check_sources.sh" || { echo "run_feed_study.sh: sim/models hash check failed." >&2; exit 3; }
# The declaration must match the code, or the run is not the declared study.
python3 -I "${SCRIPT_DIR}/feed_study.py" declare | cmp -s - "${SCRIPT_DIR}/feed-study-declaration.md" \
  || { echo "run_feed_study.sh: feed-study-declaration.md is stale vs feed_study.py declare." >&2; exit 3; }

NGSPICE_BIN="$(command -v ngspice)"
NGSPICE_SHA="$(sha256sum "${NGSPICE_BIN}" | awk '{print $1}')"
DESIGN_NETLIST_SHA="$(sha256sum "${REPO_ROOT}/design/netlist/lna.spice" | awk '{print $1}')"
EM_SHA="$(sha256sum "${SIM_DIR}/models/sg13g2_inductor_em.spice" | awk '{print $1}')"
CAP_LIB_SHA="$(sha256sum "${CAP_LIB}" | awk '{print $1}')"
CAP_MOD_SHA="$(sha256sum "${CAP_MOD}" | awk '{print $1}')"
DECL_SHA="$(sha256sum "${SCRIPT_DIR}/feed-study-declaration.md" | awk '{print $1}')"

sim_record_paths
FEED=(python3 -I "${SCRIPT_DIR}/feed_study.py")
PDK_ARGS=(--models-lib "${MODELS_LIB}" --mos-lib "${MOS_LIB}" --osdi-dir "${OSDI_DIR}" --cap-lib "${CAP_LIB}")

N_RUN=0
run_deck() {
  # run_deck <stem> [logpath]: one ngspice -b, cwd = the corners dir.
  local stem="$1" log="${2:-${CORNERS_OUT}/$1.log}" rc=0
  N_RUN=$(( N_RUN + 1 ))
  ( cd "${CORNERS_OUT}" && ngspice -b "${SNAPSHOTS_OUT}/${stem}.spice" > "${log}" 2>&1 ) || rc=$?
  if (( rc != 0 )) || ! grep -q '^BENCH_COMPLETE' "${log}"; then
    echo "run_feed_study.sh: ${stem} FAILED (rc=${rc}) -- see ${log}" >&2
    exit 1
  fi
}

echo "run_feed_study.sh: record ${RECORD_ID}; ${NGSPICE_VERSION} (${NGSPICE_BIN}); nominal cell only"

"${FEED[@]}" tune-gen --snapdir "${SNAPSHOTS_OUT}" --outdir "${CORNERS_OUT}"
run_deck tune
"${FEED[@]}" plan "${PDK_ARGS[@]}" --snapdir "${SNAPSHOTS_OUT}" --outdir "${CORNERS_OUT}"
run_deck cmim_probe
VARIANTS=(committed ideal_choke em5_cideal em5_cmim em5_cmim_bp10 em5_cq30 em4_cideal em4_cmim)
for v in "${VARIANTS[@]}"; do run_deck "scan_${v}"; done

SCAN_RC=0
"${FEED[@]}" scan-reduce --snapdir "${SNAPSHOTS_OUT}" --corners "${CORNERS_OUT}" \
  --csv "${RECORDS_DIR}/${RECORD_ID}-feeds.csv" --band-csv "${RECORDS_DIR}/${RECORD_ID}-feeds-band.csv" \
  --markdown "${CORNERS_OUT}/scan_headlines.md" || SCAN_RC=$?

"${FEED[@]}" match-gen "${PDK_ARGS[@]}" --snapdir "${SNAPSHOTS_OUT}" --outdir "${CORNERS_OUT}" --corners "${CORNERS_OUT}"
for deck in "${SNAPSHOTS_OUT}"/char_*.spice; do
  stem="$(basename "${deck}" .spice)"; v="${stem#char_}"
  run_deck "${stem}" "${CORNERS_OUT}/charset/${v}/char.log"
done
"${FEED[@]}" match-solve "${PDK_ARGS[@]}" --snapdir "${SNAPSHOTS_OUT}" --outdir "${CORNERS_OUT}" --corners "${CORNERS_OUT}"
for deck in "${SNAPSHOTS_OUT}"/match_*.spice; do run_deck "$(basename "${deck}" .spice)"; done

MATCH_RC=0
"${FEED[@]}" match-reduce --snapdir "${SNAPSHOTS_OUT}" --corners "${CORNERS_OUT}" \
  --csv "${RECORDS_DIR}/${RECORD_ID}-match.csv" --markdown "${CORNERS_OUT}/match_headlines.md" || MATCH_RC=$?

{
  echo "# Record ${RECORD_ID}"
  echo
  echo "- **Experiment**: lna-matching-feasibility, finite resonant base-bias feed vs the ideal-choke noise bound (issue #193)."
  echo "- **Standing**: **NOMINAL-CELL EXPLORATION, NOT A RESULT.** One PVT cell (typ / 27 C / 1.80 V)."
  echo "  No number below is a conformance claim against any \`spec/target-spec.md\` row and nothing here is a"
  echo "  final-stability claim (the mu gate at every ratified cell stays with #27). Any production bias-feed"
  echo "  change needs a separate decision record and a complete PVT campaign."
  echo "- **Declaration (committed before the run)**: \`feed-study-declaration.md\` sha256 \`${DECL_SHA}\`: candidate set,"
  echo "  model provenance, validity flags, best-feed rule and go/no-go policy."
  echo "- **DUT**: \`design/netlist/lna.spice\` sha256 \`${DESIGN_NETLIST_SHA}\`, unresized, inlined verbatim except the"
  echo "  \`BENCH EDIT\` lines (R3b line replaced by the variant's feed; Le / Lc loss in the matching decks). R3b = 330 Ohm and"
  echo "  the bref reference are retained and the bias is not retuned. \`design/\` and \`spec/\` are not modified."
  echo "- **EM inductor model**: \`sim/models/sg13g2_inductor_em.spice\` sha256 \`${EM_SHA}\` (3 extracted geometries, one process"
  echo "  point, one temperature)."
  echo "- **Capacitor model**: PDK \`cap_cmim\`, \`cornerCAP.lib\` (cap_typ) sha256 \`${CAP_LIB_SHA}\`, \`capacitors_mod.lib\` sha256"
  echo "  \`${CAP_MOD_SHA}\`. No bottom-plate parasitic in the model: bracketed, not claimed (see the declaration)."
  echo "- **PDK**: \`${PDK}\` at \`${PDK_ROOT}\`; \`hbt_typ\` + \`mos_tt\`; ${SIM_PDK_RELEASE} via ${SIM_PDK_ID_ROUTE}; model hashes in"
  echo "  \`records/${RECORD_ID}.pdk-provenance.json\` (the cap libraries are hashed above, outside that sidecar's closure)."
  echo "- **Simulator**: ${NGSPICE_VERSION}; binary \`${NGSPICE_BIN}\` sha256 \`${NGSPICE_SHA}\`; ${N_RUN} sequential single-process"
  echo "  nominal-cell decks, no grid, no fleet submission."
  echo "- **Bench**: README.md \"Bench definitions\" and \"Finite resonant base-feed study (issue #193)\": 50 Ohm \`sp\` ports,"
  echo "  \`sp lin 11 2.4e9 2.4835e9\` with donoise, \`sp dec 40 1e7 3e10\`, \`noise ... lin 21\` at T0 = 290 K, \`.options gmin=1e-10\`."
  echo "  Restated in every deck header."
  if (( SCAN_RC != 0 || MATCH_RC != 0 )); then
    echo "- **Reduction**: flagged (scan exit ${SCAN_RC}, match exit ${MATCH_RC}) -- see the problems lists below."
  else
    echo "- **Reduction**: ok, no problems flagged."
  fi
  echo
  echo "### Machine-generated tables"
  echo
  cat "${CORNERS_OUT}/scan_headlines.md" 2>/dev/null || echo "(none)"
  echo
  cat "${CORNERS_OUT}/match_headlines.md" 2>/dev/null || echo "(none)"
  echo
  echo "- **Links**: decks, \`feed_plan.json\`, \`match_plan.json\` \`netlist-snapshots/${RECORD_ID}/\`; logs, raw wrdata tables,"
  echo "  \`scan_summary.json\`, \`recommendation.json\` \`corners/${RECORD_ID}/\`; \`records/${RECORD_ID}-feeds.csv\` (one row per feed),"
  echo "  \`records/${RECORD_ID}-feeds-band.csv\` (per in-band frequency), \`records/${RECORD_ID}-match.csv\` (verified matched amplifier)."
  echo "- **Timestamp / author**: $(date -u +%Y-%m-%dT%H:%M:%SZ), Loom Builder (agent), issue #193."
} > "${RECORDS_DIR}/${RECORD_ID}.md"

echo "run_feed_study.sh: wrote records/${RECORD_ID}.md"
if (( SCAN_RC != 0 || MATCH_RC != 0 )); then exit 1; fi
