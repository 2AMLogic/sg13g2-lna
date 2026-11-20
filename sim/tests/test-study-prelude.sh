#!/usr/bin/env bash
# PDK-free tests for the shared matching-study preflight (issue #450):
# the startup block sim/lna-matching-feasibility/study_prelude.sh that the
# feed (#193), Le (#198) and Q (#200) runners source with their study
# identity.
#
# Everything runs in a mktemp fixture: a stub ngspice on PATH (version banner
# driven by SDT_VER), a fixture open_pdks-shaped PDK tree, and a mirror of the
# sim/ subtree the preflight touches (env.sh, pdk.json, tools/pdk_identity.py,
# models/, design/netlist/lna.spice). No simulator, PDK, klt or network is
# used and nothing under the real sim/ tree is written.
#
# Cases:
#   1. each real runner, invalid MATCH_NGSPICE -> exit 3, its own script name
#      on stderr, nothing on stdout, no record artifact created
#   2. ngspice version floor: an ngspice-42 banner and an unparseable banner
#      both exit 3 with the exact floor message, before any record dir exists
#   3. stale declaration, per study identity -> exit 3 with that study's own
#      module and declaration named in the message
#   4. missing cornerCAP.lib -> exit 3 with the exact cap-model message
#   5. edited vendored model (check_sources.sh fails) -> exit 3
#   6. valid inputs: for each of the three identities, the prelude's output
#      and full post-state (selected simulator, all six SHA-256 values, the
#      sim_require_pdk results) are byte-identical to the ORIGINAL startup
#      block, embedded below as the differential baseline (the pre-#450
#      run_feed_study.sh:39-73 sequence, study names parameterized)
#   7. MATCH_NGSPICE override: baseline and prelude still byte-identical, and
#      both select the override's ngspice binary
set -u
HERE="$(cd "$(dirname "$0")" && pwd)"
SIM_REAL="$(cd "$HERE/.." && pwd)"
REPO_REAL="$(cd "$SIM_REAL/.." && pwd)"
RUNNERS_DIR="$SIM_REAL/lna-matching-feasibility"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
pass=0; fail=0
ok() { echo "PASS: $1"; pass=$((pass+1)); }
bad() { echo "FAIL: $1"; fail=$((fail+1)); }

# --- 1. invalid MATCH_NGSPICE, against the real runners (no PDK needed:
# the check is the first thing each runner does) --------------------------
NOPE="$TMP/nope-ngspice"
for r in run_feed_study.sh run_le_study.sh run_q_study.sh; do
  tree_before="$(git -C "$REPO_REAL" status --porcelain 2>/dev/null)"
  out="$(MATCH_NGSPICE="$NOPE" bash "$RUNNERS_DIR/$r" 2>"$TMP/e-$r")"; rc=$?
  tree_after="$(git -C "$REPO_REAL" status --porcelain 2>/dev/null)"
  expect="${r}: MATCH_NGSPICE=${NOPE} is not executable."
  if [ "$rc" -eq 3 ] && [ -z "$out" ] && [ "$(cat "$TMP/e-$r")" = "$expect" ] \
     && [ "$tree_before" = "$tree_after" ]; then
    ok "invalid MATCH_NGSPICE ($r): exit 3, own name on stderr, no record created"
  else bad "invalid MATCH_NGSPICE $r (rc=$rc out=[$out] err=[$(cat "$TMP/e-$r")])"; fi
done

# --- fixture repo mirror + fixture PDK + stub ngspice ---------------------
STUBS="$TMP/stubs"; mkdir -p "$STUBS"
cat > "$STUBS/ngspice" <<'STUB'
#!/bin/sh
# Stub ngspice: `ngspice -v` line 2 (the version banner the preflight reads)
# comes from $SDT_VER. Arguments are ignored.
echo "stub ngspice"
echo "${SDT_VER:-ngspice-46 stub}"
STUB
chmod +x "$STUBS/ngspice"
OVR="$TMP/ovr"; mkdir -p "$OVR"
printf '#!/bin/sh\necho "stub override"\necho "ngspice-46 override"\n' > "$OVR/ngspice"
chmod +x "$OVR/ngspice"

REPO="$TMP/repo"
STUDY="$REPO/sim/lna-matching-feasibility"
mkdir -p "$STUDY" "$REPO/sim/tools" "$REPO/sim/models" "$REPO/design/netlist"
cp "$SIM_REAL/env.sh" "$REPO/sim/env.sh"
cp "$SIM_REAL/pdk.json" "$REPO/sim/pdk.json"
cp "$SIM_REAL/tools/pdk_identity.py" "$SIM_REAL/tools/artifact_store.py" "$REPO/sim/tools/"
cp "$SIM_REAL/models/check_sources.sh" "$SIM_REAL/models/SOURCE.md" \
   "$SIM_REAL/models/sg13g2_inductor_em.spice" "$REPO/sim/models/"
cp "$REPO_REAL/design/netlist/lna.spice" "$REPO/design/netlist/lna.spice"
cp "$RUNNERS_DIR/study_prelude.sh" "$STUDY/study_prelude.sh"

# Three fixture study identities: a module whose `declare` output is fixed,
# committed as the matching declaration.
mkstudy() { # <module-stem> <declaration-file>
  printf '#!/usr/bin/env python3\nimport sys\nDECL = "fixture %s declaration\\n"\nif len(sys.argv) > 1 and sys.argv[1] == "declare":\n    sys.stdout.write(DECL)\n' "$1" \
    > "$STUDY/$1.py"
  python3 -I "$STUDY/$1.py" declare > "$STUDY/$2"
}
mkstudy feed_study feed-study-declaration.md
mkstudy le_study le-study-declaration.md
mkstudy q_study q-study-declaration.md

# Fixture PDK install (the test-pdk-identity.sh tree, plus the cap models
# the preflight checks) at the pinned release 0.3.0.
PDKF="$TMP/pdk"
mkpdk() {
  local m="$PDKF/ihp-sg13g2/libs.tech/ngspice/models"
  mkdir -p "$m/sub" "$PDKF/ihp-sg13g2/libs.tech/ngspice/osdi"
  printf '.lib cur\n.include sg13g2_hbt_mod.lib\n.endl\n' > "$m/cornerHBT.lib"
  printf '* hbt model\n.include sub/extra.lib\n' > "$m/sg13g2_hbt_mod.lib"
  echo '* extra' > "$m/sub/extra.lib"
  echo '* mos' > "$m/cornerMOShv.lib"
  echo '* cap corner' > "$m/cornerCAP.lib"
  echo '* cap mod' > "$m/capacitors_mod.lib"
  local f
  for f in psp103 psp103_nqs mosvar; do echo x > "$PDKF/ihp-sg13g2/libs.tech/ngspice/osdi/$f.osdi"; done
  echo 0.3.0 > "$PDKF/ihp-sg13g2/.fetched-version"
}
mkpdk

# --- the differential baseline: the ORIGINAL startup block, verbatim ------
# Pre-#450 run_feed_study.sh:39-73 (equivalently run_le_study.sh:39-72 /
# run_q_study.sh:43-76) with only the three study-specific names
# parameterized. Sourced at top level exactly like the prelude, so the
# comparison exercises the real scoping of both.
cat > "$TMP/baseline.sh" <<'BASEEOF'
_bl_name="${1:?baseline: <script-name> is required}"
_bl_module="${2:?baseline: <study-module> is required}"
_bl_decl="${3:?baseline: <declaration-file> is required}"

if [[ -n "${MATCH_NGSPICE:-}" ]]; then
  if [[ ! -x "${MATCH_NGSPICE}" ]]; then
    echo "${_bl_name}: MATCH_NGSPICE=${MATCH_NGSPICE} is not executable." >&2
    exit 3
  fi
  PATH="$(cd "$(dirname "${MATCH_NGSPICE}")" && pwd):${PATH}"
  export PATH
fi

SIM_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
source "${SIM_DIR}/env.sh"

sim_require_pdk "${_bl_name}" --osdi
command -v python3 >/dev/null 2>&1 || { echo "${_bl_name}: python3 not on PATH." >&2; exit 3; }
NGSPICE_MAJOR="$(printf '%s\n' "${NGSPICE_VERSION}" | sed -n 's/.*ngspice-\([0-9][0-9]*\).*/\1/p')"
if [[ -z "${NGSPICE_MAJOR}" ]] || (( NGSPICE_MAJOR < 46 )); then
  echo "${_bl_name}: need ngspice >= 46 (found '${NGSPICE_VERSION}'); set MATCH_NGSPICE." >&2
  exit 3
fi
CAP_LIB="${SG13G2_NGSPICE_MODELS}/cornerCAP.lib"
CAP_MOD="${SG13G2_NGSPICE_MODELS}/capacitors_mod.lib"
[[ -f "${CAP_LIB}" && -f "${CAP_MOD}" ]] || { echo "${_bl_name}: ${CAP_LIB} / capacitors_mod.lib missing." >&2; exit 3; }
"${SIM_DIR}/models/check_sources.sh" || { echo "${_bl_name}: sim/models hash check failed." >&2; exit 3; }
python3 -I "${SCRIPT_DIR}/${_bl_module}" declare | cmp -s - "${SCRIPT_DIR}/${_bl_decl}" \
  || { echo "${_bl_name}: ${_bl_decl} is stale vs ${_bl_module} declare." >&2; exit 3; }

NGSPICE_BIN="$(command -v ngspice)"
NGSPICE_SHA="$(sha256sum "${NGSPICE_BIN}" | awk '{print $1}')"
DESIGN_NETLIST_SHA="$(sha256sum "${REPO_ROOT}/design/netlist/lna.spice" | awk '{print $1}')"
EM_SHA="$(sha256sum "${SIM_DIR}/models/sg13g2_inductor_em.spice" | awk '{print $1}')"
CAP_LIB_SHA="$(sha256sum "${CAP_LIB}" | awk '{print $1}')"
CAP_MOD_SHA="$(sha256sum "${CAP_MOD}" | awk '{print $1}')"
DECL_SHA="$(sha256sum "${SCRIPT_DIR}/${_bl_decl}" | awk '{print $1}')"

unset _bl_name _bl_module _bl_decl
BASEEOF

dump_state() {
  # The full post-preflight state a runner consumes, one key per line.
  printf 'SIM_SCRIPT_NAME=%s\nNGSPICE_VERSION=%s\nNGSPICE_MAJOR=%s\nNGSPICE_BIN=%s\nNGSPICE_SHA=%s\nDESIGN_NETLIST_SHA=%s\nEM_SHA=%s\nCAP_LIB=%s\nCAP_LIB_SHA=%s\nCAP_MOD=%s\nCAP_MOD_SHA=%s\nDECL_SHA=%s\nMODELS_LIB=%s\n' \
    "${SIM_SCRIPT_NAME}" "${NGSPICE_VERSION}" "${NGSPICE_MAJOR}" "${NGSPICE_BIN}" \
    "${NGSPICE_SHA}" "${DESIGN_NETLIST_SHA}" "${EM_SHA}" "${CAP_LIB}" "${CAP_LIB_SHA}" \
    "${CAP_MOD}" "${CAP_MOD_SHA}" "${DECL_SHA}" "${MODELS_LIB}"
}

# run_impl <prelude|baseline> <name> <module> <decl>: source one
# implementation of the startup block in a fresh subshell with the stubbed
# PATH and fixture PDK, then dump the state it left behind. SDT_VER /
# MATCH_NGSPICE ride in from the caller's environment.
run_impl() {
  (
    set -euo pipefail
    cd "$TMP"
    PATH="$STUBS:$PATH"
    PDK_ROOT="$PDKF"
    export PATH PDK_ROOT
    SCRIPT_DIR="$STUDY"
    export SCRIPT_DIR
    if [ "$1" = prelude ]; then
      # shellcheck disable=SC1090
      source "$STUDY/study_prelude.sh" "$2" "$3" "$4"
    else
      # shellcheck disable=SC1090
      source "$TMP/baseline.sh" "$2" "$3" "$4"
    fi
    dump_state
  )
}

# no_record_dirs: a refused preflight must leave no record reservation.
no_record_dirs() {
  [ ! -e "$STUDY/records" ] && [ ! -e "$STUDY/corners" ] && [ ! -e "$STUDY/netlist-snapshots" ]
}

# --- 2. ngspice version floor ---------------------------------------------
out="$(SDT_VER="ngspice-42 old" run_impl prelude t.sh feed_study.py feed-study-declaration.md 2>"$TMP/e2a")"; rc=$?
expect="t.sh: need ngspice >= 46 (found 'ngspice-42 old'); set MATCH_NGSPICE."
if [ "$rc" -eq 3 ] && [ "$(cat "$TMP/e2a")" = "$expect" ] && no_record_dirs; then
  ok "version floor: ngspice-42 banner refused, exit 3, no record dirs"
else bad "version floor 42 (rc=$rc err=[$(cat "$TMP/e2a")])"; fi
out="$(SDT_VER="development snapshot" run_impl prelude t.sh feed_study.py feed-study-declaration.md 2>"$TMP/e2b")"; rc=$?
expect="t.sh: need ngspice >= 46 (found 'development snapshot'); set MATCH_NGSPICE."
if [ "$rc" -eq 3 ] && [ "$(cat "$TMP/e2b")" = "$expect" ] && no_record_dirs; then
  ok "version floor: unparseable banner refused, exit 3"
else bad "version floor unparseable (rc=$rc err=[$(cat "$TMP/e2b")])"; fi

# --- 3. stale declaration, per study identity ------------------------------
for triple in \
  "run_feed_study.sh feed_study.py feed-study-declaration.md" \
  "run_le_study.sh le_study.py le-study-declaration.md" \
  "run_q_study.sh q_study.py q-study-declaration.md"; do
  set -- $triple
  name="$1"; module="$2"; decl="$3"
  printf 'tampered\n' >> "$STUDY/$decl"
  out="$(run_impl prelude "$name" "$module" "$decl" 2>"$TMP/e3-$name")"; rc=$?
  expect="${name}: ${decl} is stale vs ${module} declare."
  if [ "$rc" -eq 3 ] && [ "$(cat "$TMP/e3-$name")" = "$expect" ] && no_record_dirs; then
    ok "stale declaration ($name): exit 3 naming its own module and declaration"
  else bad "stale declaration $name (rc=$rc err=[$(cat "$TMP/e3-$name")])"; fi
  python3 -I "$STUDY/$module" declare > "$STUDY/$decl"   # restore
done

# --- 4. missing cap model ---------------------------------------------------
mv "$PDKF/ihp-sg13g2/libs.tech/ngspice/models/cornerCAP.lib" "$TMP/cap.bak"
out="$(run_impl prelude t.sh feed_study.py feed-study-declaration.md 2>"$TMP/e4")"; rc=$?
capmod="$PDKF/ihp-sg13g2/libs.tech/ngspice/models/cornerCAP.lib"
expect="t.sh: ${capmod} / capacitors_mod.lib missing."
if [ "$rc" -eq 3 ] && [ "$(cat "$TMP/e4")" = "$expect" ] && no_record_dirs; then
  ok "missing cornerCAP.lib: exit 3 with the exact cap-model message"
else bad "missing cap (rc=$rc err=[$(cat "$TMP/e4")])"; fi
mv "$TMP/cap.bak" "$capmod"

# --- 5. edited vendored model (check_sources.sh fails) ----------------------
printf '* edited\n' >> "$REPO/sim/models/sg13g2_inductor_em.spice"
out="$(run_impl prelude t.sh feed_study.py feed-study-declaration.md 2>"$TMP/e5")"; rc=$?
if [ "$rc" -eq 3 ] && grep -q '^t.sh: sim/models hash check failed\.$' "$TMP/e5" && no_record_dirs; then
  ok "edited vendored model: exit 3 via the sim/models hash check"
else bad "model hash (rc=$rc err=[$(cat "$TMP/e5")])"; fi
git -C "$REPO_REAL" show HEAD:sim/models/sg13g2_inductor_em.spice > "$REPO/sim/models/sg13g2_inductor_em.spice"

# --- 6./7. differential vs the original block -------------------------------
for triple in \
  "run_feed_study.sh feed_study.py feed-study-declaration.md" \
  "run_le_study.sh le_study.py le-study-declaration.md" \
  "run_q_study.sh q_study.py q-study-declaration.md"; do
  set -- $triple
  base_out="$(run_impl baseline "$1" "$2" "$3" 2>"$TMP/be6")"; base_rc=$?
  pre_out="$(run_impl prelude "$1" "$2" "$3" 2>"$TMP/pe6")"; pre_rc=$?
  if [ "$base_rc" -eq 0 ] && [ "$pre_rc" -eq 0 ] \
     && [ "$base_out" = "$pre_out" ] \
     && cmp -s "$TMP/be6" "$TMP/pe6" \
     && grep -q "^SIM_SCRIPT_NAME=$1\$" <<<"$pre_out" \
     && grep -q "^DECL_SHA=$(sha256sum "$STUDY/$3" | awk '{print $1}')\$" <<<"$pre_out"; then
    ok "differential ($1): stdout/stderr and the full post-state byte-identical to the original block"
  else
    bad "differential $1 (base_rc=$base_rc pre_rc=$pre_rc)"
    diff <(printf '%s\n' "$base_out") <(printf '%s\n' "$pre_out") | head -10 >&2 || true
  fi
done

# MATCH_NGSPICE override: same differential, plus the selected binary.
base_out="$(MATCH_NGSPICE="$OVR/ngspice" run_impl baseline run_q_study.sh q_study.py q-study-declaration.md 2>"$TMP/be7")"; base_rc=$?
pre_out="$(MATCH_NGSPICE="$OVR/ngspice" run_impl prelude run_q_study.sh q_study.py q-study-declaration.md 2>"$TMP/pe7")"; pre_rc=$?
if [ "$base_rc" -eq 0 ] && [ "$pre_rc" -eq 0 ] && [ "$base_out" = "$pre_out" ] \
   && cmp -s "$TMP/be7" "$TMP/pe7" \
   && grep -q "^NGSPICE_BIN=$(cd "$OVR" && pwd)/ngspice\$" <<<"$pre_out" \
   && grep -q '^NGSPICE_VERSION=ngspice-46 override$' <<<"$pre_out"; then
  ok "MATCH_NGSPICE override: byte-identical, and the override binary is the selected simulator"
else bad "override differential (base_rc=$base_rc pre_rc=$pre_rc out=[$pre_out])"; fi

echo "$pass passed, $fail failed"
[ "$fail" -eq 0 ] && [ "$pass" -ge 11 ]
