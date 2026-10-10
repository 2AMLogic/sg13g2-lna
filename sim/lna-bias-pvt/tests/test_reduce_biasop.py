"""Unit tests and committed-record replay for reduce_biasop.py (issue #117).

Stdlib only, headless, no ngspice, no PDK, single process. Fixtures are
generated inline into temp dirs (a good 45+3 log set, then one defect at a
time); the replay tests reduce the retained logs of both committed records
into temp files and compare bytes with the committed CSVs. Nothing writes
under sim/.

Run from the repo root:

    python3 -I -m unittest discover -s sim/lna-bias-pvt/tests
"""
import contextlib
import importlib.util
import io
import os
import shutil
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
BIAS = HERE.parent

_spec = importlib.util.spec_from_file_location(
    "reduce_biasop", BIAS / "reduce_biasop.py")
rb = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(rb)

OP_BASE = {"ic1": "0.004", "ic2": "0.004", "ic3": "0.0005", "ib1": "3E-06",
           "vb1": "0.85", "vbref": "0.85", "vce1": "0.8", "vce2": "1.0",
           "vbe1": "0.85", "idd": "0.0047", "pdc": "0.0085"}
AUDIT = {"vbg": "1.04", "vl": "1.0405", "gsvo": "0.9", "cb3": "0.74"}


def op_line(over=None, drop=(), audit=True):
    kv = dict(OP_BASE)
    if audit:
        kv.update(AUDIT)
    kv.update(over or {})
    for k in drop:
        kv.pop(k)
    return "BIASOP " + " ".join("%s %s" % i for i in kv.items())


def su_line(end="0.004", s2=None, s3=None):
    s2 = end if s2 is None else s2
    s3 = end if s3 is None else s3
    return "STARTUP ic1_end %s ic1_s2 %s ic1_s3 %s" % (end, s2, s3)


def log(line):
    return "ngspice banner\n%s\nBENCH_COMPLETE\n" % line


class Fixture(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.d = self.tmp / "corners"
        self.d.mkdir()
        for c in rb.op_cells():
            self.put(rb.op_id(c), op_line())
        for c in rb.STARTUP_CELLS:
            self.put(rb.startup_id(c), su_line())

    def put(self, pid, line, raw=None):
        (self.d / (pid + ".log")).write_text(raw if raw is not None
                                             else log(line))

    def reduce(self, **kw):
        return rb.reduce_all(str(self.d), **kw)

    def bad(self, needle, **kw):
        with self.assertRaises(rb.ReductionError) as cm:
            self.reduce(**kw)
        self.assertIn(needle, str(cm.exception))

    NOM_OP = rb.op_id(rb.NOMINAL_CELL)
    NOM_SU = rb.startup_id(rb.NOMINAL_CELL)


class GoodInputs(Fixture):
    def test_clean_reduction(self):
        s, u, f = self.reduce(require_audit=True)
        self.assertEqual(len(s.splitlines()), 46)
        self.assertEqual(len(u.splitlines()), 4)
        self.assertEqual(f["N_OP"], "45")
        self.assertEqual(f["STARTUP_ALL_PASS"], "yes")
        self.assertEqual(f["N_IC1_BAD"], "0")
        self.assertEqual(f["SERVO_MAX_ERR_V"], "0.0005")
        self.assertIn(
            "op_typ_27c_vdd1.80v,typ,27,1.80,0.004,0.004,0.0005,3E-06,"
            "0.85,0.85,0.8,1.0,0.85,0.0047,0.0085,yes,yes", s)

    def test_raw_tokens_preserved(self):
        self.put(self.NOM_OP, op_line({"ib1": "4.07447E-06"}))
        s, _, _ = self.reduce()
        self.assertIn(",4.07447E-06,", s)

    def test_no_audit_keys_ok_unless_required(self):
        for c in rb.op_cells():
            self.put(rb.op_id(c), op_line(audit=False))
        _, _, f = self.reduce()
        self.assertEqual(f["AUDIT_PRESENT"], "no")
        self.bad("required but absent", require_audit=True)

    def test_smoke_inventory(self):
        for c in rb.op_cells():
            if c != rb.NOMINAL_CELL:
                (self.d / (rb.op_id(c) + ".log")).unlink()
        for c in rb.STARTUP_CELLS:
            if c != rb.NOMINAL_CELL:
                (self.d / (rb.startup_id(c) + ".log")).unlink()
        s, u, _ = self.reduce(smoke=True)
        self.assertEqual(len(s.splitlines()), 2)
        self.assertEqual(len(u.splitlines()), 2)


class GenuineFailuresAreResults(Fixture):
    def test_ic1_bar_violation_is_a_row(self):
        self.put(self.NOM_OP, op_line({"ic1": "0.0046"}))
        self.put(self.NOM_SU, su_line("0.0046"))
        s, u, f = self.reduce()
        self.assertIn("0.0046,0.004,0.0005,3E-06,0.85,0.85,0.8,1.0,0.85,"
                      "0.0047,0.0085,NO,yes", s)
        self.assertEqual((f["N_IC1_BAD"], f["N_IC1_OK"]), ("1", "44"))

    def test_bar_edges(self):
        self.put(self.NOM_OP, op_line({"ic1": "4.5e-3", "pdc": "10e-3"}))
        s, _, _ = self.reduce()
        row = [r for r in s.splitlines() if r.startswith(self.NOM_OP)][0]
        # ic1 <= bar is inclusive; pdc < bar is strict.
        self.assertTrue(row.endswith(",yes,NO"), row)

    def test_pdc_bar_violation(self):
        self.put(self.NOM_OP, op_line({"pdc": "0.0123"}))
        _, _, f = self.reduce()
        self.assertEqual(f["N_PDC_BAD"], "1")

    def test_startup_failures_get_verdicts(self):
        cases = {
            "NO-RINGING-FAIL": su_line("0.004", "0.0041", "0.004"),
            "OP-MISMATCH-FAIL": su_line("0.0030"),
            "LATCHED-ZERO": su_line("0", "0", "0"),
        }
        for verdict, line in cases.items():
            with self.subTest(verdict):
                self.put(self.NOM_SU, line)
                _, u, f = self.reduce()
                self.assertIn(",%s\n" % verdict, u)
                self.assertEqual(f["STARTUP_ALL_PASS"], "no")
                self.assertIn(verdict, f["STARTUP_VERDICTS"])

    def test_startup_numeric_format(self):
        self.put(self.NOM_SU, su_line("0.004", "0.0041", "0.004"))
        _, u, _ = self.reduce()
        self.assertIn("startup_typ_27c_vdd1.80v,typ,27,1.80,0.004,0.004,"
                      "0.000,2.479,NO-RINGING-FAIL", u)


class MalformedEvidence(Fixture):
    def test_missing_ic1_not_treated_as_zero(self):
        self.put(self.NOM_OP, op_line(drop=("ic1",)))
        self.bad("missing required key(s): ic1")

    def test_missing_pdc(self):
        self.put(self.NOM_OP, op_line(drop=("pdc",)))
        self.bad("missing required key(s): pdc")

    def test_missing_biasop_line(self):
        self.put(self.NOM_OP, "", raw="ngspice\nBENCH_COMPLETE\n")
        self.bad("no BIASOP line")

    def test_missing_startup_line(self):
        self.put(self.NOM_SU, "", raw="BENCH_COMPLETE\n")
        self.bad("no STARTUP line")

    def test_duplicate_line(self):
        self.put(self.NOM_OP, "", raw=log(op_line()) + op_line() + "\n")
        self.bad("2 BIASOP lines")

    def test_duplicate_key(self):
        self.put(self.NOM_OP, op_line() + " ic1 0.001")
        self.bad("key 'ic1' repeated")

    def test_odd_tokens(self):
        self.put(self.NOM_OP, op_line() + " dangling")
        self.bad("odd token count")

    def test_nonfinite_values(self):
        for bad in ("nan", "-nan", "inf", "-inf"):
            with self.subTest(bad):
                self.put(self.NOM_OP, op_line({"ic1": bad}))
                self.bad("not finite")

    def test_nonnumeric_value(self):
        self.put(self.NOM_OP, op_line({"pdc": "oops"}))
        self.bad("not a number")

    def test_nonfinite_startup(self):
        self.put(self.NOM_SU, su_line("nan"))
        self.bad("not finite")

    def test_missing_startup_key(self):
        self.put(self.NOM_SU, "STARTUP ic1_end 0.004 ic1_s2 0.004")
        self.bad("ic1_s3")

    def test_partial_audit_keys(self):
        self.put(self.NOM_OP, op_line(drop=("cb3",)))
        self.bad("partial audit keys")

    def test_audit_keys_nonuniform(self):
        self.put(self.NOM_OP, op_line(audit=False))
        self.bad("audit keys present at some op points")

    def test_missing_log_file(self):
        (self.d / (self.NOM_OP + ".log")).unlink()
        self.bad("missing log(s): " + self.NOM_OP + ".log")

    def test_unexpected_log_file(self):
        self.put("op_typ_27c_vdd1.81v", op_line())
        self.bad("unexpected log(s)")

    def test_missing_op_counterpart_for_startup(self):
        # smoke-style op inventory but full startup inventory
        for c in rb.op_cells():
            if c != rb.NOMINAL_CELL:
                (self.d / (rb.op_id(c) + ".log")).unlink()
        with self.assertRaisesRegex(rb.ReductionError,
                                    "no matching op point"):
            rb.reduce_startup(
                str(self.d), rb.STARTUP_CELLS[0],
                {rb.op_id(rb.NOMINAL_CELL):
                 rb.reduce_op(str(self.d), rb.NOMINAL_CELL, False)})

    def test_missing_startup_counterpart_inventory(self):
        (self.d / (self.NOM_SU + ".log")).unlink()
        self.bad("missing log(s)")


class Cli(Fixture):
    def run_main(self, *extra):
        out = self.tmp / "o"
        out.mkdir(exist_ok=True)
        args = ["--corners-dir", str(self.d), "--summary-csv",
                str(out / "s.csv"), "--startup-csv", str(out / "u.csv"),
                *extra]
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            rc = rb.main(args)
        return rc, out, err.getvalue()

    def test_ok_writes_both(self):
        rc, out, _ = self.run_main()
        self.assertEqual(rc, 0)
        self.assertTrue((out / "s.csv").exists() and (out / "u.csv").exists())

    def test_malformed_writes_nothing(self):
        self.put(self.NOM_OP, op_line(drop=("ic1",)))
        rc, out, err = self.run_main()
        self.assertEqual(rc, 2)
        self.assertIn("MALFORMED EVIDENCE", err)
        self.assertEqual(list(out.iterdir()), [])

    def test_malformed_startup_writes_no_summary_either(self):
        self.put(self.NOM_SU, su_line("inf"))
        rc, out, _ = self.run_main()
        self.assertEqual(rc, 2)
        self.assertEqual(list(out.iterdir()), [])

    def test_refuses_to_overwrite(self):
        out = self.tmp / "o"
        out.mkdir()
        (out / "s.csv").write_text("keep\n")
        rc, _, _ = self.run_main()
        self.assertEqual(rc, 4)
        self.assertEqual((out / "s.csv").read_text(), "keep\n")
        self.assertFalse((out / "u.csv").exists())


class ReplayCommittedRecords(unittest.TestCase):
    """Reduce retained logs and compare bytes with the committed CSVs."""

    def replay(self, rid, audit):
        corners = BIAS / "corners" / rid
        s, u, f = rb.reduce_all(str(corners), require_audit=audit)
        for text, suffix in ((s, "summary"), (u, "startup")):
            committed = (BIAS / "records" / ("%s-%s.csv" % (rid, suffix)))
            self.assertEqual(text.encode(), committed.read_bytes(),
                             "%s %s drifted" % (rid, suffix))
        self.assertEqual(f["N_OP"], "45")
        self.assertEqual(f["STARTUP_ALL_PASS"], "yes")
        return f

    def test_replay_mirror_reference_record(self):
        f = self.replay("20260921-132025-d6da30a", audit=False)
        self.assertEqual(f["AUDIT_PRESENT"], "no")

    def test_replay_dr0003_record(self):
        f = self.replay("20260921-173552-2aeafef", audit=True)
        self.assertEqual(f["AUDIT_PRESENT"], "yes")

    def test_replay_via_cli_into_temp(self):
        rid = "20260921-173552-2aeafef"
        with tempfile.TemporaryDirectory() as t:
            rc = rb.main(["--corners-dir", str(BIAS / "corners" / rid),
                          "--summary-csv", os.path.join(t, "s.csv"),
                          "--startup-csv", os.path.join(t, "u.csv"),
                          "--facts", os.path.join(t, "f")])
            self.assertEqual(rc, 0)
            self.assertEqual(
                Path(t, "s.csv").read_bytes(),
                (BIAS / "records" / (rid + "-summary.csv")).read_bytes())


if __name__ == "__main__":
    unittest.main()
