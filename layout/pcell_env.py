"""Load IHP SG13G2's own PyCell library headlessly, reproducibly.

Every device in this repo's layout is drawn by the PDK's native PyCells
(``ihp-sg13g2/libs.tech/klayout/python/sg13g2_pycell_lib``), registered by
that package as the KLayout library ``SG13_dev``. This module is the one
place the import environment for that is set up:

* **PDK resolution** -- ``$PDK_ROOT``/``$PDK`` (default ``ihp-sg13g2``), then
  the same fallback prefixes ``sim/env.sh`` searches, so ``sim/`` and
  ``layout/`` agree on which install is in use.
* **Submodule shims** -- ``pypreprocessor`` and ``pycell4klayout-api`` come
  from ``layout/build/pcell-deps/`` at the commits the pinned PDK release
  records (``layout/tools/fetch-pcell-deps.sh``), never from the host
  install, whose copies may be empty (tarball fetch) or a different
  revision.
* **``#ifdef KLAYOUT`` selection** -- the library preprocesses its PyCell
  sources and keeps the KLayout code path only when a ``KLAYOUT``
  environment variable exists or a parent process name contains
  "klayout". A plain ``python`` process has neither, so the variable is
  set here explicitly.
* **No Tcl parameter callbacks** -- ``cni.dlo`` wires PyCell parameter
  callbacks (``Calculate``-driven derived values) through ``tkinter`` and a
  ``parameters.tcl`` tree the v0.3.0 tarball does not ship; with tkinter
  importable but the tree absent, the first ``coerce_parameters`` call
  raises and that instance draws nothing. Blocking tkinter for the import
  turns callbacks off cleanly, so every parameter must be passed
  explicitly (``generate.py`` does: no ``Calculate`` field is relied on).
"""

from __future__ import annotations

import hashlib
import os
import sys
from pathlib import Path

LAYOUT_DIR = Path(__file__).resolve().parent
PCELL_DEPS = LAYOUT_DIR / "build" / "pcell-deps"

_FALLBACK_PREFIXES = (
    "/usr/share/pdk",
    "/usr/local/share/pdk",
    "~/share/pdk",
    "~/.ciel",
    "~/.volare",
)


def resolve_pdk() -> Path:
    """Return ``<PDK_ROOT>/<PDK>`` (the ``ihp-sg13g2`` directory)."""
    pdk = os.environ.get("PDK", "ihp-sg13g2")
    roots = []
    if os.environ.get("PDK_ROOT"):
        roots.append(os.environ["PDK_ROOT"])
    roots.extend(os.path.expanduser(p) for p in _FALLBACK_PREFIXES)
    for root in roots:
        cand = Path(root) / pdk
        if (cand / "libs.tech" / "klayout" / "python" / "sg13g2_pycell_lib").is_dir():
            return cand
    raise SystemExit(
        f"pcell_env: no {pdk} install with libs.tech/klayout/python/sg13g2_pycell_lib "
        "under PDK_ROOT or the usual prefixes (see sim/env.sh)"
    )


def pcell_lib_digest(pdk_dir: Path) -> str:
    """sha256 over the PyCell library's own sources (sorted relative paths +
    bytes) -- recorded in each layout's provenance so a different PDK PyCell
    revision is visible, not silent."""
    lib = pdk_dir / "libs.tech" / "klayout" / "python" / "sg13g2_pycell_lib"
    h = hashlib.sha256()
    for f in sorted(lib.rglob("*")):
        if f.is_file() and "__pycache__" not in f.parts and f.suffix in (".py", ".json"):
            h.update(str(f.relative_to(lib)).encode())
            h.update(b"\0")
            h.update(f.read_bytes())
    return "sha256:" + h.hexdigest()


def load_sg13_dev():
    """Import and register the ``SG13_dev`` PyCell library; return
    ``(pya_module, library, pdk_dir)``."""
    pdk_dir = resolve_pdk()
    for stamp in ("root/pypreprocessor/.fetched-sha", "pycell4klayout-api/.fetched-sha"):
        if not (PCELL_DEPS / stamp).is_file():
            raise SystemExit(
                f"pcell_env: {PCELL_DEPS / stamp} missing -- run layout/tools/fetch-pcell-deps.sh"
            )
    py_dir = pdk_dir / "libs.tech" / "klayout" / "python"
    # Order matters: the pinned shims must shadow whatever the host install
    # carries under the same package names, so they come first.
    sys.path[0:0] = [
        str(PCELL_DEPS / "root"),
        str(PCELL_DEPS / "pycell4klayout-api" / "source" / "python"),
        str(py_dir),
    ]

    os.environ["KLAYOUT"] = "1"
    sys.modules["tkinter"] = None  # type: ignore[assignment]
    try:
        import pya  # noqa: F401  (pip `klayout` provides it)
        import sg13g2_pycell_lib  # noqa: F401  registers SG13_dev
    finally:
        sys.modules.pop("tkinter", None)
    lib = pya.Library.library_by_name("SG13_dev")
    if lib is None:
        raise SystemExit("pcell_env: SG13_dev library did not register")
    return pya, lib, pdk_dir
