"""Helpers shared by the signoff inventory checkers (issue #274).

Used by `check-repo-hygiene.py` (T1 item 10), `check-testbench-inventory.py`
(T1 item 9) and `check-artifact-manifests.py`, which load this file by explicit
path (`importlib.util.spec_from_file_location`) so `python3 -I` works: isolated
mode does not put the script's own directory on `sys.path`. Same recipe, and
same reason, as `sim/tools/reducer_common.py` (issue #160).

Stdlib only, as `signoff/README.md` requires of these checkers: nothing here
imports klt, touches the network, or writes to the tree. A caller that
path-loads this module must set `sys.dont_write_bytecode = True` first — the
checkers assert that a read-only run leaves the tree byte-identical, which a
`__pycache__/` write would break.

`check_bindings` is the one envelope-binding implementation both inventory
checkers use. It previously existed twice and had diverged: this copy keeps the
item-9 diagnostics (a stale envelope is reported field by field, and "missing"
stays distinct from "unparsable"), which are strictly the more useful of the
two.
"""

import hashlib
import json
import os
import subprocess


def sha256_bytes(data):
    """The `sha256:<hex>` digest form both inventories and envelopes record."""
    return "sha256:" + hashlib.sha256(data).hexdigest()


def read_bytes(root, rel):
    with open(os.path.join(root, rel), "rb") as fh:
        return fh.read()


def read_text(root, rel, errors="strict"):
    """Decode a repo-relative file as UTF-8.

    Strict by default: an undecodable byte in a file an audit hashes is a
    defect worth surfacing rather than papering over. The item-9 checker scans
    prose documents for documented invocations and passes `errors="replace"`
    there, so one bad byte in a README cannot abort the whole audit.
    """
    return read_bytes(root, rel).decode("utf-8", errors=errors)


def tracked(root):
    """The set of paths in `root`'s git index, via `git ls-files -z`."""
    out = subprocess.run(["git", "-C", root, "ls-files", "-z"], check=True,
                         capture_output=True).stdout.decode()
    return set(p for p in out.split("\0") if p)


def render(obj):
    """The committed on-disk form of an inventory: sorted keys, 2-space indent,
    exactly one trailing newline. The bytes the envelope's content_hash binds."""
    return (json.dumps(obj, indent=2, sort_keys=True) + "\n").encode()


class Audit:
    """Collects audit findings. `root` is the repo root, for callers that want
    it on hand (the item-9 checker reads `audit.root`); findings are reported by
    the caller, which owns the `AUDIT:` / `BINDING:` prefix."""

    def __init__(self, root=None):
        self.root = root
        self.errors = []

    def err(self, msg):
        self.errors.append(msg)


def check_bindings(audit, root, envelope_rel, inv_bytes, envelope_for,
                   require_envelope=True):
    """Assert the committed envelope equals `envelope_for(sha256(inv_bytes))`.

    `envelope_for` is the caller's per-item envelope builder: the envelope
    content is item-specific and stays with its item, only the binding check is
    shared. A stale envelope is reported one finding per differing field, so the
    regeneration diff is readable. With `require_envelope=False` an absent
    envelope is tolerated; an unparsable one is always a finding.
    """
    inv_hash = sha256_bytes(inv_bytes)
    try:
        env = json.loads(read_text(root, envelope_rel))
    except FileNotFoundError:
        if require_envelope:
            audit.err("envelope %s is missing" % envelope_rel)
        env = None
    except ValueError as exc:
        audit.err("envelope %s is not valid JSON (%s)" % (envelope_rel, exc))
        env = None
    if env is not None and not isinstance(env, dict):
        audit.err("envelope %s is not a JSON object" % envelope_rel)
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
