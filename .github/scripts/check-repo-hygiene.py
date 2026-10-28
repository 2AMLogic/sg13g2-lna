#!/usr/bin/env python3
"""Audit and freshness check for the T1 item-10 repo-hygiene inventory (issue #217).

T1 item 10 ("Repo hygiene") asks for a README stating what the block is, its
spec table, and how to reproduce every result; a license; and CI that at
minimum keeps the harness and evidence formats valid. The pinned klt (0.8.0)
accepts item 10 as an artifact-anchored generic envelope bound to an audited
artifact. That artifact is `signoff/repo-hygiene/inventory.json`, derived here
from the tracked tree.

Modes
-----
(default) check   Read-only. Recompute the inventory from the tracked tree and
                  fail on any divergence from the committed inventory or
                  envelope. Needs only python3 (stdlib) and `git ls-files`; no klt, PDK or network.
--write           Regenerate the inventory. The envelope for item 10 is
                  emitted only when the audit is complete. An incomplete audit writes nothing and exits 1.

What is checked mechanically is listed in MECHANICAL_CHECKS and is copied into
the inventory. What is NOT checked (that a declared command exits 0, that the
README prose is accurate) is listed in NOT_CHECKED. A command passes or fails
in its own CI job on each commit; this audit attests only that it is declared,
tracked, and run by CI.

Exit status: 0 ok, 1 audit/freshness failure, 2 usage error.
"""

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys

ITEM = 10
INVENTORY = "signoff/repo-hygiene/inventory.json"
ENVELOPE = "signoff/repo-hygiene/envelope.json"
MANIFEST = "signoff/manifest.json"
REPORT = "signoff/t1-report.json"
WORKFLOW = ".github/workflows/signoff.yml"
README = "README.md"
SPEC = "spec/target-spec.md"
LICENSE = "LICENSE"
BLOCK = "sg13g2-lna"

HYGIENE_FILES = {
    README: "README stating the block, its spec table pointer and the reproduction index",
    LICENSE: "license",
    SPEC: "source of the spec table the README points to",
    WORKFLOW: "CI workflow",
    ".github/scripts/check-repo-hygiene.py": "this audit",
    ".github/scripts/test-check-repo-hygiene.sh": "this audit's self-test",
}

# (job, exact single-line `run:` command, what it keeps valid)
DECLARED_COMMANDS = [
    ("signoff", ".github/scripts/test-check-signoff.sh", "drift-checker self-test"),
    ("signoff", ".github/scripts/check-signoff.sh", "T1 verdict-of-record format and drift"),
    ("record-citations", ".github/scripts/check-record-citations", "evidence record citations resolve"),
    ("testbench-inventory", "python3 -I .github/scripts/check-testbench-inventory.py", "item-9 inventory freshness"),
    ("netlist-freshness", "python3 -I .github/scripts/check-netlist-freshness", "netlist matches schematic inventory"),
    ("layout-freshness", ".github/scripts/check-layout-freshness", "layout evidence agrees with its provenance"),
    ("model-provenance", "sim/models/check_sources.sh", "vendored models match recorded sha256"),
    ("sim-append-only", '.github/scripts/check-sim-append-only --base "origin/${{ github.base_ref }}"',
     "committed sim/ evidence is append-only (pull_request only)"),
    ("local-checks-drift", ".github/scripts/test-run-local-checks.sh", "local runner mirrors the workflow"),
    ("repo-hygiene", ".github/scripts/test-check-repo-hygiene.sh", "this audit's self-test"),
    ("repo-hygiene", "python3 -I .github/scripts/check-repo-hygiene.py", "this audit"),
]

MECHANICAL_CHECKS = [
    "every hygiene file (README, LICENSE, spec source, workflow, this audit) is tracked and present, and is hashed",
    "README names the block, has a 'Target specification' section linking spec/target-spec.md and a 'Reproducing the results' section",
    "spec/target-spec.md contains a markdown table with a header, a separator and at least one data row",
    "LICENSE is non-empty",
    "every declared command's script is tracked and present, and is hashed",
    "every declared command appears verbatim as a single-line `run:` in its named CI job",
    "the committed inventory equals the recomputed one; the envelope binds its hash",
]

NOT_CHECKED = [
    "that any declared command exits 0: each runs in its own CI job on every commit, and the envelope does not encode that outcome",
    "that README prose is accurate or complete beyond the structural checks above",
    "that CI covers every evidence format the repo holds",
]


def sha256_bytes(b):
    return "sha256:" + hashlib.sha256(b).hexdigest()


def read_bytes(root, rel):
    with open(os.path.join(root, rel), "rb") as fh:
        return fh.read()


def read_text(root, rel):
    return read_bytes(root, rel).decode("utf-8")


def tracked(root):
    out = subprocess.run(["git", "-C", root, "ls-files", "-z"], check=True,
                         capture_output=True).stdout.decode()
    return set(p for p in out.split("\0") if p)


def workflow_runs(text):
    """Map job id -> list of single-line `run:` commands (block scalars are skipped)."""
    jobs, cur, in_jobs = {}, None, False
    for line in text.splitlines():
        if re.match(r"^jobs:\s*$", line):
            in_jobs = True
            continue
        if not in_jobs:
            continue
        m = re.match(r"^  ([A-Za-z0-9_-]+):\s*$", line)
        if m:
            cur = m.group(1)
            jobs[cur] = []
            continue
        m = re.match(r"^\s+(?:- )?run:\s+(\S.*?)\s*$", line)
        if m and cur and m.group(1) not in ("|", ">", "|-", ">-"):
            jobs[cur].append(m.group(1))
    return jobs


class Audit:
    def __init__(self):
        self.errors = []

    def err(self, msg):
        self.errors.append(msg)


def has_spec_table(text):
    lines = text.splitlines()
    for i in range(len(lines) - 2):
        if (lines[i].lstrip().startswith("|")
                and re.match(r"^\s*\|[\s:|-]*-[\s:|-]*\|\s*$", lines[i + 1])
                and lines[i + 2].lstrip().startswith("|")):
            return True
    return False


def build(root, audit):
    trk = tracked(root)
    files, scripts = {}, {}

    def hash_file(rel, why):
        if rel not in trk:
            audit.err("%s is not tracked (%s)" % (rel, why))
            return None
        if not os.path.isfile(os.path.join(root, rel)):
            audit.err("%s is tracked but missing from the checkout (%s)" % (rel, why))
            return None
        data = read_bytes(root, rel)
        return {"sha256": sha256_bytes(data), "bytes": len(data), "role": why}

    for rel, why in sorted(HYGIENE_FILES.items()):
        rec = hash_file(rel, why)
        if rec:
            files[rel] = rec

    if README in files:
        text = read_text(root, README)
        if BLOCK not in text.splitlines()[0]:
            audit.err("README first line does not name the block %r" % BLOCK)
        if not re.search(r"^## Target specification\s*$", text, re.M) or "spec/target-spec.md" not in text:
            audit.err("README lacks a 'Target specification' section linking spec/target-spec.md")
        if not re.search(r"^## Reproducing the results\s*$", text, re.M):
            audit.err("README lacks a 'Reproducing the results' section")
    if SPEC in files and not has_spec_table(read_text(root, SPEC)):
        audit.err("%s contains no markdown table (header, separator, data row)" % SPEC)
    if LICENSE in files and not read_text(root, LICENSE).strip():
        audit.err("LICENSE is empty")

    jobs = {}
    if WORKFLOW in files:
        jobs = workflow_runs(read_text(root, WORKFLOW))
    commands = []
    for job, cmd, keeps in DECLARED_COMMANDS:
        script = next(t for t in cmd.split() if t.startswith((".github/", "sim/")))
        rec = hash_file(script, "script of a declared CI command")
        if rec:
            scripts[script] = rec
        if cmd not in jobs.get(job, []):
            audit.err("declared command %r is not run by CI job %r in %s" % (cmd, job, WORKFLOW))
        commands.append({"job": job, "command": cmd, "script": script, "keeps_valid": keeps})

    if audit.errors:
        return None
    return {
        "schema_version": 1,
        "t1_item": ITEM,
        "block": BLOCK,
        "files": files,
        "command_scripts": dict(sorted(scripts.items())),
        "declared_commands": commands,
        "audit": {
            "verdict": "complete",
            "mechanical_checks": MECHANICAL_CHECKS,
            "not_checked": NOT_CHECKED,
        },
    }


def render(inv):
    return (json.dumps(inv, indent=2, sort_keys=True) + "\n").encode()


def envelope_for(inv_hash):
    return {
        "kind": "generic",
        "provenance": {"input": {"content_hash": inv_hash, "path": INVENTORY}},
        "schema_version": 1,
        "source": "%s via .github/scripts/check-repo-hygiene.py" % INVENTORY,
        "status": "pass",
        "summary": ("Audited repo-hygiene inventory: README (block, spec-table pointer, reproduction "
                    "index), license and CI workflow are tracked and hashed, and the declared harness "
                    "and evidence-format checks are tracked scripts run by CI. Establishes presence "
                    "and wiring only: not that any command exits 0, not RF compliance, not overall T1."),
        "t1_item": ITEM,
    }


def check_bindings(root, audit, inv_bytes):
    inv_hash = sha256_bytes(inv_bytes)
    try:
        env = json.loads(read_text(root, ENVELOPE))
    except (OSError, ValueError):
        audit.err("%s is missing or unparsable" % ENVELOPE)
        env = None
    if env is not None and env != envelope_for(inv_hash):
        audit.err("%s does not equal the envelope derived from the inventory (hash %s)" % (ENVELOPE, inv_hash))


def main(argv):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--root", default=os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))
    ap.add_argument("--write", action="store_true", help="regenerate inventory (+ envelope)")
    args = ap.parse_args(argv)
    root = os.path.abspath(args.root)

    audit = Audit()
    inv = build(root, audit)
    if inv is None:
        for e in audit.errors:
            print("AUDIT: %s" % e, file=sys.stderr)
        print("FAIL: repo-hygiene audit is incomplete (%d finding(s)); nothing written/passed"
              % len(audit.errors), file=sys.stderr)
        return 1
    data = render(inv)

    if args.write:
        os.makedirs(os.path.join(root, os.path.dirname(INVENTORY)), exist_ok=True)
        with open(os.path.join(root, INVENTORY), "wb") as fh:
            fh.write(data)
        inv_hash = sha256_bytes(data)
        with open(os.path.join(root, ENVELOPE), "w") as fh:
            fh.write(json.dumps(envelope_for(inv_hash), indent=2, sort_keys=True) + "\n")
        print("wrote %s (%s) and %s" % (INVENTORY, inv_hash, ENVELOPE))
        print("re-attest item 10 (signoff/README.md) and refresh the rolling report")
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
        for sect in ("files", "command_scripts"):
            oldf, newf = old.get(sect, {}), inv[sect]
            for p in sorted(set(oldf) | set(newf)):
                if oldf.get(p) != newf.get(p):
                    print("STALE: %s: inventory has %s, tree has %s" % (p, oldf.get(p), newf.get(p)), file=sys.stderr)
        print("FAIL: %s is stale against the tracked tree; regenerate with "
              "`python3 -I .github/scripts/check-repo-hygiene.py --write`" % INVENTORY, file=sys.stderr)
        return 1
    check_bindings(root, audit, committed)
    if audit.errors:
        for e in audit.errors:
            print("BINDING: %s" % e, file=sys.stderr)
        print("FAIL: item %d outer bindings are stale" % ITEM, file=sys.stderr)
        return 1
    print("OK: repo-hygiene inventory is fresh and bound to item %d (%s)" % (ITEM, sha256_bytes(committed)))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
