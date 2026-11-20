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

- **#458**: test_usage_errors no longer pins class-2 non-publication (assertion dropped in PR #457)

## In Progress

Issues currently being built (`loom:building`).

- **#336**: operator: refresh spec/target-spec.md disclosure cells (Gain/NF/S11/S22/Stability rows + open-work list) once #27 closes
- **#433**: docs: README.md:3-4 lede duplicates the PDK name ("on IHP SG13G2 on [IHP SG13G2]")
- **#438**: ERC negative-control break layer is declared twice: run_flow.sh hardcodes 6/0, erc_control.py records its own constant
- **#439**: Share the per-point IIP3 measurement calculation across both reducers
- **#446**: check-signoff.sh does not gate on a T1 met-count regression
- **#449**: Reuse the Q-study boundary reduction for both metrics and band data
- **#450**: Share the matching-study preflight across the feed, Le and Q runners
- **#454**: Share batch-set report collection between the variant and IIP3 runners

## PRs Awaiting Review

PRs waiting on Judge (`loom:review-requested`).

_None._

## Approved (Awaiting Merge)

PRs that passed review and are queued for Champion auto-merge (`loom:pr`).

- **#381**: docs(spec): propose DR-0004 amendment making narrow disclosure-cell refreshes Builder work
- **#444**: refactor: share the per-point IIP3 measurement across both reducers
- **#455**: feat: gate check-signoff.sh on T1 met-item regressions vs the merge base
- **#456**: refactor(sim): reuse the q-study reduction's band in the boundary loop
- **#459**: refactor(sim): share the matching-study preflight across the feed, Le and Q runners

## Proposed

Issues carrying `loom:curated`.

- **#4**: Gap-to-T1 tracker: artifact-presence checklist (schematic through repo hygiene) *(curated)*
- **#58**: design: adopt the larger emitter array and measure the cascode split against the NF row (decision record 0004, Option C, first lever) *(curated)*
- **#201**: Worker capability request: compatible standalone KLayout for native PDK evidence *(curated)*
- **#227**: Live verification: klt artifact verify against the real broker with SIM_ARTIFACT_STORE=1 (follow-up to PR #223) *(curated)*
- **#336**: operator: refresh spec/target-spec.md disclosure cells (Gain/NF/S11/S22/Stability rows + open-work list) once #27 closes *(curated)*
- **#433**: docs: README.md:3-4 lede duplicates the PDK name ("on IHP SG13G2 on [IHP SG13G2]") *(curated)*
- **#438**: ERC negative-control break layer is declared twice: run_flow.sh hardcodes 6/0, erc_control.py records its own constant *(curated)*
- **#446**: check-signoff.sh does not gate on a T1 met-count regression *(curated)*
- **#458**: test_usage_errors no longer pins class-2 non-publication (assertion dropped in PR #457) *(curated)*

## Proposed (Architect / Hermit)

- **#68**: sim: Monte Carlo on the DR-0003 bias core and an explicit statistical-row classification (T1 item 6) *(architect)*
- **#269**: Remove the inlined native-DRC validate copy in check-layout-freshness: call layout/native_drc_identity.py instead *(hermit)*
- **#282**: Simplify rederive_nf_fixed_t0.py: the round-trip identity guard is algebraically vacuous *(hermit)*
- **#432**: Remove reducer-only drive-level overrides from the IIP3 runner *(hermit)*
- **#449**: Reuse the Q-study boundary reduction for both metrics and band data *(hermit)*
- **#450**: Share the matching-study preflight across the feed, Le and Q runners *(hermit)*

## Epics

_None._

## Backlog Balance

| Bucket | Count |
|------|-------|
| Operator merge-risk holds | 1 |
| Very important | 0 |
| Important | 0 |
| Ready (`loom:issue`) | 1 |
| In Progress (`loom:building`) | 8 |
| PRs awaiting review | 0 |
| Approved PRs awaiting merge | 5 |
| Curated | 9 |
| Architect / Hermit proposals | 6 |
| Active epics | 0 |
<!-- guide:plan-body:end -->
