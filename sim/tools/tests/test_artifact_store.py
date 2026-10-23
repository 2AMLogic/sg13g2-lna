"""Tests for sim/tools/artifact_store.py with a stub `klt` (no broker, no network)."""

import hashlib
import json
import os
import stat
import subprocess
import sys
import tempfile
import unittest

TOOL = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "artifact_store.py")

STUB = r'''#!/usr/bin/env python3
import hashlib, json, os, sys
mode = os.environ.get("STUB_MODE", "ok")
a = sys.argv[1:]
if a[:2] != ["artifact", "put"]:
    sys.exit(2)
if "--help" in a:
    if mode == "nopt":
        sys.stderr.write("invalid choice: 'artifact'\n"); sys.exit(2)
    print("usage: klt artifact put [--manifest PATH]"); sys.exit(0)
if mode == "unreachable":
    sys.stderr.write("broker_unreachable\n"); sys.exit(1)
manifest = a[a.index("--manifest") + 1]; name = a[a.index("--name") + 1]; path = a[-1]
data = open(path, "rb").read(); sha = hashlib.sha256(data).hexdigest()
try:
    m = json.load(open(manifest))
except OSError:
    m = {"schema_version": 1, "entries": []}
uri = "s3://bucket/" + sha if mode == "badscheme" else "artifact:evidence/o__r/" + sha
m["entries"].append({"sha256": sha, "size": len(data), "kind": "evidence",
                     "producer": {"tool": "klt", "version": "0", "loom.repo": "o/r", "commit": None},
                     "uri": uri, "name": name})
json.dump(m, open(manifest, "w"))
'''


class ArtifactStoreTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        t = self._tmp.name
        self.root = os.path.join(t, "repo")
        self.scratch = os.path.join(self.root, "sim", "artifact-scratch", "b-r1")
        os.makedirs(os.path.join(self.scratch, "sub"))
        for rel, data in (("a.log", b"alpha\n"), ("sub/b.dat", b"beta\n")):
            with open(os.path.join(self.scratch, rel), "wb") as fh:
                fh.write(data)
        self.bin = os.path.join(t, "bin")
        os.makedirs(self.bin)
        self.stub = os.path.join(self.bin, "klt")
        with open(self.stub, "w") as fh:
            fh.write(STUB)
        os.chmod(self.stub, os.stat(self.stub).st_mode | stat.S_IXUSR)

    def run_put(self, mode="ok", broker="http://broker.invalid", have_klt=True, run_id="r1"):
        env = {"PATH": (self.bin + os.pathsep if have_klt else "") + "/usr/bin:/bin", "STUB_MODE": mode}
        if broker is not None:
            env["KLT_ARTIFACT_BROKER"] = broker
        return subprocess.run([sys.executable, "-I", TOOL, "put", "--bench", "b", "--run-id", run_id,
                               "--scratch", self.scratch, "--repo-root", self.root],
                              env=env, capture_output=True, text=True)

    def assert_nothing_written(self):
        self.assertFalse(os.path.exists(os.path.join(self.root, "manifests")))

    def test_success_writes_manifest_and_summary(self):
        r = self.run_put()
        self.assertEqual(r.returncode, 0, r.stderr)
        d = os.path.join(self.root, "manifests", "artifacts")
        m = json.load(open(os.path.join(d, "b-r1.manifest.json")))
        names = sorted(e["name"] for e in m["entries"])
        self.assertEqual(names, ["b/r1/a.log", "b/r1/sub/b.dat"])
        for e in m["entries"]:
            self.assertTrue(e["uri"].startswith("artifact:"))
        md = open(os.path.join(d, "b-r1.summary.md")).read()
        self.assertIn(hashlib.sha256(b"alpha\n").hexdigest(), md)
        self.assertIn("| `b/r1/a.log` | 6 |", md)

    def test_broker_unset_fails_closed(self):
        r = self.run_put(broker=None)
        self.assertEqual(r.returncode, 3)
        self.assertIn("KLT_ARTIFACT_BROKER", r.stderr)
        self.assert_nothing_written()

    def test_klt_missing_fails_closed(self):
        r = self.run_put(have_klt=False)
        self.assertEqual(r.returncode, 3)
        self.assertIn("klt is not on PATH", r.stderr)
        self.assert_nothing_written()

    def test_klt_without_artifact_put_fails_closed(self):
        r = self.run_put(mode="nopt")
        self.assertEqual(r.returncode, 3)
        self.assertIn("no usable `artifact put`", r.stderr)
        self.assert_nothing_written()

    def test_unreachable_broker_fails_closed(self):
        r = self.run_put(mode="unreachable")
        self.assertEqual(r.returncode, 4)
        self.assertIn("klt artifact put failed", r.stderr)
        self.assert_nothing_written()

    def test_non_artifact_uri_rejected(self):
        r = self.run_put(mode="badscheme")
        self.assertEqual(r.returncode, 4)
        self.assert_nothing_written()

    def test_existing_manifest_is_never_overwritten(self):
        self.assertEqual(self.run_put().returncode, 0)
        p = os.path.join(self.root, "manifests", "artifacts", "b-r1.manifest.json")
        before = open(p).read()
        r = self.run_put()
        self.assertEqual(r.returncode, 4)
        self.assertEqual(open(p).read(), before)

    def test_empty_scratch_and_bad_ids_rejected(self):
        os.remove(os.path.join(self.scratch, "a.log"))
        os.remove(os.path.join(self.scratch, "sub", "b.dat"))
        self.assertEqual(self.run_put().returncode, 2)
        self.assertEqual(self.run_put(run_id="../x").returncode, 2)
        self.assert_nothing_written()


if __name__ == "__main__":
    unittest.main()
