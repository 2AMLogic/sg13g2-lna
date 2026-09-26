# Source me:  source sim/env.sh
#
# Resolves the SG13G2 PDK environment (PDK_ROOT/PDK env vars, falling back
# to the usual open_pdks install prefixes: /usr/share/pdk,
# /usr/local/share/pdk, ~/share/pdk, ~/.ciel, ~/.volare), so an interactive
# ngspice session and every sim/*/run_*.sh script agree on which PDK
# install is in use. Follows sg13g2-bandgap/sim/env.sh's and
# sg13g2-opamp/sim/env.sh's shape (same PDK, same resolution order) --
# see sim/README.md "PDK pin" for why this repo reuses that convention
# rather than inventing its own.
#
# It also carries the small shell surface every sim/*/run_*_sweep.sh needs
# and used to copy-paste: sim_require_pdk (the preflight and its exit-3
# contract), sim_record_paths (mint a <record-id>, create its append-only
# output dirs), sim_jobs / sim_pool_init / sim_pool_spawn (the ngspice job
# pool), sim_render (deck rendering) and sim_check_log (the per-point
# pass/fail gate). See sim/README.md "Shared runner surface (sim/env.sh)"
# for what each one contracts to do. Bench definitions -- sweep grids,
# corner-section maps, per-experiment template substitutions, SMOKE
# overrides, bespoke failure criteria -- deliberately stay in each runner.
#
# Safe to source from any directory; does not require `klt` to be
# installed (this repo's testbenches must remain runnable in a sandbox
# that has ngspice but not klayout-tools).
#
# This file is sourced, not executed, so it has no shebang; the directive
# below tells shellcheck which dialect to assume.
# shellcheck shell=bash

export PDK="${PDK:-ihp-sg13g2}"

if [[ -z "${PDK_ROOT:-}" ]]; then
  for _sg13g2_candidate in /usr/share/pdk /usr/local/share/pdk \
                           "${HOME}/share/pdk" "${HOME}/.ciel" "${HOME}/.volare"; do
    if [[ -d "${_sg13g2_candidate}/${PDK}/libs.tech/ngspice" ]]; then
      export PDK_ROOT="${_sg13g2_candidate}"
      break
    fi
  done
fi

if [[ -n "${PDK_ROOT:-}" && -d "${PDK_ROOT}/${PDK}/libs.tech/ngspice" ]]; then
  export SG13G2_NGSPICE_MODELS="${PDK_ROOT}/${PDK}/libs.tech/ngspice/models"
  echo "sg13g2-lna: PDK_ROOT=${PDK_ROOT} PDK=${PDK}"
else
  echo "sg13g2-lna: no ${PDK} install found under PDK_ROOT or the usual prefixes." >&2
  echo "sg13g2-lna: set PDK_ROOT to an open_pdks-shaped IHP-Open-PDK checkout and re-source," >&2
  echo "sg13g2-lna: e.g. via klayout-tools' scripts/fetch-ihp-sg13g2.sh, then:" >&2
  echo "sg13g2-lna:   export PDK_ROOT=/path/to/ihp-open-pdk PDK=ihp-sg13g2" >&2
  echo "sg13g2-lna: see sim/pdk.json for the pinned release this repo's evidence records target." >&2
fi

unset _sg13g2_candidate

# --- Repo-relative anchors ------------------------------------------------
# Derived from THIS file's own location, so they are identical whichever
# runner (or interactive shell) sources it. A runner still resolves its own
# SCRIPT_DIR before sourcing: that is the experiment directory, which only
# the runner knows.
SIM_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SIM_DIR}/.." && pwd)"

# --- Shared runner surface -----------------------------------------------
# State the helpers below share with their caller, declared here so every
# helper is safe to call under `set -u` no matter which subset a runner uses.
SIM_SCRIPT_NAME=""        # set by sim_require_pdk; prefixes every message
SIM_LOG_FAIL_PATTERNS=""  # extra egrep alternation for sim_check_log
SIM_DUT_SUBCKT=""         # file spliced in at a deck's @@LNA_SUBCKT@@
SIM_POOL_JOBS=1           # set by sim_pool_init
SIM_POOL_SPAWNED=0        # how many points sim_pool_spawn has scheduled

sim_require_pdk() {
  # sim_require_pdk <script-name> [--osdi]
  #
  # The PDK/ngspice preflight every runner shares. EVERY failure path here
  # prints "<script-name>: <what is missing>" on stderr and exits 3 -- the
  # documented per-runner contract (a missing PDK, a missing ngspice, or a
  # missing cornerHBT.lib all exit 3, each named by the runner that asked).
  # The <script-name> argument is what keeps that prefix per-runner rather
  # than collapsing five guards into one generic message.
  #
  # Sets, in the caller: SIM_SCRIPT_NAME, NGSPICE_VERSION, MODELS_LIB and --
  # with --osdi, for the benches that instantiate a MOS/PSP103 device --
  # MOS_LIB and OSDI_DIR, each checked to exist.
  local want_osdi=0
  SIM_SCRIPT_NAME="${1:?sim_require_pdk: <script-name> is required}"
  shift
  while (( $# > 0 )); do
    case "$1" in
      --osdi) want_osdi=1 ;;
      *) echo "sim_require_pdk: unknown option '$1'" >&2; exit 2 ;;
    esac
    shift
  done

  if [[ -z "${PDK_ROOT:-}" || ! -d "${PDK_ROOT}/${PDK}/libs.tech/ngspice" ]]; then
    echo "${SIM_SCRIPT_NAME}: no resolvable ${PDK:-ihp-sg13g2} install -- see sim/env.sh output above." >&2
    exit 3
  fi

  command -v ngspice >/dev/null 2>&1 || {
    echo "${SIM_SCRIPT_NAME}: ngspice not on PATH." >&2
    exit 3
  }
  # shellcheck disable=SC2034  # consumed by the sourcing runner's record
  NGSPICE_VERSION="$(ngspice -v 2>&1 | sed -n '2p')"

  # SG13G2_NGSPICE_MODELS is exported above by the same resolution the
  # guard just re-checked; the runners consume it from here instead of each
  # rebuilding the models path out of PDK_ROOT.
  MODELS_LIB="${SG13G2_NGSPICE_MODELS}/cornerHBT.lib"
  if [[ ! -f "${MODELS_LIB}" ]]; then
    echo "${SIM_SCRIPT_NAME}: cornerHBT.lib not found at ${MODELS_LIB}" >&2
    exit 3
  fi

  if (( want_osdi )); then
    MOS_LIB="${SG13G2_NGSPICE_MODELS}/cornerMOShv.lib"
    OSDI_DIR="${PDK_ROOT}/${PDK}/libs.tech/ngspice/osdi"
    local f
    for f in "${MOS_LIB}" "${OSDI_DIR}/psp103.osdi" \
             "${OSDI_DIR}/psp103_nqs.osdi" "${OSDI_DIR}/mosvar.osdi"; do
      if [[ ! -f "${f}" ]]; then
        echo "${SIM_SCRIPT_NAME}: ${f} not found -- if the .osdi models are missing, run sim/tools/build-osdi.sh (see sim/README.md 'OSDI device models'); the MOS devices this bench instantiates will not simulate without them." >&2
        exit 3
      fi
    done
  fi
}

sim_record_paths() {
  # sim_record_paths   (the experiment dir is the caller's ${SCRIPT_DIR})
  #
  # Mints this run's <record-id> -- <YYYYMMDD>-<HHMMSS>-<short-git-sha>,
  # UTC, per sim/README.md "Directory / naming convention" -- and creates
  # the three append-only output locations a record is written into.
  # Sets, in the caller: REPO_GIT_SHA, RECORD_ID, EXPERIMENT_DIR,
  # SNAPSHOTS_OUT, CORNERS_OUT, RECORDS_DIR.
  EXPERIMENT_DIR="${SCRIPT_DIR}"
  REPO_GIT_SHA="$(cd "${REPO_ROOT}" && git rev-parse --short HEAD 2>/dev/null || echo unknown)"
  RECORD_ID="$(date -u +%Y%m%d-%H%M%S)-${REPO_GIT_SHA}"
  SNAPSHOTS_OUT="${EXPERIMENT_DIR}/netlist-snapshots/${RECORD_ID}"
  CORNERS_OUT="${EXPERIMENT_DIR}/corners/${RECORD_ID}"
  RECORDS_DIR="${EXPERIMENT_DIR}/records"
  mkdir -p "${SNAPSHOTS_OUT}" "${CORNERS_OUT}" "${RECORDS_DIR}"
}

sim_jobs() {
  # sim_jobs <var-name>
  #
  # Sets <var-name> to this host's default concurrency -- min(6, ncpu/3),
  # floor 1 -- unless it is already set, in which case the explicit knob
  # wins. Every scheduled point is an independent `ngspice -b` writing only
  # files named after that point, so concurrency is a pure wall-clock
  # choice: it changes nothing about any recorded number.
  local __sim_jobs_var="${1:?sim_jobs: <var-name> is required}"
  local __sim_jobs_ncpu __sim_jobs_n
  if [[ -n "${!__sim_jobs_var:-}" ]]; then
    return 0
  fi
  # `getconf _NPROCESSORS_ONLN` is the portable probe; `sysctl -n hw.ncpu`
  # is the macOS spelling of the same number (NOT `sysctl -n ncpu`, which
  # is not a sysctl OID and fails on every host).
  __sim_jobs_ncpu="$( (getconf _NPROCESSORS_ONLN 2>/dev/null \
                       || sysctl -n hw.ncpu 2>/dev/null \
                       || echo 4) | head -1 )"
  __sim_jobs_n=$(( __sim_jobs_ncpu / 3 ))
  if (( __sim_jobs_n < 1 )); then __sim_jobs_n=1; fi
  if (( __sim_jobs_n > 6 )); then __sim_jobs_n=6; fi
  printf -v "${__sim_jobs_var}" '%s' "${__sim_jobs_n}"
}

sim_pool_init() {
  # sim_pool_init <jobs> -- arm sim_pool_spawn's concurrency limit and
  # reset its scheduled-point counter.
  SIM_POOL_JOBS="${1:?sim_pool_init: <jobs> is required}"
  SIM_POOL_SPAWNED=0
}

sim_pool_spawn() {
  # sim_pool_spawn <fn> <args...> -- run <fn> in the background, at most
  # SIM_POOL_JOBS at a time, counting it in SIM_POOL_SPAWNED. `trap - EXIT`
  # in the child keeps the child's exit from deleting the parent's shared
  # temp files. Uses bash 4.3's `wait -n`, which every caller guards for.
  while (( $(jobs -rp | wc -l) >= SIM_POOL_JOBS )); do
    wait -n 2>/dev/null || true
  done
  SIM_POOL_SPAWNED=$(( SIM_POOL_SPAWNED + 1 ))
  ( trap - EXIT; "$@" ) &
}

sim_render() {
  # sim_render <template> <outfile> <extra sed-args...>
  #
  # Renders one deck: the caller's own per-experiment substitutions (bench
  # definitions, which stay in the runner) are applied first, then the PDK
  # paths every deck needs. When SIM_DUT_SUBCKT names a file, that file is
  # spliced in at the deck's @@LNA_SUBCKT@@ marker (the committed-DUT
  # benches).
  local tmpl="$1" out="$2"; shift 2
  if [[ -n "${SIM_DUT_SUBCKT}" ]]; then
    sed "$@" \
      -e "s|@@MODELS_LIB@@|${MODELS_LIB}|g" \
      -e "s|@@MOS_LIB@@|${MOS_LIB:-}|g" \
      -e "s|@@OSDI_DIR@@|${OSDI_DIR:-}|g" \
      "${tmpl}" \
      | sed -e "/@@LNA_SUBCKT@@/r ${SIM_DUT_SUBCKT}" -e "/@@LNA_SUBCKT@@/d" > "${out}"
  else
    sed "$@" \
      -e "s|@@MODELS_LIB@@|${MODELS_LIB}|g" \
      -e "s|@@MOS_LIB@@|${MOS_LIB:-}|g" \
      -e "s|@@OSDI_DIR@@|${OSDI_DIR:-}|g" \
      "${tmpl}" > "${out}"
  fi
}

sim_check_log() {
  # sim_check_log <point-id> <log> <rc>
  #
  # The per-point pass/fail gate the concurrent runners share: a non-zero
  # ngspice exit, any bench-specific pattern the runner put in
  # SIM_LOG_FAIL_PATTERNS (an egrep alternation; empty = none), or a
  # missing "BENCH_COMPLETE" marker fails the point. Failed point ids are
  # appended to ${FAILED_LIST} -- a file, not a shell array, because each
  # point runs in its own background subshell whose variable writes cannot
  # propagate back to the parent.
  #
  # Benches whose failure criterion is genuinely bespoke
  # (sim/hbt-characterization, sim/breakdown-extraction: count the emitted
  # "PT " lines against an expected N_POINTS) deliberately do NOT use this.
  local point_id="$1" log="$2" rc="$3"
  if [[ "${rc}" -ne 0 ]] \
    || { [[ -n "${SIM_LOG_FAIL_PATTERNS}" ]] && grep -qiE "${SIM_LOG_FAIL_PATTERNS}" "${log}"; } \
    || ! grep -q "^BENCH_COMPLETE" "${log}"; then
    echo "${SIM_SCRIPT_NAME}: FAILED ${point_id} (rc=${rc}) -- see ${log}" >&2
    echo "${point_id}" >> "${FAILED_LIST}"
    return 1
  fi
  return 0
}
