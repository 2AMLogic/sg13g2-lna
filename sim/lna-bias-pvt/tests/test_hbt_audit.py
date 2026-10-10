"""PDK-free tests for hbt_audit.py (issue #155).

Stdlib only, no ngspice, no PDK, nothing written under sim/. Run from the
repo root (same discover command CI and run-local-checks.sh use):

    python3 -I -m unittest discover -s sim/lna-bias-pvt/tests
"""
import importlib.util
import os
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
BIAS = HERE.parent
REPO = BIAS.parent.parent
NETLIST = REPO / "design" / "netlist" / "lna.spice"

_spec = importlib.util.spec_from_file_location("hbt_audit",
                                               BIAS / "hbt_audit.py")
ha = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ha)

NET = ("**.subckt lna vdd vss rfin rfout\n"
       "XQ1 c1 b1 e1 vss npn13G2 Nx=8\n"
       "XQa a a vss vss npn13G2 Nx=1\n"
       "Rx vdd c1 1k m=1\n"
       "XMb nc_b nc_b vdd vdd sg13_hv_pmos w=10u l=1u ng=1 m=1\n"
       "**.ends\n.end\n")


def good_line(hbts, over=None, drop=(), count=None, extra=""):
    kv = {}
    for k, h in hbts.items():
        kv[k + "_nx"] = str(h["nx"])
        kv[k + "_ic"] = "0.5E-03"
        kv[k + "_vbe"] = "0.85"
        kv[k + "_vce"] = "1.0"
    kv.update(over or {})
    for d in drop:
        kv.pop(d)
    head = "HBTAUDIT count %s " % (len(hbts) if count is None else count)
    return head + " ".join("%s %s" % i for i in kv.items()) + extra


class Inventory(unittest.TestCase):
    def test_committed_netlist_has_all_six_hbts(self):
        hbts, _ = ha.parse_hbts(NETLIST.read_text(), str(NETLIST))
        self.assertEqual(sorted(hbts),
                         ["xq1", "xq2", "xq3", "xqa", "xqb", "xqc"])
        self.assertEqual([hbts[k]["nx"] for k in sorted(hbts)],
                         [8, 8, 1, 1, 8, 1])

    def test_added_instance_gets_probes_automatically(self):
        more = NET.replace("**.ends", "XQz z z vss vss npn13G2 Nx=4\n**.ends")
        hbts, ports = ha.parse_hbts(more)
        text = "\n".join(ha.probe_lines(hbts, ports))
        self.assertIn("xqz_ic", text)
        self.assertIn("HBTAUDIT count 3", text)
        self.assertIn("xqz_nx 4", text)

    def test_resized_instance_changes_nx_and_log_must_follow(self):
        hbts, _ = ha.parse_hbts(NET.replace("Nx=1", "Nx=2"))
        self.assertEqual(hbts["xqa"]["nx"], 2)
        old_hbts, _ = ha.parse_hbts(NET)
        with self.assertRaisesRegex(ha.ReductionError, "logged Nx"):
            ha.audit_log(good_line(old_hbts), hbts)

    def test_empty_inventory_and_bad_nx_rejected(self):
        with self.assertRaises(ha.ReductionError):
            ha.parse_hbts("**.subckt lna vdd vss\nRx vdd vss 1k\n**.ends\n")
        with self.assertRaises(ha.ReductionError):
            ha.parse_hbts(NET.replace("Nx=8", "Nx=11"))
        with self.assertRaises(ha.ReductionError):
            ha.parse_hbts(NET.replace("Nx=1", "Nx=0"))

    def test_probe_node_references(self):
        hbts, ports = ha.parse_hbts(NET)
        text = "\n".join(ha.probe_lines(hbts, ports))
        self.assertIn("let xq1_vce = v(xdut.c1) - v(xdut.e1)", text)
        self.assertIn("let xqa_vbe = v(xdut.a) - v(vss)", text)  # port node

    def test_template_has_probe_marker_and_runner_uses_tool(self):
        tmpl = (BIAS / "testbench" / "tb_lna_biasop.spice.tmpl").read_text()
        self.assertIn("@@HBT_AUDIT_PROBES@@", tmpl)
        self.assertLess(tmpl.index("@@HBT_AUDIT_PROBES@@"),
                        tmpl.index('echo "BENCH_COMPLETE"'))
        run = (BIAS / "run_biasop_sweep.sh").read_text()
        self.assertIn("hbt_audit.py", run)
        self.assertIn("@@HBT_AUDIT_PROBES@@", run)


class Classification(unittest.TestCase):
    def test_boundaries(self):
        c = ha.classify
        # ic strict: exactly 0.003*Nx is OUT; vbe/vce bounds inclusive.
        self.assertFalse(c(1, 3.0e-3, 0.8, 1.0)[0]["ic"])
        self.assertTrue(c(1, 2.999e-3, 0.8, 1.0)[0]["ic"])
        self.assertTrue(c(1, 1e-3, 0.65, 0.4)[0]["vbe"])
        self.assertTrue(c(1, 1e-3, 0.65, 0.4)[0]["vce"])
        self.assertTrue(c(1, 1e-3, 0.96, 2.0)[0]["vbe"])
        self.assertTrue(c(1, 1e-3, 0.96, 2.0)[0]["vce"])
        self.assertFalse(c(1, 1e-3, 0.6499, 1.0)[0]["vbe"])
        self.assertFalse(c(1, 1e-3, 0.9601, 1.0)[0]["vbe"])
        self.assertFalse(c(1, 1e-3, 0.8, 0.3999)[0]["vce"])
        self.assertFalse(c(1, 1e-3, 0.8, 2.0001)[0]["vce"])

    def test_nx_scales_current_limit(self):
        _, bad1, lim1 = ha.classify(1, 4e-3, 0.8, 1.0)
        _, bad8, lim8 = ha.classify(8, 4e-3, 0.8, 1.0)
        self.assertEqual(bad1, ["ic"])
        self.assertEqual(bad8, [])
        self.assertAlmostEqual(lim8, 0.024)
        self.assertEqual(ha.classify(8, 0.024, 0.8, 1.0)[1], ["ic"])

    def test_ambient_range_is_separate_from_tj(self):
        self.assertTrue(ha.ambient_in_range("125"))
        self.assertTrue(ha.ambient_in_range("-40"))
        self.assertFalse(ha.ambient_in_range("126"))


class LogValidation(unittest.TestCase):
    def setUp(self):
        self.hbts, _ = ha.parse_hbts(NET)

    def bad(self, line, pat):
        with self.assertRaisesRegex(ha.ReductionError, pat):
            ha.audit_log(line, self.hbts, "x.log")

    def test_good(self):
        out = ha.audit_log(good_line(self.hbts), self.hbts)
        self.assertEqual(sorted(out), ["xq1", "xqa"])

    def test_no_line(self):
        self.bad("nothing here", "no HBTAUDIT")

    def test_missing_instance(self):
        self.bad(good_line(self.hbts, drop=["xqa_nx", "xqa_ic", "xqa_vbe",
                                            "xqa_vce"]), "missing probe")

    def test_missing_probe(self):
        self.bad(good_line(self.hbts, drop=["xq1_vce"]), "xq1_vce")

    def test_count_mismatch(self):
        self.bad(good_line(self.hbts, count=3), "count 3")

    def test_unexpected_instance(self):
        self.bad(good_line(self.hbts, over={"xqz_nx": "1"}, count=2),
                 "not in the netlist")

    def test_stray_key(self):
        self.bad(good_line(self.hbts, extra=" foo 1"), "unexpected")

    def test_duplicate_key(self):
        self.bad(good_line(self.hbts, extra=" xq1_ic 1"), "repeated")

    def test_nonfinite_and_text(self):
        for v in ("nan", "inf", "-inf", "abc"):
            self.bad(good_line(self.hbts, over={"xq1_ic": v}), "xq1_ic")

    def test_two_lines(self):
        ln = good_line(self.hbts)
        self.bad(ln + "\n" + ln, "2 HBTAUDIT")


class Reduction(unittest.TestCase):
    """Whole-directory reduction with synthetic op logs (smoke inventory)."""

    def make(self, d, line):
        rb = ha._rb()
        for cell in rb.op_cells(True):
            Path(d, rb.op_id(cell) + ".log").write_text(
                "BIASOP ic1 1\n" + line + "\nBENCH_COMPLETE\n")
        for cell in rb.startup_cells(True):
            Path(d, rb.startup_id(cell) + ".log").write_text("x\n")

    def rows(self, line):
        with tempfile.TemporaryDirectory() as d:
            self.make(d, line)
            return ha.reduce_dir(d, NET, smoke=True).splitlines()

    def test_in_range_table_has_every_instance_and_tj_unassessed(self):
        hbts, _ = ha.parse_hbts(NET)
        rows = self.rows(good_line(hbts))
        self.assertEqual(rows[0], ha.CSV_HEADER)
        self.assertEqual(len(rows), 3)
        for r in rows[1:]:
            f = r.split(",")
            self.assertEqual(f[13], "IN-RANGE")
            self.assertEqual(f[-1], "UNASSESSED")
            self.assertEqual(f[-2], "yes")  # ambient 27 C in model range

    def test_genuine_out_of_range_is_a_row_not_an_error(self):
        hbts, _ = ha.parse_hbts(NET)
        rows = self.rows(good_line(hbts, over={"xqa_ic": "0.004",
                                               "xqa_vce": "2.1"}))
        qa = [r.split(",") for r in rows if ",XQa," in r][0]
        self.assertEqual(qa[13], "OUT-OF-RANGE")
        self.assertEqual(qa[14], "ic+vce")
        self.assertEqual(qa[15], "yes")   # above the 1.6 V header datum
        q1 = [r.split(",") for r in rows if ",XQ1," in r][0]
        self.assertEqual(q1[13], "IN-RANGE")
        self.assertEqual(q1[15], "no")

    def test_header_datum_does_not_change_validity(self):
        hbts, _ = ha.parse_hbts(NET)
        rows = self.rows(good_line(hbts, over={"xq1_vce": "1.8"}))
        f = [r.split(",") for r in rows if ",XQ1," in r][0]
        self.assertEqual((f[13], f[15]), ("IN-RANGE", "yes"))

    def test_missing_probe_rejects_whole_set(self):
        hbts, _ = ha.parse_hbts(NET)
        with tempfile.TemporaryDirectory() as d:
            self.make(d, good_line(hbts, drop=["xq1_ic"]))
            with self.assertRaises(ha.ReductionError):
                ha.reduce_dir(d, NET, smoke=True)

    def test_old_logs_without_probes_are_not_tabulated(self):
        with tempfile.TemporaryDirectory() as d:
            self.make(d, "")
            with self.assertRaisesRegex(ha.ReductionError, "no HBTAUDIT"):
                ha.reduce_dir(d, NET, smoke=True)

    def test_cli_exit_codes_and_no_overwrite(self):
        hbts, _ = ha.parse_hbts(NET)
        with tempfile.TemporaryDirectory() as d, \
                tempfile.TemporaryDirectory() as o:
            self.make(d, good_line(hbts))
            net = Path(o, "n.spice")
            net.write_text(NET)
            out = os.path.join(o, "t.csv")
            args = ["reduce", "--netlist", str(net), "--corners-dir", d,
                    "--out-csv", out, "--smoke"]
            self.assertEqual(ha.main(args), 0)
            self.assertEqual(ha.main(args), 4)


class LegacyRecords(unittest.TestCase):
    def test_legacy_coverage_is_incomplete_and_names_gaps(self):
        rows = ha.legacy_coverage(NETLIST.read_text()).splitlines()[1:]
        by = {r.split(",")[0]: r.split(",") for r in rows}
        self.assertEqual(len(by), 6)
        for q in ("XQa", "XQb", "XQc"):
            self.assertEqual(by[q][5], "INCOMPLETE")
            self.assertEqual(by[q][6], "ic+vbe+vce")
        self.assertEqual(by["XQ2"][6], "vbe")
        for r in by.values():
            self.assertEqual(r[-1], "UNASSESSED")

    def test_committed_records_lack_hbt_audit(self):
        logs = sorted((BIAS / "corners").glob("*/op_*.log"))
        self.assertTrue(logs)
        for p in logs:
            self.assertNotIn("HBTAUDIT", p.read_text(errors="replace"))
        # Only the deterministic op-grid records (dirs holding op_*.log);
        # corners/ also holds the issue-#90 Monte Carlo campaign's dirs.
        for rec in sorted({p.parent for p in logs}):
            with self.assertRaises(ha.ReductionError):
                ha.reduce_dir(str(rec), NETLIST.read_text())


if __name__ == "__main__":
    unittest.main()
