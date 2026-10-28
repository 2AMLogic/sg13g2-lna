#!/usr/bin/env bash
# Self-test for check-repo-hygiene.py (issue #217) -- a freshness check that
# cannot fail is no check at all. Every case runs in a throwaway git
# repository holding only the files the checker reads; the real tree is only
# read. No klt, ngspice, PDK or network is involved.
#
# Cases:
#   1. pristine fixture                                  -> passes
#   2. check mode writes nothing                         -> tree unchanged
#   3. hygiene file missing / untracked (README,
#      LICENSE, spec, workflow, a command script)        -> FAILS
#   4. README lacks spec section / reproduction index /
#      block name; spec has no table; LICENSE empty      -> FAILS, --write refuses
#   5. declared command no longer run by its CI job      -> FAILS, --write refuses
#   6. hygiene file changed without refreshing           -> FAILS (stale hash)
#   7. stale envelope                                    -> FAILS
#   8. --write on a pristine fixture then check          -> passes after rebind

set -u

HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$HERE/../.." && pwd)"

pass=0
fail=0
BASE=""
trap '[ -n "$BASE" ] && rm -rf "$BASE" "$BASE".case.*' EXIT

ok()  { echo "PASS: $1"; pass=$((pass + 1)); }
bad() { echo "FAIL: $1" >&2; fail=$((fail + 1)); }

run_check() { # run_check <tree> [args...] -> sets OUT, RC
  local tree="$1"; shift
  OUT="$(cd "$tree" && env -i PATH=/usr/bin:/bin python3 -I "$tree/.github/scripts/check-repo-hygiene.py" "$@" 2>&1)"
  RC=$?
}

# expect <name> <0|1> <tree> [pattern ...]
expect() {
  local name="$1" want="$2" tree="$3"; shift 3
  run_check "$tree"
  local good=1 pat
  [ "$RC" -eq "$want" ] || good=0
  for pat in "$@"; do
    printf '%s' "$OUT" | grep -q -- "$pat" || good=0
  done
  if [ "$good" -eq 1 ]; then ok "$name"; else
    bad "$name (rc=$RC, wanted $want; patterns: $*)"; printf '%s\n' "$OUT" | head -8 >&2
  fi
}

# case_tree <label> -> prints a fresh copy of the committed fixture
# (called in $(...), so a counter would not survive: take a unique name from mktemp)
case_tree() {
  local d
  d="$(mktemp -d "$BASE.case.XXXXXX")"
  cp -a "$BASE/." "$d/"
  printf '%s' "$d"
}

commit_all() { (cd "$1" && git add -A && git -c user.email=t@t -c user.name=t commit -q -m fixture --allow-empty); }

build_base() {
  BASE="$(mktemp -d)"
  local f
  # Every tracked file the checker reads or hashes: the hygiene files, every
  # declared-command script, and the three outer bindings.
  while IFS= read -r f; do
    [ -n "$f" ] || continue
    mkdir -p "$BASE/$(dirname "$f")"
    cp -p "$ROOT/$f" "$BASE/$f"
  done < <(
    python3 -I - "$ROOT" <<'PY'
import importlib.util, sys
spec = importlib.util.spec_from_file_location("h", sys.argv[1] + "/.github/scripts/check-repo-hygiene.py")
h = importlib.util.module_from_spec(spec)
spec.loader.exec_module(h)
paths = set(h.HYGIENE_FILES) | {h.MANIFEST, h.REPORT, h.INVENTORY, h.ENVELOPE}
for _, cmd, _ in h.DECLARED_COMMANDS:
    paths.update(t for t in cmd.split() if t.startswith((".github/", "sim/")))
print("\n".join(sorted(paths)))
PY
  )
  (cd "$BASE" && git init -q && git add -A && git -c user.email=t@t -c user.name=t commit -q -m base)
}

# edit <tree> <file> <python expression on string s> ; then commit
edit() {
  python3 -I - "$1/$2" "$3" <<'PY'
import sys
p, expr = sys.argv[1], sys.argv[2]
s = open(p).read()
try:
    s = eval(expr)
except SyntaxError:  # statement form: must leave the new text in `s`
    ns = {"s": s}
    exec(expr, ns)
    s = ns["s"]
open(p, "w").write(s)
PY
  commit_all "$1"
}

build_base

# 1. pristine
expect "pristine fixture passes" 0 "$BASE" "OK: repo-hygiene inventory is fresh"

# 2. check mode writes nothing
T="$(case_tree)"
before="$(cd "$T" && find . -path ./.git -prune -o -type f -print0 | sort -z | xargs -0 sha256sum | sha256sum)"
run_check "$T"
after="$(cd "$T" && find . -path ./.git -prune -o -type f -print0 | sort -z | xargs -0 sha256sum | sha256sum)"
if [ "$before" = "$after" ] && [ "$RC" -eq 0 ]; then ok "check mode leaves the tree unchanged"; else bad "check mode modified the tree or failed (rc=$RC)"; fi

# 3. missing / untracked hygiene files
for f in README.md LICENSE spec/target-spec.md .github/workflows/signoff.yml \
         .github/scripts/check-signoff.sh sim/models/check_sources.sh; do
  T="$(case_tree)"; (cd "$T" && git rm -q "$f" && git -c user.email=t@t -c user.name=t commit -q -m rm)
  expect "missing $f fails" 1 "$T" "AUDIT:.*$f"
  T="$(case_tree)"; (cd "$T" && git rm -q --cached "$f" && git -c user.email=t@t -c user.name=t commit -q -m untrack)
  expect "untracked $f fails" 1 "$T" "AUDIT:.*$f.*not tracked"
done

# 4. content structure defects
T="$(case_tree)"; edit "$T" README.md 's.replace("## Target specification", "## Specs")'
expect "README without spec section fails" 1 "$T" "Target specification"
run_check "$T" --write
[ "$RC" -eq 1 ] && ok "--write refuses README without spec section" || bad "--write accepted README without spec section"

T="$(case_tree)"; edit "$T" README.md 's.replace("## Reproducing the results", "## Other")'
expect "README without reproduction index fails" 1 "$T" "Reproducing the results"

T="$(case_tree)"; edit "$T" README.md 's.replace("# sg13g2-lna", "# something-else", 1)'
expect "README not naming the block fails" 1 "$T" "does not name the block"

T="$(case_tree)"; edit "$T" spec/target-spec.md 's.replace("|", "/")'
expect "spec without a table fails" 1 "$T" "contains no markdown table"

T="$(case_tree)"; edit "$T" LICENSE '""'
expect "empty LICENSE fails" 1 "$T" "LICENSE is empty"

# 5. declared command not run by CI
T="$(case_tree)"; edit "$T" .github/workflows/signoff.yml 's.replace("run: .github/scripts/check-signoff.sh", "run: true")'
expect "declared command dropped from CI fails" 1 "$T" "not run by CI job 'signoff'"
run_check "$T" --write
[ "$RC" -eq 1 ] && ok "--write refuses a declared command CI does not run" || bad "--write accepted a dropped CI command"

T="$(case_tree)"; edit "$T" .github/workflows/signoff.yml 's.replace("run: sim/models/check_sources.sh", "run: sim/models/check_sources.sh --skip")'
expect "declared command altered in CI fails" 1 "$T" "not run by CI job 'model-provenance'"

# 6. stale hash: any inventoried file or command script changed
for f in README.md LICENSE spec/target-spec.md .github/scripts/check-signoff.sh sim/models/check_sources.sh; do
  T="$(case_tree)"; edit "$T" "$f" 's + "\n# touched\n"'
  expect "changed $f without refresh is stale" 1 "$T" "STALE: $f" "is stale"
done
T="$(case_tree)"; edit "$T" .github/workflows/signoff.yml 's + "\n# touched\n"'
expect "changed workflow without refresh is stale" 1 "$T" "STALE: .github/workflows/signoff.yml"

# 7. outer bindings
T="$(case_tree)"; edit "$T" signoff/repo-hygiene/envelope.json 's.replace("\"pass\"", "\"fail\"")'
expect "stale envelope fails" 1 "$T" "does not equal the envelope"

# 8. --write rebinds after a legitimate change
T="$(case_tree)"; edit "$T" README.md 's + "\n"'
run_check "$T" --write
if [ "$RC" -eq 0 ]; then ok "--write regenerates after a change"; else bad "--write failed (rc=$RC)"; fi
run_check "$T"
if [ "$RC" -eq 0 ]; then ok "after --write the check passes"; else bad "check fails after --write (rc=$RC)"; printf '%s\n' "$OUT" | head -5 >&2; fi

echo
echo "pass=$pass fail=$fail"
[ "$fail" -eq 0 ]
