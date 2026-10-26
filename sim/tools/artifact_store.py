#!/usr/bin/env python3
"""Store a run's raw outputs in the artifact store; commit only a manifest.

    python3 -I sim/tools/artifact_store.py put --bench <bench> --run-id <id> \
        --scratch <dir> [--repo-root <dir>]

Every regular file under <dir> (a git-ignored scratch directory the run
script staged its raw outputs into) is uploaded with `klt artifact put` and
named `<bench>/<run-id>/<path relative to scratch>`. On success two files
are written, and only then:

    manifests/artifacts/<bench>-<run-id>.manifest.json   klt manifest; every
        uri is `artifact:<key>`; no storage location is written
    manifests/artifacts/<bench>-<run-id>.summary.md      name, size, sha256
        per object

Fail closed: if $KLT_ARTIFACT_BROKER is unset, `klt` is missing or has no
`artifact put`, the broker is unreachable or refuses, or the returned
manifest does not describe exactly the staged files, the exit status is
nonzero and NOTHING is written under manifests/. A manifest is never
overwritten (evidence is append-only); a clashing run id is refused.

Exit status: 0 ok, 2 usage, 3 environment (broker/klt), 4 store or
manifest failure.

Stdlib only; needs no PDK or ngspice. The store itself is reached only
through `klt`, so no broker URL or credential appears in this repo.
"""

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

EXIT_USAGE, EXIT_ENV, EXIT_STORE = 2, 3, 4
NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
URI_RE = re.compile(r"^artifact:[^/\s]\S*$")
SHA_RE = re.compile(r"^[0-9a-f]{64}$")
MANIFEST_DIR = os.path.join("manifests", "artifacts")


class StoreError(Exception):
    def __init__(self, code, msg):
        super().__init__(msg)
        self.code = code


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def preflight():
    """Return the klt path, or raise StoreError (exit 3)."""
    if not os.environ.get("KLT_ARTIFACT_BROKER"):
        raise StoreError(EXIT_ENV, "KLT_ARTIFACT_BROKER is unset; run on a host with the artifact broker "
                                   "(a fleet worker). Nothing was stored or written.")
    klt = shutil.which("klt")
    if klt is None:
        raise StoreError(EXIT_ENV, "klt is not on PATH. Nothing was stored or written.")
    try:
        r = subprocess.run([klt, "artifact", "put", "--help"], capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.SubprocessError) as exc:
        raise StoreError(EXIT_ENV, "cannot run `klt artifact put --help`: %s" % exc)
    if r.returncode != 0 or "--manifest" not in r.stdout:
        raise StoreError(EXIT_ENV, "this klt has no usable `artifact put` (need a newer klayout-tools "
                                   "on the writer host). Nothing was stored or written.")
    return klt


def staged_files(scratch):
    files = []
    for dirpath, dirnames, filenames in os.walk(scratch):
        dirnames.sort()
        for fn in sorted(filenames):
            p = os.path.join(dirpath, fn)
            if os.path.islink(p) or not os.path.isfile(p):
                raise StoreError(EXIT_USAGE, "%s is not a regular file" % p)
            if os.path.getsize(p) == 0:
                raise StoreError(EXIT_USAGE, "%s is empty (a store entry needs size >= 1)" % p)
            files.append(p)
    if not files:
        raise StoreError(EXIT_USAGE, "no files staged under %s" % scratch)
    return files


def check_manifest(manifest, expected):
    """expected: {name: (sha256, size)}. Raise StoreError unless the manifest matches exactly."""
    if not isinstance(manifest, dict) or manifest.get("schema_version") != 1 \
            or not isinstance(manifest.get("entries"), list):
        raise StoreError(EXIT_STORE, "klt wrote a manifest that is not schema_version 1")
    seen = {}
    for e in manifest["entries"]:
        if not isinstance(e, dict) or not isinstance(e.get("uri"), str) or not URI_RE.match(e["uri"]):
            raise StoreError(EXIT_STORE, "manifest entry without an artifact:<key> uri: %r" % (e,))
        seen[e.get("name")] = e
    if set(seen) != set(expected):
        raise StoreError(EXIT_STORE, "manifest names %s differ from the staged files %s"
                         % (sorted(map(str, seen)), sorted(expected)))
    for name, (sha, size) in expected.items():
        e = seen[name]
        if e.get("sha256") != sha or e.get("size") != size:
            raise StoreError(EXIT_STORE, "manifest entry %s does not match the staged bytes" % name)


def summary_md(bench, run_id, manifest_rel, entries):
    lines = ["# Artifact summary: %s %s" % (bench, run_id), "",
             "Raw outputs of this run are in the artifact store, not in git. Manifest: `%s`." % manifest_rel,
             "Verify with `klt artifact verify %s` on a host with `$KLT_ARTIFACT_BROKER`." % manifest_rel, "",
             "| name | size (bytes) | sha256 |", "|---|---:|---|"]
    for e in sorted(entries, key=lambda x: x["name"]):
        lines.append("| `%s` | %d | `%s` |" % (e["name"], e["size"], e["sha256"]))
    return "\n".join(lines) + "\n"


def put(bench, run_id, scratch, repo_root):
    for label, v in (("--bench", bench), ("--run-id", run_id)):
        if not NAME_RE.match(v):
            raise StoreError(EXIT_USAGE, "%s %r is not a plain identifier" % (label, v))
    if not os.path.isdir(scratch):
        raise StoreError(EXIT_USAGE, "scratch dir %s does not exist" % scratch)
    mdir = os.path.join(repo_root, MANIFEST_DIR)
    final_manifest = os.path.join(mdir, "%s-%s.manifest.json" % (bench, run_id))
    final_summary = os.path.join(mdir, "%s-%s.summary.md" % (bench, run_id))
    for p in (final_manifest, final_summary):
        if os.path.lexists(p):
            raise StoreError(EXIT_STORE, "%s exists; manifests are append-only, use a new run id" % p)
    klt = preflight()
    files = staged_files(scratch)
    expected = {}
    for p in files:
        name = "%s/%s/%s" % (bench, run_id, os.path.relpath(p, scratch).replace(os.sep, "/"))
        expected[name] = (sha256_file(p), os.path.getsize(p))
        files[files.index(p)] = (p, name)

    with tempfile.TemporaryDirectory(prefix="artifact-store-") as tmp:
        tmp_manifest = os.path.join(tmp, "manifest.json")
        for p, name in files:
            try:
                r = subprocess.run([klt, "artifact", "put", "--manifest", tmp_manifest, "--name", name, p],
                                   capture_output=True, text=True, timeout=3600)
            except (OSError, subprocess.SubprocessError) as exc:
                raise StoreError(EXIT_STORE, "klt artifact put failed for %s: %s" % (name, exc))
            if r.returncode != 0:
                raise StoreError(EXIT_STORE, "klt artifact put failed for %s (exit %d): %s"
                                 % (name, r.returncode, (r.stderr or r.stdout).strip()[-500:]))
        try:
            with open(tmp_manifest, encoding="utf-8") as fh:
                manifest = json.load(fh)
        except (OSError, ValueError) as exc:
            raise StoreError(EXIT_STORE, "klt left no readable manifest: %s" % exc)
        check_manifest(manifest, expected)
        text = json.dumps(manifest, indent=2, sort_keys=True) + "\n"
        rel = os.path.relpath(final_manifest, repo_root).replace(os.sep, "/")
        md = summary_md(bench, run_id, rel, manifest["entries"])
        os.makedirs(mdir, exist_ok=True)
        # Exclusive create: a concurrent writer of the same id loses, nothing is overwritten.
        try:
            with open(final_manifest, "x", encoding="utf-8") as fh:
                fh.write(text)
            try:
                with open(final_summary, "x", encoding="utf-8") as fh:
                    fh.write(md)
            except OSError:
                os.unlink(final_manifest)
                raise
        except OSError as exc:
            raise StoreError(EXIT_STORE, "cannot write manifest files: %s" % exc)
    return final_manifest, final_summary


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("put", help="upload the scratch dir and write the manifest + summary")
    p.add_argument("--bench", required=True)
    p.add_argument("--run-id", required=True)
    p.add_argument("--scratch", required=True)
    p.add_argument("--repo-root", default=os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))
    a = ap.parse_args(argv)
    try:
        m, s = put(a.bench, a.run_id, os.path.abspath(a.scratch), os.path.abspath(a.repo_root))
    except StoreError as exc:
        print("artifact_store.py: %s" % exc, file=sys.stderr)
        return exc.code
    print("artifact_store.py: wrote %s and %s" % (m, s))
    return 0


if __name__ == "__main__":
    sys.exit(main())
