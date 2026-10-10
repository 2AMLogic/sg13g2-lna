"""PDK-free tests for the startup waveform settling audit (issue #154).

Synthetic waveforms plus a replay of the retained record
20260921-173552-2aeafef into scratch outputs only (nothing under sim/ is
written). Run from the repo root:

    python3 -I -m unittest discover -s sim/lna-bias-pvt/tests \
        -p test_startup_waveform_audit.py -v
"""
import contextlib
import importlib.util
import io
import os
import tempfile
import unittest
from pathlib import Path

BIAS = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location(
    "reduce_biasop", BIAS / "reduce_biasop.py")
rb = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(rb)

OP = 4.0e-3
RECORD = BIAS / "corners" / "20260921-173552-2aeafef"


def wave(step=1e-9, tstop=1.2e-5, fn=None):
    n = int(round(tstop / step))
    t = [i * step for i in range(n + 1)]
    y = [fn(x) if fn else OP for x in t]
    return t, y


class AuditTests(unittest.TestCase):
    def test_stable_passes(self):
        t, y = wave()
        r = rb.startup_waveform_audit(t, y, OP)
        self.assertEqual(r["verdict"], "PASS")
        self.assertEqual(r["n_samples"], 10001)

    def test_mid_window_excursion_with_matching_tail_fails(self):
        t, y = wave(fn=lambda x: OP * 1.2 if 5e-6 <= x <= 5.5e-6 else OP)
        # The historical three-sample check sees only the tail and passes.
        self.assertEqual(
            rb.startup_verdict(y[-1], y[-11], y[-26], OP)[2], "PASS")
        r = rb.startup_waveform_audit(t, y, OP)
        self.assertNotEqual(r["verdict"], "PASS")
        self.assertEqual(r["verdict"], "WINDOW-OP-MISMATCH-FAIL")

    def test_small_ringing_spread_fails(self):
        t, y = wave(fn=lambda x: OP * 1.03 if 5e-6 <= x <= 5.5e-6 else OP)
        self.assertEqual(rb.startup_waveform_audit(t, y, OP)["verdict"],
                         "WINDOW-SPREAD-FAIL")

    def test_latched_zero(self):
        t, y = wave(fn=lambda x: 0.0)
        self.assertEqual(rb.startup_waveform_audit(t, y, OP)["verdict"],
                         "WINDOW-LATCHED-ZERO")

    def test_early_transient_outside_window_ignored(self):
        t, y = wave(fn=lambda x: OP * 0.2 if x < 1.5e-6 else OP)
        self.assertEqual(rb.startup_waveform_audit(t, y, OP)["verdict"],
                         "PASS")

    def test_truncated(self):
        t, y = wave(tstop=8e-6)
        with self.assertRaises(rb.WaveformTruncatedError):
            rb.startup_waveform_audit(t, y, OP)
        with self.assertRaises(rb.WaveformTruncatedError):
            rb.startup_waveform_audit([], [], OP)
        with self.assertRaises(rb.WaveformTruncatedError):
            rb.startup_waveform_audit([0.0, 1.0], [1.0], OP)
        with self.assertRaises(rb.WaveformTruncatedError):
            rb.parse_waveform("", "x")
        with self.assertRaises(rb.WaveformTruncatedError):
            rb.parse_waveform("1e-9\n", "x")

    def test_nonfinite(self):
        t, y = wave()
        y[5000] = float("nan")
        with self.assertRaises(rb.WaveformNonfiniteError):
            rb.startup_waveform_audit(t, y, OP)
        for bad in ("nan", "inf", "abc"):
            with self.assertRaises(rb.WaveformNonfiniteError):
                rb.parse_waveform("0 1\n1e-9 %s\n" % bad, "x")

    def test_nonmonotonic(self):
        t, y = wave()
        t[6000] = t[5999]
        with self.assertRaises(rb.WaveformNonmonotonicError):
            rb.startup_waveform_audit(t, y, OP)
        with self.assertRaises(rb.WaveformNonmonotonicError):
            rb.parse_waveform("0 1\n2e-9 1\n1e-9 1\n", "x")

    def test_insufficient_coverage(self):
        # Coarse 20 ns step: ends covered, but too few in-window samples
        # and gaps too large.
        t, y = wave(step=2e-8)
        with self.assertRaises(rb.WaveformCoverageError):
            rb.startup_waveform_audit(t, y, OP)
        # Enough samples overall but the window start is not covered.
        t, y = wave(step=1e-9)
        keep = [i for i, x in enumerate(t) if not 2e-6 <= x < 3e-6]
        with self.assertRaises(rb.WaveformCoverageError):
            rb.startup_waveform_audit([t[i] for i in keep],
                                      [y[i] for i in keep], OP)

    def test_sample_gap(self):
        t, y = wave()
        keep = [i for i, x in enumerate(t) if not 6e-6 < x < 6.1e-6]
        with self.assertRaises(rb.WaveformSampleGapError):
            rb.startup_waveform_audit([t[i] for i in keep],
                                      [y[i] for i in keep], OP)

    def test_errors_are_reduction_errors(self):
        for c in (rb.WaveformTruncatedError, rb.WaveformNonfiniteError,
                  rb.WaveformNonmonotonicError, rb.WaveformCoverageError,
                  rb.WaveformSampleGapError):
            self.assertTrue(issubclass(c, rb.ReductionError))

    def test_historical_verdict_unchanged(self):
        self.assertEqual(rb.startup_verdict(4e-3, 4e-3, 4e-3, 4e-3)[2],
                         "PASS")
        self.assertEqual(rb.SPREAD_LIMIT_PCT, 2.0)
        self.assertEqual(rb.OP_MISMATCH_LIMIT_PCT, 5.0)


class ReplayTests(unittest.TestCase):
    def test_retained_record_replay_scratch_only(self):
        with tempfile.TemporaryDirectory() as d:
            outs = [os.path.join(d, n) for n in ("s.csv", "u.csv", "w.csv")]
            err = io.StringIO()
            with contextlib.redirect_stderr(err):
                rc = rb.main(["--corners-dir", str(RECORD),
                              "--require-audit", "--summary-csv", outs[0],
                              "--startup-csv", outs[1],
                              "--waveform-audit-csv", outs[2]])
            self.assertEqual(rc, 0, err.getvalue())
            rows = Path(outs[2]).read_text().splitlines()
            self.assertEqual(len(rows), 4)
            for r in rows[1:]:
                f = r.split(",")
                self.assertEqual(f[-2:], ["PASS", "PASS"])
                self.assertEqual(f[6], "10001")
            # Published derivation record replays byte-for-byte.
            pub = BIAS / "records" / (
                "20260921-173552-2aeafef-startup-waveform-audit.csv")
            self.assertEqual(Path(outs[2]).read_bytes(), pub.read_bytes())
            # Historical CSV untouched by the audit.
            hist = BIAS / "records" / "20260921-173552-2aeafef-startup.csv"
            self.assertEqual(Path(outs[1]).read_bytes(), hist.read_bytes())

    def test_replay_refuses_overwrite(self):
        with tempfile.TemporaryDirectory() as d:
            w = os.path.join(d, "w.csv")
            Path(w).write_text("x")
            with contextlib.redirect_stderr(io.StringIO()):
                rc = rb.main(["--corners-dir", str(RECORD),
                              "--summary-csv", os.path.join(d, "s"),
                              "--startup-csv", os.path.join(d, "u"),
                              "--waveform-audit-csv", w])
            self.assertEqual(rc, 4)


if __name__ == "__main__":
    unittest.main()
