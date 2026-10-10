#!/usr/bin/env bash
# PDK-free tests for the installed-PDK identity preflight (issue #118).
# Fixture PDK trees and a stub ngspice live in a mktemp dir; no real PDK,
# network or simulator is used. Runs sim_require_pdk in subshells.
set -u
HERE="$(cd "$(dirname "$0")" && pwd)"
ENV_SH="$(cd "$HERE/.." && pwd)/env.sh"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
pass=0; fail=0
ok() { echo "PASS: $1"; pass=$((pass+1)); }
bad() { echo "FAIL: $1"; fail=$((fail+1)); }

STUBS="$TMP/stubs"; mkdir -p "$STUBS"
printf '#!/bin/sh\necho "stub"\necho "ngspice-46 stub"\n' > "$STUBS/ngspice"
chmod +x "$STUBS/ngspice"

# mkpdk <root>: fixture install with a transitive model include
mkpdk() {
  local m="$1/ihp-sg13g2/libs.tech/ngspice/models"
  mkdir -p "$m" "$1/ihp-sg13g2/libs.tech/ngspice/osdi"
  printf '.lib cur\n.include sg13g2_hbt_mod.lib\n.endl\n' > "$m/cornerHBT.lib"
  printf '* hbt model\n.include sub/extra.lib\n' > "$m/sg13g2_hbt_mod.lib"
  mkdir -p "$m/sub"; echo '* extra' > "$m/sub/extra.lib"
  echo '* mos' > "$m/cornerMOShv.lib"
  for f in psp103 psp103_nqs mosvar; do echo x > "$1/ihp-sg13g2/libs.tech/ngspice/osdi/$f.osdi"; done
}

# preflight <root> [args]: prints "rc=<n>" ; stderr -> $TMP/err
preflight() {
  local root="$1"; shift
  (
    PATH="$STUBS:$PATH"; PDK_ROOT="$root"; export PDK_ROOT
    # shellcheck disable=SC1090
    source "$ENV_SH" >/dev/null 2>&1
    sim_require_pdk t.sh "$@"
    echo "OK ${SIM_PDK_RELEASE} ${SIM_PDK_ID_ROUTE}"
  ) 2>"$TMP/err"
  echo "rc=$?"
}

# 1. tarball marker, normalization both ways
R1="$TMP/r1"; mkpdk "$R1"; echo "0.3.0" > "$R1/ihp-sg13g2/.fetched-version"
out="$(preflight "$R1" --osdi)"
if [[ "$out" == *"OK 0.3.0 tarball-marker"* && "$out" == *rc=0 ]]; then ok "marker 0.3.0 matches pin v0.3.0"; else bad "marker match: $out"; fi
echo "v0.3.0" > "$R1/ihp-sg13g2/.fetched-version"
out="$(preflight "$R1")"
[[ "$out" == *rc=0 ]] && ok "marker v0.3.0 normalized" || bad "marker v-prefix: $out"

# 2. mismatch -> named error, exit 3
echo "0.3.1" > "$R1/ihp-sg13g2/.fetched-version"
out="$(preflight "$R1")"
if [[ "$out" == *rc=3 ]] && grep -q PDK_IDENTITY_MISMATCH "$TMP/err"; then ok "wrong release -> PDK_IDENTITY_MISMATCH exit 3"; else bad "mismatch: $out"; fi

# 3. no marker, no git -> unverifiable
rm "$R1/ihp-sg13g2/.fetched-version"
out="$(preflight "$R1")"
if [[ "$out" == *rc=3 ]] && grep -q PDK_IDENTITY_UNVERIFIABLE "$TMP/err"; then ok "no identity route -> PDK_IDENTITY_UNVERIFIABLE"; else bad "unverifiable: $out"; fi

# 4. source checkout at exact tag / wrong tag / untagged
R2="$TMP/r2"; mkpdk "$R2"
G=(git -C "$R2/ihp-sg13g2" -c user.name=t -c user.email=t@t)
"${G[@]}" init -q . 2>/dev/null && "${G[@]}" add -A && "${G[@]}" commit -q -m x && "${G[@]}" tag v0.3.0
out="$(preflight "$R2" --osdi)"
if [[ "$out" == *"OK v0.3.0 source-checkout"* && "$out" == *rc=0 ]]; then ok "source checkout at v0.3.0"; else bad "checkout match: $out"; fi
"${G[@]}" tag -d v0.3.0 >/dev/null; "${G[@]}" tag v0.2.9
out="$(preflight "$R2")"
if [[ "$out" == *rc=3 ]] && grep -q PDK_IDENTITY_MISMATCH "$TMP/err"; then ok "source checkout at wrong tag rejected"; else bad "checkout mismatch: $out"; fi
"${G[@]}" tag -d v0.2.9 >/dev/null
out="$(preflight "$R2")"
if [[ "$out" == *rc=3 ]] && grep -q PDK_IDENTITY_UNVERIFIABLE "$TMP/err"; then ok "untagged checkout rejected"; else bad "untagged: $out"; fi

# 5. missing transitive include
R3="$TMP/r3"; mkpdk "$R3"; echo 0.3.0 > "$R3/ihp-sg13g2/.fetched-version"
rm "$R3/ihp-sg13g2/libs.tech/ngspice/models/sub/extra.lib"
out="$(preflight "$R3")"
if [[ "$out" == *rc=3 ]] && grep -q PDK_MODEL_INPUT_MISSING "$TMP/err"; then ok "missing transitive include rejected"; else bad "missing include: $out"; fi

# 6. failure happens before record reservation; success writes sidecar
E="$TMP/exp"; mkdir -p "$E"
run_full() {
  (
    PATH="$STUBS:$PATH"; PDK_ROOT="$1"; export PDK_ROOT
    # shellcheck disable=SC1090
    source "$ENV_SH" >/dev/null 2>&1
    # shellcheck disable=SC2034  # read by sim_record_paths (sourced env.sh) as the experiment dir
    SCRIPT_DIR="$E"
    sim_require_pdk t.sh --osdi
    sim_record_paths
    echo "ID ${RECORD_ID}"
  ) 2>"$TMP/err"
}
echo 9.9 > "$R1/ihp-sg13g2/.fetched-version"
run_full "$R1" >/dev/null; rc=$?
if [[ $rc -eq 3 && -z "$(ls -A "$E")" ]]; then ok "mismatch exits before any record dir is created"; else bad "reservation leak rc=$rc: $(ls "$E")"; fi
echo 0.3.0 > "$R1/ihp-sg13g2/.fetched-version"
out="$(run_full "$R1")"; rc=$?
id="${out#ID }"
side="$E/records/$id.pdk-provenance.json"
if [[ $rc -eq 0 && -f "$side" ]] && python3 -I - "$side" <<'PY'
import json, sys
d = json.load(open(sys.argv[1]))
names = [m["path"].rsplit("/", 1)[-1] for m in d["model_inputs"]]
assert d["verified"] and d["identity_route"] == "tarball-marker"
assert d["installed_release_raw"] == "0.3.0"
for n in ("cornerHBT.lib", "sg13g2_hbt_mod.lib", "extra.lib", "cornerMOShv.lib", "psp103.osdi"):
    assert n in names, n
assert all(len(m["sha256"]) == 64 for m in d["model_inputs"])
PY
then ok "sidecar records verified identity and transitive model hashes"; else bad "sidecar rc=$rc"; fi

echo "$pass passed, $fail failed"
[ "$fail" -eq 0 ]
