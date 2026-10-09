"""Self-test for check_envelope_replay.py using temporary fixtures only."""
import contextlib
import io
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import check_envelope_replay as chk  # noqa: E402

GOOD = "a,b\n1,2.5\n3,4.5\n"


def run(script_body, committed_body):
    with tempfile.TemporaryDirectory() as tmp:
        t = Path(tmp)
        script = t / "derive.py"
        script.write_text(script_body)
        committed = t / "committed.csv"
        committed.write_text(committed_body)
        err = io.StringIO()
        with contextlib.redirect_stderr(err), contextlib.redirect_stdout(io.StringIO()):
            rc = chk.check(script, committed)
        return rc, err.getvalue()


def deriver(content):
    return (
        "import argparse\n"
        "ap = argparse.ArgumentParser(); ap.add_argument('--out', required=True)\n"
        "a = ap.parse_args()\n"
        f"open(a.out, 'w').write({content!r})\n")


class ReplayCheck(unittest.TestCase):
    def test_match_passes(self):
        self.assertEqual(run(deriver(GOOD), GOOD)[0], 0)

    def test_changed_value_fails(self):
        rc, err = run(deriver(GOOD.replace("4.5", "4.6")), GOOD)
        self.assertEqual(rc, 1)
        self.assertIn("line 3", err)
        self.assertIn("NEW evidence record", err)

    def test_failing_derivation_fails(self):
        rc, err = run("import sys; sys.exit(3)\n", GOOD)
        self.assertEqual(rc, 2)
        self.assertIn("derivation exited 3", err)

    def test_missing_committed_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            with contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(
                    chk.check(Path(tmp) / "x.py", Path(tmp) / "missing.csv"), 2)

    def test_real_data_replays(self):
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(chk.check(chk.DEFAULT_SCRIPT, chk.DEFAULT_COMMITTED), 0)


if __name__ == "__main__":
    unittest.main()
