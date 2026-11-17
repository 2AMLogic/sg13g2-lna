#!/usr/bin/env bash
# check-klt-pin.sh — fail when the klt release that grades the signoff
# (.github/workflows/signoff.yml) differs from the one that mints the cited
# layout evidence (layout/run_flow.sh KLT_RELEASE), so the skew of issue #100
# cannot recur silently. Also checks check-signoff.sh, signoff/README.md,
# the KLayout engine pin KLAYOUT_PIN (issue #294), and the prose
# klayout-tools==/klayout== pins in README.md and layout/README.md (#320).
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
# issue #294: the same two sites also share the KLayout engine pin
# (uvx --with klayout==$KLAYOUT_PIN); keep them from skewing the same way.
kflow="$(sed -n 's/^KLAYOUT_PIN="\([0-9][0-9.]*\)"$/\1/p' layout/run_flow.sh)"
[ -n "$kflow" ] || { echo "FAIL: no KLAYOUT_PIN in layout/run_flow.sh" >&2; rc=1; }
krunner="$(sed -n 's/^KLAYOUT_PIN = "\([0-9][0-9.]*\)".*$/\1/p' layout/run_native_drc.py)"
[ -n "$krunner" ] || { echo "FAIL: no KLAYOUT_PIN in layout/run_native_drc.py" >&2; rc=1; }
[ "$krunner" = "$kflow" ] || { echo "FAIL: layout/run_native_drc.py pins KLayout '${krunner:-nothing}', layout/run_flow.sh KLAYOUT_PIN is ${kflow:-nothing}" >&2; rc=1; }
# issue #320: the prose klayout-tools== pins in the two top-level READMEs
# follow the same rule; the historical dev-build string (0.9.2.dev1022+g…)
# carries no klayout-tools== prefix, so it never matches.
for f in .github/workflows/signoff.yml .github/scripts/check-signoff.sh signoff/README.md README.md layout/README.md; do
  pins="$(grep -o 'klayout-tools==[0-9][0-9.]*' "$f" | sort -u | tr '\n' ' ')"
  [ "$pins" = "klayout-tools==$flow " ] || {
    echo "FAIL: $f pins '${pins:-nothing}', layout/run_flow.sh KLT_RELEASE is $flow" >&2
    rc=1
  }
done
# issue #320: the same two READMEs also carry the KLayout engine pin in
# prose (…pip install klayout==…). 'klayout==' never matches
# 'klayout-tools==', so this loop is independent of the one above.
for f in README.md layout/README.md; do
  kpins="$(grep -o 'klayout==[0-9][0-9.]*' "$f" | sort -u | tr '\n' ' ')"
  [ "$kpins" = "klayout==$kflow " ] || {
    echo "FAIL: $f pins KLayout '${kpins:-nothing}', layout/run_flow.sh KLAYOUT_PIN is $kflow" >&2
    rc=1
  }
done
[ "$rc" -eq 0 ] && echo "ok: klt pin $flow is consistent"
exit "$rc"
