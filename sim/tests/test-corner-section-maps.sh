#!/usr/bin/env bash
# PDK-free tests for the canonical corner-label -> PDK-section maps and
# sim_grid_desc in sim/env.sh (issue #283).
#
# The maps used to be restated in six sim/*/run_*.sh runners. Consolidating
# them removes the "five copies agree, the sixth does not" failure mode, but
# only if the one copy is itself pinned: this file is that pin. No ngspice,
# PDK, klt or network is used, and nothing under sim/*/ is written.
#
# Cases:
#   1. the canonical maps hold exactly the PDK fact sim/README.md records
#      (cornerHBT.lib: three real sections, sf/fs -> hbt_typ; cornerMOShv.lib:
#      all five, straight through)
#   2. every runner still sources env.sh, declares no inline map of its own,
#      and keeps its own CORNER_LABELS
#   3. sim_grid_desc reproduces run_core_envelope.sh's former inline
#      GRID_DESC line byte-for-byte (that string is folded into a record's
#      resume fingerprint, so a drift here would strand in-flight records)
#   4. sim_grid_desc --hbt-only omits the MOS section, for the HBT-only benches
#   5. a narrower CORNER_LABELS (biasref's deliberate three labels; a
#      HBT_CORNERS override) resolves against the five-key maps unchanged
#   6. an unresolvable label and a bad argument fail loudly, non-zero,
#      with nothing on stdout
#   7. the Python-side copies of the same PDK fact (reduce_biasref.py's
#      MOS_SECTION_OF, lna_variant_campaign.py's HBT/MOS) agree with the
#      canonical on every key they hold -- the cross-language pin of #287.
#      A copy may hold a subset of the five labels (biasref's bench is
#      deliberately three), but a held key must match and no copy may hold
#      a key the canonical lacks.
set -u
HERE="$(cd "$(dirname "$0")" && pwd)"
SIM_DIR_T="$(cd "$HERE/.." && pwd)"
ENV_SH="$SIM_DIR_T/env.sh"
[ -f "$ENV_SH" ] || { echo "FAIL: $ENV_SH missing" >&2; exit 1; }

pass=0; fail=0
ok()  { echo "PASS: $1"; pass=$((pass+1)); }
bad() { echo "FAIL: $1"; fail=$((fail+1)); }

# grid_desc <labels> [--hbt-only]: run sim_grid_desc in a fresh subshell with
# CORNER_LABELS set to <labels>, printing only its stdout.
grid_desc() {
  local labels="$1"; shift
  (
    # shellcheck disable=SC1090
    source "$ENV_SH" >/dev/null 2>&1
    # shellcheck disable=SC2034  # read by sim_grid_desc
    read -r -a CORNER_LABELS <<< "$labels"
    sim_grid_desc "$@"
  )
}

# 1. the canonical maps are the PDK fact, stated once.
maps="$(
  # shellcheck disable=SC1090
  source "$ENV_SH" >/dev/null 2>&1
  for c in typ bcs wcs sf fs; do
    printf '%s=%s,%s\n' "$c" "${SIM_HBT_SECTION_OF[$c]}" "${SIM_MOS_SECTION_OF[$c]}"
  done
)"
want_maps="typ=hbt_typ,mos_tt
bcs=hbt_bcs,mos_ff
wcs=hbt_wcs,mos_ss
sf=hbt_typ,mos_sf
fs=hbt_typ,mos_fs"
if [ "$maps" = "$want_maps" ]; then
  ok "canonical maps: five labels onto cornerHBT.lib's three real sections, cornerMOShv.lib straight through"
else
  bad "canonical maps differ from sim/README.md's convention"
  printf 'got:\n%s\nwant:\n%s\n' "$maps" "$want_maps" >&2
fi

# The five keys are exactly the fleet's five labels -- no more, no less.
nkeys="$(
  # shellcheck disable=SC1090
  source "$ENV_SH" >/dev/null 2>&1
  printf '%s\n' "${!SIM_HBT_SECTION_OF[@]}" "${!SIM_MOS_SECTION_OF[@]}" | sort -u | tr '\n' ' '
)"
if [ "$nkeys" = "bcs fs sf typ wcs " ]; then
  ok "both maps are keyed on exactly {typ,bcs,wcs,sf,fs}"
else
  bad "unexpected map keys: '$nkeys'"
fi

# 2. no runner restates a map, and each keeps its own CORNER_LABELS.
RUNNERS="lna-characterization/run_lna_sweep.sh
lna-bias-pvt/run_biasop_sweep.sh
breakdown-extraction/run_breakdown_sweep.sh
lna-core-envelope/run_core_envelope.sh
hbt-characterization/run_hbt_sweep.sh
biasref-topology/run_biasref_sweep.sh"
n_runners=0
while IFS= read -r rel; do
  [ -n "$rel" ] || continue
  f="$SIM_DIR_T/$rel"
  n_runners=$((n_runners+1))
  if [ ! -f "$f" ]; then bad "$rel: missing"; continue; fi
  if grep -qE '^declare -A (HBT|MOS)_SECTION_OF=' "$f"; then
    bad "$rel: still declares an inline corner-section map"
  elif ! grep -q 'source "${SIM_DIR}/env.sh"' "$f"; then
    bad "$rel: does not source sim/env.sh"
  elif ! grep -qE 'CORNER_LABELS=\(|HBT_CORNERS:-' "$f"; then
    bad "$rel: no CORNER_LABELS of its own (that is a per-bench definition)"
  elif ! grep -q 'sim_grid_desc' "$f"; then
    bad "$rel: does not record its resolved section map (sim_grid_desc)"
  else
    ok "$rel: sources env.sh, no inline map, own CORNER_LABELS, records the resolved map"
  fi
done <<< "$RUNNERS"
[ "$n_runners" -eq 6 ] || bad "expected 6 runners, checked $n_runners"

# 3. byte-identical to run_core_envelope.sh's former inline GRID_DESC line.
#    That former line is reproduced here verbatim, against the HEAD maps, so
#    this case is a real differential oracle and not a restatement of (1).
legacy="$(
  bash -c '
    set -u
    declare -A HBT_SECTION_OF=( [typ]=hbt_typ [bcs]=hbt_bcs [wcs]=hbt_wcs [sf]=hbt_typ [fs]=hbt_typ )
    declare -A MOS_SECTION_OF=( [typ]=mos_tt [bcs]=mos_ff [wcs]=mos_ss [sf]=mos_sf [fs]=mos_fs )
    CORNER_LABELS=(typ bcs wcs sf fs)
    GRID_DESC=""
    for _c in "${CORNER_LABELS[@]}"; do GRID_DESC+=";${_c}=${HBT_SECTION_OF[$_c]},${MOS_SECTION_OF[$_c]}"; done
    printf "%s\n" "$GRID_DESC"'
)"
got=";$(grid_desc 'typ bcs wcs sf fs')"
if [ "$got" = "$legacy" ]; then
  ok "sim_grid_desc reproduces the former inline GRID_DESC byte-for-byte ($legacy)"
else
  bad "GRID_DESC drift would strand in-flight core-envelope records"
  printf 'legacy: %s\nnow:    %s\n' "$legacy" "$got" >&2
fi

# 4. --hbt-only, for the benches whose decks never load cornerMOShv.lib.
got="$(grid_desc 'typ bcs wcs sf fs' --hbt-only)"
want="typ=hbt_typ;bcs=hbt_bcs;wcs=hbt_wcs;sf=hbt_typ;fs=hbt_typ"
if [ "$got" = "$want" ]; then ok "--hbt-only omits the MOS section"
else bad "--hbt-only: got '$got' want '$want'"; fi

# 5. a narrower grid resolves against the five-key maps unchanged.
got="$(grid_desc 'typ bcs wcs')"
want="typ=hbt_typ,mos_tt;bcs=hbt_bcs,mos_ff;wcs=hbt_wcs,mos_ss"
if [ "$got" = "$want" ]; then ok "biasref's deliberate three-label grid resolves to three entries"
else bad "three-label grid: got '$got' want '$want'"; fi

got="$(grid_desc 'typ' --hbt-only)"
if [ "$got" = "typ=hbt_typ" ]; then ok "a single-label grid (a SMOKE run / HBT_CORNERS override) resolves to one entry"
else bad "single-label grid: got '$got'"; fi

# 6. failures are loud, non-zero, and silent on stdout.
out="$(grid_desc 'typ nope' 2>/dev/null)"; rc=$?
if [ "$rc" -ne 0 ] && [ -z "$out" ]; then
  ok "an unresolvable corner label fails non-zero with nothing on stdout (rc=$rc)"
else bad "unresolvable label: rc=$rc out='$out'"; fi

err="$(grid_desc 'typ nope' 2>&1 >/dev/null)"
case "$err" in
  *"'nope'"*SIM_HBT_SECTION_OF*) ok "the message names the offending label and the map to fix" ;;
  *) bad "unhelpful message for an unresolvable label: '$err'" ;;
esac

out="$(grid_desc 'typ' --bogus 2>/dev/null)"; rc=$?
if [ "$rc" -ne 0 ] && [ -z "$out" ]; then
  ok "an unknown argument fails non-zero with nothing on stdout (rc=$rc)"
else bad "unknown argument: rc=$rc out='$out'"; fi

# 7. the Python copies agree with the canonical across the language boundary
#    (issue #287). The maps are read from the modules by import under
#    `python3 -I` -- the same explicit-path load reduce_biasref.py itself
#    uses for reducer_common.py -- not grep-parsed, so a reformat cannot
#    silently unpin them; the comparison itself stays here in bash against
#    the maps sourced from env.sh, so the test never restates the fact.
canon="$(
  # shellcheck disable=SC1090
  source "$ENV_SH" >/dev/null 2>&1
  for c in typ bcs wcs sf fs; do
    printf '%s\t%s\t%s\n' "$c" "${SIM_HBT_SECTION_OF[$c]}" "${SIM_MOS_SECTION_OF[$c]}"
  done
)"
declare -A CANON_HBT=() CANON_MOS=()
while IFS=$'\t' read -r k h m; do
  [ -n "$k" ] || continue
  CANON_HBT["$k"]="$h"
  CANON_MOS["$k"]="$m"
done <<< "$canon"

py_rows="$(python3 -I - "$SIM_DIR_T" <<'PYEOF'
import importlib.util
import pathlib
import sys

sim = pathlib.Path(sys.argv[1])

def load(name, path):
    spec = importlib.util.spec_from_file_location(name, str(path))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod

rb = load("reduce_biasref", sim / "biasref-topology" / "reduce_biasref.py")
lvc = load("lna_variant_campaign",
           sim / "lna-characterization" / "lna_variant_campaign.py")
for module, dictname, m in (
    ("reduce_biasref.py", "MOS_SECTION_OF", rb.MOS_SECTION_OF),
    ("lna_variant_campaign.py", "HBT", lvc.HBT),
    ("lna_variant_campaign.py", "MOS", lvc.MOS),
):
    for k in sorted(m):
        print(f"{module}\t{dictname}\t{k}\t{m[k]}")
PYEOF
)" || bad "importing the Python maps failed"

# py_check_one <dictname-in-rows>: every key the named dict holds must map to
# the same section as the canonical, and the canonical must actually have
# that key (the subset rule: narrow is fine, divergent is not).
py_check_one() {
  local dictname="$1" cname want module k v n=0 bad_n=0
  case "$dictname" in
    HBT)  cname="SIM_HBT_SECTION_OF" ;;
    MOS*) cname="SIM_MOS_SECTION_OF" ;;
  esac
  while IFS=$'\t' read -r module k v; do
    [ -n "$module" ] || continue
    n=$((n+1))
    want="${CANON_HBT[$k]:-}"
    [ "$cname" = "SIM_MOS_SECTION_OF" ] && want="${CANON_MOS[$k]:-}"
    if [ -z "$want" ]; then
      bad "$module: $dictname holds key '$k', which $cname (sim/env.sh) does not have"
      bad_n=$((bad_n+1))
    elif [ "$v" != "$want" ]; then
      bad "$module: ${dictname}[${k}]='$v' diverges from ${cname}[${k}]='${want}' (sim/env.sh is canonical)"
      bad_n=$((bad_n+1))
    fi
  done < <(printf '%s\n' "$py_rows" | awk -F'\t' -v d="$dictname" '$2==d {print $1 "\t" $3 "\t" $4}')
  if [ "$n" -eq 0 ]; then
    bad "no $dictname rows could be read from the Python modules"
  elif [ "$bad_n" -eq 0 ]; then
    ok "$dictname agrees with sim/env.sh's $cname on every key it holds ($n keys)"
  fi
}
py_check_one MOS_SECTION_OF
py_check_one HBT
py_check_one MOS

echo "pass=$pass fail=$fail"
[ "$fail" -eq 0 ] && [ "$pass" -ge 17 ]
