#!/usr/bin/env bash
# Joint emitter-degeneration / input-match study on the finite base feed (issue #198).
#
#   export PDK_ROOT=/path/to/ihp-open-pdk PDK=ihp-sg13g2   # or let sim/env.sh find it
#   MATCH_NGSPICE=/path/to/ngspice-46/bin/ngspice \
#     sim/lna-matching-feasibility/run_le_study.sh
#
# ONE PVT cell only (typ / 27 C / 1.80 V), by construction: no corner grid, no
# Monte Carlo and no knob that adds one. Each deck is a different circuit (feed
# x Le) with its own multi-analysis .control block (alter / wrdata / noise), so
# the study is a short sequence of single-cell decks, the convention of
# run_feed_study.sh (#193), not a corner matrix. A multi-corner confirmation
# belongs to a `klt sim` corners request on the fleet, never to a hand-launched
# grid on a shared host (and never as a local fallback).
#
# The point set, tolerances, selection / stopping rules and go/no-go policy are
# declared in le-study-declaration.md, generated from le_study.py and committed
# before the first run. The runner refuses to start if it is stale.
#
# Strictly one ngspice process at a time, at most 32 decks (28 as declared):
#   1. char_<point>     13 characterizations (Le explicit; feed swapped in)
#   2. verify_<point>   the three 1 nH controls first, then control-check
#                       (STOP if outside the declared tolerances), then the rest
#   3. bracket_<point>_{q5par,q10ser}   worse-Q and series-loss brackets on the
#                       shortlisted finite-feed point
#
# Environment knobs (all optional):
#   MATCH_NGSPICE=<path>  ngspice >= 46 (PSP103 OSDI v0.4).
#
# Output (append-only, sim/README.md layout), one record id for the whole study:
#   netlist-snapshots/<id>/  decks, le_plan.json, le_match_plan.json, le_shortlist.json
#   corners/<id>/            logs, wrdata tables, le_headlines.md, recommendation.json
#   records/<id>{.md,-le-points.csv,-le-control.csv,.pdk-provenance.json}
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SIM_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"

if [[ -n "${MATCH_NGSPICE:-}" ]]; then
  if [[ ! -x "${MATCH_NGSPICE}" ]]; then
    echo "run_le_study.sh: MATCH_NGSPICE=${MATCH_NGSPICE} is not executable." >&2
    exit 3
  fi
  PATH="$(cd "$(dirname "${MATCH_NGSPICE}")" && pwd):${PATH}"
  export PATH
fi

# shellcheck source-path=SCRIPTDIR
# shellcheck source=../env.sh
source "${SIM_DIR}/env.sh"

sim_require_pdk run_le_study.sh --osdi
command -v python3 >/dev/null 2>&1 || { echo "run_le_study.sh: python3 not on PATH." >&2; exit 3; }
NGSPICE_MAJOR="$(printf '%s\n' "${NGSPICE_VERSION}" | sed -n 's/.*ngspice-\([0-9][0-9]*\).*/\1/p')"
if [[ -z "${NGSPICE_MAJOR}" ]] || (( NGSPICE_MAJOR < 46 )); then
  echo "run_le_study.sh: need ngspice >= 46 (found '${NGSPICE_VERSION}'); set MATCH_NGSPICE." >&2
  exit 3
fi
CAP_LIB="${SG13G2_NGSPICE_MODELS}/cornerCAP.lib"
CAP_MOD="${SG13G2_NGSPICE_MODELS}/capacitors_mod.lib"
[[ -f "${CAP_LIB}" && -f "${CAP_MOD}" ]] || { echo "run_le_study.sh: ${CAP_LIB} / capacitors_mod.lib missing." >&2; exit 3; }
"${SIM_DIR}/models/check_sources.sh" || { echo "run_le_study.sh: sim/models hash check failed." >&2; exit 3; }
python3 -I "${SCRIPT_DIR}/le_study.py" declare | cmp -s - "${SCRIPT_DIR}/le-study-declaration.md" \
  || { echo "run_le_study.sh: le-study-declaration.md is stale vs le_study.py declare." >&2; exit 3; }

NGSPICE_BIN="$(command -v ngspice)"
NGSPICE_SHA="$(sha256sum "${NGSPICE_BIN}" | awk '{print $1}')"
DESIGN_NETLIST_SHA="$(sha256sum "${REPO_ROOT}/design/netlist/lna.spice" | awk '{print $1}')"
EM_SHA="$(sha256sum "${SIM_DIR}/models/sg13g2_inductor_em.spice" | awk '{print $1}')"
CAP_LIB_SHA="$(sha256sum "${CAP_LIB}" | awk '{print $1}')"
CAP_MOD_SHA="$(sha256sum "${CAP_MOD}" | awk '{print $1}')"
DECL_SHA="$(sha256sum "${SCRIPT_DIR}/le-study-declaration.md" | awk '{print $1}')"

sim_record_paths
LE=(python3 -I "${SCRIPT_DIR}/le_study.py")
PDK_ARGS=(--models-lib "${MODELS_LIB}" --mos-lib "${MOS_LIB}" --osdi-dir "${OSDI_DIR}" --cap-lib "${CAP_LIB}")
BUDGET=32

N_RUN=0
run_deck() {
  # run_deck <stem> [logpath]: one ngspice -b, cwd = the corners dir.
  local stem="$1" log="${2:-${CORNERS_OUT}/$1.log}" rc=0
  N_RUN=$(( N_RUN + 1 ))
  if (( N_RUN > BUDGET )); then
    echo "run_le_study.sh: deck budget ${BUDGET} exceeded at ${stem}" >&2
    exit 1
  fi
  ( cd "${CORNERS_OUT}" && ngspice -b "${SNAPSHOTS_OUT}/${stem}.spice" > "${log}" 2>&1 ) || rc=$?
  if (( rc != 0 )) || ! grep -q '^BENCH_COMPLETE' "${log}"; then
    echo "run_le_study.sh: ${stem} FAILED (rc=${rc}) -- see ${log}" >&2
    exit 1
  fi
}
stems() { "${LE[@]}" stems --snapdir "${SNAPSHOTS_OUT}" "$1"; }

echo "run_le_study.sh: record ${RECORD_ID}; ${NGSPICE_VERSION} (${NGSPICE_BIN}); nominal cell only"

"${LE[@]}" char-gen "${PDK_ARGS[@]}" --snapdir "${SNAPSHOTS_OUT}" --outdir "${CORNERS_OUT}"
while read -r s; do run_deck "${s}" "${CORNERS_OUT}/charset/${s#char_}/char.log"; done < <(stems char)
"${LE[@]}" solve "${PDK_ARGS[@]}" --snapdir "${SNAPSHOTS_OUT}" --outdir "${CORNERS_OUT}" --corners "${CORNERS_OUT}"

while read -r s; do run_deck "${s}"; done < <(stems control)
CONTROL_CSV="${RECORDS_DIR}/${RECORD_ID}-le-control.csv"
if ! "${LE[@]}" control-check --snapdir "${SNAPSHOTS_OUT}" --corners "${CORNERS_OUT}" --csv "${CONTROL_CSV}"; then
  echo "run_le_study.sh: STOP (declared stopping rule): a 1 nH control is outside tolerance; see ${CONTROL_CSV}." >&2
  exit 1
fi
while read -r s; do run_deck "${s}"; done < <(stems rest)

"${LE[@]}" shortlist "${PDK_ARGS[@]}" --snapdir "${SNAPSHOTS_OUT}" --outdir "${CORNERS_OUT}" --corners "${CORNERS_OUT}"
while read -r s; do run_deck "${s}"; done < <(stems bracket)

RED_RC=0
"${LE[@]}" reduce --snapdir "${SNAPSHOTS_OUT}" --corners "${CORNERS_OUT}" \
  --csv "${RECORDS_DIR}/${RECORD_ID}-le-points.csv" --control-csv "${CONTROL_CSV}" \
  --markdown "${CORNERS_OUT}/le_headlines.md" || RED_RC=$?

{
  echo "# Record ${RECORD_ID}"
  echo
  echo "- **Experiment**: lna-matching-feasibility, joint emitter degeneration (Le) / input match on the finite base feed (issue #198)."
  echo "- **Standing**: **NOMINAL-CELL EXPLORATION, NOT A RESULT.** One PVT cell (typ / 27 C / 1.80 V)."
  echo "  No number below is a conformance claim against any \`spec/target-spec.md\` row and nothing here is a"
  echo "  final-stability claim (the mu gate at every ratified cell stays with #27). Any production Le or feed"
  echo "  change needs a separate decision record and a complete PVT campaign. Ideal-choke numbers are diagnostic only."
  echo "- **Declaration (committed before the run)**: \`le-study-declaration.md\` sha256 \`${DECL_SHA}\`: point set,"
  echo "  model assumptions, control tolerances, selection / stopping rules and go/no-go policy."
  echo "- **DUT**: \`design/netlist/lna.spice\` sha256 \`${DESIGN_NETLIST_SHA}\`, unresized, inlined verbatim except the"
  echo "  \`BENCH EDIT\` lines (Le value and its loss resistor; R3b line replaced by the feed; Lc loss). R3b = 330 Ohm and"
  echo "  the bref reference are retained and the bias is not retuned. \`design/\` and \`spec/\` are not modified."
  echo "- **Feed plan**: reused from record \`20261010-233800-d1312cc\` (\`feed_plan.json\`, sha256 in \`le_plan.json\`)."
  echo "- **EM inductor model**: \`sim/models/sg13g2_inductor_em.spice\` sha256 \`${EM_SHA}\`."
  echo "- **Capacitor model**: PDK \`cap_cmim\`, \`cornerCAP.lib\` (cap_typ) sha256 \`${CAP_LIB_SHA}\`, \`capacitors_mod.lib\` sha256"
  echo "  \`${CAP_MOD_SHA}\`. No bottom-plate parasitic in the model."
  echo "- **Le model**: ideal L with an ASSUMED Q (10; bracket 5) as a parallel (DC-transparent) or series resistor; no"
  echo "  extracted model exists for these values. Not a layout feasibility claim."
  echo "- **PDK**: \`${PDK}\` at \`${PDK_ROOT}\`; \`hbt_typ\` + \`mos_tt\`; ${SIM_PDK_RELEASE} via ${SIM_PDK_ID_ROUTE}; model hashes in"
  echo "  \`records/${RECORD_ID}.pdk-provenance.json\` (the cap libraries are hashed above, outside that sidecar's closure)."
  echo "- **Simulator**: ${NGSPICE_VERSION}; binary \`${NGSPICE_BIN}\` sha256 \`${NGSPICE_SHA}\`; ${N_RUN} sequential single-process"
  echo "  nominal-cell decks (budget ${BUDGET}), no grid, no fleet submission."
  echo "- **Bench**: README.md \"Bench definitions\" and \"Joint Le / input-match study (issue #198)\": 50 Ohm \`sp\` ports,"
  echo "  \`sp lin 11 2.4e9 2.4835e9\` with donoise, \`sp dec 40 1e7 3e10\`, \`noise ... lin 21\` at T0 = 290 K, \`.options gmin=1e-10\`,"
  echo "  Rxoutdc = 1e11 Ohm on xout. Restated in every deck header."
  if (( RED_RC != 0 )); then
    echo "- **Reduction**: flagged (exit ${RED_RC}) -- see the problems list below."
  else
    echo "- **Reduction**: ok, no problems flagged."
  fi
  echo
  echo "### Machine-generated tables"
  echo
  cat "${CORNERS_OUT}/le_headlines.md" 2>/dev/null || echo "(none)"
  echo
  echo "- **Links**: decks, \`le_plan.json\`, \`le_match_plan.json\`, \`le_shortlist.json\` \`netlist-snapshots/${RECORD_ID}/\`; logs,"
  echo "  raw wrdata tables, \`recommendation.json\` \`corners/${RECORD_ID}/\`; \`records/${RECORD_ID}-le-points.csv\` (one row per"
  echo "  point and bracket), \`records/${RECORD_ID}-le-control.csv\` (1 nH control reproduction)."
  echo "- **Timestamp / author**: $(date -u +%Y-%m-%dT%H:%M:%SZ), Loom Builder (agent), issue #198."
} > "${RECORDS_DIR}/${RECORD_ID}.md"

echo "run_le_study.sh: wrote records/${RECORD_ID}.md"
if (( RED_RC != 0 )); then exit 1; fi
