#!/usr/bin/env python3
"""Replay the breakdown summary reduction and diff it byte-for-byte (issue #145).

Regenerates both summaries into a temporary directory from explicitly named
committed input CSVs (default: the record pinned in RECORD_ID below, never the
newest by timestamp) using reduce_breakdown.py, then compares bytes with the
committed summaries. Stdlib only; no PDK, ngspice or klt; never writes under
records/.

Exit codes: 0 match, 1 differs, 2 missing input / reduction failed.
"""
import argparse
import subprocess
import sys
import tempfile
from pathlib import Path

EXP = Path(__file__).resolve().parent.parent
REDUCER = EXP / "reduce_breakdown.py"
RECORD_ID = "20260918-212948-013274f"
REC = EXP / "records"


def check(locus, sweep, locus_summary, sweep_summary, reducer=REDUCER) -> int:
    for p in (locus, sweep, locus_summary, sweep_summary):
        if not Path(p).is_file():
            print(f"FAIL: input not found: {p}", file=sys.stderr)
            return 2
    with tempfile.TemporaryDirectory(prefix="breakdown-replay-") as tmp:
        oa, ob = Path(tmp) / "locus-summary.csv", Path(tmp) / "sweep-summary.csv"
        proc = subprocess.run(
            [sys.executable, "-I", str(reducer), "--locus", str(locus), "--sweep", str(sweep),
             "--out-locus-summary", str(oa), "--out-sweep-summary", str(ob)],
            capture_output=True, text=True)
        if proc.returncode != 0:
            print(f"FAIL: reduction exited {proc.returncode}\n{proc.stdout}{proc.stderr}",
                  file=sys.stderr)
            return 2
        rc = 0
        for got_p, want_p in ((oa, locus_summary), (ob, sweep_summary)):
            got, want = got_p.read_bytes(), Path(want_p).read_bytes()
            if got == want:
                print(f"OK: replay matches {Path(want_p).name} ({len(want)} bytes)")
                continue
            gl, wl = got.split(b"\n"), want.split(b"\n")
            n = next((i for i, (a, b) in enumerate(zip(wl, gl)) if a != b), min(len(wl), len(gl)))
            print(f"FAIL: replay differs from {Path(want_p).name}; first difference at line "
                  f"{n + 1} (committed {len(wl)} lines, replayed {len(gl)} lines)", file=sys.stderr)
            if n < len(wl) and n < len(gl):
                print(f"  committed: {wl[n].decode(errors='replace')}", file=sys.stderr)
                print(f"  replayed:  {gl[n].decode(errors='replace')}", file=sys.stderr)
            rc = 1
        if rc:
            print("If the change is an intentional scientific correction, mint a NEW evidence "
                  "record; do not replace the historical output (sim/README.md, append-only).",
                  file=sys.stderr)
        return rc


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--record-id", default=RECORD_ID)
    ap.add_argument("--locus"); ap.add_argument("--sweep")
    ap.add_argument("--locus-summary"); ap.add_argument("--sweep-summary")
    a = ap.parse_args(argv)
    r = a.record_id
    return check(a.locus or REC / f"{r}-bvceo-locus.csv",
                 a.sweep or REC / f"{r}-heldbase-sweep.csv",
                 a.locus_summary or REC / f"{r}-bvceo-summary.csv",
                 a.sweep_summary or REC / f"{r}-heldbase-summary.csv")


if __name__ == "__main__":
    sys.exit(main())
