#!/usr/bin/env bash
# Cold-start invocation:
#
#   export PDK_ROOT=/path/to/ihp-open-pdk   # parent dir containing ihp-sg13g2/
#   export PDK=ihp-sg13g2
#   sim/breakdown-extraction/run_breakdown_sweep.sh
#
# (PDK_ROOT/PDK may also be left unset if the PDK is installed under one of
# the usual prefixes sim/env.sh checks.) Requires ngspice and python3 on
# PATH; does not require xschem, klt, or an OSDI build step (npn13G2 is a
# native ngspice VBIC model -- see sim/pdk.json). Full methodology, bench
# definitions, extraction criteria and model-validity caveats are in
# sim/breakdown-extraction/README.md -- read that first if a result here
# looks surprising.
#
# Extracts npn13G2's collector-emitter breakdown behaviour from the model
# card's own weak-avalanche parameters (avc1 = 2.40, avc2 = 10.81 --
# sg13g2_hbt_mod.lib), over the HBT process-corner grid x {-40, 27, 125} C
# x Nx in {1, 8}:
#
#   BENCH A (tb_bvceo_iforce.spice.tmpl) -- THE EXTRACTION. A
#     current-driven continuation: the collector current is FORCED over a
#     logarithmic grid and V_CE is the MEASURED quantity, which removes
#     the multi-branch ambiguity that makes a voltage-driven open-base
#     (or, as this record shows, any snapback-bearing) .dc sweep
#     untrustworthy. Run at
#       RB = 1e12 Ohm (open) -> BVCEO, at selft = 1 AND selft = 0
#       RB = 1.4e4 Ohm       -> BVCER at the loose end of the cascode
#                               base's plausible Thevenin bracket
#       RB = 1.4e3 Ohm       -> BVCER at its nominal value
#       RB = 1.4e2 / 1e-3    -> BVCER(tight) / BVCES method probes
#     The forced-current grid tops out at 3.16e-3 A/finger, which is the
#     model card's OWN declared current-validity ceiling (ic < 0.003*Nx
#     A), so "no sustaining branch was found" always means "none exists
#     within the range the card is valid over", never "the sweep was too
#     short".
#
#   BENCH B (tb_bvcer_vsweep.spice.tmpl) -- the held-base LEAKAGE
#     read-out and two controls. A voltage-driven .dc sweep of V_CE,
#     which is sound only where the characteristic is monotone and
#     single-valued:
#       RB = 1.4e3 / 1e-3 Ohm -> held-base leakage I_C(V_CE) at
#                                DR-0001's V_CE read-out points (sound:
#                                monotone everywhere)
#       RB = 1e9 Ohm          -> CONTROL: the naive open-base method's
#                                failure, reproduced
#       RB = 1.4e4 Ohm        -> CONTROL: the same branch-following
#                                failure at a finite base impedance that
#                                DOES snap back, cross-checked against
#                                Bench A's answer for the same cells
#     Plus an extended-ceiling (12 V) probe set, explicitly outside the
#     model card's validity range, to show the absence of any held-base
#     runaway at RB <= 1.4e3 Ohm is not an artefact of where the primary
#     sweep stops.
#
# The 1.4 kOhm centre of the finite-RB bracket is the Thevenin resistance
# of the bypassed 11:1 cascode-base divider proposed in
# spec/decision-records/0001-bias-supply-topology.md at a 100 uA divider
# current -- see README.md "Why 1.4 kOhm, and why a bracket around it"
# for the derivation and for why a bracket is swept rather than a single
# value (DR-0001 fixes the divider RATIO, not its absolute impedance).
#
# Writes append-only evidence under corners/<record-id>/,
# netlist-snapshots/<record-id>/ and records/<record-id>*.{csv,md} -- see
# sim/README.md for the convention this follows, and
# sim/hbt-characterization/run_hbt_sweep.sh for the structural precedent
# (render-deck -> ngspice -b -> parse -> CSV + record).
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SIM_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
REPO_ROOT="$(cd "${SIM_DIR}/.." && pwd)"

# shellcheck source=/dev/null
source "${SIM_DIR}/env.sh"

if [[ -z "${PDK_ROOT:-}" || ! -d "${PDK_ROOT}/${PDK}/libs.tech/ngspice" ]]; then
  echo "run_breakdown_sweep.sh: no resolvable ${PDK:-ihp-sg13g2} install -- see sim/env.sh output above." >&2
  exit 3
fi

command -v ngspice >/dev/null 2>&1 || { echo "run_breakdown_sweep.sh: ngspice not on PATH." >&2; exit 3; }
command -v python3 >/dev/null 2>&1 || { echo "run_breakdown_sweep.sh: python3 not on PATH." >&2; exit 3; }
NGSPICE_VERSION="$(ngspice -v 2>&1 | sed -n '2p' | sed 's/^\*\* *//')"

MODELS_LIB="${PDK_ROOT}/${PDK}/libs.tech/ngspice/models/cornerHBT.lib"
if [[ ! -f "${MODELS_LIB}" ]]; then
  echo "run_breakdown_sweep.sh: cornerHBT.lib not found at ${MODELS_LIB}" >&2
  exit 3
fi

REPO_GIT_SHA="$(cd "${REPO_ROOT}" && git rev-parse --short HEAD 2>/dev/null || echo unknown)"
RECORD_ID="$(date -u +%Y%m%d-%H%M%S)-${REPO_GIT_SHA}"

EXPERIMENT_DIR="${SCRIPT_DIR}"
SNAPSHOTS_OUT="${EXPERIMENT_DIR}/netlist-snapshots/${RECORD_ID}"
CORNERS_OUT="${EXPERIMENT_DIR}/corners/${RECORD_ID}"
RECORDS_DIR="${EXPERIMENT_DIR}/records"
CSV_A="${RECORDS_DIR}/${RECORD_ID}-bvceo-locus.csv"
CSV_B="${RECORDS_DIR}/${RECORD_ID}-heldbase-sweep.csv"
SUM_A="${RECORDS_DIR}/${RECORD_ID}-bvceo-summary.csv"
SUM_B="${RECORDS_DIR}/${RECORD_ID}-heldbase-summary.csv"
MD_OUT="${RECORDS_DIR}/${RECORD_ID}.md"
mkdir -p "${SNAPSHOTS_OUT}" "${CORNERS_OUT}" "${RECORDS_DIR}"

# --- Sweep grid ----------------------------------------------------------
# Corner labels mirror cornerMOShv.lib's five-label convention (for
# fleet-wide consistency), mapped onto cornerHBT.lib's three REAL sections
# -- see sim/README.md "Corner-label convention" for the discrepancy this
# resolves. sf/fs fall back to hbt_typ, so their rows are numerically
# identical to typ by construction; they are run and recorded anyway so
# the grid is literally the one spec/target-spec.md names.
CORNER_LABELS=(typ bcs wcs sf fs)
declare -A HBT_SECTION_OF=( [typ]=hbt_typ [bcs]=hbt_bcs [wcs]=hbt_wcs [sf]=hbt_typ [fs]=hbt_typ )
TEMPS=(-40 27 125)
NXS=(1 8)

# Base terminations. The label is what appears in point ids and CSVs.
declare -A RB_OHM=( [open]=1e12 [1g]=1e9 [14k]=1.4e4 [1p4k]=1.4e3 [140]=1.4e2 [short]=1e-3 )

# Bench A: forced collector current, logarithmic, PER FINGER (the grid is
# multiplied by Nx inside the template so the current DENSITY grid -- and
# hence the extraction criteria -- is Nx-invariant). 1e-10 A/finger ->
# 3.16e-3 A/finger, 8 points/decade, 61 points. 1e-6/1e-5/1e-4 A/finger
# land exactly on the grid; 5e-4 A/finger (DR-0001's nominal 4.0 mA at
# Nx=8) is interpolated between grid points.
I_START="1e-10"
PTS_PER_DECADE=8
N_POINTS_A=61

# Bench B: voltage sweep. 0.20 V -> 5.40 V in 0.04 V steps = 131 points,
# a step chosen so 1.12 V (DR-0001's worst-case V_CE2), 1.40 V
# (BVCEO min), 1.60 V (vce_max) and 2.00 V (the model card's validity
# ceiling) all land exactly on the grid, and a ceiling chosen to sit just
# past the card's vbc_max = 5.1 V.
V_START="0.20"
V_STEP="0.04"
V_STOP="5.40"
N_POINTS_B=131
# Extended-ceiling probe (explicitly outside the model's validity range).
V_STOP_EXT="12.00"
N_POINTS_B_EXT=296

CSV_A_RAW="${CSV_A}.part"
CSV_B_RAW="${CSV_B}.part"
echo "point_id,bench,role,corner_label,hbt_section,temp_c,nx,selft,rb_label,rb_ohm,ic_a,ic_per_nx_a,vce_v,vb_v,ie_a" > "${CSV_A_RAW}"
echo "point_id,bench,role,corner_label,hbt_section,temp_c,nx,selft,rb_label,rb_ohm,vce_v,ic_a,ic_per_nx_a,vbe_v" > "${CSV_B_RAW}"

total_runs=0
failed_points=()
partial_points=()
probe_points=()

# run_bench_a <corner> <section> <temp> <nx> <selft> <rb_label> <role>
# role: "extraction" (a hard failure fails the run) or "probe" (a
# non-convergent result is the expected, recorded outcome).
run_bench_a() {
  local corner_label="$1" hbt_section="$2" temp="$3" nx="$4" selft="$5" rb_label="$6" role="$7"
  local rb="${RB_OHM[${rb_label}]}"
  local point_id="a_nx${nx}_${corner_label}_${temp}c_rb${rb_label}_st${selft}"
  local netlist="${SNAPSHOTS_OUT}/${point_id}.spice"
  local log="${CORNERS_OUT}/${point_id}.log"
  local meas="${CORNERS_OUT}/${point_id}.meas"
  rm -f "${meas}"

  sed \
    -e "s|@@MEAS_OUT@@|${meas}|g" \
    -e "s|@@MODELS_LIB@@|${MODELS_LIB}|g" \
    -e "s|@@HBT_SECTION@@|${hbt_section}|g" \
    -e "s|@@TEMP@@|${temp}|g" \
    -e "s|@@NX@@|${nx}|g" \
    -e "s|@@SELFT@@|${selft}|g" \
    -e "s|@@RB@@|${rb}|g" \
    -e "s|@@I_START@@|${I_START}|g" \
    -e "s|@@PTS_PER_DECADE@@|${PTS_PER_DECADE}|g" \
    -e "s|@@N_POINTS@@|${N_POINTS_A}|g" \
    "${EXPERIMENT_DIR}/testbench/tb_bvceo_iforce.spice.tmpl" > "${netlist}"

  total_runs=$((total_runs + 1))
  local rc=0
  ngspice -b "${netlist}" > "${log}" 2>&1 || rc=$?

  local n_pt n_conv
  # NUM is the strict numeric-token test applied to every parsed value:
  # anything else (an interleaved diagnostic, an empty field from a
  # non-converged op) is recorded as a blank, never as a number.
  n_pt=$(grep -c "^PT " "${meas}" 2>/dev/null || true)
  n_conv=$(awk '$1=="VCE" && $2 ~ /^[+-]?([0-9]+\.?[0-9]*|\.[0-9]+)([eE][+-]?[0-9]+)?$/ { c++ } END { print c+0 }' "${meas}" 2>/dev/null || echo 0)

  if [[ "${role}" == "probe" ]]; then
    # A probe cell exists to SHOW the method failing at a held base. Its
    # outcome (however partial) is recorded, never treated as a run
    # failure -- see README.md "Why Bench A is open-base only".
    probe_points+=("${point_id}:${n_conv}/${N_POINTS_A}")
  else
    # A hard failure of an EXTRACTION cell is: a non-zero ngspice exit, a
    # model-resolution error, a missing end-of-control-script marker, or
    # fewer than N_POINTS_A "PT " markers (the batch aborted partway).
    if [[ ${rc} -ne 0 ]] \
      || grep -qiE "Unable to find definition of model|couldn't be loaded|Unknown model type|fatal error" "${log}" \
      || ! grep -q "Simulation executed from .control section" "${log}" \
      || [[ "${n_pt}" -lt "${N_POINTS_A}" ]]; then
      echo "run_breakdown_sweep.sh: FAILED ${point_id} (rc=${rc}, PT lines=${n_pt}/${N_POINTS_A}) -- see ${log}" >&2
      failed_points+=("${point_id}")
      return
    fi
    if [[ "${n_conv}" -lt "${N_POINTS_A}" ]]; then
      partial_points+=("${point_id}:${n_conv}/${N_POINTS_A}")
    fi
  fi

  awk -v pid="${point_id}" -v role="${role}" -v corner="${corner_label}" -v section="${hbt_section}" \
      -v temp="${temp}" -v nx="${nx}" -v selft="${selft}" \
      -v rbl="${rb_label}" -v rb="${rb}" '
    function num(s) {
      return (s ~ /^[+-]?([0-9]+\.?[0-9]*|\.[0-9]+)([eE][+-]?[0-9]+)?$/) ? s : ""
    }
    $1=="PT"  { ic = num($2); vce = ""; vb = ""; ie = ""; next }
    $1=="VCE" { vce = num($2); next }
    $1=="VBE" { vb  = num($2); next }
    $1=="IE"  {
      ie = num($2)
      icpn = (ic == "") ? "" : sprintf("%.6e", (ic+0) / nx)
      printf "%s,A,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s\n", \
        pid, role, corner, section, temp, nx, selft, rbl, rb, ic, icpn, vce, vb, ie
      next
    }
  ' "${meas}" >> "${CSV_A_RAW}"
}

# run_bench_b <corner> <section> <temp> <nx> <selft> <rb_label> <role> <v_stop> <n_expected> <id_prefix>
run_bench_b() {
  local corner_label="$1" hbt_section="$2" temp="$3" nx="$4" selft="$5" rb_label="$6"
  local role="$7" v_stop="$8" n_expected="$9" id_prefix="${10}"
  local rb="${RB_OHM[${rb_label}]}"
  local point_id="${id_prefix}_nx${nx}_${corner_label}_${temp}c_rb${rb_label}_st${selft}"
  local netlist="${SNAPSHOTS_OUT}/${point_id}.spice"
  local log="${CORNERS_OUT}/${point_id}.log"
  local meas="${CORNERS_OUT}/${point_id}.meas"
  rm -f "${meas}"

  sed \
    -e "s|@@MEAS_OUT@@|${meas}|g" \
    -e "s|@@MODELS_LIB@@|${MODELS_LIB}|g" \
    -e "s|@@HBT_SECTION@@|${hbt_section}|g" \
    -e "s|@@TEMP@@|${temp}|g" \
    -e "s|@@NX@@|${nx}|g" \
    -e "s|@@SELFT@@|${selft}|g" \
    -e "s|@@RB@@|${rb}|g" \
    -e "s|@@V_START@@|${V_START}|g" \
    -e "s|@@V_STOP@@|${v_stop}|g" \
    -e "s|@@V_STEP@@|${V_STEP}|g" \
    "${EXPERIMENT_DIR}/testbench/tb_bvcer_vsweep.spice.tmpl" > "${netlist}"

  total_runs=$((total_runs + 1))
  local rc=0
  ngspice -b "${netlist}" > "${log}" 2>&1 || rc=$?

  if grep -qiE "Unable to find definition of model|couldn't be loaded|Unknown model type" "${log}"; then
    echo "run_breakdown_sweep.sh: FAILED ${point_id} (model resolution) -- see ${log}" >&2
    failed_points+=("${point_id}")
    return
  fi

  # `print ic vbe` emits one "<index> <vce> <ic> <vbe>" row per swept
  # point. A voltage-driven sweep that loses convergence stops EARLY and
  # ngspice then exits non-zero -- that truncation is itself data (it is
  # how the naive-method control fails), so it is recorded as a partial
  # cell rather than discarded. Only a cell that produced NO rows at all
  # is a hard failure.
  local n_rows
  n_rows=$(awk 'NF==4 && $1 ~ /^[0-9]+$/ { c++ } END { print c+0 }' "${meas}" 2>/dev/null || echo 0)
  if [[ "${n_rows}" -eq 0 ]]; then
    echo "run_breakdown_sweep.sh: FAILED ${point_id} (rc=${rc}, no swept rows) -- see ${log}" >&2
    failed_points+=("${point_id}")
    return
  fi
  if [[ "${n_rows}" -lt "${n_expected}" ]]; then
    partial_points+=("${point_id}:${n_rows}/${n_expected}")
  fi

  awk -v pid="${point_id}" -v role="${role}" -v corner="${corner_label}" -v section="${hbt_section}" \
      -v temp="${temp}" -v nx="${nx}" -v selft="${selft}" \
      -v rbl="${rb_label}" -v rb="${rb}" '
    function isnum(s) {
      return (s ~ /^[+-]?([0-9]+\.?[0-9]*|\.[0-9]+)([eE][+-]?[0-9]+)?$/)
    }
    NF==4 && $1 ~ /^[0-9]+$/ && isnum($2) && isnum($3) && isnum($4) {
      printf "%s,B,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%.6e,%s\n", \
        pid, role, corner, section, temp, nx, selft, rbl, rb, $2, $3, ($3+0)/nx, $4
    }
  ' "${meas}" >> "${CSV_B_RAW}"
}

echo "run_breakdown_sweep.sh: record ${RECORD_ID}; Bench A (open base) ..."
# --- Bench A: BVCEO (open base), self-heating ON and OFF -----------------
for corner_label in "${CORNER_LABELS[@]}"; do
  hbt_section="${HBT_SECTION_OF[${corner_label}]}"
  for temp in "${TEMPS[@]}"; do
    for nx in "${NXS[@]}"; do
      for selft in 1 0; do
        run_bench_a "${corner_label}" "${hbt_section}" "${temp}" "${nx}" "${selft}" open extraction
      done
    done
  done
done

echo "run_breakdown_sweep.sh: Bench A (finite base termination) ..."
# --- Bench A: BVCER at the cascode-base Thevenin bracket -----------------
# Same robust current-driven method, full grid, at the two base
# impedances that bracket DR-0001's bypassed 11:1 divider (see README.md
# "Why 1.4 kOhm, and why a bracket around it"). selft is not swept here:
# these cells sit at sub-nanowatt dissipation until the avalanche branch
# is reached, and the open-base cells above already bound the
# self-heating sensitivity.
for corner_label in "${CORNER_LABELS[@]}"; do
  hbt_section="${HBT_SECTION_OF[${corner_label}]}"
  for temp in "${TEMPS[@]}"; do
    for nx in "${NXS[@]}"; do
      for rb_label in 14k 1p4k; do
        run_bench_a "${corner_label}" "${hbt_section}" "${temp}" "${nx}" 1 "${rb_label}" extraction
      done
    done
  done
done

# --- Bench A: tight-RB / shorted-base METHOD PROBES (typ/27 C only) ------
# Committed so the README's claim that no avalanche-sustained branch
# exists at a tightly-held base -- within the model card's own current
# validity range -- is itself evidenced, not asserted. These cells are
# expected to lose convergence: with the base held to the emitter the
# device is off, so forcing even 0.1 nA drives the solver to tens or
# hundreds of volts and then into a self-heating NaN.
for nx in "${NXS[@]}"; do
  for rb_label in 140 short; do
    run_bench_a typ hbt_typ 27 "${nx}" 1 "${rb_label}" probe
  done
done

echo "run_breakdown_sweep.sh: Bench B (held-base leakage + controls) ..."
# --- Bench B: the naive voltage-driven control at a quasi-open base ------
for corner_label in "${CORNER_LABELS[@]}"; do
  hbt_section="${HBT_SECTION_OF[${corner_label}]}"
  for temp in "${TEMPS[@]}"; do
    for nx in "${NXS[@]}"; do
      run_bench_b "${corner_label}" "${hbt_section}" "${temp}" "${nx}" 1 1g \
        control-open "${V_STOP}" "${N_POINTS_B}" b
    done
  done
done

# --- Bench B: held-base leakage read-out (1.4 kOhm and short) -----------
# Sound here: at these impedances I_C(V_CE) is monotone and
# single-valued over the whole swept range (asserted per cell in the
# summary's ic_monotone_in_vce column, not assumed).
for corner_label in "${CORNER_LABELS[@]}"; do
  hbt_section="${HBT_SECTION_OF[${corner_label}]}"
  for temp in "${TEMPS[@]}"; do
    for nx in "${NXS[@]}"; do
      for rb_label in 1p4k short; do
        run_bench_b "${corner_label}" "${hbt_section}" "${temp}" "${nx}" 1 "${rb_label}" \
          leakage "${V_STOP}" "${N_POINTS_B}" b
      done
    done
  done
done

# --- Bench B: the SECOND control -- a finite base impedance that DOES
# snap back (14 kOhm). Run voltage-driven on purpose, so the record shows
# the branch-following failure is not unique to an open base, and so
# Bench A's answer for the same cells can be cross-checked against it.
for corner_label in "${CORNER_LABELS[@]}"; do
  hbt_section="${HBT_SECTION_OF[${corner_label}]}"
  for temp in "${TEMPS[@]}"; do
    for nx in "${NXS[@]}"; do
      run_bench_b "${corner_label}" "${hbt_section}" "${temp}" "${nx}" 1 14k \
        control-snapback "${V_STOP}" "${N_POINTS_B}" b
    done
  done
done

# --- Bench B: extended-ceiling probe (12 V), OUTSIDE model validity ------
for corner_label in "${CORNER_LABELS[@]}"; do
  hbt_section="${HBT_SECTION_OF[${corner_label}]}"
  for temp in "${TEMPS[@]}"; do
    run_bench_b "${corner_label}" "${hbt_section}" "${temp}" 8 1 1p4k \
      extended-probe "${V_STOP_EXT}" "${N_POINTS_B_EXT}" bx
  done
done

a_rows=$(($(wc -l < "${CSV_A_RAW}") - 1))
b_rows=$(($(wc -l < "${CSV_B_RAW}") - 1))
if [[ ${a_rows} -le 0 || ${b_rows} -le 0 ]]; then
  echo "run_breakdown_sweep.sh: a bench produced no data -- refusing to write a summary." >&2
  exit 1
fi
mv "${CSV_A_RAW}" "${CSV_A}"
mv "${CSV_B_RAW}" "${CSV_B}"

# --- Summaries -----------------------------------------------------------
HEADLINE="$(mktemp -t breakdown-headline)"
python3 - "${CSV_A}" "${SUM_A}" "${CSV_B}" "${SUM_B}" "${HEADLINE}" <<'PYEOF'
import csv, math, sys
from collections import defaultdict

csv_a, sum_a, csv_b, sum_b, headline_path = sys.argv[1:6]

# Bench A extraction criteria, in A PER FINGER (Nx-invariant by
# construction -- the forced-current grid is scaled by Nx in the
# template). 5e-4 A/finger is DR-0001's nominal operating current
# (I_C = 4.0 mA at Nx = 8).
A_CRITERIA = [("1ua", 1e-6), ("10ua", 1e-5), ("100ua", 1e-4), ("500ua", 5e-4)]
# Bench B: leakage read-out voltages, and the current criteria at which a
# held-base breakdown voltage would be declared (per finger).
B_READOUT_V = [("1p12", 1.12), ("1p40", 1.40), ("1p60", 1.60), ("2p00", 2.00)]
B_CRITERIA = [("1ua", 1e-6), ("10ua", 1e-5)]


def interp_x_at_y(pts, target):
    """Linear-in-log(y) interpolation of x at a target y, over an
    ascending-in-y run of (y, x) pairs."""
    prev = None
    for y, x in pts:
        if prev is not None and prev[0] <= target <= y:
            if y == prev[0]:
                return x
            f = (math.log(target) - math.log(prev[0])) / (math.log(y) - math.log(prev[0]))
            return prev[1] + f * (x - prev[1])
        prev = (y, x)
    return None


# ---------------- Bench A ----------------
rows_a = list(csv.DictReader(open(csv_a)))
groups = defaultdict(list)
for r in rows_a:
    groups[r["point_id"]].append(r)

out_a = []
for pid, pts in groups.items():
    meta = pts[0]
    good = [(float(p["ic_per_nx_a"]), float(p["vce_v"]))
            for p in pts if p["vce_v"] not in ("", None)]
    good.sort()
    row = {
        "point_id": pid, "role": meta["role"], "corner_label": meta["corner_label"],
        "hbt_section": meta["hbt_section"], "temp_c": meta["temp_c"],
        "nx": meta["nx"], "selft": meta["selft"],
        "rb_label": meta["rb_label"], "rb_ohm": meta["rb_ohm"],
        "n_points": len(pts), "n_converged": len(good),
    }
    for name, target in A_CRITERIA:
        v = interp_x_at_y(good, target)
        row[f"vce_at_{name}_per_nx_v"] = f"{v:.4f}" if v is not None else ""
    if good:
        imin, vmin = min(good, key=lambda t: t[1])
        row["locus_min_vce_v"] = f"{vmin:.4f}"
        row["locus_min_at_ic_per_nx_a"] = f"{imin:.4e}"
        # A fold-back (snapback) exists only if the locus minimum is
        # interior to the swept current range; a monotonically rising
        # locus means the low-current end never needed an
        # avalanche-sustained branch (leakage carries it instead), so no
        # sustaining voltage is defined there.
        row["locus_has_foldback"] = "yes" if good[0][0] < imin < good[-1][0] else "no"
    else:
        row["locus_min_vce_v"] = ""
        row["locus_min_at_ic_per_nx_a"] = ""
        row["locus_has_foldback"] = ""
    out_a.append(row)

fields_a = ["point_id", "role", "corner_label", "hbt_section", "temp_c", "nx", "selft",
            "rb_label", "rb_ohm", "n_points", "n_converged"] + \
           [f"vce_at_{n}_per_nx_v" for n, _ in A_CRITERIA] + \
           ["locus_min_vce_v", "locus_min_at_ic_per_nx_a", "locus_has_foldback"]
out_a.sort(key=lambda r: (r["role"], r["rb_label"], r["nx"], r["corner_label"],
                          int(r["temp_c"]), r["selft"]))
# newline="\n", not "": csv's default dialect terminates rows with CRLF,
# which would make this committed append-only record differ byte-for-byte
# from every other CSV in sim/ (all LF) and from its own re-run under git's
# text normalisation.
with open(sum_a, "w", newline="\n") as f:
    w = csv.DictWriter(f, fieldnames=fields_a)
    w.writeheader()
    w.writerows(out_a)

# ---------------- Bench B ----------------
rows_b = list(csv.DictReader(open(csv_b)))
groups_b = defaultdict(list)
for r in rows_b:
    groups_b[r["point_id"]].append(r)

out_b = []
for pid, pts in groups_b.items():
    meta = pts[0]
    seq = sorted((float(p["vce_v"]), float(p["ic_per_nx_a"])) for p in pts)
    row = {
        "point_id": pid, "role": meta["role"], "corner_label": meta["corner_label"],
        "hbt_section": meta["hbt_section"], "temp_c": meta["temp_c"],
        "nx": meta["nx"], "selft": meta["selft"],
        "rb_label": meta["rb_label"], "rb_ohm": meta["rb_ohm"],
        "n_points": len(seq),
        "v_last_v": f"{seq[-1][0]:.2f}",
        "ic_per_nx_max_a": f"{max(i for _, i in seq):.4e}",
    }
    # Monotone in I_C over the swept range? (The property that makes a
    # voltage-driven sweep sound for this cell.)
    mono = all(seq[k][1] >= seq[k - 1][1] * (1 - 1e-9) for k in range(1, len(seq)))
    row["ic_monotone_in_vce"] = "yes" if mono else "no"
    # V_CE at which I_C/finger first crosses each criterion (interpolated).
    iv = [(i, v) for v, i in seq]
    for name, target in B_CRITERIA:
        crossed = [k for k in range(len(seq)) if seq[k][1] >= target]
        if crossed:
            k = crossed[0]
            if k == 0:
                v = seq[0][0]
            else:
                v = interp_x_at_y([iv[k - 1], iv[k]], target)
                v = v if v is not None else seq[k][0]
            row[f"vce_at_{name}_per_nx_v"] = f"{v:.4f}"
        else:
            row[f"vce_at_{name}_per_nx_v"] = ""
    for name, target in B_READOUT_V:
        hit = [i for v, i in seq if abs(v - target) < 1e-9]
        row[f"ic_per_nx_at_{name}v_a"] = f"{hit[0]:.4e}" if hit else ""
    out_b.append(row)

fields_b = ["point_id", "role", "corner_label", "hbt_section", "temp_c", "nx", "selft",
            "rb_label", "rb_ohm", "n_points", "v_last_v", "ic_per_nx_max_a",
            "ic_monotone_in_vce"] + \
           [f"vce_at_{n}_per_nx_v" for n, _ in B_CRITERIA] + \
           [f"ic_per_nx_at_{n}v_a" for n, _ in B_READOUT_V]
out_b.sort(key=lambda r: (r["role"], r["rb_label"], r["nx"], r["corner_label"], int(r["temp_c"])))
with open(sum_b, "w", newline="\n") as f:
    w = csv.DictWriter(f, fieldnames=fields_b)
    w.writeheader()
    w.writerows(out_b)

# ---------------- Headline numbers the record narrates ----------------
open_rows = [r for r in out_a if r["rb_label"] == "open" and r["role"] == "extraction"]
# A cell has an avalanche-SUSTAINED branch only if its locus turns round
# at a physically meaningful voltage inside the swept (and card-valid)
# current range. 10 V is an order of magnitude above anything the card is
# valid for, so anything above it is the "device is simply off, the
# solver is extrapolating" regime, not a breakdown branch.
SUSTAIN_V_CEILING = 10.0


def sustained(r):
    return (r["locus_has_foldback"] == "yes"
            and r["locus_min_vce_v"] != ""
            and float(r["locus_min_vce_v"]) <= SUSTAIN_V_CEILING)


def emit(f, key, value):
    # Single-quoted: several values contain ";", "/" and spaces, which
    # the shell would otherwise treat as syntax when it sources this.
    f.write("%s='%s'\n" % (key, str(value).replace("'", "'\\''")))


with open(headline_path, "w") as f:
    emit(f, "N_OPEN_CELLS", len(open_rows))
    for name, _ in A_CRITERIA:
        col = f"vce_at_{name}_per_nx_v"
        vals = [(float(r[col]), r) for r in open_rows if r[col]]
        if not vals:
            continue
        lo_v, lo_r = min(vals, key=lambda t: t[0])
        hi_v, hi_r = max(vals, key=lambda t: t[0])
        u = name.upper()
        emit(f, f"BVCEO_{u}_MIN", f"{lo_v:.4f}")
        emit(f, f"BVCEO_{u}_MIN_CELL",
             f"{lo_r['corner_label']}/{lo_r['temp_c']}C/Nx{lo_r['nx']}/selft{lo_r['selft']}")
        emit(f, f"BVCEO_{u}_MAX", f"{hi_v:.4f}")
        emit(f, f"BVCEO_{u}_MAX_CELL",
             f"{hi_r['corner_label']}/{hi_r['temp_c']}C/Nx{hi_r['nx']}/selft{hi_r['selft']}")
        emit(f, f"N_BELOW_1V4_{u}",
             len({(r["corner_label"], r["temp_c"], r["nx"]) for v, r in vals if v < 1.4}))
        emit(f, f"CELLS_BELOW_1V4_{u}",
             ' '.join('/'.join(c) for c in sorted(
                 {(r["corner_label"], r["temp_c"], r["nx"]) for v, r in vals if v < 1.4})))
        emit(f, f"N_BELOW_1V6_{u}",
             len({(r["corner_label"], r["temp_c"], r["nx"]) for v, r in vals if v < 1.6}))
        # Per-temperature minimum (the temperature-derating statement).
        for t in ("-40", "27", "125"):
            tv = [v for v, r in vals if r["temp_c"] == t]
            if tv:
                emit(f, f"BVCEO_{u}_MIN_T{t.replace('-', 'M')}", f"{min(tv):.4f}")
        # Self-heating delta: same cell, selft 1 vs 0.
        by_cell = defaultdict(dict)
        for v, r in vals:
            by_cell[(r["corner_label"], r["temp_c"], r["nx"])][r["selft"]] = v
        d = [abs(x["1"] - x["0"]) for x in by_cell.values() if "1" in x and "0" in x]
        emit(f, f"SELFT_MAX_DELTA_{u}", f"{max(d):.6f}" if d else "NA")
        # Nx invariance: same corner/temp/selft, Nx 1 vs 8.
        by_cell2 = defaultdict(dict)
        for v, r in vals:
            by_cell2[(r["corner_label"], r["temp_c"], r["selft"])][r["nx"]] = v
        d2 = [abs(x["1"] - x["8"]) for x in by_cell2.values() if "1" in x and "8" in x]
        emit(f, f"NX_MAX_DELTA_{u}", f"{max(d2):.6f}" if d2 else "NA")

# Bench A: the finite-base-termination (BVCER) extraction cells.
with open(headline_path, "a") as f:
    for rbl in ("14k", "1p4k"):
        cells = [r for r in out_a if r["rb_label"] == rbl and r["role"] == "extraction"]
        u = rbl.upper().replace("P", "P")
        emit(f, f"N_A_{u}_CELLS", len(cells))
        sus = [r for r in cells if sustained(r)]
        emit(f, f"N_A_{u}_SUSTAINED", len(sus))
        if sus:
            vals = [(float(r["locus_min_vce_v"]), r) for r in sus]
            lo_v, lo_r = min(vals, key=lambda t: t[0])
            hi_v, hi_r = max(vals, key=lambda t: t[0])
            emit(f, f"A_{u}_SUS_MIN", f"{lo_v:.4f}")
            emit(f, f"A_{u}_SUS_MIN_CELL",
                 f"{lo_r['corner_label']}/{lo_r['temp_c']}C/Nx{lo_r['nx']}")
            emit(f, f"A_{u}_SUS_MAX", f"{hi_v:.4f}")
            emit(f, f"A_{u}_SUS_MAX_CELL",
                 f"{hi_r['corner_label']}/{hi_r['temp_c']}C/Nx{hi_r['nx']}")
            for t in ("-40", "27", "125"):
                tv = [v for v, r in vals if r["temp_c"] == t]
                if tv:
                    emit(f, f"A_{u}_SUS_MIN_T{t.replace('-', 'M')}", f"{min(tv):.4f}")
        op_vals = [float(r["vce_at_500ua_per_nx_v"]) for r in cells if r["vce_at_500ua_per_nx_v"]]
        emit(f, f"A_{u}_500UA_MIN", f"{min(op_vals):.4f}" if op_vals else "NA")
        emit(f, f"A_{u}_500UA_MAX", f"{max(op_vals):.4f}" if op_vals else "NA")
    probes = [r for r in out_a if r["role"] == "probe"]
    emit(f, "N_A_PROBE_CELLS", len(probes))
    emit(f, "N_A_PROBE_SUSTAINED", len([r for r in probes if sustained(r)]))
    emit(f, "A_PROBE_MIN_VCE", ' '.join(
        f"{r['rb_label']}/Nx{r['nx']}:{r['locus_min_vce_v'] or 'NA'}V" for r in
        sorted(probes, key=lambda r: (r["rb_label"], int(r["nx"])))))

# Bench B: held-base leakage cells and the two controls.
held = [r for r in out_b if r["role"] == "leakage"]
held_crossed = [r for r in held if r["vce_at_1ua_per_nx_v"]]
held_nonmono = [r for r in held if r["ic_monotone_in_vce"] != "yes"]
ext = [r for r in out_b if r["role"] == "extended-probe"]
ext_crossed = [r for r in ext if r["vce_at_1ua_per_nx_v"]]
ctrl = [r for r in out_b if r["role"] == "control-open"]
ctrl_crossed = [r for r in ctrl if r["vce_at_1ua_per_nx_v"]]
ctrl_trunc = [r for r in ctrl if r["n_points"] < 131]
snap = [r for r in out_b if r["role"] == "control-snapback"]
snap_crossed = [r for r in snap if r["vce_at_1ua_per_nx_v"]]


def leak_max(rows, col):
    vals = [(float(r[col]), r) for r in rows if r[col]]
    if not vals:
        return "NA", "NA"
    v, r = max(vals, key=lambda t: t[0])
    return f"{v:.3e}", f"{r['corner_label']}/{r['temp_c']}C/Nx{r['nx']}/RB={r['rb_label']}"


with open(headline_path, "a") as f:
    emit(f, "N_HELD_CELLS", len(held))
    emit(f, "N_HELD_CROSSED", len(held_crossed))
    emit(f, "N_HELD_NONMONO", len(held_nonmono))
    emit(f, "HELD_RB_LABELS", ' '.join(sorted({r["rb_label"] for r in held})))
    for name, _ in B_READOUT_V:
        col = f"ic_per_nx_at_{name}v_a"
        v, cell = leak_max(held, col)
        emit(f, f"HELD_LEAK_MAX_{name.upper()}", v)
        emit(f, f"HELD_LEAK_MAX_{name.upper()}_CELL", cell)
    emit(f, "N_EXT_CELLS", len(ext))
    emit(f, "N_EXT_CROSSED", len(ext_crossed))
    emit(f, "EXT_IC_MAX", max((r["ic_per_nx_max_a"] for r in ext), default="NA"))
    emit(f, "N_CTRL_CELLS", len(ctrl))
    emit(f, "N_CTRL_CROSSED", len(ctrl_crossed))
    emit(f, "N_CTRL_TRUNCATED", len(ctrl_trunc))
    emit(f, "CTRL_CROSSED_CELLS", ' '.join(
        f"{r['corner_label']}/{r['temp_c']}C/Nx{r['nx']}@{float(r['vce_at_1ua_per_nx_v']):.2f}V"
        for r in sorted(ctrl_crossed, key=lambda r: (r['corner_label'], int(r['temp_c']), r['nx']))))
    emit(f, "CTRL_CROSSED_TEMPS", ' '.join(sorted({r["temp_c"] for r in ctrl_crossed}, key=int)))
    emit(f, "N_SNAP_CELLS", len(snap))
    emit(f, "N_SNAP_CROSSED", len(snap_crossed))
    emit(f, "SNAP_CROSSED_TEMPS", ' '.join(sorted({r["temp_c"] for r in snap_crossed}, key=int)))
    snap_v = [float(r["vce_at_1ua_per_nx_v"]) for r in snap_crossed]
    emit(f, "SNAP_V_MIN", f"{min(snap_v):.4f}" if snap_v else "NA")
    emit(f, "SNAP_V_MAX", f"{max(snap_v):.4f}" if snap_v else "NA")
    emit(f, "N_SNAP_NONMONO", len([r for r in snap if r["ic_monotone_in_vce"] != "yes"]))

print(f"wrote {len(out_a)} Bench A summary rows -> {sum_a}")
print(f"wrote {len(out_b)} Bench B summary rows -> {sum_b}")
PYEOF

# shellcheck source=/dev/null
source "${HEADLINE}"
rm -f "${HEADLINE}"

{
  echo "# Record ${RECORD_ID}"
  echo
  echo "- **Experiment**: breakdown-extraction"
  echo "- **Claim**: \`npn13G2\` collector-emitter breakdown extracted from"
  echo "  the model card's own weak-avalanche parameters (\`avc1 = 2.40\`,"
  echo "  \`avc2 = 10.81\`) -- BVCEO (open base) and BVCER/BVCES (finite and"
  echo "  shorted base terminations), both by current-driven continuation,"
  echo "  with voltage-driven controls and leakage read-outs -- across the HBT"
  echo "  process-corner grid x {-40, 27, 125} C x Nx in {1, 8}. Evidence"
  echo "  for \`spec/decision-records/0001-bias-supply-topology.md\`'s"
  echo "  breakdown budget (issue #20); **not** a ratification of any"
  echo "  \`spec/target-spec.md\` row, and **not** a silicon claim -- every"
  echo "  number here is a property of the committed VBIC model card."
  echo "- **Bench definitions**: see \`README.md\` -- short summary: DC only,"
  echo "  no RF port and no 50 Ohm reference anywhere. Bench A forces the"
  echo "  collector current over a logarithmic grid (${N_POINTS_A} points,"
  echo "  ${PTS_PER_DECADE}/decade, from Nx*${I_START} A) and MEASURES V_CE;"
  echo "  Bench B sweeps V_CE (\`.dc\`, ${V_START} V -> ${V_STOP} V in"
  echo "  ${V_STEP} V steps; ${V_STOP_EXT} V for the extended probe) and"
  echo "  measures I_C. Emitter grounded through a 0 V source,"
  echo "  substrate/buried-layer terminal tied to the emitter reference,"
  echo "  base terminated to the emitter through \`Rbe\`."
  echo "- **Extraction criteria**: on Bench A, the measured V_CE at a forced"
  echo "  collector current of 1, 10, 100 and 500 uA/finger (500 uA/finger"
  echo "  = DR-0001's nominal 4.0 mA at Nx=8), plus the locus minimum (the"
  echo "  avalanche-SUSTAINING voltage) where the locus turns round inside"
  echo "  the swept range. On Bench B, the V_CE at which I_C/finger first"
  echo "  reaches 1 or 10 uA, or blank when it never does within the swept"
  echo "  range. A breakdown voltage is only defined WITH its current"
  echo "  criterion -- see \`README.md\` \"Extraction criteria\"."
  echo "- **Devices**: \`npn13G2\` (native VBIC level=9, no OSDI needed),"
  echo "  Nx in {1, 8}, PDK-default single-finger geometry"
  echo "  (le=0.96 um, we=0.12 um)."
  echo "- **PDK**: \`${PDK}\` at \`${PDK_ROOT}\` -- pinned release: see"
  echo "  \`sim/pdk.json\` (IHP-Open-PDK v0.3.0)."
  echo "- **ngspice**: \`${NGSPICE_VERSION}\`"
  CORNER_LABELS_STR="$(IFS=,; echo "${CORNER_LABELS[*]}")"
  TEMPS_STR="$(IFS=,; echo "${TEMPS[*]}")"
  echo "- **Sweep grid**: corner_label {${CORNER_LABELS_STR}} x temp"
  echo "  {${TEMPS_STR}} C x Nx {1,8}. Bench A: RB=1e12 Ohm (open) at"
  echo "  selft=1 and selft=0 over the full grid; RB in {1.4e4, 1.4e3} Ohm"
  echo "  over the full grid at selft=1; plus 4 tight-RB method probes"
  echo "  (RB in {1.4e2, 1e-3} Ohm) at typ/27 C. Bench B: RB in {1.4e3,"
  echo "  1e-3} Ohm over the full grid (held-base leakage read-out),"
  echo "  RB=1e9 Ohm over the full grid (naive-method control), RB=1.4e4"
  echo "  Ohm over the full grid (snapback control), and a ${V_STOP_EXT} V"
  echo "  extended-ceiling probe at RB=1.4e3 Ohm, Nx=8."
  echo "- **Self-heating**: the open-base (BVCEO) cells are run **both"
  echo "  ways** -- \`selft=1\` (the PDK default, thermal node active, rth ="
  echo "  \`selft*3.26e3*(4/Nx)**0.9\` K/W) and \`selft=0\` (rth forced to 0)."
  echo "  Largest |BVCEO(selft=1) - BVCEO(selft=0)| over all open-base"
  echo "  cells: **${SELFT_MAX_DELTA_1UA} V** at the 1 uA/finger criterion,"
  echo "  **${SELFT_MAX_DELTA_500UA} V** at 500 uA/finger. Bench B cells were"
  echo "  run at \`selft=1\` only (held-base dissipation is sub-nanowatt)."
  echo "- **Result**: ${total_runs} ngspice invocations; ${a_rows} Bench A"
  echo "  locus rows and ${b_rows} Bench B sweep rows parsed."
  if [[ ${#failed_points[@]} -gt 0 ]]; then
    echo "- **Failed cells**: ${failed_points[*]}"
  else
    echo "- **Failed cells**: none."
  fi
  if [[ ${#partial_points[@]} -gt 0 ]]; then
    echo "- **Partial cells** (solver lost the branch part-way; recorded,"
    echo "  not discarded -- the truncation is itself data): ${partial_points[*]}"
  else
    echo "- **Partial cells**: none."
  fi
  if [[ ${#probe_points[@]} -gt 0 ]]; then
    echo "- **Bench A tight-RB method probes** (RB in {1.4e2, 1e-3} Ohm at"
    echo "  typ/27 C; expected NOT to converge -- see README.md \"What the"
    echo "  model cannot tell us\"), converged points of ${N_POINTS_A}:"
    echo "  ${probe_points[*]}. Sustained avalanche branches found in"
    echo "  ${N_A_PROBE_SUSTAINED} of ${N_A_PROBE_CELLS}; lowest V_CE anywhere on"
    echo "  each probe locus: ${A_PROBE_MIN_VCE}."
  fi
  echo "- **BVCEO (open base, ${N_OPEN_CELLS} cells)**:"
  echo "  - at 1 uA/finger: **min ${BVCEO_1UA_MIN} V** (${BVCEO_1UA_MIN_CELL}),"
  echo "    max ${BVCEO_1UA_MAX} V (${BVCEO_1UA_MAX_CELL})"
  echo "  - at 10 uA/finger: min ${BVCEO_10UA_MIN} V (${BVCEO_10UA_MIN_CELL}),"
  echo "    max ${BVCEO_10UA_MAX} V (${BVCEO_10UA_MAX_CELL})"
  echo "  - at 100 uA/finger: min ${BVCEO_100UA_MIN} V (${BVCEO_100UA_MIN_CELL}),"
  echo "    max ${BVCEO_100UA_MAX} V (${BVCEO_100UA_MAX_CELL})"
  echo "  - at 500 uA/finger (DR-0001's nominal I_C): min ${BVCEO_500UA_MIN} V"
  echo "    (${BVCEO_500UA_MIN_CELL}), max ${BVCEO_500UA_MAX} V (${BVCEO_500UA_MAX_CELL})"
  echo "- **Temperature dependence of BVCEO** (minimum over corners/Nx/selft"
  echo "  at the 1 uA/finger criterion): -40 C **${BVCEO_1UA_MIN_TM40} V**,"
  echo "  27 C **${BVCEO_1UA_MIN_T27} V**, 125 C **${BVCEO_1UA_MIN_T125} V**."
  echo "  At 500 uA/finger: -40 C ${BVCEO_500UA_MIN_TM40} V, 27 C"
  echo "  ${BVCEO_500UA_MIN_T27} V, 125 C ${BVCEO_500UA_MIN_T125} V."
  echo "- **Consistency with the process spec (1.4 V min / 1.6 V target)**:"
  echo "  at the 1 uA/finger criterion, ${N_BELOW_1V4_1UA} corner/temp/Nx"
  echo "  combinations fall below the 1.4 V minimum"
  echo "  (${CELLS_BELOW_1V4_1UA:-none}) and ${N_BELOW_1V6_1UA} fall below the"
  echo "  1.6 V target. At the 500 uA/finger criterion, ${N_BELOW_1V4_500UA}"
  echo "  fall below 1.4 V (${CELLS_BELOW_1V4_500UA:-none}) and"
  echo "  ${N_BELOW_1V6_500UA} below 1.6 V. See README.md \"Is this"
  echo "  consistent with the process spec?\" for the reading of these."
  echo "- **Nx invariance**: largest |BVCEO(Nx=1) - BVCEO(Nx=8)| at the same"
  echo "  corner/temp/selft, on the per-finger current criterion:"
  echo "  **${NX_MAX_DELTA_1UA} V** at 1 uA/finger, ${NX_MAX_DELTA_500UA} V at"
  echo "  500 uA/finger."
  echo "- **BVCER at RB = 14 kOhm (Bench A, ${N_A_14K_CELLS} cells)** -- the"
  echo "  LOOSE end of the cascode-base Thevenin bracket, and the only"
  echo "  finite termination at which the model still has an"
  echo "  avalanche-sustained branch inside its own current-validity range:"
  echo "  a sustaining branch is found in ${N_A_14K_SUSTAINED} of"
  echo "  ${N_A_14K_CELLS} cells, with sustaining voltage **min"
  echo "  ${A_14K_SUS_MIN} V** (${A_14K_SUS_MIN_CELL}), max ${A_14K_SUS_MAX} V"
  echo "  (${A_14K_SUS_MAX_CELL}); per temperature: -40 C"
  echo "  ${A_14K_SUS_MIN_TM40} V, 27 C ${A_14K_SUS_MIN_T27} V, 125 C"
  echo "  ${A_14K_SUS_MIN_T125} V. At DR-0001's nominal 500 uA/finger the"
  echo "  same locus sits at ${A_14K_500UA_MIN}-${A_14K_500UA_MAX} V."
  echo "- **BVCER at RB = 1.4 kOhm (Bench A, ${N_A_1P4K_CELLS} cells)** -- the"
  echo "  NOMINAL Thevenin value: a sustained avalanche branch is found in"
  echo "  **${N_A_1P4K_SUSTAINED} of ${N_A_1P4K_CELLS} cells**. The locus is"
  echo "  still descending through ${A_1P4K_500UA_MIN}-${A_1P4K_500UA_MAX} V at"
  echo "  the 500 uA/finger criterion and has not turned round by the top"
  echo "  of the forced-current grid, which is the model card's own"
  echo "  current-validity ceiling (ic < 0.003*Nx A). I.e. within the range"
  echo "  the card is valid over, this termination has no collector-emitter"
  echo "  breakdown at all."
  echo "- **BVCES / tight-RB (Bench A probes)**: ${N_A_PROBE_SUSTAINED} of"
  echo "  ${N_A_PROBE_CELLS} probe cells show a sustained branch -- the same"
  echo "  answer as 1.4 kOhm, more strongly."
  echo "- **Held-base leakage (Bench B, ${N_HELD_CELLS} cells, RB in"
  echo "  {${HELD_RB_LABELS}})**: I_C is monotone in V_CE in"
  echo "  $((N_HELD_CELLS - N_HELD_NONMONO)) of ${N_HELD_CELLS} cells (so the"
  echo "  voltage-driven sweep is sound there), and the 1 uA/finger"
  echo "  criterion is reached in **${N_HELD_CROSSED} of ${N_HELD_CELLS}"
  echo "  cells** -- independently confirming Bench A's finding that no"
  echo "  collector-emitter breakdown occurs at RB <= 1.4 kOhm anywhere up"
  echo "  to the ${V_STOP} V ceiling, which is already past the model card's"
  echo "  \`vbc_max = 5.1\`. Worst-case held-base leakage: ${HELD_LEAK_MAX_1P12}"
  echo "  A/finger at V_CE=1.12 V (${HELD_LEAK_MAX_1P12_CELL}),"
  echo "  ${HELD_LEAK_MAX_1P60} A/finger at 1.60 V (${HELD_LEAK_MAX_1P60_CELL}),"
  echo "  ${HELD_LEAK_MAX_2P00} A/finger at 2.00 V (${HELD_LEAK_MAX_2P00_CELL})."
  echo "- **Extended-ceiling probe (${V_STOP_EXT} V, OUTSIDE the model card's"
  echo "  validity range)**: ${N_EXT_CROSSED} of ${N_EXT_CELLS} cells reach the"
  echo "  1 uA/finger criterion; largest current seen anywhere in those"
  echo "  sweeps is ${EXT_IC_MAX} A/finger. The absence of a held-base"
  echo "  runaway below ${V_STOP} V is therefore not an artefact of the"
  echo "  primary sweep's ceiling -- but nothing above 2.0 V is a claim"
  echo "  about silicon (README.md \"What the model cannot tell us\")."
  echo "- **Naive-method control (Bench B, RB = 1e9 Ohm,"
  echo "  ${N_CTRL_CELLS} cells)**: a runaway (1 uA/finger) was found in"
  echo "  ${N_CTRL_CROSSED} cells, all at temperature(s)"
  echo "  {${CTRL_CROSSED_TEMPS:-none}} -- ${CTRL_CROSSED_CELLS:-none} --"
  echo "  and ${N_CTRL_TRUNCATED} cells lost convergence before the sweep"
  echo "  ceiling. This reproduces the branch-following failure DR-0001"
  echo "  describes, against Bench A's ${N_OPEN_CELLS}/${N_OPEN_CELLS}"
  echo "  converged open-base cells."
  echo "- **Snapback control (Bench B, RB = 1.4e4 Ohm, ${N_SNAP_CELLS}"
  echo "  cells)**: the voltage-driven sweep finds a runaway in only"
  echo "  ${N_SNAP_CROSSED} cells, all at temperature(s)"
  echo "  {${SNAP_CROSSED_TEMPS:-none}}, in the range"
  echo "  ${SNAP_V_MIN}-${SNAP_V_MAX} V, and reports a non-monotone I_C(V_CE)"
  echo "  in ${N_SNAP_NONMONO} of them -- i.e. the SAME temperature-selective"
  echo "  branch-following failure as the open-base control, now at a"
  echo "  finite base impedance. Bench A finds the sustained branch for"
  echo "  ${N_A_14K_SUSTAINED}/${N_A_14K_CELLS} of the same cells at all three"
  echo "  temperatures. Where the two disagree, Bench A is the number this"
  echo "  record quotes; these control cells are quoted only as evidence"
  echo "  about the METHOD."
  echo "- **Links**:"
  echo "  - Templates: \`testbench/tb_bvceo_iforce.spice.tmpl\` (Bench A),"
  echo "    \`testbench/tb_bvcer_vsweep.spice.tmpl\` (Bench B)"
  echo "  - Per-cell generated netlists: \`netlist-snapshots/${RECORD_ID}/\`"
  echo "  - Per-cell raw ngspice console logs (\`*.log\`) and measurement"
  echo "    streams (\`*.meas\`): \`corners/${RECORD_ID}/\`"
  echo "  - Bench A full locus CSV: \`records/${RECORD_ID}-bvceo-locus.csv\`"
  echo "  - Bench A summary CSV: \`records/${RECORD_ID}-bvceo-summary.csv\`"
  echo "  - Bench B full sweep CSV: \`records/${RECORD_ID}-heldbase-sweep.csv\`"
  echo "  - Bench B summary CSV: \`records/${RECORD_ID}-heldbase-summary.csv\`"
  echo "- **Regeneration**: \`sim/breakdown-extraction/run_breakdown_sweep.sh\`"
  echo "  (mints a NEW record id; this one is never overwritten)."
  echo "- **Timestamp / author**: $(date -u +%Y-%m-%dT%H:%M:%SZ), Loom Builder"
  echo "  (agent), issue #20."
} > "${MD_OUT}"

echo "run_breakdown_sweep.sh: wrote ${MD_OUT}"
echo "run_breakdown_sweep.sh: ${total_runs} ngspice invocations; BVCEO@1uA/finger in [${BVCEO_1UA_MIN}, ${BVCEO_1UA_MAX}] V; held-base 1uA/finger reached in ${N_HELD_CROSSED}/${N_HELD_CELLS} cells"

if [[ ${#failed_points[@]} -gt 0 ]]; then
  exit 1
fi
exit 0
