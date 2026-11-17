#!/usr/bin/env bash
# Self-test for characterization-report (issue #233) — a freshness check
# that cannot fail is no check at all. Every case runs in a throwaway
# fixture tree synthesized from minimal inputs; the real tree is only read
# (spec/ratified-rows.json and the bench reducer module are copied in as
# the row source and the one measurement->row mapping).
#
# The fixture mirrors the real generator inputs: a manifest whose item-5
# citations point at synthesized `klt sim` report envelopes (each binding a
# netlist stub by the same provenance.input / netlist_closure shape the
# grader reads), a coverage index with one claim per record, and the
# manifest's item-8 citation pinning the generated report. No klt, ngspice,
# PDK, git or network is involved; nothing outside the fixture tree is
# written.
#
# Cases:
#   1. pristine all-pass fixture   -> --write emits envelope status pass;
#                                     check passes; --write is byte-identical
#   2. pristine nf-fail fixture    -> envelope status fail (the honest
#                                     verdict); check passes
#   3. hand-edited report          -> FAILS (stale)
#   4. hand-set envelope status    -> FAILS (status is never hand-set)
#   5. stale item-8 manifest pin   -> FAILS
#   6. superseded record cited     -> FAILS, --write refuses
#   7. uncovered row, no gap       -> FAILS, --write refuses
#   8. citation rows vs the bench  -> FAILS, --write refuses
#   9. item 8 uncited              -> note, check passes (unciting is legal)

set -u

HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$HERE/../.." && pwd)"

pass=0
fail=0
BASE=""
trap '[ -n "$BASE" ] && rm -rf "$BASE" "$BASE".case.*' EXIT

ok()  { echo "PASS: $1"; pass=$((pass + 1)); }
bad() { echo "FAIL: $1" >&2; fail=$((fail + 1)); }

run() { # run <mode> <tree> [extra args...] -> sets OUT, RC
  # mode "" means the default check mode: no flag is passed at all.
  local mode="$1" tree="$2" checker; shift 2
  checker="$tree/.github/scripts/characterization-report"
  if [ -n "$mode" ]; then
    OUT="$(cd "$tree" && env -i PATH=/usr/bin:/bin python3 -I "$checker" "$mode" "$@" 2>&1)"
  else
    OUT="$(cd "$tree" && env -i PATH=/usr/bin:/bin python3 -I "$checker" "$@" 2>&1)"
  fi
  RC=$?
}

# expect <name> <want-rc> <mode> <tree> [pattern ...]
expect() {
  local name="$1" want="$2" mode="$3" tree="$4"; shift 4
  run "$mode" "$tree"
  local good=1 pat
  [ "$RC" -eq "$want" ] || good=0
  for pat in "$@"; do
    printf '%s' "$OUT" | grep -q -- "$pat" || good=0
  done
  if [ "$good" -eq 1 ]; then ok "$name"; else
    bad "$name (rc=$RC, wanted $want; patterns: $*)"; printf '%s\n' "$OUT" | head -8 >&2
  fi
}

envelope_status() { # envelope_status <tree> -> prints the committed status
  python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["status"])' \
    "$1/signoff/characterization.envelope.json"
}

cite_item8() { # cite_item8 <tree>: pin evidence."8" to the generated report
  python3 -I - "$1" <<'PY'
import json, sys
root = sys.argv[1]
report = json.load(open(root + "/measurements/characterization-report.json"))
h = json.load(open(root + "/signoff/characterization.envelope.json"))["provenance"]["input"]["content_hash"]
p = root + "/signoff/manifest.json"
m = json.load(open(p))
m.setdefault("evidence", {})["8"] = {
    "file": "signoff/characterization.envelope.json", "content_hash": h}
with open(p, "w") as fh:
    json.dump(m, fh, indent=2, sort_keys=True)
    fh.write("\n")
PY
}

build_fixture() { # build_fixture <dest> <nf-status: pass|fail>
  env -i PATH=/usr/bin:/bin python3 -I - "$ROOT" "$1" "$2" <<'PY'
import hashlib, json, os, shutil, sys

root, dst, nf_status = sys.argv[1], sys.argv[2], sys.argv[3]
REC = "20260101-000000-abcdef0"

def write(rel, data):
    path = os.path.join(dst, rel)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as fh:
        fh.write(data)
    return "sha256:" + hashlib.sha256(data).hexdigest()

for d in (".github/scripts", "spec", "sim/lna-characterization"):
    os.makedirs(os.path.join(dst, d), exist_ok=True)
shutil.copy2(os.path.join(root, ".github/scripts/characterization-report"),
             os.path.join(dst, ".github/scripts/characterization-report"))
shutil.copy2(os.path.join(root, "spec/ratified-rows.json"),
             os.path.join(dst, "spec/ratified-rows.json"))
shutil.copy2(os.path.join(root, "sim/lna-characterization/reduce_spec_envelopes.py"),
             os.path.join(dst, "sim/lna-characterization/reduce_spec_envelopes.py"))

# Synthesize the bench: one netlist stub + one report envelope per stem,
# with the rollup fields the reducer reads and the provenance/netlist-
# closure binding the grader verifies.
import importlib.util
spec = importlib.util.spec_from_file_location(
    "reduce_spec_envelopes",
    os.path.join(dst, "sim/lna-characterization/reduce_spec_envelopes.py"))
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

citations = []
for stem in mod.STEMS:
    graded = [(m, r, e) for (m, r, e) in mod.GRADED[stem]]
    netlist_rel = "sim/lna-characterization/netlist-snapshots/%s/%s.spice" % (REC, stem)
    netlist_hash = write(netlist_rel, ("* %s synthesized netlist stub\n.end\n" % stem).encode())
    meas, corner_meas = [], []
    for name, row, extreme in graded:
        status = nf_status if row == "nf" else "pass"
        value = {"s21_db_min": 18.7162981, "s11_db_worst": -11.11244,
                 "s22_db_worst": -14.965332, "mu_min": 1.00000037,
                 "s11_mag_max": 0.998995826, "s22_mag_max": 0.999999631,
                 "ic1": 0.00415097376, "pdc": 0.0097681213,
                 "nf290_db_worst": 4.37793746}[name]
        unit = {"s21_db_min": "dB", "s11_db_worst": "dB", "s22_db_worst": "dB",
                "nf290_db_worst": "dB", "ic1": "A", "pdc": "W"}.get(name)
        limits = {"gain": {"min": 15.0}, "s11": {"max": -10.0}, "s22": {"max": -10.0},
                  "mu": {"min": 1.0}, "negres": {"max": 1.0}, "ic1": {"max": 0.0045},
                  "power": {"max": 0.01}, "nf": {"max": 1.5}}[row]
        margin = 0.0 if status == "pass" else -2.87793746
        meas.append({"name": name, "spec_row": row, "status": status, "unit": unit,
                     "limits": limits, extreme: {"corner_id": "typ/1.800V/27C",
                                                 "value": value, "margin": margin},
                     "worst_case": {"corner_id": "typ/1.800V/27C",
                                    "value": value, "margin": margin}})
        corner_meas.append({"name": name, "value": value, "unit": unit,
                            "status": status, "margin": margin})
    report = {
        "schema_version": 3,
        "netlist": {"path": netlist_rel, "scope": "repo"},
        "status": "pass" if nf_status == "pass" or stem != "matched_noise" else "fail",
        "corner_count": 1, "passed": 1, "failed": 0, "errored": 0, "inconclusive": 0,
        "measurements": meas,
        "corners": [{"corner_id": "typ/1.800V/27C", "measurements": corner_meas,
                     "status": "pass"}],
        "environment": {"netlist_sha256": netlist_hash,
                        "netlist_closure": [{"path": netlist_rel, "scope": "repo",
                                             "sha256": netlist_hash}]},
        "provenance": {"input": {"content_hash": netlist_hash, "role": "netlist"}},
    }
    rel = "sim/lna-characterization/netlist-snapshots/%s/reports/%s.report.json" % (REC, stem)
    write(rel, (json.dumps(report, indent=2, sort_keys=True) + "\n").encode())
    citations.append({"file": rel, "content_hash": netlist_hash,
                      "rows": sorted({r for (_m, r, _e) in graded})})

rows = json.load(open(os.path.join(dst, "spec/ratified-rows.json")))["rows"]
spec_rows = [{"id": r["id"]} for r in rows if r["id"] not in ("iip3", "supply")]
spec_rows += [
    {"id": "iip3", "gap": "numeric target NOT ratified (fixture gap text)"},
    {"id": "supply", "gap": "context row realized by the ratified corner axis (fixture gap text)"},
]
manifest = {
    "block": "fixture-lna", "kind": "analog",
    "evidence": {"5": citations},
    "spec_rows": {"5": spec_rows},
}
write("signoff/manifest.json", (json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode())
coverage = {"claims": [{"id": "lna-char-spec-envelope-" + REC,
                        "classification": "present-dut",
                        "result_status": "published"}]}
write("signoff/testbench-coverage.json",
      (json.dumps(coverage, indent=2, sort_keys=True) + "\n").encode())
PY
  run --write "$1"
  if [ "$RC" -ne 0 ]; then bad "fixture build ($1) --write failed"; printf '%s\n' "$OUT" | head -8 >&2; return 1; fi
  cite_item8 "$1"
}

new_case() { # new_case <nf-status> -> prints a fresh fixture tree
  local c nf="$1"
  c="$(mktemp -d "$BASE.case.XXXXXX")"
  build_fixture "$c" "$nf" || { echo "fixture build failed" >&2; exit 1; }
  echo "$c"
}

BASE="$(mktemp -d)"

# --- case 1: all-pass fixture; mechanical derivation, byte identity
C1="$(new_case pass)" || exit 1
if [ "$(envelope_status "$C1")" = "pass" ]; then
  ok "all-pass fixture derives envelope status pass"
else
  bad "all-pass fixture derives envelope status pass (found $(envelope_status "$C1"))"
fi
expect "all-pass fixture check passes" 0 "" "$C1" "OK:"
sha256sum "$C1/measurements/characterization-report.json" \
          "$C1/signoff/characterization.envelope.json" > "$BASE.sums"
run --write "$C1"
if sha256sum -c "$BASE.sums" >/dev/null 2>&1; then
  ok "--write is byte-identical across runs"
else
  bad "--write is byte-identical across runs"
fi

# --- case 2: nf-fail fixture; the honest fail verdict
C2="$(new_case fail)" || exit 1
if [ "$(envelope_status "$C2")" = "fail" ]; then
  ok "nf-fail fixture derives envelope status fail"
else
  bad "nf-fail fixture derives envelope status fail (found $(envelope_status "$C2"))"
fi
expect "nf-fail fixture check passes (fail is a correct verdict)" 0 "" "$C2" "OK:" "envelope status fail"

# --- case 3: hand-edited report -> stale
C3="$(new_case fail)" || exit 1
python3 - "$C3" <<'PY'
import json, sys
p = sys.argv[1] + "/measurements/characterization-report.json"
r = json.load(open(p))
for row in r["rows"]:
    if row["id"] == "nf":
        row["measurements"][0]["worst_value"] = "0.9"
with open(p, "w") as fh:
    json.dump(r, fh, indent=2, sort_keys=True); fh.write("\n")
PY
expect "hand-edited report fails check" 1 "" "$C3" "does not match a fresh generation"

# --- case 4: hand-set envelope status over a failing row -> stale
C4="$(new_case fail)" || exit 1
python3 - "$C4" <<'PY'
import json, sys
p = sys.argv[1] + "/signoff/characterization.envelope.json"
e = json.load(open(p))
e["status"] = "pass"
with open(p, "w") as fh:
    json.dump(e, fh, indent=2, sort_keys=True); fh.write("\n")
PY
expect "hand-set envelope status fails check" 1 "" "$C4" \
  "signoff/characterization.envelope.json does not match a fresh generation"

# --- case 5: stale item-8 pin -> FAIL
C5="$(new_case fail)" || exit 1
python3 - "$C5" <<'PY'
import json, sys
p = sys.argv[1] + "/signoff/manifest.json"
m = json.load(open(p))
m["evidence"]["8"]["content_hash"] = "sha256:" + "0" * 64
with open(p, "w") as fh:
    json.dump(m, fh, indent=2, sort_keys=True); fh.write("\n")
PY
expect "stale item-8 manifest pin fails check" 1 "" "$C5" "pins sha256:"

# --- case 6: superseded record cited -> refuse everywhere
C6="$(new_case fail)" || exit 1
python3 - "$C6" <<'PY'
import json, sys
p = sys.argv[1] + "/signoff/testbench-coverage.json"
c = json.load(open(p))
c["claims"][0]["classification"] = "historical-dut"
with open(p, "w") as fh:
    json.dump(c, fh, indent=2, sort_keys=True); fh.write("\n")
PY
expect "superseded record refuses --write" 1 "--write" "$C6" "superseded DUT"
expect "superseded record refuses check" 1 "" "$C6" "superseded DUT"

# --- case 7: uncovered row with no declared gap -> refuse
C7="$(new_case fail)" || exit 1
python3 - "$C7" <<'PY'
import json, sys
p = sys.argv[1] + "/signoff/manifest.json"
m = json.load(open(p))
m["spec_rows"]["5"] = [e for e in m["spec_rows"]["5"] if e["id"] != "iip3"]
with open(p, "w") as fh:
    json.dump(m, fh, indent=2, sort_keys=True); fh.write("\n")
PY
expect "uncovered row without a gap refuses --write" 1 "--write" "$C7" \
  "neither a covering envelope nor a declared gap"

# --- case 8: citation rows disagreeing with the bench mapping -> refuse
C8="$(new_case fail)" || exit 1
python3 - "$C8" <<'PY'
import json, sys
p = sys.argv[1] + "/signoff/manifest.json"
m = json.load(open(p))
for c in m["evidence"]["5"]:
    if "matched_sp_stab" in c["file"]:
        c["rows"] = ["mu"]
with open(p, "w") as fh:
    json.dump(m, fh, indent=2, sort_keys=True); fh.write("\n")
PY
expect "citation rows disagreeing with the reducer refuse --write" 1 "--write" "$C8" \
  "declared rows"

# --- case 9: item 8 uncited -> note, check still passes
C9="$(new_case fail)" || exit 1
python3 - "$C9" <<'PY'
import json, sys
p = sys.argv[1] + "/signoff/manifest.json"
m = json.load(open(p))
del m["evidence"]["8"]
with open(p, "w") as fh:
    json.dump(m, fh, indent=2, sort_keys=True); fh.write("\n")
PY
expect "uncited item 8 passes check with a note" 0 "" "$C9" "OK:" "not cited"

echo ""
echo "passed: $pass  failed: $fail"
[ "$fail" -eq 0 ]
