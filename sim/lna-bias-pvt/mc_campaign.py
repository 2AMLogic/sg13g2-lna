#!/usr/bin/env python3
"""Full-DUT DC mismatch campaign: request generator, validator, reducer (issue #90).

Three subcommands, none of which launches a simulation itself:

  gen       Write the bench netlist (circuit body), the two `klt sim` request
            files and a provenance manifest under netlist-snapshots/<record-id>/.
            Stdlib only. Refuses to write into an existing directory.
  validate  Check those requests against the INSTALLED klt's own request
            validators (imported from the klt CLI's interpreter -- run this
            file with that interpreter, see run_mc_campaign.sh) and record what
            was checked. A request the installed klt would reject is never
            submitted. Exit 3 if klt cannot be imported (nothing validated).
  reduce    Read the three fleet reports (main, same-request replay, nominal
            negative control) and write the per-sample CSV plus the summary
            JSON/Markdown. Stdlib only. Exit 0 = structurally complete fleet
            evidence (the control verdicts are fields of the summary, never a
            reason to hide it); exit 2 = incomplete, malformed or not fleet
            evidence (nothing should be published).

The DUT is the committed design/netlist/lna.spice, inlined with the same
convention as testbench/tb_lna_biasop.spice.tmpl (xschem's `**.subckt` /
`**.ends` markers uncommented, trailing `.end` dropped, no device line edited),
so I_C1, the total supply current I_DD and P_dc = VDD * I_DD describe one DUT.

Requests (both single-corner: typ / 27 C / 1.80 V, Monte Carlo fan-out only):

  mc_mismatch     cornerHBT.lib hbt_typ_mismatch + cornerMOShv.lib
                  mos_tt_mismatch, n=200, seed=68001, vary=mismatch.
                  Submitted twice: the second submission is the replay.
  negctl_nominal  cornerHBT.lib hbt_typ + cornerMOShv.lib mos_tt (no AGAUSS
                  terms), n=20, the same seed and vary. The per-sample ngspice
                  seed still changes, so this is a repeated-sample run with
                  mismatch disabled: every observable must collapse to one
                  value. It is not the replay.

Why `vary` is not used as the control: klt's `vary` pins the per-axis seed
labels, but the single `.options seed=` it writes (rndseed) is derived from
both labels, and SG13G2's mismatch terms draw from that one global ngspice
RNG. With a *_mismatch section loaded, `vary: "process"` would still change
every AGAUSS draw. Disabling the mismatch sections is the only control that
actually removes the stochastic terms.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import math
import re
import statistics
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SIM_DIR = HERE.parent
REPO = SIM_DIR.parent
DESIGN_NETLIST = REPO / "design" / "netlist" / "lna.spice"
PDK_JSON = SIM_DIR / "pdk.json"

SCHEMA = "lna-bias-mc-campaign/1"
SUMMARY_SCHEMA = "lna-bias-mc-summary/1"
RECORD_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
ISSUE = 90

# --- campaign constants (issue #90 scope) ------------------------------------
SEED = 68001
N_MAIN = 200
N_NEGCTL = 20
TEMP_C = 27
VDD_V = 1.80
I_C1_BAR_A = 4.5e-3     # DR-0001: I_C1 <= 4.5 mA; a sample EXCEEDS when I_C1 > bar
P_DC_BAR_W = 10e-3      # target-spec Power row: P_dc < 10 mW; EXCEEDS when P_dc >= bar
HBT_LIB = "libs.tech/ngspice/models/cornerHBT.lib"
MOS_LIB = "libs.tech/ngspice/models/cornerMOShv.lib"
OSDI_FILES = ("psp103.osdi", "psp103_nqs.osdi", "mosvar.osdi")

REQUESTS = {
    # stem: (process name, hbt section, mos section, n)
    "mc_mismatch": ("typ_mismatch", "hbt_typ_mismatch", "mos_tt_mismatch", N_MAIN),
    "negctl_nominal": ("typ", "hbt_typ", "mos_tt", N_NEGCTL),
}
# report file stem -> request stem it was produced from
RUNS = {
    "mc_mismatch": "mc_mismatch",
    "mc_mismatch_replay": "mc_mismatch",
    "negctl_nominal": "negctl_nominal",
}

# --- observables -------------------------------------------------------------
# (name, ngspice expression, unit). The DUT instance is Xdut, as in
# tb_lna_biasop.spice.tmpl; supply source is Vdd so klt's `alter vdd=` hits it.
OBSERVABLES = [
    ("ic1", "@q.xdut.xq1.qnpn13g2[ic]", "A"),
    ("ic2", "@q.xdut.xq2.qnpn13g2[ic]", "A"),
    ("ic3", "@q.xdut.xq3.qnpn13g2[ic]", "A"),
    ("ib1", "@q.xdut.xq1.qnpn13g2[ib]", "A"),
    ("vb1", "v(xdut.b1)", "V"),
    ("vbref", "v(xdut.bref)", "V"),
    ("vdd_node", "v(vdd)", "V"),
    ("idd", "-i(vdd)", "A"),
    ("pdc", "v(vdd)*(-i(vdd))", "W"),
]
# Sampled model parameters read back from the instantiated devices. In the
# nominal sections area=1 and delvto=0 by construction (no AGAUSS term).
SAMPLED_PARAMS = [
    ("q1_area", "@q.xdut.xq1.qnpn13g2[area]", "1"),
    ("q2_area", "@q.xdut.xq2.qnpn13g2[area]", "1"),
    ("q3_area", "@q.xdut.xq3.qnpn13g2[area]", "1"),
    ("qa_area", "@q.xdut.xqa.qnpn13g2[area]", "1"),
    ("qb_area", "@q.xdut.xqb.qnpn13g2[area]", "1"),
    ("qc_area", "@q.xdut.xqc.qnpn13g2[area]", "1"),
    ("mnp1_delvto", "@n.xdut.xmnp1.nsg13_hv_nmos[delvto]", "V"),
    ("mnp2_delvto", "@n.xdut.xmnp2.nsg13_hv_nmos[delvto]", "V"),
    ("mis_delvto", "@n.xdut.xmis.nsg13_hv_pmos[delvto]", "V"),
    ("mref_delvto", "@n.xdut.xmref.nsg13_hv_pmos[delvto]", "V"),
]
# Expected one-sigma of each sampled parameter under the *_mismatch sections,
# read from the pinned PDK's model text (informational comparison only):
#   npn13G2:  area = agauss(1, 0.1, 1)                         -> 0.1 (not Nx-scaled)
#   hv nmos:  delvto = agauss(0, 0.007/sqrt(m*l*w*1e12), 1)    (l = 1 um)
#   hv pmos:  delvto = agauss(0, 0.0045/sqrt(m*l*w*1e12), 1)
EXPECTED_SIGMA = {
    "q1_area": 0.1, "q2_area": 0.1, "q3_area": 0.1,
    "qa_area": 0.1, "qb_area": 0.1, "qc_area": 0.1,
    "mnp1_delvto": 0.007 / math.sqrt(10.0),     # w=10u
    "mnp2_delvto": 0.007 / math.sqrt(10.0),     # w=10u
    "mis_delvto": 0.0045 / math.sqrt(512.0),    # w=512u
    "mref_delvto": 0.0045 / math.sqrt(40.0),    # w=40u
}
NOMINAL_PARAM = {k: (1.0 if k.endswith("_area") else 0.0) for k, _, _ in SAMPLED_PARAMS}
ALL_MEAS = [n for n, _, _ in OBSERVABLES] + [n for n, _, _ in SAMPLED_PARAMS]

# Replay: identical request, identical image -> identical printed numbers are
# expected; the tolerance only absorbs last-digit formatting.
REPLAY_REL_TOL = 1e-7
REPLAY_ABS_TOL = 1e-15
# Deterministic reference: typ/27C/1.80V op cell of record
# 20260921-173552-2aeafef (same design/netlist/lna.spice sha256, ngspice-46,
# 6 significant digits printed). Informational cross-check of the negative
# control; a different simulator build may move the last digits.
DETERMINISTIC_REF = {
    "record": "20260921-173552-2aeafef",
    "netlist_sha256": "23f9445b01dbec997a2247e40deb6fcaf09b4c2a4a3301c0aae2d37ad27768d1",
    "values": {"ic1": 0.0039403, "ic3": 0.000506174, "ib1": 5.4304e-06,
               "vb1": 0.843494, "vbref": 0.845286, "idd": 0.00471442, "pdc": 0.00848596},
    "rel_tol": 1e-4,
}


def sha256_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def sha256_file(p: Path) -> str:
    return sha256_bytes(Path(p).read_bytes())


# =============================================================================
# gen
# =============================================================================

def dut_subckt(netlist_path: Path = DESIGN_NETLIST) -> str:
    out = []
    for line in Path(netlist_path).read_text().splitlines():
        if line.startswith("**.subckt") or line.startswith("**.ends"):
            line = line[2:]
        elif line == ".end":
            continue
        out.append(line)
    text = "\n".join(out) + "\n"
    if not re.search(r"^\.subckt lna ", text, re.M) or not re.search(r"^\.ends", text, re.M):
        raise SystemExit(f"could not recover '.subckt lna'/.ends from {netlist_path}")
    return text


def bench_netlist(netlist_path: Path = DESIGN_NETLIST) -> str:
    return (
        "* sg13g2-lna full-DUT DC mismatch campaign bench (issue #90)\n"
        "* Generated by sim/lna-bias-pvt/mc_campaign.py gen -- do not edit.\n"
        f"* DUT: design/netlist/lna.spice sha256 {sha256_file(netlist_path)}, inlined\n"
        "*   with tb_lna_biasop.spice.tmpl's convention (no device line altered).\n"
        "* klt sim owns the deck: .options seed, the .lib sections, .temp, the\n"
        "*   pre_osdi lines, `alter vdd=` and the op analysis come from the\n"
        "*   sibling *.request.json. gmin=1e-10 is ngspice's default value, made\n"
        "*   explicit exactly as in tb_lna_biasop.spice.tmpl.\n"
        "* Observables (I_C1, I_DD, P_dc = V(vdd) * I_DD of THIS full DUT) and\n"
        "*   sampled-parameter read-backs are the requests' expr measurements.\n"
        ".options tnom=27 gmin=1e-10\n"
        + dut_subckt(netlist_path)
        + "\nVdd vdd 0 dc 1.8\nVss vss 0 dc 0\nRtin rfin 0 50\nRtout rfout 0 50\n"
        "Xdut vdd vss rfin rfout lna\n"
    )


def measurements() -> list[dict]:
    lim = {"ic1": {"max": I_C1_BAR_A}, "pdc": {"max": P_DC_BAR_W}}
    out = []
    for name, expr, unit in OBSERVABLES + SAMPLED_PARAMS:
        m = {"name": name, "expr": expr, "unit": unit}
        if name in lim:
            m["limits"] = lim[name]
        out.append(m)
    return out


def request(stem: str, netlist_name: str, pdk_root_var: str = "$PDK_ROOT") -> dict:
    pname, hbt, mos, n = REQUESTS[stem]
    return {
        "netlist": netlist_name,
        "backend": "batch",
        "models": {"pdk": "ihp-sg13g2"},
        "corners": {
            "process": [{"name": pname, "sections": [
                {"lib": HBT_LIB, "section": hbt},
                {"lib": MOS_LIB, "section": mos},
            ]}],
            "supply_v": {"vdd": [VDD_V]},
            "temperature_c": [TEMP_C],
        },
        "monte_carlo": {"n": n, "seed": SEED, "vary": "mismatch",
                        "quantiles": [0, 5, 50, 95, 100]},
        "analysis": {"kind": "op", "args": ""},
        "measurements": measurements(),
        "options": {
            "timeout_s": 120,
            "keep_artifacts": True,
            "osdi_preload": [f"{pdk_root_var}/ihp-sg13g2/libs.tech/ngspice/osdi/{f}"
                             for f in OSDI_FILES],
            "stage_model_inputs": True,
            "ngspice_init": ["set numdgt=8"],
        },
    }


def generate(record_id: str, out_root: Path | None = None, git_sha: str = "unknown",
             netlist_path: Path = DESIGN_NETLIST) -> Path:
    if not RECORD_ID_RE.match(record_id):
        raise SystemExit(f"invalid record id {record_id!r}")
    out = Path(out_root or HERE / "netlist-snapshots") / record_id
    if out.exists() and any(out.iterdir()):
        raise SystemExit(f"{out} is not empty: snapshots are append-only; mint a new record id")
    out.mkdir(parents=True, exist_ok=True)
    bench = out / "bench_mc.spice"
    bench.write_text(bench_netlist(netlist_path))
    reqs = {}
    for stem in REQUESTS:
        p = out / f"{stem}.request.json"
        p.write_text(json.dumps(request(stem, bench.name), indent=2) + "\n")
        pname, hbt, mos, n = REQUESTS[stem]
        reqs[stem] = {"request": p.name, "request_sha256": sha256_file(p),
                      "process": pname, "hbt_section": hbt, "mos_section": mos, "n": n}
    pdk = json.loads(PDK_JSON.read_text())
    manifest = {
        "schema": SCHEMA, "issue": ISSUE, "record_id": record_id,
        "status": "request-set-not-run",
        "note": "Generated requests only; no measured result. Fleet reports land under "
                "corners/<record-id>/ and are reduced by `mc_campaign.py reduce`.",
        "git_sha": git_sha,
        "design_netlist": "design/netlist/lna.spice",
        "design_netlist_sha256": sha256_file(netlist_path),
        "bench": bench.name, "bench_sha256": sha256_file(bench),
        "generator_sha256": sha256_file(Path(__file__)),
        "pdk_pin": pdk.get("release_tag"),
        "seed": SEED, "temperature_c": TEMP_C, "vdd_v": VDD_V,
        "thresholds": {"ic1_exceeds_if_gt_A": I_C1_BAR_A, "pdc_exceeds_if_ge_W": P_DC_BAR_W},
        "requests": reqs,
        "runs": RUNS,
        "observables": [n for n, _, _ in OBSERVABLES],
        "sampled_params": [n for n, _, _ in SAMPLED_PARAMS],
    }
    (out / "campaign-manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    return out


def load_manifest(snapshot_dir: Path) -> dict:
    m = json.loads((Path(snapshot_dir) / "campaign-manifest.json").read_text())
    if m.get("schema") != SCHEMA:
        raise SystemExit(f"unsupported manifest schema {m.get('schema')!r}")
    return m


def verify_snapshot(snapshot_dir: Path) -> list[str]:
    snapshot_dir = Path(snapshot_dir)
    m = load_manifest(snapshot_dir)
    problems = []
    if sha256_file(snapshot_dir / m["bench"]) != m["bench_sha256"]:
        problems.append("bench netlist hash drift")
    for stem, r in m["requests"].items():
        if sha256_file(snapshot_dir / r["request"]) != r["request_sha256"]:
            problems.append(f"{stem}: request hash drift")
    return problems


# =============================================================================
# validate (runs under the klt CLI's own interpreter)
# =============================================================================

#: Top-level request keys documented for `klt sim` 0.7.0 (docs/cli/sim.md
#: "JSON schema"). klt itself has no dry-run and publishes no request JSON
#: Schema, so an unknown key is refused here rather than silently ignored.
KNOWN_TOP_LEVEL = {"netlist", "engine", "backend", "remote", "batch", "models", "corners",
                   "exclude", "monte_carlo", "analysis", "measurements", "options",
                   "netlist_source", "op_lint"}
USED_OPTIONS = {"timeout_s", "keep_artifacts", "osdi_preload", "stage_model_inputs",
                "ngspice_init"}


def validate(snapshot_dir: Path) -> dict:
    snapshot_dir = Path(snapshot_dir)
    try:
        from klayout_tools import sim as ksim  # noqa: PLC0415
        from klayout_tools import __version__ as kver  # noqa: PLC0415
    except Exception as exc:  # pragma: no cover - depends on host
        print(f"validate: cannot import the installed klt ({exc}); run with the klt CLI's "
              "interpreter. Nothing validated; do not submit.", file=sys.stderr)
        raise SystemExit(3)
    problems = verify_snapshot(snapshot_dir)
    m = load_manifest(snapshot_dir)
    checked = {}
    for stem, r in m["requests"].items():
        path = snapshot_dir / r["request"]
        req = ksim.load_request(str(path))
        unknown = sorted(set(req) - KNOWN_TOP_LEVEL)
        if unknown:
            problems.append(f"{stem}: unknown top-level keys {unknown}")
        extra_opts = sorted(set(req.get("options", {})) - USED_OPTIONS)
        if extra_opts:
            problems.append(f"{stem}: unexpected options {extra_opts}")
        n, seed, vary = ksim._validate_monte_carlo_spec(req["monte_carlo"])
        ksim._validate_mc_statistics_spec(req["monte_carlo"])
        ksim._validate_measurement_forms(req["measurements"])
        ksim._validate_expr_names_unique(req["measurements"])
        ksim._validate_ngspice_init(req["options"]["ngspice_init"])
        points = ksim._expand_corners(req["corners"], req.get("exclude") or [])
        sampled, info = ksim._expand_monte_carlo(points, req["monte_carlo"])
        if req.get("backend") != "batch":
            problems.append(f"{stem}: backend is not batch")
        if req["options"].get("stage_model_inputs") is not True:
            problems.append(f"{stem}: stage_model_inputs must be true (else klt steps back to local)")
        if len(points) != 1:
            problems.append(f"{stem}: expected exactly one corner, got {len(points)}")
        if (n, seed, vary) != (r["n"], SEED, "mismatch") or len(sampled) != r["n"]:
            problems.append(f"{stem}: monte_carlo expands to {len(sampled)} units, "
                            f"(n,seed,vary)=({n},{seed},{vary})")
        secs = [s for p in points for s in (getattr(p, "process_sections", None) or [])]
        if secs != [r["hbt_section"], r["mos_section"]]:
            problems.append(f"{stem}: process sections {secs} != manifest")
        rnd = [p.mc_seed["rndseed"] for p in sampled]
        checked[stem] = {
            "units": len(sampled), "n": n, "seed": seed, "vary": vary,
            "process_sections": secs,
            "distinct_rndseeds": len(set(rnd)),
            "first_rndseeds": rnd[:5],
            "rndseed_sha256": sha256_bytes(",".join(map(str, rnd)).encode()),
        }
    return {"klt_module_version": kver, "problems": problems, "requests": checked}


# =============================================================================
# reduce
# =============================================================================

def _num(v):
    """JSON value -> float or None; non-finite is returned as float (nan/inf)."""
    if isinstance(v, bool) or v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v)
    if isinstance(v, str):
        try:
            return float(v)
        except ValueError:
            return None
    return None


def _finite(x) -> bool:
    return x is not None and math.isfinite(x)


def load_report(path: Path) -> tuple[dict | None, str | None]:
    if not Path(path).is_file():
        return None, "missing_report"
    try:
        d = json.loads(Path(path).read_text())
    except (OSError, ValueError) as exc:
        return None, f"unreadable_report: {exc}"
    if not isinstance(d, dict):
        return None, "unreadable_report: not an object"
    if "error" in d and "corners" not in d:
        return d, f"error_envelope: {d['error'].get('message') if isinstance(d['error'], dict) else d['error']}"
    if not isinstance(d.get("corners"), list):
        return d, "malformed_report: no corners[]"
    return d, None


def fleet_identity(report: dict) -> dict:
    env = report.get("environment") or {}
    rem = env.get("remote") or {}
    keys = ("provider", "job_id", "state", "exit_code", "instance_type", "lifecycle",
            "ami_id", "runner_klt_version", "client_klt_version", "runner_compatibility",
            "elapsed_seconds")
    return {k: rem.get(k) for k in keys}


def extract_samples(report: dict, n_expected: int) -> tuple[list[dict], list[str]]:
    """One row per sample_index 0..n-1 (missing samples become explicit rows)."""
    issues = []
    by_idx: dict[int, dict] = {}
    for c in report.get("corners", []):
        mc = c.get("monte_carlo") or {}
        idx = mc.get("sample_index")
        if not isinstance(idx, int):
            issues.append(f"corner {c.get('corner_id')!r} has no monte_carlo.sample_index")
            continue
        if idx in by_idx:
            issues.append(f"duplicate sample_index {idx}")
            by_idx[idx]["duplicate"] = True
            continue
        vals = {}
        for m in c.get("measurements") or []:
            if isinstance(m, dict) and m.get("name") in ALL_MEAS:
                vals[m["name"]] = _num(m.get("value"))
        codes = sorted({d.get("code") for d in (c.get("diagnostics") or [])
                        if isinstance(d, dict) and d.get("code")})
        by_idx[idx] = {"sample_index": idx, "rndseed": mc.get("seed"),
                       "status": c.get("status"), "diagnostics": codes,
                       "values": vals, "duplicate": False, "present": True}
    rows = []
    for idx in range(n_expected):
        r = by_idx.get(idx) or {"sample_index": idx, "rndseed": None, "status": "missing",
                                "diagnostics": [], "values": {}, "duplicate": False,
                                "present": False}
        rows.append(r)
    extra = sorted(i for i in by_idx if not 0 <= i < n_expected)
    if extra:
        issues.append(f"unexpected sample_index values {extra}")
    for r in rows:
        r["classification"] = classify(r)
    return rows, issues


def classify(row: dict) -> str:
    if not row["present"]:
        return "missing"
    if row["duplicate"]:
        return "duplicate"
    if row["status"] == "error":
        return "failed_error"
    if row["status"] not in ("pass", "fail"):
        return f"failed_status_{row['status']}"
    for k in ALL_MEAS:
        v = row["values"].get(k)
        if v is None:
            return f"failed_missing_{k}"
        if not math.isfinite(v):
            return f"failed_nonfinite_{k}"
    return "ok"


def stats(values: list) -> dict:
    fin = [v for v in values if _finite(v)]
    nonfin = sum(1 for v in values if v is not None and not math.isfinite(v))
    missing = sum(1 for v in values if v is None)
    out = {"n_finite": len(fin), "n_nonfinite": nonfin, "n_missing": missing,
           "mean": None, "stdev": None, "min": None, "max": None, "zero_spread": None}
    if fin:
        out["mean"] = statistics.fmean(fin)
        out["min"], out["max"] = min(fin), max(fin)
        out["zero_spread"] = out["min"] == out["max"]
    if len(fin) >= 2:
        out["stdev"] = statistics.stdev(fin)
    return out


def pearson(xs: list, ys: list):
    pairs = [(x, y) for x, y in zip(xs, ys) if _finite(x) and _finite(y)]
    if len(pairs) < 3:
        return None
    mx = statistics.fmean(p[0] for p in pairs)
    my = statistics.fmean(p[1] for p in pairs)
    sxy = sum((x - mx) * (y - my) for x, y in pairs)
    sxx = sum((x - mx) ** 2 for x, _ in pairs)
    syy = sum((y - my) ** 2 for _, y in pairs)
    if sxx == 0 or syy == 0:
        return None
    return sxy / math.sqrt(sxx * syy)


def summarize_run(rows: list[dict]) -> dict:
    ok = [r for r in rows if r["classification"] == "ok"]
    col = {k: [r["values"].get(k) for r in rows if r["present"] and not r["duplicate"]]
           for k in ALL_MEAS}
    fails: dict[str, int] = {}
    for r in rows:
        if r["classification"] != "ok":
            fails[r["classification"]] = fails.get(r["classification"], 0) + 1
    ic1 = [r["values"].get("ic1") for r in ok]
    pdc = [r["values"].get("pdc") for r in ok]
    diag: dict[str, int] = {}
    for r in rows:
        for c in r["diagnostics"]:
            diag[c] = diag.get(c, 0) + 1
    return {
        "samples_expected": len(rows),
        "samples_present": sum(1 for r in rows if r["present"]),
        "samples_ok": len(ok),
        "failures": fails,
        "diagnostic_counts": diag,
        "status_counts": _count(r["status"] for r in rows),
        "stats": {k: stats(v) for k, v in col.items()},
        "count_ic1_gt_bar": sum(1 for v in ic1 if v > I_C1_BAR_A),
        "count_ic1_eq_bar": sum(1 for v in ic1 if v == I_C1_BAR_A),
        "count_pdc_ge_bar": sum(1 for v in pdc if v >= P_DC_BAR_W),
        "count_pdc_eq_bar": sum(1 for v in pdc if v == P_DC_BAR_W),
        "pdc_vs_vdd_idd_max_abs_err": _max_or_none(
            abs(r["values"]["pdc"] - r["values"]["vdd_node"] * r["values"]["idd"]) for r in ok),
    }


def _count(it) -> dict:
    out: dict = {}
    for x in it:
        out[str(x)] = out.get(str(x), 0) + 1
    return out


def _max_or_none(it):
    vals = list(it)
    return max(vals) if vals else None


def compare_replay(a: list[dict], b: list[dict]) -> dict:
    worst_rel, worst_abs, mismatches = 0.0, 0.0, []
    for ra, rb in zip(a, b):
        if ra["rndseed"] != rb["rndseed"]:
            mismatches.append(f"sample {ra['sample_index']}: rndseed differs")
        if ra["classification"] != rb["classification"]:
            mismatches.append(f"sample {ra['sample_index']}: classification "
                              f"{ra['classification']} vs {rb['classification']}")
            continue
        if ra["classification"] != "ok":
            continue
        for k in ALL_MEAS:
            x, y = ra["values"][k], rb["values"][k]
            d = abs(x - y)
            rel = d / max(abs(x), abs(y)) if max(abs(x), abs(y)) > 0 else 0.0
            worst_abs, worst_rel = max(worst_abs, d), max(worst_rel, rel)
            if d > REPLAY_ABS_TOL and rel > REPLAY_REL_TOL:
                mismatches.append(f"sample {ra['sample_index']} {k}: {x!r} vs {y!r}")
    if len(a) != len(b):
        mismatches.append(f"sample counts differ: {len(a)} vs {len(b)}")
    compared = sum(1 for ra, rb in zip(a, b) if ra["classification"] == rb["classification"] == "ok")
    return {"rel_tol": REPLAY_REL_TOL, "abs_tol": REPLAY_ABS_TOL,
            "samples_compared": compared, "max_abs_diff": worst_abs, "max_rel_diff": worst_rel,
            "mismatches": mismatches[:50], "n_mismatches": len(mismatches),
            "pass": compared > 0 and not mismatches}


def negative_control(rows: list[dict]) -> dict:
    ok = [r for r in rows if r["classification"] == "ok"]
    spread = {}
    for k in ALL_MEAS:
        vals = [r["values"][k] for r in ok]
        spread[k] = (max(vals) - min(vals)) if vals else None
    param_at_nominal = all(r["values"][k] == NOMINAL_PARAM[k] for r in ok for k in NOMINAL_PARAM)
    seeds = {r["rndseed"] for r in ok}
    ref = {}
    for k, v in DETERMINISTIC_REF["values"].items():
        got = ok[0]["values"][k] if ok else None
        ref[k] = {"reference": v, "control": got,
                  "rel_diff": (abs(got - v) / abs(v)) if got is not None else None}
    ref_ok = bool(ok) and all(e["rel_diff"] is not None and e["rel_diff"] <= DETERMINISTIC_REF["rel_tol"]
                              for e in ref.values())
    collapsed = bool(ok) and all(s == 0 for s in spread.values())
    return {"samples_ok": len(ok), "samples_expected": len(rows),
            "distinct_rndseeds": len(seeds),
            "max_minus_min": spread,
            "sampled_params_at_nominal": param_at_nominal,
            "collapsed": collapsed,
            "pass": collapsed and param_at_nominal and len(ok) == len(rows) and len(seeds) > 1,
            "deterministic_reference": {"record": DETERMINISTIC_REF["record"],
                                        "rel_tol": DETERMINISTIC_REF["rel_tol"],
                                        "values": ref, "agrees": ref_ok}}


def variation(main_summary: dict, rows: list[dict]) -> dict:
    ok = [r for r in rows if r["classification"] == "ok"]
    st = main_summary["stats"]
    params = {}
    for k, _, _ in SAMPLED_PARAMS:
        s = st[k]
        params[k] = {"stdev": s["stdev"], "expected_sigma_from_pdk_text": EXPECTED_SIGMA[k],
                     "zero_spread": s["zero_spread"]}
    active = all(p["stdev"] is not None and p["stdev"] > 0 for p in params.values())
    # Sensitivity: I_C1 mirrors I_C3 through the Q1:Q3 area ratio (Nx 8:1 times
    # the sampled area factors), so ln(I_C1) should track ln(q1_area/q3_area).
    x = [math.log(r["values"]["q1_area"] / r["values"]["q3_area"])
         if r["values"]["q1_area"] > 0 and r["values"]["q3_area"] > 0 else None for r in ok]
    y = [math.log(r["values"]["ic1"]) if r["values"]["ic1"] > 0 else None for r in ok]
    corr = pearson(x, y)
    zero = sorted(k for k in ALL_MEAS if st[k]["zero_spread"])
    expl = {}
    for k in zero:
        if k == "vdd_node":
            expl[k] = "ideal supply source: V(vdd) is set by `alter vdd=1.8`, not by the DUT"
        else:
            expl[k] = "UNEXPLAINED zero spread under mismatch sampling"
    return {"sampled_params": params, "all_sampled_params_vary": active,
            "corr_ln_ic1_vs_ln_q1_over_q3_area": corr,
            "zero_spread_quantities": zero, "zero_spread_explanations": expl,
            "pass": active and corr is not None and corr > 0.5
            and all(not v.startswith("UNEXPLAINED") for v in expl.values())}


def reduce(snapshot_dir: Path, corners_dir: Path, out_dir: Path, record_id: str) -> int:
    snapshot_dir, corners_dir, out_dir = Path(snapshot_dir), Path(corners_dir), Path(out_dir)
    m = load_manifest(snapshot_dir)
    problems = verify_snapshot(snapshot_dir)
    runs, rows_of = {}, {}
    for run, req_stem in RUNS.items():
        n = m["requests"][req_stem]["n"]
        rep, err = load_report(corners_dir / f"{run}.report.json")
        entry = {"request": m["requests"][req_stem]["request"], "n_requested": n}
        if err:
            problems.append(f"{run}: {err}")
            entry["error"] = err
        if rep is not None and "corners" in rep:
            fid = fleet_identity(rep)
            env = rep.get("environment") or {}
            emc = env.get("monte_carlo") or {}
            entry.update({"fleet": fid, "engine_version": env.get("engine_version"),
                          "report_status": rep.get("status"),
                          "netlist_sha256": env.get("netlist_sha256"),
                          "monte_carlo": {k: emc.get(k) for k in ("n", "seed", "vary")},
                          "family_mismatch": emc.get("family_mismatch"),
                          "provenance_klt_version": (rep.get("provenance") or {}).get("klt_version"),
                          "osdi_preload": env.get("osdi_preload"),
                          "corner_section_libs": env.get("corner_section_libs")})
            if fid["provider"] != "aws-batch-fleet" or not fid["job_id"]:
                problems.append(f"{run}: not a batch-fleet report (environment.remote missing)")
            if fid["state"] != "done":
                problems.append(f"{run}: fleet job state {fid['state']!r}")
            if (emc.get("n"), emc.get("seed"), emc.get("vary")) != (n, SEED, "mismatch"):
                problems.append(f"{run}: environment.monte_carlo {emc} != request")
            rows, issues = extract_samples(rep, n)
            problems.extend(f"{run}: {i}" for i in issues)
            rows_of[run] = rows
            entry["summary"] = summarize_run(rows)
        runs[run] = entry

    complete = not problems and set(rows_of) == set(RUNS)
    result = {"schema": SUMMARY_SCHEMA, "issue": ISSUE, "record_id": record_id,
              "complete": complete, "problems": problems,
              "design_netlist_sha256": m["design_netlist_sha256"],
              "bench_sha256": m["bench_sha256"], "pdk_pin": m["pdk_pin"],
              "seed": SEED, "temperature_c": TEMP_C, "vdd_v": VDD_V,
              "thresholds": m["thresholds"], "runs": runs}
    if "mc_mismatch" in rows_of:
        result["variation"] = variation(runs["mc_mismatch"]["summary"], rows_of["mc_mismatch"])
    if "mc_mismatch" in rows_of and "mc_mismatch_replay" in rows_of:
        result["replay"] = compare_replay(rows_of["mc_mismatch"], rows_of["mc_mismatch_replay"])
    if "negctl_nominal" in rows_of:
        result["negative_control"] = negative_control(rows_of["negctl_nominal"])
    result["controls_pass"] = bool(complete and result.get("variation", {}).get("pass")
                                   and result.get("replay", {}).get("pass")
                                   and result.get("negative_control", {}).get("pass"))
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / f"{record_id}-mc-summary.json").write_text(
        json.dumps(result, indent=2, sort_keys=True, allow_nan=False, default=str) + "\n")
    if "mc_mismatch" in rows_of:
        (out_dir / f"{record_id}-mc-samples.csv").write_text(samples_csv(rows_of["mc_mismatch"]))
    (out_dir / f"{record_id}-mc-summary.md").write_text(render_md(result))
    return 0 if complete else 2


def samples_csv(rows: list[dict]) -> str:
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(["sample_index", "rndseed", "status", "classification", "diagnostics",
                "ic1_gt_4p5mA", "pdc_ge_10mW"] + ALL_MEAS)
    for r in rows:
        v = r["values"]
        ic1, pdc = v.get("ic1"), v.get("pdc")
        w.writerow([r["sample_index"], r["rndseed"], r["status"], r["classification"],
                    ";".join(r["diagnostics"]),
                    "" if not _finite(ic1) else int(ic1 > I_C1_BAR_A),
                    "" if not _finite(pdc) else int(pdc >= P_DC_BAR_W)]
                   + ["" if v.get(k) is None else repr(v[k]) for k in ALL_MEAS])
    return buf.getvalue()


def _fmt(x, unit="", scale=1.0, nd=5):
    if x is None:
        return "n/a"
    return f"{x * scale:.{nd}g}{unit}"


def render_md(s: dict) -> str:
    L = [f"# {s['record_id']} -- full-DUT DC mismatch campaign (issue #90)", ""]
    L.append(f"**Structurally complete fleet evidence:** {'yes' if s['complete'] else 'NO'}; "
             f"**all controls pass:** {'yes' if s['controls_pass'] else 'NO'}.")
    L.append("")
    if s["problems"]:
        L += ["## Problems (record incomplete)", ""] + [f"- {p}" for p in s["problems"]] + [""]
    L += ["## Bench", "",
          f"- DUT `design/netlist/lna.spice` sha256 `{s['design_netlist_sha256']}`; bench "
          f"sha256 `{s['bench_sha256']}`; PDK pin `{s['pdk_pin']}`.",
          f"- One operating point: {s['temperature_c']} C, VDD {s['vdd_v']} V; base seed "
          f"{s['seed']}; DC `op` only.",
          "- P_dc = V(vdd) x I_DD of the full DUT (I_DD = -i(Vdd), the only supply source).", ""]
    L += ["## Runs", "", "| run | request | job id | state | runner klt | ngspice | samples ok / requested | failures |",
          "|---|---|---|---|---|---|---|---|"]
    for run, e in s["runs"].items():
        f = e.get("fleet") or {}
        sm = e.get("summary") or {}
        L.append(f"| {run} | {e['request']} | {f.get('job_id')} | {f.get('state')} | "
                 f"{f.get('runner_klt_version')} | {e.get('engine_version')} | "
                 f"{sm.get('samples_ok', 0)} / {e['n_requested']} | {sm.get('failures', {})} |")
    L.append("")
    main = (s["runs"].get("mc_mismatch") or {}).get("summary")
    if main:
        st = main["stats"]
        L += ["## Mismatch distribution (mc_mismatch, nominal process sections + per-instance mismatch)", "",
              "| quantity | finite | non-finite | missing | mean | sample stdev | min | max |",
              "|---|---|---|---|---|---|---|---|"]
        for k in ALL_MEAS:
            q = st[k]
            L.append(f"| {k} | {q['n_finite']} | {q['n_nonfinite']} | {q['n_missing']} | "
                     f"{_fmt(q['mean'])} | {_fmt(q['stdev'])} | {_fmt(q['min'])} | {_fmt(q['max'])} |")
        L += ["", f"- Samples with I_C1 > 4.5 mA: **{main['count_ic1_gt_bar']}** of "
              f"{main['samples_ok']} usable (equal to the bar: {main['count_ic1_eq_bar']}, not counted).",
              f"- Samples with P_dc >= 10 mW: **{main['count_pdc_ge_bar']}** of "
              f"{main['samples_ok']} usable (equality counts).",
              f"- Failed / non-usable samples (kept visible, never dropped): {main['failures'] or 'none'}.",
              "- These are finite-sample observations at one operating point, not a qualified "
              "yield figure and not a `klt yield` verdict.", ""]
    v = s.get("variation")
    if v:
        L += ["## Active stochastic variation", "",
              f"- Every sampled parameter varies: {v['all_sampled_params_vary']}.",
              f"- corr(ln I_C1, ln(q1_area/q3_area)) = {_fmt(v['corr_ln_ic1_vs_ln_q1_over_q3_area'], nd=4)} "
              "(Q1 mirrors Q3, so a positive correlation shows the sampled area reaches the observable).",
              "", "| sampled parameter | sample stdev | expected sigma (PDK text) |", "|---|---|---|"]
        for k, p in v["sampled_params"].items():
            L.append(f"| {k} | {_fmt(p['stdev'])} | {_fmt(p['expected_sigma_from_pdk_text'])} |")
        L += ["", "Zero-spread quantities: "
              + (", ".join(f"`{k}` ({v['zero_spread_explanations'][k]})" for k in v["zero_spread_quantities"]) or "none"), ""]
    r = s.get("replay")
    if r:
        L += ["## Seeded replay (same request, second fleet job)", "",
              f"- {r['samples_compared']} ordered samples compared; max abs diff {_fmt(r['max_abs_diff'])}, "
              f"max rel diff {_fmt(r['max_rel_diff'])} (tolerance rel {r['rel_tol']:g} or abs {r['abs_tol']:g}); "
              f"mismatches {r['n_mismatches']}; **{'PASS' if r['pass'] else 'FAIL'}**.", ""]
    n = s.get("negative_control")
    if n:
        ref = n["deterministic_reference"]
        L += ["## Negative control (nominal sections, mismatch disabled, repeated samples)", "",
              f"- {n['samples_ok']} / {n['samples_expected']} usable samples over "
              f"{n['distinct_rndseeds']} distinct ngspice seeds; every observable collapsed to one value: "
              f"{n['collapsed']}; sampled parameters at nominal (area=1, delvto=0): {n['sampled_params_at_nominal']}; "
              f"**{'PASS' if n['pass'] else 'FAIL'}**.",
              f"- Cross-check against deterministic record `{ref['record']}` (typ/27 C/1.80 V, rel tol "
              f"{ref['rel_tol']:g}): agrees = {ref['agrees']}.", ""]
        for k, e in ref["values"].items():
            L.append(f"  - {k}: reference {e['reference']!r}, control {e['control']!r}, rel diff {_fmt(e['rel_diff'])}")
        L.append("")
    L += ["## Not measured (disclosed)", "",
          "- RF statistical rows (gain, NF, IIP3, S11/S22, stability): unmeasured.",
          "- Resistor / passive tolerance: unmeasured (bias resistors are ideal SPICE R).",
          "- PVT: one operating point only; no full-PVT statistical signoff, no `klt yield` verdict.",
          "- HBT mismatch in this PDK is a single per-instance emitter-area factor (sigma 0.1, "
          "not scaled with Nx); MOS mismatch is delvto/factuo/w/l. Nothing else is sampled.", ""]
    return "\n".join(L) + "\n"


# =============================================================================
# CLI
# =============================================================================

def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    g = sub.add_parser("gen")
    g.add_argument("--record-id", required=True)
    g.add_argument("--out-root")
    g.add_argument("--git-sha", default="unknown")
    v = sub.add_parser("validate")
    v.add_argument("--snapshot-dir", required=True)
    v.add_argument("--out", required=True)
    vs = sub.add_parser("verify-snapshot")
    vs.add_argument("--snapshot-dir", required=True)
    r = sub.add_parser("reduce")
    r.add_argument("--snapshot-dir", required=True)
    r.add_argument("--corners-dir", required=True)
    r.add_argument("--out-dir", required=True)
    r.add_argument("--record-id", required=True)
    a = ap.parse_args(argv)
    if a.cmd == "gen":
        print(generate(a.record_id, Path(a.out_root) if a.out_root else None, a.git_sha))
        return 0
    if a.cmd == "verify-snapshot":
        p = verify_snapshot(Path(a.snapshot_dir))
        for x in p:
            print(f"verify-snapshot: {x}", file=sys.stderr)
        return 2 if p else 0
    if a.cmd == "validate":
        res = validate(Path(a.snapshot_dir))
        Path(a.out).write_text(json.dumps(res, indent=2, sort_keys=True) + "\n")
        for x in res["problems"]:
            print(f"validate: {x}", file=sys.stderr)
        return 2 if res["problems"] else 0
    return reduce(Path(a.snapshot_dir), Path(a.corners_dir), Path(a.out_dir), a.record_id)


if __name__ == "__main__":
    sys.exit(main())
