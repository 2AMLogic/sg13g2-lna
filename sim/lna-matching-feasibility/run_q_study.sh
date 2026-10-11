#!/usr/bin/env bash
# Feed-isolation / input-Q requirements map after the Le-study NO-GO (issue #200).
#
#   export PDK_ROOT=/path/to/ihp-open-pdk PDK=ihp-sg13g2   # or let sim/env.sh find it
#   MATCH_NGSPICE=/path/to/ngspice-46/bin/ngspice \
#     sim/lna-matching-feasibility/run_q_study.sh
#
# ONE PVT cell only (typ / 27 C / 1.80 V), by construction: no corner grid, no
# Monte Carlo and no knob that adds one. Each deck is a different circuit with
# its own multi-analysis .control block, so the study is a short sequence of
# single-cell decks, the convention of run_le_study.sh (#198), not a corner
# matrix. A multi-corner confirmation belongs to a `klt sim` corners request on
# the fleet, never to a hand-launched grid on a shared host (and never as a
# local fallback).
#
# The map, bracket set, control tolerances, boundary rules and verdict policy
# are declared in q-study-declaration.md, generated from q_study.py and
# committed before the first run. The runner refuses to start if it is stale.
#
# Strictly one ngspice process at a time, at most 16 decks (11 planned):
#   1. char_ctl_*      2 char controls (re-renders of the retained #198 decks,
#                      identical modulo checkout paths) + the tank probe, then
#                      control-check (STOP if outside the declared tolerances)
#   2. verify_ctl_*    2 control verifications, then ctl-verify-check (STOP)
#   3. char_bracket_*  the three hypothetical feed-loss proxy characterizations
#   4. qmap            the input-Q requirements map (predictions from the
#                      RETAINED #198 characterization) + boundary verify decks
#   5. verify_bound_*  the declared boundary verifications
#
# Environment knobs (all optional):
#   MATCH_NGSPICE=<path>  ngspice >= 46 (PSP103 OSDI v0.4).
#
# Output (append-only, sim/README.md layout), one record id for the whole study:
#   netlist-snapshots/<id>/  decks, qreq_plan.json, qreq_ctl_verify.json, qreq_map.json
#   corners/<id>/            logs, wrdata tables, qreq_headlines.md, recommendation.json
#   records/<id>{.md,-isolation.csv,-qmap.csv,-control-char.csv,-control-verify.csv,
#                .pdk-provenance.json}
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SIM_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"

if [[ -n "${MATCH_NGSPICE:-}" ]]; then
  if [[ ! -x "${MATCH_NGSPICE}" ]]; then
    echo "run_q_study.sh: MATCH_NGSPICE=${MATCH_NGSPICE} is not executable." >&2
    exit 3
  fi
  PATH="$(cd "$(dirname "${MATCH_NGSPICE}")" && pwd):${PATH}"
  export PATH
fi

# shellcheck source-path=SCRIPTDIR
# shellcheck source=../env.sh
source "${SIM_DIR}/env.sh"

sim_require_pdk run_q_study.sh --osdi
command -v python3 >/dev/null 2>&1 || { echo "run_q_study.sh: python3 not on PATH." >&2; exit 3; }
NGSPICE_MAJOR="$(printf '%s\n' "${NGSPICE_VERSION}" | sed -n 's/.*ngspice-\([0-9][0-9]*\).*/\1/p')"
if [[ -z "${NGSPICE_MAJOR}" ]] || (( NGSPICE_MAJOR < 46 )); then
  echo "run_q_study.sh: need ngspice >= 46 (found '${NGSPICE_VERSION}'); set MATCH_NGSPICE." >&2
  exit 3
fi
CAP_LIB="${SG13G2_NGSPICE_MODELS}/cornerCAP.lib"
CAP_MOD="${SG13G2_NGSPICE_MODELS}/capacitors_mod.lib"
[[ -f "${CAP_LIB}" && -f "${CAP_MOD}" ]] || { echo "run_q_study.sh: ${CAP_LIB} / capacitors_mod.lib missing." >&2; exit 3; }
"${SIM_DIR}/models/check_sources.sh" || { echo "run_q_study.sh: sim/models hash check failed." >&2; exit 3; }
python3 -I "${SCRIPT_DIR}/q_study.py" declare | cmp -s - "${SCRIPT_DIR}/q-study-declaration.md" \
  || { echo "run_q_study.sh: q-study-declaration.md is stale vs q_study.py declare." >&2; exit 3; }

NGSPICE_BIN="$(command -v ngspice)"
NGSPICE_SHA="$(sha256sum "${NGSPICE_BIN}" | awk '{print $1}')"
DESIGN_NETLIST_SHA="$(sha256sum "${REPO_ROOT}/design/netlist/lna.spice" | awk '{print $1}')"
EM_SHA="$(sha256sum "${SIM_DIR}/models/sg13g2_inductor_em.spice" | awk '{print $1}')"
CAP_LIB_SHA="$(sha256sum "${CAP_LIB}" | awk '{print $1}')"
CAP_MOD_SHA="$(sha256sum "${CAP_MOD}" | awk '{print $1}')"
DECL_SHA="$(sha256sum "${SCRIPT_DIR}/q-study-declaration.md" | awk '{print $1}')"

sim_record_paths
Q=(python3 -I "${SCRIPT_DIR}/q_study.py")
PDK_ARGS=(--models-lib "${MODELS_LIB}" --mos-lib "${MOS_LIB}" --osdi-dir "${OSDI_DIR}" --cap-lib "${CAP_LIB}")
BUDGET=16

N_RUN=0
run_deck() {
  # run_deck <stem> [logpath]: one ngspice -b, cwd = the corners dir.
  local stem="$1" log="${2:-${CORNERS_OUT}/$1.log}" rc=0
  N_RUN=$(( N_RUN + 1 ))
  if (( N_RUN > BUDGET )); then
    echo "run_q_study.sh: deck budget ${BUDGET} exceeded at ${stem}" >&2
    exit 1
  fi
  ( cd "${CORNERS_OUT}" && ngspice -b "${SNAPSHOTS_OUT}/${stem}.spice" > "${log}" 2>&1 ) || rc=$?
  if (( rc != 0 )) || ! grep -q '^BENCH_COMPLETE' "${log}"; then
    echo "run_q_study.sh: ${stem} FAILED (rc=${rc}) -- see ${log}" >&2
    exit 1
  fi
}
stems() { "${Q[@]}" stems --snapdir "${SNAPSHOTS_OUT}" "$1"; }

echo "run_q_study.sh: record ${RECORD_ID}; ${NGSPICE_VERSION} (${NGSPICE_BIN}); nominal cell only"

# --- 1. static decks: char controls (byte-checked vs retained) + probe -------
"${Q[@]}" control-gen "${PDK_ARGS[@]}" --snapdir "${SNAPSHOTS_OUT}" --outdir "${CORNERS_OUT}"
while read -r s; do run_deck "${s}" "${CORNERS_OUT}/charset/${s#char_ctl_}/char.log"; done < <(stems ctlchar)
while read -r s; do run_deck "${s}"; done < <(stems probe)

CONTROL_CSV="${RECORDS_DIR}/${RECORD_ID}-control-char.csv"
if ! "${Q[@]}" control-check --snapdir "${SNAPSHOTS_OUT}" --corners "${CORNERS_OUT}" --csv "${CONTROL_CSV}"; then
  echo "run_q_study.sh: STOP (declared stopping rule): a level-1 control is outside tolerance; see ${CONTROL_CSV}." >&2
  exit 1
fi

# --- 2. control verifications (networks re-synthesized from the fresh char) --
"${Q[@]}" ctl-verify-gen "${PDK_ARGS[@]}" --snapdir "${SNAPSHOTS_OUT}" --outdir "${CORNERS_OUT}" --corners "${CORNERS_OUT}"
while read -r s; do run_deck "${s}"; done < <(stems ctlverify)
CONTROL_CSV="${RECORDS_DIR}/${RECORD_ID}-control-verify.csv"
if ! "${Q[@]}" ctl-verify-check --snapdir "${SNAPSHOTS_OUT}" --corners "${CORNERS_OUT}" --csv "${CONTROL_CSV}"; then
  echo "run_q_study.sh: STOP (declared stopping rule): a level-2 control is outside tolerance; see ${CONTROL_CSV}." >&2
  exit 1
fi

# --- 3. bracket characterizations (hypothetical requirement proxies) ---------
while read -r s; do
  run_deck "${s}" "${CORNERS_OUT}/charset/${s#char_bracket_}/char.log"
done < <(stems bracket)

# --- 4. the requirements map + declared boundary verifications ---------------
"${Q[@]}" qmap "${PDK_ARGS[@]}" --snapdir "${SNAPSHOTS_OUT}" --outdir "${CORNERS_OUT}"
while read -r s; do
  [[ -n "${s}" ]] || continue
  run_deck "${s}"
done < <(stems boundary)

# --- 5. reduction ------------------------------------------------------------
RED_RC=0
"${Q[@]}" reduce --snapdir "${SNAPSHOTS_OUT}" --corners "${CORNERS_OUT}" \
  --isolation-csv "${RECORDS_DIR}/${RECORD_ID}-isolation.csv" \
  --map-csv "${RECORDS_DIR}/${RECORD_ID}-qmap.csv" \
  --markdown "${CORNERS_OUT}/qreq_headlines.md" || RED_RC=$?

{
  echo "# Record ${RECORD_ID}"
  echo
  echo "- **Experiment**: lna-matching-feasibility, feed-isolation / input-Q requirements map after the"
  echo "  Le-study NO-GO (issue #200)."
  echo "- **Standing**: **NOMINAL-CELL EXPLORATION, NOT A RESULT.** One PVT cell (typ / 27 C / 1.80 V)."
  echo "  No number below is a conformance claim against any \`spec/target-spec.md\` row and nothing here is a"
  echo "  final-stability claim (the mu gate at every ratified cell stays with #27). This study MAPS"
  echo "  REQUIREMENTS: every map cell is a prediction, every bracket point is a hypothetical requirement"
  echo "  proxy, the ideal-choke numbers are diagnostic, and none of them can authorize production or PVT"
  echo "  work. \`design/\` and \`spec/\` are not modified."
  echo "- **Declaration (committed before the run)**: \`q-study-declaration.md\` sha256 \`${DECL_SHA}\`: map and"
  echo "  bracket set, reused-evidence provenance, control tolerances, boundary rules, stopping rules and"
  echo "  the separate requirements / campaign verdict policy."
  echo "- **DUT**: \`design/netlist/lna.spice\` sha256 \`${DESIGN_NETLIST_SHA}\`, unresized, inlined verbatim except the"
  echo "  \`BENCH EDIT\` lines (Le value and its loss resistor; R3b line replaced by the feed; Lc loss; the"
  echo "  bracket's tank-parallel resistor). R3b = 330 Ohm and the bref reference are retained and the bias"
  echo "  is not retuned."
  echo "- **Reused retained evidence**: characterization tables, match plan and feed plan of record"
  echo "  \`20261011-101454-3ec590d\` (#198) and the Yser grid / cmim probe of record"
  echo "  \`20261010-233800-d1312cc\` (#193); hashes in \`qreq_plan.json\`; the char control decks were"
  echo "  re-rendered byte for byte and re-run as the level-1 control."
  echo "- **EM inductor model**: \`sim/models/sg13g2_inductor_em.spice\` sha256 \`${EM_SHA}\`, unmodified; the"
  echo "  bracket edit is one thermal-noisy, DC-transparent parallel resistor ACROSS the retained tank."
  echo "- **Capacitor model**: PDK \`cap_cmim\`, \`cornerCAP.lib\` (cap_typ) sha256 \`${CAP_LIB_SHA}\`,"
  echo "  \`capacitors_mod.lib\` sha256 \`${CAP_MOD_SHA}\`. No bottom-plate parasitic in the model."
  echo "- **PDK**: \`${PDK}\` at \`${PDK_ROOT}\`; \`hbt_typ\` + \`mos_tt\`; ${SIM_PDK_RELEASE} via ${SIM_PDK_ID_ROUTE}; model hashes in"
  echo "  \`records/${RECORD_ID}.pdk-provenance.json\` (the cap libraries are hashed above, outside that sidecar's closure)."
  echo "- **Simulator**: ${NGSPICE_VERSION}; binary \`${NGSPICE_BIN}\` sha256 \`${NGSPICE_SHA}\`; ${N_RUN} sequential single-process"
  echo "  nominal-cell decks (budget ${BUDGET}, 8 char-class + 8 verify caps), no grid, no fleet submission."
  echo "- **Bench**: README.md \"Bench definitions\" and \"Feed-isolation / input-Q requirements study"
  echo "  (issue #200)\": 50 Ohm \`sp\` ports, \`sp lin 11 2.4e9 2.4835e9\` with donoise, \`sp dec 40 1e7 3e10\`,"
  echo "  \`noise ... lin 21\` at T0 = 290 K, \`.options gmin=1e-10\`, Rxoutdc = 1e11 Ohm on xout. Restated in"
  echo "  every deck header."
  if (( RED_RC != 0 )); then
    echo "- **Reduction**: flagged (exit ${RED_RC}) -- see the problems list below."
  else
    echo "- **Reduction**: ok, no problems flagged."
  fi
  echo
  echo "### Machine-generated tables"
  echo
  cat "${CORNERS_OUT}/qreq_headlines.md" 2>/dev/null || echo "(none)"
  echo
  echo "- **Links**: decks, \`qreq_plan.json\`, \`qreq_ctl_verify.json\`, \`qreq_map.json\`"
  echo "  \`netlist-snapshots/${RECORD_ID}/\`; logs, raw wrdata tables, \`recommendation.json\`"
  echo "  \`corners/${RECORD_ID}/\`; \`records/${RECORD_ID}-qmap.csv\` (one row per arm x input-Q cell),"
  echo "  \`records/${RECORD_ID}-isolation.csv\` (probe + bracket isolation / NFmin table),"
  echo "  \`records/${RECORD_ID}-control-char.csv\` and \`-control-verify.csv\` (level-1 and level-2"
  echo "  control reproduction)."
  echo "- **Timestamp / author**: $(date -u +%Y-%m-%dT%H:%M:%SZ), Loom Builder (agent), issue #200."
} > "${RECORDS_DIR}/${RECORD_ID}.md"

echo "run_q_study.sh: wrote records/${RECORD_ID}.md"
if (( RED_RC != 0 )); then exit 1; fi
