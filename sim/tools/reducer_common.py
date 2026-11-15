"""Helpers shared by the sim reducers (issues #160, #280).

Used by biasref-topology/reduce_biasref.py and lna-bias-pvt/reduce_biasop.py,
which load this file by explicit path (importlib.util.spec_from_file_location)
so `python3 -I` works. Stdlib only. `finite` is deliberately NOT here: the two
reducers validate numbers differently and each keeps its own. `require` takes
that validator injected as its last argument, so each reducer passes its own
`finite` and the two grammars stay separate. The startup verdict rule and its
two thresholds (issue #280) grade a spec row, so they are defined here once.
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


def startup_id(cell):
    """Log/point id of a startup cell: startup_<label>_<T>c_vdd<V>v."""
    return "startup_%s_%sc_vdd%sv" % cell


SPREAD_LIMIT_PCT = 2.0
OP_MISMATCH_LIMIT_PCT = 5.0


def require(kv, keys, tag, source, finite):
    """Check `keys` are present in `kv` and return them mapped through the
    injected `finite` (each reducer passes its own; the two number grammars
    deliberately differ)."""
    missing = [k for k in keys if k not in kv]
    if missing:
        raise ReductionError("%s: %s line missing required key(s): %s"
                             % (source, tag, ", ".join(missing)))
    return {k: finite(kv[k], k, source) for k in keys}


def startup_verdict(end, s2, s3, opic):
    """Grade one startup row against its op point: returns (spread_pct,
    end_vs_op_pct, PASS|NO-RINGING-FAIL|OP-MISMATCH-FAIL|LATCHED-ZERO)."""
    mx, mn = max(end, s2, s3), min(end, s2, s3)
    mean = (end + s2 + s3) / 3.0
    spread = 100.0 * (mx - mn) / mean if mean > 0 else 999
    dvsop = 100.0 * (end - opic) / opic if opic > 0 else 999
    verdict = "PASS"
    if spread > SPREAD_LIMIT_PCT:
        verdict = "NO-RINGING-FAIL"
    if dvsop > OP_MISMATCH_LIMIT_PCT or dvsop < -OP_MISMATCH_LIMIT_PCT:
        verdict = "OP-MISMATCH-FAIL"
    if end <= 0:
        verdict = "LATCHED-ZERO"
    return spread, dvsop, verdict
