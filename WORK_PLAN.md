# Work Plan

<!-- guide:plan-body:start -->
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

Human-approved issues ready for implementation (`loom:issue`).

_None._

## In Progress

Issues currently being built (`loom:building`).

- **#35**: T1 item 11 (power delivery, structural): klt erc supply spec + LVS supply pairing — unmet until layout exists
- **#336**: operator: refresh spec/target-spec.md disclosure cells (Gain/NF/S11/S22/Stability rows + open-work list) once #27 closes
- **#425**: Reuse the validated S-parameter log for the 290 K noise-figure cross-check
- **#433**: docs: README.md:3-4 lede duplicates the PDK name ("on IHP SG13G2 on [IHP SG13G2]")
- **#435**: Centralize native DRC cleanup so a failed klt version probe archives the previous report
- **#437**: Item-9 fixture suite has no case that fails when tree_digest's hash input changes
- **#439**: Share the per-point IIP3 measurement calculation across both reducers

## PRs Awaiting Review

PRs waiting on Judge (`loom:review-requested`).

- **#440**: fix: archive the previous native DRC pair at one exit point, not nine

## Approved (Awaiting Merge)

PRs that passed review and are queued for Champion auto-merge (`loom:pr`).

- **#381**: docs(spec): propose DR-0004 amendment making narrow disclosure-cell refreshes Builder work
- **#434**: feat(signoff): T1 item-11 power-delivery ERC evidence -- supply spec, negative controls, compound citation

## Proposed

Issues carrying `loom:curated`.

- **#4**: Gap-to-T1 tracker: artifact-presence checklist (schematic through repo hygiene) *(curated)*
- **#58**: design: adopt the larger emitter array and measure the cascode split against the NF row (decision record 0004, Option C, first lever) *(curated)*
- **#201**: Worker capability request: compatible standalone KLayout for native PDK evidence *(curated)*
- **#227**: Live verification: klt artifact verify against the real broker with SIM_ARTIFACT_STORE=1 (follow-up to PR #223) *(curated)*
- **#336**: operator: refresh spec/target-spec.md disclosure cells (Gain/NF/S11/S22/Stability rows + open-work list) once #27 closes *(curated)*
- **#433**: docs: README.md:3-4 lede duplicates the PDK name ("on IHP SG13G2 on [IHP SG13G2]") *(curated)*
- **#437**: Item-9 fixture suite has no case that fails when tree_digest's hash input changes *(curated)*

## Proposed (Architect / Hermit)

- **#68**: sim: Monte Carlo on the DR-0003 bias core and an explicit statistical-row classification (T1 item 6) *(architect)*
- **#269**: Remove the inlined native-DRC validate copy in check-layout-freshness: call layout/native_drc_identity.py instead *(hermit)*
- **#282**: Simplify rederive_nf_fixed_t0.py: the round-trip identity guard is algebraically vacuous *(hermit)*
- **#432**: Remove reducer-only drive-level overrides from the IIP3 runner *(hermit)*

## Epics

_None._

## Backlog Balance

| Bucket | Count |
|------|-------|
| Operator merge-risk holds | 1 |
| Very important | 0 |
| Important | 0 |
| Ready (`loom:issue`) | 0 |
| In Progress (`loom:building`) | 7 |
| PRs awaiting review | 1 |
| Approved PRs awaiting merge | 2 |
| Curated | 7 |
| Architect / Hermit proposals | 4 |
| Active epics | 0 |
<!-- guide:plan-body:end -->
