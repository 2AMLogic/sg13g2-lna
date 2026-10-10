"""Unit tests and committed-record replay for reduce_biasref.py (issue #149).

Stdlib only, headless, no ngspice, no PDK, single process. Fixtures are
generated inline into temp dirs (a good complete log set, then one defect at
a time); the replay tests reduce the retained logs of both committed records
into temp files and compare with the committed CSVs. Nothing writes under
sim/.

Run from the repo root:

    python3 -I -m unittest discover -s sim/biasref-topology/tests
"""
import contextlib
import importlib.util
import io
import shutil
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
EXP = HERE.parent

_spec = importlib.util.spec_from_file_location(
    "reduce_biasref", EXP / "reduce_biasref.py")
rb = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(rb)

STAGE1_ID = "20260921-160018-a46ed37"
STAGE2_ID = "20260921-173323-2aeafef"
CORR_ID = "20261010-100000-424d385"


def log(line):
    return "ngspice banner\n%s\nBENCH_COMPLETE\n" % line


MPA = "MPADIODE veb 0.9 id -0.0001"
CORE = "BIASREF iq3 0.0004 iqa 1.6E-05 vbref 0.83 vna 0.74 vsdb 0.96"
SERVO = ("SERVO iq3 0.0005 iv 1.6E-05 iref -4E-05 vbg 1.04 vl 1.04 "
         "gsvo 0.9 vbref 0.85 cb3 0.74 idd 0.0006")


def su(end="0.0004", s2=None, s3=None):
    return "STARTUP iq3_end %s iq3_s2 %s iq3_s3 %s" % (
        end, end if s2 is None else s2, end if s3 is None else s3)


class Fixture(unittest.TestCase):
    smoke = False

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.d = self.tmp / "corners"
        self.d.mkdir()
        self.lines = {}
        labels, temps, vdds, feeds, cells = rb.grids(self.smoke)
        for l in labels:
            for t in temps:
                for f in feeds:
                    self.lines[rb.mpa_id(l, t, f)] = MPA
                for v in vdds:
                    self.lines[rb.core_id((l, t, v))] = CORE
                    self.lines[rb.servo_id((l, t, v))] = SERVO
        for c in cells:
            self.lines[rb.startup_id(c)] = su()
            self.lines[rb.servo_startup_id(c)] = su("0.0005")
        # op iq3 for the servo pairs is 0.0005, for the core pairs 0.0004.
        self.write_all()

    def write_all(self):
        for pid, line in self.lines.items():
            (self.d / (pid + ".log")).write_text(log(line))

    def put(self, pid, line):
        self.lines[pid] = line
        (self.d / (pid + ".log")).write_text(log(line))

    def reduce(self, phases=rb.ALL_PHASES):
        return rb.reduce_all(str(self.d), phases, self.smoke)

    def rejects(self, *needles, **kw):
        with self.assertRaises(rb.ReductionError) as cm:
            self.reduce(**kw)
        msg = str(cm.exception)
        for n in needles:
            self.assertIn(n, msg)

    def cli(self, *extra):
        out = self.tmp / "out"
        out.mkdir(exist_ok=True)
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            rc = rb.main(["--corners-dir", str(self.d), "--out-dir",
                          str(out), "--prefix", "x", *extra])
        return rc, err.getvalue(), out


CORE0 = rb.core_id(("typ", "27", "1.80"))
SU0 = rb.startup_id(("typ", "27", "1.80"))
SERVO_SU0 = rb.servo_startup_id(("typ", "27", "1.80"))
MPA0 = rb.mpa_id("typ", "27", "100u")


class TestValid(Fixture):
    def test_all_five_phases_and_shapes(self):
        out = self.reduce()
        self.assertEqual(set(out), set(rb.ALL_PHASES))
        self.assertEqual(len(out["mpa-diode"].splitlines()), 28)
        self.assertEqual(len(out["core-minigrid"].splitlines()), 28)
        self.assertEqual(len(out["servo-minigrid"].splitlines()), 28)
        for ph in ("core-startup", "servo-startup"):
            self.assertEqual(len(out[ph].splitlines()), 4)
        for line in out["core-minigrid"].splitlines():
            self.assertEqual(line.count(","), 9)
        self.assertIn("core_typ_27c_vdd1.80v,typ,mos_tt,27,1.80,0.0004,"
                      "1.6E-05,0.83,0.74,0.96", out["core-minigrid"])
        self.assertIn("mpa_typ_27c_i100u,typ,27,100u,0.9\n",
                      out["mpa-diode"])

    def test_startup_pass_conventions(self):
        row = [l for l in self.reduce()["core-startup"].splitlines()
               if l.startswith(SU0)][0]
        self.assertEqual(
            row, "%s,typ,27,1.80,0.0004,0.0004,0.000,0.000,PASS" % SU0)

    def test_stage1_needs_no_servo_logs(self):
        for p in self.d.glob("servo_*.log"):
            p.unlink()
        out = self.reduce(rb.STAGE1_PHASES)
        self.assertEqual(set(out), set(rb.STAGE1_PHASES))

    def test_stage1_rejects_extra_servo_logs_only_if_unexpected(self):
        # servo logs present while reducing stage1 are unexpected inventory.
        self.rejects("unexpected", "servo_", phases=rb.STAGE1_PHASES)

    def test_genuine_startup_failures_stay_visible(self):
        cases = [
            (su("0.0004", "0.0004", "0.00044"), "NO-RINGING-FAIL"),
            (su("0.00044", "0.00044", "0.00044"), "OP-MISMATCH-FAIL"),
            (su("0", "0", "0"), "LATCHED-ZERO"),
        ]
        for line, verdict in cases:
            self.put(SU0, line)
            rows = self.reduce()["core-startup"]
            self.assertTrue(
                [r for r in rows.splitlines()
                 if r.startswith(SU0)][0].endswith(verdict), (line, rows))

    def test_servo_startup_pairs_with_servo_op(self):
        row = [l for l in self.reduce()["servo-startup"].splitlines()
               if l.startswith(SERVO_SU0)][0]
        self.assertIn(",0.0005,0.0005,0.000,0.000,PASS", row)

    def test_negative_zero_matches_awk_format(self):
        self.put(SU0, su("0.00039999999"))
        row = [l for l in self.reduce()["core-startup"].splitlines()
               if l.startswith(SU0)][0]
        self.assertIn(",-0.000,", row)


class TestMalformed(Fixture):
    def test_missing_measurement_line(self):
        self.put(MPA0, "nothing here")
        self.rejects(MPA0, "no MPADIODE")

    def test_duplicate_measurement_line(self):
        self.put(CORE0, CORE + "\n" + CORE)
        self.rejects(CORE0, "2 BIASREF lines")

    def test_wrong_type_line(self):
        self.put(CORE0, MPA)
        self.rejects(CORE0, "no BIASREF")

    def test_missing_key(self):
        self.put(CORE0, CORE.replace(" vsdb 0.96", ""))
        self.rejects(CORE0, "vsdb")

    def test_duplicate_key(self):
        self.put(CORE0, CORE + " vsdb 0.97")
        self.rejects(CORE0, "'vsdb' repeated")

    def test_odd_token_count(self):
        self.put(CORE0, CORE + " vsdb")
        self.rejects(CORE0, "odd token")

    def test_trailing_numeric_junk(self):
        self.put(SU0, "STARTUP iq3_end 1 iq3_s2 1garbage iq3_s3 1")
        self.rejects(SU0, "iq3_s2", "1garbage")

    def test_non_finite_and_overflow(self):
        for bad in ("nan", "NaN", "inf", "-inf", "infinity", "1e999",
                    "-1e999", "1_0", "0x10", "--1", "1e", "", "."):
            self.put(MPA0, "MPADIODE veb %s" % bad if bad
                     else "MPADIODE veb")
            with self.assertRaises(rb.ReductionError, msg=bad):
                self.reduce()

    def test_bad_value_in_every_phase_names_file_and_key(self):
        for pid, line, key in (
                (CORE0, CORE.replace("vna 0.74", "vna 0.7x"), "vna"),
                (rb.servo_id(("typ", "27", "1.80")),
                 SERVO.replace("idd 0.0006", "idd nan"), "idd"),
                (SERVO_SU0, su("0.0005", "inf"), "iq3_s2")):
            self.put(pid, line)
            self.rejects(pid, key)
            self.setUp()

    def test_missing_log_is_missing_phase_point(self):
        (self.d / (CORE0 + ".log")).unlink()
        self.rejects("missing log", CORE0)

    def test_missing_servo_phase_cannot_be_complete(self):
        for p in self.d.glob("servo_*.log"):
            p.unlink()
        self.rejects("missing log", "servo_typ_27c_vdd1.80v.log")

    def test_unexpected_log(self):
        (self.d / "core_typ_27c_vdd1.70v.log").write_text(log(CORE))
        self.rejects("unexpected", "core_typ_27c_vdd1.70v.log")

    def test_missing_op_counterpart_in_smoke_style_inventory(self):
        # A startup cell whose op cell is absent from the op rows.
        rows = {"core_other": {"iq3": "1"}}
        with self.assertRaises(rb.ReductionError) as cm:
            rb.startup_rows(str(self.d), [("typ", "27", "1.80")],
                            rb.startup_id, rows, rb.core_id, "core")
        self.assertIn("no matching core point", str(cm.exception))

    def test_nothing_written_on_rejection(self):
        self.put(CORE0, "garbage")
        rc, err, out = self.cli()
        self.assertEqual(rc, 2)
        self.assertIn("MALFORMED EVIDENCE", err)
        self.assertIn(CORE0, err)
        self.assertEqual(list(out.iterdir()), [])

    def test_refuses_to_overwrite(self):
        rc, _, out = self.cli()
        self.assertEqual(rc, 0)
        self.assertEqual(len(list(out.iterdir())), 5)
        rc, err, _ = self.cli()
        self.assertEqual(rc, 4)
        self.assertIn("refusing to overwrite", err)


class TestSmoke(Fixture):
    smoke = True

    def test_smoke_inventory(self):
        out = self.reduce()
        self.assertEqual(len(out["core-minigrid"].splitlines()), 2)
        self.assertEqual(len(out["core-startup"].splitlines()), 2)


class TestHistoricalReplay(unittest.TestCase):
    """Replay every committed phase CSV from its retained logs."""

    @classmethod
    def setUpClass(cls):
        cls.out = {}
        for rid, phases in ((STAGE1_ID, rb.STAGE1_PHASES),
                            (STAGE2_ID, rb.ALL_PHASES)):
            cls.out[rid] = rb.reduce_all(str(EXP / "corners" / rid), phases)

    def committed(self, rid, phase):
        return (EXP / "records" / ("%s-%s.csv" % (rid, phase))).read_text()

    def test_phase_csvs_replay_byte_for_byte(self):
        for rid, texts in self.out.items():
            for phase, text in texts.items():
                if phase == "core-minigrid":
                    continue  # historical vsdb_v defect, see below
                with self.subTest(record=rid, phase=phase):
                    self.assertEqual(text, self.committed(rid, phase))

    def test_core_minigrid_historical_vsdb_defect_is_exactly_that(self):
        for rid, texts in self.out.items():
            new = texts["core-minigrid"].splitlines()
            old = self.committed(rid, "core-minigrid").splitlines()
            with self.subTest(record=rid):
                self.assertEqual(len(new), len(old))
                self.assertEqual(old[0], new[0])  # header declares vsdb_v
                for n, o in zip(new[1:], old[1:]):
                    self.assertEqual(n.rsplit(",", 1)[0], o)
                    self.assertEqual(o.count(",") + 1, 9)

    def test_correction_record_matches_reducer(self):
        for rid, short in ((STAGE1_ID, "a46ed37"), (STAGE2_ID, "2aeafef")):
            p = EXP / "records" / ("%s-%s-core-minigrid-corrected.csv"
                                   % (CORR_ID, short))
            with self.subTest(record=rid):
                self.assertEqual(self.out[rid]["core-minigrid"],
                                 p.read_text())

    def test_committed_startups_are_all_pass(self):
        for rid, texts in self.out.items():
            for phase in ("core-startup", "servo-startup"):
                if phase in texts:
                    for row in texts[phase].splitlines()[1:]:
                        self.assertTrue(row.endswith(",PASS"), row)


if __name__ == "__main__":
    unittest.main()
