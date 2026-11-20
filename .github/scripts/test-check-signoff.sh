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
#
# T1 met-regression gate (issue #446). Fixtures commit a baseline, apply a
# candidate edit the real klt render grades, and run the checker with
# --base at the baseline (12 uses the raw SHA — the merge-group shape).
# Tamper primitives, graded by the real klt: editing a file bound by
# item 9's attestation envelope renders item 9 unmet/stale_evidence (the
# PR #444 loss shape); a violating DRC status renders item 3
# unmet/check_failed (the pre-#229 shape):
#  12. lost item fails even though the record faithfully regenerates
#      (raw-SHA base)                        -> FAILS, names item + reason
#  13. the same regression without --base    -> passes (no-base contract)
#  14. one-for-one swap, equal met count     -> FAILS
#  15. unchanged partial completion          -> passes
#  16. a gained item                          -> passes
#  17. new acknowledgement covers its item    -> passes, NOTE visible
#  18. an entry for a different item          -> FAILS
#  19. an entry already at the base           -> FAILS
#  20. drift with an acknowledgement present  -> FAILS (drift gate)
#  21. baseline report missing at the base    -> FAILS, diagnostic
#  22. baseline report unparsable             -> FAILS, diagnostic
#  23. unresolvable --base ref                -> FAILS, diagnostic
#  24. empty --base (malformed event payload) -> FAILS, diagnostic

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
  # scope:"repo" inputs of the klt --attest envelopes resolve against the
  # nearest .git ancestor (issue #238).
  git init -q "$tree"
  cp -R "$ROOT/signoff" "$tree/signoff"
  # The manifest's file-backed citations are repo-root-relative and are
  # graded (and re-hashed) by the render, so a pristine copy must carry
  # them too -- otherwise every cited row renders unreadable_evidence and
  # the pristine case fails for a reason that is not drift (issue #63).
  #
  # Every artifact a cited envelope BINDS must be carried as well, not just
  # the envelope. klt 0.9.x re-hashes each bound artifact and publishes the
  # result as `citation.artifact_binding.members[].status`; an absent file is
  # `unverifiable`, which renders the whole row
  # `unmet` / `unverifiable_provenance` (issue #272). Under 0.8.0 the
  # self-report was not re-checked against the artifacts, so copying the
  # envelopes alone was enough and items 9/10 rendered `met` here.
  #
  # Two places name those artifacts, and both are copied:
  #   * `provenance.input` -- the pre-0.9 single {path, content_hash} form
  #     and the 0.9+ multi-path {paths: [...], content_hash} form;
  #   * `attestation.checks[].path` -- the inventoried files the attestation
  #     hashed (item 9's testbenches, item 10's hygiene files).
  # Missing sources are skipped rather than fatal: a tampering fixture may
  # legitimately have removed one, and the case asserts the checker's verdict,
  # not this helper's.
  python3 -I - "$ROOT" "$tree" <<'PY'
import json, os, shutil, sys

root, tree = sys.argv[1], sys.argv[2]


def copy_rel(rel):
    """Copy a repo-relative path into the scratch tree, if it exists."""
    if not rel or os.path.isabs(rel):
        return
    src = os.path.join(root, rel)
    if not os.path.isfile(src):
        return
    dst = os.path.join(tree, rel)
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    shutil.copy2(src, dst)


def rel_of(path_field):
    """A provenance path is either a bare string or {path, scope}."""
    if isinstance(path_field, str):
        return path_field
    if isinstance(path_field, dict):
        return path_field.get("path")
    return None


def copy_envelope_inputs(rel):
    """Copy every artifact the envelope at `rel` names or binds."""
    try:
        with open(os.path.join(root, rel)) as f:
            env = json.load(f)
    except (OSError, ValueError):
        return
    inp = (env.get("provenance") or {}).get("input")
    for e in inp if isinstance(inp, list) else [inp]:
        if not isinstance(e, dict):
            continue
        copy_rel(rel_of(e.get("path")))                 # pre-0.9 single path
        for sub in e.get("paths") or []:                # 0.9+ multi-path
            if isinstance(sub, dict):
                copy_rel(rel_of(sub.get("path")))
    # Inventoried artifacts the attestation hashed and the render re-hashes.
    for chk in (env.get("attestation") or {}).get("checks") or []:
        if isinstance(chk, dict):
            copy_rel(rel_of(chk.get("path")))


with open(os.path.join(root, "signoff", "manifest.json")) as f:
    evidence = json.load(f).get("evidence", {})
for entry in evidence.values():
    for e in entry if isinstance(entry, list) else [entry]:
        rel = e.get("file") if isinstance(e, dict) else None
        if not rel:
            continue
        copy_rel(rel)
        copy_envelope_inputs(rel)
PY
  # Scope metadata the guard binds citations to (issue #80): realization,
  # provenance, the extraction and DRC envelopes (the DRC one is uncited in
  # the committed manifest; fixtures re-cite it) and the declared netlist. No GDS
  # or regeneration needed.
  mkdir -p "$tree/layout/lna_core" "$tree/design/netlist"
  for f in realization.json lna_core.provenance.json extract_report.json drc_report.json; do
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

# The committed manifest leaves item 3 uncited (klt 0.9.2 grades the partial
# cell's DRC clean); CITE_DRC re-cites it so the fixtures below can exercise
# the scope guard on a met DRC row.
CITE_DRC='m = rd(t + "/signoff/manifest.json"); m["evidence"]["3"] = {"file": "layout/lna_core/drc_report.json", "content_hash": m["evidence"]["4"]["content_hash"]}; wr(t + "/signoff/manifest.json", m)'
PASS_DRC="$CITE_DRC"'; d = rd(L + "/drc_report.json"); d.update(status="clean", violation_count=0, rule_counts={}, metrics={"drc__error__count": 0}, violations=[]); wr(L + "/drc_report.json", d)'
PASS_LVS='d = rd(L + "/lvs_full_report.json"); d["status"] = "match"; wr(L + "/lvs_full_report.json", d)'

# --- T1 met-regression gate helpers (issue #446; cases 12-24)
# Regression fixtures need committed baselines: gt runs git in the scratch
# tree with a fixture identity (same convention as
# test-check-sim-append-only.sh).
gt() { git -C "$1" -c user.name=t -c user.email=t@t -c commit.gpgsign=false "${@:2}"; }
commit_tree() { # commit_tree <tree> [message]
  gt "$1" add -A
  gt "$1" commit -q -m "${2:-fixture}"
}

# TAMPER9: edit a file item 9's attestation envelope binds -> item 9 renders
# unmet/stale_evidence (the PR #444 loss shape). REPAIR9 restores it.
TAMPER9='open(t + "/sim/lna-bias-pvt/testbench/tb_lna_biasop.spice.tmpl", "a").write("\n* fixture tamper\n")'
repair9() { # repair9 <tree>
  cp "$ROOT/sim/lna-bias-pvt/testbench/tb_lna_biasop.spice.tmpl" \
    "$1/sim/lna-bias-pvt/testbench/tb_lna_biasop.spice.tmpl"
}
# VIOL3: a violating DRC status -> item 3 renders unmet/check_failed.
VIOL3='d = rd(L + "/drc_report.json"); d["status"] = "violations"; d["violation_count"] = 1; wr(L + "/drc_report.json", d)'

# ack <tree> <entry>: add an acknowledgement entry under "## Acknowledged
# T1 downgrades" in the scratch README (creating the section if the copied
# README does not carry it). The parser accepts entries anywhere under the
# heading; inserting directly under it keeps fixtures order-independent.
ack() {
  ACK_TREE="$1" ACK_ENTRY="$2" python3 -c '
import os
t, entry = os.environ["ACK_TREE"], os.environ["ACK_ENTRY"]
p = os.path.join(t, "signoff", "README.md")
head = "## Acknowledged T1 downgrades"
lines = open(p).read().splitlines()
if head in lines:
    lines.insert(lines.index(head) + 1, entry)
else:
    lines += ["", head, "", entry]
open(p, "w").write("\n".join(lines) + "\n")
'
}

# run_base <name> <expect 0|1> <tree> <base-ref> [pattern ...]: like run_msg
# but with --base; every pattern must appear in the checker's stderr in both
# modes (the regression gate's OK/NOTE/FAIL lines all go to stderr).
run_base() {
  name="$1"; expect="$2"; tree="$3"; bref="$4"; shift 4
  out="$("$CHECKER" --root "$tree" --base "$bref" 2>&1 >/dev/null)"; rc=$?
  [ "$rc" -gt 1 ] && rc=1
  ok=1
  [ "$rc" -eq "$expect" ] || ok=0
  for pat in "$@"; do
    printf '%s' "$out" | grep -q -- "$pat" || ok=0
  done
  if [ "$ok" -eq 1 ]; then
    echo "PASS: $name"; pass=$((pass + 1))
  else
    echo "FAIL: $name (rc=$rc, expected $expect; wanted: $*)" >&2
    printf '%s\n' "$out" >&2; fail=$((fail + 1))
  fi
}

# 1. Pristine copy passes.
t="$(fresh_tree)"
run_case "pristine tree passes" 0 "$t"

# 2. Tampered committed record fails: the verdict-of-record no longer
#    matches what klt actually renders.
t="$(fresh_tree)"
sed -i.bak 's/"t1_met_count": [0-9]*/"t1_met_count": 99/' "$t/signoff/t1-report.json"
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
# (the committed cell is complete since #346, so one instance is moved back
# out of scope to make the fixture partial)
edit_tree "$t" "$PASS_DRC
$PASS_LVS
r = rd(L + '/realization.json'); r['out_of_scope']['Cvdd'] = r['in_scope'].pop('Cvdd'); wr(L + '/realization.json', r)"
run_msg "partial cell with met DRC+LVS rows fails per item" 1 "$t" \
  "item 3 (DRC clean)" "item 4 (LVS clean)" "34 of 38 instances drawn"

# 6. A passing partial extraction envelope cited for item 2.
t="$(fresh_tree)"
edit_tree "$t" 'm = rd(t + "/signoff/manifest.json"); m["evidence"]["2"] = {"file": "layout/lna_core/extract_report.json", "content_hash": m["evidence"]["4"]["content_hash"]}; wr(t + "/signoff/manifest.json", m); L = t + "/layout/lna_core"; r = rd(L + "/realization.json"); r["out_of_scope"]["Cvdd"] = r["in_scope"].pop("Cvdd"); wr(L + "/realization.json", r)'
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
edit_tree "$t" 'r = rd(L + "/realization.json"); r["in_scope"].pop("Cvdd"); wr(L + "/realization.json", r)'
run_msg "unassigned netlist instance fails" 1 "$t" "does not partition" "Cvdd"
t="$(fresh_tree)"
edit_tree "$t" 'r = rd(L + "/realization.json"); r["modeled_in_device"]["XQ1"] = {"of": "x", "reason": "x"}; wr(L + "/realization.json", r)'
run_msg "instance in in_scope and modeled_in_device fails" 1 "$t" "does not partition" "XQ1"
t="$(fresh_tree)"
edit_tree "$t" 'r = rd(L + "/realization.json"); r["modeled_in_device"].pop("Rle"); wr(L + "/realization.json", r)'
run_msg "unassigned modeled instance fails" 1 "$t" "does not partition" "Rle"
t="$(fresh_tree)"
edit_tree "$t" 'r = rd(L + "/realization.json"); r["out_of_scope"]["XQ1"] = "x"; wr(L + "/realization.json", r)'
run_msg "instance in both lists fails" 1 "$t" "does not partition" "XQ1"

# 11. Input-hash disagreement between evidence and scope.
t="$(fresh_tree)"
edit_tree "$t" 'p = rd(L + "/lna_core.provenance.json"); p["gds_sha256"] = "0" * 64; wr(L + "/lna_core.provenance.json", p)'
run_msg "scope provenance hash disagreement fails" 1 "$t" "input hash disagreement"
t="$(fresh_tree)"
edit_tree "$t" "$CITE_DRC"'; d = rd(L + "/drc_report.json"); d["provenance"]["input"]["content_hash"] = "sha256:" + "0" * 64; wr(L + "/drc_report.json", d)'
run_msg "report input hash disagreement fails" 1 "$t" "input hash disagreement"

# 12. A lost T1 item fails the gate even though the committed record
#     faithfully regenerates its own regression (the PR #444 shape:
#     5/11 -> 4/11, item 9 unmet/stale_evidence). Raw-SHA base: the
#     merge-group invocation shape.
t="$(fresh_tree)"
commit_tree "$t" baseline
edit_tree "$t" "$TAMPER9"
commit_tree "$t" candidate
run_base "regenerated record of a lost T1 item still fails (raw-SHA base)" 1 \
  "$t" "$(gt "$t" rev-parse HEAD~1)" \
  "item 9" "stale_evidence" "NOT acknowledged" "issue #446"

# 13. Without --base the same tree passes: pushes to main and standalone
#     freshness checks compare against no baseline (no-base contract).
run_case "same regression without --base is freshness-only" 0 "$t"

# 14. One-for-one swap: item 9 is repaired, item 3 is lost, the met count
#     is unchanged (4/11 at both) — an improvement on a different item
#     cannot cancel the loss.
t="$(fresh_tree)"
edit_tree "$t" "$TAMPER9"
commit_tree "$t" baseline
repair9 "$t"
edit_tree "$t" "$VIOL3"
commit_tree "$t" candidate
run_base "one-for-one swap fails despite an equal met count" 1 \
  "$t" "$(gt "$t" rev-parse HEAD~1)" "item 3" "check_failed"

# 15. Unchanged partial completion: the met set is identical (others stay
#     unmet) — passes.
t="$(fresh_tree)"
edit_tree "$t" "$TAMPER9"
commit_tree "$t" baseline
echo fixture > "$t/fixture.txt"
commit_tree "$t" candidate
run_base "unchanged partial completion passes" 0 \
  "$t" "$(gt "$t" rev-parse HEAD~1)" "no T1 met-item regression"

# 16. A gained item passes (4/11 -> 5/11).
t="$(fresh_tree)"
edit_tree "$t" "$TAMPER9"
commit_tree "$t" baseline
repair9 "$t"
edit_tree "$t" 'pass'
commit_tree "$t" candidate
run_base "a gained item passes" 0 \
  "$t" "$(gt "$t" rev-parse HEAD~1)" "no T1 met-item regression"

# 17. A new acknowledgement entry covers exactly its named item; the loss
#     and the stated reason stay visible (NOTE lines).
t="$(fresh_tree)"
commit_tree "$t" baseline
edit_tree "$t" "$TAMPER9"
ack "$t" "- T1 item 9 (Testbenches shipped): fixture-acknowledged loss (self-test)."
commit_tree "$t" candidate
run_base "new acknowledgement covers its item" 0 \
  "$t" "$(gt "$t" rev-parse HEAD~1)" \
  "item 9" "stale_evidence" "acknowledged by: - T1 item 9 (Testbenches shipped): fixture-acknowledged loss (self-test)."

# 18. An entry for a different item authorizes nothing.
t="$(fresh_tree)"
commit_tree "$t" baseline
edit_tree "$t" "$TAMPER9"
ack "$t" "- T1 item 3 (DRC clean): wrong-item fixture entry (self-test)."
commit_tree "$t" candidate
run_base "acknowledgement for a different item authorizes nothing" 1 \
  "$t" "$(gt "$t" rev-parse HEAD~1)" "item 9" "NOT acknowledged"

# 19. An entry that already exists at the merge base authorizes nothing
#     (a leftover entry from an earlier, repaired loss).
t="$(fresh_tree)"
ack "$t" "- T1 item 9 (Testbenches shipped): stale leftover entry (self-test)."
commit_tree "$t" baseline
edit_tree "$t" "$TAMPER9"
commit_tree "$t" candidate
run_base "older entry cannot excuse a later loss" 1 \
  "$t" "$(gt "$t" rev-parse HEAD~1)" "item 9" "NOT acknowledged"

# 20. Drift still fails with an acknowledgement present: the entry is no
#     self-authorisation for a stale record either.
t="$(fresh_tree)"
commit_tree "$t" baseline
sed -i.bak 's/"t1_met_count": 5/"t1_met_count": 99/' "$t/signoff/t1-report.json"
rm -f "$t/signoff/t1-report.json.bak"
ack "$t" "- T1 item 9 (Testbenches shipped): fixture-acknowledged loss (self-test)."
run_base "acknowledgement does not bypass drift" 1 \
  "$t" "$(gt "$t" rev-parse HEAD)" "does not match the fresh klt render"

# 21. A baseline report missing at the merge base fails closed.
t="$(fresh_tree)"
commit_tree "$t" root
gt "$t" rm -q signoff/t1-report.json
commit_tree "$t" drop-record
gt "$t" checkout HEAD~1 -- signoff/t1-report.json
commit_tree "$t" candidate
run_base "missing baseline report fails closed" 1 \
  "$t" "$(gt "$t" rev-parse HEAD~1)" "has no signoff/t1-report.json"

# 22. A baseline report that does not parse fails closed.
t="$(fresh_tree)"
commit_tree "$t" root
printf '{ oops\n' > "$t/signoff/t1-report.json"
commit_tree "$t" corrupt-record
gt "$t" checkout HEAD~1 -- signoff/t1-report.json
commit_tree "$t" candidate
run_base "unparsable baseline report fails closed" 1 \
  "$t" "$(gt "$t" rev-parse HEAD~1)" "did not parse as JSON"

# 23. An unresolvable --base ref fails closed.
t="$(fresh_tree)"
commit_tree "$t" baseline
run_base "unresolvable --base ref fails closed" 1 \
  "$t" no-such-ref "does not resolve to a commit"

# 24. An empty --base (malformed event payload) fails closed.
run_base "empty --base fails closed" 1 "$t" "" "non-empty ref"

echo "self-test: $pass passed, $fail failed"
[ "$fail" -eq 0 ]
