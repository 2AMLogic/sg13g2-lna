"""Unit tests for gen_spec_envelopes.py (issue #364).

Covers the limit derivation from the ratified rows (mW->W / mA->A scaling,
comparator mapping, exact decimal arithmetic) and every refusal path
(non-ratified row, unit mismatches, already-graded measurement, missing
corner/measurement, append-only out-dir refusals), plus a round-trip:
regenerating the issue-#231 envelope requests from the pinned reference
record is byte-identical to the committed ones. Stdlib only, headless,
PDK-free, single process; the generator only ever writes into a temp dir.

Run from the repo root (single process):

    python3 -I -m unittest discover -s sim/lna-characterization/tests
"""
import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
LNA = HERE.parent
REPO = LNA.parents[1]
SNAPS = LNA / "netlist-snapshots"
REF_RECORD = "20261116-023212-eacd53a"  # pinned reference (matched-DUT benches)
ENV_RECORD = "20261117-054141-bdebb4d"  # committed envelope record
REF = SNAPS / REF_RECORD
ENV = SNAPS / ENV_RECORD
GEN = LNA / "gen_spec_envelopes.py"


def load(name):
    spec = importlib.util.spec_from_file_location(name, LNA / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


G = load("gen_spec_envelopes")


def real_rows():
    return G.load_ratified(REPO)


def real_ref(stem):
    return json.loads((REF / f"{stem}.request.json").read_text(encoding="utf-8"))


class LimitDerivation(unittest.TestCase):
    """limits_for: ratified comparator/limit/unit -> klt sim limits, in SI."""

    def test_power_10mw_scales_to_watts(self):
        self.assertEqual(G.limits_for(real_rows()["power"]),
                         ({"limits": {"max": 0.01}}, "W"))

    def test_ic1_le_uses_max_and_scales_to_amps(self):
        # the <= comparator maps to "max" like <
        self.assertEqual(G.limits_for(real_rows()["ic1"]),
                         ({"limits": {"max": 0.0045}}, "A"))

    def test_db_rows_map_min_and_max_passthrough(self):
        self.assertEqual(G.limits_for(real_rows()["gain"]),
                         ({"limits": {"min": 15.0}}, None))
        self.assertEqual(G.limits_for(real_rows()["s11"]),
                         ({"limits": {"max": -10.0}}, None))

    def test_dimensionless_stability_rows(self):
        self.assertEqual(G.limits_for(real_rows()["mu"]),
                         ({"limits": {"min": 1.0}}, None))
        self.assertEqual(G.limits_for(real_rows()["negres"]),
                         ({"limits": {"max": 1.0}}, None))

    def test_scaling_is_exact_decimal_not_float(self):
        # float(Decimal("4.5")*Decimal("1e-3")) is exactly the double 0.0045;
        # the naive float shortcut drifts: 4.5*1e-3 == 0.0045000000000000005.
        self.assertNotEqual(4.5 * 1e-3, 0.0045)
        self.assertEqual(G.limits_for(real_rows()["ic1"])[1], "A")
        (limits, _) = G.limits_for(real_rows()["ic1"])
        self.assertEqual(limits["limits"]["max"], 0.0045)

    def test_unsupported_comparator_refused(self):
        row = dict(real_rows()["power"], comparator="=")
        with self.assertRaises(SystemExit) as cm:
            G.limits_for(row)
        self.assertIn("unsupported comparator '='", str(cm.exception))


class BuildRequest(unittest.TestCase):
    """build_request: corner-box narrowing and validated limit injection."""

    def test_all_four_stems_inject_validated_limits(self):
        rows = real_rows()
        op = G.build_request(real_ref("matched_op"), rows, "matched_op")
        by = {m["name"]: m for m in op["measurements"]}
        self.assertEqual(by["ic1"]["limits"], {"max": 0.0045})
        self.assertEqual(by["ic1"]["spec_row"], "ic1")
        self.assertEqual(by["pdc"]["limits"], {"max": 0.01})
        self.assertEqual(by["pdc"]["spec_row"], "power")
        band = G.build_request(real_ref("matched_sp_band"), rows, "matched_sp_band")
        by = {m["name"]: m for m in band["measurements"]}
        self.assertEqual(by["s21_db_min"]["limits"], {"min": 15.0})
        self.assertEqual(by["s11_db_worst"]["limits"], {"max": -10.0})
        self.assertEqual(by["s22_db_worst"]["spec_row"], "s22")
        stab = G.build_request(real_ref("matched_sp_stab"), rows, "matched_sp_stab")
        by = {m["name"]: m for m in stab["measurements"]}
        self.assertEqual(by["mu_min"]["limits"], {"min": 1.0})
        self.assertEqual(by["s11_mag_max"]["limits"], {"max": 1.0})
        self.assertEqual(by["s22_mag_max"]["spec_row"], "negres")
        noise = G.build_request(real_ref("matched_noise"), rows, "matched_noise")
        nf = {m["name"]: m for m in noise["measurements"]}["nf290_db_worst"]
        self.assertEqual(nf["limits"], {"max": 1.5})
        self.assertNotIn("spec_row", nf)  # honest limit, deliberately untagged

    def test_corner_box_narrowed_to_ratified_hbt_box(self):
        op = G.build_request(real_ref("matched_op"), real_rows(), "matched_op")
        self.assertEqual([p["name"] for p in op["corners"]["process"]],
                         ["typ", "bcs", "wcs"])
        self.assertEqual(op["corners"]["supply_v"], {"vdd": [1.62, 1.80, 1.98]})
        self.assertEqual(op["corners"]["temperature_c"], [-40, 27, 125])
        # everything outside corners/measurements is copied verbatim
        self.assertEqual(op["analysis"], real_ref("matched_op")["analysis"])
        self.assertEqual(op["netlist"], real_ref("matched_op")["netlist"])

    def test_source_request_is_not_mutated(self):
        ref = real_ref("matched_op")
        G.build_request(ref, real_rows(), "matched_op")
        by = {m["name"]: m for m in ref["measurements"]}
        self.assertNotIn("limits", by["ic1"])
        self.assertNotIn("spec_row", by["pdc"])
        self.assertEqual([p["name"] for p in ref["corners"]["process"]],
                         ["typ", "bcs", "wcs", "sf", "fs"])

    def test_missing_process_corner_refused(self):
        ref = real_ref("matched_op")
        ref["corners"]["process"] = [p for p in ref["corners"]["process"]
                                     if p["name"] != "wcs"]
        with self.assertRaises(SystemExit) as cm:
            G.build_request(ref, real_rows(), "matched_op")
        self.assertIn("lacks ratified process corners: ['wcs']", str(cm.exception))

    def test_not_ratified_row_refused(self):
        rows = real_rows()
        rows["ic1"] = dict(rows["ic1"], status="draft")
        with self.assertRaises(SystemExit) as cm:
            G.build_request(real_ref("matched_op"), rows, "matched_op")
        self.assertIn("row ic1: not ratified, refusing to grade it", str(cm.exception))

    def test_missing_reference_measurement_refused(self):
        ref = real_ref("matched_op")
        ref["measurements"] = [m for m in ref["measurements"] if m["name"] != "pdc"]
        with self.assertRaises(SystemExit) as cm:
            G.build_request(ref, real_rows(), "matched_op")
        self.assertIn("no measurement pdc", str(cm.exception))

    def test_measurement_unit_mismatch_refused(self):
        ref = real_ref("matched_op")
        for m in ref["measurements"]:
            if m["name"] == "pdc":
                m["unit"] = "mW"
        with self.assertRaises(SystemExit) as cm:
            G.build_request(ref, real_rows(), "matched_op")
        self.assertIn("unit 'mW' != expected 'W'", str(cm.exception))

    def test_ratified_unit_scale_mismatch_refused(self):
        # a ratified row whose scaled unit disagrees with the declared
        # measurement unit is refused, not silently graded
        rows = real_rows()
        rows["power"] = dict(rows["power"], unit="mA")
        with self.assertRaises(SystemExit) as cm:
            G.build_request(real_ref("matched_op"), rows, "matched_op")
        self.assertIn("ratified unit mA scales to A, measurement declares W",
                      str(cm.exception))

    def test_already_graded_measurement_refused(self):
        for tag in ("limits", "spec_row"):
            ref = real_ref("matched_op")
            for m in ref["measurements"]:
                if m["name"] == "ic1":
                    m[tag] = {"max": 1} if tag == "limits" else "ic1"
            with self.assertRaises(SystemExit) as cm:
                G.build_request(ref, real_rows(), "matched_op")
            self.assertIn("already graded", str(cm.exception))


def run_gen(out_dir, ref_dir=REF):
    return subprocess.run(
        [sys.executable, "-I", str(GEN), "--ref-dir", str(ref_dir), "--out-dir", str(out_dir)],
        capture_output=True, text=True)


class GeneratorMain(unittest.TestCase):
    """main() end-to-end (subprocess, python3 -I, temp out-dirs only)."""

    def test_writes_fresh_snapshot_into_temp_dir(self):
        with tempfile.TemporaryDirectory(prefix="gen-env-tests-") as tmp:
            out = Path(tmp) / "new-record"
            proc = run_gen(out)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertEqual(proc.stdout.count("wrote "), 4)
            self.assertIn("27 cells per analysis", proc.stdout)
            for stem in G.REQUEST_STEMS:
                # decks are byte-copies of the reference benches
                self.assertEqual((out / f"{stem}.spice").read_bytes(),
                                 (REF / f"{stem}.spice").read_bytes())
                req = json.loads((out / f"{stem}.request.json").read_text(encoding="utf-8"))
                self.assertEqual([p["name"] for p in req["corners"]["process"]],
                                 ["typ", "bcs", "wcs"])

    def test_refuses_out_dir_with_unrelated_entries(self):
        with tempfile.TemporaryDirectory(prefix="gen-env-tests-") as tmp:
            out = Path(tmp) / "occupied"
            out.mkdir()
            (out / "notes.txt").write_text("stray", encoding="utf-8")
            proc = run_gen(out)
            self.assertEqual(proc.returncode, 1)
            self.assertIn("refusing out dir", proc.stderr)
            self.assertIn("append-only", proc.stderr)

    def test_refuses_request_overwrite(self):
        with tempfile.TemporaryDirectory(prefix="gen-env-tests-") as tmp:
            out = Path(tmp) / "has-request"
            out.mkdir()
            (out / "matched_op.request.json").write_text("{}", encoding="utf-8")
            proc = run_gen(out)
            self.assertEqual(proc.returncode, 1)
            self.assertIn("refusing to overwrite", proc.stderr)

    def test_refuses_non_identical_deck(self):
        with tempfile.TemporaryDirectory(prefix="gen-env-tests-") as tmp:
            out = Path(tmp) / "has-deck"
            out.mkdir()
            (out / "matched_op.spice").write_text("* junk deck\n.end\n", encoding="utf-8")
            proc = run_gen(out)
            self.assertEqual(proc.returncode, 1)
            self.assertIn("non-identical deck", proc.stderr)

    def test_regenerated_requests_match_committed_round_trip(self):
        # the committed envelope requests are generated, not hand-edited:
        # regenerating from the pinned reference record reproduces them byte
        # for byte (and the committed decks are the reference benches).
        with tempfile.TemporaryDirectory(prefix="gen-env-roundtrip-") as tmp:
            out = Path(tmp) / "regen"
            proc = run_gen(out)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            for stem in G.REQUEST_STEMS:
                self.assertEqual((out / f"{stem}.request.json").read_bytes(),
                                 (ENV / f"{stem}.request.json").read_bytes(),
                                 f"{stem}.request.json does not round-trip")
                self.assertEqual((ENV / f"{stem}.spice").read_bytes(),
                                 (REF / f"{stem}.spice").read_bytes(),
                                 f"committed {stem}.spice is not the reference bench")


if __name__ == "__main__":
    unittest.main()
