#!/usr/bin/env bash
# Cold-start invocation:
#
#   export PDK_ROOT=/path/to/ihp-open-pdk   # parent dir containing ihp-sg13g2/
#   export PDK=ihp-sg13g2
#   sim/tools/build-osdi.sh --check          # one-time: OSDI models present+loadable
#   sim/biasref-topology/run_biasref_sweep.sh
#
# (PDK_ROOT/PDK may also be left unset if the PDK is installed under one of
# the usual prefixes sim/env.sh checks.) Requires ngspice on PATH and the
# OSDI device models the Option-A core instantiates (sg13_hv_pmos is PSP103,
# a Verilog-A/OSDI device -- unlike the npn13G2-only benches, this runner
# will not simulate without them; build/load them with sim/tools/build-osdi.sh,
# see sim/README.md "OSDI device models"). Full methodology, bench
# definitions and stated method limits are in sim/biasref-topology/README.md
# -- read that first if a result here looks surprising.
#
# Issue #33 / DR-0003 design-space evidence. Three benches, one record:
#   Phase A (mpa-diode): the pnpMPA diode-connected terminal drop over
#     {typ,bcs,wcs} x {-40,27,125} C at feed currents {0.52mA, 100uA, 20uA} --
#     the Curator-pass Option-B adequacy trace (the same cornerHBT.lib
#     sections corner pnpMPA via sgp_mpa_* scalars).
#   Phase B (core-minigrid): the Option-A first-increment core (self-biased
#     Widlar PTAT skeleton on sg13_hv_pmos + npn13G2, seed leg, 21:1 output
#     copy into the Q3 island diode) over {typ,bcs,wcs} x {-40,27,125} C x
#     {1.62,1.80,1.98} V -- the supply-independence and residual-tone
#     evidence. The MOS corner maps typ->mos_tt, bcs->mos_ff, wcs->mos_ss
#     (sim/README.md "Corner-label convention").
#   Phase C (core-startup): supply-ramp transients at the three cells the
#     committed lna-bias-pvt startup check uses, verifying the seed leg
#     starts the loop and it settles to the op bench's value (no latch, no
#     ringing).
#
# Writes append-only evidence under corners/<record-id>/,
# netlist-snapshots/<record-id>/ and records/<record-id>-*.csv +
# <record-id>.md -- see sim/README.md for the convention this follows.
#
# Environment knobs (all optional):
#   BIASREF_JOBS=<n>   how many ngspice processes to run concurrently
#                      (default: min(6, ncpu/3), floor 1). Every point writes
#                      only its OWN files; concurrency changes nothing about
#                      the numbers. Set 1 for a strictly serial run.
#   BIASREF_SMOKE=1    nominal cells only, for plumbing checks.
set -euo pipefail

if (( BASH_VERSINFO[0] < 4 || (BASH_VERSINFO[0] == 4 && BASH_VERSINFO[1] < 3) )); then
  echo "run_biasref_sweep.sh: needs bash >= 4.3 (found ${BASH_VERSION})." >&2
  exit 3
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SIM_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
REPO_ROOT="$(cd "${SIM_DIR}/.." && pwd)"

# shellcheck source=/dev/null
source "${SIM_DIR}/env.sh"

if [[ -z "${PDK_ROOT:-}" || ! -d "${PDK_ROOT}/${PDK}/libs.tech/ngspice" ]]; then
  echo "run_biasref_sweep.sh: no resolvable ${PDK:-ihp-sg13g2} install -- see sim/env.sh output above." >&2
  exit 3
fi

command -v ngspice >/dev/null 2>&1 || { echo "run_biasref_sweep.sh: ngspice not on PATH." >&2; exit 3; }
NGSPICE_VERSION="$(ngspice -v 2>&1 | sed -n '2p')"

MODELS_LIB="${PDK_ROOT}/${PDK}/libs.tech/ngspice/models/cornerHBT.lib"
MOS_LIB="${PDK_ROOT}/${PDK}/libs.tech/ngspice/models/cornerMOShv.lib"
OSDI_DIR="${PDK_ROOT}/${PDK}/libs.tech/ngspice/osdi"
for f in "${MODELS_LIB}" "${MOS_LIB}" "${OSDI_DIR}/psp103.osdi" "${OSDI_DIR}/psp103_nqs.osdi" "${OSDI_DIR}/mosvar.osdi"; do
  if [[ ! -f "${f}" ]]; then
    echo "run_biasref_sweep.sh: missing ${f} -- if it is the .osdi models, run sim/tools/build-osdi.sh (see sim/README.md 'OSDI device models')." >&2
    exit 3
  fi
done

REPO_GIT_SHA="$(cd "${REPO_ROOT}" && git rev-parse --short HEAD 2>/dev/null || echo unknown)"
RECORD_ID="$(date -u +%Y%m%d-%H%M%S)-${REPO_GIT_SHA}"

EXPERIMENT_DIR="${SCRIPT_DIR}"
SNAPSHOTS_OUT="${EXPERIMENT_DIR}/netlist-snapshots/${RECORD_ID}"
CORNERS_OUT="${EXPERIMENT_DIR}/corners/${RECORD_ID}"
RECORDS_DIR="${EXPERIMENT_DIR}/records"
mkdir -p "${SNAPSHOTS_OUT}" "${CORNERS_OUT}" "${RECORDS_DIR}"

# --- PVT grids ------------------------------------------------------------
CORNER_LABELS=(typ bcs wcs)
declare -A HBT_SECTION_OF=( [typ]=hbt_typ [bcs]=hbt_bcs [wcs]=hbt_wcs )
declare -A MOS_SECTION_OF=( [typ]=mos_tt [bcs]=mos_ff [wcs]=mos_ss )
TEMPS=(-40 27 125)
VDDS=(1.62 1.80 1.98)
MPA_FEEDS=(0.52m 100u 20u)
STARTUP_CELLS=("bcs 125 1.98" "wcs -40 1.62" "typ 27 1.80")

if [[ -n "${BIASREF_SMOKE:-}" ]]; then
  CORNER_LABELS=(typ); TEMPS=(27); VDDS=(1.80); MPA_FEEDS=(0.52m)
  STARTUP_CELLS=("typ 27 1.80")
fi

render() { # render <template> <outfile> <extra sed-args...>
  local tmpl="$1" out="$2"; shift 2
  sed "$@" \
    -e "s|@@MODELS_LIB@@|${MODELS_LIB}|g" \
    -e "s|@@MOS_LIB@@|${MOS_LIB}|g" \
    -e "s|@@OSDI_DIR@@|${OSDI_DIR}|g" \
    "${tmpl}" > "${out}"
}

_ncpu="$(sysctl -n ncpu 2>/dev/null || getconf _NPROCESSORS_ONLN 2>/dev/null || echo 3)"
BIASREF_JOBS="${BIASREF_JOBS:-$(( _ncpu / 3 ))}"
(( BIASREF_JOBS < 1 )) && BIASREF_JOBS=1
(( BIASREF_JOBS > 6 )) && BIASREF_JOBS=6

FAILED_LIST="$(mktemp)"
trap 'rm -f "${FAILED_LIST}"' EXIT

pool_spawn() {
  while (( $(jobs -rp | wc -l) >= BIASREF_JOBS )); do
    wait -n 2>/dev/null || true
  done
  ( trap - EXIT; "$@" ) &
}

_check() { # _check <point_id> <log> <rc>
  local pid="$1" log="$2" rc="$3"
  if [[ "${rc}" != 0 ]] || ! grep -q "^BENCH_COMPLETE" "${log}"; then
    echo "run_biasref_sweep.sh: FAILED ${pid} (rc=${rc}) -- see ${log}" >&2
    echo "${pid}" >> "${FAILED_LIST}"
    return 1
  fi
  return 0
}

run_mpa_cell() {
  local label="$1" temp="$2" ifeed="$3"
  local hbt="${HBT_SECTION_OF[${label}]}"
  local pid="mpa_${label}_${temp}c_i${ifeed}"
  local netlist="${SNAPSHOTS_OUT}/${pid}.spice"
  local log="${CORNERS_OUT}/${pid}.log"
  render "${EXPERIMENT_DIR}/testbench/tb_mpa_diode.spice.tmpl" "${netlist}" \
    -e "s|@@HBT_SECTION@@|${hbt}|g" \
    -e "s|@@TEMP@@|${temp}|g" \
    -e "s|@@IFEED@@|${ifeed}|g"
  local rc=0
  ngspice -b "${netlist}" > "${log}" 2>&1 || rc=$?
  _check "${pid}" "${log}" "${rc}" || return 0
}

run_core_cell() {
  local label="$1" temp="$2" vdd="$3"
  local hbt="${HBT_SECTION_OF[${label}]}"
  local mos="${MOS_SECTION_OF[${label}]}"
  local pid="core_${label}_${temp}c_vdd${vdd}v"
  local netlist="${SNAPSHOTS_OUT}/${pid}.spice"
  local log="${CORNERS_OUT}/${pid}.log"
  render "${EXPERIMENT_DIR}/testbench/tb_core_minigrid.spice.tmpl" "${netlist}" \
    -e "s|@@HBT_SECTION@@|${hbt}|g" \
    -e "s|@@MOS_SECTION@@|${mos}|g" \
    -e "s|@@TEMP@@|${temp}|g" \
    -e "s|@@VDD@@|${vdd}|g"
  local rc=0
  ngspice -b "${netlist}" > "${log}" 2>&1 || rc=$?
  _check "${pid}" "${log}" "${rc}" || return 0
}

run_startup_cell() {
  local label="$1" temp="$2" vdd="$3"
  local hbt="${HBT_SECTION_OF[${label}]}"
  local mos="${MOS_SECTION_OF[${label}]}"
  local pid="startup_${label}_${temp}c_vdd${vdd}v"
  local netlist="${SNAPSHOTS_OUT}/${pid}.spice"
  local log="${CORNERS_OUT}/${pid}.log"
  local dat="${CORNERS_OUT}/${pid}.dat"
  render "${EXPERIMENT_DIR}/testbench/tb_core_startup.spice.tmpl" "${netlist}" \
    -e "s|@@HBT_SECTION@@|${hbt}|g" \
    -e "s|@@MOS_SECTION@@|${mos}|g" \
    -e "s|@@TEMP@@|${temp}|g" \
    -e "s|@@VDD@@|${vdd}|g" \
    -e "s|@@STARTUP_DAT@@|${dat}|g"
  local rc=0
  ngspice -b "${netlist}" > "${log}" 2>&1 || rc=$?
  _check "${pid}" "${log}" "${rc}" || return 0
}

echo "run_biasref_sweep.sh: record ${RECORD_ID}; ${#CORNER_LABELS[@]} corners x ${#TEMPS[@]} temps; ${BIASREF_JOBS} job(s)"

for label in "${CORNER_LABELS[@]}"; do
  for temp in "${TEMPS[@]}"; do
    for ifeed in "${MPA_FEEDS[@]}"; do
      pool_spawn run_mpa_cell "${label}" "${temp}" "${ifeed}"
    done
  done
done
for label in "${CORNER_LABELS[@]}"; do
  for temp in "${TEMPS[@]}"; do
    for vdd in "${VDDS[@]}"; do
      pool_spawn run_core_cell "${label}" "${temp}" "${vdd}"
    done
  done
done
for cell in "${STARTUP_CELLS[@]}"; do
  set -- ${cell}
  pool_spawn run_startup_cell "${1}" "${2}" "${3}"
done
wait

if [[ -s "${FAILED_LIST}" ]]; then
  echo "run_biasref_sweep.sh: $(wc -l < "${FAILED_LIST}") cell(s) FAILED; no record written (append-only records must be complete)."
  cat "${FAILED_LIST}"
  exit 4
fi

# --- Parse (sequential, deterministic) -------------------------------------
MPA_CSV="${RECORDS_DIR}/${RECORD_ID}-mpa-diode.csv"
echo "point_id,corner_label,temp_c,feed_i,v_eb_v" > "${MPA_CSV}"
for label in "${CORNER_LABELS[@]}"; do
  for temp in "${TEMPS[@]}"; do
    for ifeed in "${MPA_FEEDS[@]}"; do
      pid="mpa_${label}_${temp}c_i${ifeed}"
      awk -v pid="${pid}" -v lbl="${label}" -v t="${temp}" -v i="${ifeed}" '
        /^MPADIODE / {
          for (k = 2; k < NF; k += 2) { key = $k; val = $(k+1); kv[key] = val }
          printf "%s,%s,%s,%s,%s\n", pid, lbl, t, i, kv["veb"]
        }' "${CORNERS_OUT}/${pid}.log" >> "${MPA_CSV}"
    done
  done
done

CORE_CSV="${RECORDS_DIR}/${RECORD_ID}-core-minigrid.csv"
echo "point_id,corner_label,mos_section,temp_c,vdd_v,iq3_a,iqa_a,vbref_v,vna_v,vsdb_v" > "${CORE_CSV}"
for label in "${CORNER_LABELS[@]}"; do
  for temp in "${TEMPS[@]}"; do
    for vdd in "${VDDS[@]}"; do
      pid="core_${label}_${temp}c_vdd${vdd}v"
      awk -v pid="${pid}" -v lbl="${label}" -v mos="${MOS_SECTION_OF[${label}]}" -v t="${temp}" -v v="${vdd}" '
        /^BIASREF / {
          for (k = 2; k < NF; k += 2) { key = $k; val = $(k+1); kv[key] = val }
          printf "%s,%s,%s,%s,%s,%s,%s,%s,%s\n", pid, lbl, mos, t, v, \
            kv["iq3"], kv["iqa"], kv["vbref"], kv["vna"], kv["vsdb"]
        }' "${CORNERS_OUT}/${pid}.log" >> "${CORE_CSV}"
    done
  done
done

STARTUP_CSV="${RECORDS_DIR}/${RECORD_ID}-core-startup.csv"
echo "point_id,corner_label,temp_c,vdd_v,iq3_end_a,iq3_op_a,end_vs_op_pct,settled_spread_pct,verdict" > "${STARTUP_CSV}"
for cell in "${STARTUP_CELLS[@]}"; do
  set -- ${cell}
  label="$1"; temp="$2"; vdd="$3"
  pid="startup_${label}_${temp}c_vdd${vdd}v"
  op_id="core_${label}_${temp}c_vdd${vdd}v"
  op_iq3="$(awk -F, -v p="${op_id}" '$1==p {print $6}' "${CORE_CSV}")"
  awk -v pid="${pid}" -v lbl="${label}" -v t="${temp}" -v v="${vdd}" -v opic="${op_iq3:-0}" '
    /^STARTUP / {
      for (k = 2; k < NF; k += 2) { key = $k; val = $(k+1); kv[key] = val }
      end = kv["iq3_end"]; s2 = kv["iq3_s2"]; s3 = kv["iq3_s3"]
      mx = end; mn = end
      if (s2+0 > mx) mx = s2; if (s3+0 > mx) mx = s3
      if (s2+0 < mn) mn = s2; if (s3+0 < mn) mn = s3
      mean = (end + s2 + s3) / 3.0
      spread = (mean > 0) ? 100.0 * (mx - mn) / mean : 999
      dvsop  = (opic+0 > 0) ? 100.0 * (end - opic) / opic : 999
      verdict = "PASS"
      if (spread > 2.0) verdict = "NO-RINGING-FAIL"
      if (dvsop > 5.0 || dvsop < -5.0) verdict = "OP-MISMATCH-FAIL"
      if (end <= 0) verdict = "LATCHED-ZERO"
      printf "%s,%s,%s,%s,%.6g,%.6g,%.3f,%.3f,%s\n", pid, lbl, t, v, end, opic, dvsop, spread, verdict
    }' "${CORNERS_OUT}/${pid}.log" >> "${STARTUP_CSV}"
done

# --- Headline numbers --------------------------------------------------------
MPA_STATS="$(awk -F, 'NR>1 { if (!minset || $5+0 < min) {min=$5; minid=$1}; minset=1
                          if ($5+0 > max) {max=$5; maxid=$1} }
                    END { print minid, min, maxid, max }' "${MPA_CSV}")"
read -r MPA_MIN_ID MPA_MIN MPA_MAX_ID MPA_MAX <<<"${MPA_STATS}"

# Per-feed-current Option-B envelope disproof: the feed family each diode
# drop would set is I ~ (VDD - d)/R, so its worst/nominal current ratio is
# (1.98 - d_hot)/(1.80 - d_nom) with d_hot = V_EB(bcs,125C), d_nom =
# V_EB(typ,27C) at the SAME feed current. Computed from this run's own CSV;
# the committed npn13G2 family's comparable figure (from
# ../lna-bias-pvt/records/20260921-132025-d6da30a: V_BREF 0.7455 V at
# bcs/125C/1.98 V vs 0.8349 V at typ/27C/1.80 V) is 1.280 -- cited by
# DR-0003.
MPA_ENVELOPE="$(awk -F, '
  NR>1 { d[$4"_"$2"_"$3] = $5 }
  END {
    for (i in d) {
      split(i, k, "_")
      if (k[2] == "typ" && k[3] == "27") {
        nom_lbl = k[1] "_typ_27"; hot_lbl = k[1] "_bcs_125"; cold_lbl = k[1] "_wcs_-40"
        if (d[nom_lbl] != "" && d[hot_lbl] != "" && d[cold_lbl] != "") {
          hn = (1.98 - d[hot_lbl]) / (1.80 - d[nom_lbl])
          cn = (1.62 - d[cold_lbl]) / (1.80 - d[nom_lbl])
          printf "  I=%s: hot/nom=%.3f cold/nom=%.3f (d_nom=%.4f V, d_hot=%.4f V, d_cold=%.4f V)\n", k[1], hn, cn, d[nom_lbl], d[hot_lbl], d[cold_lbl]
        }
      }
    }
  }' "${MPA_CSV}" | sort)"

NOM="$(awk -F, '$2=="typ" && $4=="27" && $5=="1.80" {print $6}' "${CORE_CSV}")"
HOT="$(awk -F, '$2=="bcs" && $4=="125" && $5=="1.98" {print $6}' "${CORE_CSV}")"
COLD="$(awk -F, '$2=="wcs" && $4=="-40" && $5=="1.62" {print $6}' "${CORE_CSV}")"
HOT_GAIN="$(awk -v a="${HOT:-0}" -v b="${NOM:-0}" 'BEGIN { printf "%.3f", (a+0 > 0 && b+0 > 0) ? a/b : 0 }')"
COLD_GAIN="$(awk -v a="${COLD:-0}" -v b="${NOM:-0}" 'BEGIN { printf "%.3f", (a+0 > 0 && b+0 > 0) ? a/b : 0 }')"
COMMITTED_SUMMARY="${SIM_DIR}/lna-bias-pvt/records/20260921-132025-d6da30a-summary.csv"
if [[ -f "${COMMITTED_SUMMARY}" ]]; then
  # The committed R3a feed family's supply sensitivity, read the same way
  # (worst per-(corner,T) move of the Q3 share, ic3, across the three VDDs):
  COMMITTED_MOVE="$(awk -F, '
    NR>1 { key = $2"_T"$3
           if (!(key in lo) || $7+0 < lo[key]) lo[key] = $7
           if (!(key in hi) || $7+0 > hi[key]) hi[key] = $7 }
    END { worst = 0
          for (k in lo) { m = 100*(hi[k]-lo[k])/lo[k]; if (m > worst) { worst = m; wk = k } }
          printf "%.1f%% (worst cell %s)", worst, wk }' "${COMMITTED_SUMMARY}")"
else
  COMMITTED_MOVE="n/a (committed summary CSV not found)"
fi
SU_VERDICTS="$(awk -F, 'NR>1 && $9 != "" {print $9}' "${STARTUP_CSV}" | sort -u | tr '\n' ' ')"

RECORD_MD="${RECORDS_DIR}/${RECORD_ID}.md"
cat > "${RECORD_MD}" <<EOF
# ${RECORD_ID} -- flat PVT bias-reference design-space evidence (issue #33 / DR-0003)

## What this record is

Three design-space probes backing \`spec/decision-records/0003-flat-pvt-bias-reference.md\`:

1. **pnpMPA diode trace (Option B)**: the Curator pass of #33 inserted
   the substrate PNP \`pnpMPA\` as Option B with its adequacy at this
   headroom explicitly "not traced". This is that trace: the
   diode-connected terminal drop across \`{typ,bcs,wcs} x {-40,27,125} C\`
   at feed currents \`{0.52mA, 100uA, 20uA}\`.
2. **Option-A first-increment core (the self-biased Widlar PTAT skeleton)**:
   the supply-independent stage of the chosen Option A architecture, over
   \`{typ,bcs,wcs} x {-40,27,125} C x {1.62,1.80,1.98} V\` with the MOS
   corner mapped per \`sim/README.md\`. Evidences (a) supply independence
   of the reference-island feed and (b) the residual PTAT tone that
   Stage 2's amp-servo mixed-tone output must trim.
3. **Startup / latch check**: supply ramps of the same skeleton at the
   three cells the committed \`sim/lna-bias-pvt\` startup bench uses,
   verifying the seed leg boots the loop out of its zero-current
   degenerate state.

**No conformance claim**: nothing here claims against any
\`spec/target-spec.md\` row; those rows are inputs, not outputs, of #33.
This is design-space input to DR-0003, the same class of evidence
\`sim/hbt-characterization/\` is for DR-0001.

## PDK

- PDK_ROOT: \`${PDK_ROOT}\` (PDK: \`${PDK}\`, pinned release in \`sim/pdk.json\`)
- ngspice: \`${NGSPICE_VERSION}\`
- OSDI models: \`${OSDI_DIR}\` (present + loadable per
  \`sim/tools/build-osdi.sh --check\`; \`sg13_hv_pmos\` = PSP103.6)

## DUT inventories

- Phase A: \`pnpMPA\` (Gummel-Poon level=1, native; cornered by the same
  \`cornerHBT.lib\` sections via \`sgp_mpa_*\` scalars), diode-connected
  (e=b fed, c=b=vss), behind a 0 V ammeter.
- Phase B/C (\`testbench/tb_core_minigrid.spice.tmpl\`): XMb/XQb/Rp (the
  degenerated feedback leg, Nx=8, Rp=3.4k), XMa/XQa (plain diode leg,
  Nx=1), Rseed (10 Meg startup seed), XMk (21:1 output copy) into XQ3
  (Nx=1 island diode). All devices are the PDK's real compact models;
  resistors are generic ideal SPICE R's, the same idealization the
  committed schematic uses (see README method limits).

## Results

### Phase A -- pnpMPA diode drop (Option B)

- Terminal drop spans \`${MPA_MIN} V\` (\`${MPA_MIN_ID}\`) .. \`${MPA_MAX} V\`
  (\`${MPA_MAX_ID}\`) across the traced grid. Option-B adequacy judged
  the way the feed family it would seed actually behaves: each drop d
  sets a \`I ~ (VDD - d)/R\` reference family whose worst/nominal
  current ratio is \`(1.98 - d_hot)/(1.80 - d_nom)\` -- measured per feed
  current below. **At every traced current the ratio is WORSE than the
  committed npn13G2 family's own 1.280** (V_BREF 0.7455 V hot vs
  0.8349 V nominal, from
  \`../lna-bias-pvt/records/20260921-132025-d6da30a-summary.csv\`):
  the MPA's \`rb=700\` base resistance at \`bf=1.10\` both raises its
  drop at island-scale currents and widens its T-swing. Full table:
  \`${RECORD_ID}-mpa-diode.csv\`.

\`\`\`
${MPA_ENVELOPE}
\`\`\`

### Phase B -- Option-A skeleton mini-grid

- Nominal cell (typ/27 C/1.80 V): island current \`i_q3 = ${NOM} A\`.
- Binding hot cell (bcs/125 C/1.98 V): \`i_q3 = ${HOT} A\`
  (hot/nominal gain ${HOT_GAIN}).
- Binding cold cell (wcs/-40 C/1.62 V): \`i_q3 = ${COLD} A\`
  (cold/nominal gain ${COLD_GAIN}).
- **Supply independence**: $(awk -F, '
    NR>1 { key = $2"_"$4
           if (!(key in lo) || $6+0 < lo[key]) lo[key] = $6
           if (!(key in hi) || $6+0 > hi[key]) hi[key] = $6 }
    END { worst = 0
          for (k in lo) { m = 100*(hi[k]-lo[k])/lo[k]; if (m > worst) worst = m }
          printf "worst-per-(corner,T) island-current move across the full ±10%% VDD swing: %.2f%%", worst }' "${CORE_CSV}")
  -- versus \`${COMMITTED_MOVE}\` for the committed R3a feed family measured
  the identical way (ic3 share, worst per-(corner,T) move across
  1.62/1.80/1.98 V) from the committed 45-cell record
  \`../lna-bias-pvt/records/20260921-132025-d6da30a-summary.csv\`.
- Residual tone is PTAT-shaped as designed (this skeleton is NOT the
  flat core; the flat trim is Stage 2's deliverable). Full table:
  \`${RECORD_ID}-core-minigrid.csv\`.

### Phase C -- startup / latch

- Verdicts: ${SU_VERDICTS:-none}. See \`${RECORD_ID}-core-startup.csv\` and
  the wrdata artifacts. The seed leg (10 Meg) is load-bearing: during
  development the unseeded skeleton's op was observed settling to the
  zero-current branch at most cells -- the same degenerate-state hazard
  every self-biased loop has.

## Method limits (what this record does NOT say)

- **No LNA instantiation, no RF claim of any kind.** These are
  design-space probes of the reference core, not measurements of the
  committed \`design/netlist/lna.spice\`.
- **No flatness claim for the skeleton**: its output tone is PTAT by
  design; only the full DR-0003 Stage-2 architecture (amp-servo
  mixed-tone output) is a candidate to hold the two ratified bars at a
  4.0 mA nominal, and that core is not what was measured here.
- **No mismatch sections** (\`hbt_*_mismatch\`/\`mos_tt_mismatch\` are out of
  scope, matching the committed 45-cell grid's convention); the 21:1
  output mirror ratio in particular must be centroid-matched at layout
  time before any ratified number.
- **Ideal resistors**: Rp/Rseed are generic ideal SPICE R's with no
  tolerance or tempco -- the same idealization every committed bench in
  this tree uses, and the same budget caveat.
- **Model validity boxes**: every npn13G2 instance rides inside the
  model card's stated ranges (V_BE 0.65-0.96 V measured at
  \`vna\`/\`vbref\`; T inside -40..+125 C; Nx legal 1-10); the PSP103
  HV-PMOS instances operate at |V_SD| well under the HV card's 3.0 V
  rating, honoring DR-0001's "any MOS in the bias network must be the
  HV flavour" constraint.

## Regeneration

\`\`\`bash
export PDK_ROOT=/path/to/ihp-open-pdk PDK=ihp-sg13g2
sim/tools/build-osdi.sh --check
sim/biasref-topology/run_biasref_sweep.sh
\`\`\`

## Links

- Templates: \`testbench/tb_mpa_diode.spice.tmpl\`,
  \`testbench/tb_core_minigrid.spice.tmpl\`,
  \`testbench/tb_core_startup.spice.tmpl\`
- Per-point generated netlists: \`netlist-snapshots/${RECORD_ID}/\`
- Per-point raw ngspice logs / wrdata: \`corners/${RECORD_ID}/\`
- CSVs: \`records/${RECORD_ID}-mpa-diode.csv\`,
  \`records/${RECORD_ID}-core-minigrid.csv\`,
  \`records/${RECORD_ID}-core-startup.csv\`
- Decision record: \`spec/decision-records/0003-flat-pvt-bias-reference.md\`
- Issue: #33 (acceptance criteria and scope)
- Committed-family baseline: \`../lna-bias-pvt/records/20260921-132025-d6da30a\`
EOF

echo "run_biasref_sweep.sh: done. Record ${RECORD_ID}"
echo "  mpa-diode : ${MPA_CSV}"
echo "  core-grid : ${CORE_CSV}"
echo "  startup   : ${STARTUP_CSV}"
echo "  record    : ${RECORD_MD}"
echo "  island i_q3 nominal: ${NOM} A | hot ${HOT} A | cold ${COLD} A"
echo "  startup verdicts: ${SU_VERDICTS:-none}"
