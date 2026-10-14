#!/usr/bin/env python3
"""Audit and freshness check for the T1 item-9 testbench inventory (issue #195).

T1 item 9 ("Testbenches shipped") asks that every claimed measurement's
testbench is committed, with a documented cold-start invocation and a pinned
PDK. The evidence the pinned klt can read for it is an artifact-anchored
generic envelope bound to an audited artifact. That artifact is
`signoff/testbench-inventory.json`, derived here from the hand-maintained
coverage index `signoff/testbench-coverage.json`.

Modes
-----
(default) check   Read-only. Recompute the inventory from the tracked tree and
                  the coverage index, and fail on any divergence from the
                  committed inventory, envelope, manifest citation or rolling
                  report. Needs only python3 (stdlib) and `git ls-files`; no
                  PDK, ngspice, klt or network, and it writes nothing.
--write           Regenerate the inventory. The envelope and the manifest
                  citation for item 9 are emitted only when the audit is
                  complete. An incomplete audit writes nothing and exits 1.

What is checked mechanically is listed in MECHANICAL_CHECKS below and is
copied into the inventory. What is NOT checked (that a documented command
actually runs, that the stated classification is right, that the index is not
under-inclusive about prose the scan cannot parse) is listed in the index's
`reviewer_checks` and is the audit reviewer's job. Command text in a README
does not prove execution succeeds.

Exit status: 0 ok, 1 audit/freshness failure, 2 usage error.
"""

import argparse
import fnmatch
import hashlib
import json
import os
import re
import subprocess
import sys

ITEM = 9
INDEX = "signoff/testbench-coverage.json"
INVENTORY = "signoff/testbench-inventory.json"
ENVELOPE = "signoff/testbench-inventory.envelope.json"
MANIFEST = "signoff/manifest.json"
REPORT = "signoff/t1-report.json"
WORKFLOW = ".github/workflows/signoff.yml"
PDK_JSON = "sim/pdk.json"

CLASSIFICATIONS = {
    "present-dut": "measures the DUT committed today (design/netlist/lna.spice)",
    "historical-dut": "measures a superseded DUT; not reproducible from the current tree",
    "device-characterization": "model-card level device study, no LNA DUT",
    "variant-exploration": "PVT-grid study of non-committed DUT variants (probes)",
    "nominal-exploration": "single-PVT-cell study, not a PVT result",
    "data-only-derivation": "derived from committed data; no new simulation",
}
RESULT_STATUS = {"published", "superseded", "none-blocked", "none-unrun"}
ROLE_KEYS = (
    "bench_templates",
    "bench_generators",
    "runners",
    "reducers",
    "derivations",
    "replay_checks",
    "published_views",
    "docs",
)
EVIDENCE_DIRS = ("records", "corners", "netlist-snapshots", "views")
STD_ID = re.compile(r"(?<![0-9A-Za-z])\d{8}-\d{6}-[0-9a-f]{7,40}(?![0-9A-Za-z])")
# "sim/<slug>/" mentions; a sibling repo's path ("other-repo/sim/x/") is not ours.
SIM_MENTION = re.compile(r"(?<![A-Za-z0-9_-]/)(?<![A-Za-z0-9_.-])sim/([A-Za-z0-9_][A-Za-z0-9_.-]*)/")

MECHANICAL_CHECKS = [
    "the coverage index parses and every claim carries the required fields and a known classification",
    "every listed path is a tracked, existing file (runners invoked directly are mode 100755)",
    "every sim/<dir>/ is an indexed family or an explicitly named support directory",
    "every tracked non-evidence file in an indexed family is listed by a claim or excluded with a reason",
    "every tracked record, view, corners and netlist-snapshots id in an indexed family belongs to a claim",
    "sim/<slug>/ mentions and standard record ids in the declared claim sources resolve to the index",
    "no tracked bench-like file outside sim/ exists unless excluded with a reason",
    "each bench template is referenced by name from a listed runner, reducer or generator of its claim",
    "each cold-start command appears verbatim in its named document and names a listed runner, reducer, derivation or replay path",
    "each data-only derivation names source claims that exist and have records",
    "every listed input, shared input and record file is hashed (sha256); corner and snapshot trees get a git-blob digest",
    "the PDK pin and the grader pin are read from sim/pdk.json and the workflow",
    "the committed inventory equals the recomputed one byte for byte",
    "the envelope, the manifest citation and the rolling report (when present) bind the same inventory hash",
]


class Audit:
    def __init__(self, root):
        self.root = root
        self.errors = []

    def err(self, msg):
        self.errors.append(msg)


def sha256_bytes(data):
    return "sha256:" + hashlib.sha256(data).hexdigest()


def read_bytes(root, rel):
    with open(os.path.join(root, rel), "rb") as fh:
        return fh.read()


def read_text(root, rel):
    return read_bytes(root, rel).decode("utf-8", errors="replace")


def git_ls_files(root):
    """Return {path: (mode, blob)} for the index, via `git ls-files -s -z`."""
    try:
        out = subprocess.run(
            ["git", "-C", root, "ls-files", "-s", "-z"],
            check=True,
            capture_output=True,
        ).stdout
    except (OSError, subprocess.CalledProcessError) as exc:
        raise SystemExit("ERROR: cannot list tracked files in %s: %s" % (root, exc))
    files = {}
    for rec in out.decode("utf-8", errors="surrogateescape").split("\0"):
        if not rec:
            continue
        meta, _, path = rec.partition("\t")
        mode, blob, _stage = meta.split()
        files[path] = (mode, blob)
    return files


def norm_ws(text):
    """Join backslash continuations and collapse whitespace."""
    text = re.sub(r"\\\s*\n", " ", text)
    return " ".join(text.split())


def load_json(audit, rel, what):
    try:
        return json.loads(read_text(audit.root, rel))
    except FileNotFoundError:
        audit.err("%s: missing %s" % (what, rel))
    except ValueError as exc:
        audit.err("%s: %s is not valid JSON (%s)" % (what, rel, exc))
    return None


def id_matches(basename, ident):
    return (
        basename == ident
        or basename.startswith(ident + ".")
        or basename.startswith(ident + "-")
    )


def evidence_files(tracked, family, ident):
    """Tracked evidence paths of one family that belong to one record id."""
    pre = "sim/%s/" % family
    found = {"records": [], "views": [], "corners": [], "netlist-snapshots": []}
    for path in tracked:
        if not path.startswith(pre):
            continue
        rest = path[len(pre):].split("/")
        if rest[0] in ("records", "views") and len(rest) == 2:
            if id_matches(rest[1], ident):
                found[rest[0]].append(path)
        elif rest[0] in ("corners", "netlist-snapshots") and len(rest) >= 3:
            if rest[1] == ident:
                found[rest[0]].append(path)
    return found


def claim_paths(claim):
    paths = []
    for key in ROLE_KEYS:
        paths.extend(claim.get(key, []))
    return paths


def build(root, audit):
    """Recompute the inventory. Findings go to audit.errors."""
    tracked = git_ls_files(root)
    index = load_json(audit, INDEX, "coverage index")
    if index is None:
        return None
    if index.get("schema_version") != 1 or index.get("t1_item") != ITEM:
        audit.err("coverage index: need schema_version 1 and t1_item %d" % ITEM)
        return None

    for need in (
        "audit_scope",
        "claim_sources",
        "reviewer_checks",
        "open_gaps",
        "shared_input_groups",
        "support_dirs",
        "families",
        "claims",
        "excluded_bench_like_paths",
    ):
        if need not in index:
            audit.err("coverage index: missing top-level key %r" % need)
    if audit.errors:
        return None

    groups = index["shared_input_groups"]
    families = index["families"]
    claims = index["claims"]
    claim_ids = [c.get("id") for c in claims]
    if len(set(claim_ids)) != len(claim_ids):
        audit.err("coverage index: duplicate claim ids")
    by_id = {c.get("id"): c for c in claims}

    needed_files = set()  # paths hashed into the inventory

    def need_path(rel, owner):
        if rel not in tracked:
            audit.err("%s: %s is not a tracked file" % (owner, rel))
            return False
        if not os.path.isfile(os.path.join(root, rel)):
            audit.err("%s: %s is tracked but absent from the work tree" % (owner, rel))
            return False
        needed_files.add(rel)
        return True

    # ---- shared groups
    for gname, group in groups.items():
        if not group.get("why"):
            audit.err("shared group %s: needs a 'why'" % gname)
        for rel in group.get("paths", []):
            need_path(rel, "shared group %s" % gname)

    # ---- sim/ directory coverage
    sim_dirs = sorted({p.split("/")[1] for p in tracked if p.startswith("sim/") and p.count("/") >= 2})
    for d in sim_dirs:
        if d not in families and d not in index["support_dirs"]:
            audit.err(
                "sim/%s/ is neither an indexed measurement family nor a named support "
                "directory: a new measurement family must be classified in %s" % (d, INDEX)
            )
    for fam in families:
        if fam not in sim_dirs:
            audit.err("family %s is indexed but sim/%s/ has no tracked files" % (fam, fam))
    for d, reason in index["support_dirs"].items():
        if not reason:
            audit.err("support dir %s: needs a reason" % d)

    # ---- per-claim structure and paths
    claim_files = {}
    for claim in claims:
        cid = claim.get("id", "<no id>")
        for req in ("id", "family", "classification", "result_status", "summary",
                    "dut", "cold_start", "tool_pins", "limitations", "record_ids"):
            if req not in claim:
                audit.err("claim %s: missing field %r" % (cid, req))
        if claim.get("classification") not in CLASSIFICATIONS:
            audit.err("claim %s: unknown classification %r" % (cid, claim.get("classification")))
        if claim.get("result_status") not in RESULT_STATUS:
            audit.err("claim %s: unknown result_status %r" % (cid, claim.get("result_status")))
        if claim.get("family") not in families:
            audit.err("claim %s: family %r is not indexed" % (cid, claim.get("family")))
        for g in claim.get("shared", []):
            if g not in groups:
                audit.err("claim %s: unknown shared group %r" % (cid, g))
        for rel in claim_paths(claim):
            need_path(rel, "claim %s" % cid)
        claim_files[cid] = set(claim_paths(claim))
        if not claim.get("docs"):
            audit.err("claim %s: lists no documentation file" % cid)
        deriv = claim.get("classification") == "data-only-derivation"
        if deriv:
            if not claim.get("derives_from"):
                audit.err("claim %s: a data-only derivation must name derives_from claims" % cid)
            for src in claim.get("derives_from", []):
                if src not in by_id:
                    audit.err("claim %s: derives_from %r is not a claim" % (cid, src))
                elif not by_id[src].get("record_ids"):
                    audit.err("claim %s: source claim %s has no records" % (cid, src))
            if not (claim.get("derivations") or claim.get("reducers")):
                audit.err("claim %s: a derivation needs a derivation/reducer file" % cid)
        else:
            if not (claim.get("bench_templates") or claim.get("bench_generators")):
                audit.err("claim %s: no bench template or generator listed" % cid)
            if not claim.get("runners"):
                audit.err("claim %s: no runner listed" % cid)
        if claim.get("classification") == "historical-dut" and not claim.get("revision_note"):
            audit.err("claim %s: a historical DUT needs a revision_note (reproduction route)" % cid)
        if not claim.get("cold_start"):
            audit.err("claim %s: no cold-start command" % cid)
        else:
            want = "replay" if deriv else "run"
            if not any(c.get("kind") == want for c in claim["cold_start"]):
                audit.err("claim %s: needs a documented %r cold-start entry" % (cid, want))
        if claim.get("dut") not in ("present", "historical", "none"):
            audit.err("claim %s: dut must be present, historical or none" % cid)
        if claim.get("dut") == "present" and "dut-netlist" not in claim.get("shared", []):
            audit.err("claim %s: a present-DUT claim must hash the dut-netlist shared group" % cid)
        if claim.get("dut") == "historical" and claim.get("classification") != "historical-dut":
            audit.err("claim %s: dut=historical requires classification historical-dut" % cid)
        if claim.get("classification") == "historical-dut" and claim.get("dut") == "present":
            audit.err("claim %s: a historical-DUT claim cannot have dut=present" % cid)

    # ---- bench templates are referenced by a runner/reducer/generator of the claim
    for claim in claims:
        cid = claim.get("id", "<no id>")
        refs = []
        for key in ("runners", "reducers", "bench_generators", "derivations"):
            refs.extend(p for p in claim.get(key, []) if p in tracked and os.path.isfile(os.path.join(root, p)))
        ref_text = "\n".join(read_text(root, p) for p in refs)
        for tmpl in claim.get("bench_templates", []):
            if tmpl in tracked and os.path.basename(tmpl) not in ref_text:
                audit.err(
                    "claim %s: bench %s is not referenced by any listed runner/reducer/generator"
                    % (cid, tmpl)
                )

    # ---- cold-start commands
    for claim in claims:
        cid = claim.get("id", "<no id>")
        listed = claim_files[cid]
        for cs in claim.get("cold_start", []):
            cmd, doc = cs.get("command"), cs.get("doc")
            if not cmd or not doc or not cs.get("needs"):
                audit.err("claim %s: cold_start entries need command, doc and needs" % cid)
                continue
            if doc not in listed:
                audit.err("claim %s: cold-start doc %s is not among its listed docs" % (cid, doc))
            if doc in tracked and os.path.isfile(os.path.join(root, doc)):
                if norm_ws(cmd) not in norm_ws(read_text(root, doc)):
                    audit.err(
                        "claim %s: documented invocation not found in %s: %s" % (cid, doc, cmd)
                    )
            if cs.get("kind") not in ("run", "replay"):
                audit.err("claim %s: cold_start kind must be 'run' or 'replay'" % cid)
            cmd_paths = [
                t for t in norm_ws(cmd).split()
                if "/" in t or t.endswith((".py", ".sh"))
            ]
            code = [f for f in listed if f not in claim.get("docs", [])]
            hits = [
                t
                for t in cmd_paths
                if any(
                    f == t
                    or f.startswith(t.rstrip("/") + "/")
                    or ("/" not in t and f.endswith("/" + t))
                    for f in code
                )
            ]
            if not hits:
                audit.err(
                    "claim %s: cold-start command does not name a listed runner/reducer/"
                    "derivation/replay path: %s" % (cid, cmd)
                )
            for t in cmd_paths:
                if t in claim.get("runners", []) and t in tracked and t.endswith(".sh"):
                    if tracked[t][0] != "100755":
                        audit.err("claim %s: runner %s is invoked directly but is not executable" % (cid, t))

    # ---- family file accountability
    all_listed = set().union(*claim_files.values()) if claim_files else set()
    for fam, fmeta in families.items():
        pre = "sim/%s/" % fam
        globs = fmeta.get("unaccounted_ok", [])
        for g in globs:
            if not g.get("glob") or not g.get("reason"):
                audit.err("family %s: unaccounted_ok entries need glob and reason" % fam)
        readme = fmeta.get("readme")
        if readme not in all_listed:
            audit.err("family %s: readme %s is not listed in any claim's docs" % (fam, readme))
        for path in sorted(p for p in tracked if p.startswith(pre)):
            rest = path[len(pre):]
            if rest.split("/")[0] in EVIDENCE_DIRS:
                continue
            if path in all_listed:
                continue
            if any(fnmatch.fnmatchcase(rest, g.get("glob", "")) for g in globs):
                continue
            audit.err(
                "family %s: tracked file %s is in no claim and not excluded: a new bench, "
                "runner or reducer must be indexed" % (fam, path)
            )

    # ---- evidence id accountability
    ids_by_family = {}
    for claim in claims:
        ids_by_family.setdefault(claim.get("family"), set()).update(claim.get("record_ids", []))
    for fam in families:
        pre = "sim/%s/" % fam
        seen = set()
        for path in tracked:
            if not path.startswith(pre):
                continue
            rest = path[len(pre):].split("/")
            if rest[0] in ("corners", "netlist-snapshots") and len(rest) >= 3:
                seen.add((rest[0], rest[1]))
            elif rest[0] in ("records", "views") and len(rest) == 2:
                seen.add((rest[0], rest[1]))
        for kind, name in sorted(seen):
            ok = any(
                id_matches(name, i) or (kind in ("corners", "netlist-snapshots") and name == i)
                for i in ids_by_family.get(fam, ())
            )
            if not ok:
                audit.err(
                    "family %s: %s/%s belongs to no claim's record_ids: a new record must be indexed"
                    % (fam, kind, name)
                )
    for claim in claims:
        cid = claim.get("id", "<no id>")
        for ident in claim.get("record_ids", []):
            ev = evidence_files(tracked, claim.get("family"), ident)
            if not (ev["records"] or ev["views"] or ev["corners"] or ev["netlist-snapshots"]):
                audit.err("claim %s: record id %s has no tracked evidence" % (cid, ident))
            for rel in ev["records"] + ev["views"]:
                need_path(rel, "claim %s record" % cid)

    # ---- claim sources: sim/<slug>/ mentions and record ids
    known_slugs = set(families) | set(index["support_dirs"])
    all_ids = set()
    for ids in ids_by_family.values():
        all_ids |= ids
    evidence_text_ids = set()
    for path in tracked:
        m = re.match(r"sim/[^/]+/(?:records|corners|netlist-snapshots|views)/([^/]+)", path)
        if m:
            evidence_text_ids.update(STD_ID.findall(m.group(1)))
    for src in index["claim_sources"]:
        if not need_path(src, "claim source"):
            continue
        text = read_text(root, src)
        for slug in sorted(set(SIM_MENTION.findall(text))):
            if slug not in known_slugs and slug not in ("README.md", "pdk.json", "env.sh"):
                audit.err(
                    "claim source %s mentions sim/%s/, which is not an indexed family or support dir"
                    % (src, slug)
                )
        for ident in sorted(set(STD_ID.findall(text))):
            if ident in evidence_text_ids and ident not in all_ids:
                audit.err(
                    "claim source %s cites record %s, which exists in sim/ but no claim lists it"
                    % (src, ident)
                )

    # ---- bench-like files outside sim/
    excl = index["excluded_bench_like_paths"]
    for path in sorted(tracked):
        if path.startswith(("sim/", ".loom/", ".agents/", ".claude/")):
            continue
        base = os.path.basename(path)
        if (base.startswith("tb_") or base.endswith(".spice.tmpl") or base.startswith("run_")) \
                and path not in excl:
            audit.err(
                "tracked bench-like file %s is outside sim/ and not excluded in the index" % path
            )
    for path, reason in excl.items():
        if path not in tracked:
            audit.err("excluded bench-like path %s is not tracked" % path)
        if not reason:
            audit.err("excluded bench-like path %s: needs a reason" % path)

    # ---- pins
    pins = {}
    pdk = load_json(audit, PDK_JSON, "pdk pin")
    if pdk is not None:
        for k in ("release_tag", "variant", "source"):
            if not pdk.get(k):
                audit.err("%s lacks %r" % (PDK_JSON, k))
        pins["pdk"] = {
            "file": PDK_JSON,
            "release_tag": pdk.get("release_tag"),
            "variant": pdk.get("variant"),
            "source": pdk.get("source"),
            "ngspice_actually_used": (pdk.get("device_models_used_by_this_repo_so_far") or {}).get(
                "ngspice_actually_used"
            ),
        }
        needed_files.add(PDK_JSON)
    try:
        m = re.search(r"klayout-tools==([0-9][0-9.]*)", read_text(root, WORKFLOW))
    except FileNotFoundError:
        m = None
    if m is None:
        audit.err("cannot read the pinned klt release from %s" % WORKFLOW)
    else:
        pins["grader"] = {"tool": "klayout-tools", "version": m.group(1), "source": WORKFLOW}

    # ---- hashes
    files = {}
    for rel in sorted(needed_files):
        if rel in tracked and os.path.isfile(os.path.join(root, rel)):
            files[rel] = sha256_bytes(read_bytes(root, rel))

    def tree_digest(family, kind, ident):
        rows = sorted(
            (p, tracked[p][1])
            for p in tracked
            if p.startswith("sim/%s/%s/%s/" % (family, kind, ident))
        )
        h = hashlib.sha256()
        for p, blob in rows:
            h.update(("%s %s\n" % (blob, p)).encode())
        return {"files": len(rows), "git_blob_digest": "sha256:" + h.hexdigest()}

    out_claims = []
    for claim in claims:
        fam = claim.get("family")
        entry = {
            k: claim[k]
            for k in sorted(claim)
            if k not in ("record_ids",)
        }
        entry["records"] = []
        for ident in claim.get("record_ids", []):
            ev = evidence_files(tracked, fam, ident)
            entry["records"].append(
                {
                    "id": ident,
                    "published_files": sorted(ev["records"] + ev["views"]),
                    "corners": tree_digest(fam, "corners", ident),
                    "netlist_snapshots": tree_digest(fam, "netlist-snapshots", ident),
                }
            )
        out_claims.append(entry)

    audit_block = {
        "scope": index["audit_scope"],
        "claim_sources": index["claim_sources"],
        "classification_legend": CLASSIFICATIONS,
        "mechanical_checks": MECHANICAL_CHECKS,
        "reviewer_checks": index["reviewer_checks"],
        "open_gaps": index["open_gaps"],
        "verdict": "complete" if not audit.errors and not index["open_gaps"] else "incomplete",
        "establishes": (
            "that the benches, runners, reducers, pins and documented cold-start invocations "
            "of the declared scope are committed, hashed and cross-referenced. It does not "
            "establish that any command succeeds, RF compliance, or overall T1."
        ),
    }
    return {
        "schema_version": 1,
        "t1_item": ITEM,
        "kind": "testbench-inventory",
        "pins": pins,
        "audit": audit_block,
        "shared_input_groups": groups,
        "families": {
            f: {"readme": m["readme"], "unaccounted_ok": m.get("unaccounted_ok", [])}
            for f, m in sorted(families.items())
        },
        "support_dirs": index["support_dirs"],
        "excluded_bench_like_paths": excl,
        "claims": out_claims,
        "files": files,
    }


def render(obj):
    return (json.dumps(obj, indent=2, sort_keys=True) + "\n").encode()


def envelope_for(inv_hash):
    return {
        "schema_version": 1,
        "kind": "generic",
        "status": "pass",
        "t1_item": ITEM,
        "summary": (
            "Audited testbench inventory for the published measurement scope: benches, runners, "
            "reducers, pins and documented cold-start invocations are committed, hashed and "
            "cross-referenced. Establishes shipped benches only: not that any command succeeds, "
            "not RF compliance, not overall T1."
        ),
        "source": "signoff/testbench-inventory.json via .github/scripts/check-testbench-inventory.py",
        "provenance": {"input": {"path": INVENTORY, "content_hash": inv_hash}},
    }


def check_bindings(audit, inv_bytes, require_envelope=True):
    root = audit.root
    inv_hash = sha256_bytes(inv_bytes)
    try:
        env = json.loads(read_text(root, ENVELOPE))
    except FileNotFoundError:
        if require_envelope:
            audit.err("envelope %s is missing" % ENVELOPE)
        env = None
    except ValueError as exc:
        audit.err("envelope %s is not valid JSON (%s)" % (ENVELOPE, exc))
        env = None
    if env is not None:
        exp = envelope_for(inv_hash)
        if env != exp:
            for k in sorted(set(env) | set(exp)):
                if env.get(k) != exp.get(k):
                    audit.err(
                        "stale envelope: field %r differs from what the current inventory "
                        "requires (regenerate with --write)" % k
                    )
    manifest = load_json(audit, MANIFEST, "manifest")
    if manifest is not None:
        cite = (manifest.get("evidence") or {}).get(str(ITEM))
        want = {"file": ENVELOPE, "content_hash": inv_hash}
        if cite != want:
            audit.err(
                "stale manifest binding: evidence[%d] is %s, expected %s"
                % (ITEM, json.dumps(cite, sort_keys=True), json.dumps(want, sort_keys=True))
            )
    rep_path = os.path.join(root, REPORT)
    if os.path.exists(rep_path):
        try:
            report = json.loads(read_text(root, REPORT))
        except ValueError:
            audit.err("%s is not valid JSON" % REPORT)
            return
        row = None
        for it in report.get("t1_items", report.get("items", [])):
            if isinstance(it, dict) and it.get("id") == ITEM:
                row = it
        if row is None:
            audit.err("%s has no item %d row" % (REPORT, ITEM))
        else:
            cit = row.get("citation") or {}
            ab = cit.get("artifact_binding") or {}
            if row.get("status") != "met" or ab.get("content_hash") != inv_hash \
                    or ab.get("path") != INVENTORY:
                audit.err(
                    "stale rolling report: item %d is %r with binding %s; refresh %s with the "
                    "pinned grader" % (ITEM, row.get("status"), json.dumps(ab, sort_keys=True), REPORT)
                )


def main(argv):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--root", default=os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))
    ap.add_argument("--write", action="store_true", help="regenerate inventory (+ envelope + manifest citation if complete)")
    args = ap.parse_args(argv)
    root = os.path.abspath(args.root)

    audit = Audit(root)
    inv = build(root, audit)
    if inv is None or audit.errors:
        for e in audit.errors:
            print("AUDIT: %s" % e, file=sys.stderr)
        print("FAIL: testbench inventory audit is incomplete (%d finding(s)); nothing written/passed"
              % len(audit.errors), file=sys.stderr)
        return 1
    if inv["audit"]["verdict"] != "complete":
        for g in inv["audit"]["open_gaps"]:
            print("AUDIT: open gap: %s" % g, file=sys.stderr)
        print("FAIL: audit verdict is incomplete (open gaps declared); no pass emitted", file=sys.stderr)
        return 1
    data = render(inv)

    if args.write:
        with open(os.path.join(root, INVENTORY), "wb") as fh:
            fh.write(data)
        inv_hash = sha256_bytes(data)
        with open(os.path.join(root, ENVELOPE), "w") as fh:
            fh.write(json.dumps(envelope_for(inv_hash), indent=2, sort_keys=True) + "\n")
        manifest = json.loads(read_text(root, MANIFEST))
        manifest.setdefault("evidence", {})[str(ITEM)] = {"file": ENVELOPE, "content_hash": inv_hash}
        manifest["evidence"] = dict(sorted(manifest["evidence"].items(), key=lambda kv: int(kv[0])))
        with open(os.path.join(root, MANIFEST), "w") as fh:
            fh.write(json.dumps(manifest, indent=2) + "\n")
        print("wrote %s (%s), %s and the item %d manifest citation" % (INVENTORY, inv_hash, ENVELOPE, ITEM))
        print("now refresh the rolling report with the pinned grader (signoff/README.md)")
        return 0

    try:
        committed = read_bytes(root, INVENTORY)
    except FileNotFoundError:
        print("FAIL: %s is missing; run with --write" % INVENTORY, file=sys.stderr)
        return 1
    if committed != data:
        try:
            old = json.loads(committed.decode())
        except ValueError:
            old = {}
        oldf, newf = old.get("files", {}), inv["files"]
        for p in sorted(set(oldf) | set(newf)):
            if oldf.get(p) != newf.get(p):
                print("STALE: %s: inventory has %s, tree has %s" % (p, oldf.get(p), newf.get(p)), file=sys.stderr)
        print("FAIL: %s is stale against the tracked tree and %s; regenerate with "
              "`python3 -I .github/scripts/check-testbench-inventory.py --write`" % (INVENTORY, INDEX),
              file=sys.stderr)
        return 1
    check_bindings(audit, committed)
    if audit.errors:
        for e in audit.errors:
            print("BINDING: %s" % e, file=sys.stderr)
        print("FAIL: item 9 outer bindings are stale", file=sys.stderr)
        return 1
    print("OK: testbench inventory is fresh (%d claims, %d hashed files) and bound by envelope, manifest and report"
          % (len(inv["claims"]), len(inv["files"])))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
