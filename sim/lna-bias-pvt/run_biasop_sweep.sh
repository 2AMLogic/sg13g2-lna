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
# models"). Requires neither xschem nor python3 (npn13G2 itself stays a
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
REPO_ROOT="$(cd "${SIM_DIR}/.." && pwd)"

# shellcheck source=/dev/null
source "${SIM_DIR}/env.sh"

if [[ -z "${PDK_ROOT:-}" || ! -d "${PDK_ROOT}/${PDK}/libs.tech/ngspice" ]]; then
  echo "run_biasop_sweep.sh: no resolvable ${PDK:-ihp-sg13g2} install -- see sim/env.sh output above." >&2
  exit 3
fi

command -v ngspice >/dev/null 2>&1 || { echo "run_biasop_sweep.sh: ngspice not on PATH." >&2; exit 3; }
NGSPICE_VERSION="$(ngspice -v 2>&1 | sed -n '2p')"

MODELS_LIB="${PDK_ROOT}/${PDK}/libs.tech/ngspice/models/cornerHBT.lib"
MOS_LIB="${PDK_ROOT}/${PDK}/libs.tech/ngspice/models/cornerMOShv.lib"
OSDI_DIR="${PDK_ROOT}/${PDK}/libs.tech/ngspice/osdi"
if [[ ! -f "${MODELS_LIB}" ]]; then
  echo "run_biasop_sweep.sh: cornerHBT.lib not found at ${MODELS_LIB}" >&2
  exit 3
fi
for f in "${MOS_LIB}" "${OSDI_DIR}/psp103.osdi" "${OSDI_DIR}/psp103_nqs.osdi" "${OSDI_DIR}/mosvar.osdi"; do
  if [[ ! -f "${f}" ]]; then
    echo "run_biasop_sweep.sh: ${f} not found -- if the .osdi models are missing, run sim/tools/build-osdi.sh (see sim/README.md 'OSDI device models'); the DR-0003 Stage-2 DUT will not simulate without them." >&2
    exit 3
  fi
done

DESIGN_NETLIST="${REPO_ROOT}/design/netlist/lna.spice"
if [[ ! -f "${DESIGN_NETLIST}" ]]; then
  echo "run_biasop_sweep.sh: design netlist not found at ${DESIGN_NETLIST}" >&2
  exit 3
fi
DESIGN_NETLIST_SHA="$(shasum -a 256 "${DESIGN_NETLIST}" | awk '{print $1}')"

REPO_GIT_SHA="$(cd "${REPO_ROOT}" && git rev-parse --short HEAD 2>/dev/null || echo unknown)"
RECORD_ID="$(date -u +%Y%m%d-%H%M%S)-${REPO_GIT_SHA}"

EXPERIMENT_DIR="${SCRIPT_DIR}"
SNAPSHOTS_OUT="${EXPERIMENT_DIR}/netlist-snapshots/${RECORD_ID}"
CORNERS_OUT="${EXPERIMENT_DIR}/corners/${RECORD_ID}"
RECORDS_DIR="${EXPERIMENT_DIR}/records"
mkdir -p "${SNAPSHOTS_OUT}" "${CORNERS_OUT}" "${RECORDS_DIR}"

# --- DUT: the committed design netlist, inlined verbatim ----------------
# Same uncomment-subckt convention as sim/lna-characterization's runner.
DUT_SUBCKT="$(mktemp)"
trap 'rm -f "${DUT_SUBCKT}"' EXIT
sed -e 's|^\*\*\.subckt|.subckt|' \
    -e 's|^\*\*\.ends|.ends|' \
    -e '/^\.end$/d' \
    "${DESIGN_NETLIST}" > "${DUT_SUBCKT}"
grep -q '^\.subckt lna ' "${DUT_SUBCKT}" || {
  echo "run_biasop_sweep.sh: could not recover a '.subckt lna ...' line from ${DESIGN_NETLIST}" >&2
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

render() {
  # render <template> <outfile> <sed-args...>
  local tmpl="$1" out="$2"; shift 2
  sed "$@" \
    -e "s|@@MODELS_LIB@@|${MODELS_LIB}|g" \
    -e "s|@@MOS_LIB@@|${MOS_LIB}|g" \
    -e "s|@@OSDI_DIR@@|${OSDI_DIR}|g" \
    "${tmpl}" \
    | sed -e "/@@LNA_SUBCKT@@/r ${DUT_SUBCKT}" -e "/@@LNA_SUBCKT@@/d" > "${out}"
}

_ncpu="$(sysctl -n ncpu 2>/dev/null || getconf _NPROCESSORS_ONLN 2>/dev/null || echo 3)"
BIASOP_JOBS="${BIASOP_JOBS:-$(( _ncpu / 3 ))}"
(( BIASOP_JOBS < 1 )) && BIASOP_JOBS=1
(( BIASOP_JOBS > 6 )) && BIASOP_JOBS=6

FAILED_LIST="$(mktemp)"
trap 'rm -f "${DUT_SUBCKT}" "${FAILED_LIST}"' EXIT

pool_spawn() {
  # pool_spawn <fn> <args...> -- run in the background, at most
  # BIASOP_JOBS at a time. `trap - EXIT` in the child keeps the child's
  # exit from deleting the parent's shared temp files.
  while (( $(jobs -rp | wc -l) >= BIASOP_JOBS )); do
    wait -n 2>/dev/null || true
  done
  ( trap - EXIT; "$@" ) &
}

_check() { # _check <point_id> <log> <rc>
  local pid="$1" log="$2" rc="$3"
  if [[ "${rc}" != 0 ]] || ! grep -q "^BENCH_COMPLETE" "${log}"; then
    echo "run_biasop_sweep.sh: FAILED ${pid} (rc=${rc}) -- see ${log}" >&2
    echo "${pid}" >> "${FAILED_LIST}"
    return 1
  fi
  return 0
}

run_op_cell() {
  local corner_label="$1" temp="$2" vdd="$3"
  local hbt_section="${HBT_SECTION_OF[${corner_label}]}"
  local mos_section="${MOS_SECTION_OF[${corner_label}]}"
  local point_id="op_${corner_label}_${temp}c_vdd${vdd}v"
  local netlist="${SNAPSHOTS_OUT}/${point_id}.spice"
  local log="${CORNERS_OUT}/${point_id}.log"
  render "${EXPERIMENT_DIR}/testbench/tb_lna_biasop.spice.tmpl" "${netlist}" \
    -e "s|@@MODELS_LIB@@|${MODELS_LIB}|g" \
    -e "s|@@HBT_SECTION@@|${hbt_section}|g" \
    -e "s|@@MOS_SECTION@@|${mos_section}|g" \
    -e "s|@@TEMP@@|${temp}|g" \
    -e "s|@@VDD@@|${vdd}|g"
  local rc=0
  ngspice -b "${netlist}" > "${log}" 2>&1 || rc=$?
  _check "${point_id}" "${log}" "${rc}" || return 0
}

run_startup_cell() {
  local corner_label="$1" temp="$2" vdd="$3"
  local hbt_section="${HBT_SECTION_OF[${corner_label}]}"
  local mos_section="${MOS_SECTION_OF[${corner_label}]}"
  local point_id="startup_${corner_label}_${temp}c_vdd${vdd}v"
  local netlist="${SNAPSHOTS_OUT}/${point_id}.spice"
  local log="${CORNERS_OUT}/${point_id}.log"
  local dat="${CORNERS_OUT}/${point_id}.dat"
  render "${EXPERIMENT_DIR}/testbench/tb_lna_startup.spice.tmpl" "${netlist}" \
    -e "s|@@MODELS_LIB@@|${MODELS_LIB}|g" \
    -e "s|@@HBT_SECTION@@|${hbt_section}|g" \
    -e "s|@@MOS_SECTION@@|${mos_section}|g" \
    -e "s|@@TEMP@@|${temp}|g" \
    -e "s|@@VDD@@|${vdd}|g" \
    -e "s|@@STARTUP_DAT@@|${dat}|g"
  local rc=0
  ngspice -b "${netlist}" > "${log}" 2>&1 || rc=$?
  _check "${point_id}" "${log}" "${rc}" || return 0
}

echo "run_biasop_sweep.sh: record ${RECORD_ID}; ${#OP_CELLS[@]} op cells, ${#STARTUP_CELLS[@]} startup cells, ${BIASOP_JOBS} job(s)"

for cell in "${OP_CELLS[@]}"; do
  set -- ${cell}
  pool_spawn run_op_cell "${1}" "${2}" "${3}"
done
for cell in "${STARTUP_CELLS[@]}"; do
  set -- ${cell}
  pool_spawn run_startup_cell "${1}" "${2}" "${3}"
done
wait

if [[ -s "${FAILED_LIST}" ]]; then
  echo "run_biasop_sweep.sh: $(wc -l < "${FAILED_LIST}") cell(s) FAILED; no record written (append-only records must be complete)."
  cat "${FAILED_LIST}"
  exit 4
fi

# --- Parse (sequential, deterministic) -----------------------------------
SUMMARY_CSV="${RECORDS_DIR}/${RECORD_ID}-summary.csv"
echo "point_id,corner_label,temp_c,vdd_v,ic1_a,ic2_a,ic3_a,ib1_a,vb1_v,vbref_v,vce1_v,vce2_v,vbe1_v,idd_a,pdc_w,ic1_within_4p5ma,pdc_within_10mw" \
  > "${SUMMARY_CSV}"
for cell in "${OP_CELLS[@]}"; do
  set -- ${cell}
  label="$1"; temp="$2"; vdd="$3"
  point_id="op_${label}_${temp}c_vdd${vdd}v"
  awk -v pid="${point_id}" -v lbl="${label}" -v t="${temp}" -v v="${vdd}" \
      -v iclim="4.5e-3" -v pdclim="10e-3" '
    /^BIASOP / {
      for (i = 2; i < NF; i += 2) { k = $i; kv = $(i+1); val[k] = kv }
      ic1ok = (val["ic1"] <= iclim) ? "yes" : "NO"
      pdcok = (val["pdc"] < pdclim) ? "yes" : "NO"
      printf "%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s\n", \
        pid, lbl, t, v, val["ic1"], val["ic2"], val["ic3"], val["ib1"], \
        val["vb1"], val["vbref"], val["vce1"], val["vce2"], val["vbe1"], \
        val["idd"], val["pdc"], ic1ok, pdcok
    }' "${CORNERS_OUT}/${point_id}.log" >> "${SUMMARY_CSV}"
done

# Startup verdicts.
STARTUP_CSV="${RECORDS_DIR}/${RECORD_ID}-startup.csv"
echo "point_id,corner_label,temp_c,vdd_v,ic1_end_a,ic1_op_a,end_vs_op_pct,settled_spread_pct,verdict" \
  > "${STARTUP_CSV}"
for cell in "${STARTUP_CELLS[@]}"; do
  set -- ${cell}
  label="$1"; temp="$2"; vdd="$3"
  point_id="startup_${label}_${temp}c_vdd${vdd}v"
  op_id="op_${label}_${temp}c_vdd${vdd}v"
  op_ic1="$(awk -F, -v p="${op_id}" '$1==p {print $5}' "${SUMMARY_CSV}")"
  awk -v pid="${point_id}" -v lbl="${label}" -v t="${temp}" -v v="${vdd}" -v opic="${op_ic1:-0}" '
    /^STARTUP / {
      for (i = 2; i < NF; i += 2) { k = $i; val[k] = $(i+1) }
      end = val["ic1_end"]; s2 = val["ic1_s2"]; s3 = val["ic1_s3"]
      mx = end; mn = end
      if (s2 > mx) mx = s2; if (s3 > mx) mx = s3
      if (s2 < mn) mn = s2; if (s3 < mn) mn = s3
      mean = (end + s2 + s3) / 3.0
      spread = (mean > 0) ? 100.0 * (mx - mn) / mean : 999
      dvsop  = (opic > 0) ? 100.0 * (end - opic) / opic : 999
      verdict = "PASS"
      if (spread > 2.0) verdict = "NO-RINGING-FAIL"
      if (dvsop > 5.0 || dvsop < -5.0) verdict = "OP-MISMATCH-FAIL"
      if (end <= 0) verdict = "LATCHED-ZERO"
      printf "%s,%s,%s,%s,%.6g,%.6g,%.3f,%.3f,%s\n", pid, lbl, t, v, end, opic, dvsop, spread, verdict
    }' "${CORNERS_OUT}/${point_id}.log" >> "${STARTUP_CSV}"
done

# --- Headline numbers -----------------------------------------------------
read -r IC1_MIN_CELL IC1_MIN IC1_MAX_CELL IC1_MAX PDC_MIN_CELL PDC_MIN PDC_MAX_CELL PDC_MAX \
  N_IC1_OK N_IC1_BAD N_PDC_OK N_PDC_BAD <<<"$(awk -F, '
    BEGIN { icok = 0; icbad = 0; pdok = 0; pdbad = 0; minset = 0; pminset = 0; max = 0; pmax = 0 }
    NR>1 {
      if (!minset || $5 < min) { min = $5; minc = $1 } ; minset = 1
      if ($5 > max) { max = $5; maxc = $1 }
      if (!pminset || $15 < pmin) { pmin = $15; pminc = $1 } ; pminset = 1
      if ($15 > pmax) { pmax = $15; pmaxc = $1 }
      if ($16 == "yes") icok++; else icbad++
      if ($17 == "yes") pdok++; else pdbad++
    }
    END { print minc, min, maxc, max, pminc, pmin, pmaxc, pmax, icok+0, icbad+0, pdok+0, pdbad+0 }' \
    "${SUMMARY_CSV}")"
SU_VERDICTS="$(awk -F, 'NR>1 && $9 != "" {print $9}' "${STARTUP_CSV}" | sort -u | tr '\n' ' ')"

# --- DR-0003 Stage-2 audit stats (from the extra BIASOP keys in the logs) --
# Nominal cell's I_C1 vs DR-0001's 4.0 mA plan-table entry (the DR-0003
# Stage-2 sizing amendment states the tolerance this landing is judged
# against), the worst-case servo-transparency error |vl - vbg| over the
# 45 cells, and the new Qc diode's V_BE span (its validity-box ride).
NOMINAL_CELL="op_typ_27c_vdd1.80v"
NOMINAL_IC1_A="$(awk '/^BIASOP / { for (i=2;i<NF;i+=2) if ($i=="ic1") print $(i+1) }' "${CORNERS_OUT}/${NOMINAL_CELL}.log" | head -1)"
SERVO_MAX_ERR_V="$(for f in "${CORNERS_OUT}"/op_*.log; do awk '/^BIASOP / { for (i=2;i<NF;i+=2) { if ($i=="vl") vl=$(i+1); if ($i=="vbg") vbg=$(i+1) } e=(vl>vbg)?(vl-vbg):(vbg-vl); if (e>m) m=e } END { printf "%.6g\n", m }' "$f"; done | sort -g | tail -1)"
QC_VBE_MIN="$(for f in "${CORNERS_OUT}"/op_*.log; do awk '/^BIASOP / { for (i=2;i<NF;i+=2) if ($i=="cb3") print $(i+1) }' "$f"; done | sort -g | head -1)"
QC_VBE_MAX="$(for f in "${CORNERS_OUT}"/op_*.log; do awk '/^BIASOP / { for (i=2;i<NF;i+=2) if ($i=="cb3") print $(i+1) }' "$f"; done | sort -g | tail -1)"
NOMINAL_PCT_VS_4MA="$(awk -v ic1="${NOMINAL_IC1_A:-0}" 'BEGIN { printf "%.2f", 100.0*(ic1-4.0e-3)/4.0e-3 }')"

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
- ngspice: \`${NGSPICE_VERSION}\`

## DUT

- \`design/netlist/lna.spice\` sha256: \`${DESIGN_NETLIST_SHA}\`
- repo HEAD (short): \`${REPO_GIT_SHA}\`

## Grid

- {typ,bcs,wcs,sf,fs} x {-40,27,125} C x {1.62,1.80,1.98} V = 45 cells
  (\`cornerHBT.lib\` sections \`hbt_typ\`/\`hbt_bcs\`/\`hbt_wcs\`;
  \`sf\`/\`fs\` duplicate \`hbt_typ\` -- no skewed HBT section ships, per
  \`sim/README.md\`'s "Corner-label convention"), and -- since the
  DR-0003 Stage-2 DUT instantiates \`sg13_hv_pmos\`/\`sg13_hv_nmos\` --
  \`cornerMOShv.lib\` sections mapped straight through by the five labels
  (\`mos_tt\`/\`mos_ff\`/\`mos_ss\`/\`mos_sf\`/\`mos_fs\`), with the OSDI
  models preloaded (\`pre_osdi\`).
- Analysis: ngspice \`op\` per cell; probes named in
  \`testbench/tb_lna_biasop.spice.tmpl\`.
- Failed cells: none.

## Bars evaluated

| Bar | Source | Status |
|---|---|---|
| I_C1 <= 4.5 mA at every cell | DR-1 bias-network requirement (proposed DR, cited by #26) | ${N_IC1_BAD} violation(s) of ${N_IC1_OK} cells |
| P_dc < 10 mW at every cell | spec/target-spec.md Power row (DR-0002 issue #32, ratified; verification gate named this issue) | ${N_PDC_BAD} violation(s) of ${N_PDC_OK} cells |

## Results

- **I_C1** spans $(awk "BEGIN{printf \"%.4f\", ${IC1_MIN}*1000}") mA (cell ${IC1_MIN_CELL})
  .. $(awk "BEGIN{printf \"%.4f\", ${IC1_MAX}*1000}") mA (cell ${IC1_MAX_CELL})
  over the ${N_IC1_OK} cells. Old divider evidence
  (\`../lna-characterization/records/\`): 0.0249 .. 14.697 mA.
- **P_dc** spans $(awk "BEGIN{printf \"%.4f\", ${PDC_MIN}*1000}") mW (cell ${PDC_MIN_CELL})
  .. $(awk "BEGIN{printf \"%.4f\", ${PDC_MAX}*1000}") mW (cell ${PDC_MAX_CELL}).
  Old divider evidence: 0.386 .. 29.639 mW.
- **Margins at the binding cells**: I_C1 max is $(awk "BEGIN{printf \"%.2f\", 100*(4.5-${IC1_MAX}*1000)/4.5}")% under the 4.5 mA bar; P_dc max is $(awk "BEGIN{printf \"%.2f\", 100*(10.0-${PDC_MAX}*1000)/10.0}")% under the 10 mW bar.
- **Mirror transfer check**: I_C1 vs 8*I_C3 per cell (same-file columns);
  Q1's I_B1 span confirms the beta-independence of the transfer.
- **Startup/latch check**: supply-ramp transients at the nominal and both
  extreme cells settled to the op point (verdicts: ${SU_VERDICTS:-none}).
  See \`${RECORD_ID}-startup.csv\` and the wrdata artifacts.
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
echo "  startup verdicts: ${SU_VERDICTS:-none}"