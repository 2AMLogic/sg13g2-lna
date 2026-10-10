#!/usr/bin/env python3
"""Installed-PDK identity check + model-input hashing (issue #118).

Usage: pdk_identity.py <pdk.json> <pdk-dir> <models-lib> [extra-file ...]

Offline. Compares the installed PDK's release with the pin in pdk.json
(release_tag, variant), tolerating a leading "v" on either side, and prints
a JSON provenance object on stdout. On failure prints a named preflight
error ("PDK_IDENTITY_MISMATCH" / "PDK_IDENTITY_UNVERIFIABLE" /
"PDK_MODEL_INPUT_MISSING") on stderr and exits 3.

Identity routes (first that yields a value wins):
  tarball-marker   <pdk-dir>/.fetched-version (fetch-ihp-sg13g2.sh install)
  source-checkout  `git -C <pdk-dir> describe --tags --exact-match HEAD`
                   (pdk-dir must itself be a git work tree root)
A path alone is never trusted: no route -> UNVERIFIABLE.

Model-input boundary: the transitive closure of `.lib <file> [section]`,
`.include`/`.inc` and `.osdi_preload`-free references starting from the
corner library (cornerHBT.lib), found by textual scan, plus every extra
file given (the OSDI binaries / cornerMOShv.lib closure). Each file is
SHA-256 hashed. Textual scan only: files loaded by other means (e.g. paths
built inside a model) are not seen -- stated limit, not a signoff verdict.
"""
import hashlib
import json
import os
import re
import subprocess
import sys

INC = re.compile(r'^\s*\.(?:lib|include|inc)\s+(?:"([^"]+)"|\'([^\']+)\'|(\S+))',
                 re.IGNORECASE)


def fail(name, msg):
    sys.stderr.write(f"{name}: {msg}\n")
    sys.exit(3)


def norm(tag):
    tag = tag.strip()
    return tag[1:] if tag[:1] in ("v", "V") and tag[1:2].isdigit() else tag


def identity(pdk_dir):
    marker = os.path.join(pdk_dir, ".fetched-version")
    if os.path.isfile(marker):
        with open(marker, encoding="utf-8", errors="replace") as fh:
            val = fh.read().strip()
        if not val:
            fail("PDK_IDENTITY_UNVERIFIABLE", f"{marker} is empty")
        return "tarball-marker", val
    try:
        top = subprocess.run(["git", "-C", pdk_dir, "rev-parse", "--show-toplevel"],
                             capture_output=True, text=True, check=True).stdout.strip()
        if os.path.realpath(top) == os.path.realpath(pdk_dir):
            tag = subprocess.run(
                ["git", "-C", pdk_dir, "describe", "--tags", "--exact-match", "HEAD"],
                capture_output=True, text=True, check=True).stdout.strip()
            if tag:
                return "source-checkout", tag
    except (OSError, subprocess.CalledProcessError):
        pass
    fail("PDK_IDENTITY_UNVERIFIABLE",
         f"{pdk_dir} has no .fetched-version marker and is not a git checkout "
         "at an exact release tag; cannot verify against the sim/pdk.json pin")


def closure(roots):
    seen, order, todo = set(), [], [os.path.realpath(r) for r in roots]
    while todo:
        f = todo.pop(0)
        if f in seen:
            continue
        if not os.path.isfile(f):
            fail("PDK_MODEL_INPUT_MISSING", f"{f} referenced but not found")
        seen.add(f)
        order.append(f)
        if f.endswith((".osdi", ".so")):
            continue
        with open(f, encoding="utf-8", errors="replace") as fh:
            for line in fh:
                m = INC.match(line)
                if not m:
                    continue
                ref = next(g for g in m.groups() if g)
                if ref.lower().endswith((".lib", ".spice", ".spi", ".mod", ".inc", ".cir")) \
                        or os.sep in ref:
                    cand = ref if os.path.isabs(ref) else os.path.join(os.path.dirname(f), ref)
                    if os.path.isfile(cand):
                        todo.append(os.path.realpath(cand))
                    elif ref.lower().endswith((".lib", ".spice", ".spi", ".inc", ".cir")):
                        fail("PDK_MODEL_INPUT_MISSING",
                             f"{f} references {ref}, not found at {cand}")
    return order


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def main(argv):
    if len(argv) < 4:
        sys.stderr.write(__doc__)
        return 2
    pin_path, pdk_dir, models_lib, extras = argv[1], argv[2], argv[3], argv[4:]
    with open(pin_path, encoding="utf-8") as fh:
        pin = json.load(fh)
    want_tag, want_variant = pin.get("release_tag"), pin.get("variant")
    if not want_tag:
        fail("PDK_IDENTITY_UNVERIFIABLE", f"{pin_path} has no release_tag")
    if want_variant and os.path.basename(os.path.normpath(pdk_dir)) != want_variant:
        fail("PDK_IDENTITY_MISMATCH",
             f"installed variant dir '{os.path.basename(os.path.normpath(pdk_dir))}' "
             f"!= pinned variant '{want_variant}'")
    route, found = identity(pdk_dir)
    if norm(found) != norm(want_tag):
        fail("PDK_IDENTITY_MISMATCH",
             f"installed release '{found}' (via {route}) != pinned '{want_tag}' "
             f"in {pin_path}")
    files = closure([models_lib] + extras)
    print(json.dumps({
        "schema": "sg13g2-lna/pdk-provenance/1",
        "pin_file": "sim/pdk.json",
        "pinned_release_tag": want_tag,
        "pinned_variant": want_variant,
        "verified": True,
        "identity_route": route,
        "installed_release_raw": found,
        "pdk_dir": os.path.realpath(pdk_dir),
        "model_input_boundary": "textual .lib/.include closure from cornerHBT.lib "
                                "plus the listed extra files; not a proof of "
                                "completeness",
        "model_inputs": [{"path": p, "sha256": sha256(p)} for p in files],
    }, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
