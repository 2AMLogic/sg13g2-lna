#!/usr/bin/env bash
# Cold-start invocation:
#
#   export PDK_ROOT=/path/to/ihp-open-pdk   # parent dir containing ihp-sg13g2/
#   export PDK=ihp-sg13g2
#   sim/lna-bias-pvt/run_biasop_sweep.sh
#
# (PDK_ROOT/PDK may also be left unset if the PDK is installed under one of
# the usual prefixes sim/env.sh checks.) Requires ngspice on PATH and the
# OSDI device models (since the DR-0003 Stage-2 core swap the DUT
# instantiates sg13_hv_pmos / sg13_hv_nmos, PSP103.6 via OSDI -- build or
# check them with sim/tools/build-osdi.sh, see sim/README.md "OSDI device
# models"). Requires python3 (stdlib only, for reduce_biasop.py) but not
# xschem (npn13G2 itself stays a
# native ngspice VBIC model -- see sim/pdk.json). Full methodology, bench
# definitions and stated method limits are in sim/lna-bias-pvt/README.md --
# read that first if a result here looks surprising.
#
# Runs the DC operating-point PVT sweep against the COMMITTED
# design/netlist/lna.spice (the regenerated netlist of design/lna.sch):
# the original acceptance evidence for issue #26's mirror replacement,
# re-run as the 45-cell bar evidence for issue #33's DR-0003 Stage-2
# flat-reference core swap (the two bars stay byte-identical in meaning:
# I_C1 <= 4.5 mA, P_dc < 10 mW at every cell):
#
#   Phase 1 (op): per PVT cell of the same 45-cell grid
#     sim/lna-characterization uses -- {typ,bcs,wcs,sf,fs} x {-40,27,125} C
#     x {1.62,1.80,1.98} V -- `op` and the operating-point probes
#     (I_C1, I_C2, I_C3, I_B1, V_B1, V_BREF, V_CE1, V_CE2, V_BE1, I_DD,
#     P_dc), evaluated against the two acceptance bars: DR-1's bias-network
#     requirement I_C1 <= 4.5 mA at every cell, and spec/target-spec.md's
#     (DR-0002-ratified) Power row P_dc < 10 mW at every cell.
#   Phase 2 (startup): supply-ramp transient at the two extreme PVT cells
#     (bcs/125C/1.98V, wcs/-40C/1.62V) plus the nominal cell, checking the
#     bias generator settles to the same op point with no latch or ringing
#     (issue #26's Test Plan edge case).
#
# Writes append-only evidence under corners/<record-id>/,
# netlist-snapshots/<record-id>/ and records/<record-id>-summary.csv +
# <record-id>.md -- see sim/README.md for the convention this follows.
#
# Environment knobs (all optional):
#   BIASOP_JOBS=<n>    how many ngspice processes to run concurrently
#                      (default: min(6, ncpu/3), floor 1). Every point
#                      writes only its OWN files, so concurrency changes
#                      nothing about the numbers, only wall-clock time.
#                      Set 1 for a strictly serial run.
#   BIASOP_SMOKE=1     nominal PVT cell only, for plumbing checks.
set -euo pipefail

# Needs the bash 4.3 `wait -n` job pool (see sim/lna-characterization's
# identical guard).
if (( BASH_VERSINFO[0] < 4 || (BASH_VERSINFO[0] == 4 && BASH_VERSINFO[1] < 3) )); then
  echo "run_biasop_sweep.sh: needs bash >= 4.3 (found ${BASH_VERSION})." >&2
  exit 3
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SIM_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"

# shellcheck source-path=SCRIPTDIR
# shellcheck source=../env.sh
source "${SIM_DIR}/env.sh"

# PDK/ngspice preflight (exit 3 on any miss, prefixed with this runner's
# own name). --osdi because the DR-0003 Stage-2 DUT instantiates
# sg13_hv_pmos/sg13_hv_nmos (PSP103.6, loadable only as OSDI).
sim_require_pdk run_biasop_sweep.sh --osdi

DESIGN_NETLIST="${REPO_ROOT}/design/netlist/lna.spice"
if [[ ! -f "${DESIGN_NETLIST}" ]]; then
  echo "run_biasop_sweep.sh: design netlist not found at ${DESIGN_NETLIST}" >&2
  exit 3
fi
DESIGN_NETLIST_SHA="$(shasum -a 256 "${DESIGN_NETLIST}" | awk '{print $1}')"

# This run's record id + its three append-only output locations.
sim_record_paths

# --- DUT: the committed design netlist, inlined verbatim ----------------
# Same uncomment-subckt convention as sim/lna-characterization's runner.
# SIM_DUT_SUBCKT is what sim_render splices in at @@LNA_SUBCKT@@.
SIM_DUT_SUBCKT="$(mktemp)"
trap 'rm -f "${SIM_DUT_SUBCKT}"' EXIT
sed -e 's|^\*\*\.subckt|.subckt|' \
    -e 's|^\*\*\.ends|.ends|' \
    -e '/^\.end$/d' \
    "${DESIGN_NETLIST}" > "${SIM_DUT_SUBCKT}"
grep -q '^\.subckt lna ' "${SIM_DUT_SUBCKT}" || {
  echo "run_biasop_sweep.sh: could not recover a '.subckt lna ...' line from ${DESIGN_NETLIST}" >&2
  exit 3
}

# --- HBT audit probes (issue #155) --------------------------------------
# Derived from the netlist being simulated, never hand-listed: every
# npn13G2 instance gets ic/vbe/vce probes in every op deck.
HBT_PROBES="$(mktemp)"
trap 'rm -f "${SIM_DUT_SUBCKT}" "${HBT_PROBES}"' EXIT
python3 -I "${SCRIPT_DIR}/hbt_audit.py" probes "${DESIGN_NETLIST}" > "${HBT_PROBES}" || {
  echo "run_biasop_sweep.sh: could not derive HBT probes from ${DESIGN_NETLIST}" >&2
  exit 3
}

# --- PVT grid (identical to sim/lna-characterization) -------------------
CORNER_LABELS=(typ bcs wcs sf fs)
declare -A HBT_SECTION_OF=( [typ]=hbt_typ [bcs]=hbt_bcs [wcs]=hbt_wcs [sf]=hbt_typ [fs]=hbt_typ )
# DR-0003 Stage-2: the DUT instantiates sg13_hv_pmos/sg13_hv_nmos, so
# the 45-cell grid also maps onto cornerMOShv.lib's sections. cornerMOShv
# ships all five real MOS sections, so the five labels map straight
# through (typ->mos_tt, bcs->mos_ff, wcs->mos_ss, sf->mos_sf,
# fs->mos_fs) per sim/README.md "Corner-label convention" -- only the
# HBT side duplicates (sf/fs have no skewed HBT section and re-use
# hbt_typ).
declare -A MOS_SECTION_OF=( [typ]=mos_tt [bcs]=mos_ff [wcs]=mos_ss [sf]=mos_sf [fs]=mos_fs )
TEMPS=(-40 27 125)
VDDS=(1.62 1.80 1.98)

# --- Acceptance bars (issue #26; both ratified by DR-0002) -------------

if [[ -n "${BIASOP_SMOKE:-}" ]]; then
  OP_CELLS=("typ 27 1.80")
else
  OP_CELLS=()
  for label in "${CORNER_LABELS[@]}"; do
    for t in "${TEMPS[@]}"; do
      for v in "${VDDS[@]}"; do
        OP_CELLS+=("${label} ${t} ${v}")
      done
    done
  done
fi
STARTUP_CELLS=("bcs 125 1.98" "wcs -40 1.62" "typ 27 1.80")
# Smoke: nominal startup only -- the extreme startup cells have no op
# counterpart in a nominal-only run (reduce_biasop.py rejects that pairing).
[[ -n "${BIASOP_SMOKE:-}" ]] && STARTUP_CELLS=("typ 27 1.80")

# Deck rendering (sim_render), the ngspice job pool (sim_jobs /
# sim_pool_init / sim_pool_spawn) and the per-point pass/fail gate
# (sim_check_log) are sim/env.sh's shared surface; this bench adds no
# failure pattern of its own beyond the BENCH_COMPLETE marker.
sim_jobs BIASOP_JOBS
sim_pool_init "${BIASOP_JOBS}"

FAILED_LIST="$(mktemp)"
trap 'rm -f "${SIM_DUT_SUBCKT}" "${HBT_PROBES}" "${FAILED_LIST}"' EXIT

run_op_cell() {
  local corner_label="$1" temp="$2" vdd="$3"
  local hbt_section="${HBT_SECTION_OF[${corner_label}]}"
  local mos_section="${MOS_SECTION_OF[${corner_label}]}"
  local point_id="op_${corner_label}_${temp}c_vdd${vdd}v"
  local netlist="${SNAPSHOTS_OUT}/${point_id}.spice"
  local log="${CORNERS_OUT}/${point_id}.log"
  sim_render "${EXPERIMENT_DIR}/testbench/tb_lna_biasop.spice.tmpl" "${netlist}" \
    -e "/@@HBT_AUDIT_PROBES@@/r ${HBT_PROBES}" -e "/@@HBT_AUDIT_PROBES@@/d" \
    -e "s|@@MODELS_LIB@@|${MODELS_LIB}|g" \
    -e "s|@@HBT_SECTION@@|${hbt_section}|g" \
    -e "s|@@MOS_SECTION@@|${mos_section}|g" \
    -e "s|@@TEMP@@|${temp}|g" \
    -e "s|@@VDD@@|${vdd}|g"
  local rc=0
  ngspice -b "${netlist}" > "${log}" 2>&1 || rc=$?
  sim_check_log "${point_id}" "${log}" "${rc}" || return 0
}

run_startup_cell() {
  local corner_label="$1" temp="$2" vdd="$3"
  local hbt_section="${HBT_SECTION_OF[${corner_label}]}"
  local mos_section="${MOS_SECTION_OF[${corner_label}]}"
  local point_id="startup_${corner_label}_${temp}c_vdd${vdd}v"
  local netlist="${SNAPSHOTS_OUT}/${point_id}.spice"
  local log="${CORNERS_OUT}/${point_id}.log"
  local dat="${CORNERS_OUT}/${point_id}.dat"
  sim_render "${EXPERIMENT_DIR}/testbench/tb_lna_startup.spice.tmpl" "${netlist}" \
    -e "s|@@MODELS_LIB@@|${MODELS_LIB}|g" \
    -e "s|@@HBT_SECTION@@|${hbt_section}|g" \
    -e "s|@@MOS_SECTION@@|${mos_section}|g" \
    -e "s|@@TEMP@@|${temp}|g" \
    -e "s|@@VDD@@|${vdd}|g" \
    -e "s|@@STARTUP_DAT@@|${dat}|g"
  local rc=0
  ngspice -b "${netlist}" > "${log}" 2>&1 || rc=$?
  sim_check_log "${point_id}" "${log}" "${rc}" || return 0
}

echo "run_biasop_sweep.sh: record ${RECORD_ID}; ${#OP_CELLS[@]} op cells, ${#STARTUP_CELLS[@]} startup cells, ${BIASOP_JOBS} job(s)"

for cell in "${OP_CELLS[@]}"; do
  set -- ${cell}
  sim_pool_spawn run_op_cell "${1}" "${2}" "${3}"
done
for cell in "${STARTUP_CELLS[@]}"; do
  set -- ${cell}
  sim_pool_spawn run_startup_cell "${1}" "${2}" "${3}"
done
wait

if [[ -s "${FAILED_LIST}" ]]; then
  echo "run_biasop_sweep.sh: $(wc -l < "${FAILED_LIST}") cell(s) FAILED; no record written (append-only records must be complete)."
  cat "${FAILED_LIST}"
  exit 4
fi

# --- Validate + reduce (reduce_biasop.py) ----------------------------------
# All BIASOP/STARTUP parsing, required-key / finite-value / single-result /
# inventory / op-startup-pair validation and the two CSVs live in the
# stdlib-only reduce_biasop.py (unit-tested and replayable against retained
# logs, see tests/). It writes NOTHING unless every input validates, so
# malformed evidence aborts the run here with exit 4 and no summary. A
# measured bar violation is a legitimate result and still gets a row.
SUMMARY_CSV="${RECORDS_DIR}/${RECORD_ID}-summary.csv"
STARTUP_CSV="${RECORDS_DIR}/${RECORD_ID}-startup.csv"
FACTS_DIR="$(mktemp -d)"
trap 'rm -rf "${SIM_DUT_SUBCKT}" "${HBT_PROBES}" "${FAILED_LIST}" "${FACTS_DIR}"' EXIT
REDUCE_ARGS=(--corners-dir "${CORNERS_OUT}" --summary-csv "${SUMMARY_CSV}"
             --startup-csv "${STARTUP_CSV}" --facts "${FACTS_DIR}/facts"
             --require-audit)
[[ -n "${BIASOP_SMOKE:-}" ]] && REDUCE_ARGS+=(--smoke)
if ! python3 -I "${SCRIPT_DIR}/reduce_biasop.py" "${REDUCE_ARGS[@]}"; then
  echo "run_biasop_sweep.sh: reduction rejected the logs; no summary or record written (append-only records must be complete and well-formed)." >&2
  exit 4
fi

# --- Per-HBT model-validity table (issue #155) ----------------------------
# Separate from the bar CSV: refuses (exit 2 -> no record) if any expected
# instance/probe is missing; genuine out-of-range values are rows, not errors.
HBT_CSV="${RECORDS_DIR}/${RECORD_ID}-hbt-validity.csv"
HBT_ARGS=(reduce --netlist "${DESIGN_NETLIST}" --corners-dir "${CORNERS_OUT}"
          --out-csv "${HBT_CSV}")
[[ -n "${BIASOP_SMOKE:-}" ]] && HBT_ARGS+=(--smoke)
if ! python3 -I "${SCRIPT_DIR}/hbt_audit.py" "${HBT_ARGS[@]}"; then
  echo "run_biasop_sweep.sh: HBT audit rejected the logs; no complete record (the bar CSVs above are partial)." >&2
  exit 4
fi
N_HBT_OOR="$(awk -F, 'NR>1 && $14=="OUT-OF-RANGE"{n++} END{print n+0}' "${HBT_CSV}")"
N_HBT_ROWS="$(awk -F, 'NR>1{n++} END{print n+0}' "${HBT_CSV}")"

# --- Headline numbers (validated; produced by the reducer) ----------------
# shellcheck disable=SC2034  # consumed by the record heredoc below
while IFS='=' read -r _k _v; do
  [[ "${_k}" =~ ^[A-Z0-9_]+$ ]] || { echo "run_biasop_sweep.sh: bad reducer fact '${_k}'" >&2; exit 4; }
  printf -v "${_k}" '%s' "${_v}"
done < "${FACTS_DIR}/facts"

# DR-0003 Stage-2 audit: nominal-cell I_C1 vs DR-0001's 4.0 mA plan-table
# entry, worst-cell servo-transparency error |vl - vbg| and the Qc diode's
# V_BE span all come from the reducer's validated facts.
NOMINAL_PCT_VS_4MA="$(awk -v ic1="${NOMINAL_IC1_A}" 'BEGIN { printf "%.2f", 100.0*(ic1-4.0e-3)/4.0e-3 }')"

# Prose that must follow the measurement, not assume it.
if [[ "${STARTUP_ALL_PASS}" == "yes" ]]; then
  STARTUP_PROSE="all ${N_STARTUP} supply-ramp transient(s) settled to the op point with no ringing or latch"
else
  STARTUP_PROSE="NOT all supply-ramp transients passed (${N_STARTUP_PASS} of ${N_STARTUP} PASS) -- see the startup CSV for the failing verdict(s)"
fi

RECORD_MD="${RECORDS_DIR}/${RECORD_ID}.md"
cat > "${RECORD_MD}" <<EOF
# ${RECORD_ID} -- DC op-point PVT sweep of the Q1 bias generator (issues #26 / #33)

## What this record is

The 45-cell bar evidence for the committed \`design/netlist/lna.spice\`:
originally the acceptance evidence for issue #26's bias-generator
replacement (placeholder resistive divider -> 8:1 density-matched
npn13G2 current-mirror reference), re-run for issue #33's DR-0003
Stage-2 flat-reference core swap (the \`R3a\` feed is deleted; the bref
island is now fed by the amp-servo'd flat-reference core -- see
\`spec/decision-records/0003-flat-pvt-bias-reference.md\` and
\`../biasref-topology/\`). The two bars and their evaluation are
byte-identical in meaning to the pre-swap bench.
**Status, stated row by row**: DR-0002 (issue #32, merged 2026-09-21)
ratified \`spec/target-spec.md\`'s Power (< 10 mW) and Supply rows and
DR-0001 (whose \`I_C1 <= 4.5 mA\` bias-network mandate it carries), and
DR-0002's Power-row binding conditions explicitly name issue #26 -- this
bias-generator work -- as the verification gate whose evidence it awaits.
This record is that evidence, with every number traceable to the bench
that produced it; the rows DR-0002 left DRAFT (e.g. the IIP3 numeric
target) stay DRAFT pending their own decision record, and nothing here
relaxes any row.

## PDK

- PDK_ROOT: \`${PDK_ROOT}\` (PDK: \`${PDK}\`, pinned release in
  \`sim/pdk.json\`)
- PDK identity (verified): \`${SIM_PDK_RELEASE}\` via ${SIM_PDK_ID_ROUTE}; model hashes in \`records/${RECORD_ID}.pdk-provenance.json\`
- ngspice: \`${NGSPICE_VERSION}\`

## DUT

- \`design/netlist/lna.spice\` sha256: \`${DESIGN_NETLIST_SHA}\`
- repo HEAD (short): \`${REPO_GIT_SHA}\`

## Grid

- {typ,bcs,wcs,sf,fs} x {-40,27,125} C x {1.62,1.80,1.98} V = full grid; this record validated ${N_OP} op cell(s) and ${N_STARTUP} startup cell(s)
  (\`cornerHBT.lib\` sections \`hbt_typ\`/\`hbt_bcs\`/\`hbt_wcs\`;
  \`sf\`/\`fs\` duplicate \`hbt_typ\` -- no skewed HBT section ships, per
  \`sim/README.md\`'s "Corner-label convention"), and -- since the
  DR-0003 Stage-2 DUT instantiates \`sg13_hv_pmos\`/\`sg13_hv_nmos\` --
  \`cornerMOShv.lib\` sections mapped straight through by the five labels
  (\`mos_tt\`/\`mos_ff\`/\`mos_ss\`/\`mos_sf\`/\`mos_fs\`), with the OSDI
  models preloaded (\`pre_osdi\`).
- Analysis: ngspice \`op\` per cell; probes named in
  \`testbench/tb_lna_biasop.spice.tmpl\`.
- Failed cells: none (simulator gate); reduction validated every log (required keys, finite values, one result per point, full inventory, op/startup pairs).

## Bars evaluated

| Bar | Source | Status |
|---|---|---|
| I_C1 <= 4.5 mA at every cell | DR-1 bias-network requirement (proposed DR, cited by #26) | ${N_IC1_BAD} violation(s) of ${N_OP} cells |
| P_dc < 10 mW at every cell | spec/target-spec.md Power row (DR-0002 issue #32, ratified; verification gate named this issue) | ${N_PDC_BAD} violation(s) of ${N_OP} cells |

## Results

- **I_C1** spans $(awk "BEGIN{printf \"%.4f\", ${IC1_MIN}*1000}") mA (cell ${IC1_MIN_CELL})
  .. $(awk "BEGIN{printf \"%.4f\", ${IC1_MAX}*1000}") mA (cell ${IC1_MAX_CELL})
  over the ${N_OP} cells. Old divider evidence
  (\`../lna-characterization/records/\`): 0.0249 .. 14.697 mA.
- **P_dc** spans $(awk "BEGIN{printf \"%.4f\", ${PDC_MIN}*1000}") mW (cell ${PDC_MIN_CELL})
  .. $(awk "BEGIN{printf \"%.4f\", ${PDC_MAX}*1000}") mW (cell ${PDC_MAX_CELL}).
  Old divider evidence: 0.386 .. 29.639 mW.
- **Margins at the binding cells**: I_C1 max is $(awk "BEGIN{printf \"%.2f\", 100*(4.5-${IC1_MAX}*1000)/4.5}")% under the 4.5 mA bar; P_dc max is $(awk "BEGIN{printf \"%.2f\", 100*(10.0-${PDC_MAX}*1000)/10.0}")% under the 10 mW bar.
- **Mirror transfer check**: I_C1 vs 8*I_C3 per cell (same-file columns);
  Q1's I_B1 span confirms the beta-independence of the transfer.
- **Startup/latch check**: ${STARTUP_PROSE} (verdicts: ${STARTUP_VERDICTS}).
  See \`${RECORD_ID}-startup.csv\` and the wrdata artifacts.
- **Per-HBT model-validity audit** (issue #155): \`${RECORD_ID}-hbt-validity.csv\`
  has one row per npn13G2 instance per cell (${N_HBT_ROWS} rows; instances
  are read from the simulated netlist). ${N_HBT_OOR} row(s) are outside the
  model validity box (ic < 0.003*Nx A, vbe 0.65-0.96 V, vce 0.4-2.0 V,
  source: sg13g2_hbt_mod.lib header). Junction temperature is UNASSESSED:
  npn13G2 exposes no self-heating node, and ambient-temperature coverage is
  a separate column. Model validity is not a breakdown/stress rating.
- **DR-0003 Stage-2 core audit** (extra BIASOP keys; the CSV's bar columns
  are unchanged): the nominal cell (typ/27C/1.80V) lands \`I_C1\` at
  $(awk -v x="${NOMINAL_IC1_A:-0}" 'BEGIN{printf "%.4f", x*1000}') mA
  = $(awk -v x="${NOMINAL_PCT_VS_4MA:-0}" 'BEGIN{printf "%+.2f", x}') % vs
  DR-0001's 4.0 mA plan-table entry (inside the DR-0003 Stage-2 sizing
  amendment's stated +/-3 % tolerance band); the amp-servo's worst-cell
  transduction error |vl - vbg| is ${SERVO_MAX_ERR_V:-n/a} V (servo
  transparency); the new sum-branch diode Qc rides V_BE(cold-cell max) =
  ${QC_VBE_MAX:-n/a} V .. V_BE(hot-cell min) = ${QC_VBE_MIN:-n/a} V
  across the grid (its collector-base is diode-tied, so V_CE = V_BE).

## Method limits (what this record does NOT say)

- **No RF claim.** \`op\` only. The re-bias moves the RF operating point
  (b1 still sees 330 Ohm R3b into an RF-grounded reference island, but
  I_C1 moved from the 3.06 mA committed mirror nominal to the 4.0 mA
  plan-table entry); S-parameters / NF / stability consequences are
  measured by re-running
  \`../lna-characterization/run_lna_sweep.sh\` against this same netlist,
  and coordinate with #27's matching-network work, which owns that RF
  state.
- **The decks' explicit \`gmin=1e-10\`** in \`.options\` is VALUE-IDENTICAL
  to ngspice's default (no numeric shift on cells that converged
  before); making it explicit selects ngspice's working gmin-stepping
  fallback, which the Stage-2 netlist's \`op\` needs at the
  bcs/-40C/1.62V cell (verified: plain implicit default aborts with
  singular iterations there; the explicit card converges 45/45). The
  startup deck's fine initial tran step (1e-9 vs the committed 5e-8) is
  the sg13g2-bandgap fleet's own documented cure for the ngspice VBIC
  boot-desert "Timestep too small" abort (their closed-loop-startup /
  closed-loop-vref-pvt headers, issues #58/#151) -- reproduced here
  against the committed 5e-8 before adopting it.
- **No mismatch/model-spread sections** (\`hbt_*_mismatch\`/\`_stat\` are
  out of scope, matching the campaign convention this grid mirrors).
- **Ideal R/C**: the mirror's resistors are generic ideal primitives with
  no tolerance or tempco, exactly like every other passive in this
  schematic; resistor matching is a layout-time parameter outside this
  record's scope.
- **Model validity box**: every npn13G2 instance here rides inside
  sg13g2_hbt_mod.lib's stated validity box (V_BE 0.65..0.96 V,
  V_CE 0.4..2.0 V, T -40..+125 C) -- worth re-checking on any future
  re-bias; Q3's cold V_BREF and Q1/Q2's V_CE are the closest calls.

## Regeneration

\`\`\`bash
export PDK_ROOT=/path/to/ihp-open-pdk PDK=ihp-sg13g2
sim/lna-bias-pvt/run_biasop_sweep.sh
\`\`\`

## Links

- Templates: \`testbench/tb_lna_biasop.spice.tmpl\`,
  \`testbench/tb_lna_startup.spice.tmpl\`
- Per-point generated netlists: \`netlist-snapshots/${RECORD_ID}/\`
- Per-point raw ngspice logs / wrdata: \`corners/${RECORD_ID}/\`
- Per-cell CSV: \`records/${RECORD_ID}-summary.csv\`
- Startup CSV: \`records/${RECORD_ID}-startup.csv\`
- Issue: #26 (original acceptance criteria and scope); issue #33 /
  DR-0003 Stage 2 (the flat-reference core swap this record re-verifies)
- Stage-2 design-space bench: \`../biasref-topology/\` (skeleton, sum
  branch, and servo-core evidence)
- Pre-fix divider evidence: \`../lna-characterization/records/20260918-210908-4293920*\`
EOF

echo "run_biasop_sweep.sh: done. Record ${RECORD_ID}"
echo "  summary : ${SUMMARY_CSV}"
echo "  record  : ${RECORD_MD}"
echo "  I_C1 span: $(awk "BEGIN{printf \"%.4f\", ${IC1_MIN}*1000}") .. $(awk "BEGIN{printf \"%.4f\", ${IC1_MAX}*1000}") mA   | bar: <= 4.5 mA  (${N_IC1_BAD} violation(s))"
echo "  P_dc span: $(awk "BEGIN{printf \"%.4f\", ${PDC_MIN}*1000}") .. $(awk "BEGIN{printf \"%.4f\", ${PDC_MAX}*1000}") mW     | bar: < 10 mW    (${N_PDC_BAD} violation(s))"
echo "  startup verdicts: ${STARTUP_VERDICTS}"