#!/usr/bin/env bash
# Self-test for sim/models/check_sources.sh: prove the gate can fail (issue #84).
# Cases (each on a throwaway copy of sim/models/; the real tree is untouched):
#   1. pristine copy                              -> passes (0)
#   2. one model byte flipped                     -> FAILS (1), names file + both hashes
#   3. model file missing                         -> FAILS (1)
#   4. SOURCE.md with no sha256 row at all        -> FAILS (2)
#   5. section whose sha256 row is deleted        -> FAILS (1), even if another row exists
#   6. model modified AND sha256 row re-stamped   -> passes (0)
#   7. real tree still passes and is unmodified
set -u
HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$HERE/../.." && pwd)"
SRC="$ROOT/sim/models"
MODEL=sg13g2_inductor_em.spice
[ -f "$SRC/check_sources.sh" ] || { echo "FAIL: $SRC/check_sources.sh missing" >&2; exit 1; }
TMP="$(mktemp -d)"; trap 'rm -rf "$TMP"' EXIT
before="$(cd "$ROOT" && git status --porcelain -- sim/models 2>/dev/null)"
pass=0; fail=0
mk() { d="$TMP/$1"; mkdir -p "$d"
  cp "$SRC/check_sources.sh" "$SRC/SOURCE.md" "$SRC/$MODEL" "$d/"; }
ok() { echo "PASS: $1"; pass=$((pass+1)); }
bad() { echo "FAIL: $1"; fail=$((fail+1)); }
# run <label> <wanted-exit> <dir>; output left in $TMP/out
run() { bash "$3/check_sources.sh" >"$TMP/out" 2>&1; got=$?
  if [ "$got" -eq "$2" ]; then ok "$1"; else bad "$1 (got $got, wanted $2)"; fi; }

mk ok; run "pristine copy" 0 "$TMP/ok"

mk flip; printf 'x' >> "$TMP/flip/$MODEL"
run "modified model" 1 "$TMP/flip"
want="$(grep -o 'File sha256 | `[0-9a-f]*' "$SRC/SOURCE.md" | grep -o '[0-9a-f]\{64\}')"
got="$(sha256sum "$TMP/flip/$MODEL" | awk '{print $1}')"
if grep -q "$MODEL" "$TMP/out" && grep -q "$want" "$TMP/out" && grep -q "$got" "$TMP/out"
then ok "failure names model, recorded and actual hash"
else bad "failure output lacks model name or hashes"; fi

mk gone; rm "$TMP/gone/$MODEL"
run "missing model" 1 "$TMP/gone"

mk none; sed -i '/File sha256/d' "$TMP/none/SOURCE.md"
run "no sha256 rows at all" 2 "$TMP/none"

# Second section keeps a valid row while the first loses its own.
mk sec; sed -i '/File sha256/d' "$TMP/sec/SOURCE.md"
printf '\n## other.spice\n\n| Field | Value |\n|---|---|\n| File sha256 | `%064d` |\n' 0 >> "$TMP/sec/SOURCE.md"
: > "$TMP/sec/other.spice"
run "section with deleted sha256 row" 1 "$TMP/sec"

mk stamp; printf 'x' >> "$TMP/stamp/$MODEL"
new="$(sha256sum "$TMP/stamp/$MODEL" | awk '{print $1}')"
sed -i "s/\`$want\`/\`$new\`/" "$TMP/stamp/SOURCE.md"
run "legitimate re-stamp" 0 "$TMP/stamp"

if bash "$SRC/check_sources.sh" >/dev/null 2>&1; then ok "real tree passes"; else bad "real tree fails"; fi
after="$(cd "$ROOT" && git status --porcelain -- sim/models 2>/dev/null)"
if [ "$before" = "$after" ]; then ok "real tree unmodified"; else bad "real tree modified"; fi

echo "$pass passed, $fail failed"
[ "$fail" -eq 0 ]
