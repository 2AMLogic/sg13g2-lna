#!/usr/bin/env bash
# check-signoff.sh — keep the committed klt signoff verdict-of-record
# honest.
#
# Re-renders the T1-T4 tier report from the committed block manifest and
# the vendored design-evidence-tiers doc, then compares the fresh render
# byte-for-byte against signoff/t1-report.json. Any drift — a manifest
# citation whose artifact changed, a reworded checklist, a stale record —
# fails here instead of rotting. Refreshing the record is a deliberate
# act:
#
#   klt signoff --manifest signoff/manifest.json \
#     --tiers-doc signoff/design-evidence-tiers.md --format json \
#     > signoff/t1-report.json
#
# "Runs clean" follows docs/cli/signoff.md's exit-code contract: 0 (all
# T1 items met) and 3 (ran successfully, at least one item unmet) are
# both successful renders — an all-unmet report is a correct verdict,
# not a CI failure. Everything else (bad manifest, unparsable tiers doc,
# usage error) is a hard failure. The payload's own fields are the real
# gate (the doc's rule: "gate on status/tier, not the exit code"): the
# fresh render must parse, carry the expected block/kind, and contain no
# top-level error block.
#
# Requirements: klt on PATH (see signoff/README.md for the pinned
# install). Headless — needs no PDK, no KLayout project, no network
# beyond the pip install that put klt there.

set -u

payload_rc=0

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
if [ "${1:-}" = "--root" ] && [ -n "${2:-}" ]; then
  ROOT="$2"
  shift 2
fi

MANIFEST="signoff/manifest.json"
TIERS_DOC="signoff/design-evidence-tiers.md"
RECORD="signoff/t1-report.json"

fail() {
  echo "FAIL: $1" >&2
  exit 1
}

command -v klt >/dev/null 2>&1 || \
  fail "klt not on PATH — install the pinned release (see signoff/README.md): python3 -m pip install klayout-tools==0.6.0"

cd "$ROOT" || fail "cannot cd to $ROOT"
[ -f "$MANIFEST" ] || fail "missing $MANIFEST"
[ -f "$TIERS_DOC" ] || fail "missing $TIERS_DOC"
[ -f "$RECORD" ] || fail "missing $RECORD"

tmp="$(mktemp)"
err="$(mktemp)"
trap 'rm -f "$tmp" "$err"' EXIT

klt signoff --manifest "$MANIFEST" --tiers-doc "$TIERS_DOC" --format json \
  >"$tmp" 2>"$err"
rc=$?

# Report payload gates before drift comparison: a failing manifest whose
# fresh render accidentally matches a stale committed record must still
# fail.
python3 - "$tmp" <<'PY' || payload_rc=1
import json, sys

with open(sys.argv[1]) as f:
    report = json.load(f)

assert isinstance(report, dict), "report is not a JSON object"
assert "error" not in report, f"report is a klt error envelope: {report.get('error')}"
assert report.get("schema_version") == 1, "unexpected report schema_version"
assert report.get("block") == "sg13g2-lna", "report does not grade this block"
assert report.get("kind") == "analog", "report does not grade kind=analog"
assert report.get("t1_item_count") == 11, "report does not render the 11-item checklist"
PY
if [ "${payload_rc:-0}" -ne 0 ]; then
  cat "$err" >&2
  fail "fresh render did not produce a valid sg13g2-lna/analog tier report"
fi

case "$rc" in
  0|3) ;;  # ran clean: all-met (0) or tier: null with unmet items (3)
  *) cat "$err" >&2; fail "klt signoff did not run clean (exit $rc) — 0 (all T1 met) and 3 (>=1 unmet) are both valid verdicts; any other exit is a broken manifest/doc" ;;
esac

if cmp -s "$tmp" "$RECORD"; then
  met="$(python3 -c 'import json,sys; r=json.load(open(sys.argv[1])); print(r["t1_met_count"])' "$RECORD")"
  count="$(python3 -c 'import json,sys; r=json.load(open(sys.argv[1])); print(r["t1_item_count"])' "$RECORD")"
  echo "OK: signoff/t1-report.json matches the fresh klt render (T1: $met/$count items met; tier: $(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["tier"])' "$RECORD"))"
  exit 0
fi

echo "FAIL: signoff/t1-report.json does not match the fresh klt render — the verdict of record has drifted." >&2
echo "" >&2
echo "A manifest citation, the vendored tiers doc, or the klt pin changed" >&2
echo "without refreshing the record. Diff (committed vs fresh):" >&2
echo "" >&2
diff "$RECORD" "$tmp" >&2 || true
echo "" >&2
echo "If the change is deliberate, refresh the verdict of record and commit it:" >&2
echo "  klt signoff --manifest signoff/manifest.json \\" >&2
echo "    --tiers-doc signoff/design-evidence-tiers.md --format json \\" >&2
echo "  > signoff/t1-report.json" >&2
exit 1
