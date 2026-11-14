"""Unit tests for sim/tools/reducer_common.py (issues #172, #280).

Stdlib only, headless, no ngspice, no PDK. Loads the module by explicit path
exactly as the reducers do. Writes only into temp dirs.

Run from the repo root:

    python3 -I -m unittest discover -s sim/tools/tests
"""
import importlib.util
import os
import re
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


class StartupIdTests(unittest.TestCase):
    def test_id_format(self):
        self.assertEqual(rc.startup_id(("bcs", "125", "1.98")),
                         "startup_bcs_125c_vdd1.98v")
        self.assertEqual(rc.startup_id(("typ", "27", "1.80")),
                         "startup_typ_27c_vdd1.80v")


class StartupVerdictTests(unittest.TestCase):
    """The graded startup verdict rule (issue #280): all four verdicts and
    both threshold boundaries. Boundary values are integers/halves so the
    float math is exact."""

    def test_pass(self):
        spread, dvsop, verdict = rc.startup_verdict(4e-3, 4e-3, 4e-3, 4e-3)
        self.assertEqual((spread, dvsop, verdict), (0.0, 0.0, "PASS"))

    def test_spread_boundary_exactly_at_limit_passes(self):
        # mx-mn = 2, mean = 100 -> spread = 2.0 == SPREAD_LIMIT_PCT (> is strict)
        spread, dvsop, verdict = rc.startup_verdict(99.0, 101.0, 100.0, 100.0)
        self.assertEqual(spread, 2.0)
        self.assertEqual(verdict, "PASS")

    def test_spread_just_over_limit_fails(self):
        # mx-mn = 2.5, mean = 100 -> spread = 2.5
        _, _, verdict = rc.startup_verdict(99.0, 101.5, 99.5, 100.0)
        self.assertEqual(verdict, "NO-RINGING-FAIL")

    def test_op_mismatch_positive_boundary_passes(self):
        # dvsop = 100*(210-200)/200 = 5.0 == OP_MISMATCH_LIMIT_PCT
        _, dvsop, verdict = rc.startup_verdict(210.0, 210.0, 210.0, 200.0)
        self.assertEqual(dvsop, 5.0)
        self.assertEqual(verdict, "PASS")

    def test_op_mismatch_negative_boundary_passes(self):
        # dvsop = 100*(190-200)/200 = -5.0
        _, dvsop, verdict = rc.startup_verdict(190.0, 190.0, 190.0, 200.0)
        self.assertEqual(dvsop, -5.0)
        self.assertEqual(verdict, "PASS")

    def test_op_mismatch_just_over_positive_limit_fails(self):
        # dvsop = 5.5, spread ~ 0.48 (within limit) -> pure mismatch failure
        _, _, verdict = rc.startup_verdict(211.0, 210.0, 210.0, 200.0)
        self.assertEqual(verdict, "OP-MISMATCH-FAIL")

    def test_op_mismatch_just_under_negative_limit_fails(self):
        # dvsop = -5.5, spread ~ 0.53
        _, _, verdict = rc.startup_verdict(189.0, 190.0, 190.0, 200.0)
        self.assertEqual(verdict, "OP-MISMATCH-FAIL")

    def test_op_mismatch_overrides_no_ringing(self):
        # spread 2.99 (> 2) AND dvsop 10 (> 5): the mismatch check wins
        _, _, verdict = rc.startup_verdict(99.0, 102.0, 100.0, 90.0)
        self.assertEqual(verdict, "OP-MISMATCH-FAIL")

    def test_latched_zero(self):
        _, _, verdict = rc.startup_verdict(0.0, 1.0, 1.0, 1.0)
        self.assertEqual(verdict, "LATCHED-ZERO")

    def test_latched_zero_overrides_everything(self):
        # spread would fail (150 > 2) and dvsop would fail (-100 < -5),
        # but end <= 0 is graded LATCHED-ZERO
        _, _, verdict = rc.startup_verdict(0.0, 1.0, 1.0, 1.0)
        self.assertEqual(verdict, "LATCHED-ZERO")
        _, _, verdict = rc.startup_verdict(-1e-3, 1e-3, 1e-3, 1e-3)
        self.assertEqual(verdict, "LATCHED-ZERO")

    def test_thresholds_are_the_shared_constants(self):
        self.assertEqual(rc.SPREAD_LIMIT_PCT, 2.0)
        self.assertEqual(rc.OP_MISMATCH_LIMIT_PCT, 5.0)


class RequireTests(unittest.TestCase):
    """`require` takes the number validator injected (issue #280): each
    reducer passes its own `finite` and the grammars stay separate."""

    @staticmethod
    def strict_finite(raw, key, source):
        # biasref's grammar: strict finite decimal, no underscores etc.
        if not re.match(r"[+-]?(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?\Z", raw):
            raise rc.ReductionError("%s: key %r value %r is not a finite "
                                    "decimal number" % (source, key, raw))
        return float(raw)

    @staticmethod
    def loose_finite(raw, key, source):
        # biasop's grammar: float() then finiteness
        return float(raw)

    def test_missing_key_names_source_tag_and_key(self):
        with self.assertRaisesRegex(rc.ReductionError,
                                    "src: TAG line missing required "
                                    "key\(s\): b, a"):
            rc.require({"c": "1"}, ("b", "a", "c"), "TAG", "src",
                       self.strict_finite)

    def test_returns_values_through_the_injected_validator(self):
        out = rc.require({"a": "2.5"}, ("a",), "TAG", "src",
                         lambda raw, key, source: 42.0)
        self.assertEqual(out, {"a": 42.0})

    def test_injection_preserves_the_deliberate_grammar_divergence(self):
        # `1_0` is a valid float literal but not a strict decimal token:
        # the strict (biasref) grammar rejects it, the float (biasop)
        # grammar accepts it. One `require`, two behaviours.
        with self.assertRaises(rc.ReductionError):
            rc.require({"a": "1_0"}, ("a",), "TAG", "src", self.strict_finite)
        self.assertEqual(rc.require({"a": "1_0"}, ("a",), "TAG", "src",
                                    self.loose_finite), {"a": 10.0})


if __name__ == "__main__":
    unittest.main()
