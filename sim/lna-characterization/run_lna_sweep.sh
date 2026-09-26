#!/usr/bin/env bash
# Cold-start invocation:
#
#   export PDK_ROOT=/path/to/ihp-open-pdk   # parent dir containing ihp-sg13g2/
#   export PDK=ihp-sg13g2
#   sim/lna-characterization/run_lna_sweep.sh
#
# (PDK_ROOT/PDK may also be left unset if the PDK is installed under one of
# the usual prefixes sim/env.sh checks.) Requires ngspice and python3 on
# PATH, and -- since the DR-0003 Stage-2 core swap (issue #33 / PR #40,
# commit e25df3b) -- the OSDI device models, because the committed DUT now
# instantiates sg13_hv_pmos / sg13_hv_nmos (PSP103.6 via OSDI). Build or
# check them with sim/tools/build-osdi.sh (see sim/README.md "OSDI device
# models"); npn13G2 itself stays a native ngspice VBIC model needing no
# compile step -- see sim/pdk.json. Does not require xschem or klt. Full
# methodology, bench definitions, corner scope and stated method limits are
# in sim/lna-characterization/README.md -- read that first if a result here
# looks surprising.
#
# Runs the CIRCUIT-level characterization of design/lna.sch (via its
# committed netlist design/netlist/lna.spice) that issue #18 asks for:
#
#   Phase 1 (sp/NF/stability): per PVT cell, ngspice `sp` S-parameters
#     (S11/S21/S12/S22) at 50 Ohm ports over the 2400-2483.5 MHz draft
#     band, ngspice's own two-port NF/NFmin, a `.noise`-based NF at two
#     reference temperatures, a transducer-gain cross-check, and a
#     broadband (10 MHz .. 30 GHz) k-factor / mu-factor / |Delta| stability
#     sweep.
#   Phase 2 (IIP3): two-tone coherent transient + FFT, per PVT cell at two
#     drive levels, plus a 5-point drive-level sweep at the nominal cell to
#     demonstrate the 3:1 IM3 slope the extrapolation assumes.
#
# Writes append-only evidence under corners/<record-id>/,
# netlist-snapshots/<record-id>/ and records/<record-id>.{csv,md} -- see
# sim/README.md for the convention this follows
# (sim/hbt-characterization/run_hbt_sweep.sh is the structural precedent
# for the render-deck -> ngspice -b -> parse -> CSV+record shape).
#
# Environment knobs (all optional):
#   LNA_SWEEP_JOBS=<n>   how many ngspice processes to run concurrently
#                        (default: min(6, ncpu/3), floor 1). Every point
#                        writes only to its OWN netlist/log/wrdata files, so
#                        concurrency changes nothing about the numbers -- it
#                        only changes wall-clock time. Set 1 for a strictly
#                        serial run.
#   LNA_SWEEP_SMOKE=1    single nominal PVT cell, for plumbing checks.
set -euo pipefail

# `declare -A` (bash 4.0) and the `wait -n` job pool below (bash 4.3) are
# both used; fail loudly rather than mis-executing under bash 3.2 (still
# /bin/bash on macOS -- `#!/usr/bin/env bash` normally picks up a newer one).
if (( BASH_VERSINFO[0] < 4 || (BASH_VERSINFO[0] == 4 && BASH_VERSINFO[1] < 3) )); then
  echo "run_lna_sweep.sh: needs bash >= 4.3 (found ${BASH_VERSION})." >&2
  exit 3
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SIM_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
REPO_ROOT="$(cd "${SIM_DIR}/.." && pwd)"

# shellcheck source=/dev/null
source "${SIM_DIR}/env.sh"

if [[ -z "${PDK_ROOT:-}" || ! -d "${PDK_ROOT}/${PDK}/libs.tech/ngspice" ]]; then
  echo "run_lna_sweep.sh: no resolvable ${PDK:-ihp-sg13g2} install -- see sim/env.sh output above." >&2
  exit 3
fi

command -v ngspice >/dev/null 2>&1 || { echo "run_lna_sweep.sh: ngspice not on PATH." >&2; exit 3; }
command -v python3 >/dev/null 2>&1 || { echo "run_lna_sweep.sh: python3 not on PATH." >&2; exit 3; }
NGSPICE_VERSION="$(ngspice -v 2>&1 | sed -n '2p')"

MODELS_LIB="${PDK_ROOT}/${PDK}/libs.tech/ngspice/models/cornerHBT.lib"
MOS_LIB="${PDK_ROOT}/${PDK}/libs.tech/ngspice/models/cornerMOShv.lib"
OSDI_DIR="${PDK_ROOT}/${PDK}/libs.tech/ngspice/osdi"
if [[ ! -f "${MODELS_LIB}" ]]; then
  echo "run_lna_sweep.sh: cornerHBT.lib not found at ${MODELS_LIB}" >&2
  exit 3
fi
# DR-0003 Stage-2 (issue #33 / PR #40): the committed DUT instantiates
# sg13_hv_pmos / sg13_hv_nmos, so this bench now needs cornerMOShv.lib and
# the OSDI models too -- the same preamble sim/lna-bias-pvt's runner
# already carries.
for f in "${MOS_LIB}" "${OSDI_DIR}/psp103.osdi" "${OSDI_DIR}/psp103_nqs.osdi" "${OSDI_DIR}/mosvar.osdi"; do
  if [[ ! -f "${f}" ]]; then
    echo "run_lna_sweep.sh: ${f} not found -- if the .osdi models are missing, run sim/tools/build-osdi.sh (see sim/README.md 'OSDI device models'); the DR-0003 Stage-2 DUT will not simulate without them." >&2
    exit 3
  fi
done

DESIGN_NETLIST="${REPO_ROOT}/design/netlist/lna.spice"
if [[ ! -f "${DESIGN_NETLIST}" ]]; then
  echo "run_lna_sweep.sh: design netlist not found at ${DESIGN_NETLIST}" >&2
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
# design/netlist/lna.spice is xschem's own flat netlist of design/lna.sch:
# it carries its top-level subcircuit markers commented out ("**.subckt
# lna vdd vss rfin rfout" / "**.ends") because the schematic was netlisted
# directly rather than instantiated through lna.sym. Uncomment exactly
# those two markers and drop the trailing ".end" so the identical device
# list can be instantiated twice inside one testbench deck. NOTHING ELSE is
# changed -- every device line is verbatim, and the sha256 above pins which
# revision these numbers belong to.
DUT_SUBCKT="$(mktemp)"
trap 'rm -f "${DUT_SUBCKT}"' EXIT
sed -e 's|^\*\*\.subckt|.subckt|' \
    -e 's|^\*\*\.ends|.ends|' \
    -e '/^\.end$/d' \
    "${DESIGN_NETLIST}" > "${DUT_SUBCKT}"
grep -q '^\.subckt lna ' "${DUT_SUBCKT}" || {
  echo "run_lna_sweep.sh: could not recover a '.subckt lna ...' line from ${DESIGN_NETLIST}" >&2
  exit 3
}

# --- PVT grid -----------------------------------------------------------
# Corner labels mirror the five-label fleet convention, mapped onto
# cornerHBT.lib's three REAL sections -- see sim/README.md "Corner label
# convention": sf/fs fall back to hbt_typ because no skewed HBT section
# exists in this PDK. Read `wcs` as this repo's `ss`-equivalent wherever
# spec/target-spec.md names an `ss`-corner binding condition.
CORNER_LABELS=(typ bcs wcs sf fs)
declare -A HBT_SECTION_OF=( [typ]=hbt_typ [bcs]=hbt_bcs [wcs]=hbt_wcs [sf]=hbt_typ [fs]=hbt_typ )
# DR-0003 Stage-2: the DUT also instantiates sg13_hv_pmos/sg13_hv_nmos, so
# every cell maps onto a cornerMOShv.lib section as well. cornerMOShv ships
# all five real MOS sections, so the five labels map straight through
# (typ->mos_tt, bcs->mos_ff, wcs->mos_ss, sf->mos_sf, fs->mos_fs) -- only
# the HBT side duplicates. Identical mapping to
# sim/lna-bias-pvt/run_biasop_sweep.sh, so the two benches describe the same
# 45 cells.
declare -A MOS_SECTION_OF=( [typ]=mos_tt [bcs]=mos_ff [wcs]=mos_ss [sf]=mos_sf [fs]=mos_fs )
TEMPS=(-40 27 125)
# DR-1's proposed nominal rail is 1.8 V; spec/target-spec.md's "Verification
# corners" asks for +/-10% around whatever the Supply row eventually ratifies.
VDDS=(1.62 1.80 1.98)

# --- Band / analysis constants -----------------------------------------
F_BAND_LO="2.4e9"
F_BAND_MID="2.44175e9"
F_BAND_HI="2.4835e9"
N_INBAND=11
# Stability: CLAUDE.md requires out-of-band coverage; target-spec.md's
# stability row asks for >= 3x the upper band edge (7.4505 GHz). This sweep
# runs 10 MHz .. 30 GHz, i.e. 12x the upper band edge and ~240x below the
# lower edge, at 40 points/decade.
F_STAB_LO="1e7"
F_STAB_HI="3e10"
N_STAB_DEC=40

# --- Two-tone / FFT constants (coherent by construction) ----------------
# tstep = 4 ps, N = 65536 -> df = 1/(N*tstep) = 3.814697265625 MHz.
# Tones and all measured products are placed exactly on bin centres, so a
# rectangular window leaks nothing and ngspice applies no zero padding.
TSTEP="4e-12"
NFFT=65536
TSTART="1e-6"
B1=640; B2=642; BIM3L=638; BIM3H=644; BIM5L=636; BIM5H=646
read -r DF F1 F2 FIM3L FIM3H FSPACE TWINDOW TSTOP <<EOF
$(python3 - "${TSTEP}" "${NFFT}" "${TSTART}" "${B1}" "${B2}" "${BIM3L}" "${BIM3H}" <<'PYEOF'
import sys
tstep = float(sys.argv[1]); n = int(sys.argv[2]); tstart = float(sys.argv[3])
b1, b2, bl, bh = (int(x) for x in sys.argv[4:8])
df = 1.0/(n*tstep)
twin = (n-1)*tstep
print(repr(df), repr(b1*df), repr(b2*df), repr(bl*df), repr(bh*df),
      repr((b2-b1)*df), repr(twin), repr(tstart+twin))
PYEOF
)
EOF

# Per-tone open-circuit source amplitudes (V peak). The two-level pair is
# run at every PVT cell (two levels so the parser can check the 3:1 IM3
# slope per cell, not just at nominal); the extra levels run at the nominal
# cell only, to exhibit the full slope over a 24 dB drive range.
AMPS_GRID=(1e-3 2e-3)
AMPS_NOMINAL_ONLY=(5e-4 4e-3 8e-3)
NOMINAL_CORNER="typ"
NOMINAL_TEMP="27"
NOMINAL_VDD="1.80"

# LNA_SWEEP_SMOKE=1 runs the identical flow over a single nominal PVT cell
# (two drive levels), for checking the end-to-end plumbing -- template
# rendering, ngspice invocation, wrdata layout, parser, record -- in ~20 s
# instead of the full campaign. A smoke record is still a real, complete
# record; it is simply not a PVT campaign, so do not commit one as evidence.
if [[ -n "${LNA_SWEEP_SMOKE:-}" ]]; then
  CORNER_LABELS=(typ)
  TEMPS=(27)
  VDDS=(1.80)
  AMPS_NOMINAL_ONLY=()
  echo "run_lna_sweep.sh: LNA_SWEEP_SMOKE set -- single-cell smoke run, NOT a PVT campaign"
fi

# --- Concurrency -------------------------------------------------------
# Each scheduled point is an independent `ngspice -b` on its own generated
# deck, writing only files named after that point, so the pool below is a
# pure wall-clock optimization: the committed numbers are bit-identical to a
# serial run (LNA_SWEEP_JOBS=1).
if [[ -z "${LNA_SWEEP_JOBS:-}" ]]; then
  _ncpu="$( (getconf _NPROCESSORS_ONLN 2>/dev/null || sysctl -n hw.ncpu 2>/dev/null || echo 4) | head -1 )"
  LNA_SWEEP_JOBS=$(( _ncpu / 3 ))
  (( LNA_SWEEP_JOBS < 1 )) && LNA_SWEEP_JOBS=1
  (( LNA_SWEEP_JOBS > 6 )) && LNA_SWEEP_JOBS=6
  unset _ncpu
fi

total_runs=0
# Failures are recorded in a file, not a shell array: each point runs in a
# background subshell, whose variable writes cannot propagate to the parent.
FAILED_LIST="$(mktemp)"
trap 'rm -f "${DUT_SUBCKT}" "${FAILED_LIST}"' EXIT

pool_spawn() {
  # pool_spawn <fn> <args...> -- run in the background, at most
  # LNA_SWEEP_JOBS at a time. `trap - EXIT` in the child keeps the child's
  # exit from deleting the parent's shared temp files.
  while (( $(jobs -rp | wc -l) >= LNA_SWEEP_JOBS )); do
    wait -n 2>/dev/null || true
  done
  total_runs=$((total_runs + 1))
  ( trap - EXIT; "$@" ) &
}

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

check_log() {
  # check_log <point_id> <log> <rc>
  local point_id="$1" log="$2" rc="$3"
  if [[ "${rc}" -ne 0 ]] \
    || grep -qiE "Unable to find definition of model|couldn't be loaded|Unknown model type|fatal error|doAnalyses: TRAN: Timestep too small" "${log}" \
    || ! grep -q "^BENCH_COMPLETE" "${log}"; then
    echo "run_lna_sweep.sh: FAILED ${point_id} (rc=${rc}) -- see ${log}" >&2
    echo "${point_id}" >> "${FAILED_LIST}"
    return 1
  fi
  return 0
}

run_sparam_cell() {
  local corner_label="$1" hbt_section="$2" temp="$3" vdd="$4"
  local mos_section="${MOS_SECTION_OF[${corner_label}]}"
  local point_id="sp_${corner_label}_${temp}c_vdd${vdd}v"
  local netlist="${SNAPSHOTS_OUT}/${point_id}.spice"
  local log="${CORNERS_OUT}/${point_id}.log"
  local inband_dat="${CORNERS_OUT}/${point_id}.inband.dat"
  local stab_dat="${CORNERS_OUT}/${point_id}.stability.dat"

  render "${EXPERIMENT_DIR}/testbench/tb_lna_sparam.spice.tmpl" "${netlist}" \
    -e "s|@@HBT_SECTION@@|${hbt_section}|g" \
    -e "s|@@MOS_SECTION@@|${mos_section}|g" \
    -e "s|@@TEMP@@|${temp}|g" \
    -e "s|@@VDD@@|${vdd}|g" \
    -e "s|@@N_INBAND@@|${N_INBAND}|g" \
    -e "s|@@F_BAND_LO@@|${F_BAND_LO}|g" \
    -e "s|@@F_BAND_MID@@|${F_BAND_MID}|g" \
    -e "s|@@F_BAND_HI@@|${F_BAND_HI}|g" \
    -e "s|@@F_STAB_LO@@|${F_STAB_LO}|g" \
    -e "s|@@F_STAB_HI@@|${F_STAB_HI}|g" \
    -e "s|@@N_STAB_DEC@@|${N_STAB_DEC}|g" \
    -e "s|@@INBAND_DAT@@|${inband_dat}|g" \
    -e "s|@@STAB_DAT@@|${stab_dat}|g"

  local rc=0
  ngspice -b "${netlist}" > "${log}" 2>&1 || rc=$?
  check_log "${point_id}" "${log}" "${rc}" || return 0
}

run_iip3_point() {
  local corner_label="$1" hbt_section="$2" temp="$3" vdd="$4" amp="$5" amp_label="$6"
  local mos_section="${MOS_SECTION_OF[${corner_label}]}"
  local point_id="iip3_${corner_label}_${temp}c_vdd${vdd}v_${amp_label}"
  local netlist="${SNAPSHOTS_OUT}/${point_id}.spice"
  local log="${CORNERS_OUT}/${point_id}.log"

  render "${EXPERIMENT_DIR}/testbench/tb_lna_iip3.spice.tmpl" "${netlist}" \
    -e "s|@@HBT_SECTION@@|${hbt_section}|g" \
    -e "s|@@MOS_SECTION@@|${mos_section}|g" \
    -e "s|@@TEMP@@|${temp}|g" \
    -e "s|@@VDD@@|${vdd}|g" \
    -e "s|@@AMP@@|${amp}|g" \
    -e "s|@@TSTEP@@|${TSTEP}|g" \
    -e "s|@@TSTART@@|${TSTART}|g" \
    -e "s|@@TSTOP@@|${TSTOP}|g" \
    -e "s|@@TWINDOW@@|${TWINDOW}|g" \
    -e "s|@@NFFT@@|${NFFT}|g" \
    -e "s|@@DF@@|${DF}|g" \
    -e "s|@@F1@@|${F1}|g" \
    -e "s|@@F2@@|${F2}|g" \
    -e "s|@@FSPACE@@|${FSPACE}|g" \
    -e "s|@@FIM3L@@|${FIM3L}|g" \
    -e "s|@@FIM3H@@|${FIM3H}|g" \
    -e "s|@@B1@@|${B1}|g" \
    -e "s|@@B2@@|${B2}|g" \
    -e "s|@@BIM3L@@|${BIM3L}|g" \
    -e "s|@@BIM3H@@|${BIM3H}|g" \
    -e "s|@@BIM5L@@|${BIM5L}|g" \
    -e "s|@@BIM5H@@|${BIM5H}|g"

  local rc=0
  ngspice -b "${netlist}" > "${log}" 2>&1 || rc=$?
  check_log "${point_id}" "${log}" "${rc}" || return 0
}

amp_label_of() {
  python3 -c "
import sys
a = float(sys.argv[1]) * 1e3
s = ('%g' % a).replace('.', 'p')
print('a%smv' % s)
" "$1"
}

echo "run_lna_sweep.sh: record ${RECORD_ID} (${LNA_SWEEP_JOBS} concurrent ngspice job(s))"
echo "run_lna_sweep.sh: phase 1/2 -- S-parameters, NF, stability ($(( ${#CORNER_LABELS[@]} * ${#TEMPS[@]} * ${#VDDS[@]} )) cells)"
for corner_label in "${CORNER_LABELS[@]}"; do
  hbt_section="${HBT_SECTION_OF[${corner_label}]}"
  for temp in "${TEMPS[@]}"; do
    for vdd in "${VDDS[@]}"; do
      pool_spawn run_sparam_cell "${corner_label}" "${hbt_section}" "${temp}" "${vdd}"
    done
  done
done
wait

echo "run_lna_sweep.sh: phase 2/2 -- two-tone IIP3"
for corner_label in "${CORNER_LABELS[@]}"; do
  hbt_section="${HBT_SECTION_OF[${corner_label}]}"
  for temp in "${TEMPS[@]}"; do
    for vdd in "${VDDS[@]}"; do
      for amp in "${AMPS_GRID[@]}"; do
        pool_spawn run_iip3_point "${corner_label}" "${hbt_section}" "${temp}" "${vdd}" \
          "${amp}" "$(amp_label_of "${amp}")"
      done
    done
  done
done
for amp in "${AMPS_NOMINAL_ONLY[@]}"; do
  pool_spawn run_iip3_point "${NOMINAL_CORNER}" "${HBT_SECTION_OF[${NOMINAL_CORNER}]}" \
    "${NOMINAL_TEMP}" "${NOMINAL_VDD}" "${amp}" "$(amp_label_of "${amp}")"
done
wait

failed_points=()
if [[ -s "${FAILED_LIST}" ]]; then
  while IFS= read -r _fp; do
    [[ -n "${_fp}" ]] && failed_points+=("${_fp}")
  done < <(sort "${FAILED_LIST}")
fi

# --- Parse every raw artefact into the record CSVs ----------------------
SPARAM_CSV="${RECORDS_DIR}/${RECORD_ID}-sparam.csv"
IIP3_CSV="${RECORDS_DIR}/${RECORD_ID}-iip3.csv"
SUMMARY_CSV="${RECORDS_DIR}/${RECORD_ID}-summary.csv"

python3 "${EXPERIMENT_DIR}/parse_lna_sweep.py" \
  --corners-dir "${CORNERS_OUT}" \
  --sparam-csv "${SPARAM_CSV}" \
  --iip3-csv "${IIP3_CSV}" \
  --summary-csv "${SUMMARY_CSV}" \
  --band-lo "${F_BAND_LO}" --band-hi "${F_BAND_HI}" \
  --df "${DF}" --f1 "${F1}" --f2 "${F2}"

# --- Human-readable append-only record ---------------------------------
MD_OUT="${RECORDS_DIR}/${RECORD_ID}.md"
HEADLINES="$(python3 "${EXPERIMENT_DIR}/parse_lna_sweep.py" --headlines \
  --summary-csv "${SUMMARY_CSV}" --iip3-csv "${IIP3_CSV}")"

{
  echo "# Record ${RECORD_ID}"
  echo
  echo "- **Experiment**: lna-characterization (issue #18)"
  echo "- **Claim**: circuit-level 50 Ohm-port S-parameters (S11/S21/S12/S22),"
  echo "  noise figure, k-factor/mu-factor stability and two-tone IIP3 of"
  echo "  \`design/lna.sch\` (via its committed netlist), across a"
  echo "  process x temperature x supply PVT grid. **Not** a conformance"
  echo "  claim against any \`spec/target-spec.md\` row. That table's"
  echo "  RATIFIED rows (decision record 0002) are a bar, not a"
  echo "  hypothesis -- but their *verification* is gated on the #26 bias"
  echo "  and #27 matching re-runs, so this record is evidence about the"
  echo "  as-committed DUT, not a pass/fail verdict against the spec."
  echo "- **DUT**: \`design/netlist/lna.spice\` (sha256"
  echo "  \`${DESIGN_NETLIST_SHA}\`), inlined verbatim into every generated"
  echo "  deck as a \`.subckt lna vdd vss rfin rfout\`."
  echo "- **Bench definitions**: see \`README.md\` -- short summary: 50 Ohm"
  echo "  reference impedance at both ports (\`sp\` analysis port sources);"
  echo "  NF from an input-referred \`.noise\` measurement with NOISELESS"
  echo "  Rs/RL and the source noise re-introduced analytically at"
  echo "  T0 = 290 K (IEEE) and at 300.15 K, cross-checked against"
  echo "  ngspice's own two-port \`sp\` NF; IIP3 from a coherent two-tone"
  echo "  transient + rectangular-window FFT, no zero padding."
  echo "- **PDK**: \`${PDK}\` at \`${PDK_ROOT}\` -- pinned release: see"
  echo "  \`sim/pdk.json\` (IHP-Open-PDK v0.3.0)."
  echo "- **Device model sections**: HBT from \`cornerHBT.lib\`"
  echo "  (\`hbt_typ\`/\`hbt_bcs\`/\`hbt_wcs\`; \`sf\`/\`fs\` fall back to"
  echo "  \`hbt_typ\` -- no skewed HBT section exists in this PDK), MOS from"
  echo "  \`cornerMOShv.lib\` mapped straight through by the five labels"
  echo "  (\`mos_tt\`/\`mos_ff\`/\`mos_ss\`/\`mos_sf\`/\`mos_fs\`), with the"
  echo "  PSP103.6 OSDI models preloaded (\`pre_osdi\`). Identical mapping to"
  echo "  \`sim/lna-bias-pvt/run_biasop_sweep.sh\`, so both benches describe"
  echo "  the same 45 cells."
  echo "- **ngspice**: \`${NGSPICE_VERSION}\`, with"
  echo "  \`.options gmin=1e-10\` in every deck. That is 100x ngspice-46's"
  echo "  own 1e-12 default and is NOT what the two pre-DR-0003 records ran"
  echo "  under; the DR-0003 flat-reference core does not converge at the"
  echo "  coldest/lowest-rail cells without it. Measured cost of the"
  echo "  override at the nominal cell: every recorded quantity moves in the"
  echo "  7th significant figure or beyond (largest relative move anywhere"
  echo "  4.5e-5, on the ill-conditioned Rollett k). See \`README.md\`"
  echo "  section \"gmin and the DR-0003 core\"."
  echo "- **Ideal-passive assumption (this record's largest stated limit)**:"
  echo "  \`Le\`/\`Lc\` are ideal infinite-Q SPICE \`L\` primitives and the"
  echo "  capacitors/resistors are ideal \`C\`/\`R\`, because SG13G2's open PDK"
  echo "  ships no simulatable inductor model (issue #5, upstream"
  echo "  \`2AMLogic/klayout-tools#1519\`). Only the HBTs and the DR-0003"
  echo "  core's MOS devices are real PDK models. This makes every"
  echo "  gain/NF/S11/S22 number here the MOST OPTIMISTIC case, and makes"
  echo "  the stability numbers the LEAST-DAMPED case. No number in this"
  echo "  record is verified against a physical passive model, let alone"
  echo "  silicon. Full list: \`README.md\` section \"Model limitations\"."
  CORNER_LABELS_STR="$(IFS=,; echo "${CORNER_LABELS[*]}")"
  TEMPS_STR="$(IFS=,; echo "${TEMPS[*]}")"
  VDDS_STR="$(IFS=,; echo "${VDDS[*]}")"
  echo "- **PVT grid**: corner_label {${CORNER_LABELS_STR}} x temp"
  echo "  {${TEMPS_STR}} C x VDD {${VDDS_STR}} V ="
  echo "  $(( ${#CORNER_LABELS[@]} * ${#TEMPS[@]} * ${#VDDS[@]} )) cells, each run for both phases."
  echo "- **In-band sweep**: ${N_INBAND} points, ${F_BAND_LO} .. ${F_BAND_HI} Hz."
  echo "- **Stability sweep**: ${F_STAB_LO} .. ${F_STAB_HI} Hz at ${N_STAB_DEC} points/decade"
  echo "  (>= 3x the upper band edge, as the stability spec row requires)."
  echo "- **Two-tone**: f1=${F1} Hz, f2=${F2} Hz, spacing=${FSPACE} Hz;"
  echo "  FFT N=${NFFT} samples at ${TSTEP} s/sample (window ${TWINDOW} s,"
  echo "  bin ${DF} Hz), rectangular window, no zero padding,"
  echo "  ${TSTART} s of transient discarded before the window."
  echo "- **Result**: ${total_runs} ngspice invocations (run ${LNA_SWEEP_JOBS} at a"
  echo "  time; each writes only its own files, so concurrency affects wall-clock"
  echo "  time only, not any number below)."
  if [[ ${#failed_points[@]} -gt 0 ]]; then
    echo "- **Failed cells**: ${failed_points[*]}"
  else
    echo "- **Failed cells**: none."
  fi
  echo "${HEADLINES}"
  echo "- **Links**:"
  echo "  - Templates: \`testbench/tb_lna_sparam.spice.tmpl\`,"
  echo "    \`testbench/tb_lna_iip3.spice.tmpl\`"
  echo "  - Parser: \`parse_lna_sweep.py\`"
  echo "  - Per-point generated netlists: \`netlist-snapshots/${RECORD_ID}/\`"
  echo "  - Per-point raw ngspice logs and wrdata tables:"
  echo "    \`corners/${RECORD_ID}/\`"
  echo "  - Per-frequency in-band S-parameter/NF/stability CSV:"
  echo "    \`records/${RECORD_ID}-sparam.csv\`"
  echo "  - Per-point IIP3 CSV: \`records/${RECORD_ID}-iip3.csv\`"
  echo "  - Per-cell summary CSV: \`records/${RECORD_ID}-summary.csv\`"
  echo "- **Timestamp / author**: $(date -u +%Y-%m-%dT%H:%M:%SZ), Loom Builder"
  echo "  (agent), issue #18."
} > "${MD_OUT}"

echo "run_lna_sweep.sh: wrote ${MD_OUT}"
echo "run_lna_sweep.sh: wrote ${SPARAM_CSV}, ${IIP3_CSV}, ${SUMMARY_CSV}"
echo "${HEADLINES}"

if [[ ${#failed_points[@]} -gt 0 ]]; then
  echo "run_lna_sweep.sh: ${#failed_points[@]} failed point(s): ${failed_points[*]}" >&2
  exit 1
fi
exit 0
