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

`run_item_check` (issue #302) is the shared `main()` driver for the same two
inventory checkers, factored for the same reason: their two `main()` bodies
duplicated the whole freshness/binding protocol and had already grown gate
asymmetries that looked like bugs.
"""

import argparse
import hashlib
import json
import os
import subprocess
import sys


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


def run_item_check(argv, *, item, inventory, envelope, build, envelope_for,
                   sections, audit_label, ok_line, gate=None, stale_context="",
                   description=None):
    """Shared `main()` of the two inventory checkers (issue #302).

    `check-repo-hygiene.py` (item 10) and `check-testbench-inventory.py`
    (item 9) carried two near-identical `main()` bodies; this is the one
    implementation of the protocol they both ran:

      1. `build(root, audit)` recomputes the inventory. Audit findings or a
         None return refuse the run: each finding prints as `AUDIT:`, then
         `FAIL: <audit_label> audit is incomplete`.
      2. `gate(inv)`, when given, is the item's extra pre-render refusal —
         item 9's verdict gate. It prints its own findings and returns True
         to refuse; item 10 has none.
      3. `--write` emits the rendered inventory plus the item's
         klt-generic envelope and names the separate re-attestation step in
         signoff/README.md. The inventory directory is created
         `exist_ok=True` unconditionally: a no-op for both committed
         layouts, and one less per-item difference to carry.
      4. Otherwise the committed inventory must equal the recomputed one
         byte for byte — a stale one reports `STALE:` per differing path,
         walked over `sections` — and the committed envelope must bind the
         inventory's hash (`BINDING:` findings via `check_bindings`).

    The keyword-only parameters are exactly the per-item parts:

      item          T1 item number; names the re-attest hint and the
                    binding FAIL line.
      inventory     repo-relative inventory path (written and compared).
      envelope      repo-relative envelope path (written and bound).
      build         f(root, audit) -> inventory dict, or None on findings.
                    Gate contract: the audit gate below checks BOTH
                    `inv is None` and `audit.errors`. Item 10's build
                    converts every late finding into a None return, so its
                    second half is a no-op; item 9's build does not — its
                    late findings come back inside an inventory whose
                    verdict is "incomplete" — so the second half is what
                    surfaces them. Do not "simplify" it to `inv is None`.
      envelope_for  f(inv_hash) -> the item's expected envelope dict.
      sections      inventory sections the STALE walk covers (item 10:
                    files + command_scripts; item 9: files).
      audit_label   the item's name in the incomplete-audit FAIL line.
      ok_line       f(inv, committed) -> the success line (item 10 prints
                    the inventory hash, item 9 its claim/file counts).
      gate          optional pre-render refusal; see step 2.
      stale_context spliced into the stale FAIL line after "tracked tree"
                    (item 9 names the coverage index it must also match).
      description   argparse description (the checker's docstring title).

    The `--root` default resolves from this module's `__file__`: the driver
    serves only checkers that live beside it in `.github/scripts/`, so it
    yields the same repo root the standalone mains computed from their own
    `__file__`. The stale FAIL hint names the running checker via
    `sys.argv[0]`'s basename, so it cannot drift from the script that
    printed it.
    """
    ap = argparse.ArgumentParser(description=description)
    ap.add_argument("--root", default=os.path.abspath(os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "..", "..")))
    ap.add_argument("--write", action="store_true", help="regenerate inventory (+ envelope)")
    args = ap.parse_args(argv)
    root = os.path.abspath(args.root)

    audit = Audit(root)
    inv = build(root, audit)
    if inv is None or audit.errors:
        for e in audit.errors:
            print("AUDIT: %s" % e, file=sys.stderr)
        print("FAIL: %s audit is incomplete (%d finding(s)); nothing written/passed"
              % (audit_label, len(audit.errors)), file=sys.stderr)
        return 1
    if gate is not None and gate(inv):
        return 1
    data = render(inv)

    if args.write:
        os.makedirs(os.path.join(root, os.path.dirname(inventory)), exist_ok=True)
        with open(os.path.join(root, inventory), "wb") as fh:
            fh.write(data)
        inv_hash = sha256_bytes(data)
        with open(os.path.join(root, envelope), "w") as fh:
            fh.write(json.dumps(envelope_for(inv_hash), indent=2, sort_keys=True) + "\n")
        print("wrote %s (%s) and %s" % (inventory, inv_hash, envelope))
        print("re-attest item %d (signoff/README.md) and refresh the rolling report" % item)
        return 0

    try:
        committed = read_bytes(root, inventory)
    except FileNotFoundError:
        print("FAIL: %s is missing; run with --write" % inventory, file=sys.stderr)
        return 1
    if committed != data:
        try:
            old = json.loads(committed.decode())
        except ValueError:
            old = {}
        for sect in sections:
            oldf, newf = old.get(sect, {}), inv[sect]
            for p in sorted(set(oldf) | set(newf)):
                if oldf.get(p) != newf.get(p):
                    print("STALE: %s: inventory has %s, tree has %s"
                          % (p, oldf.get(p), newf.get(p)), file=sys.stderr)
        script = os.path.basename(sys.argv[0])
        print("FAIL: %s is stale against the tracked tree%s; regenerate with "
              "`python3 -I .github/scripts/%s --write`" % (inventory, stale_context, script),
              file=sys.stderr)
        return 1
    check_bindings(audit, root, envelope, committed, envelope_for)
    if audit.errors:
        for e in audit.errors:
            print("BINDING: %s" % e, file=sys.stderr)
        print("FAIL: item %d outer bindings are stale" % item, file=sys.stderr)
        return 1
    print(ok_line(inv, committed))
    return 0
