#!/usr/bin/env python3
"""Layout-citation scope guard for the T1 signoff record (issue #80).

A byte-consistent signoff report can still overclaim: if a layout
envelope for a PARTIAL cell (layout/<cell>/realization.json lists
out_of_scope instances) ever renders item 2, 3 or 4 `met`, the block-level
row would be backed by evidence that does not describe the block. This
guard validates the applicability of each layout citation. It never
rewrites or re-grades a verdict: klt stays the sole grader; the rendered
status is only read to see whether a row is `met`.

For every manifest evidence entry on items 2 (Layout), 3 (DRC) and 4 (LVS)
that cites a file:
  * the cited file's directory must hold realization.json and
    <top_cell>.provenance.json (scope metadata); missing/malformed -> failure,
    never a silent "full scope";
  * realization.json's in_scope/out_of_scope must partition the instances
    of the netlist it names (parsed with layout/lvs_reference.py's
    parse_netlist, same check as the LVS-reference generator);
  * input binding: the report's provenance.input.content_hash, the
    manifest entry's content_hash and provenance.json's gds_sha256 must all
    be the same sha256 (and the report's input role must be "layout");
  * scope is `full` only when out_of_scope is empty; otherwise partial,
    and a `met` row (items 2/3/4) backed by it is rejected.
Uncited rows, and partial evidence whose row is not `met`, pass.

Usage: check-signoff-scope.py --root DIR --manifest REL --report PATH
Stdlib only; no klt, ngspice, PDK or layout regeneration.
"""
import argparse
import importlib.util
import json
import sys
from pathlib import Path

LAYOUT_ITEMS = {"2": "Layout", "3": "DRC clean", "4": "LVS clean"}
HERE = Path(__file__).resolve().parent


def load_parse_netlist():
    p = HERE.parent.parent / "layout" / "lvs_reference.py"
    spec = importlib.util.spec_from_file_location("lvs_reference", p)
    mod = importlib.util.module_from_spec(spec)
    sys.dont_write_bytecode = True
    spec.loader.exec_module(mod)
    return mod.parse_netlist


def jload(path):
    try:
        return json.loads(path.read_text()), None
    except Exception as e:  # noqa: BLE001
        return None, str(e)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", required=True)
    ap.add_argument("--manifest", default="signoff/manifest.json")
    ap.add_argument("--report", required=True, help="rendered klt signoff JSON")
    a = ap.parse_args()
    root = Path(a.root).resolve()
    errs = []

    manifest, e = jload(root / a.manifest)
    report, e2 = jload(Path(a.report))
    if manifest is None or report is None:
        print(f"signoff-scope: cannot read manifest/report ({e or e2})", file=sys.stderr)
        return 1
    status = {str(i.get("id")): i.get("status") for i in report.get("items", [])}
    parse_netlist = load_parse_netlist()
    remediation = (
        "remediation: withdraw the partial-layout citation from signoff/manifest.json "
        "(and refresh the record), or supply evidence for the complete block "
        "(see signoff/README.md, 'Layout scope guard')"
    )

    for item, entry in manifest.get("evidence", {}).items():
        if item not in LAYOUT_ITEMS:
            continue
        for ev in entry if isinstance(entry, list) else [entry]:
            rel = ev.get("file") if isinstance(ev, dict) else None
            if not rel:
                continue
            tag = f"item {item} ({LAYOUT_ITEMS[item]}) cites {rel}"
            n0 = len(errs)
            cdir = (root / rel).parent
            rep, err = jload(root / rel)
            if rep is None:
                errs.append(f"{tag}: cited report unreadable ({err})")
                continue
            rz, err = jload(cdir / "realization.json")
            if rz is None:
                errs.append(f"{tag}: missing/invalid scope metadata {cdir.name}/realization.json ({err}); "
                            "scope is never assumed full")
                continue
            prov, err = jload(
                cdir / f"{rz.get('top_cell', cdir.name)}.provenance.json")
            if prov is None:
                errs.append(f"{tag}: missing/invalid scope input hash file "
                            f"{cdir.name}/{rz.get('top_cell', cdir.name)}.provenance.json ({err})")
                continue
            ins, outs, nl = rz.get("in_scope"), rz.get("out_of_scope"), rz.get("netlist")
            if not (isinstance(ins, dict) and isinstance(outs, dict) and isinstance(nl, str)):
                errs.append(f"{tag}: realization.json lacks netlist/in_scope/out_of_scope")
                continue
            try:
                cards = parse_netlist(root / nl)
            except (OSError, SystemExit) as ex:
                errs.append(f"{tag}: cannot parse declared netlist {nl} ({ex})")
                continue
            both = sorted(set(ins) & set(outs))
            missing = sorted(set(cards) - set(ins) - set(outs))
            stale = sorted((set(ins) | set(outs)) - set(cards))
            if both or missing or stale:
                errs.append(f"{tag}: realization.json does not partition {nl}: in both={both} "
                            f"unassigned={missing} not-in-netlist={stale}")
                continue
            # input-hash binding
            rin = (rep.get("provenance") or {}).get("input") or {}
            rhash, mhash = rin.get("content_hash"), ev.get("content_hash")
            shash = prov.get("gds_sha256")
            shash = f"sha256:{shash}" if isinstance(shash, str) and not shash.startswith("sha256:") else shash
            if rin.get("role") != "layout" or not rhash:
                errs.append(f"{tag}: report has no provenance.input (role layout + content_hash)")
            elif not mhash or not shash or not (rhash == mhash == shash):
                errs.append(f"{tag}: input hash disagreement: report={rhash} manifest={mhash} "
                            f"scope(provenance gds_sha256)={shash}")
            if len(errs) > n0:
                continue
            drawn, total = len(ins), len(cards)
            if outs and status.get(item) == "met":
                errs.append(f"{tag}: row is `met` but the evidence covers a partial scope "
                            f"({drawn} of {total} instances drawn, {len(outs)} undrawn); "
                            "a partial layout cannot establish block-level "
                            f"{LAYOUT_ITEMS[item]}")

    if errs:
        print("FAIL: signoff scope guard (issue #80):", file=sys.stderr)
        for m in errs:
            print(f"  signoff-scope: {m}", file=sys.stderr)
        print(f"  {remediation}", file=sys.stderr)
        return 1
    print("OK: layout citations are scope-valid (no met row backed by a partial layout)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
