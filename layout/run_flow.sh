#!/usr/bin/env bash
# run_flow.sh -- regenerate layout/lna_core/ and its klt evidence (issue #63).
#
#   layout/run_flow.sh            # generate GDS + reference, run DRC/extract/LVS
#   NX=10 layout/run_flow.sh      # same, with issue #58's emitter count
#
# Steps, all deterministic for fixed inputs:
#   1. layout/tools/fetch-pcell-deps.sh   pinned PyCell shims (idempotent)
#   2. layout/lna_core/generate.py        lna_core.gds + .provenance.json
#   3. layout/lvs_reference.py            lna_core.lvs_reference.spice
#   4. klt drc     --deck sg13g2          drc_report.json
#   5. klt extract --deck sg13g2          extract_report.json + lna_core.extracted.spice
#   6. klt lvs     lvs_request.json       lvs_report.json      (scoped reference)
#   7. klt lvs     lvs_full_request.json  lvs_full_report.json (design/netlist/lna.spice as-is)
#
# klt: the PyPI *release* named below, run isolated through uvx so the
# evidence is graded by a tagged build regardless of whatever klt a host has
# installed (a host tool may be a post-tag build: `klt version` reports
# is_release=false for those). Override with KLT="klt" to use the host's.
# DRC/LVS exit 3 ("ran, found violations/mismatch") is a successful run and
# is recorded, not treated as a script failure; any other non-zero exit is.
#
# PYTHON: an interpreter with the pip `klayout` package (generate.py).
set -euo pipefail

LAYOUT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${LAYOUT_DIR}/.." && pwd)"
CELL_DIR="${LAYOUT_DIR}/lna_core"
KLT_RELEASE="0.7.0"
read -r -a KLT_CMD <<< "${KLT:-uvx --isolated --from klayout-tools==${KLT_RELEASE} klt}"
PYTHON="${PYTHON:-python3}"
NX_ARGS=()
if [[ -n "${NX:-}" ]]; then NX_ARGS=(--nx "${NX}"); fi

# run_klt <out.json> <args...>: exit 0 and 3 are recorded runs.
run_klt() {
  local out="$1"; shift
  local rc=0
  (cd "${CELL_DIR}" && "${KLT_CMD[@]}" "$@" --format json) > "${out}.tmp" || rc=$?
  if [[ ${rc} -ne 0 && ${rc} -ne 3 ]]; then
    echo "run_flow: klt $1 failed (exit ${rc}); output left in ${out}.tmp" >&2
    exit "${rc}"
  fi
  mv "${out}.tmp" "${out}"
  echo "run_flow: klt $1 -> $(basename "${out}") (exit ${rc})"
}

"${LAYOUT_DIR}/tools/fetch-pcell-deps.sh"
"${PYTHON}" "${CELL_DIR}/generate.py" "${NX_ARGS[@]}"
python3 -I "${LAYOUT_DIR}/lvs_reference.py" "${CELL_DIR}"

"${KLT_CMD[@]}" version --format json > "${CELL_DIR}/klt_version.json"
run_klt "${CELL_DIR}/drc_report.json" drc lna_core.gds --deck sg13g2
run_klt "${CELL_DIR}/extract_report.json" extract lna_core.gds --deck sg13g2 -o lna_core.extracted.spice
run_klt "${CELL_DIR}/lvs_report.json" lvs lvs_request.json
run_klt "${CELL_DIR}/lvs_full_report.json" lvs lvs_full_request.json

echo "run_flow: done (repo ${REPO_ROOT})"
