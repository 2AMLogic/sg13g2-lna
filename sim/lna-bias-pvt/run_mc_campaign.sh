#!/usr/bin/env bash
# Fleet runner for the issue-#90 full-DUT DC mismatch campaign.
#
#   sim/lna-bias-pvt/run_mc_campaign.sh
#
# Every simulation here is a `klt sim` Monte Carlo request submitted to the
# Spot batch fleet. This is NOT run_biasop_sweep.sh (the deterministic local
# PVT grid) and it never runs ngspice on this host.
#
# Sequence (stop on the first error; nothing is retried on another backend):
#   1. PDK identity preflight (sim_require_pdk --osdi) and record reservation
#      (sim_record_paths: netlist-snapshots/<id>/, corners/<id>/).
#   2. mc_campaign.py gen        -> bench netlist, 2 requests, manifest.
#   3. mc_campaign.py validate   -> run under the klt CLI's own interpreter, so
#      the requests are checked by the installed klt's validators. A request it
#      rejects is never submitted.
#   4. Three fleet submissions, in order:
#        mc_mismatch         n=200 seed=68001, *_mismatch sections
#        mc_mismatch_replay  the SAME request file, a second fleet job
#        negctl_nominal      n=20 seed=68001, nominal sections (mismatch off)
#      `klt sim` exit 0/3/4 means a report was written (pass / bar exceeded /
#      some sample errored) and is kept; anything else stops the run with
#      corners/<id>/STOPPED and the stderr log, no local fallback.
#   5. mc_campaign.py reduce into corners/<id>/reduction/; published under
#      records/ only if the reduction is structurally complete fleet evidence.
#      Records are append-only (noclobber).
#
# Environment: KLT_SIM_BACKEND=batch (or MC_BACKEND=batch) is required; any
# other value exits 3. `--backend batch` is also passed explicitly so klt's
# host-default step-back to `local` can never apply.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SIM_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
GEN="${SCRIPT_DIR}/mc_campaign.py"

# shellcheck source-path=SCRIPTDIR
# shellcheck source=../env.sh
source "${SIM_DIR}/env.sh"

BACKEND="${MC_BACKEND:-${KLT_SIM_BACKEND:-}}"
if [[ "${BACKEND}" != "batch" ]]; then
  echo "run_mc_campaign.sh: backend is '${BACKEND:-<unset>}', must be 'batch'. Refusing: no local fallback." >&2
  exit 3
fi
command -v klt >/dev/null 2>&1 || { echo "run_mc_campaign.sh: klt not on PATH." >&2; exit 3; }
KLT_BIN="$(command -v klt)"
KLT_PY="$(sed -n '1s/^#!//p' "${KLT_BIN}")"
[[ -x "${KLT_PY}" ]] || { echo "run_mc_campaign.sh: cannot resolve the klt CLI interpreter from ${KLT_BIN}" >&2; exit 3; }
KLT_VERSION="$(klt --version 2>&1 | head -1)"

sim_require_pdk run_mc_campaign.sh --osdi
sim_record_paths
SNAP="${SNAPSHOTS_OUT}"
CORNERS="${CORNERS_OUT}"

python3 -I "${GEN}" gen --record-id "${RECORD_ID}" --out-root "${SCRIPT_DIR}/netlist-snapshots" \
  --git-sha "${REPO_GIT_SHA}" >/dev/null
if ! "${KLT_PY}" -I "${GEN}" validate --snapshot-dir "${SNAP}" --out "${SNAP}/request-validation.json"; then
  echo "run_mc_campaign.sh: request validation failed; nothing submitted." >&2
  echo "validate: failed" > "${CORNERS}/STOPPED"
  exit 3
fi

{
  echo "record_id=${RECORD_ID}"
  echo "client_klt=${KLT_VERSION}"
  echo "client_klt_bin_sha256=$(sha256sum "${KLT_BIN}" | awk '{print $1}')"
  echo "local_ngspice=${NGSPICE_VERSION} (not used for any campaign unit)"
  echo "pdk_release=${SIM_PDK_RELEASE} via ${SIM_PDK_ID_ROUTE}"
  echo "backend=batch"
  echo "started_utc=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
} > "${CORNERS}/run-provenance.txt"
echo "run_mc_campaign.sh: record ${RECORD_ID}; client ${KLT_VERSION}; backend batch"

submit() {
  local run="$1" req="$2" rc=0
  echo "run_mc_campaign.sh: klt sim ${run} ($(basename "${req}"))"
  klt sim "${req}" --backend batch -o "${CORNERS}/${run}.artifacts" --format json \
    > "${CORNERS}/${run}.report.json" 2> "${CORNERS}/${run}.stderr.log" || rc=$?
  echo "${run}: klt_exit=${rc} finished_utc=$(date -u +%Y-%m-%dT%H:%M:%SZ)" >> "${CORNERS}/run-provenance.txt"
  case "${rc}" in
    0|3|4) return 0 ;;
    *)
      echo "run_mc_campaign.sh: ${run} exited ${rc} (see ${CORNERS}/${run}.stderr.log); STOPPING. No local fallback." >&2
      echo "${run}: rc=${rc}" >> "${CORNERS}/STOPPED"
      exit 4 ;;
  esac
}

submit mc_mismatch "${SNAP}/mc_mismatch.request.json"
submit mc_mismatch_replay "${SNAP}/mc_mismatch.request.json"
submit negctl_nominal "${SNAP}/negctl_nominal.request.json"

RED="${CORNERS}/reduction"
RC=0
python3 -I "${GEN}" reduce --snapshot-dir "${SNAP}" --corners-dir "${CORNERS}" \
  --out-dir "${RED}" --record-id "${RECORD_ID}" || RC=$?
if (( RC != 0 )); then
  echo "run_mc_campaign.sh: reduction exit ${RC}; NOT published to records/ (see ${RED}/)." >&2
  exit "${RC}"
fi
for sfx in mc-samples.csv mc-summary.json mc-summary.md; do
  [[ -e "${RECORDS_DIR}/${RECORD_ID}-${sfx}" ]] && { echo "run_mc_campaign.sh: ${RECORDS_DIR}/${RECORD_ID}-${sfx} exists; append-only." >&2; exit 4; }
done
for sfx in mc-samples.csv mc-summary.json mc-summary.md; do
  ( set -o noclobber; cat "${RED}/${RECORD_ID}-${sfx}" > "${RECORDS_DIR}/${RECORD_ID}-${sfx}" )
done
echo "run_mc_campaign.sh: published ${RECORDS_DIR}/${RECORD_ID}-mc-{samples.csv,summary.json,summary.md}"
python3 -I -c 'import json,sys; s=json.load(open(sys.argv[1])); sys.exit(0 if s["controls_pass"] else 1)' \
  "${RECORDS_DIR}/${RECORD_ID}-mc-summary.json" || { echo "run_mc_campaign.sh: a control FAILED (see the summary)." >&2; exit 1; }
