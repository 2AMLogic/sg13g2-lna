#!/usr/bin/env python3
"""Replay the committed core-envelope derivation and diff it against the record.

Runs derive_committed_record_envelope.py with an explicit --out inside a
temporary directory (never the script's default path, which is inside the
append-only records/ tree), then compares the output byte-for-byte with the
committed derived CSV. Stdlib only; no PDK, no ngspice, no network.

Exit codes: 0 match, 1 differs, 2 derivation failed / missing input.
"""
import argparse
import difflib
import subprocess
import sys
import tempfile
from pathlib import Path

EXP = Path(__file__).resolve().parent.parent
DEFAULT_SCRIPT = EXP / "derive_committed_record_envelope.py"
DEFAULT_COMMITTED = EXP / "records" / "20260926-122301-088c734-derived-envelope.csv"


def check(script: Path, committed: Path, extra_args=()) -> int:
    if not committed.is_file():
        print(f"FAIL: committed derived record not found: {committed}", file=sys.stderr)
        return 2
    with tempfile.TemporaryDirectory(prefix="envelope-replay-") as tmp:
        out = Path(tmp) / "derived.csv"
        proc = subprocess.run(
            [sys.executable, "-I", str(script), "--out", str(out), *extra_args],
            capture_output=True, text=True)
        if proc.returncode != 0:
            print(f"FAIL: derivation exited {proc.returncode}\n{proc.stdout}{proc.stderr}",
                  file=sys.stderr)
            return 2
        if not out.is_file():
            print(f"FAIL: derivation wrote no output at {out}", file=sys.stderr)
            return 2
        got = out.read_text().splitlines()
        want = committed.read_text().splitlines()
    if got == want:
        print(f"OK: replayed derivation matches {committed.name} ({len(want)} lines)")
        return 0
    n = next((i for i, (a, b) in enumerate(zip(want, got)) if a != b),
             min(len(want), len(got)))
    print(f"FAIL: replay differs from {committed.name}; first difference at line {n + 1} "
          f"(committed {len(want)} lines, replayed {len(got)} lines)", file=sys.stderr)
    diff = difflib.unified_diff(want, got, "committed", "replayed", n=1, lineterm="")
    for i, line in enumerate(diff):
        if i >= 40:
            print("... (diff truncated)", file=sys.stderr)
            break
        print(line, file=sys.stderr)
    print("If the change is an intentional scientific correction, mint a NEW evidence "
          "record; do not replace the historical output (sim/README.md, append-only).",
          file=sys.stderr)
    return 1


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--script", type=Path, default=DEFAULT_SCRIPT)
    ap.add_argument("--committed", type=Path, default=DEFAULT_COMMITTED)
    args = ap.parse_args()
    return check(args.script, args.committed)


if __name__ == "__main__":
    sys.exit(main())
