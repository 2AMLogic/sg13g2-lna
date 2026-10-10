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
#   8. extract_report / lvs_report (scoped LVS): mutated hash, missing
#      report, missing provenance.input, wrong role, malformed hash -> FAIL
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
  cp "$SRC/$C"/{lna_core.gds,lna_core.provenance.json,lna_core.lvs_reference.spice,realization.json,drc_report.json,lvs_full_report.json,extract_report.json,lvs_report.json} "$d/$C/"
  cp "$SRC/design/netlist/lna.spice" "$d/design/netlist/"
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

echo "$pass passed, $fail failed"
[ "$fail" -eq 0 ]
