# measurements/

Measured/derived results with their evidence chains.

This file is the **characterization report** for the block: it reads the
append-only evidence under [`../sim/`](../sim/README.md) and states what it
means for [`../spec/target-spec.md`](../spec/target-spec.md). It contains no
numbers of its own — every figure below is a copy of a value committed in a
`sim/*/records/` CSV, with the record id and column named so it can be
checked.

## ⚠️ Read this before quoting any number below

1. **`spec/target-spec.md` is RATIFIED for the rows it marks RATIFIED, and
   still DRAFT for the rest.** Its own status line remains the single
   source of truth: ratification landed via decision record
   [0002](../spec/decision-records/0002-target-spec-first-ratification.md)
   (issue [#19](https://github.com/2AMLogic/sg13g2-lna/issues/19), merged
   as PR #32) — the band, gain, NF, S11/S22, stability, supply and power
   rows are binding, while the IIP3 numeric target and every former DRAFT
   *stretch* column remain DRAFT by that record's explicit carve-outs.
   Nothing here is a conformance verdict: the DUT this report reads is the
   as-committed pre-#26/pre-#27 design (placeholder bias network, no
   matching network, ideal passives), so the comparisons below remain
   descriptive — measured shortfalls against the target rows, disclosed as
   such — and the language stays "against the target", never "passing".
2. **These are simulations of a schematic with idealized passives, not
   measurements of silicon.** Both inductors, all four capacitors and all
   four bias resistors in `design/lna.sch` are generic ideal SPICE
   primitives; only the two `npn13G2` HBTs are real PDK models. SG13G2's
   open PDK ships **no simulatable SPICE/EM model for any on-chip
   inductor** (issue [#5](https://github.com/2AMLogic/sg13g2-lna/issues/5),
   upstream
   [`2AMLogic/klayout-tools#1519`](https://github.com/2AMLogic/klayout-tools/issues/1519),
   still open). Infinite-Q inductors make gain, NF and both match figures
   **optimistic**, and make stability **numerically degenerate** — see
   "Limitations" below, which is not boilerplate here but the single largest
   caveat on the table.
3. **The DUT has no matching network at all**, so the S11/S22 rows below are
   not a failed match, they are the absence of one.

## The campaign this report reads

| | |
|---|---|
| Experiment | [`../sim/lna-characterization/`](../sim/lna-characterization/README.md) (issue [#18](https://github.com/2AMLogic/sg13g2-lna/issues/18)) |
| Record id | `20260918-210908-4293920` |
| DUT | `design/netlist/lna.spice` (xschem netlist of `design/lna.sch`, issue #17 / PR #23), inlined verbatim into every deck; sha256 recorded in the record |
| PDK | `ihp-sg13g2`, IHP-Open-PDK **v0.3.0** (pinned in [`../sim/pdk.json`](../sim/pdk.json)) |
| Simulator | ngspice-46 |
| Port convention | **50 Ω at both ports**, applied by ngspice `sp`-analysis port sources (`portnum`/`z0 50`) — `spec/target-spec.md`'s own stated convention |
| PVT grid | **full**: {typ, bcs, wcs, sf, fs} × {−40, 27, 125} °C × {1.62, 1.80, 1.98} V = **45 cells**, both phases at every cell, **138 `ngspice -b` invocations** |
| Raw evidence | per-point generated decks, raw ngspice logs, raw complex S-parameters and 140-frequency broadband stability tables, all committed under `../sim/lna-characterization/{netlist-snapshots,corners}/20260918-210908-4293920/` |
| Bench definitions | [`../sim/lna-characterization/README.md`](../sim/lna-characterization/README.md) — port impedances, the exact `sp`/`.noise`/`tran` analyses, the two NF reference temperatures, tone spacing and FFT parameters, and the stated limits of the IIP3 method |

**Corner-label caveat**: `cornerHBT.lib` ships **three** real HBT sections,
not five. `typ→hbt_typ`, `bcs→hbt_bcs`, `wcs→hbt_wcs`, and **`sf`/`fs` both
fall back to `hbt_typ`** — so 18 of the 45 cells are numerically identical to
their `typ` counterparts, and `spec/target-spec.md`'s "fs/sf process corners
(L/C mismatch)" binding corner for S11/S22 **is not exercised by this
campaign at all**. It cannot be: the L/C it refers to are ideal primitives
here with no corner models to sweep. Read `wcs` as this repo's
`ss`-equivalent. Full reasoning: [`../sim/README.md`](../sim/README.md)
§"Corner-label convention".

## Results against the DRAFT target table

Worst/best are across all 45 PVT cells unless stated. Every figure is a cell
of `../sim/lna-characterization/records/20260918-210908-4293920-summary.csv`
(column named in the last row of each block).

| DRAFT row | DRAFT target | DRAFT stretch | Nominal cell (typ/27 °C/1.80 V) | Worst of 45 cells | Best of 45 cells |
|---|---|---|---|---|---|
| **Gain (S21)** | > 15 dB across band | > 18 dB | **12.63 … 12.74 dB** | **−21.06 dB** (wcs/−40 °C/1.62 V) | **+14.22 dB** (bcs/−40 °C/1.98 V) |
| **Noise figure (NF)**, `T0` = 290 K | < 1.5 dB across band | < 1.0 dB | **1.867 dB** | **10.30 dB** (wcs/−40 °C/1.62 V) | **1.054 dB** (bcs/−40 °C/1.98 V) |
| **`NFmin`** (not a spec row; what an ideal noise match would give this circuit) | — | — | **0.751 dB** | 3.309 dB (wcs/−40 °C/1.62 V) | **0.600 dB** (bcs/−40 °C/1.80 V) |
| **Input match (S11)** | < −10 dB across band | < −15 dB | **−0.575 dB** | **−0.244 dB** (bcs/−40 °C/1.62 V) | −0.768 dB (wcs/125 °C/1.98 V) |
| **Output match (S22)** | < −10 dB across band | < −15 dB | **−0.0044 dB** | **−0.0034 dB** (bcs/−40 °C/1.80 V) | −0.0059 dB (wcs/125 °C/1.62 V) |
| **Stability (k)** | k > 1 across band **and** out-of-band to ≥ 3× the upper band edge | k > 1.5 | in-band **k = 0.431**, **μ = 0.99962** | broadband **k = −3.169** at 66.8 MHz and **μ = 0.99902** at 29.9 GHz (both bcs/125 °C/1.98 V); in-band worst **k = 0.346** (fs/125 °C/1.62 V), **μ = 0.99952** (wcs/125 °C/1.80 V) | k = 25.6 in-band, μ = 1.00062 — only at wcs/−40 °C/1.62 V, where the amplifier is effectively off |
| **IIP3** | > 0 dBm | > +5 dBm | **−2.22 dBm** | **−22.03 dBm** (wcs/−40 °C/1.62 V) | **+9.68 dBm** (bcs/125 °C/1.98 V) |
| **Supply** | 1.80 V ± 10 % (decided: DR-0002 makes DR-0001's 1.8 V proposal binding) | — | swept ±10 %: 1.62 / 1.80 / 1.98 V | — | — |
| **Power (P_dc)** | < 10 mW | < 5 mW | **7.75 mW** | **29.64 mW** (bcs/125 °C/1.98 V) | 0.39 mW (wcs/−40 °C/1.62 V, amplifier effectively off) |

*Summary-CSV columns behind each row, in order*: `s21_db_min` /
`s21_db_max`; `nf290_db_worst`; `nfmin_sp_db_at_band_lo`; `s11_db_worst`;
`s22_db_worst`; `k_inband_min` / `k_broadband_min` / `mu_broadband_min`;
`iip3_dbm_a2mv`; `pdc_w`. "Worst" for a match or NF row means the numerically
*least favourable* cell, which for S11/S22 is the one closest to 0 dB.

**Distance from the target rows, stated plainly**: at the nominal cell,
gain is **2.4 dB short** of the target, NF is **0.37 dB over**, IIP3 is
**2.2 dB under** its still-DRAFT numeric target, S11 is **9.4 dB short**,
S22 is **10 dB short**, and stability does not meet "k > 1 across band"
anywhere except at cells where the amplifier is essentially off. Power is
within the target at nominal and **~3× over it** at the worst cell. These
are disclosed shortfalls of the as-committed design against rows DR-0002
ratifies — each ratified row's note in `spec/target-spec.md` records them
with their root cause (#26's placeholder bias network, #27's absent
matching networks) — not conformance verdicts, which await the re-runs
those issues gate.

## The three findings that matter

### 1. The bias network, not the RF design, dominates every PVT number

`I_C1` spans **0.0249 mA to 14.70 mA** across the 45 cells — a **~590×
spread** around a 4.068 mA nominal — because `Q1`'s base bias is a bare
`V_BE`-referenced resistive divider (`R1a`/`R1b`), which `design/README.md`
already labelled a "first-order, single-corner placeholder". Consequences,
all from the same summary CSV:

- **21 of 45 cells** exceed DR-1's own `I_C1 ≤ 4.5 mA` bias-network
  requirement; **20 of 45** exceed the DRAFT `P_dc < 10 mW` row.
- Gain swings ~35 dB and NF swings ~9 dB across the corner box **entirely
  because of bias**. The `−21 dB` gain / `10.3 dB` NF worst cells are not an
  RF result; they are an amplifier that is switched off.
- IIP3 tracks the same axis, from **−22.0 dBm to +9.7 dBm** — a 31.7 dB
  swing, and **20 of the 45 cells** clear the DRAFT `> 0 dBm` row while the
  nominal cell does not. A linearity number that moves 32 dB with bias is a
  bias result, not a linearity result.

Until this is fixed, no other PVT number in this table is characterizing what
it appears to characterize. Filed as
[#26](https://github.com/2AMLogic/sg13g2-lna/issues/26).

### 2. There is no matching network, and stability says one cannot simply be bolted on

`Cin`/`Cout` are 100 pF DC blocks (≈ 0.65 Ω at 2.44 GHz), there is no base
inductor, and `Lc` presents an essentially **lossless reactive** collector
load — so |Γ| sits on the edge of the Smith chart at both ports by
construction (`S22 = −0.004 dB` is a lossless reflection, not a design
error).

The stability result is what makes this a *gate* rather than a to-do, per
`CLAUDE.md` ("k-factor / stability circles across the band, at PVT corners,
**before any matching is declared final**"):

- **μ (Edwards–Sinsky) < 1 at 40 of the 45 cells**, in-band *and* across the
  full 10 MHz – 30 GHz sweep (12× the upper band edge; the DRAFT row asks for
  ≥ 3×), with a minimum of **0.99902**. The amplifier is **conditionally**,
  not unconditionally, stable: a matching network is not free to present an
  arbitrary passive termination, and every candidate network must be
  re-checked against this same bench.
- **k reaches −3.169**, but k must be read with μ beside it here: with
  |S11| ≈ 0.94, |S22| ≈ 0.9995 and |S12| ≈ −94 dB, *both* the numerator and
  the denominator of Rollett's k nearly vanish, so k is a ratio of two
  fourth-decimal-place differences. It is a real result and a badly
  conditioned one. μ has no such problem and is the number to reason from.
  See [`../sim/lna-characterization/README.md`](../sim/lna-characterization/README.md)
  §"Why k is ill-conditioned on this circuit".
- **17 of 45 cells show |S22| marginally above unity** (max **1.000004**, at
  240–400 MHz, with the input at its 50 Ω reference). At +4 ppm this is
  indistinguishable from the numerical resolution of a lossless port — but it
  appears only in the higher-current cells and at a consistent frequency, so
  it is flagged for re-checking once a *lossy* inductor model exists, not
  dismissed.

Filed as [#27](https://github.com/2AMLogic/sg13g2-lna/issues/27).

### 3. The "sub-dB NF" thesis is not refuted — the gap is the missing input match

The repo's own thesis claim ("sub-dB noise figures at low GHz are textbook
SiGe territory", `spec/target-spec.md` source (3)) is testable against a
number this campaign produces directly. At the nominal cell the circuit
delivers **NF = 1.867 dB** into a bare 50 Ω source while its **`NFmin` is
0.751 dB** — and the best cell's `NFmin` is **0.600 dB**. Roughly **1.1 dB of
the present NF is the absent input match**, not the device.

That does **not** demonstrate sub-dB NF: `NFmin` is what an *ideal*,
lossless source-impedance transformation would give, and a real matching
network built from real (lossy, finite-Q) SG13G2 inductors will not be
ideal — finite inductor Q adds directly to NF at the input. What it does
establish is that the DRAFT stretch row is **reachable in principle on this
topology and this device**, and that the ratification argument for the NF row
should be about achievable matching-network loss, not about the HBT.

## Cross-checks performed (why these numbers are believable)

Each quantity is produced twice, by independent methods, and both results are
committed:

| Quantity | Method A | Method B | Agreement |
|---|---|---|---|
| Noise figure | ngspice's own two-port NF from the `sp` analysis (`donoise`) | `.noise` input-referred density with noiseless `Rs`/`RL` and an analytic source term | **≤ 0.0001 dB at all 15 cells at 27 °C** — the only temperature at which the two are the same quantity, since `sp`'s NF references the *analysis* temperature while the analytic one is pinned at a stated `T0`. Away from 27 °C they differ by an exact, predictable re-referencing (≤ 1.00 dB at −40 °C, ≤ 0.57 dB at 125 °C); `nf290` is the number quoted in the table above |
| Gain | \|S21\|² from the `sp` analysis | transducer gain `db(2·v_out)` from a separate `ac` analysis in an electrically isolated second DUT copy | **0.0000 dB at all 45 cells** (`gain_ac_minus_s21_db`, at the full recorded precision) |
| IIP3 | ngspice `fft`, rectangular window, no zero padding | direct coherent DFT projection over the same integer-cycle window | **≤ 0.017 dB** over all 93 points (`iip3_dbm_dft_crosscheck`) |
| IM3 3:1 slope | 1 mV and 2 mV drive at **every** cell | 5-level, 24 dB drive sweep at the nominal cell | slope in **[2.981, 3.019]** across all 45 cells (ideal cubic = 3.000) — the extrapolation's assumption holds everywhere it is used |
| Noise-floor sanity | IM5 bins measured as a floor sentinel | IM3/IM5 margin committed per point (`im3_over_im5_db`) | IM3 sits **≥ 19.1 dB** above the IM5 sentinel at all 93 points, and **≥ 25 dB at 91 of them**. The two exceptions are the highest-bias cells, where part of the IM5 amplitude is a *genuine* 5th-order product rather than numerical floor — so the ratio understates the real margin there, and the FFT/DFT cross-check still agrees to 0.016 dB at those points |
| ngspice `temp=` assumption | standalone probe deck, [`tb_resistor_noise_temp_probe.spice`](../sim/lna-characterization/testbench/tb_resistor_noise_temp_probe.spice) | — | disproved the precedent bench's assumption; see [#25](https://github.com/2AMLogic/sg13g2-lna/issues/25) |

The committed CSVs are also re-derivable from the committed raw logs alone,
with no ngspice run and no PDK install — see
[`../sim/lna-characterization/README.md`](../sim/lna-characterization/README.md)
§"Regenerating".

## Limitations

Restated here so that no number above can be quoted without them. The full
list is in
[`../sim/lna-characterization/README.md`](../sim/lna-characterization/README.md)
§"Model limitations"; the load-bearing ones are:

1. **Ideal passives.** `Le = 1 nH` / `Lc = 5 nH` are infinite-Q, zero-loss,
   no-substrate, no-self-resonance SPICE `L` elements, because no PDK
   inductor model exists to use instead (issue #5 / klayout-tools#1519, open).
   A real 5 nH at 2.44 GHz with Q ≈ 10 carries ~7.7 Ω of series loss. **Gain,
   NF, S11 and S22 above are therefore all optimistic**, and stability is
   modelled in its least-damped, most numerically degenerate configuration.
   The capacitors and bias resistors are likewise ideal, not `cap_cmim`/PDK
   resistor models.
2. **`sf`/`fs` are not real corners** in this PDK, so the DRAFT S11/S22 rows'
   own named binding corner is not covered (above).
3. **No layout, no parasitic extraction, no pad/package model.** Schematic
   netlist only.
4. **No passive-corner or mismatch/Monte-Carlo axis** (`cornerCAP.lib`,
   `*_mismatch`/`*_stat` sections) — a separate campaign.
5. **IIP3 is an extrapolation**, valid only in the 3:1 IM3 region, measured
   with a deliberately wide 7.63 MHz tone spacing so every product lands on
   an exact FFT bin centre. Its stated limits — numerical noise floor,
   harmonic-vs-intermod separation, settling-time assumption — are enumerated
   in the experiment README and must travel with the number.

## What has to happen before any of this becomes a spec claim

1. **#26** — replace the placeholder bias divider; re-run the campaign (the
   runner needs no changes).
2. **#27** — design the input/output matching networks, and re-check
   stability at every PVT cell before declaring them final. Blocked in
   practice on the inductor-model gap (#5 / klayout-tools#1519).
3. **#25** — reconcile the precedent NF bench's source-reference-temperature
   claim, so this repo has one consistent NF definition across experiments.
4. **#19** — ratify `spec/target-spec.md` — **now resolved**: ratified via
   decision record
   [0002](../spec/decision-records/0002-target-spec-first-ratification.md)
   (PR #32, this record as the evidence base). The rows it marks RATIFIED
   are now a bar, not a hypothesis; the IIP3 numeric target and the former
   stretch columns remain DRAFT pending their own record.
