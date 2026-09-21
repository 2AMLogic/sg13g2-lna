# 0002: First target-spec ratification — band, gain, NF, S11/S22, stability, supply and power

- **Status**: ratified
- **Date**: 2026-09-21
- **Decided by**: operator, by approving the issue-#19 ratification PR — the
  ratification act; drafted on the evidence by Builder (Loom)
- **Issue**: [#19](https://github.com/2AMLogic/sg13g2-lna/issues/19)
  (sub-issue of the T1 gap tracker
  [#4](https://github.com/2AMLogic/sg13g2-lna/issues/4), its checklist item 5)

**Status semantics.** This record's `ratified` status takes effect with the
operator-approved merge of the issue-#19 ratification PR: per the
ratification-via-PR standing policy
([`2AMLogic/2am#357`](https://github.com/2AMLogic/2am/issues/357)), the
operator's PR approval **is** the ratification act — the same
status-transition discipline the fleet's sibling ratifications use (e.g.
`2AMLogic/gf180-drone-fc#1`: a record reads `ratified` "only once the
operator has actually approved/merged the ratifying PR — not before").
The fleet's two-key mechanism
([`2AMLogic/2am#372`](https://github.com/2AMLogic/2am/issues/372)) was
re-verified **still not operational** at this issue's pickup (2026-09-21:
OPEN, `loom:operator-only` + `loom:epic` + `loom:operator-decision`), so the
predecessor standing policy is the path actually used, as issue #19's
acceptance criteria direct. When the two-key mechanism lands, this record —
and any future record that would *relax* a row it ratifies — falls under
that epic's relax-after-measured-FAIL rule: a weaker value requires the
market key's explicit competitiveness finding or an `loom:operator`
escalation.

## Context

`spec/target-spec.md` was DRAFT in its entirety: every row sourced from
topology-level literature and static PDK process-spec numbers, explicitly
pending "a spec-ratification issue" gated on the S-parameter/noise
testbenches. Both of issue #19's declared dependencies have since merged —
#16 (bias/supply topology decision record 0001, via PR #22) and #18 (the
circuit-level S-parameter/NF/stability/IIP3 campaign, via PR #28, merged at
`04ded14`, record `20260918-210908-4293920`) — plus, in the interim, the
breakdown-extraction bench (issue #20, PR #29, merged at `f7916e5`, record
`20260918-212948-013274f`) that closes decision record 0001's own "no
committed breakdown testbench" gap. `measurements/README.md` — the
campaign's characterization report — ends with "What has to happen before
any of this becomes a spec claim" and names this issue as step 4, with that
record as the evidence base. T1 tracker #4's checklist item 5 ("full-PVT
sim vs. a ratified spec") is blocked solely on the ratified-spec half of
that sentence; the sim half exists. This record supplies the missing half
for the rows the evidence can carry, and states plainly — in the Decision
and Consequences sections — which row it deliberately does **not** carry.

## Decision

The following rows of `spec/target-spec.md` move from DRAFT to RATIFIED at
the stated values and binding conditions (the table there carries each
row's status-vs-evidence note; this section is the binding summary):

| Row | Ratified value | Binding conditions | vs. former DRAFT |
|---|---|---|---|
| Band | 2400–2483.5 MHz (2.4 GHz ISM), primary | — | **unchanged** ("draft primary candidate" → decided) |
| Gain (S21) | > 15 dB, 50 Ω ports, across the ratified band | full ratified corner box, DR-0001 bias mandate held, post-matching (#26 + #27) | **unchanged** |
| Noise figure | < 1.5 dB, **T0 = 290 K** (`nf290`), across band, 50 Ω ports | full ratified corner box, bias mandate held, post-matching (#27) | **unchanged**, reference temperature now pinned |
| Input match (S11) | < −10 dB across band, 50 Ω reference | corner box as exercisable; post-matching (#27) | **unchanged** |
| Output match (S22) | < −10 dB across band, 50 Ω reference | corner box as exercisable; post-matching (#27) | **unchanged** |
| Stability | **μ > 1** (Edwards–Sinsky), 10 MHz–30 GHz sweep (≥ 12× the upper band edge; floor ≥ 3× preserved), every ratified cell, with k, \|Δ\| and the negative-resistance check reported alongside | corner box; the pre-condition it imposes on #27 (no match final before it holds) | **assertion-equivalent, metric refined** — k > 1 is retained as co-reported; μ is pinned as binding because the committed campaign evidences k is ill-conditioned on this topology |
| IIP3 — measurement protocol | The committed two-tone bench and its parameters (see Evidence) — the binding definition for any future IIP3 number | any future IIP3 ratification re-measures on this protocol at 50 Ω ports, available-source-power-referred | **new** (the DRAFT row specified no bench) |
| IIP3 — numeric target | **NOT RATIFIED — stays DRAFT at the former > 0 dBm level**: not force-ratified, and explicitly **not relaxed** | binding awaits #26 + #27 re-measurement, then a decision record of its own | **deliberately unchanged in DRAFT** |
| Supply | 1.80 V ± 10 % (1.62–1.98 V), single rail, cascode `npn13G2` Nx = 8 per record 0001 | the corner box's supply axis | **decided** (was "TBD 1.2–3.3 V bounded by BVCEO"); record 0001 ratified by this record |
| Power (P_dc) | < 10 mW DC (core + bias network) | full corner box with the DR-0001 mandate (`I_C ≤ 4.5 mA`) held; verification gated on #26 | **unchanged** |

Also ratified with this record:

- **The verification corner box** — {typ, bcs, wcs} real HBT sections ×
  {−40, 27, 125} °C × {1.62, 1.80, 1.98} V, with `sf`/`fs` documented as
  `typ` duplicates (the PDK ships three real sections) and `wcs` read as
  the `ss`-equivalent.
- **The port convention as binding definition** — 50 Ω at both ports;
  NF referenced to T0 = 290 K (this also settles this repo's half of #25
  going forward: future benches quote `nf290`).
- **Stretch columns are not ratified.** The former DRAFT stretch values
  (< 18 dB gain, < 1.0 dB NF "sub-dB", < −15 dB matches, k > 1.5, +5 dBm
  IIP3, < 5 mW power) each remain unratified; the ones no longer
  meaningful on this record's evidence (k > 1.5: metric superseded; < 5 mW:
  rejected by 0001's NF-vs-power evidence with ~0.2–0.5 dB bare-device NF
  cost at the required `I_C` ≤ ~2.6 mA) are recorded as dropped-with-
  rationale; the rest remain stated aspirations.

**No relaxed-in-place value anywhere.** The one numeric value changed from
its DRAFT-era placeholder is Supply — from a deliberately tentative
"TBD, 1.2–3.3 V" bounded range to record 0001's evidenced 1.80 V ± 10 %,
which is a *decision* (the value the whole committed evidence base was
generated against), not a relaxation of any previously binding bar.

### Failing-spec cases, disclosed (not absorbed)

| Row | Measured standing of the as-committed DUT | Root cause on the committed evidence | Consequence taken here |
|---|---|---|---|
| Gain | nominal 12.63–12.74 dB (2.4 dB short); 45-cell range −21.06…+14.22 dB | absent input match (~8.9 dB unilateral-availability term, below); bias spread collapses worst cells (#26) | target kept; verification gated on #26+#27; derivation shown |
| NF | nominal 1.867 dB (0.37 dB over); worst 10.30 dB | ~1.1 dB of nominal gap is the absent noise match (`NFmin` 0.751); bias spread (#26); ideal passives optimistic | target kept; verified post-#27 on `nf290` |
| S11 / S22 | nominal −0.575 dB / −0.0044 dB; 40-cell broadband max \|S22\| = 1.000004 | **no matching network exists** — `\|Γ\|` on the chart edge by construction | targets kept unchanged; #27 bound by them |
| Stability | 40/45 cells μ < 1 (min 0.99902) | conditional stability; ideal-lossless passive network is the least-damped case (real Q adds damping) | μ > 1 gated **before** any match is declared final, per `CLAUDE.md` |
| IIP3 | nominal −2.22 dBm; −22.0…+9.7 dBm across cells | bias result, not linearity result (~32 dB swing tracks `I_C1`); ~+8.9 dB available-power-plane mismatch inflation at the nominal cell; Δf base termination is a placeholder | **numeric row not ratified** (no honest bar can be set on this evidence); protocol ratified; number bound only after #26+#27 |
| Power | nominal 7.75 mW (in budget); worst 29.64 mW; mandate exceeded at 21/45 cells | placeholder resistive base-bias divider (#26, `design/README.md` caveat 2) | target kept with 0001's mandate as its budget basis; #26 gates verification |

## Evidence

Every figure below is a cell or column of a committed, append-only record;
record ids and columns are named so each can be re-derived without re-running
anything.

### Traceability — which testbench/commit each ratified row traces to

| Row | Producing evidence | Where it lives (record id → file → commit) |
|---|---|---|
| Band | in-band `sp` grid and 50 Ω NF bench of both campaigns | `sim/lna-characterization/records/20260918-210908-4293920.md` + `testbench/tb_lna_sparam.spice.tmpl` (`sp lin 11 2.4e9 2.4835e9`) — PR #28, commit `04ded14`; device-bias basis: `sim/hbt-characterization/records/20260910-200059-7da7038.csv` — PR #8 |
| Gain | S-parameter campaign (nominal + 45-cell box) | record `20260918-210908-4293920` → `records/…-summary.csv` columns `s21_db_min`/`s21_db_max`, `s11_db_worst` (summary row `sp_typ_27c_vdd1.80v`) — PR #28, commit `04ded14` |
| NF | same campaign; `nf290_*` + `nfmin_sp_db_at_band_lo` columns; dual-method cross-check ≤ 0.0001 dB at 27 °C | same record (`…-summary.csv`, `…-sparam.csv`) — PR #28, commit `04ded14` |
| S11 / S22 | same campaign; `s11_db_worst`, `s22_db_worst`, broadband `\|S22\|` check | same record — PR #28, commit `04ded14` |
| Stability | same campaign's broadband sweep; `k_broadband_min`, `mu_broadband_min`, `k_inband_min`, `mu_inband_min` + `corners/<id>/*.stability.dat` (140 frequencies) | same record — PR #28, commit `04ded14` |
| IIP3 (protocol) | same campaign's two-tone bench: `testbench/tb_lna_iip3.spice.tmpl`, `records/…-iip3.csv`, per-cell `im3_slope_2pt` ∈ [2.981, 3.019], `iip3_dbm_dft_crosscheck` ≤ 0.017 dB | same record — PR #28, commit `04ded14` |
| Supply | record 0001's breakdown budget + the committed extraction bench: BVCEO(500 µA/finger) min **1.6126 V** over 60 cells, 0 cells < 1.4 V; BVCER sustaining ≥ 2.03 V | record 0001 (PR #22) + `sim/breakdown-extraction/records/20260918-212948-013274f.md` / `…-bvceo-summary.csv` — PR #29, commit `f7916e5` |
| Power | record 0001's mandate budget (≤ 9.4 mW worst incl. bias overhead) + campaign operating points | record 0001 (PR #22) + record `20260918-210908-4293920` → `…-summary.csv` column `pdc_w` (nominal row: 7.753 mW) — PR #28, commit `04ded14` |
| Corner box | the campaign's PVT grid definition + `cornerHBT.lib` section inventory in the resolved checkout | `sim/lna-characterization/README.md` §"PVT grid"; `sim/pdk.json` (IHP-Open-PDK **v0.3.0**, tag commit `5cccb161`, fetched via klayout-tools) |

DUT identity for every campaign figure: `design/netlist/lna.spice` (xschem
netlist of `design/lna.sch`, issue #17 / PR #23), sha256
`79447449c494d60159c5430b0fd26e86de382d5426cd2904a693a28f13389b69`,
inlined verbatim into every generated deck; ngspice-46.

### Where each ratified number comes from

- **Gain > 15 dB.** Measured nominal in-band S21 = 12.63–12.74 dB against
  |S11| = −0.575 dB (0.933 linear). Because |S12| ≈ 1.9e−5 (−94 dB, measured,
  nominal cell), the unilateral decomposition's error is negligible, so the
  conjugate-input-match available-gain basis is
  GT,unilateral = |S21|²/(1−|S11|²): 12.63 dB + 10·log10(1/(1−0.933²)) =
  12.63 + 8.9 ≈ **21.5 dB** at the worst in-band point of the nominal
  cell. The ratified 15 dB bar therefore retains ≈ 6.5 dB of allowance for
  (a) matching-network insertion loss and (b) the finite-Q damping of the
  currently ideal-passive tank (campaign model-limitation #1: a real 5 nH
  at 2.44 GHz, Q ≈ 10, carries ~7.7 Ω of series loss). The bar is the
  DRAFT's own literature-anchored number, now shown to sit inside the
  measured (ideal-passive) capability envelope rather than asserted from
  it.
- **NF < 1.5 dB at 290 K.** Nominal `nf290` = 1.867 dB fails the bar
  today; `NFmin` = 0.751 dB (nominal) / 0.600 dB (best cell) bounds what an
  ideal noise match gives this circuit, and ~1.1 dB of the measured gap is
  precisely the missing input match (campaign finding 3). The 0.75 dB
  allowance between `NFmin` and the ratified bar is the budget a real
  (lossy) matching network must fit inside. Reference temperature T0 = 290 K
  is pinned as the ratified definition; the campaign's own dual-method
  cross-check (≤ 0.0001 dB agreement where the two definitions coincide at
  27 °C) evidences the number's implementation, and the −40/+125 °C
  re-referencing behavior is documented and exact.
- **S11/S22 < −10 dB.** The values are the DRAFT's, unchanged; the
  campaign's contribution is the honest *absence*-of-match measurement
  (S11 −0.575 dB, S22 −0.0044 dB at nominal) that #27 must convert into a
  real match, plus the recorded 3-section HBT corner reality (the former
  "fs/sf" binding corner is not exercisable — recorded as a gap, not
  papered over).
- **Stability μ > 1.** The DRAFT row's k > 1 intent is preserved
  assertively (μ > 1 ⇔ unconditional stability ⇔ k > 1 ∧ |Δ| < 1 at every
  frequency, when conditions are non-degenerate; Edwards–Sinsky μ is the
  single necessary-and-sufficient test), while the *binding metric* moves
  to μ because the committed campaign measures k spanning −3.169…25.6 on
  this topology — a ratio of nearly-cancelling fourth-decimal quantities
  with |S12| ≈ −94 dB — i.e. the committed evidence shows quoting
  "k = −1.1" as a margin would be dishonest and μ (no small denominator)
  is the reviewable number. CLAUDE.md's requirement that the k-factor work
  exist is honored by keeping k (and |Δ| and the negative-resistance
  check) co-reported at every cell. This is the same class of decision as
  DR-0001's measured-`V_BE`-over-textbook-TC: pin the definition the
  evidence can actually support.
- **Supply 1.80 V ± 10 %.** Record 0001's budget (worst-case device stress
  `V_CE2` = 1.116 V / `V_CE1` = 1.097 V against the 1.4 V design line),
  upgraded from "process-spec text only" to committed extraction: BVCEO at
  the operating-point criterion (500 µA/finger = 0001's nominal `I_C`)
  ≥ 1.6126 V over all corner × temp × Nx × selft cells — ≥ 0.50 V above
  the worst stress. Honesty notes carried in the spec: two cells extract
  below 1.4 V at the 1 µA/finger *leakage* criterion (criterion-dependence
  is real and stated); and the resolved PDK citation (v0.3.0, March 2026)
  post-dates nothing — it predates the provisional `5e6d592` main-branch
  read, and is authoritative because it is what every committed record was
  generated against.
- **Power < 10 mW.** Record 0001's mandate-derived budget: `I_C ≤ 4.5 mA`
  held over corners ⇒ core ≤ 8.1 mW at 1.98 V, ≤ 9.4 mW with bias-divider
  overhead; measured nominal 7.75 mW (`I_DD` = 4.307 mA). The 20/45-cell
  violation is the placeholder divider's, disclosed; the row binds #26.
- **IIP3 — no numeric ratification.** The 45-cell campaign measures IIP3
  from −22.0 to +9.7 dBm tracking `I_C1` (25 µA–14.7 mA) with a validated
  3:1 slope everywhere — a bias result, not a linearity result (finding 1).
  At the nominal cell the −2.22 dBm extrapolation is on the
  available-power axis at \|S11\| = 0.933: delivered fraction
  1−\|S11\|² ≈ 0.129 ⇒ the device-plane intercept sits ≈ 8.9 dB lower
  (≈ **−11 dBm** at `I_C1` = 4.068 mA; ≈ **−9 dBm** at the best
  in-mandate cell, 4.73 mA). The Δf = 7.63 MHz base termination — which
  dominates bipolar IM3 cancellation — is today a 100 pF block into a
  resistive divider, i.e. a placeholder that #26/#27 replace entirely. No
  bar (the draft's 0 dBm, any measured cell's value, or any adjusted
  number) is honestly bindable on standing evidence, so per the sibling
  ratification rule the row stays DRAFT rather than being force-ratified
  to make T1's checklist convenient; the bench, its parameters, and its
  slope-check mandate are ratified so the future number is
  well-defined the day it can be bound.
- **Band.** The committed design parameters, both campaigns' benches, and
  DR-0001's bias point are all 2.4 GHz-native; the in-band sweep of
  record `20260918-210908-4293920` is literally 2400–2483.5 MHz. The
  decision is "ratify what everything is already built at," not a new
  choice.

### PDK citation re-verification (this issue's guidance item)

The DRAFT spec's source (2) carried a provisional GitHub-API citation
(commit `5e6d592`, 2026-09-01) explicitly "until `klt`'s actually-resolved
PDK checkout is known". It is known: `sim/pdk.json` pins IHP-Open-PDK
**v0.3.0** (tag commit `5cccb161f7492697cfa52eb14dc03beb00bdca9e`,
2026-03-11), fetched via klayout-tools, verified installed
(`.fetched-version` = 0.3.0). The load-bearing model-card lines were
re-read from that local install while drafting this record (2026-09-21):
`* Maximum collector-to-emitter voltage: 1.6`, `vce_max = 1.6`, validity
box unchanged. The resolved release is *older* than the provisional main
read — recorded plainly: the installed release is authoritative because
every committed evidence record was generated against it; the later
upstream `main` state is uninstalled drift.

## Alternatives considered

- **Ratify the measured values (spec → datasheet of the as-committed
  DUT).** Rejected: it would be the forbidden direction — relaxing the
  targets to make results pass — and worse, it would bind the spec to a
  placeholder bias network and an absent matching network, i.e. to defects
  the repo has already filed (#26, #27).
- **Force-ratify every DRAFT number including IIP3 > 0 dBm.** Rejected for
  the IIP3 row specifically: this record's own evidence section shows the
  *device-plane* linearity ~9–11 dB below that bar at the mandated bias —
  ratifying a number the evidence contradicts is force-ratification "to
  unblock downstream verification", the exact failure mode the fleet's
  sibling ratification rule names. The number stays DRAFT; the protocol is
  what gets bound now.
- **Keep the whole table DRAFT until #26 and #27 land.** Rejected: Band,
  Supply, Power, and the binding definitions (port convention, corner box,
  stability metric, NF reference, IIP3 protocol) are already supported by
  merged, committed evidence; withholding them gains nothing and leaves
  T1's "vs. a ratified spec" half permanently unstarted.
- **Scope Power to "nominal-only" or ratify its 29.6 mW PVT worst case.**
  Both rejected: the first silently weakens the corner contract; the second
  is relaxation-to-measured. Keeping < 10 mW with record 0001's mandate as
  the budget basis, plus the disclosed 20/45-cell FAIL against the
  placeholder divider, states the truth and puts the binding where the fix
  (#26) will land.
- **Adjust Gain to ≥ 12 dB (the measured nominal).** Rejected — the
  measured shortfall is the missing input match, quantified (~8.9 dB
  unilateral availability); relaxing to today's unmatched number would bake
  the known-absent matching network into the spec.

## Consequences

- **What binds now:** Band, Gain (S21 > 15 dB), NF (< 1.5 dB @ 290 K),
  S11/S22 (< −10 dB), Stability (μ > 1, 10 MHz–30 GHz, every ratified
  cell, k/Δ/negative-resistance co-reported), Supply (1.80 V ± 10 %,
  cascode `npn13G2` Nx = 8 — record 0001 thereby ratified), Power
  (< 10 mW under the 0001 mandate), the corner box, the 50 Ω/T0 = 290 K
  port-and-reference convention, and the IIP3 measurement protocol.
  Record 0001's status field flips to ratified via this record.
- **What this unblocks:** T1 tracker #4's checklist item 5 now has its
  ratified-spec half in existence; its re-check against `origin/main`
  remains a future pass (per issue #19's own acceptance criteria, the
  tracker's item is referenced by the ratification PR, not marked met
  here). The #26/#27 design issues now carry explicit, numeric binding
  targets instead of DRAFT hypotheses, and #27 additionally carries the
  μ-gate ordering constraint: stability re-checked before any match is
  declared final.
- **The IIP3 row's next step:** after #26 and #27 land, re-run the
  campaign unchanged (the runner needs no edits) and ratify the numeric
  row on that re-measurement in its own record — at which point any value
  below the DRAFT-era > 0 dBm framing is a relax-after-measured-FAIL
  disposition and needs the two-key market competitiveness finding (or
  the operator's, until #372 lands) plus a superseding record.
- **Honest negatives, carried forward deliberately:** every performance
  number the campaign produced is optimistic-by-construction (ideal
  passives; no silicon; no layout parasitics; no mismatch axis; `sf`/`fs`
  are `typ` duplicates in this PDK), the as-committed DUT fails Gain, NF,
  S11, S22 and Stability rows today (disclosed per-row), Power fails at
  20/45 cells until #26 lands, the sub-dB NF thesis remains unproven
  (stretch unratified), and the former < 5 mW power stretch is retired
  with rationale rather than left as a silent bar. None of these are
  spec-failures of a ratified row: they are the recorded standing of the
  work-in-progress design against the bar it is now formally held to.
- **Append-only discipline:** record 0001 is not rewritten; only its
  status line and status-lead paragraph are updated by this record's
  ratification (the pre-ratification text is preserved in place with its
  resolution noted). Any future change to a row this record ratifies
  requires a superseding decision record — never an in-place edit.
