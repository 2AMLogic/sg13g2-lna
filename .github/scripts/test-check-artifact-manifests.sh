#!/usr/bin/env bash
# Self-test for check-artifact-manifests.py (issue #222): prove the gate can fail.
# Cases (throwaway git repos):
#   1. no manifests at all                              -> passes
#   2. one valid manifest + summary                     -> passes
#   3. an s3:// uri                                     -> FAILS
#   4. a non-artifact: uri (https://)                   -> FAILS
#   5. uri key not ending in the sha256                 -> FAILS
#   6. a stored object's sha256 matches a committed file-> FAILS
#   7. manifest without its summary                     -> FAILS
#   8. unknown entry field                              -> FAILS
#   9. an arn:aws: string in a summary                  -> FAILS
#  10. invalid JSON                                     -> FAILS
set -u
HERE="$(cd "$(dirname "$0")" && pwd)"
CHECKER="$HERE/check-artifact-manifests.py"
[ -f "$CHECKER" ] || { echo "FAIL: $CHECKER missing" >&2; exit 1; }
TMP="$(mktemp -d)"; trap 'rm -rf "$TMP"' EXIT
pass=0; fail=0
SHA="$(printf 'raw output\n' | sha256sum | cut -d' ' -f1)"
OTHER="$(printf 'other\n' | sha256sum | cut -d' ' -f1)"

mk() { # mk <name> <uri> [extra-json-field]; sets $d
  d="$TMP/$1"; mkdir -p "$d/manifests/artifacts" "$d/sim"
  echo "kept" > "$d/sim/kept.txt"
  if [ -n "${2:-}" ]; then
    printf '{"schema_version":1,"entries":[{"sha256":"%s","size":11,"kind":"evidence","producer":{"tool":"klt","version":"0","loom.repo":"o/r","commit":null},"uri":"%s","name":"b/r/a.log"%s}]}\n' \
      "$SHA" "$2" "${3:-}" > "$d/manifests/artifacts/b-r.manifest.json"
    echo "# summary" > "$d/manifests/artifacts/b-r.summary.md"
  fi
}
run() { # run <label> <expect: 0|1>
  git -C "$d" init -q 2>/dev/null; git -C "$d" add -A
  out="$(python3 -I "$CHECKER" --root "$d" 2>&1)"; rc=$?
  if [ "$rc" -eq "$2" ]; then echo "PASS: $1"; pass=$((pass+1))
  else echo "FAIL: $1 (exit $rc, wanted $2): $out"; fail=$((fail+1)); fi
}

mk c1; run "no manifests" 0
mk c2 "artifact:evidence/o__r/$SHA"; run "valid manifest" 0
mk c3 "s3://bucket/$SHA"; run "s3 uri rejected" 1
mk c4 "https://x.invalid/$SHA"; run "non-artifact uri rejected" 1
mk c5 "artifact:evidence/o__r/$OTHER"; run "uri key not the sha256" 1
mk c6 "artifact:evidence/o__r/$SHA"; printf 'raw output\n' > "$d/sim/committed.log"; run "stored object also committed" 1
mk c7 "artifact:evidence/o__r/$SHA"; rm "$d/manifests/artifacts/b-r.summary.md"; run "missing summary" 1
mk c8 "artifact:evidence/o__r/$SHA" ',"extra":1'; run "unknown field" 1
mk c9 "artifact:evidence/o__r/$SHA"; echo "arn:aws:s3:::x" >> "$d/manifests/artifacts/b-r.summary.md"; run "storage location in summary" 1
mk c10 "artifact:evidence/o__r/$SHA"; echo "{" > "$d/manifests/artifacts/b-r.manifest.json"; run "invalid JSON" 1

echo "pass=$pass fail=$fail"
[ "$fail" -eq 0 ]
