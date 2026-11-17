# Work Plan

<!-- guide:plan-body:start -->
## Operator Attention: Merge-Risk-Hold Pileup

Judge-approved PRs under a hold (`loom:blocked` or `loom:operator`) — only a human merge decision is missing.

_None._

## Very Important

`loom:very-important` (one counts per workspace); every stage takes these first.

- **#346**: T1 item 2 (layout) part A: draw the bias-side instances (DR-0003 reference core, vb2 divider, decoupling) in lna_core

## Important

`loom:important`; taken before unlabelled work.

- **#228**: T1 item 2 (layout): full-block LNA layout generator and GDS, beyond the 6-of-30-instance bring-up *(held)*
- **#347**: T1 item 2 (layout) part B: draw the matching network (inductors via inductor2 PyCell, caps) and settle the loss-resistor partition

## Ready

Human-approved issues ready for implementation (`loom:issue`).

- **#347**: T1 item 2 (layout) part B: draw the matching network (inductors via inductor2 PyCell, caps) and settle the loss-resistor partition
- **#346**: T1 item 2 (layout) part A: draw the bias-side instances (DR-0003 reference core, vb2 divider, decoupling) in lna_core

## In Progress

Issues currently being built (`loom:building`).

- **#336**: operator: refresh spec/target-spec.md disclosure cells (Gain/NF/S11/S22/Stability rows + open-work list) once #27 closes

## PRs Awaiting Review

PRs waiting on Judge (`loom:review-requested`).

_None._

## Approved (Awaiting Merge)

PRs that passed review and are queued for Champion auto-merge (`loom:pr`).

_None._

## Proposed

Issues carrying `loom:curated`.

- **#4**: Gap-to-T1 tracker: artifact-presence checklist (schematic through repo hygiene) *(curated)* *(held)*
- **#58**: design: adopt the larger emitter array and measure the cascode split against the NF row (decision record 0004, Option C, first lever) *(curated)*
- **#201**: Worker capability request: compatible standalone KLayout for native PDK evidence *(curated)* *(held)*
- **#227**: Live verification: klt artifact verify against the real broker with SIM_ARTIFACT_STORE=1 (follow-up to PR #223) *(curated)* *(held)*
- **#336**: operator: refresh spec/target-spec.md disclosure cells (Gain/NF/S11/S22/Stability rows + open-work list) once #27 closes *(curated)*
- **#346**: T1 item 2 (layout) part A: draw the bias-side instances (DR-0003 reference core, vb2 divider, decoupling) in lna_core *(curated)*
- **#347**: T1 item 2 (layout) part B: draw the matching network (inductors via inductor2 PyCell, caps) and settle the loss-resistor partition *(curated)*

## Proposed (Architect / Hermit)

- **#68**: sim: Monte Carlo on the DR-0003 bias core and an explicit statistical-row classification (T1 item 6) *(architect)*
- **#269**: Remove the inlined native-DRC validate copy in check-layout-freshness: call layout/native_drc_identity.py instead *(hermit)*
- **#282**: Simplify rederive_nf_fixed_t0.py: the round-trip identity guard is algebraically vacuous *(hermit)*
- **#359**: Consolidate native-DRC pair validation: one implementation instead of three *(hermit)*

## Epics

_None._

## Backlog Balance

| Bucket | Count |
|------|-------|
| Operator merge-risk holds | 0 |
| Very important | 1 |
| Important | 2 |
| Ready (`loom:issue`) | 2 |
| In Progress (`loom:building`) | 1 |
| PRs awaiting review | 0 |
| Approved PRs awaiting merge | 0 |
| Curated | 7 |
| Architect / Hermit proposals | 4 |
| Active epics | 0 |
<!-- guide:plan-body:end -->
