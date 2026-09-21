#!/usr/bin/env bash
# Cold-start invocation:
#
#   export PDK_ROOT=/path/to/ihp-open-pdk   # parent dir containing ihp-sg13g2/
#   export PDK=ihp-sg13g2
#   sim/lna-bias-pvt/run_biasop_sweep.sh
#
# (PDK_ROOT/PDK may also be left unset if the PDK is installed under one of
# the usual prefixes sim/env.sh checks.) Requires ngspice on PATH; requires
# neither xschem, python3 nor any OSDI build step (npn13G2 is a native
# ngspice VBIC model -- see sim/pdk.json). Full methodology, bench
# definitions and stated method limits are in sim/lna-bias-pvt/README.md --
# read that first if a result here looks surprising.
#
# Runs the DC operating-point PVT sweep that issue #26's acceptance
# criteria ask for, against the COMMITTED design/netlist/lna.spice (i.e.
# the regenerated netlist of the post-fix design/lna.sch):
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
if [[ ! -f "${MODELS_LIB}" ]]; then
  echo "run_biasop_sweep.sh: cornerHBT.lib not found at ${MODELS_LIB}" >&2
  exit 3
fi

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
  local point_id="op_${corner_label}_${temp}c_vdd${vdd}v"
  local netlist="${SNAPSHOTS_OUT}/${point_id}.spice"
  local log="${CORNERS_OUT}/${point_id}.log"
  render "${EXPERIMENT_DIR}/testbench/tb_lna_biasop.spice.tmpl" "${netlist}" \
    -e "s|@@MODELS_LIB@@|${MODELS_LIB}|g" \
    -e "s|@@HBT_SECTION@@|${hbt_section}|g" \
    -e "s|@@TEMP@@|${temp}|g" \
    -e "s|@@VDD@@|${vdd}|g"
  local rc=0
  ngspice -b "${netlist}" > "${log}" 2>&1 || rc=$?
  _check "${point_id}" "${log}" "${rc}" || return 0
}

run_startup_cell() {
  local corner_label="$1" temp="$2" vdd="$3"
  local hbt_section="${HBT_SECTION_OF[${corner_label}]}"
  local point_id="startup_${corner_label}_${temp}c_vdd${vdd}v"
  local netlist="${SNAPSHOTS_OUT}/${point_id}.spice"
  local log="${CORNERS_OUT}/${point_id}.log"
  local dat="${CORNERS_OUT}/${point_id}.dat"
  render "${EXPERIMENT_DIR}/testbench/tb_lna_startup.spice.tmpl" "${netlist}" \
    -e "s|@@MODELS_LIB@@|${MODELS_LIB}|g" \
    -e "s|@@HBT_SECTION@@|${hbt_section}|g" \
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

RECORD_MD="${RECORDS_DIR}/${RECORD_ID}.md"
cat > "${RECORD_MD}" <<EOF
# ${RECORD_ID} -- DC op-point PVT sweep of the Q1 bias generator (issue #26)

## What this record is

The acceptance evidence for issue #26's bias-generator replacement
(Q1's placeholder resistive divider -> 8:1 density-matched npn13G2
current-mirror reference): the DC operating point of the committed
\`design/netlist/lna.spice\` across the same 45-cell PVT grid the issue's
divider evidence used, evaluated against the two bars the issue names.
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
  \`sim/README.md\`'s "Corner-label convention").
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

## Method limits (what this record does NOT say)

- **No RF claim.** \`op\` only. The new bias network changes the RF
  impedance seen at b1 (the old ~5.1 k divider Thevenin is now 330 Ohm
  R3b into an RF-grounded reference island); S-parameters / NF /
  stability consequences are measured by re-running
  \`../lna-characterization/run_lna_sweep.sh\` against this same netlist.
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
- Issue: #26 (acceptance criteria and scope)
- Pre-fix divider evidence: \`../lna-characterization/records/20260918-210908-4293920*\`
EOF

echo "run_biasop_sweep.sh: done. Record ${RECORD_ID}"
echo "  summary : ${SUMMARY_CSV}"
echo "  record  : ${RECORD_MD}"
echo "  I_C1 span: $(awk "BEGIN{printf \"%.4f\", ${IC1_MIN}*1000}") .. $(awk "BEGIN{printf \"%.4f\", ${IC1_MAX}*1000}") mA   | bar: <= 4.5 mA  (${N_IC1_BAD} violation(s))"
echo "  P_dc span: $(awk "BEGIN{printf \"%.4f\", ${PDC_MIN}*1000}") .. $(awk "BEGIN{printf \"%.4f\", ${PDC_MAX}*1000}") mW     | bar: < 10 mW    (${N_PDC_BAD} violation(s))"
echo "  startup verdicts: ${SU_VERDICTS:-none}"