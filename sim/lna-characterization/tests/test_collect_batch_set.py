"""Fixture tests for the shared `klt sim --batch-set` collector (issue #454).

lna_variant_campaign.py collect-set is the single reader of the set envelope
on the batch path of run_lna_variant.sh and run_lna_iip3.sh. These tests
replay, per runner label and with each runner's exact invocation shape, the
fixture classes the issue recorded for the previous inline blocks:

  1. a successful set with one successful member and one member exiting 4
     whose report is missing (copy byte for byte, keep the dot in the request
     stem, print the missing-report diagnostic, emit the code-4 entry);
  2. a set exiting 3 with a successful member (copy the report; per-member
     entries stay empty -- the aggregate failure is the shell's fallback);
  3. a malformed envelope (exit 1 before copying any report).

Every envelope here is synthetic plumbing evidence only, never circuit data.
"""
import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stderr
from io import StringIO
from pathlib import Path

LNA = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location("lna_variant_campaign", LNA / "lna_variant_campaign.py")
V = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(V)

RUNNERS = ("run_lna_variant.sh", "run_lna_iip3.sh")


def write_member_report(root, body=b'{"corners": []}\n'):
    p = Path(root) / "member_report.json"
    p.write_bytes(body)
    return str(p)


def write_envelope(root, requests):
    p = Path(root) / "set-report.json"
    p.write_text(json.dumps({"requests": requests}))
    return str(p)


class CollectBatchSet(unittest.TestCase):
    def fixture_set(self, d, *, second_exit=4, second_report="missing"):
        """One successful member + one exiting `second_exit` whose report is
        `second_report` ('missing' = a path that does not exist,
        'absent' = no report field at all, 'ok' = a second good report)."""
        ok_report = write_member_report(d, b'{"corners": [{"x": 1}]}\n')
        missing = str(Path(d) / "nope.json")
        first = {"request": str(Path(d) / "ideal_noise.request.json"),
                 "report": ok_report, "exit_code": 0}
        second = {"request": str(Path(d) / "matched_iip3_a0.5mv.request.json"),
                  "exit_code": second_exit}
        if second_report == "missing":
            second["report"] = missing
        elif second_report == "ok":
            second["report"] = write_member_report(d, b'{"corners": []}\n')
        return [first, second], ok_report, missing

    def test_issue_fixture_1_member_exit_4_missing_report(self):
        for runner in RUNNERS:
            with self.subTest(runner=runner), tempfile.TemporaryDirectory() as d:
                corners = Path(d) / "corners"
                corners.mkdir()
                requests, ok_report, missing = self.fixture_set(d)
                envelope = write_envelope(d, requests)
                err = StringIO()
                with redirect_stderr(err):
                    entries = V.collect_batch_set(runner, envelope, str(corners))
                # the successful member's report is copied byte for byte, to
                # the request-stem path the reducer reads; the dot inside the
                # second stem survives (matched_iip3_a0.5mv, not a0_5mv)
                copied = corners / "ideal_noise.report.json"
                self.assertEqual(copied.read_bytes(), Path(ok_report).read_bytes())
                self.assertFalse((corners / "matched_iip3_a0.5mv.report.json").exists())
                # the missing-report diagnostic names the runner and the path
                self.assertIn(
                    f"{runner}: matched_iip3_a0.5mv: no report to collect (missing {missing})",
                    err.getvalue())
                # the failed member is recorded with its code, in envelope order
                self.assertEqual(entries, [("matched_iip3_a0.5mv", 4)])

    def test_issue_fixture_2_set_exit_3_with_successful_member(self):
        # The aggregate set exit is the SHELL's fallback (batch-set:<rc> when
        # no member failed); the collector itself reports no member failure.
        for runner in RUNNERS:
            with self.subTest(runner=runner), tempfile.TemporaryDirectory() as d:
                corners = Path(d) / "corners"
                corners.mkdir()
                requests, ok_report, _ = self.fixture_set(d, second_exit=0, second_report="ok")
                envelope = write_envelope(d, requests)
                err = StringIO()
                with redirect_stderr(err):
                    entries = V.collect_batch_set(runner, envelope, str(corners))
                self.assertEqual(entries, [])
                self.assertEqual(err.getvalue(), "")
                self.assertEqual((corners / "ideal_noise.report.json").read_bytes(),
                                 Path(ok_report).read_bytes())
                self.assertTrue((corners / "matched_iip3_a0.5mv.report.json").exists())

    def test_issue_fixture_3_malformed_envelope_exits_1_before_copying(self):
        for runner in RUNNERS:
            with self.subTest(runner=runner), tempfile.TemporaryDirectory() as d:
                corners = Path(d) / "corners"
                corners.mkdir()
                envelope = Path(d) / "set-report.json"
                envelope.write_text("{not json")
                err = StringIO()
                with redirect_stderr(err):
                    with self.assertRaises(SystemExit) as raised:
                        V.collect_batch_set(runner, str(envelope), str(corners))
                self.assertIn(f"{runner}: cannot read set envelope {envelope}:",
                              str(raised.exception.code))
                self.assertEqual(list(corners.iterdir()), [])

    def test_absent_report_field_and_unknown_stem(self):
        with tempfile.TemporaryDirectory() as d:
            corners = Path(d) / "corners"
            corners.mkdir()
            requests, _, _ = self.fixture_set(d, second_report="absent")
            requests.append({"request": "", "exit_code": 7})  # no stem to derive
            envelope = write_envelope(d, requests)
            err = StringIO()
            with redirect_stderr(err):
                entries = V.collect_batch_set("run_lna_iip3.sh", envelope, str(corners))
            self.assertIn("matched_iip3_a0.5mv: no report to collect "
                          "(member never produced one)", err.getvalue())
            # envelope order preserved; a stemless member fails as <unknown>
            self.assertEqual(entries, [("matched_iip3_a0.5mv", 4), ("<unknown>", 7)])
            self.assertEqual([p.name for p in sorted(corners.iterdir())],
                             ["ideal_noise.report.json"])

    def test_no_requests_key_is_not_an_error(self):
        with tempfile.TemporaryDirectory() as d:
            corners = Path(d) / "corners"
            corners.mkdir()
            envelope = Path(d) / "set-report.json"
            envelope.write_text(json.dumps({"status": "pass"}))
            self.assertEqual(V.collect_batch_set("run_lna_variant.sh",
                                                 str(envelope), str(corners)), [])


class CollectSetCLI(unittest.TestCase):
    """The runners' exact invocation: stdout is the failure list the shell
    consumes (`while read -r stem rc`), stderr the diagnostics, exit 1 only
    on an unreadable envelope -- consumed by nobody after a non-zero exit."""

    def invoke(self, d, runner):
        corners = Path(d) / "corners"
        corners.mkdir(exist_ok=True)
        failures = Path(d) / "set-failures.txt"
        p = subprocess.run(
            [sys.executable, "-I", str(LNA / "lna_variant_campaign.py"), "collect-set",
             "--runner", runner, "--envelope", str(Path(d) / "set-report.json"),
             "--corners-out", str(corners)],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        # the runner redirects stdout to the failures file, then consumes it
        failures.write_text(p.stdout)
        return p, failures, corners

    def test_stdout_is_the_failure_list(self):
        for runner in RUNNERS:
            with self.subTest(runner=runner), tempfile.TemporaryDirectory() as d:
                (Path(d) / "set-report.json").write_text(json.dumps({"requests": [
                    {"request": "ideal_noise.request.json", "report": write_member_report(d),
                     "exit_code": 0},
                    {"request": "le_q10_sp_stab.request.json", "exit_code": 3},
                ]}))
                p, failures, corners = self.invoke(d, runner)
                self.assertEqual(p.returncode, 0, p.stderr)
                self.assertEqual(p.stdout, "le_q10_sp_stab 3\n")
                # exactly what the runner's `while read -r stem rc` consumes
                consumed = [line.split() for line in failures.read_text().splitlines()]
                self.assertEqual(consumed, [["le_q10_sp_stab", "3"]])
                self.assertTrue((corners / "ideal_noise.report.json").exists())
                self.assertIn("le_q10_sp_stab: no report to collect "
                              "(member never produced one)", p.stderr)

    def test_stdout_stays_empty_for_a_clean_set(self):
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "set-report.json").write_text(json.dumps({"requests": [
                {"request": "matched_op.request.json",
                 "report": write_member_report(d), "exit_code": 0}]}))
            p, failures, _ = self.invoke(d, "run_lna_iip3.sh")
            self.assertEqual((p.returncode, p.stdout, p.stderr), (0, "", ""))
            self.assertEqual(failures.read_text(), "")

    def test_malformed_envelope_exits_1_with_stderr_diagnostic(self):
        for runner in RUNNERS:
            with self.subTest(runner=runner), tempfile.TemporaryDirectory() as d:
                (Path(d) / "set-report.json").write_text("not an envelope")
                p, failures, corners = self.invoke(d, runner)
                self.assertEqual(p.returncode, 1)
                self.assertIn(f"{runner}: cannot read set envelope", p.stderr)
                self.assertEqual(p.stdout, "")
                self.assertEqual(list(corners.iterdir()), [])


if __name__ == "__main__":
    unittest.main()
