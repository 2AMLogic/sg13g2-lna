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

## Ready

Human-approved issues ready for implementation (`loom:issue`).

_None._

## In Progress

Issues currently being built (`loom:building`).

- **#258**: design: give the output-match node xout a DC path and re-run the matched DUT's 125 C cells
- **#271**: docs: refresh status prose that still describes the pre-match DUT (README, signoff/README, lna-characterization README)
- **#276**: Name the logic buried in parse_core_envelope.py: 404-line main() and the one gain metric #94 left inline
- **#279**: sim: unit-test the variant campaign's bias-attribution claim generator (ic1_pct, span_scaled, the ±0.05 % branch)
- **#290**: run_native_drc.py STATUSES omits clean_partial, so a partial-scope native DRC run would be rejected as a failed run
- **#294**: check-klt-pin.sh cannot gate test-design-source-audit.sh's klt version strings, so a future bump silently disables its klt cases
- **#302**: signoff checkers: main() is still duplicated after #274 (the largest remaining shared block)

## PRs Awaiting Review

PRs waiting on Judge (`loom:review-requested`).

- **#281**: refactor(core-envelope): name the in-band gain metric and split parse_core_envelope main()
- **#308**: refactor: share one main() driver between the item-9/item-10 inventory checkers

## Approved (Awaiting Merge)

PRs that passed review and are queued for Champion auto-merge (`loom:pr`).

- **#259**: design: add DC bleed on xout, floating-node guard, 125 C batch record
- **#293**: test: pin the variant campaign's bias-attribution claim generator
- **#296**: fix(layout): accept clean_partial and not_checked native DRC verdicts across all three gates
- **#298**: docs: correct the pre-match/matched DUT claims in the status prose
- **#304**: ci: gate KLAYOUT_PIN and derive the audit suite's expected klt release

## Proposed

Issues carrying `loom:curated`.

- **#4**: Gap-to-T1 tracker: artifact-presence checklist (schematic through repo hygiene) *(curated)*
- **#27**: design: LNA has no input/output matching network — S11 = -2.96 dB, S22 = -0.003 dB, broadband mu < 1 at 45/45 PVT cells (DR-0003 core) *(curated)*
- **#58**: design: adopt the larger emitter array and measure the cascode split against the NF row (decision record 0004, Option C, first lever) *(curated)*
- **#201**: Worker capability request: compatible standalone KLayout for native PDK evidence *(curated)*
- **#227**: Live verification: klt artifact verify against the real broker with SIM_ARTIFACT_STORE=1 (follow-up to PR #223) *(curated)*
- **#258**: design: give the output-match node xout a DC path and re-run the matched DUT's 125 C cells *(curated)*
- **#260**: PR #259 follow-up: add Rbleed to layout, rerun LVS, re-attest T1 items 1/10 *(curated)*
- **#271**: docs: refresh status prose that still describes the pre-match DUT (README, signoff/README, lna-characterization README) *(curated)*
- **#279**: sim: unit-test the variant campaign's bias-attribution claim generator (ic1_pct, span_scaled, the ±0.05 % branch) *(curated)*
- **#290**: run_native_drc.py STATUSES omits clean_partial, so a partial-scope native DRC run would be rejected as a failed run *(curated)*
- **#294**: check-klt-pin.sh cannot gate test-design-source-audit.sh's klt version strings, so a future bump silently disables its klt cases *(curated)*
- **#300**: Consolidate five duplicated run_deck() gates in lna-matching-feasibility runners into sim/env.sh *(curated)*
- **#302**: signoff checkers: main() is still duplicated after #274 (the largest remaining shared block) *(curated)*

## Proposed (Architect / Hermit)

- **#68**: sim: Monte Carlo on the DR-0003 bias core and an explicit statistical-row classification (T1 item 6) *(architect)*
- **#269**: Remove the inlined native-DRC validate copy in check-layout-freshness: call layout/native_drc_identity.py instead *(hermit)*
- **#282**: Simplify rederive_nf_fixed_t0.py: the round-trip identity guard is algebraically vacuous *(hermit)*
- **#300**: Consolidate five duplicated run_deck() gates in lna-matching-feasibility runners into sim/env.sh *(hermit)*

## Epics

_None._

## Backlog Balance

| Bucket | Count |
|------|-------|
| Operator merge-risk holds | 0 |
| Very important | 0 |
| Important | 1 |
| Ready (`loom:issue`) | 0 |
| In Progress (`loom:building`) | 7 |
| PRs awaiting review | 2 |
| Approved PRs awaiting merge | 5 |
| Curated | 13 |
| Architect / Hermit proposals | 4 |
| Active epics | 0 |
<!-- guide:plan-body:end -->
