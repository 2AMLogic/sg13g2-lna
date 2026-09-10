#!/usr/bin/env bash
# Cold-start invocation:
#
#   export PDK_ROOT=/path/to/ihp-open-pdk   # parent dir containing ihp-sg13g2/
#   export PDK=ihp-sg13g2
#   sim/hbt-characterization/run_hbt_sweep.sh
#
# (PDK_ROOT/PDK may also be left unset if the PDK is installed under one of
# the usual prefixes sim/env.sh checks.) Requires ngspice on PATH; does not
# require xschem, klt, or an OSDI build step (npn13G2 is a native ngspice
# VBIC model -- see sim/pdk.json). Full methodology, bench definitions and
# what this sweep measures and does not are documented in
# sim/hbt-characterization/README.md and sim/pdk.json -- read those first
# if a result here looks surprising.
#
# Sweeps npn13G2 (Nx=1, the PDK's default single-finger emitter, plus one
# larger Nx=8 area-scaling spot check at the tt/27C/Vce=1.0V point) over a
# dense base-voltage grid (26 points, 0.55V-1.05V in 0.02V steps -- chosen
# to comfortably straddle this device's fT-peak current density,
# calibrated empirically, see README.md "Sweep grid derivation") x
# Vce in {0.8, 1.0, 1.2, 1.4} V x the HBT process-corner grid (5 labels
# mapped onto cornerHBT.lib's 3 real sections, see sim/README.md "Corner
# label convention") x temperature {-40, 27, 125} C, computing at each
# point: J_C (from the swept branch's own measured Ic), fT (short-circuit
# h21 0 dB crossing), 50 Ohm-terminated transducer gain at 2.4 GHz, and
# 50 Ohm-referenced NF at 2.4 GHz. Writes append-only evidence under
# corners/<record-id>/, netlist-snapshots/<record-id>/ and
# records/<record-id>.{csv,md} -- see sim/README.md for the convention
# this follows (sg13g2-opamp/sim/gm-id-characterization/ is the structural
# precedent for the render-deck -> ngspice -b -> parse -> CSV+record
# shape).
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SIM_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
REPO_ROOT="$(cd "${SIM_DIR}/.." && pwd)"

# shellcheck source=/dev/null
source "${SIM_DIR}/env.sh"

if [[ -z "${PDK_ROOT:-}" || ! -d "${PDK_ROOT}/${PDK}/libs.tech/ngspice" ]]; then
  echo "run_hbt_sweep.sh: no resolvable ${PDK:-ihp-sg13g2} install -- see sim/env.sh output above." >&2
  exit 3
fi

command -v ngspice >/dev/null 2>&1 || { echo "run_hbt_sweep.sh: ngspice not on PATH." >&2; exit 3; }
NGSPICE_VERSION="$(ngspice -v 2>&1 | sed -n '2p')"

MODELS_LIB="${PDK_ROOT}/${PDK}/libs.tech/ngspice/models/cornerHBT.lib"
if [[ ! -f "${MODELS_LIB}" ]]; then
  echo "run_hbt_sweep.sh: cornerHBT.lib not found at ${MODELS_LIB}" >&2
  exit 3
fi

REPO_GIT_SHA="$(cd "${REPO_ROOT}" && git rev-parse --short HEAD 2>/dev/null || echo unknown)"
RECORD_ID="$(date -u +%Y%m%d-%H%M%S)-${REPO_GIT_SHA}"

EXPERIMENT_DIR="${SCRIPT_DIR}"
SNAPSHOTS_OUT="${EXPERIMENT_DIR}/netlist-snapshots/${RECORD_ID}"
CORNERS_OUT="${EXPERIMENT_DIR}/corners/${RECORD_ID}"
RECORDS_DIR="${EXPERIMENT_DIR}/records"
CSV_RAW="${RECORDS_DIR}/${RECORD_ID}.raw.csv"
CSV_OUT="${RECORDS_DIR}/${RECORD_ID}.csv"
SUMMARY_OUT="${RECORDS_DIR}/${RECORD_ID}-summary.csv"
MD_OUT="${RECORDS_DIR}/${RECORD_ID}.md"
mkdir -p "${SNAPSHOTS_OUT}" "${CORNERS_OUT}" "${RECORDS_DIR}"

# --- Sweep grid ----------------------------------------------------------
# Corner labels mirror cornerMOShv.lib's five-label convention (for
# fleet-wide consistency), mapped onto cornerHBT.lib's three REAL sections
# -- see sim/README.md "Corner label convention" for the discrepancy this
# resolves (target-spec.md/porting-plan.md describe five HBT sections;
# the installed PDK ships three). sf/fs fall back to hbt_typ, the same
# convention sg13g2-bandgap's HBT_SECTION_OF map already uses.
CORNER_LABELS=(typ bcs wcs sf fs)
declare -A HBT_SECTION_OF=( [typ]=hbt_typ [bcs]=hbt_bcs [wcs]=hbt_wcs [sf]=hbt_typ [fs]=hbt_typ )
TEMPS=(-40 27 125)
VCES=(0.8 1.0 1.2 1.4)
VBE_START="0.55"
VBE_STEP="0.02"
N_POINTS=26
# Device area (um^2) for J_C = Ic / (Nx * AE_UNIT_UM2): the subckt's own
# default single-finger geometry (le=0.96um, we=0.12um -- see
# sg13g2_hbt_mod.lib's npn13G2 subckt .param block), Nx-multiplied.
AE_UNIT_UM2="0.1152"

echo "point_id,corner_label,hbt_section,temp_c,nx,vce_v,vbe_v,ic_a,jc_ma_um2,ft_hz,gain_db,nf_db" > "${CSV_RAW}"

total=0
failed_points=()

run_one() {
  local corner_label="$1" hbt_section="$2" temp="$3" nx="$4" vce="$5"
  local point_id="nx${nx}_${corner_label}_${temp}c_vce${vce}v"
  local netlist="${SNAPSHOTS_OUT}/${point_id}.spice"
  local log="${CORNERS_OUT}/${point_id}.log"

  sed \
    -e "s|@@MODELS_LIB@@|${MODELS_LIB}|g" \
    -e "s|@@HBT_SECTION@@|${hbt_section}|g" \
    -e "s|@@TEMP@@|${temp}|g" \
    -e "s|@@NX@@|${nx}|g" \
    -e "s|@@VCE@@|${vce}|g" \
    -e "s|@@VBE_START@@|${VBE_START}|g" \
    -e "s|@@VBE_STEP@@|${VBE_STEP}|g" \
    -e "s|@@N_POINTS@@|${N_POINTS}|g" \
    "${EXPERIMENT_DIR}/testbench/tb_hbt_sweep.spice.tmpl" > "${netlist}"

  total=$((total + 1))
  rc=0
  ngspice -b "${netlist}" > "${log}" 2>&1 || rc=$?

  # "singular matrix" is deliberately NOT in this pattern: ngspice prints
  # it routinely as a diagnostic during its own dynamic-gmin-stepping
  # convergence aid (near cutoff, where Ib2's op point is hardest to find)
  # even on a run that ultimately succeeds -- confirmed empirically (every
  # such log below still completes all N_POINTS points and ends with
  # "Simulation executed from .control section"). A genuine failure is
  # instead caught by the completeness check below: fewer than N_POINTS
  # "PT " markers, or a missing end-of-control-script marker, means the
  # batch aborted partway through.
  n_pt_lines=$(grep -c "^PT " "${log}" || true)
  if [[ ${rc} -ne 0 ]] \
    || grep -qiE "Unable to find definition of model|couldn't be loaded|Unknown model type|fatal error" "${log}" \
    || ! grep -q "Simulation executed from .control section" "${log}" \
    || [[ "${n_pt_lines}" -lt "${N_POINTS}" ]]; then
    echo "run_hbt_sweep.sh: FAILED ${point_id} (rc=${rc}, PT lines=${n_pt_lines}/${N_POINTS}) -- see ${log}" >&2
    failed_points+=("${point_id}")
    return
  fi

  # Parse the PT/IC/FT/GAIN/NF echo sequence, one point per 5-line block
  # (see testbench header "NOTE ON EXECUTION ORDER" for why the order is
  # fixed and each value is echoed immediately after its own analysis).
  awk -v corner="${corner_label}" -v section="${hbt_section}" -v temp="${temp}" \
      -v nx="${nx}" -v vce="${vce}" -v point_id="${point_id}" -v ae="${AE_UNIT_UM2}" '
    /^PT / { vbe=$2; ic=""; ft=""; gain=""; nf=""; next }
    /^IC / { ic=$2; next }
    /^FT / { ft=$2; next }
    /^GAIN / { gain=$2; next }
    /^NF / {
      nf=$2
      if (ic != "" && gain != "" && nf != "") {
        jc = (ic+0) * 1000.0 / (nx * ae)
        ftout = (ft == "NA") ? "" : ft
        printf "%s,%s,%s,%s,%s,%s,%s,%.6e,%.6f,%s,%.6f,%.6f\n", point_id, corner, section, temp, nx, vce, vbe, ic+0, jc, ftout, gain+0, nf+0
      }
      next
    }
  ' "${log}" >> "${CSV_RAW}"
}

# --- Main grid: Nx=1 across the full corner x temp x Vce grid ---
for corner_label in "${CORNER_LABELS[@]}"; do
  hbt_section="${HBT_SECTION_OF[${corner_label}]}"
  for temp in "${TEMPS[@]}"; do
    for vce in "${VCES[@]}"; do
      run_one "${corner_label}" "${hbt_section}" "${temp}" 1 "${vce}"
    done
  done
done

# --- Area-scaling spot check: Nx=8 at the nominal point only (tt/27C,
# Vce=1.0V) -- issue #7 scope: "plus one larger emitter-area/multiplicity
# so area scaling is visible", not a second full grid. ---
run_one "typ" "hbt_typ" "27" 8 "1.0"

n_data_rows=$(($(wc -l < "${CSV_RAW}") - 1))
if [[ ${n_data_rows} -le 0 ]]; then
  echo "run_hbt_sweep.sh: no points produced any data -- refusing to write a summary." >&2
  exit 1
fi

mv "${CSV_RAW}" "${CSV_OUT}"

# --- Summary: per (corner_label, temp, vce, nx) group, the noise-optimum
# J_C (minimum NF) and its fT/gain, plus the group's own fT peak J_C. ---
python3 - "${CSV_OUT}" "${SUMMARY_OUT}" <<'PYEOF'
import csv, sys
from collections import defaultdict

src, dst = sys.argv[1], sys.argv[2]
rows = list(csv.DictReader(open(src)))

groups = defaultdict(list)
for r in rows:
    key = (r["corner_label"], r["temp_c"], r["nx"], r["vce_v"])
    groups[key].append(r)

out_rows = []
for key, pts in sorted(groups.items(), key=lambda kv: (kv[0][2], kv[0][0], int(kv[0][1]), float(kv[0][3]))):
    corner, temp, nx, vce = key
    # Noise-optimum: minimum NF among points with a valid measurement.
    nf_pts = [p for p in pts if p["nf_db"] not in ("", None)]
    if not nf_pts:
        continue
    best_nf = min(nf_pts, key=lambda p: float(p["nf_db"]))
    # fT peak: among points with a valid (non-blank) fT.
    ft_pts = [p for p in pts if p["ft_hz"] not in ("", None)]
    best_ft = max(ft_pts, key=lambda p: float(p["ft_hz"])) if ft_pts else None
    out_rows.append({
        "corner_label": corner, "temp_c": temp, "nx": nx, "vce_v": vce,
        "n_points": len(pts),
        "noise_optimum_jc_ma_um2": f"{float(best_nf['jc_ma_um2']):.4f}",
        "noise_optimum_nf_db": f"{float(best_nf['nf_db']):.4f}",
        "noise_optimum_gain_db": f"{float(best_nf['gain_db']):.4f}",
        "noise_optimum_ft_hz": best_nf["ft_hz"] if best_nf["ft_hz"] else "",
        "ft_peak_jc_ma_um2": f"{float(best_ft['jc_ma_um2']):.4f}" if best_ft else "",
        "ft_peak_hz": f"{float(best_ft['ft_hz']):.4e}" if best_ft else "",
    })

with open(dst, "w", newline="") as f:
    w = csv.DictWriter(f, fieldnames=[
        "corner_label", "temp_c", "nx", "vce_v", "n_points",
        "noise_optimum_jc_ma_um2", "noise_optimum_nf_db", "noise_optimum_gain_db",
        "noise_optimum_ft_hz", "ft_peak_jc_ma_um2", "ft_peak_hz",
    ])
    w.writeheader()
    w.writerows(out_rows)
print(f"wrote {len(out_rows)} summary rows -> {dst}")
PYEOF

# --- Overall noise-optimum across the whole grid, and the binding-corner
# (wcs/125C per target-spec.md's expected NF binding corner) row, for the
# record's own narrative. ---
OVERALL_BEST=$(python3 - "${CSV_OUT}" <<'PYEOF'
import csv, sys
rows = [r for r in csv.DictReader(open(sys.argv[1])) if r["nf_db"] not in ("", None) and r["nx"] == "1"]
best = min(rows, key=lambda r: float(r["nf_db"]))
print(f"{best['corner_label']},{best['temp_c']},{best['vce_v']},{best['jc_ma_um2']},{best['nf_db']},{best['gain_db']},{best['ft_hz']}")
PYEOF
)
IFS=',' read -r BEST_CORNER BEST_TEMP BEST_VCE BEST_JC BEST_NF BEST_GAIN BEST_FT <<< "${OVERALL_BEST}"

BINDING_BEST=$(python3 - "${CSV_OUT}" <<'PYEOF'
import csv, sys
rows = [r for r in csv.DictReader(open(sys.argv[1])) if r["nf_db"] not in ("", None) and r["nx"] == "1" and r["corner_label"] == "wcs" and r["temp_c"] == "125"]
if not rows:
    print(",,,,")
else:
    best = min(rows, key=lambda r: float(r["nf_db"]))
    print(f"{best['vce_v']},{best['jc_ma_um2']},{best['nf_db']},{best['gain_db']},{best['ft_hz']}")
PYEOF
)
IFS=',' read -r BINDING_VCE BINDING_JC BINDING_NF BINDING_GAIN BINDING_FT <<< "${BINDING_BEST}"

n_data_rows=$(($(wc -l < "${CSV_OUT}") - 1))

{
  echo "# Record ${RECORD_ID}"
  echo
  echo "- **Experiment**: hbt-characterization"
  echo "- **Claim**: \`npn13G2\` fT (short-circuit h21 0 dB crossing), 50"
  echo "  Ohm-referenced NF at 2.4 GHz, and 50 Ohm-terminated transducer"
  echo "  gain at 2.4 GHz, vs collector current density J_C (swept via a"
  echo "  dense base-voltage grid) and Vce in {0.8, 1.0, 1.2, 1.4} V,"
  echo "  across the HBT process-corner grid x {-40, 27, 125} C. Nx=1 (the"
  echo "  PDK default single-finger emitter) across the full grid, plus an"
  echo "  Nx=8 area-scaling spot check at typ/27C/Vce=1.0V. Device-level"
  echo "  input to the still-open bias/supply-topology decision record"
  echo "  (\`spec/target-spec.md\` 'Open topology question') -- not the"
  echo "  decision itself, and not a claim against any \`target-spec.md\`"
  echo "  row (none are ratified)."
  echo "- **Bench definitions**: see \`README.md\` 'Bench definitions' --"
  echo "  short summary: fT from an ideal short-circuit h21 AC sweep"
  echo "  (current-source base drive, ideal-voltage-source collector"
  echo "  short); gain/NF from an ideal 50 Ohm source + 50 Ohm load with"
  echo "  ideal bias tees, NF referenced to a fixed 300.15 K source"
  echo "  temperature (Friis/IEEE convention) independent of the swept"
  echo "  ambient corner."
  echo "- **Devices**: \`npn13G2\` (native VBIC level=9, no OSDI needed),"
  echo "  Nx=1 (+ Nx=8 spot check), emitter area \`AE_UNIT_UM2\`=${AE_UNIT_UM2} um^2 per finger."
  echo "- **PDK**: \`${PDK}\` at \`${PDK_ROOT}\` -- pinned release: see"
  echo "  \`sim/pdk.json\` (IHP-Open-PDK v0.3.0)."
  echo "- **ngspice**: \`${NGSPICE_VERSION}\`"
  CORNER_LABELS_STR="$(IFS=,; echo "${CORNER_LABELS[*]}")"
  TEMPS_STR="$(IFS=,; echo "${TEMPS[*]}")"
  VCES_STR="$(IFS=,; echo "${VCES[*]}")"
  echo "- **Sweep grid**: corner_label {${CORNER_LABELS_STR}} x temp"
  echo "  {${TEMPS_STR}} x Vce {${VCES_STR}} x ${N_POINTS} base-voltage"
  echo "  points (${VBE_START}V + i*${VBE_STEP}V) = $((${#CORNER_LABELS[@]} * ${#TEMPS[@]} * ${#VCES[@]})) grid cells,"
  echo "  ${N_POINTS} points each, plus 1 Nx=8 spot-check cell."
  echo "- **Result**: ${n_data_rows} data rows parsed from ${total} ngspice"
  echo "  invocations (one per corner_label x temp x Vce x nx cell,"
  echo "  internally sweeping all ${N_POINTS} base-voltage points via"
  echo "  \`alter\`+\`dowhile\`)."
  if [[ ${#failed_points[@]} -gt 0 ]]; then
    echo "- **Failed cells**: ${failed_points[*]}"
  fi
  echo "- **Noise-optimum (whole grid, Nx=1)**: J_C=${BEST_JC} mA/um^2 at"
  echo "  corner=${BEST_CORNER}, ${BEST_TEMP} C, Vce=${BEST_VCE} V ->"
  echo "  NF=${BEST_NF} dB, gain=${BEST_GAIN} dB, fT=${BEST_FT} Hz."
  echo "- **Noise-optimum at the binding corner (wcs/125C, per"
  echo "  target-spec.md's expected NF binding corner)**: J_C=${BINDING_JC}"
  echo "  mA/um^2 at Vce=${BINDING_VCE} V -> NF=${BINDING_NF} dB,"
  echo "  gain=${BINDING_GAIN} dB, fT=${BINDING_FT} Hz."
  echo "- **Links**:"
  echo "  - Template: \`testbench/tb_hbt_sweep.spice.tmpl\`"
  echo "  - Per-point generated netlists: \`netlist-snapshots/${RECORD_ID}/\`"
  echo "  - Per-point raw ngspice logs: \`corners/${RECORD_ID}/\`"
  echo "  - Full-sweep CSV: \`records/${RECORD_ID}.csv\`"
  echo "  - Summary CSV (noise-optimum + fT-peak per corner/temp/Vce"
  echo "    cell): \`records/${RECORD_ID}-summary.csv\`"
  echo "- **Timestamp / author**: $(date -u +%Y-%m-%dT%H:%M:%SZ), Loom Builder"
  echo "  (agent), issue #7."
} > "${MD_OUT}"

echo "run_hbt_sweep.sh: wrote ${MD_OUT}, ${CSV_OUT}, ${SUMMARY_OUT}"
echo "run_hbt_sweep.sh: ${n_data_rows} data rows from ${total} ngspice invocations; noise-optimum J_C=${BEST_JC} mA/um^2 (${BEST_CORNER}/${BEST_TEMP}C/Vce=${BEST_VCE}V) -> NF=${BEST_NF} dB"

if [[ ${#failed_points[@]} -gt 0 ]]; then
  exit 1
fi
exit 0
