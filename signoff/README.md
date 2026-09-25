# klt signoff: this block's graded T1 state

- **Status**: standing convention, established by issue #30. The verdict
  of record for this block's T1 (sim-validated) standing is the committed
  report rendered by `klt signoff --manifest` — never a hand-maintained
  checkbox list in an issue body.
- **Date**: 2026-09-21, issue #30 (companion item-11 work item: #35).
- **Consumes**: `klt signoff` (klayout-tools, pinned release `0.6.0` from
  PyPI) and the vendored checklist below.
- **Does not**: grade anything itself. Every row's verdict comes from the
  tool's own mechanical parse-and-grade; this directory only declares what
  the block is (`block`, `kind`) and where each item's evidence lives.

## What lives here

| Path | What it is |
|---|---|
| `manifest.json` | The block manifest: `block`, `kind`, and the per-item `evidence` map `klt signoff --manifest` grades. The fleet roll-up (2AMLogic/2am#956) consumes exactly this file; `sg13g2-lna` is the row identity. |
| `t1-report.json` | The **verdict of record**: the committed `klt signoff --format json` output. CI re-renders the report on every push and PR and fails on any byte-drift (`.github/scripts/check-signoff.sh`), so a manifest citation whose artifact has since changed fails rather than rotting. |
| `design-evidence-tiers.md` | Vendored copy of the T1-T4 evidence-tier checklist `klt signoff` parses (see provenance below). Vendored so the render is reproducible from this repo alone, independent of whichever doc a given installed `klt` build happens to bundle (see "Why the checklist doc is vendored"). |

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
  - **Item 11 stays uncited — no evidence exists, not a tooling gap.**
    Under the previous `0.5.0` pin this item additionally had to stay
    uncited on tooling grounds: the item-11 grading rules
    (klayout-tools#2057, plus the per-item build-grading guard of #2201)
    were on klayout-tools `main` but not in any release, so a citation
    under the pinned 0.5.0 build would have fallen through to rules that
    did not exist in the running build and could have rendered `met` from
    nothing. **`klt 0.6.0` ships both #2057 and #2201** (klayout-tools
    `CHANGELOG.md@v0.6.0`), which retires that specific risk — a genuine
    item-11 citation under the current pin now grades against real rules,
    not a silent fall-through. The rendered report's per-row
    `graded_by_build: true` field (also new in 0.6.0) is the machine-checkable
    confirmation of that fact. What has not changed: this repo has no
    layout, so there is no `klt erc` supply-spec run to cite — item 11 stays
    uncited for the same reason items 2, 3, 4 and 7 do (no artifact exists
    yet), and renders `unmet`/`no_evidence` — the exact "has a row, even if
    unmet" state issue #30 requires. Item 11's blocking work (the actual
    layout and supply-spec evidence) is tracked in the companion issue #35;
    the load-bearing upstream frictions for this block are already on file
    (SiGe-HBT recognition permanently declined — klayout-tools#1242,
    documented for this PDK in `sg13g2-bandgap#4`; tap declaration by
    assertion or disclosure — klayout-tools#2240, shipped in 0.6.0).

## Why the checklist doc is vendored

The tiers checklist is `klt`'s runtime tool data: `klt signoff --manifest`
renders the item skeleton mechanically from the doc, so the checklist and
the grader can never drift. The *original* reason to vendor no longer
holds: released `klt 0.5.0` (2026-09-15) bundled only the **ten-item**
checklist (item 11, power delivery/structural, landed on klayout-tools
`main` on 2026-09-17, #2057, ahead of any release — klayout-tools#2173
tracked that release lag). **`klt 0.6.0`'s bundled doc carries item 11**,
so rendering against the bundled copy would no longer silently drop the
row.

The vendoring is kept anyway, for the **independent** reason
`signoff/README.md` has always also given: reproducibility from this repo
alone. Which checklist a render used against a given installed `klt`
build is otherwise an environment fact, not a repo fact — a different
machine with a different installed `klayout-tools` version could bundle a
different doc revision and silently re-grade this block's evidence
against different item text. Pinning the exact bytes here, alongside the
committed report's own `source_doc_content_hash` (new in 0.6.0, see
below), makes the render fully reconstructible from a checkout of this
repo, independent of whatever a given `klt` install happens to bundle.
`signoff/README.md`'s commands and `.github/scripts/check-signoff.sh`
both pass `--tiers-doc signoff/design-evidence-tiers.md` — the documented
vendoring pattern (`docs/cli/signoff.md` → "Where the tier doc comes
from", `KLT_TIERS_DOC`).

**Provenance** (keep updated on every refresh):

| Field | Value |
|---|---|
| Source | `2AMLogic/klayout-tools` `docs/design-evidence-tiers.md` |
| Pinned at | commit `c622e8addb362491664d44ba4d717f354ca88bbd` (2026-09-22, the `v0.6.0` tag commit) |
| File SHA-256 | `63eeec72e3d849761cf32dcf091af5728b069b1515e32bb3138e9454303671e5` |
| Last doc-touching upstream commit | `0882541638acaec9ceb43c4df77b47d5a1a179db` (feat(signoff): carry a mixed-signal manifest's declared partition boundary, #2303) |
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
python3 -m pip install klayout-tools==0.6.0   # the pinned release
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

**Field gap closed under the current pin.** `klt 0.5.0` predated the
report's `build` and `source_doc_content_hash` fields
(klayout-tools#2175/#2176); under that pin the committed record did not
name which `klt` build graded it or hash the checklist it was graded
against, so this repo carried the equivalent facts as prose — the PyPI
release pin in the command above and in CI's install step, and the
vendored doc's committed SHA-256 in the Provenance table. **`klt 0.6.0`
ships both fields.** The committed `t1-report.json` now carries a
top-level `build` object (`version`, `git_commit`, `git_tag`,
`grading_ruleset_id`, …) naming exactly which `klt` build produced the
render, a top-level `source_doc_content_hash` that must match the
Provenance table's File SHA-256 above, and a per-row `graded_by_build`
flag (klayout-tools#2201) confirming the running build actually has
rules for that item. What were three independently-maintained prose
pins — the PyPI version string, the vendored doc's recorded hash, and
"is item 11's rule real" — are now each cross-checked against a
machine-emitted field in the same report `check-signoff.sh` already
byte-compares, rather than resting on a human keeping three numbers in
sync by hand.

## Sources

- `klayout-tools` grader contract: `docs/cli/signoff.md` → "Tier-verdict
  report" (2AMLogic/klayout-tools).
- T1-T4 ladder and the 11-item checklist: `docs/design-evidence-tiers.md`
  (2AMLogic/klayout-tools) — the vendored copy above.
- This block's gap-to-T1 tracker: issue #4 (this report is its verdict
  of record; the hand-maintained checkbox list is retired).
- Item 11's companion work item: issue #35.
- Fleet roll-up consuming this manifest: 2AMLogic/2am#956.
