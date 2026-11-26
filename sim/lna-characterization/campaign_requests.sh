# shellcheck shell=bash
# Sourced by the variant and IIP3 runners after sim/env.sh. sim_require_pdk
# supplies SIM_SCRIPT_NAME and sim_record_paths supplies the output directories.

# Run the generated requests and leave member or aggregate failures in FAILED
# for reduction and the final record. An unreadable envelope stops the runner
# before reduction. Call directly under set -e.
lna_run_requests() {
  local backend_override=$1 max_in_flight=$2 capacity_retries=$3
  local -a requests=("${SNAPSHOTS_OUT}"/*.request.json)
  local stem rc
  FAILED=()

  if [[ "${EFFECTIVE_BACKEND}" == "batch" ]]; then
    local set_out="${CORNERS_OUT}/set" set_report="${CORNERS_OUT}/set-report.json"
    local set_errlog="${CORNERS_OUT}/set.stderr.log" failures="${CORNERS_OUT}/set-failures.txt"
    local set_rc=0
    mkdir -p "${set_out}"
    echo "${SIM_SCRIPT_NAME}: klt sim --batch-set ${#requests[@]} requests, max-in-flight ${max_in_flight}, --wait-for-capacity ${CAPACITY_WAIT}"
    klt sim --batch-set "${requests[@]}" -o "${set_out}" \
      --max-in-flight "${max_in_flight}" --capacity-retries "${capacity_retries}" \
      --wait-for-capacity "${CAPACITY_WAIT}" --format json \
      > "${set_report}" 2> "${set_errlog}" || set_rc=$?

    # collect-set copies the reports named in the envelope to the serial
    # report paths and lists failed members in envelope order.
    python3 -I "${SCRIPT_DIR}/lna_variant_campaign.py" collect-set \
      --runner "${SIM_SCRIPT_NAME}" --envelope "${set_report}" \
      --corners-out "${CORNERS_OUT}" > "${failures}" || return 1
    while read -r stem rc; do
      [[ -z "${stem}" ]] && continue
      echo "${SIM_SCRIPT_NAME}: ${stem} exited ${rc} (see ${set_errlog}, ${set_report})" >&2
      FAILED+=("${stem}:${rc}")
    done < "${failures}"
    if (( set_rc != 0 && ${#FAILED[@]} == 0 )); then
      FAILED+=("batch-set:${set_rc}")
      echo "${SIM_SCRIPT_NAME}: --batch-set exited ${set_rc} with no per-request failure (see ${set_errlog})" >&2
    fi
  else
    local req report errlog
    local -a args=(--format json)
    [[ -n "${backend_override}" ]] && args+=(--backend "${backend_override}")
    for req in "${requests[@]}"; do
      stem="$(basename "${req}" .request.json)"
      report="${CORNERS_OUT}/${stem}.report.json"
      errlog="${CORNERS_OUT}/${stem}.stderr.log"
      echo "${SIM_SCRIPT_NAME}: klt sim ${stem}"
      rc=0
      # klt runs ngspice from the corner directory and needs an absolute -o.
      klt sim "${req}" -o "${CORNERS_OUT}/${stem}.artifacts" "${args[@]}" > "${report}" 2> "${errlog}" || rc=$?
      if (( rc != 0 )); then
        echo "${SIM_SCRIPT_NAME}: ${stem} exited ${rc} (see ${errlog})" >&2
        FAILED+=("${stem}:${rc}")
        if ! python3 -I -c "import json,sys; d=json.load(open(sys.argv[1])); sys.exit(0 if d.get('corners') else 1)" "${report}" 2>/dev/null; then
          echo "${SIM_SCRIPT_NAME}: no usable report for ${stem}; stopping (no local fallback)." >&2
          break
        fi
      fi
    done
  fi
}

# Emit the remote-job bullets in record order, skipping unreadable reports.
lna_job_bullets() {
  python3 -I - "$1" <<'PYEOF'
import glob, json, sys
for p in sorted(glob.glob(sys.argv[1] + "/*.report.json")):
    try:
        d = json.load(open(p))
    except Exception:
        continue
    r = (d.get("environment") or {}).get("remote") or {}
    name = p.rsplit("/", 1)[-1][: -len(".report.json")]
    print("  - `%s`: job `%s`, %s, runner klt `%s`, state `%s`, status `%s`, %s corners" % (
        name, r.get("job_id"), r.get("instance_type"), r.get("runner_klt_version"),
        r.get("state"), d.get("status"), d.get("corner_count")))
PYEOF
}
