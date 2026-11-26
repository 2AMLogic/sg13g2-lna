"""Exercise the variant and IIP3 shell runners with fixture requests and klt replies."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

LNA = Path(__file__).resolve().parents[1]
RUNNERS = {"run_lna_variant.sh": 7, "run_lna_iip3.sh": 2}
STEMS = ("a.1", "b")

REMOTE = json.dumps({"environment": {"remote": {"job_id": "job-a", "instance_type": "c6i",
                                                "runner_klt_version": "0.7", "state": "done"}},
                     "status": "pass", "corner_count": 1, "corners": [{}]})
LOCAL = '{"status": "pass", "corner_count": 2, "corners": [{}, {}]}'

# The same stub handles both klt invocation shapes. Log the full argument
# vector so an unintended retry, backend switch or split path is observable.
KLT = '''
import json, sys
from pathlib import Path
args = sys.argv[1:]
if args == ["--version"]:
    print("klt 0.7.0")
    sys.exit(0)
with open("calls.jsonl", "a") as log:
    print(json.dumps(args), file=log)
key = "set" if args[1] == "--batch-set" else Path(args[1]).name.removesuffix(".request.json")
rc, output = json.loads(Path("replies.json").read_text())[key]
print(output)
sys.exit(rc)
'''


class CampaignRunners(unittest.TestCase):
    def run_fixture(self, runner, backend, replies):
        tmp = tempfile.TemporaryDirectory(prefix="campaign runner ")
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        sim = root / "sim"
        bench = sim / LNA.name
        bench.mkdir(parents=True)
        for script in LNA.glob("*.sh"):
            (bench / script.name).symlink_to(script)
        (sim / "models").symlink_to(LNA.parent / "models")
        (root / "design").symlink_to(LNA.parents[1] / "design")
        # Give the wrappers isolated record paths and two pre-generated
        # requests. Run the real check-client, collect-set and record writer.
        (sim / "env.sh").write_text("""
REPO_ROOT=$PWD
# Invoke the stub through Python even when the fixture is on a noexec mount.
klt() { python3 -I "$REPO_ROOT/klt_stub.py" "$@"; }
sim_require_pdk() { SIM_SCRIPT_NAME=$1; }
sim_record_paths() {
  RECORD_ID=fixture
  RECORDS_DIR=$PWD
  SNAPSHOTS_OUT=$PWD/requests
  CORNERS_OUT=$PWD/corners
}
""")
        (bench / "lna_variant_campaign.py").write_text("""
import os, runpy, sys
from pathlib import Path
if sys.argv[1] in ("summarize", "summarize-iip3"):
    Path("reduced").touch()
elif sys.argv[1] not in ("gen", "gen-iip3"):
    runpy.run_path(os.environ["CAMPAIGN"], run_name="__main__")
""")
        (root / "requests").mkdir()
        (root / "corners").mkdir()
        for stem in STEMS:
            (root / "requests" / f"{stem}.request.json").write_text("{}")
        (root / "a.json").write_text(REMOTE)
        (root / "b.json").write_text(LOCAL)
        (root / "replies.json").write_text(json.dumps(replies))
        (root / "klt_stub.py").write_text(KLT)

        env = dict(PATH=os.environ["PATH"], CAMPAIGN=str(LNA / "lna_variant_campaign.py"),
                   PDK="fixture", PDK_ROOT=str(root), SIM_PDK_RELEASE="fixture", SIM_PDK_ID_ROUTE="fixture")
        # Exercise the inherited batch backend and explicit serial override.
        env["KLT_SIM_BACKEND"] = "batch"
        if backend == "local":
            env["LNA_VARIANT_BACKEND" if "variant" in runner else "LNA_IIP3_BACKEND"] = "local"
        result = subprocess.run(["bash", str(bench / runner)], cwd=root, env=env,
                                capture_output=True, text=True, timeout=30)
        log = root / "calls.jsonl"
        self.assertTrue(log.exists(), result.stdout + result.stderr)
        calls = [json.loads(line) for line in log.read_text().splitlines()]
        return root, result, calls

    def test_batch(self):
        members = [{"request": "a.1.request.json", "report": "a.json", "exit_code": 0},
                   {"request": "b.request.json", "report": "b.json", "exit_code": 0}]
        clean = json.dumps({"requests": members})
        member_failure = json.dumps({"requests": [members[0], dict(members[1], report="missing", exit_code=4)]})
        for runner, limit in RUNNERS.items():
            for rc, envelope, failed in [(0, clean, ""), (0, member_failure, "b:4"),
                                         (3, clean, "batch-set:3"), (3, "{", None)]:
                with self.subTest(runner=runner, failed=failed):
                    root, result, calls = self.run_fixture(runner, "batch", {"set": (rc, envelope)})
                    corners = root / "corners"
                    requests = [str(root / "requests" / f"{s}.request.json") for s in STEMS]
                    self.assertEqual(calls, [["sim", "--batch-set", *requests, "-o", str(corners / "set"),
                                              "--max-in-flight", str(limit), "--capacity-retries", "3",
                                              "--wait-for-capacity", "600", "--format", "json"]])
                    self.assertIn(f"{runner}: klt sim --batch-set 2 requests, max-in-flight {limit}, "
                                  "--wait-for-capacity 600\n", result.stdout)
                    if failed is None:
                        self.assertEqual(result.returncode, 1)
                        self.assertIn(f"{runner}: cannot read set envelope {corners}/set-report.json:", result.stderr)
                        self.assertFalse((root / "reduced").exists())
                        self.assertFalse((root / "fixture.md").exists())
                        continue
                    if failed == "b:4":
                        self.assertIn(f"{runner}: b: no report to collect (missing missing)\n", result.stderr)
                        self.assertIn(f"{runner}: b exited 4 (see {corners}/set.stderr.log, "
                                      f"{corners}/set-report.json)\n", result.stderr)
                        self.assertFalse((corners / "b.report.json").exists())
                    if failed == "batch-set:3":
                        self.assertIn(f"{runner}: --batch-set exited 3 with no per-request failure "
                                      f"(see {corners}/set.stderr.log)\n", result.stderr)
                    self.assertEqual((corners / "set-failures.txt").read_text(), "b 4\n" if failed == "b:4" else "")
                    self.assert_record(root, runner, result, failed)

    def test_serial(self):
        for runner in RUNNERS:
            for rc, first_report, stops in [(0, REMOTE, False), (3, REMOTE, False),
                                            (4, '{"corners":[]}', True), (4, "{", True)]:
                with self.subTest(runner=runner, rc=rc, first_report=first_report):
                    root, result, calls = self.run_fixture(runner, "local", {"a.1": (rc, first_report), "b": (0, LOCAL)})
                    corners = root / "corners"
                    expected = STEMS[:1] if stops else STEMS
                    self.assertEqual(calls, [["sim", str(root / "requests" / f"{s}.request.json"),
                                              "-o", str(corners / f"{s}.artifacts"), "--format", "json",
                                              "--backend", "local"] for s in expected])
                    for stem in expected:
                        self.assertIn(f"{runner}: klt sim {stem}\n", result.stdout)
                    if rc:
                        self.assertIn(f"{runner}: a.1 exited {rc} (see {corners}/a.1.stderr.log)\n", result.stderr)
                    if stops:
                        self.assertIn(f"{runner}: no usable report for a.1; stopping (no local fallback).\n",
                                      result.stderr)
                    record = self.assert_record(root, runner, result, f"a.1:{rc}" if rc else "")
                    if not stops:
                        # The byte sequence includes sorting, indentation, missing
                        # remote fields, backticks and the final newline.
                        self.assertIn(b"  Jobs (klt `environment.remote`):\n"
                                      b"  - `a.1`: job `job-a`, c6i, runner klt `0.7`, state `done`, status `pass`, 1 corners\n"
                                      b"  - `b`: job `None`, None, runner klt `None`, state `None`, status `pass`, 2 corners\n"
                                      b"- **Failed requests**:", record)
                    elif first_report == "{":
                        self.assertIn(b"  Jobs (klt `environment.remote`):\n\n- **Failed requests**:", record)

    def assert_record(self, root, runner, result, failed):
        self.assertEqual(result.returncode, int(bool(failed)), result.stderr)
        self.assertTrue((root / "reduced").exists())
        record = (root / "fixture.md").read_bytes()
        self.assertIn(f"- **Failed requests**: {failed or 'none.'}\n".encode(), record)
        if failed:
            self.assertIn(f"{runner}: failed: {failed}\n", result.stderr)
        return record
