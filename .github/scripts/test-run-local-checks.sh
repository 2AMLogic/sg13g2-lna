#!/usr/bin/env bash
# Drift self-test for run-local-checks.sh (issue #108).
# Every check/test script the workflow runs must also appear in the local
# runner. Cases:
#   1. all workflow-referenced scripts appear in the runner       -> passes
#   2. a token removed from a temp copy of the runner             -> FAILS (detected)
#   3. extraction found a sane number of tokens (guards a vacuous pass)
set -u
HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$HERE/../.." && pwd)"
WF="$ROOT/.github/workflows/signoff.yml"
RUNNER="$HERE/run-local-checks.sh"
[ -f "$WF" ] || { echo "FAIL: $WF missing" >&2; exit 1; }
[ -f "$RUNNER" ] || { echo "FAIL: $RUNNER missing" >&2; exit 1; }
TMP="$(mktemp -d)"; trap 'rm -rf "$TMP"' EXIT
pass=0; fail=0
ok() { echo "PASS: $1"; pass=$((pass+1)); }
bad() { echo "FAIL: $1"; fail=$((fail+1)); }

# Tokens come from `run:` lines only (comments mention scripts too).
# check-signoff-scope.py is invoked by check-signoff.sh, not the workflow, so
# it never appears here and needs no allowlist.
tokens="$TMP/tokens"
grep -E '^[[:space:]]*run:' "$WF" \
  | grep -Eo '(test-)?check-[A-Za-z0-9_.-]+|check_sources\.sh|check_envelope_replay\.py|sim/[a-z-]+/tests' \
  | sort -u > "$tokens"

# missing <runner> : print tokens absent from the runner
missing() { while IFS= read -r t; do
    grep -qF -- "$t" "$1" || echo "$t"
  done < "$tokens"; }

n="$(wc -l < "$tokens")"
if [ "$n" -ge 12 ]; then ok "extracted $n workflow-referenced tokens"
else bad "only $n tokens extracted from $WF (extraction broken?)"; fi

m="$(missing "$RUNNER")"
if [ -z "$m" ]; then ok "runner covers every workflow-referenced script"
else bad "runner is missing: $(echo "$m" | tr '\n' ' ')"; fi

# Negative case: drop each of two tokens from a copy; drift must be detected.
for t in check-record-citations check_sources.sh; do
  grep -vF -- "$t" "$RUNNER" > "$TMP/mutant.sh"
  m="$(missing "$TMP/mutant.sh")"
  if echo "$m" | grep -qxF -- "$t"; then ok "drift detected when '$t' removed"
  else bad "removing '$t' from the runner was not detected"; fi
done

echo "passed=$pass failed=$fail"
[ "$fail" -eq 0 ]
