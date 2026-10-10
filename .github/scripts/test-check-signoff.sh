#!/usr/bin/env bash
# Self-test for check-signoff.sh — a drift checker that cannot fail is
# indistinguishable from no checker at all (same self-test convention as
# the fleets's other signoff gates, e.g. 2AMLogic/sg13g2-vco): before
# trusting the checker's verdict on the real tree, prove it still rejects
# each defect class it exists to catch.
#
# Cases (each in a throwaway copy of signoff/, never the real tree):
#   1. pristine copy               -> check-signoff.sh passes
#   2. tampered committed record   -> check-signoff.sh FAILS (drift gate)
#   3. tampered vendored tiers doc -> check-signoff.sh FAILS (drift gate)
#   4. broken manifest JSON        -> check-signoff.sh FAILS (runs-clean gate)
#
# Layout-citation scope guard (issue #80). Fixtures that need a `met` row
# are rendered by the real klt on edited copies of the cited envelopes, so
# the report is byte-synchronized and only the scope guard can object:
#   5. partial cell, met DRC+LVS rows    -> FAILS, one diagnostic per item
#   6. partial cell, passing extraction
#      envelope cited for item 2 (met)   -> FAILS
#   7. uncited layout rows               -> passes
#   8. complete-scope cell, met rows     -> passes
#   9. missing scope metadata            -> FAILS
#  10. stale netlist partition (extra / unassigned / in both) -> FAILS
#  11. evidence vs scope input-hash disagreement (report / provenance)
#                                        -> FAILS

set -u

HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$HERE/../.." && pwd)"
CHECKER="$HERE/check-signoff.sh"

if [ ! -x "$CHECKER" ]; then
  echo "FAIL: $CHECKER not found or not executable" >&2
  exit 1
fi

pass=0
fail=0

run_case() {
  # run_case <name> <expected: 0=pass 1=fail> <tree>
  name="$1"
  expect="$2"
  tree="$3"
  if "$CHECKER" --root "$tree" >/dev/null 2>&1; then
    got=0
  else
    got=1
  fi
  if [ "$got" -eq "$expect" ]; then
    echo "PASS: $name"
    pass=$((pass + 1))
  else
    echo "FAIL: $name (expected $expect, got $got)" >&2
    fail=$((fail + 1))
  fi
}

fresh_tree() {
  tree="$(mktemp -d)"
  cp -R "$ROOT/signoff" "$tree/signoff"
  # The manifest's file-backed citations are repo-root-relative and are
  # graded (and re-hashed) by the render, so a pristine copy must carry
  # them too -- otherwise every cited row renders unreadable_evidence and
  # the pristine case fails for a reason that is not drift (issue #63).
  python3 - "$ROOT" "$tree" <<'PY'
import json, os, shutil, sys

root, tree = sys.argv[1], sys.argv[2]
with open(os.path.join(root, "signoff", "manifest.json")) as f:
    evidence = json.load(f).get("evidence", {})
for entry in evidence.values():
    for e in entry if isinstance(entry, list) else [entry]:
        rel = e.get("file") if isinstance(e, dict) else None
        if not rel:
            continue
        src = os.path.join(root, rel)
        dst = os.path.join(tree, rel)
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.copy2(src, dst)
PY
  # Scope metadata the guard binds citations to (issue #80): realization,
  # provenance, the extraction envelope and the declared netlist. No GDS
  # or regeneration needed.
  mkdir -p "$tree/layout/lna_core" "$tree/design/netlist"
  for f in realization.json lna_core.provenance.json extract_report.json; do
    cp "$ROOT/layout/lna_core/$f" "$tree/layout/lna_core/$f"
  done
  cp "$ROOT/design/netlist/lna.spice" "$tree/design/netlist/lna.spice"
  echo "$tree"
}

# run_msg <name> <expect 0|1> <tree> [pattern ...]: like run_case, and on
# expected failure every pattern must appear in the checker's stderr.
run_msg() {
  name="$1"; expect="$2"; tree="$3"; shift 3
  out="$("$CHECKER" --root "$tree" 2>&1 >/dev/null)"; rc=$?
  [ "$rc" -gt 1 ] && rc=1
  ok=1
  [ "$rc" -eq "$expect" ] || ok=0
  if [ "$expect" -eq 1 ]; then
    for pat in "$@"; do
      printf '%s' "$out" | grep -q -- "$pat" || ok=0
    done
  fi
  if [ "$ok" -eq 1 ]; then
    echo "PASS: $name"; pass=$((pass + 1))
  else
    echo "FAIL: $name (rc=$rc, expected $expect; wanted: $*)" >&2
    printf '%s\n' "$out" >&2; fail=$((fail + 1))
  fi
}

# edit_tree <tree> <python snippet>: run the snippet with `t` (tree), `L`
# (layout/lna_core dir) and `rd`/`wr` JSON helpers, then re-render the
# record with the real klt so the committed report matches the edit.
edit_tree() {
  EDIT_TREE="$1" EDIT_CODE="$2" python3 -c '
import json, os
t, code = os.environ["EDIT_TREE"], os.environ["EDIT_CODE"]
L = os.path.join(t, "layout", "lna_core")
def rd(p): return json.load(open(p))
def wr(p, d): json.dump(d, open(p, "w"), indent=1)
exec(code)
'
  (cd "$1" && klt signoff --manifest signoff/manifest.json \
     --tiers-doc signoff/design-evidence-tiers.md --format json \
     > signoff/t1-report.json 2>/dev/null; true)
}

PASS_DRC='d = rd(L + "/drc_report.json"); d.update(status="clean", violation_count=0, rule_counts={}, metrics={"drc__error__count": 0}, violations=[]); wr(L + "/drc_report.json", d)'
PASS_LVS='d = rd(L + "/lvs_full_report.json"); d["status"] = "match"; wr(L + "/lvs_full_report.json", d)'

# 1. Pristine copy passes.
t="$(fresh_tree)"
run_case "pristine tree passes" 0 "$t"

# 2. Tampered committed record fails: the verdict-of-record no longer
#    matches what klt actually renders.
t="$(fresh_tree)"
sed -i.bak 's/"t1_met_count": 1/"t1_met_count": 9/' "$t/signoff/t1-report.json"
rm -f "$t/signoff/t1-report.json.bak"
run_case "tampered record fails" 1 "$t"

# 3. Tampered vendored tiers doc fails: a silently reworded checklist
#    changes the rendered report, and the committed record must be
#    refreshed deliberately, not drift past.
t="$(fresh_tree)"
sed -i.bak 's/DRC clean/DRC tampered/' "$t/signoff/design-evidence-tiers.md"
rm -f "$t/signoff/design-evidence-tiers.md.bak"
run_case "tampered tiers doc fails" 1 "$t"

# 4. Broken manifest fails: klt signoff must run clean (exit 0 or 3,
#    valid report payload) — a non-rendering manifest is a hard error,
#    never a silent pass.
t="$(fresh_tree)"
printf '{ oops\n' > "$t/signoff/manifest.json"
run_case "broken manifest fails" 1 "$t"

# 5. Partial scope, met DRC and LVS rows, synchronized report: the scope
#    guard (not the drift gate) must reject, naming each applicable row.
t="$(fresh_tree)"
edit_tree "$t" "$PASS_DRC
$PASS_LVS"
run_msg "partial cell with met DRC+LVS rows fails per item" 1 "$t" \
  "item 3 (DRC clean)" "item 4 (LVS clean)" "6 of 30 instances drawn"

# 6. A passing partial extraction envelope cited for item 2.
t="$(fresh_tree)"
edit_tree "$t" 'm = rd(t + "/signoff/manifest.json"); m["evidence"]["2"] = {"file": "layout/lna_core/extract_report.json", "content_hash": m["evidence"]["3"]["content_hash"]}; wr(t + "/signoff/manifest.json", m)'
run_msg "passing partial extraction cannot establish layout presence" 1 "$t" \
  "item 2 (Layout)" "partial scope"

# 7. Uncited layout rows are allowed (case 1 already covers the committed
#    failing partial citations).
t="$(fresh_tree)"
edit_tree "$t" 'm = rd(t + "/signoff/manifest.json"); m["evidence"] = {}; wr(t + "/signoff/manifest.json", m)'
run_msg "uncited layout rows pass" 0 "$t"

# 8. Validated complete-scope cell: every netlist instance is in_scope and
#    out_of_scope is empty, so met rows are allowed.
t="$(fresh_tree)"
edit_tree "$t" "$PASS_DRC
$PASS_LVS
r = rd(L + '/realization.json')
r['in_scope'].update({k: {'pcell': 'x', 'params': {}, 'role': 'fixture'} for k in r['out_of_scope']})
r['out_of_scope'] = {}
wr(L + '/realization.json', r)"
run_msg "complete-scope cell with met rows passes" 0 "$t"

# 9. Missing scope metadata is never read as full scope.
t="$(fresh_tree)"
rm "$t/layout/lna_core/realization.json"
run_msg "missing realization.json fails" 1 "$t" "scope metadata"
t="$(fresh_tree)"
rm "$t/layout/lna_core/lna_core.provenance.json"
run_msg "missing provenance.json fails" 1 "$t" "input hash"
t="$(fresh_tree)"
edit_tree "$t" 'r = rd(L + "/realization.json"); del r["out_of_scope"]; wr(L + "/realization.json", r)'
run_msg "realization without out_of_scope fails" 1 "$t" "lacks netlist/in_scope/out_of_scope"

# 10. Stale netlist partition.
t="$(fresh_tree)"
edit_tree "$t" 'r = rd(L + "/realization.json"); r["out_of_scope"]["ZZstale"] = "x"; wr(L + "/realization.json", r)'
run_msg "instance not in netlist fails" 1 "$t" "does not partition" "ZZstale"
t="$(fresh_tree)"
edit_tree "$t" 'r = rd(L + "/realization.json"); r["out_of_scope"].pop("Le"); wr(L + "/realization.json", r)'
run_msg "unassigned netlist instance fails" 1 "$t" "does not partition" "Le"
t="$(fresh_tree)"
edit_tree "$t" 'r = rd(L + "/realization.json"); r["out_of_scope"]["XQ1"] = "x"; wr(L + "/realization.json", r)'
run_msg "instance in both lists fails" 1 "$t" "does not partition" "XQ1"

# 11. Input-hash disagreement between evidence and scope.
t="$(fresh_tree)"
edit_tree "$t" 'p = rd(L + "/lna_core.provenance.json"); p["gds_sha256"] = "0" * 64; wr(L + "/lna_core.provenance.json", p)'
run_msg "scope provenance hash disagreement fails" 1 "$t" "input hash disagreement"
t="$(fresh_tree)"
edit_tree "$t" 'd = rd(L + "/drc_report.json"); d["provenance"]["input"]["content_hash"] = "sha256:" + "0" * 64; wr(L + "/drc_report.json", d)'
run_msg "report input hash disagreement fails" 1 "$t" "input hash disagreement"

echo "self-test: $pass passed, $fail failed"
[ "$fail" -eq 0 ]
