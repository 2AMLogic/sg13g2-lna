"""The native DRC report/sidecar pair check, in exactly one place.

`STATUSES` (the completed-run status vocabulary), `version_tuple`,
`version_at_least` and `check_pair` — the full native-pair validation
(one-sided refusal, sidecar schema/fields/bindings, report pinning, status
agreement, executable-version floor) — were previously copy-pasted into
`layout/run_native_drc.py`, `layout/native_drc_identity.py` and the
freshness gate `.github/scripts/check-layout-freshness`, kept equal only by
a sync test. Operator ruling (rjwalters, 2026-11-17, issue #359):
consolidate to this one implementation, living next to the gate it
primarily serves — the gate executes only code from its own directory and
must not import the logic it judges with from `layout/`, the directory
whose output it judges — with the layout scripts loading it by file path
(`importlib.util.spec_from_file_location`), which works under `python3 -I`
and stays stdlib-only.

The gate's logic and message text are the reference behaviour: `check_pair`
is that code verbatim, parameterised by the message path prefix
(`layout/<cell>` for the gate, the bare cell-directory name for
`native_drc_identity.validate`) and by a `fail(rel, msg)` sink, so each
caller keeps its own prefix and verdict channel while the accept/reject set
and message bodies exist once.

Stdlib only. Every consumer runs under `python3 -I`, whose isolated mode
neither puts a script's directory on `sys.path` nor writes bytecode, so
this module can only be reached by explicit path and never leaves a
`__pycache__` behind.
"""
import hashlib
import json
import re
from pathlib import Path

SCHEMA = "sg13g2-lna.native-drc/1"
REPORT = "native_drc_report.json"
SIDE = "native_drc_inputs.json"

# The completed-run status tokens these gates accept from klt's rollup
# vocabulary (run_native_drc.py's rationale records which of them
# --engine klayout emits today — issue #312). A token the runner publishes
# and the identity binds must not fail the gate, or a partial/no-verdict
# native run would be discarded one gate later than the defect issue #290
# fixes.
STATUSES = ("clean", "clean_partial", "violations",
            "coverage_unknown", "not_checked")

_VERSION_RE = re.compile(r"\d+(?:\.\d+)+")


def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


def version_tuple(s):
    """First dotted-number run in *s* as a tuple of ints, else None."""
    if not isinstance(s, str):
        return None
    m = _VERSION_RE.search(s)
    return tuple(int(x) for x in m.group(0).split(".")) if m else None


def version_at_least(got, minimum):
    """got >= minimum, padding the shorter tuple with zeros: 0.29 == 0.29.0."""
    a, b = version_tuple(got), version_tuple(minimum)
    if a is None or b is None:
        return False
    n = max(len(a), len(b))
    a += (0,) * (n - len(a))
    b += (0,) * (n - len(b))
    return a >= b


def _load_json(p, fail, rel):
    try:
        return json.loads(p.read_text())
    except Exception as e:
        fail(rel, f"unreadable JSON ({e})")
        return None


def check_pair(cell_dir, root, rel_prefix, gds, gds_sha, fail,
               report_name=REPORT, side_name=SIDE):
    """Check the native report/sidecar pair in *cell_dir*, reporting every
    problem through *fail(rel, msg)*.

    Entirely absent: allowed — no native verdict exists in this tree until
    issue #201 supplies one. One-sided or inconsistent: fails, naming it.

    *rel_prefix* names the pair's files in messages (`layout/<cell>` for
    the freshness gate, the bare cell-directory name for
    native_drc_identity.validate). *gds* is the committed GDS and *gds_sha*
    its sha256, or None when the GDS file is missing (the gate reports that
    separately and still checks everything that does not need the digest).
    *root* is the repository root the recorded GDS path is made relative
    to.
    """
    cd = Path(cell_dir)
    rep_p, side_p = cd / report_name, cd / side_name
    if not rep_p.is_file() and not side_p.is_file():
        return  # absent: allowed
    nrep_rel = f"{rel_prefix}/{report_name}"
    nside_rel = f"{rel_prefix}/{side_name}"
    if not rep_p.is_file():
        fail(nside_rel, f"{report_name} missing: native report/sidecar pair is one-sided")
        return
    if not side_p.is_file():
        fail(nrep_rel, f"{side_name} missing: native report/sidecar pair is one-sided")
        return
    side = _load_json(side_p, fail, nside_rel)
    rep = _load_json(rep_p, fail, nrep_rel)
    rel = nside_rel
    if side is None or rep is None:
        return
    if not isinstance(side, dict) or side.get("schema") != SCHEMA:
        fail(rel, "malformed (bad schema)")
        return
    keys = ("report", "report_sha256", "status", "gds", "gds_sha256", "pdk",
            "klayout_exe", "klayout_exe_resolved", "klayout_exe_version",
            "min_klayout_version")
    missing = [k for k in keys if not isinstance(side.get(k), str) or not side[k]]
    if missing:
        fail(rel, f"missing or malformed field(s): {', '.join(missing)}")
        return
    for k in ("deck_binding", "pdk_binding"):
        if k not in side:
            fail(rel, f"missing {k}")
            return
        if not isinstance(side[k], dict):
            fail(rel, f"{k} missing or malformed")
            return
    if side["report"] != report_name:
        fail(rel, f"report is {side['report']!r}, want {report_name!r}")
        return
    klt = side.get("klt")
    if not isinstance(klt, dict) or not isinstance(klt.get("version"), str) \
            or not klt["version"]:
        fail(rel, "klt identity missing or malformed")
        return
    argv = side.get("argv")
    if not isinstance(argv, list) or not argv \
            or any(not isinstance(a, str) for a in argv):
        fail(rel, "argv missing or malformed")
        return
    if sha(rep_p) != side["report_sha256"]:
        fail(rel, f"report changed since this native run (recorded "
             f"{side['report_sha256'][:12]}, now {sha(rep_p)[:12]}); "
             f"rerun layout/run_native_drc.py")
    try:
        want_gds = str(gds.resolve().relative_to(root))
    except ValueError:
        want_gds = str(gds.resolve())
    if side["gds"] != want_gds:
        fail(rel, f"gds path {side['gds']!r} != {want_gds!r}")
    elif gds_sha is not None and side["gds_sha256"] != gds_sha:
        fail(rel, f"GDS changed since this native run (recorded "
             f"{side['gds_sha256'][:12]}, now {gds_sha[:12]}); "
             f"rerun layout/run_native_drc.py")
    # the report itself must pin the committed GDS and carry the recorded verdict
    prov = rep.get("provenance") if isinstance(rep, dict) else None
    inp = prov.get("input") if isinstance(prov, dict) else None
    if not isinstance(inp, dict):
        fail(nrep_rel, "missing provenance.input")
    else:
        if inp.get("role") != "layout":
            fail(nrep_rel, f"provenance.input.role is {inp.get('role')!r}, want 'layout'")
        ch = inp.get("content_hash")
        if not isinstance(ch, str) or not ch.startswith("sha256:"):
            fail(nrep_rel, f"provenance.input.content_hash missing or malformed ({ch!r})")
        elif gds_sha is not None and ch[len("sha256:"):] != gds_sha:
            fail(nrep_rel, f"provenance.input.content_hash {ch} != sha256:{gds_sha} (committed GDS)")
    if not isinstance(rep, dict) or rep.get("status") not in STATUSES:
        got = rep.get("status") if isinstance(rep, dict) else type(rep).__name__
        fail(nrep_rel, f"status is {got!r}, want one of {list(STATUSES)}")
    elif side["status"] != rep["status"]:
        fail(rel, f"status {side['status']!r} != report status {rep['status']!r}")
    # deck / pdk bindings must equal what the report itself records; a
    # report without a deck/pdk object is refused outright (issue #386:
    # a null binding paired with a missing object used to pass None == None),
    # in _report_facts' wording so record() and the gate name the same defect
    if isinstance(prov, dict):
        for k, key in (("deck_binding", "deck"), ("pdk_binding", "pdk")):
            want = prov.get(key)
            if not isinstance(want, dict):
                fail(nrep_rel, f"report provenance has no {key} object"
                     + (" (--pdk must be given)" if key == "pdk" else ""))
            elif side[k] != want:
                fail(rel, f"{k} differs from the report's provenance; "
                     f"rerun layout/run_native_drc.py")
    # recorded executable must satisfy the recorded minimum
    vt_min, vt_exe = version_tuple(side["min_klayout_version"]), \
        version_tuple(side["klayout_exe_version"])
    if vt_min is None:
        fail(rel, f"min_klayout_version {side['min_klayout_version']!r} unparseable")
    if vt_exe is None:
        fail(rel, f"klayout_exe_version {side['klayout_exe_version']!r} unparseable")
    if vt_min is not None and vt_exe is not None:
        n = max(len(vt_min), len(vt_exe))
        a, b = vt_exe + (0,) * (n - len(vt_exe)), vt_min + (0,) * (n - len(vt_min))
        if a < b:
            fail(rel, f"klayout_exe_version {side['klayout_exe_version']!r} "
                 f"is below min_klayout_version {side['min_klayout_version']!r}")
