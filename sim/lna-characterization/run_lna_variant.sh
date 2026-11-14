#!/usr/bin/env bash
# Inductor-loss variant campaign (issue #56): re-runs the run_lna_sweep.sh
# phase-1 measurements (50 Ohm S-parameters, ngspice two-port NF, .noise NF at
# T0 = 290 K, 10 MHz..30 GHz k/mu/|S22| stability) over the SAME 45 PVT cells
# for each inductor variant, as `klt sim` corners requests.
#
#   export PDK_ROOT=/path/to/ihp-open-pdk PDK=ihp-sg13g2   # or let sim/env.sh find it
#   sim/lna-characterization/run_lna_variant.sh
#
# Why `klt sim` instead of run_lna_sweep.sh's own ngspice pool: this is a
# multi-corner grid, and on the Loom dispatch workers (KLT_SIM_BACKEND=batch,
# exported by the daemon) a grid is submitted to the Spot batch fleet rather
# than hand-launched on the shared host. `klt sim` runs ONE analysis per
# request, so each variant is three requests (sp_band, sp_stab, noise) -- see
# lna_variant_campaign.py. If a batch submit fails this script STOPS and
# records the error; it never falls back to a local grid.
#
# Variants (lna_variant_campaign.py VARIANTS): ideal, lc_em, le_q20, le_q10,
# le_q5, lc_em_le_q10. The EM model is sim/models/sg13g2_inductor_em.spice
# (stamped copy; hash-checked below, never edited here). design/ is untouched:
# every variant netlist is a generated bench artifact under
# netlist-snapshots/<record-id>/.
#
# Environment knobs (all optional):
#   LNA_VARIANTS=a,b,c    subset of variants (default: all)
#   LNA_NF_NPTS=<n>       points of the 290 K NF sweep (odd, >= 11; default 11 =
#                         the S-parameter grid); identical for every variant.
#   LNA_VARIANT_SMOKE=1   single nominal cell per request (plumbing check only;
#                         NOT a PVT campaign -- do not commit as evidence)
#   LNA_VARIANT_BACKEND=  override the klt backend (default: whatever klt picks,
#                         i.e. $KLT_SIM_BACKEND)
#   LNA_VARIANT_CAPACITY_WAIT_S=<s>  how long a batch submit waits with backoff
#                         for fleet vCPU capacity (default 600; batch only)
#   KLT_NGSPICE_BINARY=   ngspice binary for local-backend runs. The PDK's
#                         PSP103 OSDI builds target OSDI v0.4, so a local run
#                         needs ngspice >= 46 (the worker's /usr/bin/ngspice 42
#                         cannot load them); the fleet image supplies its own.
#
# Output (append-only, same layout as run_lna_sweep.sh):
#   netlist-snapshots/<record-id>/   variant netlists + klt requests
#   corners/<record-id>/             klt reports (+ per-corner decks/logs)
#   records/<record-id>{.md,-summary.csv,-compare.csv}
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SIM_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
# shellcheck source-path=SCRIPTDIR
# shellcheck source=../env.sh
source "${SIM_DIR}/env.sh"

sim_require_pdk run_lna_variant.sh --osdi
command -v klt >/dev/null 2>&1 || { echo "run_lna_variant.sh: klt not on PATH." >&2; exit 3; }
command -v python3 >/dev/null 2>&1 || { echo "run_lna_variant.sh: python3 not on PATH." >&2; exit 3; }

# The EM model copy must still match its recorded provenance hash.
"${SIM_DIR}/models/check_sources.sh" || { echo "run_lna_variant.sh: sim/models hash check failed." >&2; exit 3; }

sim_record_paths
DESIGN_NETLIST_SHA="$(sha256sum "${REPO_ROOT}/design/netlist/lna.spice" | awk '{print $1}')"
EM_SHA="$(sha256sum "${SIM_DIR}/models/sg13g2_inductor_em.spice" | awk '{print $1}')"
KLT_VERSION="$(klt --version 2>&1 | head -1)"

# klt version-floor preflight: fail here, not late at the batch runner. The
# floor lives in sim/pdk.json (klt_variant_campaign.min_version), the one place
# it is recorded. Semantic-version comparison only; no feature-list parsing.
# This checks the CLIENT klt; the batch runner image must carry the same
# features and is checked by klt itself (batch_runner_version_mismatch).
python3 -I - "${SIM_DIR}/pdk.json" "${KLT_VERSION}" <<'PYEOF' || exit 3
import json, re, sys
cfg = json.load(open(sys.argv[1]))["klt_variant_campaign"]
floor_s, feats = cfg["min_version"], cfg["required_features"]
def triple(s):
    m = re.search(r"(\d+)\.(\d+)\.(\d+)", s)
    return tuple(int(x) for x in m.groups()) if m else None
have, floor = triple(sys.argv[2]), triple(floor_s)
if have is None:
    sys.exit("run_lna_variant.sh: cannot parse a version from `klt --version` output "
             f"{sys.argv[2]!r}; need klt >= {floor_s}.")
if have < floor:
    sys.exit(f"run_lna_variant.sh: klt {'.'.join(map(str, have))} is older than the required "
             f"floor {floor_s} (sim/pdk.json klt_variant_campaign.min_version). It lacks: "
             + ", ".join(feats) + ". Use a newer klt (e.g. `uvx --from \"klayout-tools>="
             + floor_s + "\" klt`); do not run the grid locally.")
PYEOF

NF_NPTS="${LNA_NF_NPTS:-11}"
GEN_ARGS=(--outdir "${SNAPSHOTS_OUT}" --nf-npts "${NF_NPTS}")
[[ -n "${LNA_VARIANTS:-}" ]] && GEN_ARGS+=(--variants "${LNA_VARIANTS}")
[[ -n "${LNA_VARIANT_SMOKE:-}" ]] && { GEN_ARGS+=(--smoke); echo "run_lna_variant.sh: LNA_VARIANT_SMOKE set -- single-cell smoke, NOT a PVT campaign"; }
python3 "${SCRIPT_DIR}/lna_variant_campaign.py" gen "${GEN_ARGS[@]}"

KLT_ARGS=(--format json)
[[ -n "${LNA_VARIANT_BACKEND:-}" ]] && KLT_ARGS+=(--backend "${LNA_VARIANT_BACKEND}")
# The Spot batch fleet is vCPU-budgeted: a burst of requests gets
# `batch_no_capacity`, which fails the submit outright. Waiting with backoff is
# the host rule for every batch `klt sim`, so pass --wait-for-capacity whenever
# the effective backend is batch. It is a submit-side wait only: it never
# retries on another backend and never falls back to a local grid.
EFFECTIVE_BACKEND="${LNA_VARIANT_BACKEND:-${KLT_SIM_BACKEND:-local}}"
CAPACITY_WAIT="${LNA_VARIANT_CAPACITY_WAIT_S:-600}"
if [[ "${EFFECTIVE_BACKEND}" == "batch" ]]; then
  KLT_ARGS+=(--wait-for-capacity "${CAPACITY_WAIT}")
fi

echo "run_lna_variant.sh: record ${RECORD_ID}; klt ${KLT_VERSION}; KLT_SIM_BACKEND=${KLT_SIM_BACKEND:-<unset>}"
FAILED=()

# --- batch: submit the whole set in one invocation -----------------------
# Submitting the requests one at a time serialises the fleet's own launch
# overhead (~2 min per job) behind every request: the 7-variant x 3-analysis
# campaign is 21 requests, so a serial loop spends hours waiting on spot
# launches rather than on ngspice. `klt sim --batch-set` is the sanctioned
# scheduler for a set of independent requests (it forces backend batch and
# never falls back to local ngspice): at most --max-in-flight run on the fleet
# at once and the rest queue. Each member writes its own
# <set-dir>/<stem>/report.json, which is copied to the same
# corners/<id>/<stem>.report.json path the serial loop produces, so the
# reducer, the coverage validator and the record provenance below are
# unchanged and cannot tell the two submission paths apart.
if [[ "${EFFECTIVE_BACKEND}" == "batch" ]]; then
  MAX_IN_FLIGHT="${LNA_VARIANT_MAX_IN_FLIGHT:-7}"
  CAPACITY_RETRIES="${LNA_VARIANT_CAPACITY_RETRIES:-3}"
  SET_OUT="${CORNERS_OUT}/set"
  mkdir -p "${SET_OUT}"
  REQS=()
  for req in "${SNAPSHOTS_OUT}"/*.request.json; do REQS+=("${req}"); done
  echo "run_lna_variant.sh: klt sim --batch-set ${#REQS[@]} requests, max-in-flight ${MAX_IN_FLIGHT}, --wait-for-capacity ${CAPACITY_WAIT}"
  SET_REPORT="${CORNERS_OUT}/set-report.json"
  SET_ERRLOG="${CORNERS_OUT}/set.stderr.log"
  set_rc=0
  klt sim --batch-set "${REQS[@]}" -o "${SET_OUT}" \
    --max-in-flight "${MAX_IN_FLIGHT}" --capacity-retries "${CAPACITY_RETRIES}" \
    --wait-for-capacity "${CAPACITY_WAIT}" --format json \
    > "${SET_REPORT}" 2> "${SET_ERRLOG}" || set_rc=$?
  # Materialise each member's report at the per-request path the reducer reads.
  # The source path comes from the envelope's own `requests[].report` field, not
  # from a guessed directory name: klt names a member's directory after the
  # request file with only the LAST suffix removed, so `ideal_noise.request.json`
  # lands in `ideal_noise.request/`, not `ideal_noise/`.
  python3 -I - "${SET_REPORT}" "${CORNERS_OUT}" <<'PYEOF'
import json, os, re, shutil, sys
envelope, corners_out = sys.argv[1], sys.argv[2]
try:
    d = json.load(open(envelope))
except Exception as exc:
    sys.exit(f"run_lna_variant.sh: cannot read set envelope {envelope}: {exc}")
for r in d.get("requests") or []:
    src = r.get("report")
    stem = re.sub(r"\.request\.json$", "", os.path.basename(r.get("request") or ""))
    if not stem:
        continue
    if src and os.path.isfile(src):
        shutil.copyfile(src, os.path.join(corners_out, f"{stem}.report.json"))
    else:
        print(f"run_lna_variant.sh: {stem}: no report to collect "
              f"({'missing ' + src if src else 'member never produced one'})",
              file=sys.stderr)
PYEOF
  # Per-member status from the aggregate envelope: a non-zero member exit is a
  # failure even when the set as a whole returned 0.
  while read -r stem rc; do
    [[ -z "${stem}" ]] && continue
    echo "run_lna_variant.sh: ${stem} exited ${rc} (see ${SET_ERRLOG}, ${SET_REPORT})" >&2
    FAILED+=("${stem}:${rc}")
  done < <(python3 -I - "${SET_REPORT}" <<'PYEOF'
import json, os, re, sys
try:
    d = json.load(open(sys.argv[1]))
except Exception:
    sys.exit(0)
for r in d.get("requests") or []:
    if r.get("exit_code"):
        # strip the whole ".request.json" suffix, not just ".json", so the
        # label matches the <variant>_<analysis> stem used everywhere else
        stem = re.sub(r"\.request\.json$", "", os.path.basename(r.get("request") or ""))
        print("%s %s" % (stem or "<unknown>", r["exit_code"]))
PYEOF
  )
  if (( set_rc != 0 )) && [[ ${#FAILED[@]} -eq 0 ]]; then
    FAILED+=("batch-set:${set_rc}")
    echo "run_lna_variant.sh: --batch-set exited ${set_rc} with no per-request failure (see ${SET_ERRLOG})" >&2
  fi
else
for req in "${SNAPSHOTS_OUT}"/*.request.json; do
  stem="$(basename "${req}" .request.json)"
  report="${CORNERS_OUT}/${stem}.report.json"
  errlog="${CORNERS_OUT}/${stem}.stderr.log"
  echo "run_lna_variant.sh: klt sim ${stem}"
  rc=0
  # Absolute -o is required: klt runs ngspice with cwd = the corner dir, so a
  # relative --outdir yields relative deck/log paths that do not resolve there.
  klt sim "${req}" -o "${CORNERS_OUT}/${stem}.artifacts" "${KLT_ARGS[@]}" > "${report}" 2> "${errlog}" || rc=$?
  # klt sim: 0 pass, 3 a declared limit failed, 4 error/inconclusive. This
  # bench declares no limits, so only 0 is a clean run.
  if (( rc != 0 )); then
    echo "run_lna_variant.sh: ${stem} exited ${rc} (see ${errlog})" >&2
    FAILED+=("${stem}:${rc}")
    # A submit/transport failure (no usable report) must not be retried
    # locally; stop rather than burn through the remaining variants.
    if ! python3 -I -c "import json,sys; d=json.load(open(sys.argv[1])); sys.exit(0 if d.get('corners') else 1)" "${report}" 2>/dev/null; then
      echo "run_lna_variant.sh: no usable report for ${stem}; stopping (no local fallback)." >&2
      break
    fi
  fi
done
fi

SUMMARIZE_ARGS=(--corners-dir "${CORNERS_OUT}" --nf-npts "${NF_NPTS}"
  --summary-csv "${RECORDS_DIR}/${RECORD_ID}-summary.csv"
  --compare-csv "${RECORDS_DIR}/${RECORD_ID}-compare.csv"
  --headlines-md "${CORNERS_OUT}/headlines.md"
  --coverage-json "${CORNERS_OUT}/coverage.json")
[[ -n "${LNA_VARIANTS:-}" ]] && SUMMARIZE_ARGS+=(--variants "${LNA_VARIANTS}")
[[ -n "${LNA_VARIANT_SMOKE:-}" ]] && SUMMARIZE_ARGS+=(--grid smoke)
# Reduction failure (incomplete/failed/duplicate/non-finite coverage) is NOT
# masked: diagnostics, logs, reports and the record below are still written,
# then the script exits nonzero at the end.
SUMMARIZE_RC=0
python3 "${SCRIPT_DIR}/lna_variant_campaign.py" summarize "${SUMMARIZE_ARGS[@]}" || SUMMARIZE_RC=$?
if (( SUMMARIZE_RC != 0 )); then
  echo "run_lna_variant.sh: reduction FAILED (exit ${SUMMARIZE_RC}); coverage incomplete -- see ${CORNERS_OUT}/headlines.md" >&2
fi

JOBS="$(python3 -I - "${CORNERS_OUT}" <<'PYEOF'
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
)"

{
  echo "# Record ${RECORD_ID}"
  echo
  echo "- **Experiment**: lna-characterization, inductor-loss variants (issue #56)."
  echo "- **Claim**: what replacing the ideal \`Le\`/\`Lc\` of \`design/lna.sch\` with lossy"
  echo "  models does to gain, noise figure, S11, S22 and the mu stability margin at the"
  echo "  45 PVT cells, versus the ideal baseline run through the identical harness."
  echo "  Not a conformance claim against any \`spec/target-spec.md\` row."
  echo "- **DUT**: \`design/netlist/lna.spice\` sha256 \`${DESIGN_NETLIST_SHA}\`, inlined verbatim"
  echo "  except the single inductor edit per variant (marked \`VARIANT EDIT\` in each"
  echo "  netlist snapshot). \`design/\` is not modified."
  echo "- **EM inductor model**: \`sim/models/sg13g2_inductor_em.spice\` sha256 \`${EM_SHA}\`"
  echo "  (stamped copy, provenance in \`sim/models/SOURCE.md\`)."
  echo "- **Bench definitions**: see \`README.md\` section \"Inductor-loss variants\"; every"
  echo "  generated netlist snapshot header and request JSON carries the exact analysis."
  echo "- **PDK**: \`${PDK}\` at \`${PDK_ROOT}\`; HBT sections from \`cornerHBT.lib\`, MOS from"
  echo "  \`cornerMOShv.lib\` with the same label->section map as \`run_lna_sweep.sh\`."
  echo "- **PDK identity (verified)**: \`${SIM_PDK_RELEASE}\` via ${SIM_PDK_ID_ROUTE}; model hashes in \`records/${RECORD_ID}.pdk-provenance.json\`"
  echo "- **Runner**: client \`${KLT_VERSION}\`; backend \`${EFFECTIVE_BACKEND}\`$([[ "${EFFECTIVE_BACKEND}" == batch ]] && echo " (--wait-for-capacity ${CAPACITY_WAIT} s)")."
  echo "  Jobs (klt \`environment.remote\`):"
  echo "${JOBS}"
  if [[ ${#FAILED[@]} -gt 0 ]]; then
    echo "- **Failed requests**: ${FAILED[*]}"
  else
    echo "- **Failed requests**: none."
  fi
  if (( SUMMARIZE_RC != 0 )); then
    echo "- **Reduction**: FAILED (exit ${SUMMARIZE_RC}) -- **coverage incomplete**; not a complete-grid result."
  else
    echo "- **Reduction**: ok (expected grid complete, all measurements finite)."
  fi
  echo "- **Headlines (machine-generated)**:"
  echo
  cat "${CORNERS_OUT}/headlines.md" 2>/dev/null || echo "(none -- summarize found no reports)"
  echo
  echo "- **Links**: netlists+requests \`netlist-snapshots/${RECORD_ID}/\`; klt reports and"
  echo "  artifacts \`corners/${RECORD_ID}/\`; \`records/${RECORD_ID}-summary.csv\` (every"
  echo "  variant x cell x measurement); \`records/${RECORD_ID}-compare.csv\` (variant minus ideal)."
  echo "- **Timestamp / author**: $(date -u +%Y-%m-%dT%H:%M:%SZ), Loom Builder (agent), issue #56."
} > "${RECORDS_DIR}/${RECORD_ID}.md"

echo "run_lna_variant.sh: wrote ${RECORDS_DIR}/${RECORD_ID}.md"
if [[ ${#FAILED[@]} -gt 0 ]]; then
  echo "run_lna_variant.sh: failed: ${FAILED[*]}" >&2
  exit 1
fi
if (( SUMMARIZE_RC != 0 )); then
  exit 1
fi
