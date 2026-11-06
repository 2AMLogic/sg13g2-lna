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

- **#258**: design: give the output-match node xout a DC path and re-run the matched DUT's 125 C cells

## PRs Awaiting Review

PRs waiting on Judge (`loom:review-requested`).

_None._

## Approved (Awaiting Merge)

PRs that passed review and are queued for Champion auto-merge (`loom:pr`).

_None._

## Proposed

Issues carrying `loom:curated`.

- **#4**: Gap-to-T1 tracker: artifact-presence checklist (schematic through repo hygiene) *(curated)*
- **#27**: design: LNA has no input/output matching network — S11 = -2.96 dB, S22 = -0.003 dB, broadband mu < 1 at 45/45 PVT cells (DR-0003 core) *(curated)*
- **#56**: sim: replace the ideal inductors with EM-extracted lossy models from sg13g2-vco (removes the blocker on #27, T1 item 5 match and stability rows) *(curated)*
- **#58**: design: adopt the larger emitter array and measure the cascode split against the NF row (decision record 0004, Option C, first lever) *(curated)*
- **#201**: Worker capability request: compatible standalone KLayout for native PDK evidence *(curated)*
- **#227**: Live verification: klt artifact verify against the real broker with SIM_ARTIFACT_STORE=1 (follow-up to PR #223) *(curated)*
- **#258**: design: give the output-match node xout a DC path and re-run the matched DUT's 125 C cells *(curated)*
- **#260**: PR #259 follow-up: add Rbleed to layout, rerun LVS, re-attest T1 items 1/10 *(curated)*

## Proposed (Architect / Hermit)

- **#68**: sim: Monte Carlo on the DR-0003 bias core and an explicit statistical-row classification (T1 item 6) *(architect)*
- **#255**: Simplify: 8 inline importlib loaders replaced a one-line sha256 helper (+34 net LOC) *(hermit)*

## Epics

_None._

## Backlog Balance

| Bucket | Count |
|------|-------|
| Operator merge-risk holds | 0 |
| Very important | 0 |
| Important | 2 |
| Ready (`loom:issue`) | 0 |
| In Progress (`loom:building`) | 1 |
| PRs awaiting review | 0 |
| Approved PRs awaiting merge | 0 |
| Curated | 8 |
| Architect / Hermit proposals | 2 |
| Active epics | 0 |
<!-- guide:plan-body:end -->
