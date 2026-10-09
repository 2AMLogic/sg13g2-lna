# Work Plan

<!-- guide:plan-body:start -->
## Operator Attention: Merge-Risk-Hold Pileup

Judge-approved PRs stuck under a `loom:operator` merge-risk hold — implementation work is done, only a human merge decision is missing.

_None._

## Operator Priority

Issues the operator starred (`loom:operator-priority`); land these first.

_None._

## Ready

Human-approved issues ready for implementation (`loom:issue`).

- **#94**: Consolidate duplicated RF helpers in the core-envelope postprocessors

## In Progress

Issues currently being built (`loom:building`).

- **#84**: ci: enforce vendored inductor-model checksum provenance

## PRs Awaiting Review

PRs waiting on Judge (`loom:review-requested`).

_None._

## Approved (Awaiting Merge)

PRs that passed review and are queued for Champion auto-merge (`loom:pr`).

_None._

## Proposed

Issues carrying `loom:curated`.

- **#4**: Gap-to-T1 tracker: artifact-presence checklist (schematic through repo hygiene) *(curated)*
- **#46**: README: embed the fleet burndown chart (one line) *(curated)*
- **#56**: sim: replace the ideal inductors with EM-extracted lossy models from sg13g2-vco (removes the blocker on #27, T1 item 5 match and stability rows) *(curated)*

## Proposed (Architect / Hermit)

- **#68**: sim: Monte Carlo on the DR-0003 bias core and an explicit statistical-row classification (T1 item 6) *(architect)*
- **#84**: ci: enforce vendored inductor-model checksum provenance *(architect)*
- **#87**: sim: express the committed DUT's 45-cell PVT grid as klt sim corners requests (first klt-native envelope for T1 item 5) *(architect)*

## Epics

_None._

## Backlog Balance

| Tier | Count |
|------|-------|
| Operator merge-risk holds | 0 |
| Operator priority | 0 |
| Ready (`loom:issue`) | 1 |
| In Progress (`loom:building`) | 1 |
| PRs awaiting review | 0 |
| Approved PRs awaiting merge | 0 |
| Curated | 3 |
| Architect / Hermit proposals | 3 |
| Active epics | 0 |

<!-- guide:plan-body:end -->
