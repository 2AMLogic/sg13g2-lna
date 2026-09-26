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
   as-committed pre-#27 design (DR-0003 bias core landed, **no matching
   network**, ideal passives), so the comparisons below remain
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
4. **Every number below is from record `20260926-122301-088c734` and only
   that record.** `sim/lna-characterization/` holds three records describing
   three different circuits (placeholder divider → mirror reference →
   DR-0003 flat-reference core); mixing them is how a statement about a
   design that no longer exists survives. See
   [`../sim/lna-characterization/README.md`](../sim/lna-characterization/README.md)
   §"Which DUT each record describes".

## The campaign this report reads

| | |
|---|---|
| Experiment | [`../sim/lna-characterization/`](../sim/lna-characterization/README.md) (issue [#18](https://github.com/2AMLogic/sg13g2-lna/issues/18)) |
| Record id | **`20260926-122301-088c734`** (issue [#49](https://github.com/2AMLogic/sg13g2-lna/issues/49) re-baseline; supersedes the historical `20260918-210908-4293920` and `20260921-131646-d6da30a`, which this report no longer reads) |
| DUT | `design/netlist/lna.spice` (xschem netlist of `design/lna.sch`), sha256 `23f9445b01dbec99…` — the **DR-0003 flat-reference bias core** (issue #33 / PR #40, commit `e25df3b`), inlined verbatim into every deck |
| PDK | `ihp-sg13g2`, IHP-Open-PDK **v0.3.0** (pinned in [`../sim/pdk.json`](../sim/pdk.json)) |
| Simulator | ngspice-46, `.options gmin=1e-10` (not the 1e-12 default — the DR-0003 core will not converge at the coldest/lowest-rail cells without it; measured cost of the override is 7th-significant-figure, tabulated in the experiment README §"`gmin` and the DR-0003 core") |
| Device models | HBTs from `cornerHBT.lib` (`hbt_typ`/`hbt_bcs`/`hbt_wcs`), the core's `sg13_hv_pmos`/`sg13_hv_nmos` from `cornerMOShv.lib` (all five sections) with the PSP103.6 OSDI models preloaded |
| Port convention | **50 Ω at both ports**, applied by ngspice `sp`-analysis port sources (`portnum`/`z0 50`) — `spec/target-spec.md`'s own stated convention |
| PVT grid | **full**: {typ, bcs, wcs, sf, fs} × {−40, 27, 125} °C × {1.62, 1.80, 1.98} V = **45 cells**, both phases at every cell, **138 `ngspice -b` invocations**, **0 failed cells** |
| Raw evidence | per-point generated decks, raw ngspice logs, raw complex S-parameters and 140-frequency broadband stability tables, all committed under `../sim/lna-characterization/{netlist-snapshots,corners}/20260926-122301-088c734/` |
| Bench definitions | [`../sim/lna-characterization/README.md`](../sim/lna-characterization/README.md) — port impedances, the exact `sp`/`.noise`/`tran` analyses, the two NF reference temperatures, tone spacing and FFT parameters, and the stated limits of the IIP3 method |

**Corner-label caveat**: `cornerHBT.lib` ships **three** real HBT sections,
not five. `typ→hbt_typ`, `bcs→hbt_bcs`, `wcs→hbt_wcs`, and **`sf`/`fs` both
fall back to `hbt_typ`**. `cornerMOShv.lib` does ship all five, so since the
DR-0003 core landed the `sf`/`fs` cells are no longer bit-identical to
`typ` — but they differ only through the bias core's MOS devices
(≤ 0.05 % on `I_C1`, ≤ 0.0001 dB on `NFmin`) and still carry `typ`'s HBT
section, which is what sets the RF behaviour. So `spec/target-spec.md`'s
"fs/sf process corners (L/C mismatch)" binding corner for S11/S22 **is
still not exercised by this campaign**. It cannot be: the L/C it refers to
are ideal primitives here with no corner models to sweep. Read `wcs` as
this repo's `ss`-equivalent. Full reasoning:
[`../sim/README.md`](../sim/README.md) §"Corner-label convention".

## Results against the ratified target table

Worst/best are across all 45 PVT cells unless stated. Every figure is a cell
of `../sim/lna-characterization/records/20260926-122301-088c734-summary.csv`
(column named under the table), except the two broadband residues marked
"raw", which are counted from the 140-frequency
`corners/20260926-122301-088c734/*.stability.dat` tables because the summary
CSV's six-decimal columns round them away.

| Row | Ratified target | Former stretch (NOT ratified) | Nominal cell (typ/27 °C/1.80 V) | Worst of 45 cells | Best of 45 cells |
|---|---|---|---|---|---|
| **Gain (S21)** | > 15 dB across band | > 18 dB | **11.46 … 11.57 dB** | **10.27 dB** (wcs/125 °C/1.62 V) | **12.35 dB** (bcs/−40 °C/1.98 V) |
| **Noise figure (NF)**, `T0` = 290 K | < 1.5 dB across band | < 1.0 dB | **2.656 dB** | **3.776 dB** (wcs/125 °C/1.62 V) | **1.843 dB** (bcs/−40 °C/1.98 V) |
| **`NFmin`** (not a spec row; what a *lossless, ideal* noise match would give this circuit — a floor nothing passive goes below) | — | — | **2.382 dB** | **2.728 dB** (wcs/125 °C/1.62 V) | **2.075 dB** (bcs/−40 °C/1.98 V) |
| **Input match (S11)** | < −10 dB across band | < −15 dB | **−3.066 dB** | **−2.962 dB** (bcs/−40 °C/1.98 V) | −3.223 dB (wcs/125 °C/1.62 V) |
| **Output match (S22)** | < −10 dB across band | < −15 dB | **−0.0044 dB** | **−0.0033 dB** (bcs/−40 °C/1.98 V) | −0.0059 dB (wcs/125 °C/1.62 V) |
| **Stability (μ, binding)** | μ > 1, 10 MHz – 30 GHz, every cell | — (k > 1.5 dropped by DR-0002) | in-band **μ = 1.000353**; broadband **μ = 0.999997** | broadband **μ = 0.99999592** at 595.7 MHz (bcs/−40 °C/1.98 V); **45/45 cells dip below 1 out of band** | in-band **μ ≥ 1.000275 at every cell** — **0/45 in-band failures** |
| **Stability (k, context only)** | reported alongside μ | — | in-band **k = 3.825** | broadband **k = −3.530** at 50.1 MHz (bcs/125 °C/1.98 V) | in-band **k ≥ 3.390** at every cell |
| **Negative-resistance check** (raw tables) | max \|S11\|, max \|S22\| < 1 | — | \|S11\| 0.8136, \|S22\| 1.0000000 | max \|S22\| = **1.00000018** (+0.18 ppm, 188.4 MHz, bcs/125 °C/1.98 V), **45/45 cells above unity**; max \|S11\| = 0.8175 (< 1 everywhere) | — |
| **IIP3** (numeric target still DRAFT) | > 0 dBm (DRAFT) | > +5 dBm | **−1.417 dBm** | **−2.322 dBm** (wcs/−40 °C/1.62 V) | **+0.498 dBm** (bcs/125 °C/1.98 V) |
| **Supply** | 1.80 V ± 10 % | — | swept ±10 %: 1.62 / 1.80 / 1.98 V | — | — |
| **Power (P_dc)** | < 10 mW | < 5 mW | **8.486 mW** | **9.768 mW** (bcs/125 °C/1.98 V) — **0/45 cells over** | 7.187 mW (wcs/125 °C/1.62 V) |
| **`I_C1`** (DR-0001 mandate ≤ 4.5 mA) | ≤ 4.5 mA over corners | — | **3.940 mA** | **4.151 mA** (bcs/−40 °C/1.98 V) — **0/45 cells over** | 3.657 mA (wcs/125 °C/1.62 V) |

*Summary-CSV columns behind each row, in order*: `s21_db_min` /
`s21_db_max`; `nf290_db_worst`; `nfmin_sp_db_at_band_lo`; `s11_db_worst`;
`s22_db_worst`; `mu_inband_min` / `mu_broadband_min`; `k_inband_min` /
`k_broadband_min`; `s11_mag_broadband_max` / `s22_mag_broadband_max` (but
see the "raw" note above); `iip3_dbm_a2mv`; `pdc_w`; `ic1_a`. "Worst" for a
match or NF row means the numerically *least favourable* cell, which for
S11/S22 is the one closest to 0 dB.

**Distance from the target rows, stated plainly**: at the nominal cell,
gain is **3.54 dB short** of the target, NF is **1.16 dB over**, IIP3 is
**1.4 dB under** its still-DRAFT numeric target, S11 is **6.9 dB short**,
S22 is **10 dB short**, and μ — the binding stability metric — is above 1
in band at every cell but dips below it out of band at every cell. Power
and `I_C1` are **within** their bounds at every cell for the first time
(worst P_dc 9.768 mW against a 10 mW bar: 2.3 % of margin). These are
disclosed shortfalls of the as-committed design against rows DR-0002
ratifies — each ratified row's note in `spec/target-spec.md` records them
with their root cause — not conformance verdicts, which await the #27
matching re-run.

**The one that is not a matching-network problem.** Gain and NF are
usually argued as "the absent input match, recoverable by #27". On this
DUT that argument fails arithmetically for both, and the check is one line
each:

- **NF**: a passive match cannot take NF below `NFmin`. `NFmin` ≥
  **2.075 dB** at every one of the 45 cells, against a ratified
  **< 1.5 dB**. Short by **0.575 dB at the best cell**, 0.882 dB at
  nominal, 1.228 dB at the worst — under a *lossless* match and
  infinite-Q passives, i.e. in the most optimistic case that exists.
- **Gain**: the conjugate-input-match available-gain basis is
  \|S21\|²/(1−\|S11\|²) = 11.46 dB + **2.96 dB** = **14.42 dB** at nominal,
  against a ratified **> 15 dB** — short by 0.58 dB before any
  matching-network insertion loss.

Neither is a verdict on the ratified rows (which are untouched, per
`CLAUDE.md`). Both say the same thing: at the DR-0003 operating point these
two rows implicate the bias point and device sizing, not only #27.

## The three findings that matter

### 1. The bias problem is solved — and that is what makes the rest of the table meaningful

This finding used to read "the bias network, not the RF design, dominates
every PVT number": on record `20260918-210908-4293920`, `I_C1` spanned
0.0249 mA to 14.70 mA (a ~590× spread) because `Q1`'s base bias was a bare
`V_BE`-referenced resistive divider. That was filed as
[#26](https://github.com/2AMLogic/sg13g2-lna/issues/26) and **closed on
2026-09-21** by the DR-0003 flat-reference core (issue #33 / PR #40).

Measured against the landed core (record `20260926-122301-088c734`):

- `I_C1` spans **3.657 – 4.151 mA** — a **1.13× spread** around a 3.940 mA
  nominal. **0 of 45 cells** exceed DR-0001's `I_C1 ≤ 4.5 mA` mandate
  (was 21 of 45).
- `P_dc` spans **7.187 – 9.768 mW**. **0 of 45 cells** exceed the ratified
  `< 10 mW` row (was 20 of 45, worst 29.64 mW). The worst cell keeps only
  **0.23 mW / 2.3 %** of margin, which is disclosed rather than celebrated:
  it is not margin a layout or a matching network can be assumed to
  survive.
- Gain now swings **2.08 dB** and `nf290` **1.93 dB** across the whole
  corner box (was ~35 dB and ~9 dB). There is no longer a cell where the
  amplifier is switched off.
- IIP3 swings **2.82 dB** (−2.32 … +0.50 dBm), not 31.7 dB. It is finally a
  linearity result rather than a bias artefact — and on that basis **2 of
  45 cells** clear the still-DRAFT `> 0 dBm` bar while the nominal cell
  (−1.417 dBm) does not.

Every other number in this table is therefore now characterizing what it
appears to characterize. What that bought was clarity, not conformance: it
is precisely because the bias spread is gone that findings 2 and 3 below
can be read as statements about the RF design.

### 2. There is no matching network, and stability says one cannot simply be bolted on

`Cin`/`Cout` are 100 pF DC blocks (≈ 0.65 Ω at 2.44 GHz), there is no base
inductor, and `Lc` presents an essentially **lossless reactive** collector
load — so |Γ| sits on the edge of the Smith chart at both ports by
construction (`S22 = −0.004 dB` is a lossless reflection, not a design
error).

The stability result is what makes this a *gate* rather than a to-do, per
`CLAUDE.md` ("k-factor / stability circles across the band, at PVT corners,
**before any matching is declared final**"):

- **The in-band μ < 1 failure is retired.** **0 of 45 cells** now have
  in-band μ < 1 (worst **1.000275**, bcs/125 °C/1.98 V) — it was 40 of 45 on
  record `20260918-210908-4293920`. In-band k is positive at every cell too
  (min **3.390**, was 0.346).
- **The broadband μ < 1 failure is not.** **45 of 45 cells** still dip below
  1 somewhere in the 10 MHz – 30 GHz sweep (12× the upper band edge; the
  ratified row binds the whole sweep), minimum **0.99999592** (−4.1 ppm) at
  595.7 MHz, bcs/−40 °C/1.98 V. The amplifier remains **conditionally**, not
  unconditionally, stable by the binding metric — the failure has simply
  moved entirely out of band. A matching network is still not free to
  present an arbitrary passive termination, and every candidate network must
  be re-checked against this same bench.
- **k still reaches −3.530** out of band, and must still be read with μ
  beside it: with |S11| = 0.7026, |S22| = 0.99949 and |S12| = **−95.54 dB**,
  Rollett's numerator (4.84e−4) and denominator (1.27e−4) are both small
  quantities assembled from fourth-decimal-place differences. It is a real
  result and a badly conditioned one; the in-band k = 3.82 is *not* the
  reassuring margin it looks like. μ has no such problem and is the number
  to reason from. Re-derived against this DUT in
  [`../sim/lna-characterization/README.md`](../sim/lna-characterization/README.md)
  §"Why k is ill-conditioned on this circuit".
- **The |S22| > 1 residue persists, ~20× smaller, and the "it's gone"
  reading is a rounding artefact.** Counted from the raw 140-frequency
  `*.stability.dat` tables (not the summary CSV, whose six-decimal column
  rounds it to `1.000000`): **45 of 45 cells exceed unity, maximum
  1.00000018 (+0.18 ppm)** at 188.4 MHz, bcs/125 °C/1.98 V, with the input
  at its 50 Ω reference. Re-counted the same way, record
  `20260918-210908-4293920` was 31 of 45 at +3.71 ppm. At 0.18 ppm this is
  indistinguishable from the numerical resolution of a lossless port — so
  the disposition is unchanged: flagged for re-checking once a *lossy*
  inductor model exists, not dismissed.
- **max |S11| stays below 1 everywhere** (0.8175 at 10 MHz,
  bcs/125 °C/1.62 V).

Filed as [#27](https://github.com/2AMLogic/sg13g2-lna/issues/27) — still
open, still blocked in practice on the inductor-model gap.

### 3. The "sub-dB NF" thesis does not survive the DR-0003 operating point

This finding is **reversed** by the re-baseline, and that reversal is the
single most consequential result in this report.

> **⚠ Amended 2026-09-26 by issue #52 — read
> [§"Amendment (issue #52)"](#amendment-issue-52-the-nfmin-numbers-below-are-referenced-to-the-analysis-temperature-not-to-t0--290-k)
> at the end of this file before quoting the `NFmin` table below.** The
> qualitative conclusion of this section stands (0 of 45 cells clear the
> row, either way), but the three `NFmin` values in it are referenced to
> each cell's **analysis temperature**, not to the RATIFIED T0 = 290 K, so
> the *margins* quoted are wrong in both directions.

The repo's own thesis claim ("sub-dB noise figures at low GHz are textbook
SiGe territory", `spec/target-spec.md` source (3)) is testable against a
number this campaign produces directly: `NFmin`, the noise figure the
circuit would deliver under a *lossless, ideal* source-impedance match. No
passive matching network can take NF **below** `NFmin`; a real, finite-Q
one lands above it. `NFmin` is therefore a hard floor, and on this DUT it
is:

| | `NFmin` @ 2.4 GHz | vs the ratified `NF < 1.5 dB` |
|---|---|---|
| best of 45 cells (bcs/−40 °C/1.98 V) | **2.0749 dB** | **+0.575 dB over** |
| nominal cell (typ/27 °C/1.80 V) | **2.3817 dB** | **+0.882 dB over** |
| worst of 45 cells (wcs/125 °C/1.62 V) | **2.7275 dB** | **+1.228 dB over** |
| cells with `NFmin` < 1.5 dB | **0 of 45** | — |

**So the ratified NF row is not reachable by matching at this operating
point, let alone the unratified sub-dB stretch.** The argument that
licensed the earlier framing — "~1.1 dB of the present NF is the absent
noise match", resting on `NFmin` = 0.600 dB best / 0.751 dB nominal — was
measured on record `20260918-210908-4293920`, a **different circuit** (the
placeholder resistive divider), and does not transfer to the DR-0003 core.

Two corroborating numbers from the same record:

- The nominal `nf290 − NFmin` gap is now only **0.274 dB** (2.6559 −
  2.3817), against ~1.1 dB before. The DR-0003 core already presents the
  HBT with a source impedance close to its own noise optimum, so a
  matching network has very little left to recover — the opposite of the
  situation the old finding described.
- `nf290` itself is **2.6559 dB** at nominal and **3.7759 dB** at the worst
  cell, against the ratified 1.5 dB bar.

**What this does and does not mean.** It does **not** relax anything: the
ratified `NF < 1.5 dB` row is untouched here, per `CLAUDE.md` ("agents do
not relax the ratified spec to make results pass"). It does **not** say the
SiGe device cannot do sub-dB — that is a claim about the *device*, and this
is a measurement of *this circuit at this bias point with this degeneration
and these device sizes*. What it does say is that the NF row can no longer
be argued as #27's problem: closing it requires revisiting the bias point
and/or device sizing, which is a design decision needing its own decision
record, not a matching-network task. This is a complete, successful
measurement outcome, not a failure to deliver — and it **reshapes** #27's
scope rather than blocking it.

## Cross-checks performed (why these numbers are believable)

Each quantity is produced twice, by independent methods, and both results are
committed:

| Quantity | Method A | Method B | Agreement |
|---|---|---|---|
| Noise figure | ngspice's own two-port NF from the `sp` analysis (`donoise`) | `.noise` input-referred density with noiseless `Rs`/`RL` and an analytic source term | **≤ 0.0001 dB at all 15 cells at 27 °C** — the only temperature at which the two are the same quantity, since `sp`'s NF references the *analysis* temperature while the analytic one is pinned at a stated `T0`. Away from 27 °C they differ by an exact, predictable re-referencing (≤ 0.50 dB at −40 °C, ≤ 0.66 dB at 125 °C); `nf290` is the number quoted in the table above |
| Gain | \|S21\|² from the `sp` analysis | transducer gain `db(2·v_out)` from a separate `ac` analysis in an electrically isolated second DUT copy | **0.0000 dB at all 45 cells** (`gain_ac_minus_s21_db`, at the full recorded precision) |
| IIP3 | ngspice `fft`, rectangular window, no zero padding | direct coherent DFT projection over the same integer-cycle window | **≤ 0.0049 dB** over all 93 points (`iip3_dbm_dft_crosscheck`) |
| IM3 3:1 slope | 1 mV and 2 mV drive at **every** cell | 5-level, 24 dB drive sweep at the nominal cell | slope in **[2.988, 3.001]** across all 45 cells (ideal cubic = 3.000) — the extrapolation's assumption holds everywhere it is used |
| Noise-floor sanity | IM5 bins measured as a floor sentinel | IM3/IM5 margin committed per point (`im3_over_im5_db`) | IM3 sits **≥ 28.3 dB** above the IM5 sentinel at **all 93 points** — none below 25 dB, where the previous record had two marginal points |
| CSV ↔ raw logs | the committed `-summary`/`-sparam`/`-iip3` CSVs | re-derived by `parse_lna_sweep.py` from the committed raw logs alone, no ngspice and no PDK | **byte-identical** on all three files (the §"Regenerating" procedure below) |
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
2. **`sf`/`fs` are not real HBT corners** in this PDK, so the S11/S22 rows'
   own named binding corner is not covered (above) — the MOS side of those
   labels is real since the DR-0003 core, but moves `I_C1` by ≤ 0.05 %.
3. **No layout, no parasitic extraction, no pad/package model.** Schematic
   netlist only.
4. **No passive-corner or mismatch/Monte-Carlo axis** (`cornerCAP.lib`,
   `*_mismatch`/`*_stat` sections) — a separate campaign.
5. **IIP3 is an extrapolation**, valid only in the 3:1 IM3 region, measured
   with a deliberately wide 7.63 MHz tone spacing so every product lands on
   an exact FFT bin centre. Its stated limits — numerical noise floor,
   harmonic-vs-intermod separation, settling-time assumption — are enumerated
   in the experiment README and must travel with the number.
6. **One solver override, disclosed**: `.options gmin=1e-10`, 100× ngspice's
   own default, without which the DR-0003 core loses its operating point at
   four of the 45 cells. Its measured effect on every recorded quantity is
   7th-significant-figure or smaller (largest relative move anywhere 4.5e−5,
   on the ill-conditioned Rollett k), tabulated in the experiment README
   §"`gmin` and the DR-0003 core".

## What has to happen before any of this becomes a spec claim

1. **#26** — replace the placeholder bias divider — **closed 2026-09-21**
   by the DR-0003 flat-reference core (issue #33 / PR #40) and re-measured
   here (finding 1). The runner did need two changes to reach the swapped
   core — the `cornerMOShv.lib`/OSDI model preamble and the `gmin`
   override above — both disclosed in the deck headers rather than made
   silently.
2. **#27** — design the input/output matching networks, and re-check
   stability at every PVT cell before declaring them final. Blocked in
   practice on the inductor-model gap (#5 / klayout-tools#1519). **Rescoped
   by finding 3**: a matching network alone can no longer reach the
   ratified NF row at this operating point, so #27 is necessary but not
   sufficient, and the bias-point/device-sizing question it now raises
   needs a decision record of its own.
3. **#25** — reconcile the precedent NF bench's source-reference-temperature
   claim, so this repo has one consistent NF definition across experiments.
4. **#19** — ratify `spec/target-spec.md` — **now resolved**: ratified via
   decision record
   [0002](../spec/decision-records/0002-target-spec-first-ratification.md)
   (PR #32, this record as the evidence base). The rows it marks RATIFIED
   are now a bar, not a hypothesis; the IIP3 numeric target and the former
   stretch columns remain DRAFT pending their own record.

## Amendment (issue #52): the `NFmin` numbers below are referenced to the analysis temperature, not to T0 = 290 K

**Date**: 2026-09-26. **Source**: issue
[#52](https://github.com/2AMLogic/sg13g2-lna/issues/52) /
[`spec/decision-records/0004-achievable-gain-nf-power-envelope.md`](../spec/decision-records/0004-achievable-gain-nf-power-envelope.md)
§"Evidence — 3". **Nothing above is deleted or rewritten** — this amendment
is appended in the same spirit as the `sim/` append-only rule, so the
original text stays readable and the correction is explicit.

Two statements in this report need correcting, and one finding needs
withdrawing. All three are re-derivable from committed files with
`sim/lna-core-envelope/derive_committed_record_envelope.py` (no PDK, no
ngspice — it reads record `20260926-122301-088c734`'s own raw
`corners/<id>/*.inband.dat` complex-S tables).

### (a) `NFmin` — the reference temperature

ngspice's two-port `sp` noise figure — the `NF`/`NFmin` vectors, and
therefore this record's `nf_sp_db_*` / `nfmin_sp_db_*` columns — is
referenced to the **analysis temperature**, not to a fixed T0. Proof, from
this record's own data: re-referencing the *independently computed*
`.noise`-based `nf290` column (the Xb branch, noiseless `Rs`, analytic
290 K source term) to each cell's analysis temperature reproduces the
committed `sp`-analysis `nf` column (the Xa branch) to a worst error of
**9.2e-5 dB across all 45 cells**. No other convention satisfies that.

`spec/target-spec.md` RATIFIES the NF row at **T0 = 290 K**, so §3's table
is comparing a different quantity against the row. Re-referenced with the
same identity `sim/hbt-characterization/rederive_nf_fixed_t0.py` uses for
the issue-#25 correction (`F(T₀) − 1 = (F(Tₐ) − 1)·Tₐ/T₀`):

| | `NFmin` as printed in §3 | **`NFmin` at T0 = 290 K** | vs the ratified `NF < 1.5 dB` |
|---|---|---|---|
| best of 45 cells (bcs/−40 °C/1.98 V) | 2.0749 dB | **1.7389 dB** | **+0.239 dB over** (§3 said +0.575) |
| nominal cell (typ/27 °C/1.80 V) | 2.3817 dB | **2.4454 dB** | **+0.945 dB over** (§3 said +0.882) |
| worst of 45 cells (wcs/125 °C/1.62 V) | 2.7275 dB | **3.4239 dB** | **+1.924 dB over** (§3 said +1.228) |
| cells with `NFmin` < 1.5 dB | 0 of 45 | **0 of 45** | unchanged |

§3's conclusion — the ratified NF row is not reachable by matching at this
operating point — is **unaffected**. Its *margins* are: better than stated
at the cold cells, considerably worse at the hot ones. Per-cell values:
`sim/lna-core-envelope/records/20260926-122301-088c734-derived-envelope.csv`.

### (b) The gain shortfall — the metric assumed no output network

§"Results against the ratified target table" and issue #27 both quote an
"available-gain basis" of 14.42 dB at nominal (11.4604 + 2.9556), 0.58 dB
short of the ratified > 15 dB row. That arithmetic is correct and
re-derives exactly, but it applies an ideal conjugate match at the **input**
and leaves the **output terminated in the bare 50 Ω port** — which the
ratified S22 row already forbids a finished design from doing. The
committed core's output impedance, `Z = 50·(1+S22)/(1−S22)` from this
record's own complex `S22` at the nominal cell and the band-bottom sweep
point (2.4 GHz), is **0.0427 + j76.50 Ω** — parallel-equivalent
**137 kΩ ∥ j76.5 Ω**, a near-lossless current source that a 50 Ω
termination almost entirely discards. (Band mid 0.0457 + j77.92 Ω, band top
0.0489 + j79.34 Ω; nothing below turns on which in-band point is quoted.)

Charging only the output tank's own loss at a finite inductor Q (arithmetic
on the committed S-parameters, not a passive model — the PDK has none):

| output-tank Q | available gain, worst of 45 cells | nominal | cells > 15 dB |
|---|---|---|---|
| input match only (output at 50 Ω) | 13.07 dB | 14.42 dB | 3/45 |
| Q = 3 | 15.19 dB | 16.54 dB | **45/45** |
| Q = 10 | 20.40 dB | 21.75 dB | 45/45 |
| Q = ∞ (the committed ideal model) | 41.34 dB | 43.95 dB | 45/45 |

So "the gain row is unreachable even under an ideal lossless match" is
**withdrawn**. What the evidence supports is narrower: the gain row cannot
be met by an *input* match alone, and how much of the 5.4 dB of headroom at
Q = 10 survives the matching networks' own insertion loss is #27's budget.

### (c) What the campaign could not answer, and where the answer now lives

§3 says closing the NF row "requires revisiting the bias point and/or
device sizing, which is a design decision needing its own decision record".
That work is done as evidence: `sim/lna-core-envelope/` (record
`20260926-180931-90b07a0`) re-runs this exact bench over 15 DUT variants ×
the same 45 cells, with the committed netlist as a control that reproduces
this record to `0.000e+00` relative difference. Headline: emitter area at
**constant current** (not more current) is the cheapest NF lever — 80 unit
emitters instead of 8 buys 1.55 dB of `NFmin` while *lowering* worst-cell
P_dc by 1.36 mW — and the NF row then holds at all 30 cold/nominal cells
and at **none** of the 15 hot ones, on every variant tried. The trade that
leaves is DR-0004's subject, and the decision is the operator's.
