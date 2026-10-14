#!/usr/bin/env bash
# Self-test for check-layout-freshness: prove the gate can fail.
# Each case works on a throwaway copy of the layout inputs.
#   1. matching tree                      -> passes
#   2. mutated provenance gds_sha256      -> FAILS
#   3. netlist with an extra device       -> FAILS
#   4. mutated committed LVS reference    -> FAILS
#   5. mutated drc_report content_hash    -> FAILS
#   6. mutated lvs_full_report content_hash -> FAILS
#   7. missing content_hash field         -> FAILS
#   9. lvs_inputs.json (issue #130): missing, malformed, and independent
#      mutation of each reference / request / report -> FAIL, naming it
#   8. extract_report / lvs_report (scoped LVS): mutated hash, missing
#      report, missing provenance.input, wrong role, malformed hash -> FAIL
#   9. native DRC pair (issue #185): absent passes; one-sided, mutated
#      report/GDS/deck/pdk/status bindings, or an executable below its
#      recorded minimum -> FAIL, naming the relationship
set -u
HERE="$(cd "$(dirname "$0")" && pwd)"
CHECKER="$HERE/check-layout-freshness"
SRC="$(cd "$HERE/../.." && pwd)"
[ -x "$CHECKER" ] || { echo "FAIL: $CHECKER not executable" >&2; exit 1; }
while [ $# -gt 0 ]; do
  case "$1" in --root) SRC="$2"; shift 2 ;; *) echo "usage: $0 [--root DIR]" >&2; exit 2 ;; esac
done
TMP="$(mktemp -d)"; trap 'rm -rf "$TMP"' EXIT
pass=0; fail=0
C=layout/lna_core

mk() { # mk <name>: repo-shaped copy of the inputs
  d="$TMP/$1"; mkdir -p "$d/$C" "$d/design/netlist"
  cp "$SRC/layout/lvs_reference.py" "$d/layout/"
  cp "$SRC/$C"/{lna_core.gds,lna_core.provenance.json,lna_core.lvs_reference.spice,realization.json,drc_report.json,lvs_full_report.json,extract_report.json,lvs_report.json,lna_core.extracted.spice} "$d/$C/"
  cp "$SRC/design/netlist/lna.spice" "$d/design/netlist/"
  cp "$SRC/$C"/{lvs_request.json,lvs_full_request.json} "$d/$C/"
  cp "$SRC/layout/lvs_identity.py" "$d/layout/"
  # fixture sidecar: what run_flow.sh would record after each klt lvs run
  # (the committed tree's own sidecar is produced only by a real local run)
  for p in "lvs_request.json lvs_report.json" "lvs_full_request.json lvs_full_report.json"; do
    python3 -I "$d/layout/lvs_identity.py" "$d/$C" $p >/dev/null
  done
}
run() { # run <name> <expect 0|1>
  if "$CHECKER" --root "$TMP/$1" >/dev/null 2>&1; then got=0; else got=1; fi
  if [ "$got" -eq "$2" ]; then echo "PASS: $3"; pass=$((pass+1))
  else echo "FAIL: $3 (exit-class $got, wanted $2)"; fail=$((fail+1)); fi
}
sub() { sed -i "$1" "$2"; }

mk ok; run ok 0 "matching tree"
mk prov; sub 's/\("gds_sha256": "\)./\10/' "$TMP/prov/$C/lna_core.provenance.json"
if cmp -s "$TMP/prov/$C/lna_core.provenance.json" "$SRC/$C/lna_core.provenance.json"; then
  sub 's/\("gds_sha256": "\)./\11/' "$TMP/prov/$C/lna_core.provenance.json"
fi
run prov 1 "mutated provenance gds_sha256"
mk net; sub '/^\*\*\.ends/i XQ99 a b c vss npn13G2 Nx=2' "$TMP/net/design/netlist/lna.spice"
run net 1 "netlist with an extra device"
mk ref; echo "* tampered" >> "$TMP/ref/$C/lna_core.lvs_reference.spice"
run ref 1 "mutated committed reference"
for r in drc_report lvs_full_report; do
  mk $r; python3 -I - "$TMP/$r/$C/$r.json" <<'PY'
import json, sys
p = sys.argv[1]; d = json.load(open(p))
d["provenance"]["input"]["content_hash"] = "sha256:" + "0" * 64
json.dump(d, open(p, "w"))
PY
  run $r 1 "mutated $r content_hash"
done
mk nofield; python3 -I - "$TMP/nofield/$C/drc_report.json" <<'PY'
import json, sys
p = sys.argv[1]; d = json.load(open(p))
del d["provenance"]["input"]["content_hash"]
json.dump(d, open(p, "w"))
PY
run nofield 1 "missing content_hash field"

mut() { python3 -I - "$TMP/$1/$C/$2.json" "$3" <<'PY'
import json, sys
p, how = sys.argv[1], sys.argv[2]; d = json.load(open(p))
i = d["provenance"]["input"]
if how == "hash": i["content_hash"] = "sha256:" + "0" * 64
elif how == "malformed": i["content_hash"] = "deadbeef"
elif how == "role": i["role"] = "netlist"
elif how == "noinput": del d["provenance"]["input"]
json.dump(d, open(p, "w"))
PY
}
for r in extract_report lvs_report; do
  mk $r-hash; mut $r-hash $r hash
  run $r-hash 1 "mutated $r content_hash"
  for how in malformed role noinput; do
    mk $r-$how; mut $r-$how $r $how
    run $r-$how 1 "$r $how"
  done
  mk $r-missing; rm "$TMP/$r-missing/$C/$r.json"
  run $r-missing 1 "missing $r.json"
  # failure must name the offending report
  if "$CHECKER" --root "$TMP/$r-hash" 2>&1 | grep -q "$r.json"; then
    echo "PASS: $r failure names report"; pass=$((pass+1))
  else echo "FAIL: $r failure does not name report"; fail=$((fail+1)); fi
done

# --- issue #130: LVS input identity ---
named() { # named <case> <substring>: failure output must contain it
  if "$CHECKER" --root "$TMP/$1" 2>&1 | grep -q -- "$2"; then
    echo "PASS: $1 failure names '$2'"; pass=$((pass+1))
  else echo "FAIL: $1 failure does not name '$2'"; fail=$((fail+1)); fi
}
mk id-nosidecar; rm "$TMP/id-nosidecar/$C/lvs_inputs.json"
run id-nosidecar 1 "missing lvs_inputs.json"; named id-nosidecar "lvs_inputs.json"
mk id-badjson; echo '{not json' > "$TMP/id-badjson/$C/lvs_inputs.json"
run id-badjson 1 "unparseable lvs_inputs.json"
mk id-schema; echo '{"schema":"x","reports":{}}' > "$TMP/id-schema/$C/lvs_inputs.json"
run id-schema 1 "wrong-schema lvs_inputs.json"
mk id-noentry; python3 -I - "$TMP/id-noentry/$C/lvs_inputs.json" <<'PY'
import json, sys
p = sys.argv[1]; d = json.load(open(p)); del d["reports"]["lvs_full_report.json"]
json.dump(d, open(p, "w"))
PY
run id-noentry 1 "missing full-LVS sidecar entry"
mk id-nofield; python3 -I - "$TMP/id-nofield/$C/lvs_inputs.json" <<'PY'
import json, sys
p = sys.argv[1]; d = json.load(open(p)); del d["reports"]["lvs_report.json"]["reference_sha256"]
json.dump(d, open(p, "w"))
PY
run id-nofield 1 "missing reference_sha256 field"
# independent mutations (each leaves the GDS hash and every other input alone)
mk id-ok2; run id-ok2 0 "sidecar-bearing tree"
mk id-ref-scoped   # scoped reference: also trips check 2, so assert the sidecar names it
echo "* tampered" >> "$TMP/id-ref-scoped/$C/lna_core.lvs_reference.spice"
run id-ref-scoped 1 "mutated scoped reference"; named id-ref-scoped "reference netlist"
mk id-ref-full; echo "* tampered" >> "$TMP/id-ref-full/design/netlist/lna.spice"
run id-ref-full 1 "mutated full-LVS reference netlist"
named id-ref-full "lvs_full_report.json\].*reference netlist"
mk id-req; python3 -I - "$TMP/id-req/$C/lvs_request.json" <<'PY'
import json, sys
p = sys.argv[1]; d = json.load(open(p)); d["options"]["combine_devices"] = False
json.dump(d, open(p, "w"), indent=2)
PY
run id-req 1 "mutated scoped request"; named id-req "lvs_report.json\].*request lvs_request.json"
mk id-freq; python3 -I - "$TMP/id-freq/$C/lvs_full_request.json" <<'PY'
import json, sys
p = sys.argv[1]; d = json.load(open(p)); d["options"]["combine_devices"] = False
json.dump(d, open(p, "w"), indent=2)
PY
run id-freq 1 "mutated full request"; named id-freq "lvs_full_report.json\].*request lvs_full_request.json"
mk id-rep; echo " " >> "$TMP/id-rep/$C/lvs_report.json"
run id-rep 1 "mutated scoped report bytes"; named id-rep "lvs_report.json\].*report lvs_report.json"
mk id-frep; echo " " >> "$TMP/id-frep/$C/lvs_full_report.json"
run id-frep 1 "mutated full report bytes"; named id-frep "lvs_full_report.json\].*report lvs_full_report.json"
mk id-repath; python3 -I - "$TMP/id-repath/$C/lvs_full_request.json" <<'PY'
import json, sys
p = sys.argv[1]; d = json.load(open(p)); d["reference"]["netlist"] = "lna_core.lvs_reference.spice"
json.dump(d, open(p, "w"), indent=2)
PY
run id-repath 1 "request repointed at another reference"

# --- issue #176: extraction output vs netlist_sha256 ---
exmut() { # exmut <case> <python statement on d>
  python3 -I - "$TMP/$1/$C/extract_report.json" "$2" <<'PY'
import json, sys
p = sys.argv[1]; d = json.load(open(p)); exec(sys.argv[2])
json.dump(d, open(p, "w"))
PY
}
mk ex-ok; run ex-ok 0 "pristine extraction output"
mk ex-bytes; echo "* tampered" >> "$TMP/ex-bytes/$C/lna_core.extracted.spice"
run ex-bytes 1 "changed extraction output bytes"; named ex-bytes "extraction output .* != netlist_sha256"
mk ex-ws; sed -i '1s/$/ /' "$TMP/ex-ws/$C/lna_core.extracted.spice"
run ex-ws 1 "whitespace-only change to extraction output"
mk ex-del; rm "$TMP/ex-del/$C/lna_core.extracted.spice"
run ex-del 1 "deleted extraction output"; named ex-del "extraction output .* missing"
mk ex-nopath; exmut ex-nopath 'del d["netlist_path"]'
run ex-nopath 1 "missing netlist_path"; named ex-nopath "netlist_path missing or malformed"
mk ex-badpath; exmut ex-badpath 'd["netlist_path"] = 5'
run ex-badpath 1 "non-string netlist_path"
mk ex-nohash; exmut ex-nohash 'del d["netlist_sha256"]'
run ex-nohash 1 "missing netlist_sha256"; named ex-nohash "netlist_sha256 missing or malformed"
mk ex-badhash; exmut ex-badhash 'd["netlist_sha256"] = "sha256:" + d["netlist_sha256"]'
run ex-badhash 1 "malformed netlist_sha256"; named ex-badhash "netlist_sha256 missing or malformed"
mk ex-esc; cp "$TMP/ex-esc/$C/lna_core.extracted.spice" "$TMP/outside.spice"
exmut ex-esc 'd["netlist_path"] = "../../../outside.spice"'
run ex-esc 1 "netlist_path escaping the repository"; named ex-esc "escapes the repository"
mk ex-abs; exmut ex-abs 'd["netlist_path"] = "'"$TMP"'/outside.spice"'
run ex-abs 1 "absolute netlist_path"; named ex-abs "absolute"
# a repo-local output in a subdirectory of the report dir resolves relative to it
mk ex-sub; mkdir "$TMP/ex-sub/$C/sub"; mv "$TMP/ex-sub/$C/lna_core.extracted.spice" "$TMP/ex-sub/$C/sub/"
exmut ex-sub 'd["netlist_path"] = "sub/lna_core.extracted.spice"'
run ex-sub 0 "output resolved relative to report directory"

# --- issue #185: native DRC report/sidecar pair ---
# Fixture pairs are built by the real recorder (layout/native_drc_identity.py)
# over a synthetic native report, in the throwaway copy only. No fabricated
# native report is ever committed to the tree (issue #201 owns the real run).
mknative() { # mknative <name>: consistent native pair on top of a fresh copy
  mk "$1"
  python3 -I - "$TMP/$1/$C/lna_core.gds" "$TMP/$1/$C/native_drc_report.json" <<'PY'
import hashlib, json, sys
gds_sha = hashlib.sha256(open(sys.argv[1], "rb").read()).hexdigest()
rep = {
  "schema_version": 2, "file": "lna_core.gds", "deck": "ihp-sg13g2-native",
  "dbu_um": 0.001, "status": "violations", "violation_count": 1,
  "rule_counts": {"m1.width.1": 1}, "metrics": {"drc__error__count": 1},
  "violations": [{"rule": "m1.width.1"}],
  "coverage": {"schema_version": 1, "known": True},
  "provenance": {
    "klt_version": "0.7.0", "klayout_version": "0.30.30",
    "pdk": {"name": "ihp-sg13g2", "version": "0.3.0"},
    "deck": {"name": "ihp-sg13g2-native",
             "content_hash": "sha256:" + "d" * 64, "released": True},
    "input": {"role": "layout", "content_hash": "sha256:" + gds_sha},
  },
}
json.dump(rep, open(sys.argv[2], "w"), indent=2)
PY
  python3 -I "$SRC/layout/native_drc_identity.py" record "$TMP/$1/$C" \
    native_drc_report.json --gds "$TMP/$1/$C/lna_core.gds" \
    --klayout-exe klayout --klayout-exe-resolved /usr/local/bin/klayout \
    --klayout-exe-version "KLayout 0.30.30 (2026-01-01) deadbee" \
    --min-klayout-version 0.29.0 --pdk ihp-sg13g2 \
    --klt-version-json '{"schema_version":1,"version":"0.7.0","is_release":true}' \
    --argv '["klt","drc","--engine","klayout","--pdk","ihp-sg13g2"]' >/dev/null
}
natmut() { # natmut <case> <python statement on d (the sidecar doc)>
  python3 -I - "$TMP/$1/$C/native_drc_inputs.json" "$2" <<'PY'
import json, sys
p, stmt = sys.argv[1], sys.argv[2]
d = json.load(open(p)); exec(stmt)
json.dump(d, open(p, "w"), indent=2)
PY
}
mk nat-absent; run nat-absent 0 "absent native pair passes"
mknative nat-ok; run nat-ok 0 "consistent native pair"
mknative nat-reponly; rm "$TMP/nat-reponly/$C/native_drc_inputs.json"
run nat-reponly 1 "native report without sidecar"
named nat-reponly "native_drc_inputs.json missing"
mknative nat-sideonly; rm "$TMP/nat-sideonly/$C/native_drc_report.json"
run nat-sideonly 1 "native sidecar without report"
named nat-sideonly "native_drc_report.json missing"
mknative nat-repbytes; echo " " >> "$TMP/nat-repbytes/$C/native_drc_report.json"
run nat-repbytes 1 "mutated native report bytes"
named nat-repbytes "report changed since this native run"
mknative nat-sidesha; natmut nat-sidesha \
  'd["report_sha256"] = "0" * 64'
run nat-sidesha 1 "mutated recorded report digest"
named nat-sidesha "report changed since this native run"
mknative nat-gdssha; natmut nat-gdssha 'd["gds_sha256"] = "0" * 64'
run nat-gdssha 1 "mutated recorded GDS digest"
named nat-gdssha "GDS changed since this native run"
mknative nat-gdsbytes; echo " " >> "$TMP/nat-gdsbytes/$C/lna_core.gds"
run nat-gdsbytes 1 "mutated GDS bytes"
named nat-gdsbytes "GDS changed since this native run"
mknative nat-deck; natmut nat-deck 'd["deck_binding"] = {"name": "other"}'
run nat-deck 1 "mutated deck binding"
named nat-deck "deck_binding differs"
mknative nat-pdk; natmut nat-pdk 'd["pdk_binding"] = {"name": "other-pdk"}'
run nat-pdk 1 "mutated pdk binding"
named nat-pdk "pdk_binding differs"
mknative nat-status; natmut nat-status 'd["status"] = "clean"'
run nat-status 1 "sidecar status != report status"
named nat-status "status 'clean' != report status 'violations'"
mknative nat-repstatus; python3 -I - "$TMP/nat-repstatus/$C/native_drc_report.json" <<'PY'
import json, sys
p = sys.argv[1]; d = json.load(open(p)); d["status"] = "bananas"
json.dump(d, open(p, "w"), indent=2)
PY
run nat-repstatus 1 "report status outside the completed set"
named nat-repstatus "want one of"
mknative nat-repinput; python3 -I - "$TMP/nat-repinput/$C/native_drc_report.json" <<'PY'
import json, sys
p = sys.argv[1]; d = json.load(open(p))
d["provenance"]["input"]["content_hash"] = "sha256:" + "0" * 64
json.dump(d, open(p, "w"), indent=2)
PY
run nat-repinput 1 "native report repinned at other bytes"
named nat-repinput "provenance.input.content_hash"
mknative nat-oldexe; natmut nat-oldexe 'd["klayout_exe_version"] = "KLayout 0.28.16 (2023-12-30) old"'
run nat-oldexe 1 "executable below its recorded minimum"
named nat-oldexe "below min_klayout_version"
mknative nat-badmin; natmut nat-badmin 'd["min_klayout_version"] = "banana"'
run nat-badmin 1 "unparseable recorded minimum"
named nat-badmin "min_klayout_version 'banana' unparseable"
mknative nat-badschema; natmut nat-badschema 'd["schema"] = "x"'
run nat-badschema 1 "wrong-schema native sidecar"
mknative nat-noklt; natmut nat-noklt 'del d["klt"]'
run nat-noklt 1 "native sidecar without klt identity"
named nat-noklt "klt identity"
mknative nat-noargv; natmut nat-noargv 'del d["argv"]'
run nat-noargv 1 "native sidecar without argv"
named nat-noargv "argv"
mknative nat-nodeck; natmut nat-nodeck 'del d["deck_binding"]'
run nat-nodeck 1 "native sidecar without deck binding"
named nat-nodeck "missing deck_binding"

echo "$pass passed, $fail failed"
[ "$fail" -eq 0 ]
