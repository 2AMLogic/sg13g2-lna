#!/usr/bin/env bash
# Fleet runner for the issue-#58 emitter-array / cascode-split campaign.
#
#   sim/lna-core-envelope/run_core_envelope_campaign.sh gate
#   CORE_ENV_GATE_VERDICT=sim/lna-core-envelope/corners/<gate-id>/gate-verdict.json \
#     sim/lna-core-envelope/run_core_envelope_campaign.sh campaign
#
# This is NOT run_core_envelope.sh (the serial local ngspice grid of issue #52,
# which must not be executed on a shared dispatch worker). Every simulation
# here is a `klt sim` request submitted to the Spot batch fleet.
#
# HARD RULES (enforced below, not just documented):
#   * Backend must be `batch`: KLT_SIM_BACKEND=batch (the dispatch daemon exports
#     it) or CORE_ENV_BACKEND=batch. Anything else exits 3. There is no local
#     fallback, and a failed submit is never retried on another backend.
#   * The client must meet the floor in sim/pdk.json (klt_variant_campaign).
#   * `gate` submits ONE nominal cell per analysis kind on the ideal basis, plus
#     one lc_em sp_band request that exercises the EM-inductor `.include`
#     (5 requests, 1 cell each), and writes gate-verdict.json. A pass validates
#     plumbing only.
#   * `campaign` refuses to start without a PASSING gate verdict produced by the
#     SAME client version (CORE_ENV_GATE_VERDICT).
#   * Stop on the first error: ANY non-zero `klt sim` exit stops the run at once
#     (exit 4, corners/<id>/STOPPED), whether or not a report was written; no
#     further request is submitted and nothing is published. The reducer output
#     reaches records/ only if the reduction is COMPLETE, the control replay
#     holds, summary.json is not a synthetic fixture, and none of the four
#     target files already exists. Failed, partial or smoke-only results are
#     never written under records/.
#
# Prerequisite (compatibility): the batch runner image must carry the same klt
# as the client (klt itself reports batch_runner_version_mismatch). The known
# blocker is 2AMLogic/klayout-tools#2851 (0.5.0 client cannot use the batch
# backend); an open ticket is not proof of a runtime failure, and its closure
# alone is not sufficient -- the gate is the proof.
set -euo pipefail

MODE="${1:-}"
case "${MODE}" in gate|campaign) ;; *)
  echo "usage: run_core_envelope_campaign.sh gate|campaign" >&2; exit 2;; esac

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SIM_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
REPO_ROOT="$(cd "${SIM_DIR}/.." && pwd)"
GEN="${SCRIPT_DIR}/core_envelope_campaign.py"
RED="${SCRIPT_DIR}/reduce_core_envelope_campaign.py"
REFERENCE="${SIM_DIR}/lna-characterization/records/20260926-122301-088c734-summary.csv"

command -v python3 >/dev/null 2>&1 || { echo "run_core_envelope_campaign.sh: python3 not on PATH." >&2; exit 3; }
command -v klt >/dev/null 2>&1 || { echo "run_core_envelope_campaign.sh: klt not on PATH." >&2; exit 3; }

BACKEND="${CORE_ENV_BACKEND:-${KLT_SIM_BACKEND:-}}"
if [[ "${BACKEND}" != "batch" ]]; then
  echo "run_core_envelope_campaign.sh: backend is '${BACKEND:-<unset>}', must be 'batch' (export KLT_SIM_BACKEND=batch). Refusing: no local fallback." >&2
  exit 3
fi

KLT_VERSION="$(klt --version 2>&1 | head -1)"
python3 -I "${GEN}" check-client "${KLT_VERSION}" || exit 3

GIT_SHA="$(cd "${REPO_ROOT}" && git rev-parse --short HEAD 2>/dev/null || echo unknown)"
STAMP="$(date -u +%Y%m%d-%H%M%S)"
RECORD_ID="${CORE_ENV_RECORD_ID:-${STAMP}-${GIT_SHA}}"
[[ "${MODE}" == gate ]] && RECORD_ID="${CORE_ENV_RECORD_ID:-gate-${STAMP}-${GIT_SHA}}"
[[ "${RECORD_ID}" =~ ^[A-Za-z0-9][A-Za-z0-9._-]*$ ]] || { echo "invalid record id '${RECORD_ID}'" >&2; exit 2; }

SNAP="${SCRIPT_DIR}/netlist-snapshots/${RECORD_ID}"
CORNERS="${SCRIPT_DIR}/corners/${RECORD_ID}"
RECORDS="${SCRIPT_DIR}/records"
[[ -e "${CORNERS}" ]] && { echo "run_core_envelope_campaign.sh: ${CORNERS} exists; evidence is append-only, mint a new CORE_ENV_RECORD_ID." >&2; exit 4; }

if [[ "${MODE}" == campaign ]]; then
  V="${CORE_ENV_GATE_VERDICT:-}"
  [[ -f "${V}" ]] || { echo "run_core_envelope_campaign.sh: campaign needs CORE_ENV_GATE_VERDICT=<gate-verdict.json> from a passing gate." >&2; exit 3; }
  python3 -I - "${V}" "${KLT_VERSION}" <<'PYEOF' || exit 3
import json, sys
v = json.load(open(sys.argv[1]))
if v.get("schema") != "core-envelope-gate/1" or v.get("pass") is not True:
    sys.exit("run_core_envelope_campaign.sh: gate verdict is not a passing core-envelope-gate/1 document.")
if v.get("client_klt_version") != sys.argv[2]:
    sys.exit("run_core_envelope_campaign.sh: gate verdict was produced by client "
             f"{v.get('client_klt_version')!r}, current client is {sys.argv[2]!r}; rerun the gate.")
PYEOF
fi

python3 -I "${GEN}" gen --record-id "${RECORD_ID}" --set "${MODE}" --backend batch --git-sha "${GIT_SHA}"
python3 -I "${GEN}" verify-snapshot --snapshot-dir "${SNAP}"
mkdir -p "${CORNERS}"
echo "run_core_envelope_campaign.sh: ${MODE} record ${RECORD_ID}; client ${KLT_VERSION}; backend batch"

for req in "${SNAP}"/*.request.json; do
  stem="$(basename "${req}" .request.json)"
  report="${CORNERS}/${stem}.report.json"
  errlog="${CORNERS}/${stem}.stderr.log"
  echo "run_core_envelope_campaign.sh: klt sim ${stem}"
  rc=0
  klt sim "${req}" -o "${CORNERS}/${stem}.artifacts" --backend batch --format json > "${report}" 2> "${errlog}" || rc=$?
  if (( rc != 0 )); then
    echo "run_core_envelope_campaign.sh: ${stem} exited ${rc} (see ${errlog}); STOPPING. Nothing is published; no local fallback." >&2
    echo "${stem}: rc=${rc}" >> "${CORNERS}/STOPPED"
    exit 4
  fi
done

if [[ "${MODE}" == gate ]]; then
  python3 -I "${GEN}" verify-gate --snapshot-dir "${SNAP}" --corners-dir "${CORNERS}" \
    --client-version "${KLT_VERSION}" --out "${CORNERS}/gate-verdict.json"
  echo "run_core_envelope_campaign.sh: gate verdict ${CORNERS}/gate-verdict.json (plumbing only)"
  exit 0
fi

# Reduce into the corners dir first; publish to records/ only if complete.
RC=0
python3 -I "${RED}" --snapshot-dir "${SNAP}" --corners-dir "${CORNERS}" --out-dir "${CORNERS}/reduction" \
  --client-version "${KLT_VERSION}" --reference-summary "${REFERENCE}" || RC=$?
if (( RC != 0 )); then
  echo "run_core_envelope_campaign.sh: reduction exit ${RC}; NOT published to records/ (see ${CORNERS}/reduction/)." >&2
  exit "${RC}"
fi
RED_OUT="${CORNERS}/reduction"
SUFFIXES=(cells.csv split.csv summary.json summary.md)
# Never publish a synthetic fixture, an incomplete summary, or a partial set.
python3 -I - "${RED_OUT}/${RECORD_ID}-summary.json" <<'PYEOF' || exit 2
import json, sys
s = json.load(open(sys.argv[1]))
if s.get("synthetic_fixture") is not False:
    sys.exit("run_core_envelope_campaign.sh: summary.json synthetic_fixture is not false; NOT publishing.")
if s.get("complete") is not True:
    sys.exit("run_core_envelope_campaign.sh: summary.json is not complete; NOT publishing.")
PYEOF
for sfx in "${SUFFIXES[@]}"; do
  [[ -f "${RED_OUT}/${RECORD_ID}-${sfx}" ]] || { echo "run_core_envelope_campaign.sh: reduction lacks ${RECORD_ID}-${sfx}; NOT publishing." >&2; exit 2; }
  [[ -e "${RECORDS}/${RECORD_ID}-${sfx}" ]] && { echo "run_core_envelope_campaign.sh: ${RECORDS}/${RECORD_ID}-${sfx} exists; records are append-only. Nothing published." >&2; exit 4; }
done
mkdir -p "${RECORDS}"
for sfx in "${SUFFIXES[@]}"; do
  ( set -o noclobber; cat "${RED_OUT}/${RECORD_ID}-${sfx}" > "${RECORDS}/${RECORD_ID}-${sfx}" )
done
echo "run_core_envelope_campaign.sh: published ${RECORDS}/${RECORD_ID}-{cells.csv,split.csv,summary.json,summary.md}"
