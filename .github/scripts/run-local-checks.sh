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

# --- job: signoff
step "signoff: check-klt-pin.sh" .github/scripts/check-klt-pin.sh
klt_pin="$(grep -Eo 'klayout-tools==[0-9][0-9.]*' .github/workflows/signoff.yml | head -n 1 | cut -d= -f3)"
klt_have="$(command -v klt >/dev/null 2>&1 && klt --version 2>/dev/null | head -n 1)"
if [ -n "$klt_pin" ] && [ "$klt_have" = "klt $klt_pin" ]; then
  step "signoff: test-check-signoff.sh" .github/scripts/test-check-signoff.sh
  step "signoff: check-signoff.sh" .github/scripts/check-signoff.sh
else
  skip "signoff: test-check-signoff.sh (need release klt $klt_pin on PATH, have: ${klt_have:-none}; CI pip-installs it)"
  skip "signoff: check-signoff.sh (need release klt $klt_pin on PATH)"
fi

# --- job: reduction-tests
step "reduction-tests: lna-characterization unit tests" \
  python3 -I -m unittest discover -s sim/lna-characterization/tests -v

# --- job: hbt-reduction-tests
step "hbt-reduction-tests: hbt-characterization unit tests" \
  python3 -I -m unittest discover -s sim/hbt-characterization/tests -v

# --- job: layout-reduction-tests
step "layout-reduction-tests: lvs_reference unit tests" \
  python3 -I -m unittest discover -s layout/tests -v

# --- job: sim-record-paths-tests
step "sim-record-paths-tests: sim_record_paths reservation tests" \
  sim/tests/test-sim-record-paths.sh

# --- job: envelope-replay
step "envelope-replay: self-test" \
  python3 -I -m unittest discover -s sim/lna-core-envelope/tests -v
step "envelope-replay: check_envelope_replay.py" \
  python3 -I sim/lna-core-envelope/tests/check_envelope_replay.py

# --- job: record-citations
step "record-citations: self-test" .github/scripts/test-check-record-citations.sh
step "record-citations: check" .github/scripts/check-record-citations

# --- job: netlist-freshness
step "netlist-freshness: self-test" .github/scripts/test-check-netlist-freshness.sh
step "netlist-freshness: check" python3 -I .github/scripts/check-netlist-freshness

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
