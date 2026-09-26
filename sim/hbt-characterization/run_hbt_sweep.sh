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
# Sweeps npn13G2 over a dense base-voltage grid (26 points, 0.55V-1.05V in
# 0.02V steps -- chosen to comfortably straddle this device's fT-peak
# current density, calibrated empirically, see README.md "Sweep grid
# derivation") x Vce in {0.6, 0.8, 1.0, 1.2, 1.4} V x the HBT
# process-corner grid (5 labels mapped onto cornerHBT.lib's 3 real
# sections, see sim/README.md "Corner label convention") x temperature
# {-40, 27, 125} C x emitter multiplicity Nx in {1, 8}, computing at each
# point: J_C (from the swept branch's own measured Ic), fT (short-circuit
# h21 0 dB crossing), 50 Ohm-terminated transducer gain at 2.4 GHz, and
# 50 Ohm-referenced NF at 2.4 GHz.
#
# GRID HISTORY (issue #21): the first record in this experiment
# (20260910-200059-7da7038, issue #7) used Vce {0.8, 1.0, 1.2, 1.4} V with
# Nx=1 across the full grid plus a SINGLE Nx=8 spot check at
# typ/27C/Vce=1.0V. spec/decision-records/0001-bias-supply-topology.md
# recommended Nx=8 on that one spot check plus Nx=1 corner deltas, and its
# own worst-case budget reaches Vce1 = 0.54 V -- below that grid's 0.8 V
# floor. This script now runs Nx=8 across the full corner grid and adds a
# Vce = 0.6 V point, so both of DR-0001's named evidence gaps are inside
# the measured grid. The earlier, narrower grid is still reproducible via
# the environment overrides below:
#
#   HBT_VCES="0.8 1.0 1.2 1.4" HBT_NX_LIST="1" sim/.../run_hbt_sweep.sh
#
# Writes append-only evidence under corners/<record-id>/,
# netlist-snapshots/<record-id>/ and records/<record-id>.{csv,md} -- see
# sim/README.md for the convention this follows
# (sg13g2-opamp/sim/gm-id-characterization/ is the structural precedent
# for the render-deck -> ngspice -b -> parse -> CSV+record shape).
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SIM_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"

# shellcheck source-path=SCRIPTDIR
# shellcheck source=../env.sh
source "${SIM_DIR}/env.sh"

# PDK/ngspice preflight (exit 3 on any miss, prefixed with this runner's
# own name) and this run's record id + append-only output dirs. No --osdi:
# npn13G2 is a native ngspice VBIC model, and this bench instantiates
# nothing else.
sim_require_pdk run_hbt_sweep.sh
sim_record_paths

CSV_RAW="${RECORDS_DIR}/${RECORD_ID}.raw.csv"
CSV_OUT="${RECORDS_DIR}/${RECORD_ID}.csv"
SUMMARY_OUT="${RECORDS_DIR}/${RECORD_ID}-summary.csv"
MD_OUT="${RECORDS_DIR}/${RECORD_ID}.md"

# --- Sweep grid ----------------------------------------------------------
# Corner labels mirror cornerMOShv.lib's five-label convention (for
# fleet-wide consistency), mapped onto cornerHBT.lib's three REAL sections
# -- see sim/README.md "Corner label convention" for the discrepancy this
# resolves (target-spec.md/porting-plan.md described five HBT sections
# at the time this grid was recorded; target-spec.md's Verification
# corners section and the installed PDK both give three). sf/fs fall
# back to hbt_typ, the same convention sg13g2-bandgap's HBT_SECTION_OF
# map already uses.
#
# Every axis is overridable from the environment (space-separated) so an
# earlier record's narrower grid stays reproducible without editing this
# file -- see "GRID HISTORY" in the header.
read -r -a CORNER_LABELS <<< "${HBT_CORNERS:-typ bcs wcs sf fs}"
read -r -a TEMPS         <<< "${HBT_TEMPS:--40 27 125}"
read -r -a VCES          <<< "${HBT_VCES:-0.6 0.8 1.0 1.2 1.4}"
read -r -a NX_LIST       <<< "${HBT_NX_LIST:-1 8}"
declare -A HBT_SECTION_OF=( [typ]=hbt_typ [bcs]=hbt_bcs [wcs]=hbt_wcs [sf]=hbt_typ [fs]=hbt_typ )
VBE_START="0.55"
VBE_STEP="0.02"
N_POINTS=26
# Device area (um^2) for J_C = Ic / (Nx * AE_UNIT_UM2): the subckt's own
# default single-finger geometry (le=0.96um, we=0.12um -- see
# sg13g2_hbt_mod.lib's npn13G2 subckt .param block), Nx-multiplied.
AE_UNIT_UM2="0.1152"

# --- Model-card validity box (sg13g2_hbt_mod.lib, "Valid range for model")
#     ic: <(0.003*Nx) A   vbe: (0.65 - 0.96) V   vce: (0.4 - 2.0) V
#     Temp: -40C - +125C  Valid numbers: NX = 1 - 10
# Every swept temperature and every swept Nx below is inside the last two
# by construction; the first three are checked per data row and recorded
# in the CSV's validity_flags column (empty = inside the box). Flagging is
# required by issue #21: DR-0001's device-sizing argument turns on exactly
# this boundary, so a reader must be able to tell in-box rows from
# out-of-box rows without re-deriving the limits.
IC_LIMIT_PER_NX="0.003"
VBE_MIN="0.65"
VBE_MAX="0.96"
VCE_MIN="0.4"
VCE_MAX="2.0"

echo "point_id,corner_label,hbt_section,temp_c,nx,vce_v,vbe_v,ic_a,jc_ma_um2,ft_hz,gain_db,nf_db,validity_flags" > "${CSV_RAW}"

total=0
failed_points=()
partial_points=()

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

  # --- Cell-level (hard) failure -----------------------------------------
  # "singular matrix" is deliberately NOT in this pattern: ngspice prints
  # it routinely as a diagnostic during its own dynamic-gmin-stepping
  # convergence aid (near cutoff, where Ib2's op point is hardest to find)
  # even on a run that ultimately succeeds. A genuine cell-level failure is
  # a model-load error, or a batch that aborted partway through the
  # dowhile loop -- which shows up as fewer than N_POINTS "PT " markers.
  # The presence of all N_POINTS "PT " markers is direct proof the control
  # loop ran to completion; `rc` and the end-of-control-script marker are
  # NOT used as hard-failure criteria any more, because a cell in which a
  # single high-injection point diverges (see the per-point gate below)
  # legitimately ends with rc=1 and no end marker while still carrying
  # good data at every other bias point.
  n_pt_lines=$(grep -c "^PT " "${log}" || true)
  if grep -qiE "Unable to find definition of model|couldn't be loaded|Unknown model type|fatal error" "${log}" \
    || [[ "${n_pt_lines}" -lt "${N_POINTS}" ]]; then
    echo "run_hbt_sweep.sh: FAILED ${point_id} (rc=${rc}, PT lines=${n_pt_lines}/${N_POINTS}) -- see ${log}" >&2
    failed_points+=("${point_id}")
    return
  fi

  # --- Per-point parse + convergence gate + validity-box flagging --------
  # Parse the PT/IC/FT/GAIN/NF echo sequence, one point per 5-line block
  # (see testbench header "NOTE ON EXECUTION ORDER" for why the order is
  # fixed and each value is echoed immediately after its own analysis).
  #
  # A point is DROPPED (not written to the CSV) when ngspice reported an
  # operating-point failure anywhere inside that point's block. This
  # matters at Nx=8: at the cold/fast corner with Vce=1.4V the VBIC
  # electrothermal loop runs away above Vbe ~ 1.0V (Ic > 50 mA into
  # rth = 1747 K/W), the op point diverges to NaN, and ngspice then echoes
  # a STALE gain/NF value carried over from the previous plot -- exactly
  # the cross-plot vector hazard the testbench header warns about. The
  # three markers matched below ("operating point failed", "The operating
  # point could not be simulated successfully", "Timestep too small") do
  # not appear in ANY log of the converged 20260910-200059-7da7038 record,
  # so they are specific to genuine divergence. They are deliberately NOT
  # a blanket /Error:/ match: `Error: measure ftmeas when(WHEN) : out of
  # interval` is the benign "h21 never crosses 0 dB" case, which already
  # has its own handling (blank fT) and whose gain/NF are valid.
  local rows_before rows_after emitted
  rows_before=$(wc -l < "${CSV_RAW}")
  awk -v corner="${corner_label}" -v section="${hbt_section}" -v temp="${temp}" \
      -v nx="${nx}" -v vce="${vce}" -v point_id="${point_id}" -v ae="${AE_UNIT_UM2}" \
      -v iclim="${IC_LIMIT_PER_NX}" -v vbemin="${VBE_MIN}" -v vbemax="${VBE_MAX}" \
      -v vcemin="${VCE_MIN}" -v vcemax="${VCE_MAX}" '
    function bad_number(s) {
      return (s == "" || s ~ /[nN][aA][nN]/ || s ~ /[iI][nN][fF]/)
    }
    /operating point failed|The operating point could not be simulated successfully|Timestep too small/ {
      diverged = 1; next
    }
    /^PT / { vbe=$2; ic=""; ft=""; gain=""; nf=""; diverged=0; next }
    /^IC / { ic=$2; next }
    /^FT / { ft=$2; next }
    /^GAIN / { gain=$2; next }
    /^NF / {
      nf=$2
      if (!diverged && !bad_number(ic) && !bad_number(gain) && !bad_number(nf)) {
        jc = (ic+0) * 1000.0 / (nx * ae)
        ftout = (ft == "NA" || ft ~ /[nN][aA][nN]/) ? "" : ft
        flags = ""
        if ((ic+0) >= (iclim+0) * nx)          flags = flags (flags ? ";" : "") "ic_high"
        if ((vbe+0) <  (vbemin+0) - 1e-9)      flags = flags (flags ? ";" : "") "vbe_low"
        if ((vbe+0) >  (vbemax+0) + 1e-9)      flags = flags (flags ? ";" : "") "vbe_high"
        if ((vce+0) <  (vcemin+0) - 1e-9)      flags = flags (flags ? ";" : "") "vce_low"
        if ((vce+0) >  (vcemax+0) + 1e-9)      flags = flags (flags ? ";" : "") "vce_high"
        printf "%s,%s,%s,%s,%s,%s,%s,%.6e,%.6f,%s,%.6f,%.6f,%s\n", point_id, corner, section, temp, nx, vce, vbe, ic+0, jc, ftout, gain+0, nf+0, flags
      }
      next
    }
  ' "${log}" >> "${CSV_RAW}"
  rows_after=$(wc -l < "${CSV_RAW}")
  emitted=$((rows_after - rows_before))

  if [[ "${emitted}" -eq 0 ]]; then
    echo "run_hbt_sweep.sh: FAILED ${point_id} (rc=${rc}, every bias point diverged) -- see ${log}" >&2
    failed_points+=("${point_id}")
  elif [[ "${emitted}" -lt "${N_POINTS}" ]]; then
    echo "run_hbt_sweep.sh: PARTIAL ${point_id} (${emitted}/${N_POINTS} bias points converged) -- see ${log}" >&2
    partial_points+=("${point_id}:${emitted}/${N_POINTS}")
  elif [[ ${rc} -ne 0 ]] || ! grep -q "Simulation executed from .control section" "${log}"; then
    # All N_POINTS points parsed clean, yet ngspice still exited non-zero
    # or never printed its end-of-control marker: unexplained, so it is
    # NOT quietly accepted.
    echo "run_hbt_sweep.sh: FAILED ${point_id} (rc=${rc}, ${emitted}/${N_POINTS} points parsed but no end-of-control marker) -- see ${log}" >&2
    failed_points+=("${point_id}")
  fi
}

# --- Main grid: every Nx across the full corner x temp x Vce grid ---
for nx in "${NX_LIST[@]}"; do
  for corner_label in "${CORNER_LABELS[@]}"; do
    hbt_section="${HBT_SECTION_OF[${corner_label}]}"
    for temp in "${TEMPS[@]}"; do
      for vce in "${VCES[@]}"; do
        run_one "${corner_label}" "${hbt_section}" "${temp}" "${nx}" "${vce}"
      done
    done
  done
done

n_data_rows=$(($(wc -l < "${CSV_RAW}") - 1))
if [[ ${n_data_rows} -le 0 ]]; then
  echo "run_hbt_sweep.sh: no points produced any data -- refusing to write a summary." >&2
  exit 1
fi

mv "${CSV_RAW}" "${CSV_OUT}"

# --- Summary: per (corner_label, temp, nx, vce) group, the noise-optimum
# J_C (minimum NF) and its fT/gain, plus the group's own fT peak J_C --
# each reported BOTH over all converged points and restricted to points
# inside the model card's validity box (validity_flags empty). ---
python3 - "${CSV_OUT}" "${SUMMARY_OUT}" <<'PYEOF'
import csv, sys
from collections import defaultdict

src, dst = sys.argv[1], sys.argv[2]
rows = list(csv.DictReader(open(src)))

groups = defaultdict(list)
for r in rows:
    key = (r["corner_label"], r["temp_c"], r["nx"], r["vce_v"])
    groups[key].append(r)


def best_nf(pts):
    cand = [p for p in pts if p["nf_db"] not in ("", None)]
    return min(cand, key=lambda p: float(p["nf_db"])) if cand else None


def best_ft(pts):
    cand = [p for p in pts if p["ft_hz"] not in ("", None)]
    return max(cand, key=lambda p: float(p["ft_hz"])) if cand else None


out_rows = []
for key, pts in sorted(groups.items(), key=lambda kv: (int(kv[0][2]), kv[0][0], int(kv[0][1]), float(kv[0][3]))):
    corner, temp, nx, vce = key
    in_box = [p for p in pts if p["validity_flags"] == ""]
    bnf, bft = best_nf(pts), best_ft(pts)
    if bnf is None:
        continue
    ibnf, ibft = best_nf(in_box), best_ft(in_box)
    out_rows.append({
        "corner_label": corner, "temp_c": temp, "nx": nx, "vce_v": vce,
        "n_points": len(pts),
        "noise_optimum_jc_ma_um2": f"{float(bnf['jc_ma_um2']):.4f}",
        "noise_optimum_nf_db": f"{float(bnf['nf_db']):.4f}",
        "noise_optimum_gain_db": f"{float(bnf['gain_db']):.4f}",
        "noise_optimum_ft_hz": bnf["ft_hz"] if bnf["ft_hz"] else "",
        "ft_peak_jc_ma_um2": f"{float(bft['jc_ma_um2']):.4f}" if bft else "",
        "ft_peak_hz": f"{float(bft['ft_hz']):.4e}" if bft else "",
        "noise_optimum_validity_flags": bnf["validity_flags"],
        "n_points_in_box": len(in_box),
        "in_box_noise_optimum_jc_ma_um2": f"{float(ibnf['jc_ma_um2']):.4f}" if ibnf else "",
        "in_box_noise_optimum_nf_db": f"{float(ibnf['nf_db']):.4f}" if ibnf else "",
        "in_box_noise_optimum_gain_db": f"{float(ibnf['gain_db']):.4f}" if ibnf else "",
        "in_box_noise_optimum_ft_hz": (ibnf["ft_hz"] if ibnf and ibnf["ft_hz"] else ""),
        "in_box_ft_peak_jc_ma_um2": f"{float(ibft['jc_ma_um2']):.4f}" if ibft else "",
        "in_box_ft_peak_hz": f"{float(ibft['ft_hz']):.4e}" if ibft else "",
    })

with open(dst, "w", newline="") as f:
    w = csv.DictWriter(f, fieldnames=[
        # The first 11 columns are byte-for-byte the same schema (and order)
        # as record 20260910-200059-7da7038-summary.csv; issue #21's new
        # columns are strictly appended after them.
        "corner_label", "temp_c", "nx", "vce_v", "n_points",
        "noise_optimum_jc_ma_um2", "noise_optimum_nf_db", "noise_optimum_gain_db",
        "noise_optimum_ft_hz", "ft_peak_jc_ma_um2", "ft_peak_hz",
        "noise_optimum_validity_flags", "n_points_in_box",
        "in_box_noise_optimum_jc_ma_um2", "in_box_noise_optimum_nf_db",
        "in_box_noise_optimum_gain_db", "in_box_noise_optimum_ft_hz",
        "in_box_ft_peak_jc_ma_um2", "in_box_ft_peak_hz",
    ])
    w.writeheader()
    w.writerows(out_rows)
print(f"wrote {len(out_rows)} summary rows -> {dst}")
PYEOF

# --- Headline figures for the record's own narrative, computed from the
# CSV rather than asserted by hand: per-Nx grid-wide and binding-corner
# noise optima (all points, and restricted to the validity box), the
# V_CE flatness of noise-optimum NF with and without the new 0.6 V point,
# and the validity-box row census. ---
NARRATIVE="$(python3 - "${CSV_OUT}" <<'PYEOF'
import csv, sys
from collections import defaultdict

rows = [r for r in csv.DictReader(open(sys.argv[1])) if r["nf_db"] not in ("", None)]


def fmt(r):
    if r is None:
        return "n/a"
    return (f"J_C={float(r['jc_ma_um2']):.2f} mA/um^2 (I_C={float(r['ic_a'])*1e3:.2f} mA, "
            f"V_BE={r['vbe_v']} V) at corner={r['corner_label']}, {r['temp_c']} C, "
            f"V_CE={r['vce_v']} V -> NF={float(r['nf_db']):.3f} dB, "
            f"gain={float(r['gain_db']):.2f} dB, fT={r['ft_hz'] or 'NA'} Hz")


def best(sel):
    sel = list(sel)
    return min(sel, key=lambda r: float(r["nf_db"])) if sel else None


out = []
nxs = sorted({r["nx"] for r in rows}, key=int)
for nx in nxs:
    g = [r for r in rows if r["nx"] == nx]
    gib = [r for r in g if r["validity_flags"] == ""]
    bind = [r for r in g if r["corner_label"] == "wcs" and r["temp_c"] == "125"]
    bindib = [r for r in bind if r["validity_flags"] == ""]
    out.append(f"BEST_NX{nx}|{fmt(best(g))}")
    out.append(f"BESTINBOX_NX{nx}|{fmt(best(gib))}")
    out.append(f"BIND_NX{nx}|{fmt(best(bind))}")
    out.append(f"BINDINBOX_NX{nx}|{fmt(best(bindib))}")

# V_CE flatness of the noise-optimum NF, per (nx, corner, temp) -- reported
# BOTH unrestricted (the basis on which DR-0001 quoted "<=0.10 dB across
# 0.8-1.4 V") and restricted to the model card's validity box.
def flatness(restrict_to_box):
    cells = defaultdict(dict)
    for r in rows:
        if restrict_to_box and r["validity_flags"] != "":
            continue
        k = (r["nx"], r["corner_label"], r["temp_c"])
        v = r["vce_v"]
        cur = cells[k].get(v)
        if cur is None or float(r["nf_db"]) < cur:
            cells[k][v] = float(r["nf_db"])
    return cells


for scope, tag, restrict in (("in-box", "INBOX", True), ("all-points", "ALL", False)):
    cells = flatness(restrict)
    for nx in nxs:
        worst_all = worst_legacy = -1.0
        worst_all_k = worst_legacy_k = None
        d06 = []
        for k, byv in cells.items():
            if k[0] != nx:
                continue
            vals = list(byv.values())
            spread = max(vals) - min(vals)
            if spread > worst_all:
                worst_all, worst_all_k = spread, k
            legacy = [nf for v, nf in byv.items() if float(v) >= 0.8]
            if legacy:
                s = max(legacy) - min(legacy)
                if s > worst_legacy:
                    worst_legacy, worst_legacy_k = s, k
            if "0.6" in byv and "0.8" in byv:
                d06.append(byv["0.6"] - byv["0.8"])
        if worst_all_k is None:
            continue
        out.append(f"FLAT{tag}_NX{nx}|max spread of the {scope} noise-optimum NF across "
                   f"the full V_CE set = {worst_all:.3f} dB (worst cell: "
                   f"corner={worst_all_k[1]}, {worst_all_k[2]} C); across 0.8-1.4 V only "
                   f"= {worst_legacy:.3f} dB (worst cell: corner={worst_legacy_k[1]}, "
                   f"{worst_legacy_k[2]} C)")
        if d06:
            out.append(f"D06{tag}_NX{nx}|NF(V_CE=0.6 V) - NF(V_CE=0.8 V) at the {scope} "
                       f"noise optimum: min {min(d06):+.3f} dB, max {max(d06):+.3f} dB, "
                       f"mean {sum(d06) / len(d06):+.3f} dB over {len(d06)} corner/temp cells")

n_in = sum(1 for r in rows if r["validity_flags"] == "")
flagct = defaultdict(int)
for r in rows:
    for f in (r["validity_flags"].split(";") if r["validity_flags"] else []):
        flagct[f] += 1
out.append("BOX|" + f"{n_in}/{len(rows)} rows inside the model card's validity box; "
           + ", ".join(f"{k}={v}" for k, v in sorted(flagct.items())))
print("\n".join(out))
PYEOF
)"

n_data_rows=$(($(wc -l < "${CSV_OUT}") - 1))
n_cells=$((${#NX_LIST[@]} * ${#CORNER_LABELS[@]} * ${#TEMPS[@]} * ${#VCES[@]}))

{
  echo "# Record ${RECORD_ID}"
  echo
  echo "- **Experiment**: hbt-characterization"
  NX_LIST_STR="$(IFS=,; echo "${NX_LIST[*]}")"
  CORNER_LABELS_STR="$(IFS=,; echo "${CORNER_LABELS[*]}")"
  TEMPS_STR="$(IFS=,; echo "${TEMPS[*]}")"
  VCES_STR="$(IFS=,; echo "${VCES[*]}")"
  echo "- **Claim**: \`npn13G2\` fT (short-circuit h21 0 dB crossing), 50"
  echo "  Ohm-referenced NF at 2.4 GHz, and 50 Ohm-terminated transducer"
  echo "  gain at 2.4 GHz, vs collector current density J_C (swept via a"
  echo "  dense base-voltage grid) and Vce in {${VCES_STR}} V,"
  echo "  across the HBT process-corner grid x {${TEMPS_STR}} C, at emitter"
  echo "  multiplicity Nx in {${NX_LIST_STR}} -- each Nx across the FULL"
  echo "  grid (issue #21: the earlier record 20260910-200059-7da7038 had"
  echo "  Nx=8 as a single typ/27C/Vce=1.0V spot check and no Vce below"
  echo "  0.8 V). Device-level input to"
  echo "  \`spec/decision-records/0001-bias-supply-topology.md\` -- not the"
  echo "  decision itself, and not a claim against any \`target-spec.md\`"
  echo "  row (none are ratified)."
  echo "- **Bench definitions**: see \`README.md\` 'Bench definitions' --"
  echo "  short summary: fT from an ideal short-circuit h21 AC sweep"
  echo "  (current-source base drive, ideal-voltage-source collector"
  echo "  short); gain/NF from an ideal 50 Ohm source + 50 Ohm load with"
  echo "  ideal bias tees, NF referenced to a fixed 300.15 K source"
  echo "  temperature (Friis/IEEE convention) independent of the swept"
  echo "  ambient corner. Testbench template unchanged from record"
  echo "  20260910-200059-7da7038 -- only the swept grid differs."
  echo "- **Devices**: \`npn13G2\` (native VBIC level=9, no OSDI needed),"
  echo "  Nx in {${NX_LIST_STR}}, emitter area \`AE_UNIT_UM2\`=${AE_UNIT_UM2} um^2 per finger."
  echo "- **PDK**: \`${PDK}\` at \`${PDK_ROOT}\` -- pinned release: see"
  echo "  \`sim/pdk.json\` (IHP-Open-PDK v0.3.0)."
  echo "- **ngspice**: \`${NGSPICE_VERSION}\`"
  echo "- **Sweep grid**: Nx {${NX_LIST_STR}} x corner_label"
  echo "  {${CORNER_LABELS_STR}} x temp {${TEMPS_STR}} x Vce {${VCES_STR}}"
  echo "  x ${N_POINTS} base-voltage points (${VBE_START}V + i*${VBE_STEP}V)"
  echo "  = ${n_cells} grid cells, ${N_POINTS} points each."
  echo "- **Result**: ${n_data_rows} data rows parsed from ${total} ngspice"
  echo "  invocations (one per nx x corner_label x temp x Vce cell,"
  echo "  internally sweeping all ${N_POINTS} base-voltage points via"
  echo "  \`alter\`+\`dowhile\`)."
  if [[ ${#failed_points[@]} -gt 0 ]]; then
    echo "- **Failed cells**: ${failed_points[*]}"
  else
    echo "- **Failed cells**: none."
  fi
  if [[ ${#partial_points[@]} -gt 0 ]]; then
    echo "- **Partial cells** (cell ran to completion; individual bias points"
    echo "  dropped because ngspice reported an operating-point failure /"
    echo "  electrothermal divergence there, so its echoed gain/NF would have"
    echo "  been a stale cross-plot value -- see \`run_hbt_sweep.sh\`'s"
    echo "  per-point convergence gate): ${partial_points[*]}"
  else
    echo "- **Partial cells**: none -- every bias point in every cell converged."
  fi
  echo "- **Model-card validity box** (\`sg13g2_hbt_mod.lib\`: \`ic <"
  echo "  0.003*Nx A\`, \`vbe 0.65-0.96 V\`, \`vce 0.4-2.0 V\`): flagged"
  echo "  per row in the CSV's \`validity_flags\` column (empty = inside"
  echo "  the box). Every swept temperature (-40/27/125 C) and every swept"
  echo "  Nx (1-10) is inside the card's stated range by construction."
  printf '%s\n' "${NARRATIVE}" | sed -n 's/^BOX|/  Census: /p'
  echo "- **Headline figures** (all computed from \`records/${RECORD_ID}.csv\`,"
  echo "  not asserted by hand):"
  printf '%s\n' "${NARRATIVE}" | while IFS='|' read -r tag body; do
    case "${tag}" in
      BEST_NX*)      echo "  - Noise optimum, whole grid, Nx=${tag#BEST_NX}: ${body}" ;;
      BESTINBOX_NX*) echo "  - Noise optimum, whole grid, in validity box, Nx=${tag#BESTINBOX_NX}: ${body}" ;;
      BIND_NX*)      echo "  - Noise optimum at the binding corner (wcs/125C), Nx=${tag#BIND_NX}: ${body}" ;;
      BINDINBOX_NX*) echo "  - Noise optimum at the binding corner (wcs/125C), in validity box, Nx=${tag#BINDINBOX_NX}: ${body}" ;;
      FLATINBOX_NX*) echo "  - V_CE flatness (validity box only), Nx=${tag#FLATINBOX_NX}: ${body}" ;;
      FLATALL_NX*)   echo "  - V_CE flatness (all converged points), Nx=${tag#FLATALL_NX}: ${body}" ;;
      D06INBOX_NX*)  echo "  - New V_CE=0.6 V point (validity box only), Nx=${tag#D06INBOX_NX}: ${body}" ;;
      D06ALL_NX*)    echo "  - New V_CE=0.6 V point (all converged points), Nx=${tag#D06ALL_NX}: ${body}" ;;
    esac
  done
  echo "- **Links**:"
  echo "  - Template: \`testbench/tb_hbt_sweep.spice.tmpl\`"
  echo "  - Per-point generated netlists: \`netlist-snapshots/${RECORD_ID}/\`"
  echo "  - Per-point raw ngspice logs: \`corners/${RECORD_ID}/\`"
  echo "  - Full-sweep CSV: \`records/${RECORD_ID}.csv\`"
  echo "  - Summary CSV (noise-optimum + fT-peak per corner/temp/Nx/Vce"
  echo "    cell, both over all points and restricted to the validity"
  echo "    box): \`records/${RECORD_ID}-summary.csv\`"
  echo "- **Timestamp / author**: $(date -u +%Y-%m-%dT%H:%M:%SZ), Loom Builder"
  echo "  (agent), issue #21 (extends issue #7's record"
  echo "  20260910-200059-7da7038; that record is untouched -- this tree is"
  echo "  append-only, see \`sim/README.md\`)."
} > "${MD_OUT}"

echo "run_hbt_sweep.sh: wrote ${MD_OUT}, ${CSV_OUT}, ${SUMMARY_OUT}"
echo "run_hbt_sweep.sh: ${n_data_rows} data rows from ${total} ngspice invocations"
printf '%s\n' "${NARRATIVE}" | sed 's/|/: /'

if [[ ${#failed_points[@]} -gt 0 ]]; then
  exit 1
fi
exit 0
