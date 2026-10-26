#!/usr/bin/env python3
"""Validate manifests/artifacts/ (issue #222).

New sim/signoff evidence bytes live in the artifact store; git keeps only
`manifests/artifacts/<bench>-<run-id>.manifest.json` (klt artifact manifest,
schema_version 1) plus a Markdown summary. This check is read-only and
stdlib-only (no klt, broker or network; the pinned klt 0.7.0 has no
`artifact`). For every tracked *.manifest.json under manifests/artifacts/:

  * schema: schema_version 1, `entries` a non-empty list, each entry exactly
    sha256/size/kind/producer/uri (+ optional name, media_type), with the
    shapes klt's own validator enforces;
  * every uri is `artifact:<key>` and the key's last segment is the sha256;
  * no object's sha256 equals the sha256 of any other tracked file (a stored
    object must not also be committed);
  * every manifest has its .summary.md and vice versa;
  * no file under manifests/ names a storage location (`s3://`, `arn:aws:`).

Usage: check-artifact-manifests.py [--root DIR]
Exit status: 0 ok, 1 failure, 2 usage.
"""

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys

DIR = "manifests/artifacts/"
REQUIRED = {"sha256", "size", "kind", "producer", "uri"}
OPTIONAL = {"name", "media_type"}
PRODUCER = {"tool", "version", "loom.repo", "commit"}
KINDS = {"evidence", "transcript", "log", "pdk"}
SHA_RE = re.compile(r"^[0-9a-f]{64}$")
URI_RE = re.compile(r"^artifact:([^/\s]\S*)$")
LOCATION_RE = re.compile(r"s3://|arn:aws:")


def tracked(root):
    out = subprocess.run(["git", "-C", root, "ls-files", "-z"], check=True, capture_output=True).stdout.decode()
    return sorted(p for p in out.split("\0") if p)


def entry_problems(e):
    if not isinstance(e, dict):
        return ["entry is not an object"]
    p = []
    if REQUIRED - set(e):
        p.append("missing " + ", ".join(sorted(REQUIRED - set(e))))
    if set(e) - REQUIRED - OPTIONAL:
        p.append("unknown field(s) " + ", ".join(sorted(set(e) - REQUIRED - OPTIONAL)))
    sha = e.get("sha256")
    if not isinstance(sha, str) or not SHA_RE.match(sha):
        p.append("sha256 must be 64 lowercase hex digits")
    size = e.get("size")
    if not isinstance(size, int) or isinstance(size, bool) or size < 1:
        p.append("size must be a positive integer")
    if e.get("kind") not in KINDS:
        p.append("kind must be one of " + ", ".join(sorted(KINDS)))
    pr = e.get("producer")
    if not isinstance(pr, dict) or set(pr) != PRODUCER:
        p.append("producer must carry exactly " + ", ".join(sorted(PRODUCER)))
    else:
        for k in ("tool", "version", "loom.repo"):
            if not isinstance(pr[k], str) or not pr[k]:
                p.append("producer.%s must be a non-empty string" % k)
        if pr["commit"] is not None and not isinstance(pr["commit"], str):
            p.append("producer.commit must be a string or null")
    uri = e.get("uri")
    m = URI_RE.match(uri) if isinstance(uri, str) else None
    if not m:
        p.append("uri %r is not artifact:<key>" % (uri,))
    elif m.group(1).rsplit("/", 1)[-1] != sha:
        p.append("uri key does not end in the entry's sha256")
    for k in OPTIONAL:
        if k in e and not isinstance(e[k], str):
            p.append("%s must be a string" % k)
    return p


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root", default=os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
    root = os.path.abspath(ap.parse_args(argv).root)
    files = tracked(root)
    mine = [f for f in files if f.startswith("manifests/")]
    manifests = [f for f in mine if f.startswith(DIR) and f.endswith(".manifest.json")]
    summaries = [f for f in mine if f.startswith(DIR) and f.endswith(".summary.md")]
    errors = []

    for f in mine:
        try:
            text = open(os.path.join(root, f), encoding="utf-8", errors="replace").read()
        except OSError as exc:
            errors.append("%s: unreadable: %s" % (f, exc))
            continue
        if LOCATION_RE.search(text):
            errors.append("%s: names a storage location (s3:// or arn:aws:)" % f)

    shas = {}
    for f in manifests:
        stem = f[: -len(".manifest.json")]
        if stem + ".summary.md" not in summaries:
            errors.append("%s: no matching .summary.md" % f)
        try:
            m = json.load(open(os.path.join(root, f), encoding="utf-8"))
        except (OSError, ValueError) as exc:
            errors.append("%s: not valid JSON: %s" % (f, exc))
            continue
        if not isinstance(m, dict) or m.get("schema_version") != 1 or set(m) != {"schema_version", "entries"} \
                or not isinstance(m.get("entries"), list) or not m["entries"]:
            errors.append("%s: not {schema_version: 1, entries: [non-empty]}" % f)
            continue
        for i, e in enumerate(m["entries"]):
            for prob in entry_problems(e):
                errors.append("%s: entries[%d]: %s" % (f, i, prob))
            if isinstance(e, dict) and isinstance(e.get("sha256"), str):
                shas.setdefault(e["sha256"], []).append("%s entries[%d]" % (f, i))
    for s in summaries:
        if s[: -len(".summary.md")] + ".manifest.json" not in manifests:
            errors.append("%s: no matching .manifest.json" % s)

    if shas:
        for f in files:
            if f.startswith(DIR):
                continue
            path = os.path.join(root, f)
            if not os.path.isfile(path) or os.path.islink(path):
                continue
            h = hashlib.sha256()
            with open(path, "rb") as fh:
                for chunk in iter(lambda: fh.read(1 << 20), b""):
                    h.update(chunk)
            if h.hexdigest() in shas:
                errors.append("%s is committed AND stored as %s" % (f, "; ".join(shas[h.hexdigest()])))

    if errors:
        for e in errors:
            print("FAIL: " + e, file=sys.stderr)
        return 1
    print("OK: %d manifest(s), %d object(s) checked" % (len(manifests), sum(len(v) for v in shas.values())))
    return 0


if __name__ == "__main__":
    sys.exit(main())
