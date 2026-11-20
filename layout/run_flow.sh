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
#      layout/inductance_report.py        inductance_report.json (drawn vs netlist L, issue #347)
#   4. klt drc     --deck sg13g2          drc_report.json
#   5. klt extract --deck sg13g2          extract_report.json + lna_core.extracted.spice
#   6. klt lvs     lvs_request.json       lvs_report.json      (scoped reference)
#   7. klt lvs     lvs_full_request.json  lvs_full_report.json (design/netlist/lna.spice as-is)
#      after 6 and 7: layout/lvs_identity.py records lvs_inputs.json binding each
#      report to its GDS, reference and request bytes (issue #130). It runs only
#      after the tool invocation succeeded; set -e means a failed klt never
#      reaches it, so an old report is never re-attested.
#   8. layout/item2_envelope.py            item2.envelope.json (T1 item-2 generic
#      envelope pinning the GDS by hash, #228; fails unless the GDS re-hashes to
#      its provenance and realization.json's out_of_scope is empty)
#   9. klt erc      layout/lna_core/erc_spec.json  erc_report.json (T1 item-11
#      supply evidence, #35) + the two negative controls that prove the tie
#      declarations can fail (erc_break.py copies of the GDS with one tap's
#      contacts removed -> erc_control.json, assembled by erc_control.py,
#      which fails unless each control flips the verdict to violations)
#
# klt: the PyPI *release* named below, run isolated through uvx so the
# evidence is graded by a tagged build regardless of whatever klt a host has
# installed (a host tool may be a post-tag build: `klt version` reports
# is_release=false for those). Override with KLT="klt" to use the host's.
# DRC/LVS exit 3 ("ran, found violations/mismatch") is a successful run and
# is recorded, not treated as a script failure; any other non-zero exit is.
# ERC exit 4 is the same contract's "not_checked" antenna verdict (item 11
# runs without --pdk: the antenna half is item 3's deck evidence, not this
# spec's subject), and the control runs may also exit 3 (violations -- the
# expected outcome).
#
# PYTHON: an interpreter with the pip `klayout` package (generate.py).
set -euo pipefail

LAYOUT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${LAYOUT_DIR}/.." && pwd)"
CELL_DIR="${LAYOUT_DIR}/lna_core"
KLT_RELEASE="0.9.2"
# klayout: klayout-tools requires `klayout` without an upper bound, so a bare
# uvx resolve takes whatever is newest on PyPI. That silently drifts off the
# version klt itself declares as klayout_version_expected (0.30.12 at 0.9.2,
# while PyPI already carries 0.30.13), which would publish evidence whose own
# klt_version.json records actual != expected -- and klt warns that deck
# content_hash and coverage counts move with the engine. Pin it so a rerun is
# reproducible; bump it when klt's expected version moves. Upstream gap:
# klayout-tools#5601 (a released pin cannot reach a reproducible engine).
KLAYOUT_PIN="0.30.12"
read -r -a KLT_CMD <<< "${KLT:-uvx --isolated --from klayout-tools==${KLT_RELEASE} --with klayout==${KLAYOUT_PIN} klt}"
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

# run_lvs <report.json> <request.json>: run_klt, then (only on a successful
# invocation, exit 0 or recorded mismatch 3) bind the published report to the
# GDS / reference / request bytes it was produced from (issue #130).
run_lvs() {
  run_klt "${CELL_DIR}/$1" lvs "$2"
  python3 -I "${LAYOUT_DIR}/lvs_identity.py" "${CELL_DIR}" "$2" "$1"
}

"${LAYOUT_DIR}/tools/fetch-pcell-deps.sh"
"${PYTHON}" "${CELL_DIR}/generate.py" "${NX_ARGS[@]}"
python3 -I "${LAYOUT_DIR}/lvs_reference.py" "${CELL_DIR}"
"${PYTHON}" "${LAYOUT_DIR}/inductance_report.py" "${CELL_DIR}"

"${KLT_CMD[@]}" version --format json > "${CELL_DIR}/klt_version.json"
run_klt "${CELL_DIR}/drc_report.json" drc lna_core.gds --deck sg13g2
run_klt "${CELL_DIR}/extract_report.json" extract lna_core.gds --deck sg13g2 -o lna_core.extracted.spice
run_lvs lvs_report.json lvs_request.json
run_lvs lvs_full_report.json lvs_full_request.json
python3 -I "${LAYOUT_DIR}/item2_envelope.py" "${REPO_ROOT}"

# ---------------------------------------------------------------- ERC (#35) --
# The item-11 supply evidence runs from the REPO ROOT, unlike the DRC/extract/
# LVS steps above: its envelope is a manifest-cited artifact, and klt signoff's
# grader resolves the spec path the envelope names (`file`, `spec`) relative to
# the repo root, so both must be recorded repo-relative ("layout/lna_core/...").
cd "${REPO_ROOT}"
ERC_SPEC="layout/lna_core/erc_spec.json"
"${KLT_CMD[@]}" erc --validate-spec "${ERC_SPEC}"
erc_rc=0
"${KLT_CMD[@]}" erc layout/lna_core/lna_core.gds "${ERC_SPEC}" --top lna_core \
  --deck sg13g2 --format json > "${CELL_DIR}/erc_report.json" || erc_rc=$?
if [ ${erc_rc} -ne 0 ] && [ ${erc_rc} -ne 4 ]; then
  echo "run_flow: klt erc failed (exit ${erc_rc}), not a not_checked verdict" >&2
  exit "${erc_rc}"
fi
echo "run_flow: klt erc -> erc_report.json (exit ${erc_rc})"

# Negative controls: one broken copy per declared tie. A clean supply verdict
# is only evidence if the same invocation rejects a stream whose tap has lost its contacts,
# so erc_control.py fails the flow when a control does not move the verdict.
# What each break removes and where is declared once, in erc_control.py's
# CONTROLS (#438): the loop below consumes `erc_control.py --print-controls`
# (name<TAB>layer<TAB>box per control), so the layer handed to erc_break.py
# and the break_layer recorded in erc_control.json are the same value.
ERC_SCRATCH="${LAYOUT_DIR}/build/erc"
mkdir -p "${ERC_SCRATCH}"
erc_one_control() {
  local name="$1" layer="$2" box="$3"
  local broken="${ERC_SCRATCH}/broken_${name}.gds"
  "${PYTHON}" "${LAYOUT_DIR}/erc_break.py" \
    layout/lna_core/lna_core.gds "${broken}" "${layer}" "${box}" > /dev/null
  local crc=0
  "${KLT_CMD[@]}" erc "${broken}" "${ERC_SPEC}" --top lna_core \
    --deck sg13g2 --format json > "${ERC_SCRATCH}/control_${name}.json" || crc=$?
  if [ ${crc} -ne 0 ] && [ ${crc} -ne 3 ] && [ ${crc} -ne 4 ]; then
    echo "run_flow: klt erc on control ${name} failed (exit ${crc}), not a verdict" >&2
    exit "${crc}"
  fi
}
ERC_CONTROLS="${ERC_SCRATCH}/controls.tsv"
python3 -I "${LAYOUT_DIR}/erc_control.py" --print-controls > "${ERC_CONTROLS}"
ERC_CONTROL_ENVS=()
while IFS=$'\t' read -r name layer box; do
  erc_one_control "${name}" "${layer}" "${box}"
  ERC_CONTROL_ENVS+=("${ERC_SCRATCH}/control_${name}.json")
done < "${ERC_CONTROLS}"
python3 -I "${LAYOUT_DIR}/erc_control.py" "${REPO_ROOT}" "${ERC_CONTROL_ENVS[@]}"

echo "run_flow: done (repo ${REPO_ROOT})"
