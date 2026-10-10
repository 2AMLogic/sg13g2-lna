"""Unit tests for layout/pcell_env.py and generate.py's _snap (issue #173).

Pins PDK resolution order, the PyCell-library digest recorded as
``pcell_lib_sha256`` in layout provenance, and 5 nm grid snapping. Stdlib
only: no PDK and no KLayout. ``generate.py`` takes ``pya`` as a constructor
argument and imports only ``pcell_env`` at module load, so it imports
cleanly without KLayout and needs no ``pya`` shim.

Run from the repo root:
    python3 -I -m unittest discover -s layout/tests -v
"""

from __future__ import annotations

import importlib.util
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

LAYOUT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(LAYOUT))
import pcell_env  # noqa: E402

_spec = importlib.util.spec_from_file_location(
    "lna_core_generate_under_test", LAYOUT / "lna_core" / "generate.py"
)
generate = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(generate)

LIB_REL = Path("libs.tech") / "klayout" / "python" / "sg13g2_pycell_lib"


def make_pdk(root: Path, name: str = "ihp-sg13g2") -> Path:
    pdk = root / name
    (pdk / LIB_REL).mkdir(parents=True)
    return pdk


class ResolvePdkTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name).resolve()

    def resolve(self, env, prefixes=()):
        with mock.patch.dict(os.environ, env, clear=True), mock.patch.object(
            pcell_env, "_FALLBACK_PREFIXES", tuple(str(p) for p in prefixes)
        ):
            return pcell_env.resolve_pdk()

    def test_pdk_root_wins_over_fallback(self):
        a, b = self.tmp / "a", self.tmp / "b"
        want = make_pdk(a)
        make_pdk(b)
        self.assertEqual(self.resolve({"PDK_ROOT": str(a)}, [b]), want)

    def test_fallback_used_without_pdk_root(self):
        b = self.tmp / "b"
        want = make_pdk(b)
        self.assertEqual(self.resolve({}, [self.tmp / "none", b]), want)

    def test_fallback_when_pdk_root_lacks_install(self):
        a, b = self.tmp / "a", self.tmp / "b"
        a.mkdir()
        want = make_pdk(b)
        self.assertEqual(self.resolve({"PDK_ROOT": str(a)}, [b]), want)

    def test_fallback_order_first_match(self):
        b, c = self.tmp / "b", self.tmp / "c"
        want = make_pdk(b)
        make_pdk(c)
        self.assertEqual(self.resolve({}, [b, c]), want)

    def test_pdk_env_overrides_default_name(self):
        a = self.tmp / "a"
        make_pdk(a)
        want = make_pdk(a, "other-pdk")
        self.assertEqual(self.resolve({"PDK_ROOT": str(a), "PDK": "other-pdk"}), want)

    def test_default_name_is_ihp_sg13g2(self):
        a = self.tmp / "a"
        make_pdk(a, "other-pdk")
        with self.assertRaises(SystemExit):
            self.resolve({"PDK_ROOT": str(a)})

    def test_missing_pycell_lib_raises(self):
        a = self.tmp / "a"
        (a / "ihp-sg13g2" / "libs.tech").mkdir(parents=True)
        with self.assertRaises(SystemExit) as cm:
            self.resolve({"PDK_ROOT": str(a)}, [self.tmp / "nope"])
        self.assertIn("sg13g2_pycell_lib", str(cm.exception))

    def test_lib_as_file_is_not_an_install(self):
        a = self.tmp / "a"
        lib = a / "ihp-sg13g2" / LIB_REL
        lib.parent.mkdir(parents=True)
        lib.write_text("not a dir")
        with self.assertRaises(SystemExit):
            self.resolve({"PDK_ROOT": str(a)})

    def test_tilde_prefix_expanded(self):
        home = self.tmp / "home"
        want = make_pdk(home / "share" / "pdk")
        with mock.patch.dict(os.environ, {"HOME": str(home)}, clear=True), mock.patch.object(
            pcell_env, "_FALLBACK_PREFIXES", ("~/share/pdk",)
        ):
            self.assertEqual(pcell_env.resolve_pdk(), want)


class PcellLibDigestTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.pdk = make_pdk(Path(tmp.name))
        self.lib = self.pdk / LIB_REL
        (self.lib / "a.py").write_text("x = 1\n")
        (self.lib / "sub").mkdir()
        (self.lib / "sub" / "b.json").write_text("{}")

    def digest(self):
        return pcell_env.pcell_lib_digest(self.pdk)

    def test_format_and_determinism(self):
        d = self.digest()
        self.assertRegex(d, r"^sha256:[0-9a-f]{64}$")
        self.assertEqual(d, self.digest())

    def test_content_sensitive(self):
        before = self.digest()
        (self.lib / "a.py").write_text("x = 2\n")
        self.assertNotEqual(before, self.digest())

    def test_json_content_sensitive(self):
        before = self.digest()
        (self.lib / "sub" / "b.json").write_text('{"k": 1}')
        self.assertNotEqual(before, self.digest())

    def test_relative_path_sensitive(self):
        before = self.digest()
        (self.lib / "sub" / "b.json").rename(self.lib / "sub" / "c.json")
        renamed = self.digest()
        self.assertNotEqual(before, renamed)
        (self.lib / "sub" / "c.json").rename(self.lib / "b.json")
        self.assertNotEqual(renamed, self.digest())
        self.assertNotEqual(before, self.digest())

    def test_new_source_file_changes_digest(self):
        before = self.digest()
        (self.lib / "new.py").write_text("")
        self.assertNotEqual(before, self.digest())

    def test_pycache_ignored(self):
        before = self.digest()
        cache = self.lib / "__pycache__"
        cache.mkdir()
        (cache / "a.py").write_text("junk")
        (cache / "a.json").write_text("junk")
        (self.lib / "sub" / "__pycache__").mkdir()
        (self.lib / "sub" / "__pycache__" / "z.py").write_text("junk")
        self.assertEqual(before, self.digest())

    def test_other_suffixes_ignored(self):
        before = self.digest()
        (self.lib / "a.pyc").write_bytes(b"\0\1")
        (self.lib / "README.md").write_text("hi")
        (self.lib / "data.txt").write_text("hi")
        (self.lib / "noext").write_text("hi")
        self.assertEqual(before, self.digest())

    def test_directories_not_hashed(self):
        before = self.digest()
        (self.lib / "emptydir.py").mkdir()
        self.assertEqual(before, self.digest())

    def test_creation_order_irrelevant(self):
        other = make_pdk(Path(tempfile.mkdtemp()))
        self.addCleanup(__import__("shutil").rmtree, other.parent, True)
        lib2 = other / LIB_REL
        (lib2 / "sub").mkdir()
        (lib2 / "sub" / "b.json").write_text("{}")
        (lib2 / "a.py").write_text("x = 1\n")
        self.assertEqual(self.digest(), pcell_env.pcell_lib_digest(other))


class SnapTest(unittest.TestCase):
    def test_on_grid_values(self):
        self.assertEqual(generate._snap(0.0), 0)
        self.assertEqual(generate._snap(1.0), 1000)
        self.assertEqual(generate._snap(0.005), 5)
        self.assertEqual(generate._snap(1.85), 1850)

    def test_rounds_to_nearest_step(self):
        self.assertEqual(generate._snap(0.001), 0)
        self.assertEqual(generate._snap(0.002), 0)
        self.assertEqual(generate._snap(0.003), 5)
        self.assertEqual(generate._snap(0.0074), 5)
        self.assertEqual(generate._snap(0.0076), 10)

    def test_half_step_uses_bankers_rounding(self):
        # Exact half steps (binary-representable) go through round(): ties to
        # even step count, so 0.0025 um (0.5 step) -> 0 and 0.0075 (1.5) -> 10.
        self.assertEqual(generate._snap(0.0025), 0)
        self.assertEqual(generate._snap(0.0075), 10)
        self.assertEqual(generate._snap(0.0125), 10)

    def test_negative_values(self):
        self.assertEqual(generate._snap(-1.0), -1000)
        self.assertEqual(generate._snap(-0.003), -5)
        self.assertEqual(generate._snap(-0.0074), -5)
        self.assertEqual(generate._snap(-0.0076), -10)
        self.assertEqual(generate._snap(-0.0025), 0)

    def test_negative_symmetry(self):
        for v in (0.1234, 3.3333, 17.0049, 0.0075):
            self.assertEqual(generate._snap(-v), -generate._snap(v))

    def test_result_is_int_on_5nm_grid(self):
        for v in (0.0, 0.123, -4.567, 12.3456, -0.0031, 99.9999):
            r = generate._snap(v)
            self.assertIsInstance(r, int)
            self.assertEqual(r % 5, 0)


if __name__ == "__main__":
    unittest.main()
