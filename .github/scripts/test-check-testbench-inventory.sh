#!/usr/bin/env bash
# Self-test for check-testbench-inventory.py (issue #195) -- a freshness check
# that cannot fail is no check at all. Every case runs in a throwaway git
# repository built from the tracked tree; the real tree is only read.
#
# The fixture keeps every tracked file except the bulky corners/ and
# netlist-snapshots/ trees, which are replaced by one stub file per record id
# (the checker only needs their ids and a blob digest). It regenerates its own
# inventory with --write and re-binds the rolling report by editing JSON, so
# no klt, ngspice, PDK or network is involved.
#
# Cases:
#   1. pristine fixture                              -> passes
#   2. check mode writes nothing                     -> tree unchanged
#   3. bench template missing / untracked            -> FAILS
#   4. listed input changed (runner, doc, shared)    -> FAILS (stale hash)
#   5. omitted family / new sim/ family              -> FAILS
#   6. omitted claim, new record id, new bench file  -> FAILS
#   7. removed invocation documentation              -> FAILS
#   8. stale outer binding (envelope, manifest,
#      report, missing citation)                     -> FAILS
#   9. incomplete audit (open gap, no cold start)    -> FAILS, --write refuses
#  10. new claim-source family mention / bench-like
#      file outside sim/                             -> FAILS

set -u

HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$HERE/../.." && pwd)"
CHECKER="$ROOT/.github/scripts/check-testbench-inventory.py"

pass=0
fail=0
BASE=""
trap '[ -n "$BASE" ] && rm -rf "$BASE" "$BASE".case.*' EXIT

ok()  { echo "PASS: $1"; pass=$((pass + 1)); }
bad() { echo "FAIL: $1" >&2; fail=$((fail + 1)); }

run_check() { # run_check <tree> -> sets OUT, RC (no ngspice/PDK/klt on PATH needed)
  OUT="$(cd "$1" && env -i PATH=/usr/bin:/bin python3 -I "$1/.github/scripts/check-testbench-inventory.py" 2>&1)"
  RC=$?
}

# expect <name> <0|1> <tree> [pattern ...]
expect() {
  local name="$1" want="$2" tree="$3"; shift 3
  run_check "$tree"
  local good=1 pat
  [ "$RC" -eq "$want" ] || good=0
  for pat in "$@"; do
    printf '%s' "$OUT" | grep -q -- "$pat" || good=0
  done
  if [ "$good" -eq 1 ]; then ok "$name"; else
    bad "$name (rc=$RC, wanted $want; patterns: $*)"; printf '%s\n' "$OUT" | head -8 >&2
  fi
}

build_base() {
  BASE="$(mktemp -d)"
  python3 -I - "$ROOT" "$BASE" <<'PY'
import os, re, shutil, subprocess, sys
root, dst = sys.argv[1], sys.argv[2]
files = subprocess.run(["git", "-C", root, "ls-files", "-z"], check=True,
                       capture_output=True).stdout.decode().split("\0")
stubs = set()
for f in files:
    if not f or f.startswith((".loom/", ".agents/", ".claude/")):
        continue
    m = re.match(r"(sim/[^/]+/(?:corners|netlist-snapshots)/[^/]+)/", f)
    if m:
        stubs.add(m.group(1))
        continue
    os.makedirs(os.path.dirname(os.path.join(dst, f)) or dst, exist_ok=True)
    shutil.copy2(os.path.join(root, f), os.path.join(dst, f))
for s in sorted(stubs):
    os.makedirs(os.path.join(dst, s), exist_ok=True)
    with open(os.path.join(dst, s, "stub.log"), "w") as fh:
        fh.write("stub for %s\n" % s)
subprocess.run(["git", "-C", dst, "init", "-q"], check=True)
subprocess.run(["git", "-C", dst, "add", "-A"], check=True)
PY
  rebind "$BASE"
}

# rebind <tree>: regenerate inventory/envelope/manifest and point the rolling
# report's item-9 row at the new hash (what the pinned grader would render).
rebind() {
  (cd "$1" && git add -A && python3 -I .github/scripts/check-testbench-inventory.py --write >/dev/null) || return 1
  python3 -I - "$1" <<'PY'
import hashlib, json, sys
t = sys.argv[1]
h = "sha256:" + hashlib.sha256(open(t + "/signoff/testbench-inventory.json", "rb").read()).hexdigest()
r = json.load(open(t + "/signoff/t1-report.json"))
for it in r["items"]:
    if it["id"] == 9:
        it["status"] = "met"
        it["citation"]["artifact_binding"]["content_hash"] = h
        it["citation"]["content_hash"] = h
json.dump(r, open(t + "/signoff/t1-report.json", "w"), indent=2)
PY
  (cd "$1" && git add -A)
}

new_case() { # new_case -> prints a fresh copy of the pristine fixture
  local c
  c="$(mktemp -d "$BASE.case.XXXXXX")"
  cp -a "$BASE/." "$c/"
  echo "$c"
}

pyedit() { # pyedit <tree> <python code with t = tree path>
  python3 -I -c '
import json, os, sys
t, code = sys.argv[1], sys.argv[2]
def rd(p): return json.load(open(os.path.join(t, p)))
def wr(p, d): json.dump(d, open(os.path.join(t, p), "w"), indent=2, sort_keys=True)
exec(code)
' "$1" "$2"
  (cd "$1" && git add -A)
}

tree_digest() {
  (cd "$1" && find . -path ./.git -prune -o -type f -print0 | sort -z | xargs -0 sha256sum | sha256sum)
}

[ -f "$CHECKER" ] || { echo "FAIL: $CHECKER missing" >&2; exit 1; }
build_base || { echo "FAIL: could not build the fixture" >&2; exit 1; }

# 1. pristine
expect "pristine fixture passes" 0 "$BASE"

# 2. check mode is read-only
t="$(new_case)"; before="$(tree_digest "$t")"; run_check "$t"; after="$(tree_digest "$t")"
if [ "$before" = "$after" ]; then ok "check mode leaves the tree untouched"; else bad "check mode modified the tree"; fi

# 3. missing bench input
t="$(new_case)"; rm "$t/sim/lna-characterization/testbench/tb_lna_sparam.spice.tmpl"
expect "deleted bench template is rejected" 1 "$t" "tb_lna_sparam.spice.tmpl"
t="$(new_case)"; (cd "$t" && git rm -q --cached sim/lna-matching-feasibility/testbench/tb_match_char.spice.tmpl)
expect "untracked bench template is rejected" 1 "$t" "not a tracked file"
t="$(new_case)"; rm "$t/sim/lna-bias-pvt/run_biasop_sweep.sh"
expect "deleted runner is rejected" 1 "$t" "run_biasop_sweep.sh"

# 4. changed listed hash
t="$(new_case)"; printf '\n# edit\n' >> "$t/sim/hbt-characterization/run_hbt_sweep.sh"
expect "changed runner is stale" 1 "$t" "STALE: sim/hbt-characterization/run_hbt_sweep.sh"
t="$(new_case)"; printf '\n' >> "$t/sim/pdk.json"
expect "changed PDK pin is stale" 1 "$t" "STALE: sim/pdk.json"
t="$(new_case)"; printf '\n' >> "$t/sim/env.sh"
expect "changed shared runner input is stale" 1 "$t" "STALE: sim/env.sh"
t="$(new_case)"; printf '\n' >> "$t/sim/lna-characterization/records/20260926-122301-088c734-summary.csv"
expect "changed record file is stale" 1 "$t" "STALE: sim/lna-characterization/records/20260926-122301-088c734-summary.csv"
t="$(new_case)"; printf '\n' >> "$t/design/netlist/lna.spice"
expect "changed DUT netlist is stale" 1 "$t" "STALE: design/netlist/lna.spice"

# 5. omitted / new family
t="$(new_case)"
pyedit "$t" 'i = rd("signoff/testbench-coverage.json"); del i["families"]["lna-matching-feasibility"]; i["claims"] = [c for c in i["claims"] if c["family"] != "lna-matching-feasibility"]; wr("signoff/testbench-coverage.json", i)'
expect "omitted measurement family is rejected" 1 "$t" "sim/lna-matching-feasibility/ is neither"
t="$(new_case)"; mkdir -p "$t/sim/new-family/testbench"
echo "# new" > "$t/sim/new-family/README.md"; echo "* bench" > "$t/sim/new-family/testbench/tb_new.spice.tmpl"; (cd "$t" && git add -A)
expect "new sim/ family is rejected" 1 "$t" "sim/new-family/ is neither"

# 6. omitted claim / new record / new bench
t="$(new_case)"
pyedit "$t" 'i = rd("signoff/testbench-coverage.json"); i["claims"] = [c for c in i["claims"] if c["id"] != "matching-20261010-233800-d1312cc"]; wr("signoff/testbench-coverage.json", i)'
expect "omitted claim leaves its record unindexed" 1 "$t" "belongs to no claim"
t="$(new_case)"; echo "# r" > "$t/sim/hbt-characterization/records/20270101-000000-abcdef0.md"; (cd "$t" && git add -A)
expect "new record id is rejected" 1 "$t" "20270101-000000-abcdef0"
t="$(new_case)"; echo "* b" > "$t/sim/lna-characterization/testbench/tb_new_bench.spice.tmpl"; (cd "$t" && git add -A)
expect "new bench template is rejected" 1 "$t" "tb_new_bench.spice.tmpl"
t="$(new_case)"; echo "#!/usr/bin/env bash" > "$t/sim/lna-core-envelope/run_new_study.sh"; (cd "$t" && git add -A)
expect "new runner is rejected" 1 "$t" "run_new_study.sh"
t="$(new_case)"
pyedit "$t" 'i = rd("signoff/testbench-coverage.json"); [c.__setitem__("record_ids", []) for c in i["claims"] if c["id"] == "breakdown-20260918-212948-013274f"]; wr("signoff/testbench-coverage.json", i)'
expect "claim without its record ids is rejected" 1 "$t" "belongs to no claim"

# 7. removed invocation documentation
t="$(new_case)"; sed -i 's#sim/breakdown-extraction/run_breakdown_sweep.sh#run the breakdown sweep#' "$t/sim/breakdown-extraction/README.md"
expect "removed invocation documentation is rejected" 1 "$t" "documented invocation not found"
t="$(new_case)"
pyedit "$t" 'i = rd("signoff/testbench-coverage.json"); [c.__setitem__("cold_start", []) for c in i["claims"] if c["id"] == "hbt-char-20260918-203652-4293920"]; wr("signoff/testbench-coverage.json", i)'
expect "claim without a cold-start entry is rejected" 1 "$t" "no cold-start command"
t="$(new_case)"
pyedit "$t" 'i = rd("signoff/testbench-coverage.json"); [c["cold_start"][0].__setitem__("command", "sim/hbt-characterization/not_a_runner.sh") for c in i["claims"] if c["id"] == "hbt-char-20260918-203652-4293920"]; wr("signoff/testbench-coverage.json", i)'
expect "cold-start command naming no listed runner is rejected" 1 "$t" "documented invocation not found"

# 8. stale outer bindings
t="$(new_case)"
pyedit "$t" 'e = rd("signoff/testbench-inventory.envelope.json"); e["provenance"]["input"]["content_hash"] = "sha256:" + "0" * 64; wr("signoff/testbench-inventory.envelope.json", e)'
expect "stale envelope hash is rejected" 1 "$t" "stale envelope"
t="$(new_case)"
pyedit "$t" 'e = rd("signoff/testbench-inventory.envelope.json"); e["status"] = "fail"; wr("signoff/testbench-inventory.envelope.json", e)'
expect "non-pass envelope is rejected" 1 "$t" "stale envelope"
t="$(new_case)"
pyedit "$t" 'm = rd("signoff/manifest.json"); m["evidence"]["9"]["content_hash"] = "sha256:" + "1" * 64; wr("signoff/manifest.json", m)'
expect "stale manifest hash is rejected" 1 "$t" "stale manifest binding"
t="$(new_case)"
pyedit "$t" 'm = rd("signoff/manifest.json"); del m["evidence"]["9"]; wr("signoff/manifest.json", m)'
expect "missing manifest citation is rejected" 1 "$t" "stale manifest binding"
t="$(new_case)"
pyedit "$t" 'r = rd("signoff/t1-report.json"); [it["citation"]["artifact_binding"].__setitem__("content_hash", "sha256:" + "2" * 64) for it in r["items"] if it["id"] == 9]; wr("signoff/t1-report.json", r)'
expect "stale rolling report is rejected" 1 "$t" "stale rolling report"
t="$(new_case)"
pyedit "$t" 'r = rd("signoff/t1-report.json"); [it.update(status="unmet", reason="no_evidence", citation=None) for it in r["items"] if it["id"] == 9]; wr("signoff/t1-report.json", r)'
expect "rolling report without a met item 9 is rejected" 1 "$t" "stale rolling report"
t="$(new_case)"; rm "$t/signoff/testbench-inventory.envelope.json"
expect "missing envelope is rejected" 1 "$t" "envelope .* is missing"

# 9. incomplete audit
t="$(new_case)"
pyedit "$t" 'i = rd("signoff/testbench-coverage.json"); i["open_gaps"] = ["bench X not yet committed"]; wr("signoff/testbench-coverage.json", i)'
expect "declared open gap makes the audit incomplete" 1 "$t" "open gap" "incomplete"
t="$(new_case)"
pyedit "$t" 'i = rd("signoff/testbench-coverage.json"); i["open_gaps"] = ["bench X not yet committed"]; wr("signoff/testbench-coverage.json", i)'
rm "$t/signoff/testbench-inventory.envelope.json" "$t/signoff/testbench-inventory.json"
(cd "$t" && python3 -I .github/scripts/check-testbench-inventory.py --write >/dev/null 2>&1); rc=$?
if [ "$rc" -ne 0 ] && [ ! -e "$t/signoff/testbench-inventory.envelope.json" ] && [ ! -e "$t/signoff/testbench-inventory.json" ]; then
  ok "--write refuses to emit a pass for an incomplete audit"; else bad "--write emitted output for an incomplete audit (rc=$rc)"; fi
t="$(new_case)"
pyedit "$t" 'i = rd("signoff/testbench-coverage.json"); i["claims"][0]["classification"] = "made-up"; wr("signoff/testbench-coverage.json", i)'
expect "unknown classification is rejected" 1 "$t" "unknown classification"
t="$(new_case)"
pyedit "$t" 'i = rd("signoff/testbench-coverage.json"); [c.update(derives_from=[]) for c in i["claims"] if c["classification"] == "data-only-derivation"][:1]; wr("signoff/testbench-coverage.json", i)'
expect "derivation without source claims is rejected" 1 "$t" "must name derives_from"

# 10. claim-source family mention / bench-like file outside sim/
t="$(new_case)"; printf '\nSee also sim/phantom-family/README.md.\n' >> "$t/measurements/README.md"; (cd "$t" && git add -A)
expect "claim source naming an unindexed family is rejected" 1 "$t" "sim/phantom-family/"
t="$(new_case)"; mkdir -p "$t/rf"; echo "* x" > "$t/rf/tb_extra.spice.tmpl"; (cd "$t" && git add -A)
expect "bench-like file outside sim/ is rejected" 1 "$t" "tb_extra.spice.tmpl"

echo "self-test: $pass passed, $fail failed"
[ "$fail" -eq 0 ]
