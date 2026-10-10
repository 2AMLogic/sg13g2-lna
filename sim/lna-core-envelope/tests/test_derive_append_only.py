"""Append-only publication tests for derive_committed_record_envelope.py
(issue #123). Stdlib only, PDK-free, no ngspice. Reads committed raw data;
writes only into temporary directories (the no-argument case must refuse and
write nothing).

    python3 -I -m unittest discover -s sim/lna-core-envelope/tests
"""
import hashlib
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

EXP = Path(__file__).resolve().parents[1]
SCRIPT = EXP / "derive_committed_record_envelope.py"
COMMITTED = EXP / "records" / "20260926-122301-088c734-derived-envelope.csv"


def run(*args):
    return subprocess.run([sys.executable, "-I", str(SCRIPT), *args],
                          capture_output=True, text=True)


def digest(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


class AppendOnly(unittest.TestCase):
    def test_no_argument_refuses_default_output(self):
        before = digest(COMMITTED)
        r = run()
        self.assertEqual(r.returncode, 4)
        self.assertIn("refusing to overwrite", r.stderr)
        self.assertEqual(digest(COMMITTED), before)

    def test_existing_explicit_out_refused(self):
        with tempfile.TemporaryDirectory() as d:
            out = Path(d) / "e.csv"
            out.write_bytes(b"landed")
            r = run("--out", str(out))
            self.assertEqual(r.returncode, 4)
            self.assertEqual(out.read_bytes(), b"landed")

    def test_fresh_out_matches_committed(self):
        with tempfile.TemporaryDirectory() as d:
            out = Path(d) / "sub" / "e.csv"
            r = run("--out", str(out))
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertEqual(out.read_bytes(), COMMITTED.read_bytes())

    def test_concurrent_writers_single_winner(self):
        with tempfile.TemporaryDirectory() as d:
            out = Path(d) / "e.csv"
            cmd = [sys.executable, "-I", str(SCRIPT), "--out", str(out)]
            ps = [subprocess.Popen(cmd, stdout=subprocess.DEVNULL,
                                   stderr=subprocess.DEVNULL)
                  for _ in range(2)]
            rcs = sorted(p.wait() for p in ps)
            # Either exactly one wins (0) and one is refused (4), or the
            # second started after the first finished: same outcome.
            self.assertEqual(rcs, [0, 4])
            self.assertEqual(out.read_bytes(), COMMITTED.read_bytes())


if __name__ == "__main__":
    unittest.main()
