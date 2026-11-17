#!/usr/bin/env bash
# Run the CI checks of .github/workflows/signoff.yml locally (issue #108).
#
# Mirrors the workflow's self-test + check pairs, in workflow order, each
# invoked exactly as the workflow invokes them (cwd = repo root). Serial only.
# Keeps going after a failure, prints PASS/FAIL/SKIP per step and a summary,
# and exits 1 if any step failed. It never installs anything: steps that need
# an absent tool or a git base ref print a SKIP line instead.
#
# Usage: .github/scripts/run-local-checks.sh [--base <ref>]
#   --base <ref>  also run the sim-append-only check against <ref>
#                 (CI uses origin/<pull-request base branch>, full history).
# The workflow stays the authority; .github/scripts/test-run-local-checks.sh
# fails if any workflow command is not run here by a `step` exactly as CI
# runs it (whole-command match, workflow order).
set -u

base=""
while [ $# -gt 0 ]; do
  case "$1" in
    --base)
      [ $# -ge 2 ] || { echo "usage: $0 [--base <ref>]" >&2; exit 2; }
      base="$2"; shift 2 ;;
    -h|--help) sed -n '2,16p' "$0"; exit 0 ;;
    *) echo "usage: $0 [--base <ref>]" >&2; exit 2 ;;
  esac
done

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT" || exit 2

n_pass=0; n_fail=0; n_skip=0
summary=()

# step <label> <command...>: run one command, record PASS/FAIL.
step() {
  local label="$1"; shift
  echo "=== $label"
  if "$@"; then
    summary+=("PASS: $label"); n_pass=$((n_pass+1))
  else
    summary+=("FAIL: $label"); n_fail=$((n_fail+1))
  fi
}

skip() {
  echo "SKIP: $1"
  summary+=("SKIP: $1"); n_skip=$((n_skip+1))
}

# Mirrors the workflow's shell-lint discovery snippet, then lints.
shell_lint() {
  local files=() f
  mapfile -d '' -t files < <(
    {
      git ls-files -z -- 'sim/*.sh' 'layout/*.sh' '.github/scripts/*.sh'
      git ls-files -z -- '.github/scripts/*' | while IFS= read -r -d '' f; do
        case "${f##*/}" in *.*) continue ;; esac
        if head -n 1 "$f" | grep -Eq '^#![[:space:]]*(/usr/bin/env[[:space:]]+)?(/[^[:space:]]*/)?bash([[:space:]]|$)'; then
          printf '%s\0' "$f"
        fi
      done
    } | sort -z -u
  )
  if [ "${#files[@]}" -eq 0 ]; then
    echo "ERROR: no shell scripts discovered; refusing to pass an empty lint" >&2
    return 1
  fi
  printf '%s\n' "${files[@]}"
  shellcheck --shell=bash --severity=warning "${files[@]}"
}

# --- pinned release klt resolution (issue #357; shared by the attest and
# signoff jobs below): the host klt when it matches the signoff pin,
# otherwise a throwaway uvx wrapper dir prepended to PATH for exactly those
# gated steps (never a host-wide install). A wrapper that cannot resolve --
# e.g. uvx offline -- leaves klt_ready=0, so the gated steps SKIP instead of
# silently grading with a dev-build klt.
klt_pin="$(grep -Eo 'klayout-tools==[0-9][0-9.]*' .github/workflows/signoff.yml | head -n 1 | cut -d= -f3)"
klt_have="$(command -v klt >/dev/null 2>&1 && klt --version 2>/dev/null | head -n 1)"
klt_tmp=""
klt_ready=0
if [ -n "$klt_pin" ] && [ "$klt_have" = "klt $klt_pin" ]; then
  klt_ready=1
elif [ -n "$klt_pin" ] && command -v uvx >/dev/null 2>&1; then
  klt_tmp="$(mktemp -d)" \
    && printf '#!/usr/bin/env bash\nexec uvx --from "klayout-tools==%s" klt "$@"\n' "$klt_pin" >"$klt_tmp/klt" \
    && chmod +x "$klt_tmp/klt" \
    && [ "$(PATH="$klt_tmp:$PATH" klt --version 2>/dev/null | head -n 1)" = "klt $klt_pin" ] \
    && klt_ready=1
fi
klt_tmp_cleanup() { [ -n "$klt_tmp" ] && rm -rf "$klt_tmp"; }
trap klt_tmp_cleanup EXIT

# --- job: attest (issue #238; klt signoff --attest --check, needs release klt)
if [ "$klt_ready" -eq 1 ]; then
  # Scope the pinned wrapper to these steps only: both attest commands and
  # the signoff job's scripts below resolve a literal `klt` from PATH, and
  # later jobs (design-source-audit) must keep seeing the host PATH.
  [ -n "$klt_tmp" ] && PATH="$klt_tmp:$PATH"
  step "attest: T1 item 1 attestation reproduces" klt signoff --attest 1 --inventory signoff/attest/item1.json --check signoff/attest/item1.envelope.json
  step "attest: T1 item 9 attestation reproduces" klt signoff --attest 9 --inventory signoff/attest/item9.json --check signoff/attest/item9.envelope.json
  step "attest: T1 item 10 attestation reproduces" klt signoff --attest 10 --inventory signoff/attest/item10.json --check signoff/attest/item10.envelope.json
  [ -n "$klt_tmp" ] && PATH="${PATH#"$klt_tmp":}"
else
  skip "attest: items 1, 9, 10 (need release klt $klt_pin on PATH or uvx to fetch it, have: ${klt_have:-none}; CI pip-installs it)"
fi

# --- job: signoff
step "signoff: check-klt-pin.sh" .github/scripts/check-klt-pin.sh
step "signoff: test-check-klt-pin.sh" .github/scripts/test-check-klt-pin.sh
if [ "$klt_ready" -eq 1 ]; then
  [ -n "$klt_tmp" ] && PATH="$klt_tmp:$PATH"
  step "signoff: test-check-signoff.sh" .github/scripts/test-check-signoff.sh
  step "signoff: check-signoff.sh" .github/scripts/check-signoff.sh
  [ -n "$klt_tmp" ] && PATH="${PATH#"$klt_tmp":}"
else
  skip "signoff: test-check-signoff.sh (need release klt $klt_pin on PATH or uvx to fetch it, have: ${klt_have:-none}; CI pip-installs it)"
  skip "signoff: check-signoff.sh (need release klt $klt_pin on PATH)"
fi

# --- job: reduction-tests
step "reduction-tests: lna-characterization unit tests" \
  python3 -I -m unittest discover -s sim/lna-characterization/tests -v
step "reduction-tests: spec-envelope committed-record replay (issue #364)" \
  python3 -I sim/lna-characterization/reduce_spec_envelopes.py --snapshot-dir sim/lna-characterization/netlist-snapshots/20261117-054141-bdebb4d --check

# --- job: hbt-reduction-tests
# (fixed-T0 NF re-derivation, issue #101, and the production log parser
# parse_hbt_log.awk / hbt_parse.sh with its retained-log replay, issue #144)
step "hbt-reduction-tests: hbt-characterization unit tests" \
  python3 -I -m unittest discover -s sim/hbt-characterization/tests -v

# --- job: biasop-reduction-tests
step "biasop-reduction-tests: lna-bias-pvt unit tests and committed-record replay" \
  python3 -I -m unittest discover -s sim/lna-bias-pvt/tests -v
step "biasop-reduction-tests: startup waveform settling audit and retained-waveform replay (issue #154)" \
  python3 -I -m unittest discover -s sim/lna-bias-pvt/tests -p test_startup_waveform_audit.py -v

# --- job: biasref-reduction-tests
step "biasref-reduction-tests: biasref-topology unit tests and committed-record replay" \
  python3 -I -m unittest discover -s sim/biasref-topology/tests -v

# --- job: layout-reduction-tests
step "layout-reduction-tests: lvs_reference unit tests" \
  python3 -I -m unittest discover -s layout/tests -v

# --- job: sim-record-paths-tests
step "sim-record-paths-tests: sim_record_paths reservation tests" \
  sim/tests/test-sim-record-paths.sh
step "sim-record-paths-tests: sim_run_deck sequential-deck gate tests (issue #300)" \
  sim/tests/test-sim-run-deck.sh
step "sim-pdk-identity-tests: installed-PDK identity preflight tests" \
  sim/tests/test-pdk-identity.sh
step "sim-core-envelope-lifecycle-tests: core-envelope record lifecycle tests" \
  sim/tests/test-core-envelope-lifecycle.sh
step "sim-corner-section-map-tests: canonical corner-label -> PDK-section map tests" \
  sim/tests/test-corner-section-maps.sh
step "sim-reducer-common-tests: shared reducer helper tests" \
  python3 -I -m unittest discover -s sim/tools/tests -v

# --- job: envelope-replay
step "envelope-replay: self-test" \
  python3 -I -m unittest discover -s sim/lna-core-envelope/tests -v
step "envelope-replay: check_envelope_replay.py" \
  python3 -I sim/lna-core-envelope/tests/check_envelope_replay.py

# --- job: breakdown-replay
step "breakdown-replay: unit tests and replay self-test" \
  python3 -I -m unittest discover -s sim/breakdown-extraction/tests -v
step "breakdown-replay: check_breakdown_replay.py" \
  python3 -I sim/breakdown-extraction/tests/check_breakdown_replay.py

# --- job: matching-feasibility-tests (issue #186)
step "matching-feasibility-tests: solver unit tests and committed-record replay" \
  python3 -I -m unittest discover -s sim/lna-matching-feasibility/tests -v

# --- job: record-citations
step "record-citations: self-test" .github/scripts/test-check-record-citations.sh
step "record-citations: check" .github/scripts/check-record-citations

# --- job: testbench-inventory (issue #195; read-only, no PDK/ngspice/klt)
step "testbench-inventory: self-test" .github/scripts/test-check-testbench-inventory.sh
step "testbench-inventory: check" python3 -I .github/scripts/check-testbench-inventory.py

# --- job: characterization-report (issue #233; read-only, no PDK/ngspice/klt)
step "characterization-report: self-test" .github/scripts/test-characterization-report.sh
step "characterization-report: check" python3 -I .github/scripts/characterization-report

# --- job: repo-hygiene (issue #217; read-only, no PDK/ngspice/klt)
step "repo-hygiene: self-test" .github/scripts/test-check-repo-hygiene.sh
step "repo-hygiene: check" python3 -I .github/scripts/check-repo-hygiene.py

# --- job: artifact-manifests (issue #222; read-only, no klt/broker/network)
step "artifact-manifests: self-test" .github/scripts/test-check-artifact-manifests.sh
step "artifact-manifests: check" python3 -I .github/scripts/check-artifact-manifests.py

# --- job: netlist-freshness
step "netlist-freshness: self-test" .github/scripts/test-check-netlist-freshness.sh
step "netlist-freshness: check" python3 -I .github/scripts/check-netlist-freshness
step "netlist-freshness: floating-node guard self-test" .github/scripts/test-check-floating-nodes.sh
step "netlist-freshness: floating-node guard" python3 -I .github/scripts/check-floating-nodes

# --- job: netlist-regen (issue #138; needs xschem 3.4.7 + the pinned PDK,
# only when the host has both -- CI provisions them via install-xschem and
# a block-scalar fetch step)
regen_pdk=0
if command -v xschem >/dev/null 2>&1 \
  && xschem --version 2>&1 | grep -q 'XSCHEM V3\.4\.7'; then
  for c in "${PDK_ROOT:-}" /usr/share/pdk /usr/local/share/pdk "$HOME/share/pdk" "$HOME/.ciel" "$HOME/.volare"; do
    if [ -n "$c" ] && [ -f "$c/ihp-sg13g2/libs.tech/xschem/xschemrc" ]; then
      export PDK_ROOT="$c" PDK=ihp-sg13g2; regen_pdk=1; break
    fi
  done
fi
if [ "$regen_pdk" -eq 1 ]; then
  step "netlist-regen: self-test" .github/scripts/test-check-netlist-regen.sh --require-tools
  step "netlist-regen: check" .github/scripts/check-netlist-regen
  step "netlist-regen: source audit bound to live tools" .github/scripts/design-source-audit check --live-tools
else
  skip "netlist-regen: self-test (need xschem 3.4.7 and the SG13G2 PDK; CI provisions both)"
  skip "netlist-regen: check (need xschem 3.4.7 and the SG13G2 PDK)"
fi

# --- job: design-source-audit (issue #182; klt cases of the self-test SKIP
# inside the script unless the pinned release klt is on PATH)
step "design-source-audit: self-test" .github/scripts/test-design-source-audit.sh
step "design-source-audit: check" .github/scripts/design-source-audit check

# --- job: sim-append-only (CI: pull_request only)
step "sim-append-only: self-test" .github/scripts/test-check-sim-append-only.sh
if [ -n "$base" ]; then
  step "sim-append-only: check --base $base" .github/scripts/check-sim-append-only --base "$base"
else
  skip "sim-append-only: check (pass --base <ref>, e.g. origin/main, to run it)"
fi

# --- job: layout-freshness
step "layout-freshness: self-test" .github/scripts/test-check-layout-freshness.sh
step "layout-freshness: check" .github/scripts/check-layout-freshness

# --- job: model-provenance
step "model-provenance: self-test" .github/scripts/test-check-model-sources.sh
step "model-provenance: check" sim/models/check_sources.sh

# --- job: results-table-drift
step "results-table-drift: renderer self-test" \
  python3 -I -m unittest discover -s sim/lna-characterization/tests -p test_render_results.py -v
step "results-table-drift: check" python3 -I sim/lna-characterization/render_results.py --check
step "results-table-drift: 290 K narrative check" python3 -I sim/lna-characterization/render_results.py --check-narrative

# --- job: local-checks-drift
step "local-checks-drift: self-test" .github/scripts/test-run-local-checks.sh

# --- job: shell-lint (pinned ShellCheck 0.10.0, never installed here)
if ! command -v shellcheck >/dev/null 2>&1; then
  skip "shell-lint (shellcheck not on PATH; CI uses pinned 0.10.0)"
elif ! shellcheck --version | grep -qx 'version: 0.10.0'; then
  skip "shell-lint (shellcheck is not exactly 0.10.0)"
else
  step "shell-lint: shellcheck 0.10.0" shell_lint
fi

echo
echo "=== summary"
printf '%s\n' "${summary[@]}"
echo "pass=$n_pass fail=$n_fail skip=$n_skip"
[ "$n_fail" -eq 0 ]
