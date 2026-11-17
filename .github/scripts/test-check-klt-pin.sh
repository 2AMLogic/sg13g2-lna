#!/usr/bin/env bash
# Self-test for check-klt-pin.sh: prove the pin gate can fail (issue #294).
# Every case runs the gate with --root on a throwaway fixture tree built in
# a mktemp -d (never the checkout).
# Cases:
#   1. consistent tree (both pins agree across both files)       -> passes
#   2. KLT_RELEASE skew between run_flow.sh and run_native_drc.py -> FAILS
#   3. KLAYOUT_PIN skew between the same two files               -> FAILS
#   4. pin missing from run_native_drc.py (each pin)             -> FAILS
#   5. pin missing from run_flow.sh (each pin)                   -> FAILS
#   6. KLT_RELEASE and KLAYOUT_PIN skewed in one run -> FAILS with both
#      messages (the gate reports every skew, not just the first)
#   7. klayout-tools== string drifting from KLT_RELEASE          -> FAILS
#   8. pin quoted differently (single quotes)         -> FAILS (fail closed)
#   9. klayout-tools== drift in README.md prose (issue #320)      -> FAILS
#  10. klayout== drift in layout/README.md prose (issue #320)     -> FAILS
#  11. historical dev-build string (0.9.2.dev1022+g…) in
#      layout/README.md prose leaves the gate green               -> passes
#  12. both README pins drifted in one run -> FAILS with both
#      messages (the gate reports every skew, not just the first)
#  13. docstring klayout-tools== drift in run_native_drc.py       -> FAILS
#      (issue #339). Every fixture's run_native_drc.py also carries the
#      line-271 f-string (klayout-tools=={KLT_RELEASE}); it holds no
#      literal version, so case 1 staying green proves it registers no pin.
#  14. signoff README line-8 "Consumes" prose pin drift            -> FAILS
#      (issue #341), with the pip-install line left correct
#  15. README reproduction-index comment pin drift (issue #341)    -> FAILS,
#      with the uvx line left correct
set -u
HERE="$(cd "$(dirname "$0")" && pwd)"
CHECKER="$HERE/check-klt-pin.sh"
[ -f "$CHECKER" ] || { echo "FAIL: $CHECKER missing" >&2; exit 1; }
TMP="$(mktemp -d)"; trap 'rm -rf "$TMP"' EXIT
pass=0; fail=0
KLT=0.9.2
KLAY=0.30.12

mkroot() { # mkroot <name> [klt-in-runner] [klayout-in-runner] [klayout-in-flow]
  d="$TMP/$1"; klt_r="${2:-$KLT}"; klay_r="${3:-$KLAY}"; klay_f="${4:-$KLAY}"
  mkdir -p "$d/layout" "$d/.github/workflows" "$d/.github/scripts" "$d/signoff"
  printf 'KLT_RELEASE="%s"\nKLAYOUT_PIN="%s"\n' "$KLT" "$klay_f" > "$d/layout/run_flow.sh"
  {
    printf 'KLT_RELEASE = "%s"  # keep in sync with layout/run_flow.sh\n' "$klt_r"
    printf 'KLAYOUT_PIN = "%s"\n' "$klay_r"
    # issue #339: the docstring restates the pin in prose (stating the flow
    # pin, like the real file), and the line-271 f-string carries no literal
    # version — neither may skew the gate on its own.
    printf '  - klt: the pinned PyPI release klayout-tools==%s run isolated through\n' "$KLT"
    printf '        "KLT", f"uvx --isolated --from klayout-tools=={KLT_RELEASE} "\n'
  } > "$d/layout/run_native_drc.py"
  for f in .github/workflows/signoff.yml .github/scripts/check-signoff.sh signoff/README.md; do
    printf 'python3 -m pip install "klayout-tools==%s"\n' "$KLT" > "$d/$f"
  done
  # issue #341: the signoff README's "Consumes" prose and the top-level
  # README's reproduction-index comment restate the pin in the same
  # klayout-tools== form the loop greps — represent both shapes.
  printf -- '- **Consumes**: `klt signoff` (klayout-tools, pinned `klayout-tools==%s` from\n  PyPI)\n' "$KLT" >> "$d/signoff/README.md"
  {
    printf 'uvx --isolated --from klayout-tools==%s --with klayout==%s klt\n' "$KLT" "$klay_f"
    printf '.github/scripts/check-signoff.sh       # T1 verdict of record is current (needs klayout-tools==%s)\n' "$KLT"
  } > "$d/README.md"
  {
    printf 'python3 -m venv .venv && .venv/bin/pip install klayout==%s\n' "$klay_f"
    printf '`run_flow.sh` runs klt as the **PyPI release** `klayout-tools==%s`,\n' "$KLT"
  } > "$d/layout/README.md"
}
run() { # run <label> <want 0|1> <name> [required-output-substring]
  label="$1"; want="$2"; d="$TMP/$3"; pat="${4:-}"
  if out="$(bash "$CHECKER" --root "$d" 2>&1)"; then got=0; else got=1; fi
  if [ "$got" -ne "$want" ]; then
    echo "FAIL: $label (exit-class $got, wanted $want)"; printf '%s\n' "$out" | sed 's/^/    /'; fail=$((fail+1)); return
  fi
  if [ -n "$pat" ] && ! printf '%s\n' "$out" | grep -qF -- "$pat"; then
    echo "FAIL: $label (exited $want but output lacks: $pat)"; printf '%s\n' "$out" | sed 's/^/    /'; fail=$((fail+1)); return
  fi
  echo "PASS: $label"; pass=$((pass+1))
}

mkroot ok
run "consistent tree passes and prints the ok line" 0 ok "ok: klt pin $KLT is consistent"

mkroot klt_skew "0.8.0"
run "KLT_RELEASE skew between the two sites" 1 klt_skew \
  "layout/run_native_drc.py pins '0.8.0', layout/run_flow.sh KLT_RELEASE is $KLT"

mkroot klay_skew "" "0.29.0"
run "KLAYOUT_PIN skew between the two sites" 1 klay_skew \
  "layout/run_native_drc.py pins KLayout '0.29.0', layout/run_flow.sh KLAYOUT_PIN is $KLAY"

mkroot m_klt_runner; sed -i '/^KLT_RELEASE = /d' "$TMP/m_klt_runner/layout/run_native_drc.py"
run "KLT_RELEASE missing from run_native_drc.py" 1 m_klt_runner "no KLT_RELEASE in layout/run_native_drc.py"

mkroot m_klt_flow; sed -i '/^KLT_RELEASE=/d' "$TMP/m_klt_flow/layout/run_flow.sh"
run "KLT_RELEASE missing from run_flow.sh" 1 m_klt_flow "no KLT_RELEASE in layout/run_flow.sh"

mkroot m_klay_runner; sed -i '/^KLAYOUT_PIN = /d' "$TMP/m_klay_runner/layout/run_native_drc.py"
run "KLAYOUT_PIN missing from run_native_drc.py" 1 m_klay_runner "no KLAYOUT_PIN in layout/run_native_drc.py"

mkroot m_klay_flow; sed -i '/^KLAYOUT_PIN=/d' "$TMP/m_klay_flow/layout/run_flow.sh"
run "KLAYOUT_PIN missing from run_flow.sh" 1 m_klay_flow "no KLAYOUT_PIN in layout/run_flow.sh"

# one run, both pins skewed: every skew reported, not just the first
mkroot both_skew "0.8.0" "0.29.0"
if out="$(bash "$CHECKER" --root "$TMP/both_skew" 2>&1)"; then got=0; else got=1; fi
if [ "$got" -eq 1 ] \
   && printf '%s\n' "$out" | grep -qF "pins '0.8.0', layout/run_flow.sh KLT_RELEASE is $KLT" \
   && printf '%s\n' "$out" | grep -qF "pins KLayout '0.29.0', layout/run_flow.sh KLAYOUT_PIN is $KLAY" \
   && [ "$(printf '%s\n' "$out" | grep -c 'FAIL:')" -eq 2 ]; then
  echo "PASS: both pins skewed in one run are both reported"; pass=$((pass+1))
else
  echo "FAIL: both pins skewed in one run (exit-class $got, output below)"; printf '%s\n' "$out" | sed 's/^/    /'; fail=$((fail+1))
fi

mkroot tools_skew
sed -i "s/klayout-tools==$KLT/klayout-tools==0.8.0/" "$TMP/tools_skew/signoff/README.md"
run "klayout-tools== drift from KLT_RELEASE still fails" 1 tools_skew \
  "signoff/README.md pins 'klayout-tools==0.8.0 ', layout/run_flow.sh KLT_RELEASE is $KLT"

mkroot quoted; sed -i "s/^KLAYOUT_PIN=\"$KLAY\"$/KLAYOUT_PIN='$KLAY'/" "$TMP/quoted/layout/run_flow.sh"
run "differently quoted pin reads as missing (fail closed)" 1 quoted "no KLAYOUT_PIN in layout/run_flow.sh"

mkroot readme_tools_skew
sed -i "s/klayout-tools==$KLT/klayout-tools==0.8.0/" "$TMP/readme_tools_skew/README.md"
run "klayout-tools== drift in README.md prose still fails" 1 readme_tools_skew \
  "README.md pins 'klayout-tools==0.8.0 ', layout/run_flow.sh KLT_RELEASE is $KLT"

mkroot readme_klay_skew
sed -i "s/klayout==$KLAY/klayout==0.29.0/" "$TMP/readme_klay_skew/layout/README.md"
run "klayout== drift in layout/README.md prose still fails" 1 readme_klay_skew \
  "layout/README.md pins KLayout 'klayout==0.29.0 ', layout/run_flow.sh KLAYOUT_PIN is $KLAY"

mkroot dev_prose
printf '`is_release: false`; at the 0.9.2 bump it was `0.9.2.dev1022+g2a9c52b27ce7`).\n' \
  >> "$TMP/dev_prose/layout/README.md"
run "dev-build version prose in layout/README.md does not trip the gate" 0 dev_prose \
  "ok: klt pin $KLT is consistent"

# one run, both README pins drifted: every skew reported, not just the first
mkroot readme_both_skew
sed -i "s/klayout-tools==$KLT/klayout-tools==0.8.0/" "$TMP/readme_both_skew/README.md"
sed -i "s/klayout==$KLAY/klayout==0.29.0/" "$TMP/readme_both_skew/layout/README.md"
if out="$(bash "$CHECKER" --root "$TMP/readme_both_skew" 2>&1)"; then got=0; else got=1; fi
if [ "$got" -eq 1 ] \
   && printf '%s\n' "$out" | grep -qF "README.md pins 'klayout-tools==0.8.0 ', layout/run_flow.sh KLT_RELEASE is $KLT" \
   && printf '%s\n' "$out" | grep -qF "layout/README.md pins KLayout 'klayout==0.29.0 ', layout/run_flow.sh KLAYOUT_PIN is $KLAY" \
   && [ "$(printf '%s\n' "$out" | grep -c 'FAIL:')" -eq 2 ]; then
  echo "PASS: both README pins drifted in one run are both reported"; pass=$((pass+1))
else
  echo "FAIL: both README pins drifted in one run (exit-class $got, output below)"; printf '%s\n' "$out" | sed 's/^/    /'; fail=$((fail+1))
fi

# issue #339: the docstring pin in run_native_drc.py must gate like any other
mkroot drc_docstring_skew
sed -i "s/klayout-tools==$KLT/klayout-tools==0.8.0/" "$TMP/drc_docstring_skew/layout/run_native_drc.py"
run "docstring klayout-tools== drift in run_native_drc.py still fails (#339)" 1 drc_docstring_skew \
  "layout/run_native_drc.py pins 'klayout-tools==0.8.0 ', layout/run_flow.sh KLT_RELEASE is $KLT"

# issue #341: the signoff README's line-8 prose pin must gate on its own —
# skew it while the pip-install line stays correct
mkroot signoff_prose_skew
sed -i 's/pinned `klayout-tools=='"$KLT"'/pinned `klayout-tools==0.8.0/' "$TMP/signoff_prose_skew/signoff/README.md"
run "signoff README Consumes-prose pin drift still fails (#341)" 1 signoff_prose_skew \
  "signoff/README.md pins 'klayout-tools==0.8.0 klayout-tools==$KLT ', layout/run_flow.sh KLT_RELEASE is $KLT"

# issue #341: the README reproduction-index comment pin must gate on its own —
# skew it while the uvx line stays correct
mkroot readme_comment_skew
sed -i 's/needs klayout-tools=='"$KLT"'/needs klayout-tools==0.8.0/' "$TMP/readme_comment_skew/README.md"
run "README reproduction-index comment pin drift still fails (#341)" 1 readme_comment_skew \
  "README.md pins 'klayout-tools==0.8.0 klayout-tools==$KLT ', layout/run_flow.sh KLT_RELEASE is $KLT"

echo "$pass passed, $fail failed"
[ "$fail" -eq 0 ]
