#!/usr/bin/env bash
# check-klt-pin.sh — fail when the klt release that grades the signoff
# (.github/workflows/signoff.yml) differs from the one that mints the cited
# layout evidence (layout/run_flow.sh KLT_RELEASE), so the skew of issue #100
# cannot recur silently. Also checks check-signoff.sh and signoff/README.md.
set -u
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
[ "${1:-}" = "--root" ] && [ -n "${2:-}" ] && ROOT="$2"
cd "$ROOT" || exit 1
flow="$(sed -n 's/^KLT_RELEASE="\([0-9][0-9.]*\)"$/\1/p' layout/run_flow.sh)"
[ -n "$flow" ] || { echo "FAIL: no KLT_RELEASE in layout/run_flow.sh" >&2; exit 1; }
rc=0
# issue #185: run_native_drc.py pins the same release for native-deck runs;
# its KLT_RELEASE must not skew from run_flow.sh's.
runner="$(sed -n 's/^KLT_RELEASE = "\([0-9][0-9.]*\)".*$/\1/p' layout/run_native_drc.py)"
[ -n "$runner" ] || { echo "FAIL: no KLT_RELEASE in layout/run_native_drc.py" >&2; rc=1; }
[ "$runner" = "$flow" ] || { echo "FAIL: layout/run_native_drc.py pins '${runner:-nothing}', layout/run_flow.sh KLT_RELEASE is $flow" >&2; rc=1; }
for f in .github/workflows/signoff.yml .github/scripts/check-signoff.sh signoff/README.md; do
  pins="$(grep -o 'klayout-tools==[0-9][0-9.]*' "$f" | sort -u | tr '\n' ' ')"
  [ "$pins" = "klayout-tools==$flow " ] || {
    echo "FAIL: $f pins '${pins:-nothing}', layout/run_flow.sh KLT_RELEASE is $flow" >&2
    rc=1
  }
done
[ "$rc" -eq 0 ] && echo "ok: klt pin $flow is consistent"
exit "$rc"
