# shellcheck shell=bash
# hbt_parse.sh -- the hbt-characterization per-cell reduction, sourced by
# run_hbt_sweep.sh AND by tests/test_parse_hbt_log.py (issue #144), so the
# tests drive exactly the parser invocation and cell classification the
# runner publishes with. No ngspice, no PDK: pure text in, text out.
#
#   hbt_parse_log LOG POINT_ID CORNER SECTION TEMP NX VCE REJECTS
#       Reduce one cell's ngspice log with parse_hbt_log.awk. Accepted CSV
#       rows go to stdout; one "point_id,vbe,reason" line per unpublished
#       block is APPENDED to REJECTS. Reads the validity-box constants
#       AE_UNIT_UM2 IC_LIMIT_PER_NX VBE_MIN VBE_MAX VCE_MIN VCE_MAX from the
#       caller (run_hbt_sweep.sh defines them). HBT_AWK selects the awk
#       binary (default: awk) so the tests can run every available
#       implementation through this same function.
#
#   hbt_classify_cell EMITTED N_POINTS N_DIVERGED N_MALFORMED RC END_MARKER
#       Print the cell verdict: "ok", "partial", or "failed:<why>".
#       END_MARKER is 1 when the log carries ngspice's end-of-control-section
#       marker, else 0.

HBT_PARSE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
HBT_PARSE_AWK="${HBT_PARSE_DIR}/parse_hbt_log.awk"

hbt_parse_log() {
  local log="$1" point_id="$2" corner="$3" section="$4" temp="$5" nx="$6" vce="$7" rejects="$8"
  "${HBT_AWK:-awk}" \
      -v point_id="${point_id}" -v corner="${corner}" -v section="${section}" \
      -v temp="${temp}" -v nx="${nx}" -v vce="${vce}" \
      -v ae="${AE_UNIT_UM2:?}" -v iclim="${IC_LIMIT_PER_NX:?}" \
      -v vbemin="${VBE_MIN:?}" -v vbemax="${VBE_MAX:?}" \
      -v vcemin="${VCE_MIN:?}" -v vcemax="${VCE_MAX:?}" \
      -v rejects="${rejects}" \
      -f "${HBT_PARSE_AWK}" "${log}"
}

hbt_classify_cell() {
  local emitted="$1" n_points="$2" n_diverged="$3" n_malformed="$4" rc="$5" end_marker="$6"
  if [[ "${n_malformed}" -gt 0 ]]; then
    # A malformed block is never a converged measurement, and it is not the
    # documented divergence case either: unexplained, so the cell FAILS.
    echo "failed:${n_malformed} malformed block(s), ${emitted}/${n_points} points parsed"
  elif [[ "${emitted}" -eq 0 ]]; then
    echo "failed:every bias point diverged"
  elif [[ "${emitted}" -lt "${n_points}" ]]; then
    if [[ $((emitted + n_diverged)) -lt "${n_points}" ]]; then
      # Blocks missing that neither published nor diverged: unexplained.
      echo "failed:only ${emitted} converged + ${n_diverged} diverged of ${n_points} points"
    else
      # Every missing point is a documented divergence drop.
      echo "partial"
    fi
  elif [[ "${rc}" -ne 0 || "${end_marker}" -ne 1 ]]; then
    # All N_POINTS points parsed clean, yet ngspice still exited non-zero
    # or never printed its end-of-control marker: unexplained, so it is
    # NOT quietly accepted.
    echo "failed:${emitted}/${n_points} points parsed but no end-of-control marker"
  else
    echo "ok"
  fi
}
