"""Unit tests for sim/tools/reducer_common.py (issue #172).

Stdlib only, headless, no ngspice, no PDK. Loads the module by explicit path
exactly as the reducers do. Writes only into temp dirs.

Run from the repo root:

    python3 -I -m unittest discover -s sim/tools/tests
"""
import importlib.util
import os
import shutil
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent

_spec = importlib.util.spec_from_file_location(
    "reducer_common", HERE.parent / "reducer_common.py")
rc = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(rc)


class ParseKvLineTests(unittest.TestCase):
    def test_single_line_parsed_to_raw_tokens(self):
        text = "noise\nTAG a 1 b 2.5e-3\nother x y\n"
        self.assertEqual(rc.parse_kv_line(text, "TAG", "src"),
                         {"a": "1", "b": "2.5e-3"})

    def test_no_matching_line(self):
        with self.assertRaisesRegex(rc.ReductionError, "src: no TAG line"):
            rc.parse_kv_line("other a 1\n", "TAG", "src")

    def test_multiple_matching_lines(self):
        with self.assertRaisesRegex(rc.ReductionError, "2 TAG lines"):
            rc.parse_kv_line("TAG a 1\nTAG b 2\n", "TAG", "src")

    def test_odd_token_count(self):
        with self.assertRaisesRegex(rc.ReductionError, "odd token count"):
            rc.parse_kv_line("TAG a 1 b\n", "TAG", "src")

    def test_repeated_key(self):
        with self.assertRaisesRegex(rc.ReductionError, "repeated"):
            rc.parse_kv_line("TAG a 1 a 2\n", "TAG", "src")

    def test_tag_prefix_requires_trailing_space(self):
        # `TAGX ...` must not match tag `TAG`.
        with self.assertRaisesRegex(rc.ReductionError, "no TAG line"):
            rc.parse_kv_line("TAGX a 1\n", "TAG", "src")

    def test_prefixed_line_does_not_count_as_second_match(self):
        self.assertEqual(
            rc.parse_kv_line("TAGX a 1\nTAG b 2\n", "TAG", "src"),
            {"b": "2"})

    def test_tag_must_start_the_line(self):
        with self.assertRaisesRegex(rc.ReductionError, "no TAG line"):
            rc.parse_kv_line(" TAG a 1\nx TAG a 1\n", "TAG", "src")


class _TmpDirCase(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="reducer_common_test_"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)


class ReadTextTests(_TmpDirCase):
    def test_reads_file(self):
        p = self.tmp / "f.txt"
        p.write_text("hello\n", encoding="utf-8")
        self.assertEqual(rc.read_text(p), "hello\n")

    def test_unreadable_path_raises_reduction_error(self):
        missing = self.tmp / "absent.txt"
        with self.assertRaises(rc.ReductionError) as cm:
            rc.read_text(missing)
        self.assertIn("unreadable", str(cm.exception))
        self.assertIn(str(missing), str(cm.exception))

    def test_directory_raises_reduction_error(self):
        with self.assertRaises(rc.ReductionError):
            rc.read_text(self.tmp)


class WriteExclusiveTests(_TmpDirCase):
    def test_creates_file_with_text(self):
        p = self.tmp / "out.csv"
        rc.write_exclusive(p, "a,b\n1,2\n")
        self.assertEqual(p.read_bytes(), b"a,b\n1,2\n")

    def test_refuses_to_overwrite_existing_file(self):
        p = self.tmp / "out.csv"
        p.write_text("original", encoding="utf-8")
        with self.assertRaises(FileExistsError):
            rc.write_exclusive(p, "replacement")
        self.assertEqual(p.read_text(encoding="utf-8"), "original")

    def test_second_write_to_same_path_refused(self):
        p = self.tmp / "out.csv"
        rc.write_exclusive(p, "first")
        with self.assertRaises(FileExistsError):
            rc.write_exclusive(p, "second")
        self.assertEqual(p.read_text(encoding="utf-8"), "first")

    def test_no_newline_translation(self):
        p = self.tmp / "out.txt"
        rc.write_exclusive(p, "a\nb\n")
        self.assertNotIn(b"\r", p.read_bytes())


if __name__ == "__main__":
    unittest.main()
