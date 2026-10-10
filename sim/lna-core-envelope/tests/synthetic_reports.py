"""SYNTHETIC FIXTURE GENERATOR (issue #58 offline tests).

Every number produced here is invented by this module to exercise the reducer.
It is NOT circuit evidence, was never simulated, and must never be cited as a
result. Every report it writes carries `"synthetic_fixture": true`; the reducer
stamps its output SYNTHETIC and refuses to write it under records/.
"""
import json
from pathlib import Path

# Invented per-measurement defaults (a passing, forward-active, plausible-looking cell).
OP = {"ic1": 3.5e-3, "ic2": 3.5e-3, "ib1": 4.5e-6, "ib2": 4.5e-6, "vb2": 1.65,
      "vce1": 0.88, "vce2": 0.92, "vbe1": 0.77, "vbe2": 0.77, "vbc1": -0.11, "vbc2": -0.15,
      "idd": 3.9e-3, "pdc": 7.0e-3}
SP_BAND = {"s21_db_min": 16.0, "s11_db_worst": -12.0, "s22_db_worst": -11.0, "mu_band_min": 1.01,
           "nfmin_sp_db_lo": 1.0, "nfmin_sp_db_worst": 1.0, "cin_ff_mid": 220.0}
NOISE = {"nf290_db_lo": 1.2, "nf290_db_mid": 1.19, "nf290_db_hi": 1.18, "nf290_db_worst": 1.2}


def default_value(an, name):
    if an == "op" and name in OP:
        return OP[name]
    if an == "sp_band" and name in SP_BAND:
        return SP_BAND[name]
    if an == "noise":
        if name in NOISE:
            return NOISE[name]
        if name.startswith("nf290_db_f"):
            return 1.2 if name == "nf290_db_f00" else 1.1
    if an == "sp_stab" and name == "mu_min":
        return 1.0001
    return 1.0


def write_reports(snapshot_dir: Path, corners_dir: Path, client="0.7.0", runner="0.7.0", override=None):
    """override(stem, case_id, analysis, cell, values) may mutate `values` in place."""
    man = json.loads((Path(snapshot_dir) / "campaign-manifest.json").read_text())
    Path(corners_dir).mkdir(parents=True, exist_ok=True)
    for r in man["requests"]:
        corners = []
        for cell in r["expected_cells"]:
            vals = {n: default_value(r["analysis"], n) for n in r["expected_measurements"]}
            if override:
                override(r["stem"], r["case"], r["analysis"], tuple(cell), vals)
            corners.append({"process": {"name": cell[0]}, "temperature_c": cell[1],
                            "supply_v": {"vdd": cell[2]}, "status": "ok",
                            "measurements": [{"name": k, "value": v} for k, v in vals.items()]})
        doc = {"synthetic_fixture": True, "status": "pass", "corner_count": len(corners),
               "corners": corners,
               "environment": {"remote": {"job_id": "SYNTHETIC", "instance_type": "none",
                                          "runner_klt_version": runner, "state": "done"}}}
        (Path(corners_dir) / f"{r['stem']}.report.json").write_text(json.dumps(doc))
    return man
