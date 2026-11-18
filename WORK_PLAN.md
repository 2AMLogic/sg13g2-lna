# Work Plan

<!-- guide:plan-body:start -->
_Generated: 2026-11-18T22:01:20Z (snapshot; compare against live labels)_
## Operator Attention: Merge-Risk-Hold Pileup

Judge-approved PRs under a hold (`loom:blocked` or `loom:operator`) — only a human merge decision is missing.

- **#381**: docs(spec): propose DR-0004 amendment making narrow disclosure-cell refreshes Builder work

## Very Important

`loom:very-important` (one counts per workspace); every stage takes these first.

_None._

## Important

`loom:important`; taken before unlabelled work.

- **#228**: T1 item 2 (layout): full-block LNA layout generator and GDS, beyond the 6-of-30-instance bring-up

## Ready

Human-approved issues (`loom:issue`) ready for implementation — excluding held (`loom:blocked`/`loom:operator`/`loom:frozen`), `loom:building`, and issues closed by an open `loom:pr` PR (listed under Approved).

- **#228**: T1 item 2 (layout): full-block LNA layout generator and GDS, beyond the 6-of-30-instance bring-up

## In Progress

Issues currently being built (`loom:building`).

- **#336**: operator: refresh spec/target-spec.md disclosure cells (Gain/NF/S11/S22/Stability rows + open-work list) once #27 closes

## PRs Awaiting Review

PRs waiting on Judge (`loom:review-requested`).

_None._

## Approved (Awaiting Merge)

PRs that passed review and are queued for Champion auto-merge (`loom:pr`).

- **#381**: docs(spec): propose DR-0004 amendment making narrow disclosure-cell refreshes Builder work — closes #336

## Proposed

Issues carrying `loom:curated`.

- **#4**: Gap-to-T1 tracker: artifact-presence checklist (schematic through repo hygiene) *(curated)* *(held)*
- **#58**: design: adopt the larger emitter array and measure the cascode split against the NF row (decision record 0004, Option C, first lever) *(curated)* *(held)*
- **#201**: Worker capability request: compatible standalone KLayout for native PDK evidence *(curated)* *(held)*
- **#227**: Live verification: klt artifact verify against the real broker with SIM_ARTIFACT_STORE=1 (follow-up to PR #223) *(curated)* *(held)*
- **#228**: T1 item 2 (layout): full-block LNA layout generator and GDS, beyond the 6-of-30-instance bring-up *(curated)*
- **#336**: operator: refresh spec/target-spec.md disclosure cells (Gain/NF/S11/S22/Stability rows + open-work list) once #27 closes *(curated)*

## Proposed (Architect / Hermit)

- **#68**: sim: Monte Carlo on the DR-0003 bias core and an explicit statistical-row classification (T1 item 6) *(architect)* *(held)*
- **#269**: Remove the inlined native-DRC validate copy in check-layout-freshness: call layout/native_drc_identity.py instead *(hermit)* *(held)*
- **#282**: Simplify rederive_nf_fixed_t0.py: the round-trip identity guard is algebraically vacuous *(hermit)* *(held)*

## Epics

_None._

## Backlog Balance

| Bucket | Count |
|------|-------|
| Operator merge-risk holds | 1 |
| Very important | 0 |
| Important | 1 |
| Ready (`loom:issue`, net of holds/building/merge-pending) | 1 |
| In Progress (`loom:building`) | 1 |
| PRs awaiting review | 0 |
| Approved PRs awaiting merge | 1 |
| Curated | 6 |
| Architect / Hermit proposals | 3 |
| Active epics | 0 |
<!-- guide:plan-body:end -->
