#!/usr/bin/env bash
# Self-test for check-sim-append-only: prove the gate can fail.
# Cases (throwaway git repos; base branch "base", change committed on HEAD):
#   1. add a new record under records/                 -> passes
#   2. modify an existing records/*.md                 -> FAILS
#   3. delete an existing records/*.csv                -> FAILS
#   4. modify a file in netlist-snapshots/             -> FAILS
#   5. delete a file in corners/                       -> FAILS
#   6. rename a file out of records/                   -> FAILS
#   7. edit non-evidence files (run_x.sh, README.md)   -> passes
#   8. add a new file in an existing corners/<id>/ dir -> passes
#   9. bad --base ref                                  -> exit 2
#  10. mode-only change on a records/ file             -> FAILS
#  11. modify an evidence path containing spaces       -> FAILS
#  12. retarget a committed symlink under corners/     -> FAILS
set -u
HERE="$(cd "$(dirname "$0")" && pwd)"
CHECKER="$HERE/check-sim-append-only"
[ -x "$CHECKER" ] || { echo "FAIL: $CHECKER not executable" >&2; exit 1; }
TMP="$(mktemp -d)"; trap 'rm -rf "$TMP"' EXIT
pass=0; fail=0
ID=20260101-120000-abcdef1
NEW=20260202-130000-1234567

g() { git -C "$d" -c user.name=t -c user.email=t@t -c commit.gpgsign=false "$@"; }
mk() { # mk <dir> ; repo with committed evidence on branch "base", HEAD on "work"
  d="$TMP/$1"
  mkdir -p "$d/sim/x/records" "$d/sim/x/netlist-snapshots/$ID" \
    "$d/sim/x/corners/$ID" "$d/sim/x/records/with space"
  echo "record" > "$d/sim/x/records/$ID.md"
  echo "a,b" > "$d/sim/x/records/$ID.csv"
  echo "* deck" > "$d/sim/x/netlist-snapshots/$ID/tb.sp"
  echo "tt" > "$d/sim/x/corners/$ID/tt.csv"
  echo "s" > "$d/sim/x/records/with space/$ID notes.md"
  ln -s tt.csv "$d/sim/x/corners/$ID/link.csv"
  echo "#!/bin/sh" > "$d/sim/x/run_x.sh"
  echo "# x" > "$d/sim/x/README.md"
  g init -q -b base
  g add -A; g commit -q -m base
  g checkout -q -b work
}
commit() { g add -A; g commit -q -m change; }
run() { # run <name> <expect 0|1|2> <dir> [base]
  "$CHECKER" --root "$3" --base "${4:-base}" >/dev/null 2>&1; got=$?
  if [ "$got" -eq "$2" ]; then echo "PASS: $1"; pass=$((pass+1))
  else echo "FAIL: $1 (exit $got, wanted $2)"; fail=$((fail+1)); fi
}

mk add; echo new > "$d/sim/x/records/$NEW.md"; commit
run "add new record" 0 "$d"
mk modmd; echo more >> "$d/sim/x/records/$ID.md"; commit
run "modify records/*.md" 1 "$d"
mk delcsv; g rm -q "sim/x/records/$ID.csv"; commit
run "delete records/*.csv" 1 "$d"
mk modsnap; echo more >> "$d/sim/x/netlist-snapshots/$ID/tb.sp"; commit
run "modify netlist-snapshots/ file" 1 "$d"
mk delcorner; g rm -q "sim/x/corners/$ID/tt.csv"; commit
run "delete corners/ file" 1 "$d"
mk rename; g mv "sim/x/records/$ID.md" "sim/x/$ID.md"; commit
run "rename out of records/" 1 "$d"
mk source; echo "echo hi" >> "$d/sim/x/run_x.sh"; echo more >> "$d/sim/x/README.md"; commit
run "edit non-evidence files" 0 "$d"
mk addcorner; echo ff > "$d/sim/x/corners/$ID/ff.csv"; commit
run "add file in existing corners/<id>/" 0 "$d"
mk badbase
run "bad --base ref" 2 "$d" no-such-ref
mk mode; chmod +x "$d/sim/x/records/$ID.csv"; g -c core.fileMode=true add -A; g commit -q -m mode
run "mode-only change in records/" 1 "$d"
mk space; echo more >> "$d/sim/x/records/with space/$ID notes.md"; commit
run "modify path with spaces" 1 "$d"
mk symlink; ln -sfn ../../run_x.sh "$d/sim/x/corners/$ID/link.csv"; commit
run "retarget symlink in corners/" 1 "$d"

echo "$pass passed, $fail failed"
[ "$fail" -eq 0 ]
