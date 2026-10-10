"""Unit tests for layout/lvs_identity.py (issue #162).

Pins the sidecar binding (sha256 fields, request-relative path resolution),
the malformed-sidecar warning path, entry preservation across reports, the
argument-count check and atomic publication. Stdlib only: no klt or PDK.
Fixtures are tiny stand-in files in a temp repo root laid out as
<root>/layout/<cell>/ so that cell_dir.parent.parent is the repo root.

Run from the repo root:
    python3 -I -m unittest discover -s layout/tests -v
"""

from __future__ import annotations

import contextlib
import hashlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import lvs_identity  # noqa: E402


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class LvsIdentityTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name).resolve()
        self.cd = self.root / "layout" / "cell"
        self.cd.mkdir(parents=True)
        self.gds_bytes = b"GDS-standin"
        self.ref_bytes = b"* reference netlist\n"
        self.rep_bytes = b'{"verdict": "match"}\n'
        # Reference and GDS live in subdirectories under a differently named
        # layout, so nothing can be inferred from the request/report names.
        (self.cd / "geom").mkdir()
        (self.cd / "geom" / "odd_name.bin").write_bytes(self.gds_bytes)
        (self.root / "ref").mkdir()
        (self.root / "ref" / "golden.txt").write_bytes(self.ref_bytes)
        self.write_request("req.json")
        (self.cd / "rep.json").write_bytes(self.rep_bytes)

    def write_request(self, name):
        spec = {
            "reference": {"netlist": "../../ref/golden.txt"},
            "layout": {"file": "geom/odd_name.bin"},
        }
        data = json.dumps(spec).encode()
        (self.cd / name).write_bytes(data)
        return data

    def run_main(self, *args):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            rc = lvs_identity.main(["lvs_identity.py", *args])
        return rc, out.getvalue(), err.getvalue()

    def sidecar(self):
        return json.loads((self.cd / lvs_identity.NAME).read_text())

    def test_wrong_argument_count_returns_2(self):
        for args in ([], [str(self.cd)], [str(self.cd), "req.json"],
                     [str(self.cd), "req.json", "rep.json", "extra"]):
            with self.subTest(args=args):
                rc, _, err = self.run_main(*args)
                self.assertEqual(rc, 2)
                self.assertIn("lvs_identity.py", err)
        self.assertFalse((self.cd / lvs_identity.NAME).exists())

    def test_entry_hashes_and_relative_paths(self):
        req_bytes = (self.cd / "req.json").read_bytes()
        rc, out, err = self.run_main(str(self.cd), "req.json", "rep.json")
        self.assertEqual(rc, 0)
        self.assertEqual(err, "")
        self.assertIn("rep.json", out)
        doc = self.sidecar()
        self.assertEqual(doc["schema"], lvs_identity.SCHEMA)
        self.assertEqual(doc["reports"]["rep.json"], {
            "request": "req.json",
            "request_sha256": sha(req_bytes),
            "reference": "ref/golden.txt",
            "reference_sha256": sha(self.ref_bytes),
            "gds": "layout/cell/geom/odd_name.bin",
            "gds_sha256": sha(self.gds_bytes),
            "report_sha256": sha(self.rep_bytes),
        })

    def test_paths_resolve_relative_to_request_directory(self):
        # A request in a subdirectory resolves its paths against that
        # subdirectory, not the cell dir.
        sub = self.cd / "sub"
        sub.mkdir()
        (sub / "g.bin").write_bytes(b"other-gds")
        (sub / "r.txt").write_bytes(b"other-ref")
        spec = {"reference": {"netlist": "r.txt"}, "layout": {"file": "g.bin"}}
        (sub / "req2.json").write_text(json.dumps(spec))
        rc, _, _ = self.run_main(str(self.cd), "sub/req2.json", "rep.json")
        self.assertEqual(rc, 0)
        e = self.sidecar()["reports"]["rep.json"]
        self.assertEqual(e["reference"], "layout/cell/sub/r.txt")
        self.assertEqual(e["gds"], "layout/cell/sub/g.bin")
        self.assertEqual(e["reference_sha256"], sha(b"other-ref"))
        self.assertEqual(e["gds_sha256"], sha(b"other-gds"))

    def test_adding_report_keeps_other_entries(self):
        (self.cd / "rep2.json").write_bytes(b"second")
        self.assertEqual(self.run_main(str(self.cd), "req.json", "rep.json")[0], 0)
        first = self.sidecar()["reports"]["rep.json"]
        self.assertEqual(self.run_main(str(self.cd), "req.json", "rep2.json")[0], 0)
        reports = self.sidecar()["reports"]
        self.assertEqual(set(reports), {"rep.json", "rep2.json"})
        self.assertEqual(reports["rep.json"], first)
        self.assertEqual(reports["rep2.json"]["report_sha256"], sha(b"second"))

    def test_rerun_replaces_same_report_entry(self):
        self.run_main(str(self.cd), "req.json", "rep.json")
        (self.cd / "rep.json").write_bytes(b"changed")
        self.run_main(str(self.cd), "req.json", "rep.json")
        reports = self.sidecar()["reports"]
        self.assertEqual(list(reports), ["rep.json"])
        self.assertEqual(reports["rep.json"]["report_sha256"], sha(b"changed"))

    def test_malformed_sidecars_warn_and_start_fresh(self):
        bad = {
            "invalid json": "{not json",
            "non-dict": "[1, 2]",
            "wrong schema": json.dumps(
                {"schema": "other/1", "reports": {"stale.json": {}}}),
            "reports not a dict": json.dumps(
                {"schema": lvs_identity.SCHEMA, "reports": []}),
        }
        for label, text in bad.items():
            with self.subTest(label):
                (self.cd / lvs_identity.NAME).write_text(text)
                rc, _, err = self.run_main(str(self.cd), "req.json", "rep.json")
                self.assertEqual(rc, 0)
                self.assertIn("warning", err)
                self.assertIn("malformed", err)
                doc = self.sidecar()
                self.assertEqual(doc["schema"], lvs_identity.SCHEMA)
                self.assertEqual(list(doc["reports"]), ["rep.json"])

    def test_valid_sidecar_emits_no_warning(self):
        self.run_main(str(self.cd), "req.json", "rep.json")
        rc, _, err = self.run_main(str(self.cd), "req.json", "rep.json")
        self.assertEqual(rc, 0)
        self.assertEqual(err, "")

    def test_publication_leaves_no_tmp(self):
        self.run_main(str(self.cd), "req.json", "rep.json")
        self.assertFalse((self.cd / (lvs_identity.NAME + ".tmp")).exists())
        self.assertEqual(
            sorted(p.name for p in self.cd.glob("*.tmp")), [])
        # Also after replacing an existing sidecar.
        self.run_main(str(self.cd), "req.json", "rep.json")
        self.assertFalse((self.cd / (lvs_identity.NAME + ".tmp")).exists())

    def test_publication_uses_os_replace(self):
        calls = []
        real = lvs_identity.os.replace

        def spy(src, dst):
            calls.append((Path(src).name, Path(dst).name))
            # The tmp file must be complete before it is renamed in.
            json.loads(Path(src).read_text())
            return real(src, dst)

        lvs_identity.os.replace = spy
        try:
            self.run_main(str(self.cd), "req.json", "rep.json")
        finally:
            lvs_identity.os.replace = real
        self.assertEqual(calls, [(lvs_identity.NAME + ".tmp", lvs_identity.NAME)])


if __name__ == "__main__":
    unittest.main()
