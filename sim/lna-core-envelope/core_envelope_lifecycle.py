#!/usr/bin/env python3
"""Stdlib helpers for run_core_envelope.sh's record lifecycle (issue #126).

  fingerprint <out|-> key=value ...   write the run fingerprint JSON
  compare <stored.json> <new.json>    exit 0 if the digests match; else print
                                      the differing component names, exit 1
  finalize <out> <fingerprint.json> <file> ...   write the finalized marker

A value of the form `file:<path>` is replaced by that file's SHA-256, so a
changed template/DUT/model changes the fingerprint without the shell having
to hash anything. The digest covers every component, so a stored fingerprint
that was edited or truncated cannot match.
"""
import hashlib
import json
import os
import sys
import time


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def digest(components):
    blob = json.dumps(components, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(blob.encode()).hexdigest()


def write_exclusive(path, text):
    """Create `path` atomically and never replace an existing one."""
    tmp = f"{path}.tmp{os.getpid()}"
    with open(tmp, "x") as fh:
        fh.write(text)
        fh.flush()
        os.fsync(fh.fileno())
    try:
        os.link(tmp, path)
    finally:
        os.unlink(tmp)


def cmd_fingerprint(out, items):
    comp = {}
    for it in items:
        k, _, v = it.partition("=")
        if not k or not _:
            sys.exit(f"core_envelope_lifecycle.py: bad component {it!r}")
        comp[k] = sha256_file(v[5:]) if v.startswith("file:") else v
    doc = {"schema": 1, "components": comp, "digest": digest(comp)}
    text = json.dumps(doc, indent=1, sort_keys=True) + "\n"
    if out == "-":
        sys.stdout.write(text)
    else:
        write_exclusive(out, text)
    return 0


def load(path):
    with open(path) as fh:
        doc = json.load(fh)
    comp = doc["components"]
    if doc.get("schema") != 1 or digest(comp) != doc.get("digest"):
        raise ValueError("fingerprint digest does not match its components")
    return doc


def cmd_compare(stored, new):
    try:
        a = load(stored)
    except (OSError, ValueError, KeyError) as e:
        print(f"unreadable stored fingerprint ({e})")
        return 1
    b = load(new)
    if a["digest"] == b["digest"]:
        return 0
    ca, cb = a["components"], b["components"]
    for k in sorted(set(ca) | set(cb)):
        if ca.get(k) != cb.get(k):
            print(k)
    return 1


def cmd_finalize(out, fp, files):
    doc = {"schema": 1, "fingerprint_digest": load(fp)["digest"],
           "finalized_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
           "published": {os.path.basename(f): sha256_file(f) for f in files}}
    write_exclusive(out, json.dumps(doc, indent=1, sort_keys=True) + "\n")
    return 0


def main(argv):
    if len(argv) >= 3 and argv[1] == "fingerprint":
        return cmd_fingerprint(argv[2], argv[3:])
    if len(argv) == 4 and argv[1] == "compare":
        return cmd_compare(argv[2], argv[3])
    if len(argv) >= 5 and argv[1] == "finalize":
        return cmd_finalize(argv[2], argv[3], argv[4:])
    sys.exit(__doc__)


if __name__ == "__main__":
    sys.exit(main(sys.argv))
