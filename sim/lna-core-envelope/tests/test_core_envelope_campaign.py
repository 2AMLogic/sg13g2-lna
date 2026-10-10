"""Offline tests for core_envelope_campaign.py (stdlib only; no klt, ngspice or PDK)."""
import importlib.util
import json
import re
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
EXP = HERE.parent
sys.path.insert(0, str(HERE))
import synthetic_reports as syn  # noqa: E402

_spec = importlib.util.spec_from_file_location("core_envelope_campaign", EXP / "core_envelope_campaign.py")
C = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(C)
LVC = C.LVC


def committed_lines():
    out = []
    for ln in C.DESIGN_NETLIST.read_text().splitlines():
        out.append(ln[2:] if ln.startswith("**.subckt") or ln.startswith("**.ends") else ln)
    return [ln for ln in out if ln != ".end"]


class VariantScope(unittest.TestCase):
    def changed(self, sizing, loss="ideal", k=0):
        base = committed_lines()
        new = [ln for ln in C.dut_text(sizing, loss, k).splitlines() if not ln.startswith("* VARIANT EDIT")]
        return base, new

    def test_control_is_byte_identical_to_committed(self):
        base, new = self.changed("s_ctrl_a8")
        self.assertEqual(base, new)

    def test_larger_array_touches_only_xq1_xq2_xmis(self):
        base, new = self.changed("s_fixi_a80")
        self.assertEqual(len(base), len(new))
        diff = {a.split()[0] for a, b in zip(base, new) if a != b}
        self.assertEqual(diff, {"XQ1", "XQ2", "XMis"})
        txt = "\n".join(new)
        self.assertIn("XQ1 casc b1 e1 vss npn13G2 Nx=10 m=8", txt)
        self.assertIn("XQ2 outn vb2 casc vss npn13G2 Nx=10 m=8", txt)
        self.assertIn("XMis bref gsvo vdd vdd sg13_hv_pmos w=51.2u l=1u ng=1 m=1", txt)

    def test_bias_core_hbts_untouched(self):
        base, new = self.changed("s_fixi_a80")
        for pfx in C.BIAS_HBT_PREFIXES:
            self.assertEqual([x for x in base if x.startswith(pfx)], [x for x in new if x.startswith(pfx)])
        self.assertIn("XQb nc_b nc_a nc_e vss npn13G2 Nx=8", new)  # a blanket Nx=8 sed would hit this

    def test_sizing_matches_run_core_envelope_table(self):
        text = C.RUN_SCRIPT.read_text()
        for vid, row in C.RUN_SCRIPT_ROWS.items():
            self.assertIn(f'"{row}', text, vid)
        s = C.SIZING["s_fixi_a80"]
        self.assertEqual((s["nx"], s["m"], s["xmis_w_um"]), (10, 8, "51.2"))
        # mirror scaled 4096/(Nx*m), the A2 fix-I_C rule
        self.assertAlmostEqual(4096 / (s["nx"] * s["m"]), float(s["xmis_w_um"]))

    def test_edit_refused_when_line_missing(self):
        with self.assertRaises(SystemExit):
            C._replace_line_once("a\nb", "zzz", "y")

    def test_loss_cases_are_separate_bases(self):
        self.assertEqual(list(C.LOSS_CASES), ["ideal", "lc_em", "le_q20", "le_q10", "le_q5"])
        em = C.dut_text("s_ctrl_a8", "lc_em")
        self.assertIn("XLc vdd outn vss " + LVC.LC_EM_INSTANCE, em)
        self.assertIn(LVC.LE_LINE, em)  # Le stays ideal
        for q in (20, 10, 5):
            t = C.dut_text("s_ctrl_a8", f"le_q{q}")
            self.assertIn(f"Rle le_x vss {LVC.le_series_r(q):.5f}", t)
            self.assertIn(LVC.LC_LINE, t)  # Lc stays ideal
        self.assertLess(LVC.le_series_r(20), LVC.le_series_r(10))
        self.assertLess(LVC.le_series_r(10), LVC.le_series_r(5))

    def test_divider_points(self):
        self.assertEqual(len(C.SPLIT_K), 7)
        self.assertEqual(C.divider_ohms(0), (1000, 11000))
        self.assertEqual(sum(1 for k in C.SPLIT_K if k < 0), 3)
        self.assertEqual(sum(1 for k in C.SPLIT_K if k > 0), 3)
        ratios = [C.divider_ohms(k)[1] / C.divider_ohms(k)[0] for k in C.SPLIT_K]
        self.assertEqual(ratios, sorted(ratios))  # k up => R2b/R2a up => vb2 up
        self.assertEqual({sum(C.divider_ohms(k)) for k in C.SPLIT_K}, {12000})
        self.assertTrue(all(C.divider_ohms(k)[0] > 0 for k in C.SPLIT_K))
        base, new = self.changed("s_ctrl_a8", k=0)
        self.assertEqual(base, new)  # d0 is the committed divider
        base, new = self.changed("s_ctrl_a8", k=-2)
        self.assertEqual({a.split()[0] for a, b in zip(base, new) if a != b}, {"R2a", "R2b"})
        self.assertIn("R2a vdd vb2 1500 m=1", new)


class Requests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.root = Path(cls.tmp.name)
        cls.camp = C.generate("t-camp", "campaign", cls.root)
        cls.gate = C.generate("t-gate", "gate", cls.root)
        cls.man = C.load_manifest(cls.camp)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def reqs(self, kind):
        return [r for r in self.man["requests"] if r["kind"] == kind]

    def load(self, r):
        return json.loads((self.camp / r["request"]).read_text())

    def test_counts(self):
        self.assertEqual(len(self.reqs("grid")), 2 * 5 * 4)
        self.assertEqual(len(self.reqs("split")), 2 * 7 * 3)
        self.assertEqual(len(self.man["requests"]), 82)

    def test_grid_is_exact_45_cell_box_with_skew_corners(self):
        want = {(l, t, v) for l in ("typ", "bcs", "wcs", "sf", "fs") for t in (-40, 27, 125)
                for v in (1.62, 1.8, 1.98)}
        self.assertEqual(len(want), 45)
        for r in self.reqs("grid"):
            req = self.load(r)
            got = {(a, int(b), c) for a, b, c in C.expand_request_cells(req)}
            self.assertEqual(got, want, r["stem"])
            self.assertNotIn("exclude", req)
        names = {p["name"]: p["sections"] for p in self.load(self.reqs("grid")[0])["corners"]["process"]}
        self.assertEqual(names["sf"][0]["section"], "hbt_typ")
        self.assertEqual(names["sf"][1]["section"], "mos_sf")
        self.assertEqual(names["fs"][1]["section"], "mos_fs")
        self.assertEqual(names["bcs"][0]["section"], "hbt_bcs")
        self.assertEqual(names["wcs"][1]["section"], "mos_ss")

    def test_split_is_exactly_the_three_hot_cells(self):
        for r in self.reqs("split"):
            cells = sorted(C.expand_request_cells(self.load(r)))
            self.assertEqual(cells, sorted(((c[0], float(c[1]), c[2]) for c in C.HOT_CELLS)), r["stem"])
            self.assertEqual(len(cells), 3)
        pts = {r["divider_k"] for r in self.reqs("split")}
        self.assertEqual(pts, set(C.SPLIT_K))

    def test_analyses_and_measurements(self):
        for r in self.reqs("grid"):
            self.assertEqual(self.load(r)["analysis"]["kind"], {"op": "op", "noise": "noise"}.get(r["analysis"], "sp"))
        by = {(r["case"], r["analysis"]) for r in self.man["requests"]}
        for sz in C.SIZING:
            for loss in C.LOSS_CASES:
                for an in C.GRID_ANALYSES:
                    self.assertIn((f"grid__{sz}__{loss}", an), by)
        op = {m["name"] for m in C.measurements("op")}
        self.assertTrue({"ic1", "ic2", "vce1", "vce2", "vbc1", "vbc2", "idd", "pdc"} <= op)
        sp = {m["name"] for m in C.measurements("sp_band")}
        self.assertTrue({"nfmin_sp_db_worst", "cin_ff_mid", "s21_db_min"} <= sp)
        nz = {m["name"] for m in C.measurements("noise")}
        self.assertEqual(sum(n.startswith("nf290_db_f") for n in nz), 11)

    def test_netlists_carry_bench_and_edit_markers(self):
        t = (self.camp / "split__s_fixi_a80__dm3__op.spice").read_text()
        self.assertIn("R2a/R2b = 1750/10250", t)
        self.assertIn("Nx=10 m=8", t)
        self.assertIn(".options gmin=1e-10 tnom=27", t)
        self.assertIn("design/netlist/lna.spice sha256 " + C.sha256_file(C.DESIGN_NETLIST), t)
        n = (self.camp / "grid__s_ctrl_a8__ideal__noise.spice").read_text()
        self.assertIn("Rs vin nfin 50 noisy=0", n)
        self.assertFalse([ln for ln in n.splitlines() if ln.startswith("* VARIANT EDIT")])  # control verbatim
        em = (self.camp / "grid__s_ctrl_a8__lc_em__sp_band.spice").read_text()
        self.assertIn('.include "', em)

    def test_provenance_and_snapshot_integrity(self):
        self.assertEqual(self.man["status"], "request-set-not-run")
        self.assertEqual(self.man["design_netlist_sha256"], C.sha256_file(C.DESIGN_NETLIST))
        self.assertEqual(C.verify_snapshot(self.camp), [])
        with self.assertRaises(SystemExit):
            C.generate("t-camp", "campaign", self.root)  # append-only
        # tamper detection
        with tempfile.TemporaryDirectory() as d:
            g = C.generate("tamper", "gate", Path(d))
            p = g / "gate__s_fixi_a80__ideal__op.spice"
            p.write_text(p.read_text() + "* edited\n")
            self.assertTrue(any("differs from the manifest" in x for x in C.verify_snapshot(g)))

    def test_gate_is_one_nominal_cell_per_analysis(self):
        gm = C.load_manifest(self.gate)
        self.assertEqual(gm["set"], "gate")
        self.assertEqual(len(gm["requests"]), 5)
        for r in gm["requests"]:
            self.assertEqual(r["expected_cells"], [["typ", 27, 1.8]])
        by_loss = {}
        for r in gm["requests"]:
            by_loss.setdefault(r["loss"], []).append(r["analysis"])
        self.assertEqual(sorted(by_loss["ideal"]), sorted(C.GATE_ANALYSES))
        self.assertEqual(by_loss["lc_em"], ["sp_band"])

    def test_gate_exercises_em_model_include(self):
        nl = self.gate / "gate__s_fixi_a80__lc_em__sp_band.spice"
        inc = [ln for ln in nl.read_text().splitlines() if ln.startswith(".include ")]
        self.assertEqual(len(inc), 1)
        rel = inc[0].split('"')[1]
        self.assertFalse(Path(rel).is_absolute())
        self.assertEqual((self.gate / rel).resolve(), C.EM_MODEL.resolve())

    def test_bad_record_id(self):
        with self.assertRaises(SystemExit):
            C.generate("../x", "gate", self.root)


class GateVerdict(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.snap = C.generate("g", "gate", Path(self.tmp.name))
        self.cd = Path(self.tmp.name) / "corners"

    def tearDown(self):
        self.tmp.cleanup()

    def verdict(self, **kw):
        syn.write_reports(self.snap, self.cd, **{k: v for k, v in kw.items() if k in ("client", "runner")},
                          override=kw.get("override"))
        return C.verify_gate(self.snap, self.cd, "klt 0.7.0+gabc")

    def test_pass_is_plumbing_only(self):
        v = self.verdict(client="0.7.0", runner="0.7.0")
        self.assertTrue(v["pass"], v["problems"])
        self.assertIn("plumbing only", v["scope"])

    def test_runner_client_mismatch_fails(self):
        v = self.verdict(runner="0.6.0")
        self.assertFalse(v["pass"])
        self.assertTrue(any("runner klt" in p for p in v["problems"]))

    def test_nonfinite_fails(self):
        def ov(stem, case, an, cell, vals):
            if an == "noise":
                vals["nf290_db_worst"] = float("nan")
        v = self.verdict(override=ov)
        self.assertFalse(v["pass"])

    def test_missing_report_and_not_batch(self):
        syn.write_reports(self.snap, self.cd)
        (self.cd / "gate__s_fixi_a80__ideal__op.report.json").unlink()
        rep = self.cd / "gate__s_fixi_a80__ideal__noise.report.json"
        d = json.loads(rep.read_text())
        d["environment"] = {}
        rep.write_text(json.dumps(d))
        v = C.verify_gate(self.snap, self.cd, "0.7.0")
        self.assertFalse(v["pass"])
        self.assertTrue(any("no report" in p for p in v["problems"]))
        self.assertTrue(any("not a batch run" in p for p in v["problems"]))

    def test_client_floor(self):
        C.check_client_floor("klt 0.7.0+gabc")
        C.check_client_floor("0.9.1")
        with self.assertRaises(SystemExit):
            C.check_client_floor("klt 0.5.0")
        with self.assertRaises(SystemExit):
            C.check_client_floor("no version")


if __name__ == "__main__":
    unittest.main()
