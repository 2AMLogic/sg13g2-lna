"""Tests for the production HBT log parser (issue #144).

Drives sim/hbt-characterization/hbt_parse.sh's hbt_parse_log() and
hbt_classify_cell() -- the exact functions run_hbt_sweep.sh sources -- so
what is tested here is what the runner publishes. The validity-box
constants are read out of run_hbt_sweep.sh itself, not restated.

Covers: strict numeric grammar (valid scientific notation in, malformed
suffixes / empty / missing tokens out), NaN/Inf and overflowing or
underflowing exponents rejected explicitly, the documented missing-fT
sentinels (NA, NaN, empty FT after ngspice's benign out-of-interval measure
failure) still publishing blank fT, the electrothermal-divergence drop,
incomplete / out-of-order blocks, and the cell verdicts (ok / partial /
failed). A replay of every retained ngspice log of both committed records
checks that the strict parser reproduces the committed CSV rows byte for
byte and classifies cells exactly as the records state.

Every test runs under each awk implementation available on the host (awk,
gawk, mawk, busybox awk); missing ones are skipped. Stdlib only, headless,
no ngspice, no PDK, serial; nothing is written under sim/.

Run from the repo root:

    python3 -I -m unittest discover -s sim/hbt-characterization/tests
"""
import csv
import os
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
HBT = HERE.parent
LIB = HBT / "hbt_parse.sh"
AWK_FILE = HBT / "parse_hbt_log.awk"
RUNNER = HBT / "run_hbt_sweep.sh"
CORNERS = HBT / "corners"
RECORDS = HBT / "records"

REC_A = "20260910-200059-7da7038"
REC_B = "20260918-203652-4293920"
N_POINTS = 26
SECTION_OF = {"typ": "hbt_typ", "bcs": "hbt_bcs", "wcs": "hbt_wcs",
              "sf": "hbt_typ", "fs": "hbt_typ"}
CONST_NAMES = ("AE_UNIT_UM2", "IC_LIMIT_PER_NX", "VBE_MIN", "VBE_MAX",
               "VCE_MIN", "VCE_MAX")


def runner_constants():
    text = RUNNER.read_text()
    out = {}
    for name in CONST_NAMES:
        m = re.search(rf'^{name}="([^"]+)"$', text, re.M)
        if m is None:
            raise AssertionError(f"{name} not found in {RUNNER}")
        out[name] = m.group(1)
    return out


CONSTS = runner_constants()
_TMP = tempfile.TemporaryDirectory(prefix="hbt-parse-test-")
TMP = Path(_TMP.name)


def available_awks():
    """(label, command) for every awk implementation on this host."""
    found = []
    seen = set()
    for name in ("awk", "gawk", "mawk"):
        path = shutil.which(name)
        if path is None:
            continue
        real = os.path.realpath(path)
        if real in seen:
            continue
        seen.add(real)
        found.append((name, path))
    bb = shutil.which("busybox")
    if bb is not None:
        probe = subprocess.run([bb, "awk", "BEGIN{print 1}"],
                               capture_output=True, text=True)
        if probe.returncode == 0:
            # busybox dispatches on argv[0]: a symlink named awk is its awk.
            d = TMP / "busybox-bin"
            d.mkdir(exist_ok=True)
            link = d / "awk"
            if not link.exists():
                link.symlink_to(bb)
            found.append(("busybox", str(link)))
    return found


AWKS = available_awks()


def parse(log_text_or_path, awk_cmd, point_id="p", corner="typ", temp="27",
          nx="1", vce="1.0"):
    """Run hbt_parse_log; return (rows, rejects) as lists of field lists."""
    if isinstance(log_text_or_path, Path):
        log = log_text_or_path
    else:
        log = TMP / "fixture.log"
        log.write_text(log_text_or_path)
    rejects = TMP / "rejects.txt"
    rejects.write_text("")
    env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "LC_ALL": "C",
           "HBT_AWK": awk_cmd, **CONSTS}
    proc = subprocess.run(
        ["bash", "--noprofile", "--norc", "-c",
         'source "$1"; shift; hbt_parse_log "$@"', "bash", str(LIB),
         str(log), point_id, corner, SECTION_OF.get(corner, "hbt_typ"),
         temp, nx, vce, str(rejects)],
        capture_output=True, text=True, env=env)
    if proc.returncode != 0:
        raise AssertionError(f"parser exited {proc.returncode}: {proc.stderr}")
    if proc.stderr:
        raise AssertionError(f"parser wrote to stderr: {proc.stderr}")
    rows = [line.split(",") for line in proc.stdout.splitlines()]
    rej = [line.split(",") for line in rejects.read_text().splitlines()]
    return rows, rej


def classify(emitted, n_points, n_diverged, n_malformed, rc, end_marker):
    proc = subprocess.run(
        ["bash", "--noprofile", "--norc", "-c",
         'source "$1"; shift; hbt_classify_cell "$@"', "bash", str(LIB),
         str(emitted), str(n_points), str(n_diverged), str(n_malformed),
         str(rc), str(end_marker)],
        capture_output=True, text=True, check=True)
    return proc.stdout.strip()


def block(pt="0.9", ic="1e-3", ft="2.5E+11", gain="10.5", nf="2.25",
          pre_ft=""):
    """One PT/IC/FT/GAIN/NF echo block; None omits the token entirely."""
    def line(key, tok):
        return f"{key}\n" if tok is None else f"{key} {tok}\n"
    return (line("PT", pt) + line("IC", ic) + pre_ft + line("FT", ft)
            + line("GAIN", gain) + line("NF", nf))


OUT_OF_INTERVAL = ("Error: measure  ftmeas  when(WHEN) : out of interval\n"
                   "Error: &ftmeas: no such variable.\n"
                   " meas ac ftmeas when h21db=0 failed!\n\n")
DIVERGE = ("Error: Transient op failed, timestep too small\n"
           "Error: The operating point could not be simulated successfully.\n")


class PerAwk(unittest.TestCase):
    """Base: run each test body once per available awk implementation."""

    def each_awk(self):
        if not AWKS:
            self.skipTest("no awk implementation found")
        for label, cmd in AWKS:
            with self.subTest(awk=label):
                yield cmd


class TestValidNumbers(PerAwk):
    def test_scientific_notation_and_plain_forms_publish(self):
        cases = [
            # (ic, ft, gain, nf) as ngspice might echo them
            ("3.06035E-10", "2.70056E+11", "-33.6903", "38.611"),
            ("1e-3", "4.16e11", "+10", "1."),
            (".0015", "1E11", "0", "0.5e1"),
            ("0.00113218", "NA", "28.4958", "1.85275"),
        ]
        for cmd in self.each_awk():
            for ic, ft, gain, nf in cases:
                rows, rej = parse(block(ic=ic, ft=ft, gain=gain, nf=nf), cmd)
                self.assertEqual(rej, [])
                self.assertEqual(len(rows), 1)
                r = rows[0]
                self.assertEqual(len(r), 13)
                self.assertEqual(r[7], f"{float(ic):.6e}")
                self.assertEqual(r[10], f"{float(gain):.6f}")
                self.assertEqual(r[11], f"{float(nf):.6f}")
                self.assertEqual(r[9], "" if ft == "NA" else ft)

    def test_row_values_hand_computed(self):
        # Ic = 4.608 mA at Nx=4: J_C = 4.608e-3 * 1000 / (4 * 0.1152)
        # = 10.0 mA/um^2; Ic >= 0.003*4 is false; Vbe 0.97 > 0.96 -> vbe_high;
        # Vce 0.3 < 0.4 -> vce_low.
        self.assertEqual(CONSTS["AE_UNIT_UM2"], "0.1152")
        for cmd in self.each_awk():
            rows, rej = parse(block(pt="0.97", ic="4.608e-3", ft="3.1E+11",
                                    gain="12.5", nf="1.75"),
                              cmd, point_id="nx4_wcs_125c_vce0.3v",
                              corner="wcs", temp="125", nx="4", vce="0.3")
            self.assertEqual(rej, [])
            self.assertEqual(rows, [[
                "nx4_wcs_125c_vce0.3v", "wcs", "hbt_wcs", "125", "4", "0.3",
                "0.97", "4.608000e-03", "10.000000", "3.1E+11", "12.500000",
                "1.750000", "vbe_high;vce_low"]])

    def test_ic_high_and_vbe_low_flags(self):
        for cmd in self.each_awk():
            rows, _ = parse(block(pt="0.6", ic="0.003"), cmd)
            self.assertEqual(rows[0][12], "ic_high;vbe_low")
            rows, _ = parse(block(pt="0.65", ic="0.0029"), cmd)
            self.assertEqual(rows[0][12], "")


class TestMalformedTokens(PerAwk):
    def test_issue_reproduction_publishes_nothing(self):
        # The issue's synthetic reproduction: before #144 this produced a row
        # of zeros. Now it is rejected with a named reason.
        text = "PT 0.8\nIC broken\nFT NA\nGAIN broken\nNF broken\n"
        for cmd in self.each_awk():
            rows, rej = parse(text, cmd)
            self.assertEqual(rows, [])
            self.assertEqual(rej, [["p", "0.8", "malformed_ic"]])

    def test_each_key_malformed(self):
        bad = ["broken", "1.5broken", "1e", "1e-3x", "0x1A", "1,5", "--1",
               "1.2.3", "e5", "+", ".", "1e+", "12V", "1 e5"]
        for cmd in self.each_awk():
            for key in ("pt", "ic", "ft", "gain", "nf"):
                for tok in bad:
                    with self.subTest(key=key, tok=tok):
                        rows, rej = parse(block(**{key: tok}), cmd)
                        self.assertEqual(rows, [])
                        self.assertEqual(len(rej), 1)
                        reason = rej[0][-1]
                        if tok == "1 e5":
                            self.assertEqual(reason, f"extra_tokens_{key}")
                        else:
                            self.assertEqual(reason, f"malformed_{key}")

    def test_empty_and_missing_tokens(self):
        for cmd in self.each_awk():
            for key in ("pt", "ic", "gain", "nf"):
                # "KEY " (empty value) and "KEY" (no separator at all)
                for tok in ("", None):
                    with self.subTest(key=key, tok=tok):
                        rows, rej = parse(block(**{key: tok}), cmd)
                        self.assertEqual(rows, [])
                        self.assertEqual(rej[0][-1], f"missing_{key}")

    def test_nonfinite_spellings(self):
        for cmd in self.each_awk():
            for key in ("pt", "ic", "gain", "nf"):
                for tok in ("nan", "NaN", "-nan", "inf", "-Inf", "+INF",
                            "Infinity", "-infinity"):
                    with self.subTest(key=key, tok=tok):
                        rows, rej = parse(block(**{key: tok}), cmd)
                        self.assertEqual(rows, [])
                        self.assertEqual(rej[0][-1], f"nonfinite_{key}")
            for tok in ("inf", "-Inf", "Infinity"):
                rows, rej = parse(block(ft=tok), cmd)
                self.assertEqual(rows, [])
                self.assertEqual(rej[0][-1], "nonfinite_ft")

    def test_overflow_and_underflow_exponents(self):
        for cmd in self.each_awk():
            for key in ("pt", "ic", "ft", "gain", "nf"):
                for tok in ("1e999", "-1e400", "9.9e308", "1e301",
                            "1e-999", "-5e-400"):
                    with self.subTest(key=key, tok=tok):
                        rows, rej = parse(block(**{key: tok}), cmd)
                        self.assertEqual(rows, [])
                        self.assertEqual(rej[0][-1], f"out_of_range_{key}")
            # A literal zero is a valid number, not an underflow.
            for tok in ("0", "0.0", "0e5", "0.000e-12"):
                rows, rej = parse(block(gain=tok), cmd)
                self.assertEqual(rej, [])
                self.assertEqual(rows[0][10], "0.000000")

    def test_extra_tokens(self):
        for cmd in self.each_awk():
            rows, rej = parse(block(nf="1.5 dB"), cmd)
            self.assertEqual(rows, [])
            self.assertEqual(rej[0][-1], "extra_tokens_nf")


class TestMissingFt(PerAwk):
    def test_na_and_nan_sentinels_publish_blank_ft(self):
        for cmd in self.each_awk():
            for tok in ("NA", "NaN", "nan"):
                rows, rej = parse(block(ft=tok, gain="-33.5", nf="38.25"), cmd)
                self.assertEqual(rej, [])
                self.assertEqual(rows[0][9], "")
                self.assertEqual(rows[0][10:12], ["-33.500000", "38.250000"])

    def test_empty_ft_after_out_of_interval_is_benign(self):
        for cmd in self.each_awk():
            for ft in ("", None):
                rows, rej = parse(block(ft=ft, pre_ft=OUT_OF_INTERVAL), cmd)
                self.assertEqual(rej, [])
                self.assertEqual(rows[0][9], "")
                self.assertEqual(rows[0][10:12], ["10.500000", "2.250000"])

    def test_empty_ft_without_measure_failure_is_rejected(self):
        for cmd in self.each_awk():
            rows, rej = parse(block(ft=""), cmd)
            self.assertEqual(rows, [])
            self.assertEqual(rej[0][-1], "missing_ft")

    def test_measure_failure_does_not_leak_into_next_block(self):
        text = block(pt="0.55", ft="", pre_ft=OUT_OF_INTERVAL) + block(pt="0.57", ft="")
        for cmd in self.each_awk():
            rows, rej = parse(text, cmd)
            self.assertEqual([r[6] for r in rows], ["0.55"])
            self.assertEqual(rej, [["p", "0.57", "missing_ft"]])


class TestDivergenceAndIncomplete(PerAwk):
    def test_divergent_block_dropped_even_with_stale_numbers(self):
        text = (block(pt="1.01") + "PT 1.03\nIC 0.00113218\n" + DIVERGE
                + "FT 2.70056E+11\nGAIN 28.4958\nNF 1.85275\n")
        for cmd in self.each_awk():
            rows, rej = parse(text, cmd)
            self.assertEqual([r[6] for r in rows], ["1.01"])
            self.assertEqual(rej, [["p", "1.03", "diverged"]])

    def test_divergence_takes_precedence_over_malformed_tokens(self):
        text = ("PT 1.05\nIC 0.0769813\nAC operating point failed -\nFT \n"
                "GAIN \nNOISE operating point failed -\nNF \n")
        for cmd in self.each_awk():
            rows, rej = parse(text, cmd)
            self.assertEqual(rows, [])
            self.assertEqual(rej, [["p", "1.05", "diverged"]])

    def test_divergence_marker_resets_per_block(self):
        text = "PT 0.9\n" + DIVERGE + "IC 1\nFT NA\nGAIN 1\nNF 1\n" + block(pt="0.92")
        for cmd in self.each_awk():
            rows, rej = parse(text, cmd)
            self.assertEqual([r[6] for r in rows], ["0.92"])
            self.assertEqual(rej, [["p", "0.9", "diverged"]])

    def test_incomplete_block_before_next_pt_and_at_eof(self):
        text = ("PT 0.55\nIC 1e-9\nFT NA\n" + block(pt="0.57")
                + "PT 0.59\nIC 1e-9\n")
        for cmd in self.each_awk():
            rows, rej = parse(text, cmd)
            self.assertEqual([r[6] for r in rows], ["0.57"])
            self.assertEqual(rej, [["p", "0.55", "incomplete_block"],
                                   ["p", "0.59", "incomplete_block"]])

    def test_incomplete_divergent_block_at_eof_is_divergence(self):
        text = block(pt="1.01") + "PT 1.03\nIC 0.05\n" + DIVERGE
        for cmd in self.each_awk():
            rows, rej = parse(text, cmd)
            self.assertEqual(len(rows), 1)
            self.assertEqual(rej, [["p", "1.03", "diverged"]])

    def test_out_of_order_duplicate_and_orphan_lines(self):
        for cmd in self.each_awk():
            rows, rej = parse("PT 0.9\nIC 1e-3\nIC 2e-3\nFT NA\nGAIN 1\nNF 1\n", cmd)
            self.assertEqual(rows, [])
            self.assertEqual(rej[0][-1], "unexpected_ic")
            rows, rej = parse("PT 0.9\nIC 1e-3\nGAIN 1\nFT NA\nNF 1\n", cmd)
            self.assertEqual(rows, [])
            self.assertEqual(rej[0][-1], "unexpected_gain")
            rows, rej = parse(block(pt="0.9") + "NF 3\n", cmd)
            self.assertEqual(len(rows), 1)
            self.assertEqual(rej, [["p", "0.9", "orphan_nf"]])
            rows, rej = parse("IC 1e-3\n" + block(pt="0.9"), cmd)
            self.assertEqual(len(rows), 1)
            self.assertEqual(rej, [["p", "", "orphan_ic"]])

    def test_ngspice_chatter_is_ignored(self):
        text = ("Doing analysis at TEMP = -40.000000 and TNOM = 27.000000\n"
                "Using SPARSE 1.3 as Direct Linear Solver\n"
                "No. of Data Rows : 130\n  PT not a key\nPTX 1\nNFmin 3\n"
                + block())
        for cmd in self.each_awk():
            rows, rej = parse(text, cmd)
            self.assertEqual(len(rows), 1)
            self.assertEqual(rej, [])


class TestClassification(unittest.TestCase):
    def test_verdicts(self):
        self.assertEqual(classify(26, 26, 0, 0, 0, 1), "ok")
        self.assertEqual(classify(24, 26, 2, 0, 1, 0), "partial")
        self.assertTrue(classify(25, 26, 0, 1, 0, 1).startswith("failed:1 malformed"))
        # A malformed block FAILS the cell even when divergence also occurred.
        self.assertTrue(classify(23, 26, 2, 1, 1, 0).startswith("failed:1 malformed"))
        self.assertEqual(classify(0, 26, 26, 0, 1, 0), "failed:every bias point diverged")
        self.assertTrue(classify(26, 26, 0, 0, 1, 1).startswith("failed:"))
        self.assertTrue(classify(26, 26, 0, 0, 0, 0).startswith("failed:"))
        self.assertTrue(classify(24, 26, 1, 0, 0, 1).startswith("failed:only 24"))

    def test_end_to_end_cell_with_malformed_block_fails(self):
        if not AWKS:
            self.skipTest("no awk")
        text = "".join(block(pt=f"{0.55 + 0.02 * i:.2f}") for i in range(25))
        text += "PT 1.05\nIC broken\nFT NA\nGAIN 1\nNF 1\n"
        for label, cmd in AWKS:
            with self.subTest(awk=label):
                rows, rej = parse(text, cmd)
                n_div = sum(r[-1] == "diverged" for r in rej)
                verdict = classify(len(rows), N_POINTS, n_div,
                                   len(rej) - n_div, 0, 1)
                self.assertEqual(len(rows), 25)
                self.assertTrue(verdict.startswith("failed:1 malformed"), verdict)


class TestRunnerUsesSharedParser(unittest.TestCase):
    def test_runner_sources_library_and_has_no_inline_parser(self):
        text = RUNNER.read_text()
        self.assertIn('source "${SCRIPT_DIR}/hbt_parse.sh"', text)
        self.assertIn("hbt_parse_log ", text)
        self.assertIn("hbt_classify_cell ", text)
        self.assertNotIn("bad_number", text)
        self.assertNotRegex(text, r"/\^NF /")

    def test_library_passes_every_awk_variable(self):
        awk_src = AWK_FILE.read_text()
        lib = LIB.read_text()
        passed = set(re.findall(r"-v (\w+)=", lib))
        needed = {"point_id", "corner", "section", "temp", "nx", "vce", "ae",
                  "iclim", "vbemin", "vbemax", "vcemin", "vcemax", "rejects"}
        self.assertEqual(passed, needed)
        for v in needed:
            self.assertRegex(awk_src, rf"\b{v}\b")
        self.assertIn('-f "${HBT_PARSE_AWK}"', lib)


def committed_rows(record):
    with open(RECORDS / f"{record}.csv", newline="") as f:
        rows = list(csv.reader(f))
    return rows[0], rows[1:]


def cell_args(log):
    m = re.fullmatch(r"nx(\d+)_(\w+?)_(-?\d+)c_vce([0-9.]+)v\.log", log.name)
    if m is None:
        raise AssertionError(f"unexpected log name {log.name}")
    nx, corner, temp, vce = m.groups()
    return dict(point_id=log.name[:-4], corner=corner, temp=temp, nx=nx, vce=vce)


class TestRetainedLogReplay(unittest.TestCase):
    """The strict parser reproduces every committed row from retained logs."""

    def replay(self, record, ncols):
        header, committed = committed_rows(record)
        self.assertEqual(len(header), ncols)
        logs = sorted((CORNERS / record).glob("*.log"))
        self.assertGreater(len(logs), 0)
        md = (RECORDS / f"{record}.md").read_text()
        partials = set()
        for label, cmd in AWKS:
            with self.subTest(awk=label):
                got, partial, failed = [], [], []
                for log in logs:
                    a = cell_args(log)
                    rows, rej = parse(log, cmd, **a)
                    reasons = {r[-1] for r in rej}
                    self.assertLessEqual(reasons, {"diverged"},
                                         f"{log.name}: {rej}")
                    n_div = len(rej)
                    end = int("Simulation executed from .control section"
                              in log.read_text(errors="replace"))
                    verdict = classify(len(rows), N_POINTS, n_div, 0,
                                       0 if end else 1, end)
                    if verdict == "partial":
                        partial.append(f"{a['point_id']}:{len(rows)}/{N_POINTS}")
                    elif verdict != "ok":
                        failed.append(a["point_id"])
                    got.extend(r[:ncols] for r in rows)
                self.assertEqual(sorted(got), sorted(committed))
                self.assertEqual(failed, [])
                partials.add(tuple(partial))
        self.assertEqual(len(partials), 1, partials)
        return list(partials.pop()), md

    def test_record_b_full_schema(self):
        if not AWKS:
            self.skipTest("no awk")
        partial, md = self.replay(REC_B, 13)
        self.assertEqual(partial, ["nx8_bcs_-40c_vce1.4v:24/26"])
        self.assertIn("nx8_bcs_-40c_vce1.4v:24/26", md)
        self.assertIn("- **Failed cells**: none.", md)

    def test_record_a_original_schema(self):
        if not AWKS:
            self.skipTest("no awk")
        partial, _ = self.replay(REC_A, 12)
        self.assertEqual(partial, [])


if __name__ == "__main__":
    unittest.main()
