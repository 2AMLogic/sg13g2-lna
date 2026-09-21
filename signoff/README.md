# klt signoff: this block's graded T1 state

- **Status**: standing convention, established by issue #30. The verdict
  of record for this block's T1 (sim-validated) standing is the committed
  report rendered by `klt signoff --manifest` — never a hand-maintained
  checkbox list in an issue body.
- **Date**: 2026-09-21, issue #30 (companion item-11 work item: #35).
- **Consumes**: `klt signoff` (klayout-tools, pinned release `0.5.0` from
  PyPI) and the vendored checklist below.
- **Does not**: grade anything itself. Every row's verdict comes from the
  tool's own mechanical parse-and-grade; this directory only declares what
  the block is (`block`, `kind`) and where each item's evidence lives.

## What lives here

| Path | What it is |
|---|---|
| `manifest.json` | The block manifest: `block`, `kind`, and the per-item `evidence` map `klt signoff --manifest` grades. The fleet roll-up (2AMLogic/2am#956) consumes exactly this file; `sg13g2-lna` is the row identity. |
| `t1-report.json` | The **verdict of record**: the committed `klt signoff --format json` output. CI re-renders the report on every push and PR and fails on any byte-drift (`.github/scripts/check-signoff.sh`), so a manifest citation whose artifact has since changed fails rather than rotting. |
| `design-evidence-tiers.md` | Vendored copy of the T1-T4 evidence-tier checklist `klt signoff` parses (see provenance below). Vendored so the render is reproducible from this repo alone and carries the eleventh checklist item, which released `klt 0.5.0` does not bundle (see "Why the checklist doc is vendored"). |

Today every item renders `unmet` with `reason: "no_evidence"` — the honest
statement of the gap for a block at this stage, though a richer one than
"nothing exists": this block *does* have committed evidence (schematic +
derived netlist in `design/`, four `sim/` campaigns, a characterization
report in `measurements/`, and a partially ratified
`spec/target-spec.md`). None of it is a `klt`-native evidence envelope,
which is the only thing any row here can cite:

- **Items 2, 3, 4, 7 and 11 need a layout** (GDS, DRC, LVS, extraction,
  supply spec). `layout/` is a stub — there is nothing to run or cite.
- **Items 5 and 6 accept only `klt sim` / `klt yield` envelopes** for this
  analog block. The committed campaigns (`sim/hbt-characterization/`,
  `sim/breakdown-extraction/`, `sim/lna-characterization/`,
  `sim/lna-bias-pvt/`) are ngspice + bash + CSV/Markdown records, not
  `klt` JSON envelopes, so the grader cannot read them even where the
  engineering they represent is real. They also predate the 2026-09-21
  bias-network change (f718094, #34) on `main`, so they are stale as
  evidence against the current design sources anyway — "a passing report
  against last week's netlist is evidence of nothing". The re-run
  decision and the matching-network gap that would gate its verdicts are
  tracked in #33 and #27.
- **Item 8 is the only item a generic envelope may satisfy**, and the
  natural artifact (`measurements/README.md`) is real but currently worse
  than uncited: it documents itself as not-a-verdict (the spec it
  compared against was DRAFT at the time) and its record ids predate
  #34's design change. A hand-rolled wrapper asserting either `pass` or
  `fail` over that stale report states more than the artifact supports.
  Cite it after the characterization campaign is re-run against the
  current design.
- **Items 1, 2, 9 and 10 accept any passing native envelope** — the tool
  cannot check topical relevance for them, so citing them is this
  repo's responsibility, not the grader's. The honest default (per the
  grader contract's own guidance) is to leave them uncited until an
  artifact genuinely backing each claim exists; no `klt` envelope exists
  in this repo today.

Per issue #30: an all-`unmet` manifest is the honest machine-readable
statement of the gap — never hold the manifest back until the block is
further along, and never cite an envelope that does not actually support
the item just to make a row go green.

## The manifest contract

- **`kind: "analog"`** — confirmed against the block, not taken from the
  issue: `spec/target-spec.md` (first-ratification pass, decision record
  `0002-target-spec-first-ratification.md`) declares a single-ended
  cascode SiGe HBT low-noise amplifier; `spec/decision-records/0001-...`
  fixed the bias/supply topology with no digital logic anywhere in the
  signal path, and `sim/pdk.json` instantiates only the `npn13G2` HBT —
  no RTL, no partition boundary. A `mixed-signal` declaration would be
  wrong here.
- **`evidence`** — the map from item id to evidence entry, currently
  empty. When evidence starts landing, cite it honestly:
  - **File-backed** — `{"file": "<repo-root-relative path>", "content_hash": "sha256:<hash>"}`.
    Every citation MUST pin `content_hash` to the committed artifact it
    was produced against (`provenance.input.content_hash` of the cited
    `klt` envelope — see `docs/cli/signoff.md` → "Tier-verdict report"):
    an unpinned citation cannot have its freshness verified, and a
    passing report against last week's netlist is evidence of nothing.
    A mismatched pin renders the item `unmet`/`stale_evidence`.
  - **Command-backed** — `{"command": [<argv>], "cwd": ..., "content_hash": ...}`:
    `klt signoff` runs the command and grades that run's own exit status
    and stdout.
  - **Item key discipline** — bare `"<id>"` for every item on this analog
    block (per-kind `<id>.<analog|digital>` keys exist only for
    mixed-signal blocks).
  - **Items 5 and 6 are kind-restricted too**: item 5 accepts only a
    `klt sim` envelope for this analog block (and the spec table must be
    ratified — verdicts against a DRAFT spec are provisional by
    construction), item 6 only `klt yield`. See `docs/cli/signoff.md` →
    "Items 5, 6 and 8 are kind-restricted too".
  - **Item 7 accepts only a `klt pex` report** — unlike every other
    item, it rejects any other evidence kind; a clean DRC or pre-layout
    sim renders `wrong_kind` (#30's "Things that will bite").
  - **Item 11 must stay uncited while the klt pin is `0.5.0`.** The
    item-11 grading rules (klayout-tools#2057, plus the per-item
    build-grading guard of #2201) are on klayout-tools `main` but not in
    any release; a citation under the pinned 0.5.0 build would fall
    through to rules that do not exist in the running build and could
    render `met` from nothing. The row is present (the vendored
    checklist carries item 11) and renders `unmet`/`no_evidence` — the
    exact "has a row, even if unmet" state issue #30 requires. Cite it
    only after bumping the pin to a release containing #2057/#2201.
    Item 11's blocking work is tracked in the companion issue #35; the
    load-bearing upstream frictions for this block are already on file
    (SiGe-HBT recognition permanently declined — klayout-tools#1242,
    documented for this PDK in `sg13g2-bandgap#4`; tap declaration by
    assertion or disclosure — klayout-tools#2240, unreleased).

## Why the checklist doc is vendored

The tiers checklist is `klt`'s runtime tool data: `klt signoff --manifest`
renders the item skeleton mechanically from the doc, so the checklist and
the grader can never drift. Released `klt 0.5.0` (2026-09-15) bundles the
**ten-item** checklist — the eleventh item (power delivery, structural)
landed on klayout-tools `main` on 2026-09-17 (#2057), ahead of any
release: klayout-tools#2173 tracks the release lag itself. Rendering with
the bundled doc would silently report ten items and no item-11 row at
all, so `signoff/README.md`'s commands and `.github/scripts/check-signoff.sh`
both pass `--tiers-doc signoff/design-evidence-tiers.md` — the documented
vendoring pattern (`docs/cli/signoff.md` → "Where the tier doc comes
from", `KLT_TIERS_DOC`).

**Provenance** (keep updated on every refresh):

| Field | Value |
|---|---|
| Source | `2AMLogic/klayout-tools` `docs/design-evidence-tiers.md` |
| Pinned at | commit `31a3e3c41c08bbd58719e0b99a3b6d19beb9be63` (2026-09-21, repository tip) |
| File SHA-256 | `5ce13a12f12bfeb3ca07f45c7527e3423d69872f7f52a4bd0762099292e1c2e9` |
| Last doc-touching upstream commit | `31a3e3c41c08` (feat(erc): declare a tap by assertion or disclose it as unexpressible, #2240) |
| License | Apache-2.0 (klayout-tools is Apache-2.0; this copy is verbatim, unmodified) |

**Upgrade procedure**: copy the newer doc from klayout-tools verbatim,
update the provenance table, then refresh and commit `t1-report.json`
(the byte-drift gate forces exactly this — the report pins the checklist
it was graded against, and a checker that is not also checking "which
checklist said so" is checking half the question). A newer doc may also
outrun the pinned build (`graded_by_build`, klayout-tools#2201): an item
the pinned `klt` has no rules for renders `unmet` whichever way it is
cited, so guard new-item citations behind a matching klt pin bump.

## The verdict of record and its drift gate

`t1-report.json` is the **current** verdict — a rolling record, not an
append-only `sim/`-style measurement (git history is its own archive).
It is refreshed deliberately, in the same commit as whatever change
re-grades the block:

```bash
python3 -m pip install klayout-tools==0.5.0   # the pinned release
klt signoff --manifest signoff/manifest.json \
  --tiers-doc signoff/design-evidence-tiers.md --format json \
  > signoff/t1-report.json
```

`.github/scripts/check-signoff.sh` (self-tested by
`test-check-signoff.sh`, both run in CI — a checker that cannot fail is
indistinguishable from no checker at all) re-renders and byte-compares on
every push and PR. "Runs clean" follows `docs/cli/signoff.md`'s
exit-code contract: exit 0 (all items met) and exit 3 (ran successfully,
at least one item unmet) are both successful renders — an all-unmet
report is a correct verdict, not a CI failure. The payload gates on its
own fields (`block`, `kind`, `schema_version`, 11 rendered items, no
error envelope), not the exit code alone.

**Known field gap under the current pin.** `klt 0.5.0` predates the
report's `build` and `source_doc_content_hash` fields
(klayout-tools#2175/#2176, unreleased as of the pin), so the committed
record does not name which `klt` build graded it or hash the checklist
it was graded against. The compensating pins are explicit in this repo
today — the PyPI release pin in the command above and in CI's install
step, the vendored doc's committed SHA-256 above, and the CI byte-drift
gate that fails the moment any of the three moves. When a klt release
carrying #2175/#2176/#2201 is pinned, the re-rendered record picks both
fields up and the pin plus doc hashes become machine-checked rather than
prose.

## Sources

- `klayout-tools` grader contract: `docs/cli/signoff.md` → "Tier-verdict
  report" (2AMLogic/klayout-tools).
- T1-T4 ladder and the 11-item checklist: `docs/design-evidence-tiers.md`
  (2AMLogic/klayout-tools) — the vendored copy above.
- This block's gap-to-T1 tracker: issue #4 (this report is its verdict
  of record; the hand-maintained checkbox list is retired).
- Item 11's companion work item: issue #35.
- Fleet roll-up consuming this manifest: 2AMLogic/2am#956.
