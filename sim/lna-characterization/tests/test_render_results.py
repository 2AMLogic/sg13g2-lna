"""Tests for render_results.py (issue #141).

Stdlib only, headless, no ngspice/PDK. Fixtures are synthetic scratch trees
built in a temp dir (hand-computed expectations); the committed record is only
READ by the regression/drift tests. Nothing here writes under sim/.

    python3 -I -m unittest discover -s sim/lna-characterization/tests
"""
import contextlib
import importlib.util
import io
import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
LNA = HERE.parent
ROOT = LNA.parent.parent


def _load(name):
    spec = importlib.util.spec_from_file_location(name, LNA / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


rr = _load("render_results")
psw = _load("parse_lna_sweep")
GRID = psw.expected_grid(rr.STAB_GRID)
PIDS = sorted(rr.expected_point_ids())
NOM = "sp_typ_27c_vdd1.80v"

BASE_RAW = {"k": 3.0, "mu": 1.1, "delta": 0.5, "s11": 0.5, "s22": 0.9}


def csv_defaults(pid):
    c, t, v = rr.expected_point_ids()[pid]
    return {
        "point_id": pid, "corner_label": c, "temp_c": t, "vdd_v": v,
        "ic1_a": "0.004", "pdc_w": "0.008", "s11_db_worst": "-12.0",
        "s21_db_min": "16.0", "s21_db_max": "17.0", "s22_db_worst": "-12.0",
        "k_inband_min": "3.0", "mu_inband_min": "1.1",
        "nfmin_sp_db_at_band_lo": "1.0", "nf290_db_worst": "1.2",
        "nf290_db_at_band_lo": "1.2", "nf290_db_at_band_mid": "1.1",
        "nf290_db_at_band_hi": "1.0", "iip3_dbm_a2mv": "1.0",
    }


def build_tree(root, raw_ov=None, csv_ov=None):
    """Synthetic repo tree. raw_ov[pid][name] = (row_index, value) overrides one
    raw broadband sample; csv_ov[pid][col] overrides a summary column. The
    summary's broadband columns are derived from the raw table (consistent)."""
    raw_ov, csv_ov = raw_ov or {}, csv_ov or {}
    root = Path(root)
    (root / "spec").mkdir(parents=True)
    (root / "measurements").mkdir()
    for rel in ("spec/target-spec.md", "spec/ratified-rows.json"):
        shutil.copy(ROOT / rel, root / rel)
    dat_dir = root / rr.DAT_DIR.format(rec=rr.RECORD_ID)
    dat_dir.mkdir(parents=True)
    (root / "sim/lna-characterization/records").mkdir(parents=True)
    rows = []
    for pid in PIDS:
        vals = {n: [v] * len(GRID) for n, v in BASE_RAW.items()}
        for name, (idx, val) in raw_ov.get(pid, {}).items():
            vals[name][idx] = val
        with open(dat_dir / f"{pid}.stability.dat", "w") as fh:
            for i, f in enumerate(GRID):
                cols = []
                for n in ("k", "mu", "delta", "s11", None, "s22"):
                    cols += [f, vals[n][i] if n else 0.0]
                fh.write(" " + "  ".join(f"{x:.8e}" for x in cols) + " \n")
        r = csv_defaults(pid)
        r.update({
            "k_broadband_min": repr(min(vals["k"])), "mu_broadband_min": repr(min(vals["mu"])),
            "mag_delta_broadband_max": repr(max(vals["delta"])),
            "s11_mag_broadband_max": repr(max(vals["s11"])),
            "s22_mag_broadband_max": repr(max(vals["s22"])),
        })
        r.update(csv_ov.get(pid, {}))
        rows.append(r)
    write_csv(root, rows)
    readme = f"# x\n\n{rr.BEGIN}\n\nstale\n\n{rr.END}\n\ntail\n"
    (root / rr.README).write_text(readme, encoding="utf-8")
    return root


def write_csv(root, rows, cols=None):
    cols = list(cols or rr.CSV_COLS)
    p = Path(root) / rr.CSV_PATH.format(rec=rr.RECORD_ID)
    with open(p, "w", encoding="utf-8") as fh:
        fh.write(",".join(cols) + "\n")
        for r in rows:
            fh.write(",".join(str(r[c]) for c in cols) + "\n")


def read_rows(root):
    import csv
    p = Path(root) / rr.CSV_PATH.format(rec=rr.RECORD_ID)
    return list(csv.DictReader(p.read_text().splitlines()))


def run(root, *args):
    err = io.StringIO()
    with contextlib.redirect_stderr(err), contextlib.redirect_stdout(io.StringIO()):
        code = rr.main(["--root", str(root), *args])
    return code, err.getvalue()


def by_id(doc):
    return {r["id"]: r for r in doc["rows"]}


class TmpCase(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.addCleanup(self._td.cleanup)
        self.tmp = Path(self._td.name)

    def tree(self, **kw):
        self._n = getattr(self, "_n", 0) + 1
        return build_tree(self.tmp / f"t{self._n}", **kw)


class TestMapping(TmpCase):
    def test_base_fixture_hand_computed(self):
        doc = rr.build_doc(self.tree())
        g = by_id(doc)
        self.assertEqual(g["gain"]["nominal"]["value"], 16.0)
        self.assertEqual(g["gain"]["nominal"]["band_max"], 17.0)
        self.assertEqual(g["gain"]["tested_cells"], 45)
        self.assertEqual(g["gain"]["failing_cells"], 0)
        self.assertEqual(g["gain"]["numerical_verdict"], "pass")
        self.assertEqual(g["gain"]["coverage_status"], "incomplete")
        self.assertEqual(g["power"]["nominal"]["value"], 8.0)  # 0.008 W -> mW
        self.assertEqual(g["ic1"]["nominal"]["value"], 4.0)
        self.assertEqual(g["supply"]["rails"], [1.62, 1.8, 1.98])
        self.assertEqual(g["supply"]["cells_per_rail"], {"1.62": 15, "1.80": 15, "1.98": 15})
        self.assertAlmostEqual(g["mu"]["worst"]["freq_hz"] / GRID[0], 1.0, places=8)  # first occurrence
        self.assertEqual(doc["nominal_cell"], NOM)

    def test_tie_break_by_point_id_and_directions(self):
        ov = {"sp_wcs_27c_vdd1.62v": {"s21_db_min": "14.0"},
              "sp_bcs_27c_vdd1.98v": {"s21_db_min": "14.0"},
              "sp_typ_125c_vdd1.80v": {"s21_db_min": "20.0"},
              "sp_sf_125c_vdd1.80v": {"s21_db_min": "20.0"}}
        g = by_id(rr.build_doc(self.tree(csv_ov=ov)))
        self.assertEqual(g["gain"]["worst"]["point_id"], "sp_bcs_27c_vdd1.98v")
        self.assertEqual(g["gain"]["best"]["point_id"], "sp_sf_125c_vdd1.80v")
        self.assertEqual(g["gain"]["failing_cells"], 2)
        self.assertEqual(g["gain"]["numerical_verdict"], "fail")

    def test_raw_extrema_and_frequencies(self):
        ov = {"sp_typ_27c_vdd1.80v": {"mu": (7, 0.5), "k": (3, -2.0), "delta": (9, 0.75),
                                      "s11": (11, 0.6), "s22": (13, 1.25)}}
        g = by_id(rr.build_doc(self.tree(raw_ov=ov)))
        nom = g["mu"]["nominal"]
        self.assertEqual((nom["value"], nom["point_id"]), (0.5, NOM))
        self.assertAlmostEqual(nom["freq_hz"] / GRID[7], 1.0, places=8)  # 9 printed digits
        self.assertEqual(g["mu"]["worst"]["point_id"], NOM)
        self.assertAlmostEqual(g["k"]["worst"]["freq_hz"] / GRID[3], 1.0, places=8)
        self.assertEqual(g["delta"]["worst"]["value"], 0.75)
        self.assertEqual(g["negres_s11"]["worst"]["value"], 0.6)
        self.assertAlmostEqual(g["negres_s22"]["worst"]["freq_hz"] / GRID[13], 1.0, places=8)
        self.assertEqual(g["negres_s22"]["failing_cells"], 1)

    def test_classifications(self):
        doc = rr.build_doc(self.tree())
        g = by_id(doc)
        for rid in ("nfmin", "k", "delta", "supply"):
            self.assertEqual(g[rid]["classification"], "context")
            self.assertNotIn("numerical_verdict", g[rid])
        self.assertEqual(g["iip3"]["classification"], "not-ratified")
        self.assertNotIn("numerical_verdict", g["iip3"])
        self.assertTrue(g["iip3"]["advisory_only"])
        self.assertEqual(g["iip3"]["draft_advisory"]["cells_meeting"], 45)
        self.assertEqual(doc["coverage"]["status"], "incomplete")
        for r in doc["rows"]:
            if r["classification"] == "requirement":
                self.assertEqual(r["coverage_status"], "incomplete")
        text = json.dumps(doc).lower()
        self.assertIn("no full-spec compliance", text)
        self.assertNotIn("t1 signoff achieved", text)
        self.assertNotIn("limit", g["nfmin"])  # no spec verdict for NFmin


class TestStrictBoundaries(TmpCase):
    def verdicts(self, csv_ov=None, raw_ov=None):
        g = by_id(rr.build_doc(self.tree(csv_ov=csv_ov, raw_ov=raw_ov)))
        return g

    def at(self, col, value):
        return {NOM: {col: value}}

    def test_equality_fails_strict_and_passes_le(self):
        cases = [("gain", "s21_db_min", "15.0"), ("nf290", "nf290_db_worst", "1.5"),
                 ("s11", "s11_db_worst", "-10.0"), ("s22", "s22_db_worst", "-10.0"),
                 ("power", "pdc_w", "0.01")]
        for rid, col, val in cases:
            extra = {}
            if rid == "nf290":  # keep the 3-sample cross-check consistent
                extra = {"nf290_db_at_band_lo": val}
            g = self.verdicts(csv_ov={NOM: dict({col: val}, **extra)})
            self.assertEqual(g[rid]["failing_cells"], 1, rid)
            self.assertEqual(g[rid]["numerical_verdict"], "fail", rid)
        # <= : equality passes
        g = self.verdicts(csv_ov=self.at("ic1_a", "0.0045"))
        self.assertEqual(g["ic1"]["nominal"]["value"], 4.5)
        self.assertEqual(g["ic1"]["failing_cells"], 0)
        self.assertEqual(g["ic1"]["numerical_verdict"], "pass")
        g = self.verdicts(csv_ov=self.at("ic1_a", "0.0045000001"))
        self.assertEqual(g["ic1"]["failing_cells"], 1)

    def test_raw_unity_boundaries(self):
        g = self.verdicts(raw_ov={NOM: {"mu": (0, 1.0), "s22": (0, 1.0), "s11": (0, 1.0)}})
        self.assertEqual(g["mu"]["failing_cells"], 1)
        self.assertEqual(g["negres_s22"]["failing_cells"], 1)
        self.assertEqual(g["negres_s11"]["failing_cells"], 1)
        g = self.verdicts(raw_ov={NOM: {"mu": (0, 1.00000002), "s22": (0, 0.99999998)}})
        self.assertEqual(g["mu"]["failing_cells"], 0)
        self.assertEqual(g["negres_s22"]["failing_cells"], 0)

    def test_printed_rounding_does_not_decide(self):
        # raw 1.00000018 prints as 1.000000 in six decimals; it still fails < 1.
        ov = {NOM: {"s22": (5, 1.00000018)}}
        root = self.tree(raw_ov=ov, csv_ov={NOM: {"s22_mag_broadband_max": "1.000000"}})
        rows = rr.build_doc(root)
        self.assertEqual(by_id(rows)["negres_s22"]["failing_cells"], 1)
        self.assertGreater(by_id(rows)["negres_s22"]["worst"]["value"], 1.0)

    def test_iip3_draft_is_advisory(self):
        g = self.verdicts(csv_ov=self.at("iip3_dbm_a2mv", "-0.5"))
        self.assertEqual(g["iip3"]["draft_advisory"]["cells_not_meeting"], 1)
        self.assertNotIn("numerical_verdict", g["iip3"])


class TestInputIntegrity(TmpCase):
    def expect_error(self, root, frag=""):
        with self.assertRaises(rr.RenderError) as cm:
            rr.build_doc(root)
        self.assertIn(frag, str(cm.exception))

    def test_missing_and_duplicate_cells(self):
        root = self.tree()
        rows = read_rows(root)
        write_csv(root, rows[:-1])
        self.expect_error(root, "missing cells")
        write_csv(root, rows + [rows[0]])
        self.expect_error(root, "duplicate point_id")
        bad = dict(rows[0], point_id="sp_zzz_27c_vdd1.80v")
        write_csv(root, rows[1:] + [bad])
        self.expect_error(root, "unexpected point_id")

    def test_nominal_absent(self):
        root = self.tree()
        write_csv(root, [r for r in read_rows(root) if r["point_id"] != NOM])
        self.expect_error(root, "missing cells")

    def test_missing_column(self):
        root = self.tree()
        rows = read_rows(root)
        write_csv(root, rows, cols=[c for c in rr.CSV_COLS if c != "pdc_w"])
        self.expect_error(root, "missing columns")

    def test_nonfinite_and_malformed_values(self):
        for val, frag in (("nan", "non-finite"), ("inf", "non-finite"), ("abc", "malformed"), ("", "empty")):
            root = build_tree(self.tmp / f"v{abs(hash(val))}", csv_ov={NOM: {"pdc_w": val}})
            self.expect_error(root, frag)

    def test_disagreeing_point_id_columns(self):
        root = self.tree()
        rows = read_rows(root)
        rows[0]["vdd_v"] = "1.99"
        write_csv(root, rows)
        self.expect_error(root, "disagree with the point_id")

    def test_raw_files_missing_extra_and_malformed(self):
        root = self.tree()
        d = root / rr.DAT_DIR.format(rec=rr.RECORD_ID)
        f = d / f"{NOM}.stability.dat"
        orig = f.read_text()
        f.unlink()
        self.expect_error(root, "missing stability tables")
        (d / "sp_extra_27c_vdd1.80v.stability.dat").write_text(orig)
        f.write_text(orig)
        self.expect_error(root, "unexpected stability tables")
        (d / "sp_extra_27c_vdd1.80v.stability.dat").unlink()
        f.write_text("".join(orig.splitlines(True)[:-1]))  # 139 rows
        self.expect_error(root, "frequency points")
        f.write_text("".join(orig.splitlines(True)[:5] + orig.splitlines(True)[6:]))
        self.expect_error(root, NOM)
        f.write_text(orig.replace("1.00000000e+07", "1.00000000e+08", 1))
        self.expect_error(root, NOM)
        f.write_text(orig.replace("1.10000000e+00", "nan", 1))
        self.expect_error(root, "non-")
        f.write_text(orig.replace("1.10000000e+00", "x", 1))
        self.expect_error(root, "non-numeric")
        f.write_text(orig.splitlines()[0] + "\n" + "\n".join(
            " ".join(l.split()[:11]) for l in orig.splitlines()[1:]) + "\n")
        self.expect_error(root, "columns")

    def test_stale_summary_vs_raw(self):
        root = self.tree(csv_ov={NOM: {"mu_broadband_min": "1.05"}})
        self.expect_error(root, "stale or mismatched")
        root = build_tree(self.tmp / "nf", csv_ov={NOM: {"nf290_db_worst": "1.9"}})
        self.expect_error(root, "three sampled frequencies")

    def test_unreadable_record(self):
        root = self.tree()
        shutil.rmtree(root / rr.DAT_DIR.format(rec=rr.RECORD_ID))
        self.expect_error(root, "unreadable")


class TestSpecTranscription(TmpCase):
    def mutate_spec(self, old, new, count=1):
        root = self.tree()
        p = root / rr.SPEC
        t = p.read_text(encoding="utf-8")
        self.assertIn(old, t)
        p.write_text(t.replace(old, new, count), encoding="utf-8")
        return root

    def mutate_json(self, fn):
        root = self.tree()
        p = root / rr.RATIFIED
        d = json.loads(p.read_text(encoding="utf-8"))
        fn(d["rows"])
        p.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
        return root

    def fails(self, root, frag=""):
        with self.assertRaises(rr.RenderError) as cm:
            rr.load_ratified(root)
        self.assertIn(frag, str(cm.exception))

    def test_committed_transcription_validates(self):
        self.assertEqual(set(rr.load_ratified(ROOT)),
                         {"gain", "nf", "s11", "s22", "mu", "negres", "iip3", "supply", "power", "ic1"})

    def test_mutated_spec_values_fail(self):
        for old, new in (("**> 15 dB**", "**> 14 dB**"), ("**< 1.5 dB**", "**> 1.5 dB**"),
                         ("**< 10 mW**", "**< 10 W**"), ("**μ > 1 (Edwards–Sinsky)**", "**μ > 2 (Edwards–Sinsky)**"),
                         ("**1.80 V ± 10 %**", "**1.80 V ± 5 %**")):
            with self.subTest(old=old):
                self.fails(self.mutate_spec(old, new), "does not state")

    def test_mutated_negres_and_ic1_text_fail(self):
        self.fails(self.mutate_spec("max \\|S22\\| < 1 with", "max \\|S22\\| < 2 with"), "negres")
        self.fails(self.mutate_spec("`I_C ≤ 4.5 mA` over corners", "`I_C ≤ 5.5 mA` over corners"), "ic1")

    def test_mutated_status_fails(self):
        self.fails(self.mutate_spec("**Gain (S21)** — RATIFIED", "**Gain (S21)** — NOT RATIFIED"), "status")
        self.fails(self.mutate_spec("**IIP3** — numeric target **NOT RATIFIED**",
                                    "**IIP3** — numeric target RATIFIED"), "status")

    def test_missing_and_duplicate_spec_rows(self):
        root = self.tree()
        p = root / rr.SPEC
        lines = p.read_text(encoding="utf-8").splitlines(True)
        i = next(n for n, l in enumerate(lines) if l.startswith("| **Gain (S21)**"))
        p.write_text("".join(lines[:i] + lines[i + 1:]), encoding="utf-8")
        self.fails(root, "matches 0 spec rows")
        p.write_text("".join(lines[:i] + [lines[i]] + lines[i:]), encoding="utf-8")
        self.fails(root, "matches 2 spec rows")

    def test_mutated_json_fails(self):
        def lim(rows):
            next(r for r in rows if r["id"] == "gain")["limit"] = "14"
        def cmpr(rows):
            next(r for r in rows if r["id"] == "nf")["comparator"] = "≤"
        def unit(rows):
            next(r for r in rows if r["id"] == "power")["unit"] = "W"
        def status(rows):
            next(r for r in rows if r["id"] == "iip3")["status"] = "ratified"
        def dup(rows):
            rows.append(dict(rows[0]))
        def missing_key(rows):
            del rows[0]["template"]
        for fn in (lim, cmpr, unit, status, dup, missing_key):
            with self.subTest(fn=fn.__name__):
                self.fails(self.mutate_json(fn))

    def test_numbers_elsewhere_in_prose_do_not_satisfy(self):
        # Gain value cell no longer states the limit up front, but "> 15 dB"
        # still appears in the evidence prose of the same row.
        root = self.mutate_spec("| **> 15 dB** (", "| **> 16 dB** (")
        t = (root / rr.SPEC).read_text(encoding="utf-8")
        self.assertIn("0.58 dB below the 15 dB bar", t)
        self.fails(root, "does not state")


class TestRenderAndDrift(TmpCase):
    def test_double_regeneration_is_byte_identical(self):
        root = self.tree()
        outs = []
        for n in (1, 2):
            md, js = self.tmp / f"o{n}.md", self.tmp / f"o{n}.json"
            self.assertEqual(run(root, "--out-md", str(md), "--out-json", str(js))[0], 0)
            outs.append((md.read_bytes(), js.read_bytes()))
        self.assertEqual(outs[0], outs[1])
        doc = json.loads(outs[0][1])
        self.assertNotIn("timestamp", json.dumps(doc).lower())
        self.assertEqual(list(doc["inputs"]["stability_tables"]), PIDS)
        self.assertTrue(all(len(v["sha256"]) == 64 for v in doc["inputs"]["stability_tables"].values()))

    def test_update_then_check_then_mutations(self):
        root = self.tree()
        self.assertEqual(run(root, "--update")[0], 0)
        self.assertEqual(run(root, "--check")[0], 0)
        readme = root / rr.README
        js = root / rr.VERDICTS
        a, b = readme.read_text(encoding="utf-8"), js.read_text(encoding="utf-8")
        self.assertTrue(a.startswith("# x\n") and a.endswith("tail\n"))
        # check is read-only
        self.assertEqual((readme.read_text(encoding="utf-8"), js.read_text(encoding="utf-8")), (a, b))

        def mutated(path, old, new):
            orig = path.read_text(encoding="utf-8")
            self.assertIn(old, orig)
            path.write_text(orig.replace(old, new, 1), encoding="utf-8")
            code, err = run(root, "--check")
            path.write_text(orig, encoding="utf-8")
            return code, err

        code, err = mutated(readme, "16.00 … 17.00 dB", "16.01 … 17.00 dB")
        self.assertEqual(code, 1)
        self.assertIn("README", err)
        code, err = mutated(js, '"numerical_verdict": "pass"', '"numerical_verdict": "fail"')
        self.assertEqual(code, 1)
        self.assertIn("results-verdicts.json", err)
        code, _ = mutated(js, '"incomplete"', '"complete"')
        self.assertEqual(code, 1)
        # stale input: change a raw table / summary value without regenerating
        dat = root / rr.DAT_DIR.format(rec=rr.RECORD_ID) / f"{NOM}.stability.dat"
        code, _ = mutated(dat, "1.10000000e+00", "1.20000000e+00")
        self.assertNotEqual(code, 0)
        csvp = root / rr.CSV_PATH.format(rec=rr.RECORD_ID)
        code, _ = mutated(csvp, "0.008", "0.009")
        self.assertEqual(code, 1)
        # spec mutation breaks the check as well
        code, _ = mutated(root / rr.SPEC, "**> 15 dB**", "**> 14 dB**")
        self.assertEqual(code, 2)
        # a fully restored tree is fresh again
        self.assertEqual(run(root, "--check")[0], 0)

    def test_corrupt_input_never_writes(self):
        root = self.tree(csv_ov={NOM: {"pdc_w": "nan"}})
        before = (root / rr.README).read_text(encoding="utf-8")
        self.assertEqual(run(root, "--update")[0], 2)
        self.assertEqual((root / rr.README).read_text(encoding="utf-8"), before)
        self.assertFalse((root / rr.VERDICTS).exists())

    def test_markers_required(self):
        root = self.tree()
        (root / rr.README).write_text("no markers\n", encoding="utf-8")
        self.assertEqual(run(root, "--update")[0], 2)

    def test_out_md_requires_out_json(self):
        with self.assertRaises(SystemExit):
            run(self.tree(), "--out-md", str(self.tmp / "x.md"))


class TestCommittedRecord(unittest.TestCase):
    """Read-only regression on the committed record (no writes anywhere)."""

    @classmethod
    def setUpClass(cls):
        cls.doc = rr.build_doc(ROOT)
        cls.g = by_id(cls.doc)

    def test_documented_residues_from_raw_tables(self):
        self.assertEqual(self.g["mu"]["failing_cells"], 45)
        self.assertEqual(self.g["negres_s22"]["failing_cells"], 45)
        self.assertEqual(self.g["negres_s11"]["failing_cells"], 0)
        self.assertEqual(self.g["mu"]["inband_context"]["cells_not_above_1"], 0)
        self.assertAlmostEqual(self.g["negres_s22"]["worst"]["value"], 1.00000018, places=8)
        self.assertAlmostEqual(self.g["mu"]["worst"]["value"], 0.99999592, places=8)
        self.assertEqual(self.g["mu"]["worst"]["cell"], "bcs/−40 °C/1.98 V")
        self.assertEqual(self.g["power"]["failing_cells"], 0)
        self.assertEqual(self.g["ic1"]["failing_cells"], 0)
        self.assertEqual(self.g["iip3"]["draft_advisory"]["cells_meeting"], 2)
        self.assertEqual(self.g["supply"]["rails"], [1.62, 1.8, 1.98])
        self.assertEqual(self.doc["grid"]["cells"], 45)

    def test_rounded_summary_conceals_what_raw_shows(self):
        import csv
        with open(ROOT / rr.CSV_PATH.format(rec=rr.RECORD_ID), encoding="utf-8") as fh:
            rows = list(csv.DictReader(fh))
        printed_not_above_1 = [r for r in rows if not float(r["s22_mag_broadband_max"]) > 1.0]
        self.assertGreater(len(printed_not_above_1), 0)  # rounded column hides it
        self.assertEqual(self.g["negres_s22"]["failing_cells"], 45)

    def test_committed_outputs_are_fresh_and_read_only(self):
        before = {p: (ROOT / p).read_bytes() for p in (rr.README, rr.VERDICTS)}
        self.assertEqual(run(ROOT, "--check")[0], 0)
        self.assertEqual(before, {p: (ROOT / p).read_bytes() for p in (rr.README, rr.VERDICTS)})

    def test_selected_record_is_explicit(self):
        self.assertEqual(self.doc["record_id"], "20260926-122301-088c734")
        self.assertEqual(self.doc["inputs"]["summary_csv"]["path"],
                         "sim/lna-characterization/records/20260926-122301-088c734-summary.csv")


if __name__ == "__main__":
    unittest.main()
