#!/usr/bin/env bash
# Self-test for design-source-audit: prove the item-1 gate can fail (issue #182).
# Every case runs on a throwaway copy of the inputs (never the checkout).
#
# `check` cases (PDK-free):
#   1. pristine copy                                        -> passes
#   2. wiring-only schematic edit (listed input stale)      -> FAILS
#   3. symbol / xschemrc / derived-netlist byte edit        -> FAILS (each)
#   4. listed input missing; unlisted design/ file added    -> FAILS (each)
#   5. inventory lists a stale hash but the audit is re-pinned to the
#      mutated inventory (outer binding consistent)         -> FAILS
#   6. inventory mutated, audit untouched                   -> FAILS
#   7. audit pin stale                                      -> FAILS
#   8. PDK pin or regen-check script drift                  -> FAILS (each)
# `write` cases (regeneration gate, stub check-netlist-regen):
#   9. gate exits non-zero -> refuses to write (exit 3); gate exits 0 -> writes
#      files that then pass `check`
# klt cases (expected release derived from layout/run_flow.sh KLT_RELEASE;
# SKIP locally when that release is not on PATH — absent or wrong-version
# alike — while under CI/GITHUB_ACTIONS an absent klt FAILs as well, not
# just a wrong-version one: the design-source-audit job pip-installs the
# pin immediately before this suite, so any mismatch there is skew;
# issue #294):
#  10. fresh tree renders item 1 met from the klt signoff --attest
#      envelope (issue #238), with artifact_binding         -> met
#  11. attest inventory bytes mutated, citation not updated -> item 1 NOT met
# meta-case (re-invokes this suite as a child; LNA_AUDIT_SELFTEST_CHILD
# guards that child against recursing):
#  12. absent klt is fatal under CI, SKIPs locally              -> (each)
set -u
HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$HERE/../.." && pwd)"
TOOL="$HERE/design-source-audit"
[ -x "$TOOL" ] || { echo "FAIL: $TOOL not executable" >&2; exit 1; }
TMP="$(mktemp -d)"; trap 'rm -rf "$TMP"' EXIT
pass=0; fail=0; skip=0
mk() {
  d="$TMP/$1"; mkdir -p "$d/design/netlist" "$d/sim" "$d/signoff/design-source" "$d/.github/scripts"
  cp "$ROOT"/design/lna.sch "$ROOT"/design/lna.sym "$ROOT"/design/xschemrc "$d/design/"
  cp "$ROOT/design/netlist/lna.spice" "$d/design/netlist/"
  cp "$ROOT/sim/pdk.json" "$d/sim/"
  cp "$ROOT/.github/scripts/check-netlist-regen" "$d/.github/scripts/"
  cp "$ROOT"/signoff/manifest.json "$ROOT"/signoff/design-evidence-tiers.md "$d/signoff/"
  cp "$ROOT"/signoff/design-source/*.json "$d/signoff/design-source/"
  mkdir -p "$d/signoff/attest"; cp "$ROOT"/signoff/attest/*.json "$d/signoff/attest/"
  git init -q "$d"   # scope:"repo" input paths resolve against the nearest .git
}
expect() { # <label> <want-rc> <root> [args...]
  label="$1"; want="$2"; r="$3"; shift 3
  python3 -I "$TOOL" "$@" --root "$r" >/dev/null 2>"$TMP/err"; got=$?
  if [ "$got" -eq "$want" ]; then echo "PASS: $label"; pass=$((pass+1))
  else echo "FAIL: $label (got $got, wanted $want)"; sed 's/^/    /' "$TMP/err"; fail=$((fail+1)); fi
}
# repin <root>: rewrite the audit so its outer binding follows the current
# inventory bytes (simulates a careless refresh).
repin() {
  python3 -I - "$1" <<'PY'
import hashlib, json, sys
r = sys.argv[1]
h = "sha256:" + hashlib.sha256(open(r + "/signoff/design-source/inventory.json", "rb").read()).hexdigest()
a = json.load(open(r + "/signoff/design-source/audit.json"))
a["provenance"]["input"]["content_hash"] = h
open(r + "/signoff/design-source/audit.json", "w").write(json.dumps(a, indent=2, sort_keys=True) + "\n")
PY
}

mk ok; expect "pristine copy" 0 "$TMP/ok" check

mk wire; printf 'N 100 100 200 100 {lab=EXTRA}\n' >> "$TMP/wire/design/lna.sch"
expect "wiring-only schematic edit makes the audit stale" 1 "$TMP/wire" check
mk sym; printf '\n' >> "$TMP/sym/design/lna.sym"
expect "symbol byte edit" 1 "$TMP/sym" check
mk rc; printf '# x\n' >> "$TMP/rc/design/xschemrc"
expect "xschemrc byte edit" 1 "$TMP/rc" check
mk net; printf '* x\n' >> "$TMP/net/design/netlist/lna.spice"
expect "derived netlist byte edit" 1 "$TMP/net"  check

mk miss; rm "$TMP/miss/design/lna.sym"
expect "listed input missing" 1 "$TMP/miss" check
mk extra; printf 'v {xschem version=3.4.4}\n' > "$TMP/extra/design/extra.sch"
expect "unlisted design/ file" 1 "$TMP/extra" check

mk stalelisted
sed -i '0,/"sha256": "sha256:[0-9a-f]*"/s//"sha256": "sha256:0000000000000000000000000000000000000000000000000000000000000000"/' \
  "$TMP/stalelisted/signoff/design-source/inventory.json"
repin "$TMP/stalelisted"
expect "stale listed hash with consistent outer bindings" 1 "$TMP/stalelisted" check

mk inv; sed -i 's/"bytes": [0-9]*/"bytes": 1/' "$TMP/inv/signoff/design-source/inventory.json"
expect "inventory mutated without updating citation" 1 "$TMP/inv" check

mk aud; sed -i 's/"content_hash": "sha256:[0-9a-f]*"/"content_hash": "sha256:00"/' "$TMP/aud/signoff/design-source/audit.json"
expect "audit pins a stale inventory hash" 1 "$TMP/aud" check

mk pdk; sed -i 's/"release_tag": "v0.3.0"/"release_tag": "v0.4.0"/' "$TMP/pdk/sim/pdk.json"
expect "PDK pin drift" 1 "$TMP/pdk" check
mk chk; printf '# edited\n' >> "$TMP/chk/.github/scripts/check-netlist-regen"
expect "regen-check script drift" 1 "$TMP/chk" check

# write: stub regeneration gate (reads XSCHEM_VERSION/PDK_VARIANT like the real one)
stub() { # <root> <exit-code>
  printf '#!/usr/bin/env python3\nimport sys\nXSCHEM_VERSION = "3.4.4"\nPDK_VARIANT = "ihp-sg13g2"\nsys.exit(%s)\n' "$2" \
    > "$1/.github/scripts/check-netlist-regen"
}
mk wfail; stub "$TMP/wfail" 4; rm -rf "$TMP/wfail/signoff/design-source"
expect "write refuses when the regeneration gate fails" 3 "$TMP/wfail" write
if [ ! -e "$TMP/wfail/signoff/design-source/inventory.json" ]; then echo "PASS: nothing written on gate failure"; pass=$((pass+1))
else echo "FAIL: files written despite failed gate"; fail=$((fail+1)); fi
mk wok; stub "$TMP/wok" 0
expect "write succeeds when the gate passes" 0 "$TMP/wok" write
repin "$TMP/wok"
expect "written audit passes check once cited" 0 "$TMP/wok" check

# klt: the pinned grader itself. The expected release is derived from
# layout/run_flow.sh's KLT_RELEASE — the source .github/scripts/check-klt-pin.sh
# already treats as authoritative, and the pin the CI job actually installs —
# so a bump needs no edit here (issue #294). An unreadable derivation fails
# the suite rather than skipping (fail closed).
klt_expected="$(sed -n 's/^KLT_RELEASE="\([0-9][0-9.]*\)"$/\1/p' "$ROOT/layout/run_flow.sh")"
klt_found="$(command -v klt >/dev/null 2>&1 && klt --version 2>/dev/null | head -n 1 || true)"
if [ -z "$klt_expected" ]; then
  echo "FAIL: klt cases: cannot derive the expected release from layout/run_flow.sh (no KLT_RELEASE=\"<digits>\")"; fail=$((fail+1))
elif [ "$klt_found" = "klt $klt_expected" ]; then
  item1() { (cd "$1" && klt signoff --manifest signoff/manifest.json --tiers-doc signoff/design-evidence-tiers.md --format json 2>/dev/null) \
    | python3 -I -c 'import json,sys; r=json.load(sys.stdin); i=[x for x in r["items"] if x["id"]==1][0]; print(i["status"], bool((i.get("citation") or {}).get("artifact_binding")))'; }
  mk kok
  if [ "$(item1 "$TMP/kok")" = "met True" ]; then echo "PASS: klt grades item 1 met with artifact_binding"; pass=$((pass+1))
  else echo "FAIL: klt did not grade item 1 met: $(item1 "$TMP/kok")"; fail=$((fail+1)); fi
  mk kmut; printf ' ' >> "$TMP/kmut/signoff/attest/item1.json"
  case "$(item1 "$TMP/kmut")" in met*) echo "FAIL: mutated inventory still renders item 1 met"; fail=$((fail+1)) ;;
    *) echo "PASS: mutated inventory cannot render item 1 met"; pass=$((pass+1)) ;; esac
elif [ -z "$klt_found" ] && { [ -n "${CI:-}" ] || [ -n "${GITHUB_ACTIONS:-}" ]; }; then
  echo "FAIL: klt cases: no klt on PATH (or --version unreadable), expected 'klt $klt_expected' — skew (the design-source-audit job installs the pin before this suite)"; fail=$((fail+1))
elif [ -z "$klt_found" ]; then
  echo "SKIP: klt cases (need release klt $klt_expected on PATH; CI pip-installs it)"; skip=$((skip+1))
elif [ -n "${CI:-}" ] || [ -n "${GITHUB_ACTIONS:-}" ]; then
  echo "FAIL: klt cases: klt on PATH reports '${klt_found}', expected 'klt $klt_expected' — skew (the design-source-audit job installs the pin before this suite)"; fail=$((fail+1))
else
  echo "SKIP: klt cases (release klt $klt_expected not on PATH, have: ${klt_found:-none}; CI pip-installs it)"; skip=$((skip+1))
fi


# meta-case: an ABSENT klt must be fatal under CI and a SKIP locally. Re-runs
# this suite as a child with klt stripped from PATH; LNA_AUDIT_SELFTEST_CHILD
# stops the child from recursing into this case.
if [ -z "${LNA_AUDIT_SELFTEST_CHILD:-}" ]; then
  nokltpath=""; IFS=:
  for p in $PATH; do [ -x "$p/klt" ] || nokltpath="${nokltpath:+$nokltpath:}$p"; done
  unset IFS
  out="$(env -u GITHUB_ACTIONS LNA_AUDIT_SELFTEST_CHILD=1 CI=1 PATH="$nokltpath" "$0" 2>&1)"; rc=$?
  if [ "$rc" -ne 0 ] && printf '%s\n' "$out" | grep -q 'FAIL: klt cases:'; then
    echo "PASS: absent klt is fatal under CI"; pass=$((pass+1))
  else echo "FAIL: absent klt under CI (rc=$rc): $out"; fail=$((fail+1)); fi
  out="$(env -u CI -u GITHUB_ACTIONS LNA_AUDIT_SELFTEST_CHILD=1 PATH="$nokltpath" "$0" 2>&1)"; rc=$?
  if [ "$rc" -eq 0 ] && printf '%s\n' "$out" | grep -q 'SKIP: klt cases'; then
    echo "PASS: absent klt skips locally"; pass=$((pass+1))
  else echo "FAIL: absent klt locally (rc=$rc): $out"; fail=$((fail+1)); fi
fi

echo "$pass passed, $fail failed, $skip skipped"
[ "$fail" -eq 0 ]
