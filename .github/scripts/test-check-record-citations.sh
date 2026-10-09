#!/usr/bin/env bash
# Self-test for check-record-citations: prove the gate can fail.
# Cases (throwaway git repos):
#   1. valid citation (id present under sim/x/records/)  -> passes
#   2. dangling citation                                  -> FAILS
#   3. dangling citation listed in allowlist              -> passes
#   4. allowlist entry without a reason                   -> FAILS
set -u
HERE="$(cd "$(dirname "$0")" && pwd)"
CHECKER="$HERE/check-record-citations"
[ -x "$CHECKER" ] || { echo "FAIL: $CHECKER not executable" >&2; exit 1; }
TMP="$(mktemp -d)"; trap 'rm -rf "$TMP"' EXIT
pass=0; fail=0
VALID=20260101-120000-abcdef1
DANGLE=20260202-130000-1234567

mk() { # mk <dir> <cited-id> ; creates tracked repo
  d="$TMP/$1"; mkdir -p "$d/sim/x/records" "$d/.github"
  : > "$d/sim/x/records/$VALID.md"
  echo "See record $2 for evidence." > "$d/doc.md"
  git -C "$d" init -q
  git -C "$d" add -A
}
run() { # run <name> <expect 0|1> <dir>
  if "$CHECKER" --root "$3" >/dev/null 2>&1; then got=0; else got=1; fi
  if [ "$got" -eq "$2" ]; then echo "PASS: $1"; pass=$((pass+1))
  else echo "FAIL: $1 (exit-class $got, wanted $2)"; fail=$((fail+1)); fi
}

mk valid "$VALID"; run "valid citation" 0 "$TMP/valid"
mk dangling "$DANGLE"; run "dangling citation" 1 "$TMP/dangling"
mk allowed "$DANGLE"
echo "$DANGLE format example in test" > "$TMP/allowed/.github/record-citation-allowlist.txt"
git -C "$TMP/allowed" add -A; run "allowlisted citation" 0 "$TMP/allowed"
mk noreason "$DANGLE"
echo "$DANGLE" > "$TMP/noreason/.github/record-citation-allowlist.txt"
git -C "$TMP/noreason" add -A; run "allowlist entry without reason" 1 "$TMP/noreason"

echo "$pass passed, $fail failed"
[ "$fail" -eq 0 ]
