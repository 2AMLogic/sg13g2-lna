#!/usr/bin/env bash
# Cold-start invocation:
#
#   export PDK_ROOT=/path/to/ihp-open-pdk   # parent dir containing ihp-sg13g2/
#   export PDK=ihp-sg13g2
#   sim/lna-core-envelope/run_core_envelope.sh
#
# (PDK_ROOT/PDK may also be left unset if the PDK is installed under one of
# the usual prefixes sim/env.sh checks.) Requires ngspice and python3 on
# PATH plus the OSDI device models (sim/tools/build-osdi.sh) -- the DR-0003
# bias core every variant here carries instantiates sg13_hv_pmos /
# sg13_hv_nmos. Does not require xschem or klt. Full methodology, bench
# definitions, variant recipes and stated method limits are in
# sim/lna-core-envelope/README.md -- read that first if a result here looks
# surprising.
#
# WHAT THIS EXPERIMENT IS (issue #52). The circuit-level characterization
# campaign (sim/lna-characterization/, record 20260926-122301-088c734)
# measures the committed DUT. It does not answer the question issue #52
# asks: *what (gain, NF, P_dc) envelope is achievable on npn13G2 at all*,
# and does an emitter-geometry / device-count / two-stage change move it?
# This experiment answers that by re-running the SAME sp/NF/stability bench
# over a set of DUT VARIANTS across the SAME 45-cell PVT grid.
#
#   Phase A -- single-stage emitter-area axis, two families:
#     A1 "fix-J_C": the committed bias mirror (XMis w=512u) with the RF
#        cascode's Nx swept. The DR-0003 core is a DENSITY mirror (Q3 Nx=1
#        against Q1 Nx=8), so I_C tracks Nx and the current density J_C
#        stays put: this family is the issue's literal "more parallel
#        emitter area at the same J_C" question, and it is a pure
#        POWER axis.
#     A2 "fix-I_C": Nx (and instance multiplicity m, to reach total emitter
#        areas past the model card's Nx <= 10 limit) swept with XMis scaled
#        as 4096u/(Nx*m) so I_C re-lands near the committed 3.94 mA. This
#        family holds DC power roughly fixed and sweeps J_C instead -- the
#        power-neutral lever the committed campaign never exercised.
#
#   Phase B -- two-stage cascade on one shared bias core
#     (dut/lna_2stage.spice.tmpl), at total powers inside and outside the
#     RATIFIED P_dc row. This is the "or a second stage" half of the same
#     acceptance criterion.
#
# The unmodified committed netlist runs as variant `s_ctrl_a8` and is the
# runner's own regression check: its numbers must reproduce record
# 20260926-122301-088c734's at every cell (the parser asserts this against
# the committed summary CSV and refuses to write a record if it drifts).
#
# NOT claimed by anything here: IIP3 (no two-tone phase in this bench), any
# conformance verdict against spec/target-spec.md (the RATIFIED rows are a
# bar these variants are measured against, not moved by), and any statement
# about the matching networks themselves (#27 owns those). Every variant
# other than the control is a PROBE, not a design: nothing under design/
# changes because of this experiment.
#
# Writes append-only evidence under corners/<record-id>/,
# netlist-snapshots/<record-id>/ and records/<record-id>.{csv,md} -- the
# same convention sim/README.md documents for every other experiment here.
#
# Environment knobs (all optional):
#   CORE_ENV_SMOKE=1    single nominal PVT cell, for plumbing checks.
#   CORE_ENV_VARIANTS   space-separated variant-id allow-list (default: all).
#   CORE_ENV_RECORD_ID  pin the record id instead of minting one from the
#                       UTC clock + short SHA. Combined with the resume
#                       behaviour below this lets an interrupted campaign
#                       finish as ONE record rather than two partial ones.
#
# RESUME: a deck whose log already ends in BENCH_COMPLETE under the target
# record id is not re-simulated. Every deck writes only its own
# netlist/log/wrdata files and reads nothing another deck wrote, so
# resuming is exactly equivalent to never having been interrupted -- the
# manifest is rebuilt from scratch each run, so the parsed record covers the
# full variant x PVT expansion either way.
#
# CONCURRENCY: this runner is deliberately SERIAL -- one ngspice process at
# a time, no job pool, no `&`. The whole grid is ~585 short `sp` decks at
# well under a second each, so there is nothing to gain from fanning out,
# and the shared dispatch hosts this fleet runs on are explicitly not
# simulation boxes. Do not add a job pool here.
set -euo pipefail

if (( BASH_VERSINFO[0] < 4 )); then
  echo "run_core_envelope.sh: needs bash >= 4.0 (found ${BASH_VERSION})." >&2
  exit 3
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SIM_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
REPO_ROOT="$(cd "${SIM_DIR}/.." && pwd)"

# shellcheck source=/dev/null
source "${SIM_DIR}/env.sh"

if [[ -z "${PDK_ROOT:-}" || ! -d "${PDK_ROOT}/${PDK}/libs.tech/ngspice" ]]; then
  echo "run_core_envelope.sh: no resolvable ${PDK:-ihp-sg13g2} install -- see sim/env.sh output above." >&2
  exit 3
fi
command -v ngspice >/dev/null 2>&1 || { echo "run_core_envelope.sh: ngspice not on PATH." >&2; exit 3; }
command -v python3 >/dev/null 2>&1 || { echo "run_core_envelope.sh: python3 not on PATH." >&2; exit 3; }
NGSPICE_VERSION="$(ngspice -v 2>&1 | sed -n '2p')"

MODELS_LIB="${PDK_ROOT}/${PDK}/libs.tech/ngspice/models/cornerHBT.lib"
MOS_LIB="${PDK_ROOT}/${PDK}/libs.tech/ngspice/models/cornerMOShv.lib"
OSDI_DIR="${PDK_ROOT}/${PDK}/libs.tech/ngspice/osdi"
for f in "${MODELS_LIB}" "${MOS_LIB}" "${OSDI_DIR}/psp103.osdi" \
         "${OSDI_DIR}/psp103_nqs.osdi" "${OSDI_DIR}/mosvar.osdi"; do
  [[ -f "${f}" ]] || { echo "run_core_envelope.sh: ${f} not found (for the .osdi files run sim/tools/build-osdi.sh)." >&2; exit 3; }
done

DESIGN_NETLIST="${REPO_ROOT}/design/netlist/lna.spice"
[[ -f "${DESIGN_NETLIST}" ]] || { echo "run_core_envelope.sh: ${DESIGN_NETLIST} not found." >&2; exit 3; }
DESIGN_NETLIST_SHA="$(shasum -a 256 "${DESIGN_NETLIST}" | awk '{print $1}')"

TEMPLATE="${SCRIPT_DIR}/testbench/tb_core_envelope.spice.tmpl"
DUT2_TMPL="${SCRIPT_DIR}/dut/lna_2stage.spice.tmpl"
PARSER="${SCRIPT_DIR}/parse_core_envelope.py"
for f in "${TEMPLATE}" "${DUT2_TMPL}" "${PARSER}"; do
  [[ -f "${f}" ]] || { echo "run_core_envelope.sh: ${f} not found." >&2; exit 3; }
done

REPO_GIT_SHA="$(cd "${REPO_ROOT}" && git rev-parse --short HEAD 2>/dev/null || echo unknown)"
RECORD_ID="${CORE_ENV_RECORD_ID:-$(date -u +%Y%m%d-%H%M%S)-${REPO_GIT_SHA}}"

SNAPSHOTS_OUT="${SCRIPT_DIR}/netlist-snapshots/${RECORD_ID}"
CORNERS_OUT="${SCRIPT_DIR}/corners/${RECORD_ID}"
RECORDS_DIR="${SCRIPT_DIR}/records"
mkdir -p "${SNAPSHOTS_OUT}" "${CORNERS_OUT}" "${RECORDS_DIR}"

# --- Single-stage DUT: the committed design netlist, uncommented --------
# Identical recovery step to sim/lna-characterization/run_lna_sweep.sh:
# uncomment xschem's own `**.subckt`/`**.ends` markers and drop the
# trailing `.end`, changing NO device line. The per-variant substitutions
# below are then applied to THAT text, so every variant differs from the
# committed netlist only in the lines the variant table names.
DUT1_BASE="$(mktemp)"
DUT_RENDERED="$(mktemp)"
trap 'rm -f "${DUT1_BASE}" "${DUT_RENDERED}"' EXIT
sed -e 's|^\*\*\.subckt|.subckt|' -e 's|^\*\*\.ends|.ends|' -e '/^\.end$/d' \
    "${DESIGN_NETLIST}" > "${DUT1_BASE}"
grep -q '^\.subckt lna ' "${DUT1_BASE}" || {
  echo "run_core_envelope.sh: could not recover '.subckt lna ...' from ${DESIGN_NETLIST}" >&2; exit 3; }

# --- PVT grid (identical to sim/lna-characterization/) ------------------
CORNER_LABELS=(typ bcs wcs sf fs)
declare -A HBT_SECTION_OF=( [typ]=hbt_typ [bcs]=hbt_bcs [wcs]=hbt_wcs [sf]=hbt_typ [fs]=hbt_typ )
declare -A MOS_SECTION_OF=( [typ]=mos_tt [bcs]=mos_ff [wcs]=mos_ss [sf]=mos_sf [fs]=mos_fs )
TEMPS=(-40 27 125)
VDDS=(1.62 1.80 1.98)

F_BAND_LO="2.4e9"; F_BAND_MID="2.44175e9"; F_BAND_HI="2.4835e9"; N_INBAND=11
F_STAB_LO="1e7";   F_STAB_HI="3e10";       N_STAB_DEC=40

# --- Variant table ------------------------------------------------------
# id | kind | nx1 | m1 | nx2 | m2 | xmis_w_um | family
# `kind` is 1stage or 2stage. For 1stage, (nx2,m2) are ignored. xmis_w_um
# is the DR-0003 island mirror width; the committed netlist's value is 512.
VARIANTS=(
  # --- A1 fix-J_C: committed mirror, Nx swept (power axis) -------------
  "s_fixj_a2|1stage|2|1|-|-|512|A1-fixJc"
  "s_fixj_a4|1stage|4|1|-|-|512|A1-fixJc"
  "s_fixj_a6|1stage|6|1|-|-|512|A1-fixJc"
  "s_ctrl_a8|1stage|8|1|-|-|512|A1-fixJc-CONTROL"
  "s_fixj_a10|1stage|10|1|-|-|512|A1-fixJc"
  # --- A2 fix-I_C: mirror scaled 4096/(Nx*m) (density axis) ------------
  "s_fixi_a4|1stage|4|1|-|-|1024|A2-fixIc"
  "s_fixi_a10|1stage|10|1|-|-|409.6|A2-fixIc"
  "s_fixi_a20|1stage|10|2|-|-|204.8|A2-fixIc"
  "s_fixi_a40|1stage|10|4|-|-|102.4|A2-fixIc"
  "s_fixi_a80|1stage|10|8|-|-|51.2|A2-fixIc"
  # --- B two-stage on one shared bias core -----------------------------
  "t_equal|2stage|8|1|8|1|273|B-2stage"
  "t_nfw|2stage|10|4|8|1|110|B-2stage"
  "t_bal|2stage|10|4|10|2|75|B-2stage"
  "t_lownf|2stage|10|8|10|2|45|B-2stage"
  "t_full|2stage|8|1|8|1|512|B-2stage-OVERBUDGET"
)

if [[ -n "${CORE_ENV_SMOKE:-}" ]]; then
  CORNER_LABELS=(typ); TEMPS=(27); VDDS=(1.80)
  echo "run_core_envelope.sh: SMOKE MODE -- one nominal cell only. Not a campaign record."
fi
if [[ -n "${CORE_ENV_VARIANTS:-}" ]]; then
  _keep=()
  for v in "${VARIANTS[@]}"; do
    vid="${v%%|*}"
    for w in ${CORE_ENV_VARIANTS}; do [[ "${vid}" == "${w}" ]] && _keep+=("${v}"); done
  done
  VARIANTS=("${_keep[@]}")
fi

N_TOTAL=$(( ${#VARIANTS[@]} * ${#CORNER_LABELS[@]} * ${#TEMPS[@]} * ${#VDDS[@]} ))
echo "run_core_envelope.sh: record ${RECORD_ID}"
echo "run_core_envelope.sh: ${#VARIANTS[@]} variants x ${#CORNER_LABELS[@]} corners x ${#TEMPS[@]} temps x ${#VDDS[@]} supplies = ${N_TOTAL} decks (serial)"
echo "run_core_envelope.sh: DUT sha256 ${DESIGN_NETLIST_SHA}"

MANIFEST="${CORNERS_OUT}/manifest.txt"
: > "${MANIFEST}"

render_dut() {  # kind nx1 m1 nx2 m2 wis -> stdout
  local kind="$1" nx1="$2" m1="$3" nx2="$4" m2="$5" wis="$6"
  if [[ "${kind}" == "1stage" ]]; then
    # Exactly three substitutions against the committed netlist text:
    # the two RF cascode device lines' geometry and the island mirror's
    # width. Every other line is byte-identical to design/netlist/lna.spice.
    sed -e "s|^XQ2 outn vb2 casc vss npn13G2 Nx=8$|XQ2 outn vb2 casc vss npn13G2 Nx=${nx1} m=${m1}|" \
        -e "s|^XQ1 casc b1 e1 vss npn13G2 Nx=8$|XQ1 casc b1 e1 vss npn13G2 Nx=${nx1} m=${m1}|" \
        -e "s|^XMis bref gsvo vdd vdd sg13_hv_pmos w=512u |XMis bref gsvo vdd vdd sg13_hv_pmos w=${wis}u |" \
        "${DUT1_BASE}"
  else
    sed -e "s|@@NX1@@|${nx1}|g" -e "s|@@M1@@|${m1}|g" \
        -e "s|@@NX2@@|${nx2}|g" -e "s|@@M2@@|${m2}|g" \
        -e "s|@@WIS@@|${wis}|g" "${DUT2_TMPL}"
  fi
}

n_done=0
n_skipped=0
for spec in "${VARIANTS[@]}"; do
  IFS='|' read -r VID KIND NX1 M1 NX2 M2 WIS FAMILY <<< "${spec}"
  if [[ "${KIND}" == "1stage" ]]; then
    Q1_REF=xq1; Q2_REF=xq2; CASC_NODE=casc; EMIT_NODE=e1; BASE_NODE=b1; OUT_NODE=outn
    AREA=$(( NX1 * M1 ))
  else
    Q1_REF=xq1a; Q2_REF=xq1b; CASC_NODE=casca; EMIT_NODE=e1a; BASE_NODE=b1a; OUT_NODE=outa
    AREA=$(( NX1 * M1 ))
  fi
  DUT_TXT="$(render_dut "${KIND}" "${NX1}" "${M1}" "${NX2}" "${M2}" "${WIS}")"
  # Fail loudly rather than silently simulating the committed geometry if a
  # substitution ever stops matching (e.g. the netlist is regenerated with a
  # different device line spelling).
  if [[ "${KIND}" == "1stage" ]]; then
    echo "${DUT_TXT}" | grep -q "^XQ1 casc b1 e1 vss npn13G2 Nx=${NX1} m=${M1}$" || {
      echo "run_core_envelope.sh: variant ${VID}: XQ1 geometry substitution did not match ${DESIGN_NETLIST}." >&2; exit 4; }
    echo "${DUT_TXT}" | grep -q "w=${WIS}u l=1u ng=1 m=1$" || {
      echo "run_core_envelope.sh: variant ${VID}: XMis width substitution did not match ${DESIGN_NETLIST}." >&2; exit 4; }
  else
    echo "${DUT_TXT}" | grep -q '@@' && {
      echo "run_core_envelope.sh: variant ${VID}: unsubstituted @@...@@ token left in the two-stage DUT." >&2; exit 4; }
  fi

  for corner in "${CORNER_LABELS[@]}"; do
    for temp in "${TEMPS[@]}"; do
      for vdd in "${VDDS[@]}"; do
        pid="${VID}_${corner}_${temp}c_vdd${vdd}v"
        deck="${SNAPSHOTS_OUT}/${pid}.spice"
        log="${CORNERS_OUT}/${pid}.log"
        inband="${CORNERS_OUT}/${pid}.inband.dat"
        stab="${CORNERS_OUT}/${pid}.stability.dat"
        printf '%s\n' "${DUT_TXT}" > "${DUT_RENDERED}"
        env \
          S_VARIANT="${VID}" \
          S_HBT="${HBT_SECTION_OF[$corner]}" S_MOS="${MOS_SECTION_OF[$corner]}" \
          S_MODELS_LIB="${MODELS_LIB}" S_MOS_LIB="${MOS_LIB}" S_OSDI_DIR="${OSDI_DIR}" \
          S_TEMP="${temp}" S_VDD="${vdd}" \
          S_N_INBAND="${N_INBAND}" S_F_LO="${F_BAND_LO}" S_F_MID="${F_BAND_MID}" S_F_HI="${F_BAND_HI}" \
          S_N_STAB="${N_STAB_DEC}" S_F_STAB_LO="${F_STAB_LO}" S_F_STAB_HI="${F_STAB_HI}" \
          S_INBAND="${inband}" S_STAB="${stab}" \
          S_Q1="${Q1_REF}" S_Q2="${Q2_REF}" S_CASC="${CASC_NODE}" S_EMIT="${EMIT_NODE}" \
          S_BASE="${BASE_NODE}" S_OUT="${OUT_NODE}" \
          python3 - "${TEMPLATE}" "${deck}" "${DUT_RENDERED}" <<'PYEOF'
import os, sys
tmpl, out, dut = sys.argv[1], sys.argv[2], sys.argv[3]
E = os.environ
subs = {
    "@@VARIANT@@": E["S_VARIANT"],
    "@@HBT_SECTION@@": E["S_HBT"], "@@MOS_SECTION@@": E["S_MOS"],
    "@@MODELS_LIB@@": E["S_MODELS_LIB"], "@@MOS_LIB@@": E["S_MOS_LIB"],
    "@@OSDI_DIR@@": E["S_OSDI_DIR"],
    "@@TEMP@@": E["S_TEMP"], "@@VDD@@": E["S_VDD"],
    "@@N_INBAND@@": E["S_N_INBAND"], "@@F_BAND_LO@@": E["S_F_LO"],
    "@@F_BAND_MID@@": E["S_F_MID"], "@@F_BAND_HI@@": E["S_F_HI"],
    "@@N_STAB_DEC@@": E["S_N_STAB"], "@@F_STAB_LO@@": E["S_F_STAB_LO"],
    "@@F_STAB_HI@@": E["S_F_STAB_HI"],
    "@@INBAND_DAT@@": E["S_INBAND"], "@@STAB_DAT@@": E["S_STAB"],
    "@@Q1_REF@@": E["S_Q1"], "@@Q2_REF@@": E["S_Q2"],
    "@@CASC_NODE@@": E["S_CASC"], "@@EMIT_NODE@@": E["S_EMIT"],
    "@@BASE_NODE@@": E["S_BASE"], "@@OUT_NODE@@": E["S_OUT"],
    "@@LNA_SUBCKT@@": open(dut).read().rstrip("\n"),
}
txt = open(tmpl).read()
for k, v in subs.items():
    txt = txt.replace(k, v)
if "@@" in txt:
    raise SystemExit("run_core_envelope.sh: unsubstituted @@...@@ token left in " + out)
open(out, "w").write(txt)
PYEOF

        if [[ -s "${log}" ]] && grep -q "BENCH_COMPLETE" "${log}" \
             && [[ -s "${inband}" && -s "${stab}" ]]; then
          n_skipped=$((n_skipped + 1))
        else
          if ! ngspice -b "${deck}" > "${log}" 2>&1; then
            echo "run_core_envelope.sh: ngspice returned non-zero for ${pid} (see ${log})" >&2
          fi
          grep -q "BENCH_COMPLETE" "${log}" || echo "run_core_envelope.sh: ${pid} did not reach BENCH_COMPLETE" >&2
        fi
        printf '%s|%s|%s|%s|%s|%s|%s|%s|%s|%s|%s|%s|%s\n' \
          "${pid}" "${VID}" "${FAMILY}" "${KIND}" "${NX1}" "${M1}" "${NX2}" "${M2}" "${AREA}" "${WIS}" \
          "${corner}" "${temp}" "${vdd}" >> "${MANIFEST}"
        n_done=$((n_done + 1))
        if (( n_done % 45 == 0 )); then echo "  ... ${n_done}/${N_TOTAL}"; fi
      done
    done
  done
done

echo "run_core_envelope.sh: ${n_done} decks total (${n_skipped} reused from a prior interrupted run); parsing"
python3 "${PARSER}" \
  --record-id "${RECORD_ID}" \
  --corners-dir "${CORNERS_OUT}" \
  --records-dir "${RECORDS_DIR}" \
  --manifest "${MANIFEST}" \
  --design-netlist-sha "${DESIGN_NETLIST_SHA}" \
  --ngspice-version "${NGSPICE_VERSION}" \
  --pdk-root "${PDK_ROOT}/${PDK}" \
  --reference-summary "${SIM_DIR}/lna-characterization/records/20260926-122301-088c734-summary.csv"

echo "run_core_envelope.sh: wrote records/${RECORD_ID}.{csv,md}"
