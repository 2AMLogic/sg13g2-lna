# Source me with the study identity (issue #450):
#
#   source "${SCRIPT_DIR}/study_prelude.sh" <script-name> <study-module> <declaration-file>
#
# The shared matching-study preflight. run_feed_study.sh (#193), run_le_study.sh
# (#198) and run_q_study.sh (#200) each carried a byte-identical copy of the
# same startup sequence -- MATCH_NGSPICE override through the declaration hash
# -- so a change to the simulator floor, a model check or a provenance hash
# needed three matching edits. The sequence is stated once here; each runner
# passes its own identity in (its script name for messages, its python module
# and its committed declaration for the freshness check). This follows the
# shared-runner work of #300 (sim_run_deck, which took deck execution); record
# creation, deck sequencing, budgets and report formatting stay in each runner.
#
# The caller must have set SCRIPT_DIR (its own experiment directory) and runs
# under `set -euo pipefail`, as the sourcing runners do. On success the caller
# sees exactly the state its own copy used to leave behind: sim/env.sh sourced
# (SIM_DIR, REPO_ROOT, the sim_* helpers and, via sim_require_pdk, the PDK /
# ngspice resolution and identity results), CAP_LIB / CAP_MOD, the selected
# NGSPICE_BIN and the record-prose hashes NGSPICE_SHA / DESIGN_NETLIST_SHA /
# EM_SHA / CAP_LIB_SHA / CAP_MOD_SHA / DECL_SHA. Every failure prints
# "<script-name>: <what failed>" on stderr and exits 3, before sim_record_paths
# is ever called, so a refused run reserves no record.
#
# This file runs at source time, not inside a function: sim/env.sh declares
# its shared state at top level, and a function scope would make those
# declarations local to the call and silently drop them (SIM_SCRIPT_NAME,
# SIM_PDK_PROVENANCE_JSON, ...) on return.
#
# This file is sourced, not executed, so it has no shebang; the directive
# below tells shellcheck which dialect to assume.
# shellcheck shell=bash

_sp_name="${1:?study_prelude: <script-name> is required}"
_sp_module="${2:?study_prelude: <study-module> is required}"
_sp_decl="${3:?study_prelude: <declaration-file> is required}"

if [[ -n "${MATCH_NGSPICE:-}" ]]; then
  if [[ ! -x "${MATCH_NGSPICE}" ]]; then
    echo "${_sp_name}: MATCH_NGSPICE=${MATCH_NGSPICE} is not executable." >&2
    exit 3
  fi
  PATH="$(cd "$(dirname "${MATCH_NGSPICE}")" && pwd):${PATH}"
  export PATH
fi

SIM_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
# shellcheck source-path=SCRIPTDIR
# shellcheck source=../env.sh
source "${SIM_DIR}/env.sh"

sim_require_pdk "${_sp_name}" --osdi
command -v python3 >/dev/null 2>&1 || { echo "${_sp_name}: python3 not on PATH." >&2; exit 3; }
NGSPICE_MAJOR="$(printf '%s\n' "${NGSPICE_VERSION}" | sed -n 's/.*ngspice-\([0-9][0-9]*\).*/\1/p')"
if [[ -z "${NGSPICE_MAJOR}" ]] || (( NGSPICE_MAJOR < 46 )); then
  echo "${_sp_name}: need ngspice >= 46 (found '${NGSPICE_VERSION}'); set MATCH_NGSPICE." >&2
  exit 3
fi
CAP_LIB="${SG13G2_NGSPICE_MODELS}/cornerCAP.lib"
CAP_MOD="${SG13G2_NGSPICE_MODELS}/capacitors_mod.lib"
[[ -f "${CAP_LIB}" && -f "${CAP_MOD}" ]] || { echo "${_sp_name}: ${CAP_LIB} / capacitors_mod.lib missing." >&2; exit 3; }
"${SIM_DIR}/models/check_sources.sh" || { echo "${_sp_name}: sim/models hash check failed." >&2; exit 3; }
# The declaration must match the code, or the run is not the declared study.
python3 -I "${SCRIPT_DIR}/${_sp_module}" declare | cmp -s - "${SCRIPT_DIR}/${_sp_decl}" \
  || { echo "${_sp_name}: ${_sp_decl} is stale vs ${_sp_module} declare." >&2; exit 3; }

NGSPICE_BIN="$(command -v ngspice)"
# shellcheck disable=SC2034  # consumed by the sourcing runner's record prose
NGSPICE_SHA="$(sha256sum "${NGSPICE_BIN}" | awk '{print $1}')"
# shellcheck disable=SC2034  # consumed by the sourcing runner's record prose
DESIGN_NETLIST_SHA="$(sha256sum "${REPO_ROOT}/design/netlist/lna.spice" | awk '{print $1}')"
# shellcheck disable=SC2034  # consumed by the sourcing runner's record prose
EM_SHA="$(sha256sum "${SIM_DIR}/models/sg13g2_inductor_em.spice" | awk '{print $1}')"
# shellcheck disable=SC2034  # consumed by the sourcing runner's record prose
CAP_LIB_SHA="$(sha256sum "${CAP_LIB}" | awk '{print $1}')"
# shellcheck disable=SC2034  # consumed by the sourcing runner's record prose
CAP_MOD_SHA="$(sha256sum "${CAP_MOD}" | awk '{print $1}')"
# shellcheck disable=SC2034  # consumed by the sourcing runner's record prose
DECL_SHA="$(sha256sum "${SCRIPT_DIR}/${_sp_decl}" | awk '{print $1}')"

unset _sp_name _sp_module _sp_decl
