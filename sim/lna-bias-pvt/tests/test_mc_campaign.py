"""Unit tests for mc_campaign.py (issue #90): request generation and the
fleet-report reducer.

Stdlib only, headless, no ngspice, no PDK, no klt, no network. Reports are
synthesized inline (they are fixtures, never evidence) and written to temp
dirs; nothing writes under sim/.

Run from the repo root:

    python3 -I -m unittest discover -s sim/lna-bias-pvt/tests
"""
import importlib.util
import json
import math
import random
import shutil
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
BIAS = HERE.parent

_spec = importlib.util.spec_from_file_location("mc_campaign", BIAS / "mc_campaign.py")
mc = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(mc)


def sample_values(rng, mismatch=True):
    if mismatch:
        a = {k: (1 + 0.1 * rng.gauss(0, 1)) for k in
             ("q1_area", "q2_area", "q3_area", "qa_area", "qb_area", "qc_area")}
        d = {k: 0.002 * rng.gauss(0, 1) for k in
             ("mnp1_delvto", "mnp2_delvto", "mis_delvto", "mref_delvto")}
    else:
        a = {k: 1.0 for k in ("q1_area", "q2_area", "q3_area", "qa_area", "qb_area", "qc_area")}
        d = {k: 0.0 for k in ("mnp1_delvto", "mnp2_delvto", "mis_delvto", "mref_delvto")}
    ic1 = 0.0039403 * a["q1_area"] / a["q3_area"]
    idd = ic1 + 0.000774
    dv = d["mis_delvto"]
    v = {"ic1": ic1, "ic2": ic1 * 0.998, "ic3": 0.000506174 * (1 + dv), "ib1": ic1 / 725.6,
         "vb1": 0.843494 + dv, "vbref": 0.845286 + dv, "vdd_node": 1.8, "idd": idd,
         "pdc": 1.8 * idd}
    v.update(a)
    v.update(d)
    return v


BENCH_SHA = mc.sha256_bytes(mc.bench_netlist().encode())


def report(n, mismatch=True, seed=1, job="klt-sim-x", state="done", mutate=None):
    rng = random.Random(seed)
    process = "typ_mismatch" if mismatch else "typ"
    corners = []
    for i in range(n):
        vals = sample_values(rng, mismatch)
        corners.append({
            "corner_id": f"{process}/1.800V/27C/mc{i}", "status": "pass",
            "process": process, "supply_v": {"vdd": 1.8}, "temperature_c": 27,
            "monte_carlo": {"sample_index": i, "seed": 1000 + i, "process_seed": 1,
                            "mismatch_seed": 2000 + i},
            "measurements": [{"name": k, "value": vals[k]} for k in mc.ALL_MEAS],
            "diagnostics": []})
    rep = {"schema_version": 3, "status": "pass", "corners": corners,
           "environment": {"engine_version": "ngspice-46", "netlist_sha256": BENCH_SHA,
                           "corner_section_libs": [{"name": "cornerHBT.lib"},
                                                   {"name": "cornerMOShv.lib"}],
                           "monte_carlo": {"n": n, "seed": mc.SEED, "vary": "mismatch"},
                           "remote": {"provider": "aws-batch-fleet", "job_id": job,
                                      "state": state, "runner_klt_version": "0.7.0",
                                      "client_klt_version": "0.7.0",
                                      "runner_compatibility": "match"}}}
    if mutate:
        mutate(rep)
    return rep


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.snap = mc.generate("t", self.tmp / "snap")
        # Stand-in for `validate` output: digest of the fixture's 1000+i seed sequence.
        (self.snap / "request-validation.json").write_text(json.dumps({
            "problems": [], "requests": {
                stem: {"rndseed_sha256": mc.sha256_bytes(
                    ",".join(str(1000 + i) for i in range(r["n"])).encode())}
                for stem, r in mc.load_manifest(self.snap)["requests"].items()}}))
        self.corners = self.tmp / "corners"
        self.corners.mkdir()
        self.out = self.tmp / "out"

    def write(self, run, rep):
        (self.corners / f"{run}.report.json").write_text(json.dumps(rep))

    def write_all(self, main=None, replay=None, neg=None):
        self.write("mc_mismatch", main or report(mc.N_MAIN))
        self.write("mc_mismatch_replay", replay or report(mc.N_MAIN, job="klt-sim-y"))
        self.write("negctl_nominal", neg or report(mc.N_NEGCTL, mismatch=False, job="klt-sim-z"))

    def reduce(self):
        rc = mc.reduce(self.snap, self.corners, self.out, "t")
        return rc, json.loads((self.out / "t-mc-summary.json").read_text())


class TestGen(Base):
    def test_requests(self):
        m = mc.load_manifest(self.snap)
        self.assertEqual(m["requests"]["mc_mismatch"]["n"], 200)
        r = json.loads((self.snap / "mc_mismatch.request.json").read_text())
        self.assertEqual(r["monte_carlo"]["seed"], 68001)
        self.assertEqual(r["backend"], "batch")
        self.assertTrue(r["options"]["stage_model_inputs"])
        secs = [s["section"] for s in r["corners"]["process"][0]["sections"]]
        self.assertEqual(secs, ["hbt_typ_mismatch", "mos_tt_mismatch"])
        n = json.loads((self.snap / "negctl_nominal.request.json").read_text())
        self.assertEqual([s["section"] for s in n["corners"]["process"][0]["sections"]],
                         ["hbt_typ", "mos_tt"])
        self.assertEqual(r["corners"]["supply_v"], {"vdd": [1.8]})
        self.assertEqual(r["corners"]["temperature_c"], [27])

    def test_bench_is_full_dut(self):
        b = (self.snap / "bench_mc.spice").read_text()
        self.assertIn(".subckt lna vdd vss rfin rfout", b)
        self.assertIn("\nVdd vdd 0 dc 1.8\n", b)
        self.assertIn("Xdut vdd vss rfin rfout lna", b)
        self.assertNotIn("\n.end\n", b)
        for line in mc.DESIGN_NETLIST.read_text().splitlines():
            if line and not line.startswith("*") and line != ".end":
                self.assertIn(line, b)
        pdc = [m for m in mc.measurements() if m["name"] == "pdc"][0]
        self.assertEqual(pdc["expr"], "v(vdd)*(-i(vdd))")

    def test_append_only_and_hash_drift(self):
        with self.assertRaises(SystemExit):
            mc.generate("t", self.tmp / "snap")
        self.assertEqual(mc.verify_snapshot(self.snap), [])
        p = self.snap / "mc_mismatch.request.json"
        p.write_text(p.read_text() + " ")
        self.assertTrue(mc.verify_snapshot(self.snap))


class TestReduce(Base):
    def test_good_campaign(self):
        self.write_all()
        rc, s = self.reduce()
        self.assertEqual(rc, 0)
        self.assertTrue(s["complete"], s["problems"])
        self.assertTrue(s["replay"]["pass"])
        self.assertTrue(s["negative_control"]["pass"])
        self.assertTrue(s["variation"]["pass"], s["variation"])
        self.assertTrue(s["controls_pass"])
        self.assertEqual(s["variation"]["zero_spread_quantities"], ["vdd_node"])
        csv_text = (self.out / "t-mc-samples.csv").read_text().splitlines()
        self.assertEqual(len(csv_text), 1 + mc.N_MAIN)

    def test_missing_samples_stay_visible(self):
        def drop(rep):
            del rep["corners"][5]
        self.write_all(main=report(mc.N_MAIN, mutate=drop))
        rc, s = self.reduce()
        self.assertEqual(rc, 0)  # structurally a fleet report; the gap is a counted failure
        main = s["runs"]["mc_mismatch"]["summary"]
        self.assertEqual(main["failures"].get("missing"), 1)
        self.assertEqual(main["samples_ok"], mc.N_MAIN - 1)
        self.assertFalse(s["replay"]["pass"])
        row = (self.out / "t-mc-samples.csv").read_text().splitlines()[6]
        self.assertIn("missing", row)

    def test_nonfinite_and_nonconvergence(self):
        def bad(rep):
            rep["corners"][3]["measurements"][0]["value"] = float("nan")
            rep["corners"][4]["status"] = "error"
            rep["corners"][4]["diagnostics"] = [{"code": "nonconvergence", "severity": "error"}]
            rep["corners"][7]["measurements"][7]["value"] = None
        self.write_all(main=report(mc.N_MAIN, mutate=bad))
        rc, s = self.reduce()
        main = s["runs"]["mc_mismatch"]["summary"]
        self.assertEqual(main["failures"]["failed_nonfinite_ic1"], 1)
        self.assertEqual(main["failures"]["failed_error"], 1)
        self.assertEqual(main["failures"]["failed_missing_idd"], 1)
        self.assertEqual(main["diagnostic_counts"], {"nonconvergence": 1})
        self.assertEqual(main["excluded_value_counts"]["ic1"]["n_nonfinite"], 1)
        self.assertEqual(main["excluded_value_counts"]["idd"]["n_missing"], 1)
        self.assertEqual(main["stats"]["ic1"]["n_nonfinite"], 0)
        self.assertEqual(main["stats"]["ic1"]["n_finite"], mc.N_MAIN - 3)
        self.assertEqual(main["samples_ok"], mc.N_MAIN - 3)
        # allow_nan=False: the summary is strict JSON even with NaN inputs
        json.loads((self.out / "t-mc-summary.json").read_text())

    def test_threshold_equality(self):
        def edge(rep):
            m = {x["name"]: x for x in rep["corners"][0]["measurements"]}
            m["ic1"]["value"] = mc.I_C1_BAR_A        # equal: not an exceedance
            m["pdc"]["value"] = mc.P_DC_BAR_W        # equal: counts (bar is strict <)
            m = {x["name"]: x for x in rep["corners"][1]["measurements"]}
            m["ic1"]["value"] = mc.I_C1_BAR_A * 1.0001
            m["pdc"]["value"] = 0.001
        self.write_all(main=report(mc.N_MAIN, mutate=edge))
        _, s = self.reduce()
        main = s["runs"]["mc_mismatch"]["summary"]
        self.assertEqual(main["count_ic1_eq_bar"], 1)
        self.assertEqual(main["count_pdc_eq_bar"], 1)
        ic1 = [r for r in self._rows() if r["sample_index"] in ("0", "1")]
        self.assertEqual(ic1[0]["ic1_gt_4p5mA"], "0")
        self.assertEqual(ic1[0]["pdc_ge_10mW"], "1")
        self.assertEqual(ic1[1]["ic1_gt_4p5mA"], "1")

    def _rows(self):
        import csv
        with open(self.out / "t-mc-samples.csv") as f:
            return list(csv.DictReader(f))

    def test_zero_spread_main_is_not_variation(self):
        self.write_all(main=report(mc.N_MAIN, mismatch=False),
                       replay=report(mc.N_MAIN, mismatch=False, job="y"))
        _, s = self.reduce()
        self.assertFalse(s["variation"]["all_sampled_params_vary"])
        self.assertFalse(s["variation"]["pass"])
        self.assertFalse(s["controls_pass"])
        self.assertEqual(s["runs"]["mc_mismatch"]["summary"]["stats"]["ic1"]["stdev"], 0.0)

    def test_unexplained_zero_spread_fails_variation(self):
        def freeze(rep):
            for c in rep["corners"]:
                for m in c["measurements"]:
                    if m["name"] == "ic3":
                        m["value"] = 5e-4
        self.write_all(main=report(mc.N_MAIN, mutate=freeze),
                       replay=report(mc.N_MAIN, job="y", mutate=freeze))
        _, s = self.reduce()
        self.assertIn("ic3", s["variation"]["zero_spread_quantities"])
        self.assertTrue(s["variation"]["zero_spread_explanations"]["ic3"].startswith("UNEXPLAINED"))
        self.assertFalse(s["variation"]["pass"])

    def test_negative_control_that_varies_fails(self):
        def nominal_id(rep):
            for c in rep["corners"]:
                c["process"] = "typ"
                c["corner_id"] = c["corner_id"].replace("typ_mismatch", "typ")
        self.write_all(neg=report(mc.N_NEGCTL, mismatch=True, job="z", mutate=nominal_id))
        _, s = self.reduce()
        self.assertFalse(s["negative_control"]["pass"])
        self.assertFalse(s["controls_pass"])

    def test_negative_control_disagreeing_with_reference_fails(self):
        def shift(rep):
            for c in rep["corners"]:
                for m in c["measurements"]:
                    if m["name"] in ("ic1", "idd"):
                        m["value"] *= 1.01
                    elif m["name"] == "pdc":
                        m["value"] = 1.8 * next(x["value"] for x in c["measurements"]
                                                if x["name"] == "idd")
        self.write_all(neg=report(mc.N_NEGCTL, mismatch=False, job="z", mutate=shift))
        _, s = self.reduce()
        nc = s["negative_control"]
        self.assertTrue(nc["collapsed"])
        self.assertFalse(nc["deterministic_reference"]["agrees"])
        self.assertFalse(nc["pass"])
        self.assertFalse(s["controls_pass"])

    def test_replay_divergence_fails(self):
        self.write_all(replay=report(mc.N_MAIN, seed=2, job="y"))
        _, s = self.reduce()
        self.assertFalse(s["replay"]["pass"])
        self.assertGreater(s["replay"]["n_mismatches"], 0)

    def test_errored_sample_with_finite_values_is_excluded_from_stats(self):
        def err(rep):
            rep["corners"][1]["status"] = "error"
            for m in rep["corners"][1]["measurements"]:
                if m["name"] == "ic1":
                    m["value"] = 1.0
        self.write_all(main=report(mc.N_MAIN, mutate=err))
        _, s = self.reduce()
        main = s["runs"]["mc_mismatch"]["summary"]
        self.assertEqual(main["failures"], {"failed_error": 1})
        self.assertEqual(main["samples_ok"], mc.N_MAIN - 1)
        self.assertEqual(main["stats"]["ic1"]["n_finite"], mc.N_MAIN - 1)
        self.assertLess(main["stats"]["ic1"]["max"], 1.0)
        self.assertEqual(main["excluded_value_counts"]["ic1"]["n_finite"], 1)

    def test_limit_fail_with_valid_values_stays_usable(self):
        def lim(rep):
            rep["corners"][2]["status"] = "fail"
        self.write_all(main=report(mc.N_MAIN, mutate=lim))
        _, s = self.reduce()
        main = s["runs"]["mc_mismatch"]["summary"]
        self.assertEqual(main["samples_ok"], mc.N_MAIN)
        self.assertEqual(main["stats"]["ic1"]["n_finite"], mc.N_MAIN)

    def _seed_case(self, mutate, needle):
        self.write_all(replay=report(mc.N_MAIN, job="y", mutate=mutate),
                       main=report(mc.N_MAIN, mutate=mutate))
        rc, s = self.reduce()
        self.assertEqual(rc, 2)
        self.assertFalse(s["complete"])
        self.assertFalse(s["controls_pass"])
        self.assertTrue(any(needle in p for p in s["problems"]), s["problems"])

    def test_missing_seeds_rejected_even_if_replay_agrees(self):
        def drop(rep):
            for c in rep["corners"]:
                del c["monte_carlo"]["seed"]
        self._seed_case(drop, "missing or non-integer monte_carlo.seed")

    def test_repeated_seeds_rejected(self):
        def rep(r):
            for c in r["corners"]:
                c["monte_carlo"]["seed"] = 1000
        self._seed_case(rep, "repeated monte_carlo.seed")

    def test_wrong_seed_sequence_rejected_even_if_replay_agrees(self):
        def shift(rep):
            for c in rep["corners"]:
                c["monte_carlo"]["seed"] += 7
        self._seed_case(shift, "seed sequence sha256")

    def test_permuted_seed_sequence_rejected(self):
        def swap(rep):
            a, b = rep["corners"][0]["monte_carlo"], rep["corners"][1]["monte_carlo"]
            a["seed"], b["seed"] = b["seed"], a["seed"]
        self._seed_case(swap, "seed sequence sha256")

    def _gap_case(self, mutate):
        self.write_all(replay=report(mc.N_MAIN, job="y", mutate=mutate),
                       main=report(mc.N_MAIN, mutate=mutate))
        rc, s = self.reduce()
        self.assertFalse(s["seed_sequences_verified"])
        self.assertFalse(s["runs"]["mc_mismatch"]["seed_sequence_verified"])
        self.assertFalse(s["controls_pass"])
        return rc, s

    def test_matching_gap_with_wrong_seeds_cannot_pass_controls(self):
        def gap_wrong(rep):
            del rep["corners"][3]
            for c in rep["corners"]:
                c["monte_carlo"]["seed"] += 7
        self._gap_case(gap_wrong)

    def test_matching_gap_with_correct_seeds_cannot_pass_controls(self):
        def gap(rep):
            del rep["corners"][3]
        rc, s = self._gap_case(gap)
        self.assertEqual(rc, 0)  # gap stays a counted failure; only the controls verdict fails

    def test_missing_validation_record_rejected(self):
        self.write_all()
        (self.snap / "request-validation.json").unlink()
        rc, s = self.reduce()
        self.assertEqual(rc, 2)
        self.assertTrue(any("request-validation.json unusable" in p for p in s["problems"]))

    def test_null_corners_fails_cleanly(self):
        self.write_all()
        self.write("mc_mismatch", {"schema_version": 3, "corners": None})
        rc, s = self.reduce()
        self.assertEqual(rc, 2)
        self.assertFalse(s["complete"])
        self.assertTrue(any("no corners[]" in p for p in s["problems"]))
        self.assertTrue((self.out / "t-mc-summary.md").is_file())

    def test_non_object_corner_and_fields_fail_cleanly(self):
        for bad, needle in (
                (lambda r: r["corners"].__setitem__(3, "x"), "corners[3] is not an object"),
                (lambda r: r["corners"][2].__setitem__("monte_carlo", "s"), "monte_carlo is not an object"),
                (lambda r: r.__setitem__("environment", []), "environment is not an object"),
                (lambda r: r["environment"].__setitem__("remote", "r"), "environment.remote")):
            with self.subTest(needle=needle):
                self.write_all(main=report(mc.N_MAIN, mutate=bad))
                rc, s = self.reduce()
                self.assertEqual(rc, 2)
                self.assertFalse(s["complete"])
                self.assertTrue(any(needle in p for p in s["problems"]), s["problems"])

    def test_wrong_dut_hash_is_rejected(self):
        def bad(rep):
            rep["environment"]["netlist_sha256"] = "0" * 64
        self.write_all(main=report(mc.N_MAIN, mutate=bad))
        rc, s = self.reduce()
        self.assertEqual(rc, 2)
        self.assertFalse(s["complete"])
        self.assertTrue(any("netlist_sha256" in p for p in s["problems"]))

    def test_wrong_corner_identity_is_rejected(self):
        def bad(rep):
            for i, c in enumerate(rep["corners"]):
                c["corner_id"] = f"wrong_process/1.200V/125C/mc{i}"
                c["process"], c["supply_v"], c["temperature_c"] = "wrong_process", {"vdd": 1.2}, 125
        self.write_all(main=report(mc.N_MAIN, mutate=bad))
        rc, s = self.reduce()
        self.assertEqual(rc, 2)
        self.assertFalse(s["controls_pass"])
        self.assertTrue(any("process 'wrong_process'" in p for p in s["problems"]))
        self.assertTrue(any("temperature_c 125" in p for p in s["problems"]))

    def test_missing_provenance_and_wrong_section_libs_rejected(self):
        def bad(rep):
            del rep["corners"][0]["process"]
            rep["environment"]["corner_section_libs"] = [{"name": "cornerHBT.lib"}]
        self.write_all(main=report(mc.N_MAIN, mutate=bad))
        rc, s = self.reduce()
        self.assertEqual(rc, 2)
        self.assertTrue(any("missing process" in p for p in s["problems"]))
        self.assertTrue(any("corner_section_libs" in p for p in s["problems"]))

    def test_not_fleet_evidence(self):
        def local(rep):
            del rep["environment"]["remote"]
        self.write_all(main=report(mc.N_MAIN, mutate=local))
        rc, s = self.reduce()
        self.assertEqual(rc, 2)
        self.assertFalse(s["complete"])

    def test_failed_job_and_missing_report(self):
        self.write("mc_mismatch", report(mc.N_MAIN, state="failed"))
        rc, s = self.reduce()
        self.assertEqual(rc, 2)
        self.assertTrue(any("state 'failed'" in p for p in s["problems"]))
        self.assertTrue(any("missing_report" in p for p in s["problems"]))

    def test_error_envelope(self):
        self.write_all()
        self.write("negctl_nominal", {"schema_version": 1, "error": {"command": "sim", "message": "boom"}})
        rc, s = self.reduce()
        self.assertEqual(rc, 2)
        self.assertTrue(any("boom" in p for p in s["problems"]))


class TestStats(unittest.TestCase):
    def test_stats(self):
        st = mc.stats([1.0, 2.0, None, float("inf")])
        self.assertEqual((st["n_finite"], st["n_missing"], st["n_nonfinite"]), (2, 1, 1))
        self.assertAlmostEqual(st["stdev"], math.sqrt(0.5))
        self.assertIsNone(mc.stats([1.0])["stdev"])
        self.assertTrue(mc.stats([3.0, 3.0])["zero_spread"])
        self.assertIsNone(mc.stats([])["mean"])


if __name__ == "__main__":
    unittest.main()
