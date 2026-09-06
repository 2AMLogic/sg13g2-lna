# Target specification — DRAFT

**Status: DRAFT. Nothing in this file is ratified.** Every row below is
marked "DRAFT — to be ratified" and is a **starting point for engineering
ratification, not a settled datasheet number.** This is the first RF block
in the fleet (no same-block sibling to port a ratified table from), so
every numeric value here is derived from general inductive-degeneration LNA
literature and the SG13G2 device menu's static process-spec numbers — none
of it is simulation output yet. Per `CLAUDE.md`, "a gain or NF claim without
its bench is not a result"; ratification is gated on a future
spec-ratification issue (mirroring the two-key EE-key + market-key
mechanism the fleet uses elsewhere) and on the S-parameter/noise testbenches
this repo's README names as its first real work. Until ratification, no
design or simulation work may treat a row here as final, and agents must
not replace a DRAFT with an invented "final" number — a value becomes
settled only when a decision record ratifies it.

## Port convention (stated explicitly, per `CLAUDE.md`)

**All S-parameters, gain, and match figures in this document are defined at
a 50 Ω reference impedance at both the input and output ports**, matching
the top-level README's own framing ("NF and S-param numbers carry their
bench definitions. Port impedances, bias points, and the exact ngspice
analysis ... are committed beside every recorded number"). Any future
testbench that departs from a 50 Ω port (e.g. an on-chip source impedance
sweep for noise-figure sensitivity) must state so explicitly beside its
result — it does not change this row's definition.

## Where these numbers come from

Three sources, cited per row below, **none of which is silicon or an
ngspice simulation result**:

1. **Classic inductive-degeneration LNA literature (topology-level, not
   device-specific).** D. K. Shaeffer and T. H. Lee, "A 1.5-V, 1.5-GHz CMOS
   Low Noise Amplifier," *IEEE JSSC*, 1997 — the standard reference for what
   an inductively-degenerated common-emitter/source LNA can achieve
   (simultaneous noise and power matching, achievable gain/NF/S11 ranges).
   S. P. Voinigescu et al., "A Scalable High-Frequency Noise Model for
   Bipolar Transistors with Application to Optimal Transistor Sizing for
   Low-Noise Amplifier Design," *IEEE JSSC*, 1997 — the standard SiGe-HBT
   noise-optimization reference (optimum bias current density for minimum
   NF as a function of device geometry). Both are topology/device-class
   references cited for **achievable-range** framing, not numbers to be
   transcribed as this block's targets.
2. **IHP SG13G2 process specification** —
   `IHP-GmbH/IHP-Open-PDK`, `main` branch, commit
   [`5e6d592`](https://github.com/IHP-GmbH/IHP-Open-PDK/commit/5e6d592e4002946a4616f798c357f0f3c06cf3b6)
   (2026-09-01), read via the GitHub API for this issue since `klt`'s
   PDK-resolver step has not run for this repo yet — **a public-repo `main`
   read is provisional until `klt`'s actually-resolved PDK checkout is
   known; re-verify against that checkout once tooling access lands.**
   Specifically:
   `ihp-sg13g2/libs.doc/doc/SG13G2_os_process_spec.pdf` (Rev. 1.2,
   2023-12-20) — §1 "General Information" (SG13G2 HBT: fT up to 300 GHz,
   fmax up to 500 GHz — "much higher bipolar performance" than the base
   SG13S process) and §3.1 "npn13g2" (the primary HBT flavor: fT target
   350 GHz / min 300 GHz, fmax target 450 GHz / min 400 GHz, BVCEO target
   1.6 V / min 1.4 V, current gain BF target 650 / min 300 / max 1200,
   IC07 target 3.8 µA at AE = 0.07×0.9 µm²) — and
   `ihp-sg13g2/libs.tech/ngspice/models/sg13g2_hbt_mod.lib` (the VBIC
   Rev. 1.15 SPICE model card these process-spec numbers correspond to).
   These are static device-capability numbers, not simulated LNA
   performance — they bound what the topology-level literature numbers in
   (1) are plausible to reach on this specific device, nothing more.
3. **This repo's own README**, which states the block's thesis claim —
   "sub-dB noise figures at low GHz are textbook SiGe territory" — as
   **motivation for the block's existence, not a verified result.** Where a
   row below reflects that claim (the NF stretch column), it is flagged as
   such: an aspiration this repo exists to test, not a number already
   demonstrated on SG13G2.

Where a value cannot yet be sourced from any of the three — because it
depends on a decision (topology, bias point, supply rail) this issue is
explicitly scaffolding rather than making — the row says so and carries a
range or "TBD, pending decision record" rather than an invented number.

## Open topology question this table does not resolve

**Bias/supply topology is not yet decided** and several rows below (Supply,
Power, and indirectly Gain/NF/IIP3, which all depend on bias current and
device stacking) are bounded rather than pinned as a result. `npn13g2`'s
`BVCEO` is only 1.4–1.6 V (min/target) — low enough that a naive
common-emitter-plus-cascode stage stacked on a 3.3 V rail (this PDK's other
canaries' usual HV-flavor rail, per `sg13g2-bandgap`/`sg13g2-ldo`) would put
each device well past its own individual breakdown unless the topology
distributes voltage stress deliberately (e.g. a true cascode where each
device only ever sees a fraction of the rail, or a lower-voltage
single-stage design). This is genuinely novel RF work this repo's own
porting plan (`porting-plan.md` §"What is genuinely novel") flags as having
no sibling precedent to port — CMOS-canary "which supply flavor" decision
records (bandgap DR-0002, pll DR-002) reason about MOSFET gate-oxide
ratings, not bipolar breakdown-voltage stacking, so the reasoning pattern
does not transfer even though the decision-record *process* does. Resolving
it is a future decision record, not this bootstrap issue.

## DRAFT target table

Every row is **DRAFT — to be ratified**, source-cited via the "Src" column
against the numbered list above. Corner scope for every row is the
"Verification corners" section below unless the row itself states a
narrower binding corner.

| Parameter | DRAFT target | DRAFT stretch | Src | Binding corner (expected, unverified) | Note |
|---|---|---|---|---|---|
| Band | 2.4 GHz ISM (2400–2483.5 MHz), draft primary candidate | 5–6 GHz variant as a separate follow-on | (1) | — | Low-GHz choice trades off `npn13g2`'s 300+ GHz fT headroom for measurement/reproducibility ease with open tools (ngspice `.sp`/`.noise`, on-chip inductor Q at low GHz is more forgiving for a first RF canary). Alternate bands are an open item, not ratified by this document. |
| Gain (S21) | > 15 dB across band | > 18 dB | (1) | ss process corner, 125 °C, min supply | Single-stage inductively-degenerated common-emitter (or cascode, pending the open topology question above) target; not yet simulated on SG13G2 device models. |
| Noise figure (NF) | < 1.5 dB across band | < 1.0 dB ("sub-dB", per README's own thesis claim — (3)) | (2)+(3) | ss process corner, 125 °C (device noise degrades with temperature; also worst self-heating per `npn13g2`'s VBIC thermal subcircuit) | The stretch column states this repo's own reason to exist, not a demonstrated result — see source (3). Actual optimum-NF bias current density is a `Voinigescu`-style device-sizing exercise still to be done against `sg13g2_hbt_mod.lib`. |
| Input match (S11) | < −10 dB across band | < −15 dB | (1) | fs/sf process corners (L/C mismatch), extremes of temperature | Defined at the 50 Ω port convention above. Achieved via inductive source degeneration; exact L/C values are a future design-record, not this document. |
| Output match (S22) | < −10 dB across band | < −15 dB | (1) | fs/sf process corners, extremes of temperature | Same 50 Ω port convention; output match interacts with the load-inductor Q, which is itself an open `klayout-tools`-passive-model question (see `porting-plan.md`). |
| Stability (k-factor) | k > 1 (unconditionally stable) across band and out-of-band to at least 3× the upper band edge | k > 1.5 (margin) | CLAUDE.md | worst-case process/temp/supply corner combination, out-of-band as well as in-band | `CLAUDE.md`: "Stability is a spec row, not an afterthought — k-factor / stability circles across the band, at PVT corners, before any matching is declared final." Not one of the README's six named headline parameters, but required by this repo's own house rule; included here so it is never an afterthought. |
| IIP3 | > 0 dBm | > +5 dBm | (1) | tt process corner, nominal supply, nominal temperature (linearity is typically best at nominal bias; corner-dependence to be confirmed by the two-tone testbench itself) | Per `CLAUDE.md`, must be measured via two-tone transient with tone spacing and FFT parameters recorded alongside the number — no IIP3 claim is valid without that bench. |
| Supply | TBD — bounded by `npn13g2`'s BVCEO (1.4 V min / 1.6 V target); range 1.2–3.3 V pending the open topology question above | — | (2) | — | Not ratifiable until the bias/supply-topology decision record (see "Open topology question" above) lands. Listed here as a placeholder row, not a number, per this document's own "no invented number" rule. |
| Power (Pdc) | < 10 mW | < 5 mW | (1) | ff process corner, min temperature (bias current typically peaks here for a fixed bias network) | Depends directly on the Supply row above; both numbers move together once the topology decision record lands. |

## Verification corners (DRAFT)

Starting point, to be ratified alongside the rows above: process
{tt, ff, ss, fs, sf} (SG13G2's `cornerHBT.lib` ships all five,
`ihp-sg13g2/libs.tech/ngspice/models/cornerHBT.lib`, per source (2)) ×
temperature {−40, 27, 125} °C × supply ±10% around whatever nominal value
the Supply row above eventually ratifies. The passive-model corner set
(`cornerCAP.lib`, and whatever corner data exists for the inductor pycells
— see `porting-plan.md` §"Tooling friction anticipated in advance" for the
open question of whether an inductor SPICE corner model exists at all) is a
second, not-yet-resolved axis this table does not attempt to bind yet.

## Open items that must close before ratification

1. **Band selection.** 2.4 GHz ISM is a draft primary candidate, not a
   ratified choice — an alternate-band decision record is in scope for a
   future issue.
2. **Bias/supply topology** (cascode vs. single-stage, exact supply
   voltage) — see "Open topology question" above. Blocks the Supply and
   Power rows, and indirectly bounds achievable Gain/NF/IIP3.
3. **Matching-network passive models.** Inductive source/load degeneration
   needs the PDK's inductor pycell + SPICE/EM model story resolved first
   (open question, see `porting-plan.md`) — S11/S22 numbers cannot be
   simulated, only asserted from literature, until then.
4. **Device noise-optimum sizing.** The `Voinigescu`-style optimum bias
   current density for minimum NF has not been derived against
   `sg13g2_hbt_mod.lib`'s actual noise parameters.

Decision records live in `spec/decision-records/` (create the directory
when the first record is written; copy a `TEMPLATE.md` from a sibling repo
such as `sg13g2-bandgap/spec/decision-records/` to start it — one decision
per record, numbered sequentially, append-only: supersede, never edit). A
row above is ratified only when a decision record says so.
