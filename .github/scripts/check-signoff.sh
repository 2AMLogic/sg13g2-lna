#!/usr/bin/env bash
# check-signoff.sh — keep the committed klt signoff verdict-of-record
# honest, and keep its T1 evidence intact.
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
# After the render, check-signoff-scope.py rejects a `met` item 2/3/4 row
# whose cited layout evidence covers only part of the block (issue #80).
#
# With --base REF (CI's pull-request and merge-group runs, issue #446)
# the gate additionally compares the fresh render's T1 rows against the
# committed report at the merge base of REF: any T1 item that was `met`
# there and is not `met` now fails the run, named by id with its new
# status and reason. A gain on another item cannot cancel a loss, and
# faithfully regenerating the record of your own regression is not
# enough (the PR #444 shape). A deliberate downgrade is opt-in: a NEW
# entry under "## Acknowledged T1 downgrades" in signoff/README.md
# naming the T1 item and the reason acknowledges exactly that item,
# once; entries that already exist at the base, and entries for other
# items, authorize nothing. A baseline that cannot be resolved, read or
# parsed fails with a diagnostic, never a silent skip. Without --base
# (pushes to main, standalone freshness checks) no comparison runs.
#
# Requirements: klt on PATH (see signoff/README.md for the pinned
# install). Headless — needs no PDK, no KLayout project, no network
# beyond the pip install that put klt there. --base additionally needs
# the repo's git history (CI checks out with fetch-depth: 0).

set -u

payload_rc=0

fail() {
  echo "FAIL: $1" >&2
  exit 1
}

HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="$HERE/../.."
BASE=""
while [ $# -gt 0 ]; do
  case "$1" in
    --root)
      [ $# -ge 2 ] || fail "usage: $0 [--root DIR] [--base REF]"
      ROOT="$2"; shift 2 ;;
    --base)
      [ $# -ge 2 ] || fail "usage: $0 [--root DIR] [--base REF]"
      [ -n "$2" ] || fail "--base requires a non-empty ref (an empty event payload fails closed)"
      BASE="$2"; shift 2 ;;
    *)
      fail "unknown argument '$1' (usage: $0 [--root DIR] [--base REF])" ;;
  esac
done

MANIFEST="signoff/manifest.json"
TIERS_DOC="signoff/design-evidence-tiers.md"
RECORD="signoff/t1-report.json"
README_REL="signoff/README.md"

command -v klt >/dev/null 2>&1 || \
  fail "klt not on PATH — install the pinned release (see signoff/README.md): python3 -m pip install klayout-tools==0.9.2"

cd "$ROOT" || fail "cannot cd to $ROOT"
[ -f "$MANIFEST" ] || fail "missing $MANIFEST"
[ -f "$TIERS_DOC" ] || fail "missing $TIERS_DOC"
[ -f "$RECORD" ] || fail "missing $RECORD"

tmp="$(mktemp)"
err="$(mktemp)"
base_rep=""
base_read=""
trap 'rm -f "$tmp" "$err" ${base_rep:+"$base_rep"} ${base_read:+"$base_read"}' EXIT

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

# Scope guard (issue #80): a met layout/DRC/LVS row must not be backed by
# evidence for a partial cell. Reads the fresh render only to see whether a
# row is `met`; never rewrites a verdict. Stdlib python, no PDK.
python3 -I "$HERE/check-signoff-scope.py" --root . \
  --manifest "$MANIFEST" --report "$tmp" >&2 || \
  fail "layout citation scope guard rejected the signoff evidence (see signoff-scope lines above)"

# T1 met-regression gate (issue #446): compare the validated fresh render
# against the committed report at the merge base of $BASE. Bash does the git
# plumbing and fails closed on any baseline that cannot be resolved, read or
# parsed; the python block does the per-item comparison and the
# acknowledgement bookkeeping. Prints its own OK/NOTE/FAIL lines to stderr.
compare_regression() {
  git rev-parse --verify --quiet "${BASE}^{commit}" >/dev/null 2>&1 \
    || fail "--base '$BASE' does not resolve to a commit — fetch it with full history (CI checks out with fetch-depth: 0)"
  MB="$(git merge-base "$BASE" HEAD 2>/dev/null)" \
    || fail "no merge base between '$BASE' and HEAD (shallow clone? CI checks out with fetch-depth: 0)"
  base_rep="$(mktemp)"
  base_read="$(mktemp)"
  git show "$MB:$RECORD" >"$base_rep" 2>/dev/null \
    || fail "merge base ${MB:0:12} of '$BASE' has no $RECORD — a required baseline that cannot be read is a failure, not a skip"
  # A merge base without signoff/README.md simply has no acknowledgement
  # entries; every entry the candidate carries is then new.
  git show "$MB:$README_REL" >"$base_read" 2>/dev/null || : >"$base_read"
  python3 - "$base_rep" "$tmp" "$README_REL" "$base_read" "${MB:0:12}" "$BASE" <<'PY' || return 1
import json, re, sys

base_rep, cand_rep, readme_now, readme_base, mb, base_ref = sys.argv[1:7]

def die(msg):
    print(msg, file=sys.stderr)
    sys.exit(1)

try:
    base = json.load(open(base_rep))
except ValueError as e:
    die(f"FAIL: baseline signoff/t1-report.json at merge base {mb} of "
        f"'{base_ref}' did not parse as JSON ({e}) — a required baseline "
        "that cannot be read is a failure, not a skip")
try:
    cand = json.load(open(cand_rep))  # already validated by the payload gates
except ValueError as e:  # pragma: no cover — the payload gate read it first
    die(f"FAIL: fresh render did not parse ({e})")

def t1_map(report, what):
    items = report.get("items") if isinstance(report, dict) else None
    if not isinstance(items, list):
        die(f"FAIL: {what} report has no items[] list — cannot compare T1 rows")
    out = {}
    for it in items:
        if isinstance(it, dict) and isinstance(it.get("id"), int):
            out[it["id"]] = it  # T1 rows carry numeric ids; T2-T4 rows id null
    return out

b, c = t1_map(base, "baseline"), t1_map(cand, "fresh")

ACK_HEADING = "## Acknowledged T1 downgrades"
ACK_ENTRY = re.compile(r"^[-*] +T1 item (?P<item>[0-9]+)(?: +\(.+?\))?\s*:(?P<reason>.*)$")

def ack_entries(path):
    """Acknowledgement entry lines under the heading; a missing file has none."""
    try:
        lines = open(path).read().splitlines()
    except OSError:
        return set()
    out, under = set(), False
    for ln in lines:
        if ln.startswith("## "):
            under = ln.strip() == ACK_HEADING
        elif under:
            entry = ACK_ENTRY.fullmatch(ln)
            if entry and any(ch.isalnum() for ch in entry["reason"]):
                out.add((int(entry["item"]), ln.rstrip()))
    return out

new_entries = ack_entries(readme_now) - ack_entries(readme_base)
entry_of = dict(sorted(new_entries))

def label(i):
    src = c.get(i) or b.get(i) or {}
    t = src.get("title")
    return f"item {i} ({t})" if isinstance(t, str) and t else f"item {i}"

losses = []
for i in sorted(set(b) | set(c)):
    if b.get(i, {}).get("status") == "met" and c.get(i, {}).get("status") != "met":
        losses.append((i, label(i), c.get(i, {}).get("status"), c.get(i, {}).get("reason")))

if not losses:
    print(f"OK: no T1 met-item regression vs merge base {mb} of '{base_ref}'", file=sys.stderr)
    sys.exit(0)

unacked = any(i not in entry_of for i, *_ in losses)
if unacked:
    print(f"FAIL: T1 met-item regression vs merge base {mb} of '{base_ref}' (issue #446):", file=sys.stderr)
else:
    print(f"NOTE: {len(losses)} T1 item(s) lost their met status vs merge base {mb} of "
          f"'{base_ref}'; every loss is acknowledged by a new entry under "
          f"\"{ACK_HEADING}\" in signoff/README.md:", file=sys.stderr)

for i, lab, status, reason in losses:
    r = f" (reason: {reason})" if reason else ""
    mark = "acknowledged" if i in entry_of else "NOT acknowledged"
    print(f"  {lab}: met -> {status or 'missing'}{r} [{mark}]", file=sys.stderr)
    if i in entry_of:
        print(f"    acknowledged by: {entry_of[i]}", file=sys.stderr)

if unacked:
    print("A T1 item that was met at the merge base may not become unmet silently,", file=sys.stderr)
    print("and a gain on another item cannot cancel the loss. If the downgrade is", file=sys.stderr)
    print(f"deliberate, add a NEW entry under \"{ACK_HEADING}\" in signoff/README.md", file=sys.stderr)
    print("naming the T1 item and the reason — an entry that already exists at the", file=sys.stderr)
    print("merge base, or one for a different item, authorizes nothing. Otherwise", file=sys.stderr)
    print("repair the evidence and refresh the verdict of record.", file=sys.stderr)
    sys.exit(1)
PY
}

if cmp -s "$tmp" "$RECORD"; then
  if [ -n "$BASE" ]; then
    compare_regression || exit 1
  fi
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
