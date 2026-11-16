# Work Plan

<!-- guide:plan-body:start -->
## Operator Attention: Merge-Risk-Hold Pileup

Judge-approved PRs under a hold (`loom:blocked` or `loom:operator`) — only a human merge decision is missing.

- **#317**: chore(loom): resync installed Loom to v0.19.1302

## Very Important

`loom:very-important` (one counts per workspace); every stage takes these first.

_None._

## Important

`loom:important`; taken before unlabelled work.

- **#27**: design: LNA has no input/output matching network — S11 = -2.96 dB, S22 = -0.003 dB, broadband mu < 1 at 45/45 PVT cells (DR-0003 core)

## Ready

Human-approved issues ready for implementation (`loom:issue`).

- **#27**: design: LNA has no input/output matching network — S11 = -2.96 dB, S22 = -0.003 dB, broadband mu < 1 at 45/45 PVT cells (DR-0003 core)
- **#305**: design/README.md misstates which xschem generated the committed netlist
- **#311**: test flake / suspected sim_record_paths race: concurrency case fails again (wins=1 losses=7), now with per-caller evidence
- **#318**: sim/lna-characterization/README.md's "Which DUT each record describes" table is stale: 3 of 9 records, and the one it calls "current main" is superseded
- **#320**: check-klt-pin.sh's file loop still misses README.md and layout/README.md, so the prose klt/KLayout pins can drift
- **#321**: run_native_drc.py's not-full-scope NOTE hardcodes a fourth status subset that no test pins
- **#324**: test-design-source-audit.sh header comment still describes absent klt as SKIP-only (stale after #323)

## In Progress

Issues currently being built (`loom:building`).

- **#300**: Consolidate five duplicated run_deck() gates in lna-matching-feasibility runners into sim/env.sh
- **#306**: lna_variant_campaign: --temps slicing has no unit test; a narrower summarize slice under-checks coverage silently

## PRs Awaiting Review

PRs waiting on Judge (`loom:review-requested`).

_None._

## Approved (Awaiting Merge)

PRs that passed review and are queued for Champion auto-merge (`loom:pr`).

- **#317**: chore(loom): resync installed Loom to v0.19.1302

## Proposed

Issues carrying `loom:curated`.

- **#4**: Gap-to-T1 tracker: artifact-presence checklist (schematic through repo hygiene) *(curated)*
- **#27**: design: LNA has no input/output matching network — S11 = -2.96 dB, S22 = -0.003 dB, broadband mu < 1 at 45/45 PVT cells (DR-0003 core) *(curated)*
- **#58**: design: adopt the larger emitter array and measure the cascode split against the NF row (decision record 0004, Option C, first lever) *(curated)*
- **#201**: Worker capability request: compatible standalone KLayout for native PDK evidence *(curated)*
- **#227**: Live verification: klt artifact verify against the real broker with SIM_ARTIFACT_STORE=1 (follow-up to PR #223) *(curated)*
- **#300**: Consolidate five duplicated run_deck() gates in lna-matching-feasibility runners into sim/env.sh *(curated)*
- **#305**: design/README.md misstates which xschem generated the committed netlist *(curated)*
- **#306**: lna_variant_campaign: --temps slicing has no unit test; a narrower summarize slice under-checks coverage silently *(curated)*
- **#311**: test flake / suspected sim_record_paths race: concurrency case fails again (wins=1 losses=7), now with per-caller evidence *(curated)*
- **#318**: sim/lna-characterization/README.md's "Which DUT each record describes" table is stale: 3 of 9 records, and the one it calls "current main" is superseded *(curated)*
- **#320**: check-klt-pin.sh's file loop still misses README.md and layout/README.md, so the prose klt/KLayout pins can drift *(curated)*
- **#321**: run_native_drc.py's not-full-scope NOTE hardcodes a fourth status subset that no test pins *(curated)*
- **#324**: test-design-source-audit.sh header comment still describes absent klt as SKIP-only (stale after #323) *(curated)*

## Proposed (Architect / Hermit)

- **#68**: sim: Monte Carlo on the DR-0003 bias core and an explicit statistical-row classification (T1 item 6) *(architect)*
- **#269**: Remove the inlined native-DRC validate copy in check-layout-freshness: call layout/native_drc_identity.py instead *(hermit)*
- **#282**: Simplify rederive_nf_fixed_t0.py: the round-trip identity guard is algebraically vacuous *(hermit)*

## Epics

_None._

## Backlog Balance

| Bucket | Count |
|------|-------|
| Operator merge-risk holds | 1 |
| Very important | 0 |
| Important | 1 |
| Ready (`loom:issue`) | 7 |
| In Progress (`loom:building`) | 2 |
| PRs awaiting review | 0 |
| Approved PRs awaiting merge | 1 |
| Curated | 13 |
| Architect / Hermit proposals | 3 |
| Active epics | 0 |
<!-- guide:plan-body:end -->
