# Work Plan

<!-- guide:plan-body:start -->
## Operator Attention: Merge-Risk-Hold Pileup

Judge-approved PRs under a hold (`loom:blocked` or `loom:operator`) — only a human merge decision is missing.

_None._

## Very Important

`loom:very-important` (one counts per workspace); every stage takes these first.

_None._

## Important

`loom:important`; taken before unlabelled work.

- **#27**: design: LNA has no input/output matching network — S11 = -2.96 dB, S22 = -0.003 dB, broadband mu < 1 at 45/45 PVT cells (DR-0003 core)
- **#56**: sim: replace the ideal inductors with EM-extracted lossy models from sg13g2-vco (removes the blocker on #27, T1 item 5 match and stability rows)

## Ready

Human-approved issues ready for implementation (`loom:issue`).

_None._

## In Progress

Issues currently being built (`loom:building`).

- **#222**: Adopt the common artifact store for sim evidence (manifests in git, bytes via klt artifact)
- **#224**: main CI: matching-feasibility-tests replay fails with last-digit float diffs since 2026-10-21

## PRs Awaiting Review

PRs waiting on Judge (`loom:review-requested`).

_None._

## Approved (Awaiting Merge)

PRs that passed review and are queued for Champion auto-merge (`loom:pr`).

- **#225**: ci: pin matching-feasibility-tests to ubuntu-24.04

## Proposed

Issues carrying `loom:curated`.

- **#4**: Gap-to-T1 tracker: artifact-presence checklist (schematic through repo hygiene) *(curated)*
- **#27**: design: LNA has no input/output matching network — S11 = -2.96 dB, S22 = -0.003 dB, broadband mu < 1 at 45/45 PVT cells (DR-0003 core) *(curated)*
- **#56**: sim: replace the ideal inductors with EM-extracted lossy models from sg13g2-vco (removes the blocker on #27, T1 item 5 match and stability rows) *(curated)*
- **#58**: design: adopt the larger emitter array and measure the cascode split against the NF row (decision record 0004, Option C, first lever) *(curated)*
- **#90**: sim: measure full-DUT DC mismatch spread with a seeded fleet campaign and controls *(curated)*
- **#201**: Worker capability request: compatible standalone KLayout for native PDK evidence *(curated)*
- **#222**: Adopt the common artifact store for sim evidence (manifests in git, bytes via klt artifact) *(curated)*
- **#224**: main CI: matching-feasibility-tests replay fails with last-digit float diffs since 2026-10-21 *(curated)*

## Proposed (Architect / Hermit)

- **#68**: sim: Monte Carlo on the DR-0003 bias core and an explicit statistical-row classification (T1 item 6) *(architect)*

## Epics

_None._

## Backlog Balance

| Bucket | Count |
|------|-------|
| Operator merge-risk holds | 0 |
| Very important | 0 |
| Important | 2 |
| Ready (`loom:issue`) | 0 |
| In Progress (`loom:building`) | 2 |
| PRs awaiting review | 0 |
| Approved PRs awaiting merge | 1 |
| Curated | 8 |
| Architect / Hermit proposals | 1 |
| Active epics | 0 |
<!-- guide:plan-body:end -->
