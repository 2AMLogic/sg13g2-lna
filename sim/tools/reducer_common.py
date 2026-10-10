"""Helpers shared by the sim reducers (issue #160).

Used by biasref-topology/reduce_biasref.py and lna-bias-pvt/reduce_biasop.py,
which load this file by explicit path (importlib.util.spec_from_file_location)
so `python3 -I` works. Stdlib only. `finite` is deliberately NOT here: the two
reducers validate numbers differently and each keeps its own.
"""
import os


class ReductionError(Exception):
    """Malformed or incomplete evidence (never a measured result)."""


def parse_kv_line(text, tag, source):
    """Return {key: raw_token} from the single `tag ...` line in text."""
    lines = [ln for ln in text.splitlines() if ln.startswith(tag + " ")]
    if not lines:
        raise ReductionError("%s: no %s line" % (source, tag))
    if len(lines) > 1:
        raise ReductionError("%s: %d %s lines (expected exactly one)"
                             % (source, len(lines), tag))
    tokens = lines[0].split()[1:]
    if len(tokens) % 2:
        raise ReductionError("%s: %s line has an odd token count (key "
                             "without value)" % (source, tag))
    out = {}
    for k, raw in zip(tokens[0::2], tokens[1::2]):
        if k in out:
            raise ReductionError("%s: %s key %r repeated" % (source, tag, k))
        out[k] = raw
    return out


def read_text(path):
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            return fh.read()
    except OSError as exc:
        raise ReductionError("%s: unreadable (%s)" % (path, exc)) from None


def write_exclusive(path, text):
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o666)
    with os.fdopen(fd, "w", encoding="utf-8", newline="") as fh:
        fh.write(text)
