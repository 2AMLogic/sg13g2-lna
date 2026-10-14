"""Unit tests for the native DRC runner and its provenance binding
(issue #185).

Pins the runner's contract end to end with stub executables — no klayout,
klt or PDK: preflight version classes (missing executable, unparseable
`-v` output, below-minimum version), completed-run publication (klt exits
0/3/4 -> clean/violations/coverage_unknown), deck-crash refusal, refusal to
publish a report that does not pin the committed GDS, segregation of a
previous pair on every failure path, atomic pair publication and the
binding/validator's mutation classes. Stdlib only.

The stub `klt` records its argv and PATH so the tests can also pin that the
runner passes --min-klayout-version through to klt and prepends the
preflighted executable's directory to PATH.

Run from the repo root:
    python3 -I -m unittest discover -s layout/tests -v
"""

from __future__ import annotations

import contextlib
import hashlib
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

LAYOUT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(LAYOUT))
import native_drc_identity  # noqa: E402
import run_native_drc  # noqa: E402

RUNNER = LAYOUT / "run_native_drc.py"
IDENTITY = LAYOUT / "native_drc_identity.py"


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


STUB_KLAYOUT = """#!/bin/sh
# test stub: emulates the standalone klayout application's `-v` probe
printf '%s\\n' "$STUB_KLAYOUT_V"
exit 0
"""

STUB_KLT = """#!/usr/bin/env python3
'''test stub: emulates `klt version` and `klt drc --engine klayout`.'''
import hashlib, json, os, sys
argv = sys.argv[1:]
rec = os.environ.get("STUB_RECORD")
if rec:
    with open(rec, "w") as f:
        json.dump({"argv": argv, "path": os.environ.get("PATH", "")}, f)
if argv[:1] == ["version"]:
    print(json.dumps({"schema_version": 1, "version": "0.7.0", "stub": True}))
    raise SystemExit(0)
if argv[:1] != ["drc"]:
    print(f"stub: unexpected invocation: {argv}", file=sys.stderr)
    raise SystemExit(99)
gds = next((a for a in argv if a.endswith(".gds")), "")
try:
    data = open(gds, "rb").read()
except OSError:
    data = b""
status = os.environ.get("STUB_STATUS", "violations")
wrong = os.environ.get("STUB_WRONG_INPUT") == "1"
rep = {
    "schema_version": 2, "file": os.path.basename(gds), "deck": "stub-native",
    "dbu_um": 0.001, "status": status,
    "violation_count": 1 if status == "violations" else 0,
    "rule_counts": {}, "metrics": {}, "violations": [],
    "coverage": {"schema_version": 1},
    "provenance": {
        "klt_version": "0.7.0", "klayout_version": "0.30.30",
        "pdk": {"name": os.environ.get("STUB_PDK", "stub-pdk")},
        "deck": {"name": "stub-native",
                 "content_hash": "sha256:" + "s" * 64},
        "input": {"role": "layout",
                  "content_hash": "sha256:"
                  + ("0" * 64 if wrong else hashlib.sha256(data).hexdigest())},
    },
}
sys.stdout.write(json.dumps(rep, indent=2) + "\\n")
raise SystemExit(int(os.environ.get("STUB_RC", "3")))
"""


class VersionHelpersTest(unittest.TestCase):
    def test_identity_and_runner_copies_agree(self):
        samples = ["KLayout 0.28.16 (2023-12-30) abc", "0.29", "0.30.30",
                   "no digits here", "", None, "v1.2.3.4-rc1"]
        for s in samples:
            with self.subTest(sample=s):
                self.assertEqual(native_drc_identity.version_tuple(s),
                                 run_native_drc.version_tuple(s))

    def test_tuple(self):
        self.assertEqual(native_drc_identity.version_tuple(
            "KLayout 0.28.16 (2023-12-30) abc"), (0, 28, 16))
        self.assertEqual(native_drc_identity.version_tuple("0.29"), (0, 29))
        self.assertIsNone(native_drc_identity.version_tuple("no digits"))
        self.assertIsNone(native_drc_identity.version_tuple(None))

    def test_at_least_pads(self):
        at = native_drc_identity.version_at_least
        self.assertTrue(at("0.29", "0.29.0"))
        self.assertTrue(at("0.29", "0.29"))
        self.assertTrue(at("KLayout 0.30.30 (x)", "0.29"))
        self.assertFalse(at("KLayout 0.28.16 (x)", "0.29.0"))
        self.assertFalse(at("garbage", "0.29"))
        self.assertFalse(at("0.30", "garbage"))


class IdentityFixtureTest(unittest.TestCase):
    """Shared fixture: a repo-shaped temp root with a committed GDS and a
    published native report, plus the facts a runner invocation records."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name).resolve()
        self.cd = self.root / "layout" / "lna_core"
        self.cd.mkdir(parents=True)
        self.gds = self.cd / "lna_core.gds"
        self.gds_bytes = b"GDS-standin-\x01"
        self.gds.write_bytes(self.gds_bytes)
        self.exe_version = "KLayout 0.30.30 (2026-01-01) deadbee"
        self.klt_json = json.dumps(
            {"schema_version": 1, "version": "0.7.0", "stub": True})
        self.argv = ["klt", "drc", "--engine", "klayout", "lna_core.gds"]

    def write_report(self, status="violations", input_hash=None,
                     deck=None, pdk=None, raw=None):
        if raw is None:
            body = {
                "schema_version": 2, "file": "lna_core.gds",
                "deck": "stub-native", "dbu_um": 0.001, "status": status,
                "violation_count": 1 if status == "violations" else 0,
                "rule_counts": {}, "metrics": {}, "violations": [],
                "coverage": {"schema_version": 1},
                "provenance": {
                    "klt_version": "0.7.0", "klayout_version": "0.30.30",
                    "pdk": pdk if pdk is not None else {"name": "stub-pdk"},
                    "deck": deck if deck is not None else
                    {"name": "stub-native", "content_hash": "sha256:" + "s" * 64},
                    "input": {"role": "layout",
                              "content_hash": input_hash
                              or "sha256:" + sha(self.gds_bytes)},
                },
            }
            raw = json.dumps(body, indent=2) + "\n"
        (self.cd / "native_drc_report.json").write_text(raw)
        return raw

    def record(self, **over):
        kwargs = dict(
            cell_dir=self.cd, report_name="native_drc_report.json",
            gds=self.gds, klayout_exe="klayout",
            klayout_exe_resolved="/usr/bin/klayout",
            klayout_exe_version=self.exe_version,
            min_klayout_version="0.29.0", pdk="stub-pdk",
            klt_version_json=self.klt_json, argv=json.dumps(self.argv))
        kwargs.update(over)
        return native_drc_identity.record(**kwargs)

    def seed_pair(self, status="violations"):
        self.write_report(status=status)
        return self.record()

    def sidecar(self):
        return json.loads(
            (self.cd / native_drc_identity.NAME).read_text())

    def validate(self):
        return native_drc_identity.validate(self.cd, self.gds)


class IdentityRecordTest(IdentityFixtureTest):
    def test_binds_report_bytes_to_inputs(self):
        self.write_report()
        doc = self.record()
        self.assertEqual(doc["status"], "violations")
        self.assertEqual(doc["gds"], "layout/lna_core/lna_core.gds")
        self.assertEqual(doc["gds_sha256"], sha(self.gds_bytes))
        self.assertEqual(doc["report_sha256"],
                         sha((self.cd / "native_drc_report.json").read_bytes()))
        self.assertEqual(doc["deck_binding"]["name"], "stub-native")
        self.assertEqual(doc["pdk_binding"], {"name": "stub-pdk"})
        self.assertEqual(doc["klayout_exe_version"], self.exe_version)
        self.assertEqual(doc["min_klayout_version"], "0.29.0")
        self.assertEqual(doc["klt"]["version"], "0.7.0")
        self.assertEqual(doc["argv"], self.argv)
        self.assertFalse((self.cd / "native_drc_inputs.json.tmp").exists())

    def test_refuses_report_pinning_other_bytes(self):
        self.write_report(input_hash="sha256:" + "0" * 64)
        with self.assertRaises(ValueError) as cm:
            self.record()
        self.assertIn("not this GDS", str(cm.exception))
        self.assertFalse((self.cd / native_drc_identity.NAME).exists())

    def test_refuses_unknown_status(self):
        self.write_report(status="bananas")
        with self.assertRaises(ValueError):
            self.record()
        self.assertFalse((self.cd / native_drc_identity.NAME).exists())

    def test_refuses_unparseable_report(self):
        (self.cd / "native_drc_report.json").write_text("{not json")
        with self.assertRaises(ValueError):
            self.record()

    def test_refuses_report_without_deck_or_pdk(self):
        for key in ("pdk", "deck"):
            with self.subTest(key=key):
                (self.cd / "native_drc_report.json").unlink(missing_ok=True)
                self.write_report()
                rep_path = self.cd / "native_drc_report.json"
                rep = json.loads(rep_path.read_text())
                del rep["provenance"][key]
                rep_path.write_text(json.dumps(rep))
                with self.assertRaises(ValueError) as cm:
                    self.record()
                self.assertIn(f"no {key} object", str(cm.exception))
                self.assertFalse((self.cd / native_drc_identity.NAME).exists())

    def test_refuses_bad_klt_json_and_argv_and_min_version(self):
        self.write_report()
        for field, value, fragment in (
                ("klt_version_json", "{bad", "not"),
                ("klt_version_json", '{"nope": 1}', "version"),
                ("argv", "[]", "argv"),
                ("argv", '"klt"', "argv"),
                ("min_klayout_version", "banana", "dotted version")):
            with self.subTest(field=field):
                (self.cd / native_drc_identity.NAME).unlink(missing_ok=True)
                with self.assertRaises(ValueError) as cm:
                    self.record(**{field: value})
                self.assertIn(fragment, str(cm.exception))
                self.assertFalse(
                    (self.cd / native_drc_identity.NAME).exists())

    def test_refuses_exe_below_recorded_minimum(self):
        self.write_report()
        with self.assertRaises(ValueError) as cm:
            self.record(klayout_exe_version="KLayout 0.28.16 (old)")
        self.assertIn("below the required minimum", str(cm.exception))
        self.assertFalse((self.cd / native_drc_identity.NAME).exists())


class IdentityValidateTest(IdentityFixtureTest):
    def test_absent_pair_is_valid(self):
        self.assertEqual(self.validate(), [])

    def test_consistent_pair_is_valid(self):
        self.seed_pair()
        self.assertEqual(self.validate(), [])

    def test_one_sided_pairs_are_named(self):
        self.write_report()
        problems = self.validate()
        self.assertEqual(len(problems), 1)
        self.assertIn("native_drc_inputs.json missing", problems[0])
        (self.cd / "native_drc_report.json").unlink()
        (self.cd / native_drc_identity.NAME).write_text(
            json.dumps({"schema": native_drc_identity.SCHEMA}))
        problems = self.validate()
        self.assertEqual(len(problems), 1)
        self.assertIn("native_drc_report.json missing", problems[0])

    def test_mutated_report_bytes(self):
        self.seed_pair()
        with open(self.cd / "native_drc_report.json", "a") as f:
            f.write(" ")
        problems = self.validate()
        self.assertEqual(len(problems), 1)
        self.assertIn("report changed since this native run", problems[0])

    def test_mutated_gds_bytes(self):
        self.seed_pair()
        self.gds.write_bytes(self.gds_bytes + b"\x02")
        problems = self.validate()
        self.assertTrue(any("GDS changed since this native run" in p
                            for p in problems), problems)

    def test_mutated_gds_path(self):
        self.seed_pair()
        side = self.sidecar()
        side["gds"] = "layout/lna_core/other.gds"
        (self.cd / native_drc_identity.NAME).write_text(json.dumps(side))
        problems = self.validate()
        self.assertIn("gds path", problems[0])

    def test_mutated_deck_and_pdk_bindings(self):
        for key, mutated in (("deck_binding", {"name": "other"}),
                             ("pdk_binding", {"name": "other-pdk"})):
            with self.subTest(key=key):
                self.seed_pair()
                side = self.sidecar()
                side[key] = mutated
                (self.cd / native_drc_identity.NAME).write_text(
                    json.dumps(side))
                problems = self.validate()
                self.assertEqual(len(problems), 1)
                self.assertIn(f"{key} differs", problems[0])

    def test_status_mismatch(self):
        self.seed_pair(status="violations")
        side = self.sidecar()
        side["status"] = "clean"
        (self.cd / native_drc_identity.NAME).write_text(json.dumps(side))
        problems = self.validate()
        self.assertEqual(len(problems), 1)
        self.assertIn("status 'clean' != report status 'violations'",
                      problems[0])

    def test_exe_below_recorded_minimum(self):
        self.seed_pair()
        side = self.sidecar()
        side["klayout_exe_version"] = "KLayout 0.28.16 (old)"
        (self.cd / native_drc_identity.NAME).write_text(json.dumps(side))
        problems = self.validate()
        self.assertEqual(len(problems), 1)
        self.assertIn("below min_klayout_version", problems[0])

    def test_report_status_changed_to_unknown_value(self):
        self.seed_pair()
        rep_path = self.cd / "native_drc_report.json"
        rep = json.loads(rep_path.read_text())
        rep["status"] = "bananas"
        rep_path.write_text(json.dumps(rep))
        problems = self.validate()
        self.assertTrue(any("not one of" in p for p in problems), problems)

    def test_report_input_repinned(self):
        self.seed_pair()
        rep_path = self.cd / "native_drc_report.json"
        rep = json.loads(rep_path.read_text())
        rep["provenance"]["input"]["content_hash"] = "sha256:" + "f" * 64
        rep_path.write_text(json.dumps(rep))
        problems = self.validate()
        self.assertTrue(any("not this GDS" in p for p in problems))

    def test_malformed_and_missing_fields(self):
        self.seed_pair()
        (self.cd / native_drc_identity.NAME).write_text('{"schema": "x"}')
        self.assertIn("malformed (bad schema)", self.validate()[0])
        self.seed_pair()
        side = self.sidecar()
        del side["klt"]
        (self.cd / native_drc_identity.NAME).write_text(json.dumps(side))
        self.assertIn("klt identity missing", self.validate()[0])
        self.seed_pair()
        side = self.sidecar()
        del side["argv"]
        (self.cd / native_drc_identity.NAME).write_text(json.dumps(side))
        self.assertIn("argv missing or malformed", self.validate()[0])
        self.seed_pair()
        side = self.sidecar()
        del side["deck_binding"]
        (self.cd / native_drc_identity.NAME).write_text(json.dumps(side))
        self.assertIn("missing deck_binding", self.validate()[0])
        self.seed_pair()
        side = self.sidecar()
        del side["gds_sha256"]
        (self.cd / native_drc_identity.NAME).write_text(json.dumps(side))
        problems = self.validate()
        self.assertTrue(any("missing or malformed field" in p
                            for p in problems))
        self.seed_pair()
        side = self.sidecar()
        side["report"] = "other_report.json"
        (self.cd / native_drc_identity.NAME).write_text(json.dumps(side))
        self.assertIn("report is 'other_report.json'", self.validate()[0])


class IdentityCliTest(IdentityFixtureTest):
    def run_cli(self, *args):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            try:
                rc = native_drc_identity.main(
                    ["native_drc_identity.py", *args])
            except SystemExit as e:
                rc = e.code
        return rc, out.getvalue(), err.getvalue()

    def test_record_cli(self):
        self.write_report()
        rc, out, _ = self.run_cli(
            "record", str(self.cd), "native_drc_report.json",
            "--gds", str(self.gds), "--klayout-exe", "klayout",
            "--klayout-exe-resolved", "/usr/bin/klayout",
            "--klayout-exe-version", self.exe_version,
            "--min-klayout-version", "0.29.0", "--pdk", "stub-pdk",
            "--klt-version-json", self.klt_json,
            "--argv", json.dumps(self.argv))
        self.assertEqual(rc, 0)
        self.assertIn("recorded", out)
        self.assertTrue((self.cd / native_drc_identity.NAME).is_file())

    def test_record_cli_refusal_exits_1_without_sidecar(self):
        self.write_report(input_hash="sha256:" + "0" * 64)
        rc, _, err = self.run_cli(
            "record", str(self.cd), "native_drc_report.json",
            "--gds", str(self.gds), "--klayout-exe", "klayout",
            "--klayout-exe-resolved", "/usr/bin/klayout",
            "--klayout-exe-version", self.exe_version,
            "--min-klayout-version", "0.29.0", "--pdk", "stub-pdk",
            "--klt-version-json", self.klt_json,
            "--argv", json.dumps(self.argv))
        self.assertEqual(rc, 1)
        self.assertIn("not this GDS", err)
        self.assertFalse((self.cd / native_drc_identity.NAME).exists())

    def test_validate_cli(self):
        rc, _, err = self.run_cli("validate", str(self.cd),
                                  "--gds", str(self.gds))
        self.assertEqual((rc, err), (0, ""))
        self.seed_pair()
        rc, out, _ = self.run_cli("validate", str(self.cd),
                                  "--gds", str(self.gds))
        self.assertEqual(rc, 0)
        with open(self.cd / "native_drc_report.json", "a") as f:
            f.write(" ")
        rc, _, err = self.run_cli("validate", str(self.cd),
                                  "--gds", str(self.gds))
        self.assertEqual(rc, 1)
        self.assertIn("report changed", err)

    def test_missing_arguments_exit_2(self):
        for args in ([], ["record"], ["validate"], ["bogus"]):
            with self.subTest(args=args):
                rc, _, err = self.run_cli(*args)
                self.assertEqual(rc, 2)


class RunnerTest(IdentityFixtureTest):
    def setUp(self):
        super().setUp()
        self.stub_klayout = self.root / "stub-klayout" / "klayout"
        self.stub_klayout.parent.mkdir()
        self.stub_klayout.write_text(STUB_KLAYOUT)
        os.chmod(self.stub_klayout, 0o755)
        self.stub_klt = self.root / "stub-klt" / "klt"
        self.stub_klt.parent.mkdir()
        self.stub_klt.write_text(STUB_KLT)
        os.chmod(self.stub_klt, 0o755)
        self.stub_record = self.root / "stub-record.json"

    def run_runner(self, *extra, env_extra=None, min_version="0.29.0",
                   klayout_exe=True):
        env = dict(os.environ)
        env["KLT"] = f"{sys.executable} {self.stub_klt}"
        env["STUB_KLAYOUT_V"] = "KLayout 0.30.30 (2026-01-01) deadbee"
        env["STUB_RECORD"] = str(self.stub_record)
        env["STUB_PDK"] = "stub-pdk"
        for k in ("KLAYOUT_EXE", "PDK_ROOT"):
            env.pop(k, None)
        for k, v in (env_extra or {}).items():
            if v is None:
                env.pop(k, None)
            else:
                env[k] = v
        cmd = [sys.executable, "-I", str(RUNNER), "--cell-dir", str(self.cd),
               "--pdk", "stub-pdk"]
        if klayout_exe:
            cmd += ["--klayout-exe", str(self.stub_klayout)]
        if min_version is not None:
            cmd += ["--min-klayout-version", min_version]
        return subprocess.run(cmd + list(extra), capture_output=True,
                              text=True, env=env, cwd=self.root)

    def pair_exists(self):
        return ((self.cd / "native_drc_report.json").is_file(),
                (self.cd / native_drc_identity.NAME).is_file())

    def report(self):
        return json.loads(
            (self.cd / "native_drc_report.json").read_text())

    def test_publishes_violating_run_with_binding(self):
        r = self.run_runner()
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.pair_exists(), (True, True))
        rep = self.report()
        self.assertEqual(rep["status"], "violations")
        self.assertEqual(rep["violation_count"], 1)
        side = self.sidecar()
        self.assertEqual(side["status"], "violations")
        self.assertEqual(side["gds_sha256"], sha(self.gds_bytes))
        self.assertEqual(side["report_sha256"],
                         sha((self.cd / "native_drc_report.json").read_bytes()))
        self.assertIn("0.30.30", side["klayout_exe_version"])
        self.assertEqual(side["min_klayout_version"], "0.29.0")
        self.assertEqual(side["klt"]["version"], "0.7.0")
        self.assertEqual(side["klayout_exe_resolved"], str(self.stub_klayout))
        self.assertIn("--engine", side["argv"])
        self.assertIn("klayout", side["argv"])
        self.assertEqual(native_drc_identity.validate(self.cd, self.gds), [])
        rec = json.loads(self.stub_record.read_text())
        self.assertIn("--min-klayout-version", rec["argv"])
        self.assertEqual(rec["path"].split(os.pathsep)[0],
                         str(self.stub_klayout.parent))
        self.assertFalse((self.cd / "native_drc_report.json.tmp").exists())

    def test_publishes_clean_and_coverage_unknown_runs(self):
        for rc, status in (("0", "clean"), ("4", "coverage_unknown")):
            with self.subTest(rc=rc, status=status):
                for p in ("native_drc_report.json", native_drc_identity.NAME):
                    (self.cd / p).unlink(missing_ok=True)
                r = self.run_runner(env_extra={"STUB_RC": rc,
                                               "STUB_STATUS": status})
                self.assertEqual(r.returncode, 0, r.stderr)
                self.assertEqual(self.report()["status"], status)
                self.assertEqual(
                    self.sidecar()["status"], status)

    def test_klayout_exe_env_fallback(self):
        r = self.run_runner(klayout_exe=False,
                            env_extra={"KLAYOUT_EXE": str(self.stub_klayout)})
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.pair_exists(), (True, True))

    def test_usage_errors(self):
        r = self.run_runner(min_version=None)
        self.assertEqual(r.returncode, 2)
        r = self.run_runner(min_version="banana")
        self.assertEqual(r.returncode, 2)
        self.assertIn("not a dotted version", r.stderr)
        self.gds.unlink()
        r = self.run_runner()
        self.assertEqual(r.returncode, 2)
        self.assertIn("never regenerates", r.stderr)
        self.gds.write_bytes(self.gds_bytes)
        r = self.run_runner("--expect-rule-categories", "3",
                            "--expect-rule-categories-file", "f")
        self.assertEqual(r.returncode, 2)
        self.assertIn("mutually exclusive", r.stderr)
        self.assertEqual(self.pair_exists(), (False, False))

    def test_missing_executable_is_class_3(self):
        r = self.run_runner(
            klayout_exe=False,
            env_extra={"KLAYOUT_EXE": str(self.root / "nope" / "klayout")})
        self.assertEqual(r.returncode, 3)
        self.assertIn("not found", r.stderr)
        self.assertEqual(self.pair_exists(), (False, False))

    def test_missing_executable_on_path_is_class_3(self):
        empty_path = self.root / "empty-path-dir"
        empty_path.mkdir()
        r = self.run_runner(klayout_exe=False,
                            env_extra={"PATH": str(empty_path)})
        self.assertEqual(r.returncode, 3)
        self.assertIn("not found", r.stderr)
        self.assertEqual(self.pair_exists(), (False, False))

    def test_unparseable_version_output_is_class_4(self):
        r = self.run_runner(env_extra={"STUB_KLAYOUT_V": "klayout: confused"})
        self.assertEqual(r.returncode, 4)
        self.assertIn("cannot parse a version", r.stderr)
        self.assertIn("confused", r.stderr)
        self.assertEqual(self.pair_exists(), (False, False))

    def test_silent_version_probe_is_class_4(self):
        r = self.run_runner(env_extra={"STUB_KLAYOUT_V": ""})
        self.assertEqual(r.returncode, 4)
        self.assertIn("produced no output", r.stderr)

    def test_below_minimum_version_is_class_5(self):
        r = self.run_runner(
            env_extra={"STUB_KLAYOUT_V": "KLayout 0.28.16 (2023-12-30) old"})
        self.assertEqual(r.returncode, 5)
        self.assertIn("0.28.16", r.stderr)
        self.assertIn("0.29.0", r.stderr)
        self.assertIn("refusing", r.stderr)
        self.assertEqual(self.pair_exists(), (False, False))

    def test_deck_crash_is_class_6_and_keeps_staging(self):
        r = self.run_runner(env_extra={"STUB_RC": "7"})
        self.assertEqual(r.returncode, 6)
        self.assertIn("failed (exit 7)", r.stderr)
        self.assertEqual(self.pair_exists(), (False, False))
        self.assertTrue((self.cd / "native_drc_report.json.tmp").is_file())

    def test_report_not_pinning_gds_is_class_6(self):
        r = self.run_runner(env_extra={"STUB_WRONG_INPUT": "1"})
        self.assertEqual(r.returncode, 6)
        self.assertIn("does not pin this GDS", r.stderr)
        self.assertEqual(self.pair_exists(), (False, False))
        self.assertTrue((self.cd / "native_drc_report.json.tmp").is_file())

    def seg(self):
        stale = self.cd / "native_drc_stale"
        return sorted(p.name for d in stale.iterdir() for p in d.iterdir()) \
            if stale.is_dir() else []

    def test_failed_rerun_segregates_previous_pair(self):
        for env in ({"STUB_RC": "7"}, {"STUB_KLAYOUT_V": "KLayout 0.28.16 x"},
                    {}):
            tag = env.get("STUB_RC", env.get("STUB_KLAYOUT_V", "no-exe"))
            with self.subTest(failure=tag):
                self.seed_pair()
                old_report = (self.cd / "native_drc_report.json").read_bytes()
                old_side = (self.cd / native_drc_identity.NAME).read_bytes()
                if env.get("STUB_RC") is None and \
                        env.get("STUB_KLAYOUT_V") is None:
                    r = self.run_runner(
                        klayout_exe=False,
                        env_extra={"KLAYOUT_EXE": str(
                            self.root / "nope" / "klayout")})
                else:
                    r = self.run_runner(env_extra=env)
                self.assertNotEqual(r.returncode, 0)
                self.assertEqual(self.pair_exists(), (False, False))
                self.assertEqual(self.seg(),
                                 ["native_drc_inputs.json",
                                  "native_drc_report.json"])
                kept = sorted((self.cd / "native_drc_stale").rglob("*"))
                bytes_kept = {p.read_bytes() for p in kept if p.is_file()}
                self.assertEqual(bytes_kept, {old_report, old_side})
                shutil.rmtree(self.cd / "native_drc_stale")

    def test_successful_rerun_replaces_pair_without_stale_copies(self):
        self.seed_pair(status="coverage_unknown")
        old_side = self.sidecar()
        old_report = (self.cd / "native_drc_report.json").read_bytes()
        r = self.run_runner()
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.pair_exists(), (True, True))
        self.assertEqual(self.sidecar()["report_sha256"],
                         sha((self.cd / "native_drc_report.json").read_bytes()))
        self.assertNotEqual(self.sidecar()["report_sha256"],
                            old_side["report_sha256"])
        self.assertNotEqual((self.cd / "native_drc_report.json").read_bytes(),
                            old_report)
        self.assertEqual(self.sidecar()["status"], "violations")
        self.assertFalse((self.cd / "native_drc_stale").exists())

    def test_stale_staging_is_cleaned_before_a_new_run(self):
        (self.cd / "native_drc_report.json.tmp").write_text("stale")
        r = self.run_runner()
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertFalse((self.cd / "native_drc_report.json.tmp").exists())


if __name__ == "__main__":
    unittest.main()
