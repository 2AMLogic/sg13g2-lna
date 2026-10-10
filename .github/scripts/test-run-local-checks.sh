#!/usr/bin/env bash
# Drift self-test for run-local-checks.sh (issue #108).
#
# Compares whole commands, not tokens. The workflow's single-line `run:`
# commands (with "origin/${{ github.base_ref }}" read as the runner's
# "$base") must equal, in order and exactly once each, the commands the
# runner passes to `step` (text after the quoted label, `\` continuations
# joined; comments and `skip` lines never count).
#
# Block-scalar steps (`run: |` / `run: >`) are matched by step name and each
# one must be handled explicitly below; an unknown one FAILS loudly:
#   - "Install pinned ShellCheck 0.10.0": an install, never mirrored.
#   - "Install xschem" / "Fetch pinned IHP-Open-PDK v0.3.0": installs, never
#     mirrored (the runner probes for xschem + the PDK and SKIPs when absent).
#   - "Installed ShellCheck is exactly 0.10.0": runner must probe the same
#     `shellcheck --version | grep -qx 'version: 0.10.0'`.
#   - "Lint tracked first-party Bash": body (minus `set -euo pipefail`,
#     `exit 1` read as `return 1`) must equal the runner's shell_lint()
#     body line for line, and the runner must run `step ... shell_lint`.
# Single-line install steps ("Install pinned klt") are likewise never mirrored.
#
# Cases:
#   1. the committed runner matches the workflow               -> passes
#   2. each `step` statement deleted, one at a time, from a copy -> FAILS
#   3. a line removed from the copied shell-lint discovery       -> FAILS
#   4. an unhandled `run: |` step added to a workflow copy       -> FAILS
#   5. extraction found a sane number of commands (no vacuous pass)
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
# Literal strings (no expansion intended): the workflow's base-ref argument
# and the runner's equivalent.
# shellcheck disable=SC2016
BASE_WF='"origin/${{ github.base_ref }}"'
# shellcheck disable=SC2016
BASE_RN='"$base"'

# Workflow -> records, one per line:
#   CMD<TAB><step name><TAB><command>      single-line run:
#   BLOCK<TAB><step name>                  run: | or run: >, then
#   BODY<TAB><line>                        its body, leading whitespace trimmed
wf_records() {
  awk '
    function trim(s) { sub(/^[[:space:]]+/, "", s); sub(/[[:space:]]+$/, "", s); return s }
    inblock {
      if ($0 ~ /^[[:space:]]*$/) next
      match($0, /^[[:space:]]*/)
      if (RLENGTH > runind) { print "BODY\t" trim($0); next }
      inblock = 0
    }
    /^[[:space:]]*- / {
      name = ""
      if ($0 ~ /^[[:space:]]*- name:/) { name = $0; sub(/^[[:space:]]*- name:[[:space:]]*/, "", name) }
    }
    /^[[:space:]]*(- )?run:/ {
      match($0, /^[[:space:]]*(- )?/); runind = RLENGTH
      v = $0; sub(/^[[:space:]]*(- )?run:[[:space:]]*/, "", v); v = trim(v)
      if (v ~ /^[|>]/) { inblock = 1; print "BLOCK\t" name; next }
      print "CMD\t" name "\t" v
    }
  ' "$1"
}

# Runner -> "<line no><TAB><command>" for every `step` statement.
runner_steps() {
  awk '
    function trim(s) { sub(/^[[:space:]]+/, "", s); sub(/[[:space:]]+$/, "", s); return s }
    function take(s) {
      s = trim(s)
      if (s ~ /\\$/) { sub(/[[:space:]]*\\$/, "", s); more = 1 } else more = 0
      cur = (cur == "" ? s : cur " " s)
      if (!more) { print start "\t" cur; cur = ""; cont = 0 } else cont = 1
    }
    cont { take($0); next }
    /^[[:space:]]*step "[^"]*"/ {
      start = NR; cur = ""; s = $0
      sub(/^[[:space:]]*step "[^"]*"/, "", s); take(s)
    }
  ' "$1"
}

# check <workflow> <runner>: print every drift problem; return 1 if any.
check() {
  local wf="$1" rn="$2" d kind name cmd line probs=0 inlint=0
  d="$(mktemp -d -p "$TMP")"
  : > "$d/wf"; : > "$d/lint"
  wf_records "$wf" > "$d/rec"
  while IFS=$'\t' read -r kind name cmd; do
    case "$kind" in
      CMD)
        inlint=0
        case "$name" in "Install pinned klt") continue ;; esac
        printf '%s\n' "${cmd//"$BASE_WF"/"$BASE_RN"}" >> "$d/wf" ;;
      BLOCK)
        inlint=0
        case "$name" in
          "Install pinned ShellCheck 0.10.0") ;;
          "Install xschem") ;;
          "Fetch pinned IHP-Open-PDK v0.3.0") ;;
          "Installed ShellCheck is exactly 0.10.0")
            grep -qF "shellcheck --version | grep -qx 'version: 0.10.0'" "$rn" \
              || { echo "runner does not probe for ShellCheck exactly 0.10.0"; probs=1; } ;;
          "Lint tracked first-party Bash") inlint=1 ;;
          *) echo "unhandled block-scalar step '$name' (teach this test how the runner mirrors it)"; probs=1 ;;
        esac ;;
      BODY)
        line="$name"
        if [ "$inlint" -eq 1 ] && [ "$line" != "set -euo pipefail" ]; then
          [ "$line" = "exit 1" ] && line="return 1"
          printf '%s\n' "$line" >> "$d/lint"
        fi ;;
    esac
  done < "$d/rec"

  runner_steps "$rn" | cut -f2- > "$d/rn_all"
  grep -vxF shell_lint "$d/rn_all" > "$d/rn"
  while IFS= read -r cmd; do
    grep -qxF -- "$cmd" "$d/rn" || { echo "runner has no step running: $cmd"; probs=1; }
  done < "$d/wf"
  if ! diff -q "$d/wf" "$d/rn" >/dev/null; then
    echo "runner step commands differ from the workflow's (order/duplicates/extras):"
    diff "$d/wf" "$d/rn" | sed 's/^/  /'
    probs=1
  fi
  [ "$(grep -cxF shell_lint "$d/rn_all")" -eq 1 ] \
    || { echo "runner must run exactly one 'step ... shell_lint'"; probs=1; }

  awk '/^shell_lint\(\) \{/ {f=1; next} f && /^\}/ {f=0} f' "$rn" \
    | sed -e 's/^[[:space:]]*//' -e 's/[[:space:]]*$//' \
    | grep -vE '^(local |$)' > "$d/fn"
  if [ ! -s "$d/lint" ] || ! diff -q "$d/lint" "$d/fn" >/dev/null; then
    echo "runner shell_lint() differs from the workflow lint block:"
    diff "$d/lint" "$d/fn" | sed 's/^/  /'
    probs=1
  fi
  [ "$probs" -eq 0 ]
}

# 5. sanity: extraction is not vacuous.
n="$(wf_records "$WF" | grep -c '^CMD')"
s="$(runner_steps "$RUNNER" | wc -l)"
if [ "$n" -ge 17 ] && [ "$s" -ge 18 ]; then ok "extracted $n workflow run: commands, $s runner steps"
else bad "only $n workflow commands / $s runner steps extracted (extraction broken?)"; fi

# 1. committed runner matches.
if out="$(check "$WF" "$RUNNER")"; then ok "runner invokes every workflow command exactly as CI does"
else bad "runner drifted from the workflow:"; echo "$out"; fi

# 2. delete each step statement (with its continuation lines), one at a time.
while IFS=$'\t' read -r lno cmd; do
  awk -v n="$lno" 'NR == n {skip = 1} skip {c = /\\[[:space:]]*$/; if (!c) skip = 0; next} 1' \
    "$RUNNER" > "$TMP/mutant.sh"
  if cmp -s "$RUNNER" "$TMP/mutant.sh"; then bad "mutant for line $lno is identical (bug in test)"
  elif check "$WF" "$TMP/mutant.sh" >/dev/null; then bad "deleting step at line $lno ($cmd) was not detected"
  else ok "drift detected when step at line $lno is deleted: $cmd"; fi
done < <(runner_steps "$RUNNER")

# 3. drop one line of the copied discovery snippet.
grep -vF "sort -z -u" "$RUNNER" > "$TMP/mutant.sh"
if check "$WF" "$TMP/mutant.sh" >/dev/null; then bad "editing the shell_lint discovery snippet was not detected"
else ok "drift detected when the shell_lint discovery snippet is edited"; fi

# 4. an unhandled block-scalar step must fail loudly, not be skipped.
{ cat "$WF"; printf '      - name: Some future multi-line step\n        run: |\n          ./new-check\n'; } > "$TMP/wf.yml"
if out="$(check "$TMP/wf.yml" "$RUNNER")"; then bad "unhandled 'run: |' step was silently ignored"
elif echo "$out" | grep -qF "unhandled block-scalar step 'Some future multi-line step'"; then
  ok "unhandled 'run: |' step fails loudly"
else bad "unhandled 'run: |' step failed for the wrong reason: $out"; fi

echo "passed=$pass failed=$fail"
[ "$fail" -eq 0 ]
