# 0003: Flat PVT bias reference topology for Q1 (issue #33's design space)

- **Status**: proposed
- **Date**: 2026-09-21
- **Decided by**: Builder (Loom), issue #33
- **Issue**: [#33](https://github.com/2AMLogic/sg13g2-lna/issues/33)
  (tracks the flat-reference direction issue #26's PR stated as its
  documented deviation — the structural way out the issue's own body
  names)

## Context

The committed bias family (issue #26 / PR #34: `R3a` feed + diode-Q3
8:1 `npn13G2` density mirror) holds both ratified bars
(`I_C1 ≤ 4.5 mA`, `P_dc < 10 mW`, both ratified via [0002](0002-target-spec-first-ratification.md))
at every cell of the 45-cell grid, but lands the nominal at 3.06 mA —
24 % below DR-0001's 4.0 mA plan-table entry, deliberately, because the
family's reference current is `I ≈ (VDD − V_BE3)/R3a`: the feed
headroom `(VDD − V_BREF)` spans 0.7307..1.2345 V over the corner box
(1.69:1), and a 4.0 mA nominal sizes the worst cell at ~5.3 mA /
~12.3 mW. The ~0.11 dB of bare-device NF that stands behind the 4.0 mA
entry (measure 2.330 → ≈2.20 dB, interpolated on DR-0001 §"The
bias-current range") is what this issue exists to recover. Any
reference family that re-lands 4.0 mA must hold the binding hot cell
(`bcs`/125 °C/1.98 V) within ≈ 1.08-1.10 of nominal
(current bar 4.5/4.0; the P_dc bar effectively tightens this to
≈ 4.35-4.4 mA once the divider and reference-branch currents are
budgeted) — a flatness the committed family cannot reach by
re-sizing.

All numbers in this record trace to committed benches: the committed
family's from
`sim/lna-bias-pvt/records/20260921-132025-d6da30a*` (record 1 of that
experiment), the new candidate probes from
[`sim/biasref-topology/`](../../sim/biasref-topology/README.md)
(record `20260921-154716-f718094`, the bench committed beside them per
`CLAUDE.md`).

## Decision

**Choose Option A — a complementary-mirror (HV PMOS) flat-reference
core — staged.** The netlist will lock to a two-stage reference core
replacing the `R3a` feed:

- **Stage 1 (measured, landed with this record's bench): the
  supply-independent stage** — a self-biased Widlar PTAT loop built
  from `sg13_hv_pmos` (PSP103.6 via OSDI) and the existing `npn13G2`
  vocabulary: a diode-connected HV-PMOS over the degenerated feedback
  leg (`Nx=8`, emitter resistor `Rp`), a plain-diode leg (`Nx=1`)
  cross-coupled to the feedback leg's base, a 10 MΩ startup seed, and
  an output copy into the existing Q3 reference island. The HV flavour
  is **mandatory**, not preferred: DR-0001's ratified "any MOS in the
  bias network must therefore be the HV flavour" constraint (LV MOS
  `VDS_MAX = VGS_MAX = 1.6 V` < `VDD,max` = 1.98 V) binds this choice
  — the issue's own Option-A sketch named `sg13g2_lv_pmos`, and that
  variant is infeasible within the ratified constraint. The
  PVT-corners for the MOS device ride `cornerMOShv.lib`
  (`typ→mos_tt`, `bcs→mos_ff`, `wcs→mos_ss`, `sf/fs` as labelled),
  the same mapping `sg13g2-bandgap/sim/lib/pvt_preflight.sh` documents
  for this PDK.
- **Stage 2 (the follow-on issue's deliverable, the flat core proper):
  an amp-servo'd mixed-tone output** that converts the Stage-1 PTAT
  current plus a `V_BE`-anchored CTAT tone into the island current —
  an error-amplifier-closed Kuijk-style sum with a
  bare-resistor-transduced flat-current output, sized so `I_C1`
  re-lands at DR-0001's 4.0 mA nominal (± the tolerance a sized
  Stage-2 DR-stated amendment of this record states with its own
  measurements, not this record's estimates), and the two ratified
  bars re-verified over the unchanged 45-cell
  `sim/lna-bias-pvt/run_biasop_sweep.sh` bench plus the three-cell
  supply-ramp startup check.

The staged split is the sibling fleet's own proven arc for exactly this
topology class (sg13g2-bandgap: core in #16, OSDI toolchain in #22,
error amp in #9, startup cell in #24, closed-loop PVT/Iq in #88/#95),
not an invention of this record: the OSDI toolchain stage (this PR)
took that arc's own shape.

## Evidence

- **The single-junction wall (formal).** Any feed-forward family of the
  form `I ∝ (VDD − d(T,c))/R` over a single diode drop `d` fails the
  bars at a 4.0 mA nominal: the binding-cell constraint
  `(1.98 − d_hot)/(1.80 − d_nom) ≤ 1.125` requires
  `d_hot ≥ 1.09·d_nom + 0.018`, a ~+9 % T-rise of the drop — while
  every junction drop in this PDK *falls* with temperature
  (−0.66..−0.83 mV/°C measured family). No sized single-junction
  feed-forward family can hold both bars; this closes the general
  question the issue's Option-B sketch left "not traced", independent
  of which diode is chosen.
- **Option B, measured (the `pnpMPA` trace).**
  [`sim/biasref-topology/`](../../sim/biasref-topology/README.md)
  record `20260921-154716-f718094`, Phase A: the substrate-PNP diode's
  terminal drop and its implied feed family at three currents —
  hot/nominal ratio **1.392** (0.52 mA), **1.335** (100 µA), **1.326**
  (20 µA), i.e. worse than the committed `npn13G2` family's own
  **1.280** (V_BREF 0.7455/0.8349 V from the committed 45-cell
  record) at every traced scale: `rb = 700 Ω` at `bf = 1.10` both
  raises the drop and widens its T-swing. Option B is thereby
  *measured-refuted* as the flat family, not merely argued against.
- **Option A Stage 1, measured (supply independence).** Same record,
  Phase B: over `{typ,bcs,wcs} × {−40,27,125} °C × {1.62,1.80,1.98} V`
  with the MOS corner mapped as above, the skeleton's island current
  moves **≤ 0.90 %** across the full ±10 % VDD swing (worst per
  -(corner,T) cell), versus the committed family's **47.4 %** measured
  the identical way (ic3 share, worst per-(corner,T) move, from the
  committed record's own CSV). The supply term — the dominant term of
  the committed family's envelope — is thereby removed, exactly as
  the issue's wall-1 diagnosis required.
- **Option A Stage 1, measured (residual tone + startup).** Same
  record: the skeleton's residual tone is PTAT-shaped
  (hot/nominal gain 1.355, cold 0.766 at the binding cells), which is
  the two-leg self-bias cell's expected behaviour — Stage 2's
  mixed-tone output is the mechanism that must trim it, and this record
  makes no flatness claim for the skeleton. The seed leg boots the
  loop out of its zero-current degenerate state at all three
  committed startup-ramp cells (Phase C: PASS ×3) — a latch surface the
  committed feedforward family does not have, and one the unchanged
  ramp bench must keep checking.
- **The two-element-pair degeneracy (formal, bounds Stage 2's shape).**
  Stage 2 must generate its CTAT weight as `V_BE`-anchored current, not
  as a diode-pair difference: any two matched junctions differ by
  `V_T·ln(…)` (PTAT), and any series-stack difference re-inserts a
  supply-referenced or PTAT term — the same arithmetic that makes
  bare-resistor-transduction of a servo'd flat voltage the only
  flat-current mechanism in this vocabulary. This was probed, not
  assumed: the emitter-resistor and shunt-resistor variants of the
  island feed were measured during bench development and moved the hot
  gain at most 1.31 → 1.23 — nowhere near the required ≤ ~1.08.
- **P_dc budget fact (Stage 2 sizing input, from committed rows).** At
  the binding cell (1.98 V) the bar `P_dc < 10 mW` fixes
  `I_dd < 5.05 mA`; with the committed divider (~165 µA at 1.98 V) and
  a scales-others-budgeted reference overhead the usable stack current
  lands near `I_C1 ≤ ~4.3-4.4 mA` there — the number the Stage-2
  sizing must hold with stated margin, and the reason the 4.0 mA
  nominal is tight but feasible for a ≤ ~1.05 flat family and
  infeasible for anything with the committed family's envelope.

## Alternatives considered

- **Option B — `pnpMPA` diode-only core** — measured-refuted above; see
  Evidence. Rejected on measurement, at far lower toolchain cost,
  which is exactly the trace the Curator pass asked for.
- **Option A with `sg13g2_lv_pmos` (the issue's own sketch)** —
  infeasible within DR-0001's ratified LV-MOS constraint
  (`VDS/VGS ≤ 1.6 V < 1.98 V`); the HV flavour is load-bearing.
- **Option C — supply/rail decision variant (stacked/boosted bias
  rail)** — rejected: DR-0001's 1.8 V ±10 % rail is *ratified*, the
  Power bar counts the bias network's own consumption, and a
  generated rail needs a switching stage outside this repo's committed
  device vocabulary and own breakdown budget pass. It remains what
  DR-0001's text already allows: a rail decision that would have to
  supersede a record, not an implementation detail under the current
  one.
- **Re-sizing the committed family to a "4.0-shaped" nominal** —
  formally disproven (the single-junction inequality above): no R3a
  value lands 4.0 at nominal inside the bars; the committed 3.06 mA
  choice was already the family's honest optimum (issue #26's stated
  trade).

## Consequences

**Enabled**

- The Stage-2 core can now lock to concrete, measured primitives: a
  supply-independent PTAT stage (0.90 % supply sensitivity measured),
  an island feed whose corner convention and startup behavior are
  bench-proven, and an exact headroom/`P_dc` budget at the binding
  cell.
- The OSDI toolchain (`sim/tools/build-osdi.sh`) and the MOS corner
  mapping are in the tree, so the Stage-2 netlist change touches no
  new infrastructure.

**Costs and constraints this imposes**

- **Two MOS devices now require the OSDI step** wherever the bench
  instantiates them: benches fail fast without it (runner preflight),
  and the 45-cell `lna-bias-pvt` bench — when Stage 2 lands its DUT
  change — must gain `cornerMOShv.lib` section substitution plus
  `pre_osdi` lines while preserving the bar evaluation
  byte-identical in meaning (the bars, their columns and the awk
  verdicts do not change; only the generated decks' `.lib`/`pre_osdi`
  preamble does).
- **Stage 2 is a real design arc, not a re-size**: an error-amplifier
  stage at a 1.62 V worst-case rail (the sibling's 3.3 V amp stack
  needs re-sizing to ~55 % of its headroom), the mixed-tone output
  and trim, plus the unchanged-runner 45-cell bars, the three-cell
  ramp startup pass on a *closing* loop, and a DR-stated nominal
  tolerance backed by its record. The follow-on issue carries this
  scope explicitly, with this record's numbers as its sizing input.
- **Layout-time matching obligations arrive with the mirror bank**:
  the 21:1 output copy (and Stage 2's ratio devices) are
  no-mismatch-section bench numbers today; centroid layout matching
  is a budget item before any ratified claim (matching every
  `no mismatch sections` caveat in this tree).
- The `R3a` re-size the issue named happens as a *deletion* inside the
  Stage-2 core swap, not as a standalone passive change.

**Follow-up work this record does not do**

- The Stage-2 core design, DUT swap and the re-verification records
  (45-cell bars + three-cell startup + the DR-stated nominal
  tolerance at 4.0 mA): tracked as the issue this record's companion
  PR files.
- Model-validity-box audit of the amplifier stage's devices at all 45
  cells once it exists (the same recheck discipline the committed
  record documents).
