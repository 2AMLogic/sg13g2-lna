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
- **#274**: Consolidate the duplicated signoff inventory/envelope scaffolding in .github/scripts
- **#276**: Name the logic buried in parse_core_envelope.py: 404-line main() and the one gain metric #94 left inline
- **#277**: sim-core-envelope-lifecycle-tests fails intermittently: XQ1 geometry substitution did not match scratch netlist
- **#279**: sim: unit-test the variant campaign's bias-attribution claim generator (ic1_pct, span_scaled, the ±0.05 % branch)
- **#280**: Finish #160: dedupe the startup verdict rule and its thresholds across the two sim reducers
- **#287**: sim: reduce_biasref.py still holds a private copy of the corner-label -> MOS-section map that #283 consolidated on the shell side
- **#290**: run_native_drc.py STATUSES omits clean_partial, so a partial-scope native DRC run would be rejected as a failed run

## PRs Awaiting Review

PRs waiting on Judge (`loom:review-requested`).

- **#281**: refactor(core-envelope): name the in-band gain metric and split parse_core_envelope main()
- **#293**: test: pin the variant campaign's bias-attribution claim generator
- **#298**: docs: correct the pre-match/matched DUT claims in the status prose

## Approved (Awaiting Merge)

PRs that passed review and are queued for Champion auto-merge (`loom:pr`).

- **#291**: refactor: dedupe startup verdict rule and require across the sim reducers
- **#296**: fix(layout): accept clean_partial and not_checked native DRC verdicts across all three gates

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
- **#277**: sim-core-envelope-lifecycle-tests fails intermittently: XQ1 geometry substitution did not match scratch netlist *(curated)*
- **#279**: sim: unit-test the variant campaign's bias-attribution claim generator (ic1_pct, span_scaled, the ±0.05 % branch) *(curated)*
- **#290**: run_native_drc.py STATUSES omits clean_partial, so a partial-scope native DRC run would be rejected as a failed run *(curated)*

## Proposed (Architect / Hermit)

- **#68**: sim: Monte Carlo on the DR-0003 bias core and an explicit statistical-row classification (T1 item 6) *(architect)*
- **#269**: Remove the inlined native-DRC validate copy in check-layout-freshness: call layout/native_drc_identity.py instead *(hermit)*
- **#282**: Simplify rederive_nf_fixed_t0.py: the round-trip identity guard is algebraically vacuous *(hermit)*

## Epics

_None._

## Backlog Balance

| Bucket | Count |
|------|-------|
| Operator merge-risk holds | 0 |
| Very important | 0 |
| Important | 1 |
| Ready (`loom:issue`) | 0 |
| In Progress (`loom:building`) | 9 |
| PRs awaiting review | 3 |
| Approved PRs awaiting merge | 2 |
| Curated | 11 |
| Architect / Hermit proposals | 3 |
| Active epics | 0 |
<!-- guide:plan-body:end -->
