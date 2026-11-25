# Work Plan

<!-- guide:plan-body:start -->
_Generated: 2026-11-25T22:12:47Z (snapshot; compare against live labels)_
## Operator Attention: Merge-Risk-Hold Pileup

Judge-approved PRs under a hold (`loom:blocked` or `loom:operator`) — only a human merge decision is missing.

- **#381**: docs(spec): propose DR-0004 amendment making narrow disclosure-cell refreshes Builder work

## Very Important

`loom:very-important` (one counts per workspace); every stage takes these first.

_None._

## Important

`loom:important`; taken before unlabelled work.

_None._

## Ready

Human-approved issues (`loom:issue`) ready for implementation — excluding held (`loom:blocked`/`loom:operator`/`loom:frozen`), `loom:building`, and issues closed by an open `loom:pr` PR (listed under Approved).

_None._

## In Progress

Issues currently being built (`loom:building`).

- **#336**: operator: refresh spec/target-spec.md disclosure cells (Gain/NF/S11/S22/Stability rows + open-work list) once #27 closes
- **#496**: Share the klt sim execution block and remote-job summary formatter between run_lna_variant.sh and run_lna_iip3.sh

## PRs Awaiting Review

PRs waiting on Judge (`loom:review-requested`).

- **#498**: refactor(sim): share klt request execution and job bullets across LNA runners — closes #496

## Approved (Awaiting Merge)

PRs that passed review and are queued for Champion auto-merge (`loom:pr`).

- **#381**: docs(spec): propose DR-0004 amendment making narrow disclosure-cell refreshes Builder work — closes #336

## Proposed

Issues carrying `loom:curated`.

- **#4**: Gap-to-T1 tracker: artifact-presence checklist (schematic through repo hygiene) *(curated)* *(held)*
- **#58**: design: adopt the larger emitter array and measure the cascode split against the NF row (decision record 0004, Option C, first lever) *(curated)* *(held)*
- **#201**: Worker capability request: compatible standalone KLayout for native PDK evidence *(curated)* *(held)*
- **#227**: Live verification: klt artifact verify against the real broker with SIM_ARTIFACT_STORE=1 (follow-up to PR #223) *(curated)* *(held)*
- **#336**: operator: refresh spec/target-spec.md disclosure cells (Gain/NF/S11/S22/Stability rows + open-work list) once #27 closes *(curated)*

## Proposed (Architect / Hermit)

- **#68**: sim: Monte Carlo on the DR-0003 bias core and an explicit statistical-row classification (T1 item 6) *(architect)* *(held)*
- **#269**: Remove the inlined native-DRC validate copy in check-layout-freshness: call layout/native_drc_identity.py instead *(hermit)* *(held)*
- **#495**: Remove the local ngspice requirement from the fleet Monte Carlo runner *(hermit)* *(held)*

## Epics

_None._

## Backlog Balance

| Bucket | Count |
|------|-------|
| Operator merge-risk holds | 1 |
| Very important | 0 |
| Important | 0 |
| Ready (`loom:issue`, net of holds/building/merge-pending) | 0 |
| In Progress (`loom:building`) | 2 |
| PRs awaiting review | 1 |
| Approved PRs awaiting merge | 1 |
| Curated | 5 |
| Architect / Hermit proposals | 3 |
| Active epics | 0 |
<!-- guide:plan-body:end -->
