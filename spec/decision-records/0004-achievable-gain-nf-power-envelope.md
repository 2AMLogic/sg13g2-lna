# 0004: The achievable (gain, NF, P_dc) envelope on `npn13G2`, and what the RATIFIED NF row costs

- **Status**: proposed
- **Date**: 2026-09-26
- **Decided by**: Builder (Loom), issue #52 — **drafted for the operator to
  rule on; this record decides nothing by itself**
- **Issue**: [#52](https://github.com/2AMLogic/sg13g2-lna/issues/52)

> **This record does not relax, edit or reinterpret any RATIFIED row of
> [`spec/target-spec.md`](../target-spec.md).** Per `CLAUDE.md` an agent does
> not move a ratified row to make results pass, and per the TEMPLATE's status
> vocabulary a `proposed` record ratifies nothing on its own. Every RATIFIED
> row is an **input** here. What this record does is state, from measurement,
> which of those rows can hold simultaneously and at which PVT cells, what
> each one costs the others, and what the options are — so that the operator
> can decide, on evidence, whether anything needs to change and what.

## Context

`spec/target-spec.md`'s Gain (S21) > 15 dB and NF < 1.5 dB rows have been
carrying disclosed failing-spec notes since the DR-0003 re-baseline (record
`20260926-122301-088c734`, issue #49 / PR #51). Issue #52 was opened because
those notes had nowhere to go: #27 owns the matching networks and its own
body records that adding them cannot close either row, so the question *"is
this reachable at all, and at what price"* had no home.

Two of the premises that framing rested on turn out not to survive
re-derivation, and one does. All three are established below from committed
evidence, with the record id and column behind every number.

## Decision

**This record proposes nothing be changed today.** It asks the operator to
choose among four options in "Options for the operator" below, and it states
the one thing the evidence says without ambiguity:

> **On `npn13G2` inside the RATIFIED P_dc < 10 mW row, the Gain > 15 dB row
> is reachable at 45 of 45 cells and the NF < 1.5 dB row is reachable at the
> 30 cold and nominal cells but at NONE of the 15 hot (125 °C) ones.** The
> residual binding constraint on the NF row is **temperature**: it is not
> power (the best NF variant is also the *lowest*-power one), not the
> matching network (`NFmin` is already the ideal-match floor), and not device
> sizing either — sizing is the one lever that does move it, by 1.55 dB, and
> it still leaves every hot cell short. Across 15 DUT variants × 45 PVT
> cells, the best noise figure measured at any 125 °C cell is
> **NFmin = 1.601 dB at T0 = 290 K** (`s_fixi_a80`, `bcs`/125 °C/1.98 V) —
> 0.10 dB over the row before any matching-network loss, any layout
> parasitic, or any real inductor.

Stated as the envelope issue #52 asks for, with the sizing attached:

| rows | holds? | at what geometry / bias |
|---|---|---|
| P_dc + Gain | **45/45 cells** | the committed `Nx=8`, `J_C` 3.97–4.50 mA/µm², `V_CE1` 0.575–1.063 V / `V_CE2` 0.885–1.077 V, with the output network the S22 row already requires at any inductor Q ≥ 3 (Evidence 2). Also 45/45 *unmatched* on a two-stage probe (`t_bal`, 10×4 + 10×2, `J_C` 0.50–0.63 mA/µm², 6.27–9.38 mW). |
| P_dc + Gain + NF | **30/45 cells** (all −40 °C and 27 °C) | `s_fixi_a80` — 80 unit emitters at the committed current, `J_C` 0.32–0.43 mA/µm², 5.29–8.41 mW. NFmin@290 0.796–1.286 dB cold/nominal. |
| P_dc + Gain + NF at 125 °C | **0/45, on every variant tried** | best hot-cell NFmin@290 anywhere in the campaign is 1.601 dB. |
| …+ the RATIFIED μ > 1 stability row | **only on `t_bal`**, and then NF holds at 15/45 | `t_bal` is the only one of 15 variants with 0 sub-unity μ points in 6300 swept frequencies; every single-stage variant, including the committed core, violates at 45/45 out of band. |

Three caveats that belong in the same breath as the table: the gain figure is
an *upper* bound that charges the output tank's own finite-Q loss but **not**
the matching networks' insertion loss (#27's budget); the 80-unit emitter
array's layout parasitics are entirely unmodelled; and the `J_C`/`V_CE`
ranges above are measured spans over the 45-cell box, not design targets.

The gain row's apparent shortfall, by contrast, is an artefact of the metric
used to state it, and this record **proposes** it be treated as withdrawn
(see Evidence — 2). That withdrawal is a `spec/` act, so it is Option A
below, not something this record performs.

## Evidence

All numbers below are reproducible from committed files with the stated
command. Two records carry them:

- **`sim/lna-characterization/records/20260926-122301-088c734`** — the
  committed campaign on `design/netlist/lna.spice` (sha256 `23f9445b…`),
  the DUT on `main`. Bench definitions in that experiment's README: 50 Ω
  both ports, ngspice `sp`, NF from a noiseless-`Rs`/`RL` `.noise` with the
  source term re-introduced analytically, `.options gmin=1e-10`, ideal
  passives.
- **`sim/lna-core-envelope/records/20260926-180931-90b07a0`** — new with
  this record: **the same bench**, character-for-character, over 15 DUT
  variants × the same 45-cell PVT grid (675 decks). Its control variant
  `s_ctrl_a8` is the unmodified committed netlist and reproduces the
  campaign record to a worst relative difference of **0.000e+00** across all
  45 cells on the six columns the parser asserts on (`s21_db_min`,
  `s11_db_worst`, `nfmin_sp_db_at_band_lo`, `nf290_db_worst`, `pdc_w`,
  `ic1_a`) — bit-identical, and the parser exits non-zero rather than
  writing a record if that drift ever exceeds 1e-6. Independently spot-
  checked on two further columns (`s22_db_worst`, `nf_sp_db_at_band_lo`,
  also 0.000e+00) and on the stability columns, where `mu_inband_min`,
  `mu_broadband_min` and `k_inband_min` agree to ≤ 4.9e-7 relative rather
  than exactly. That residue is display precision, not a different
  measurement: `sim/lna-characterization/parse_lna_sweep.py` formats those
  three to **6** decimals and `parse_core_envelope.py` to **8**, from the
  same raw sweep values. Every variant number therefore rests on a bench
  proven identical to the committed one.

### 1. The device-level corroboration is withdrawn — the two NF benches measure different things, and the device one points the wrong way

Issue #52's Evidence section cites the committed device campaign
(`sim/hbt-characterization/records/20260921-124900-d6da30a-summary.csv`,
column `noise_optimum_nf_db_corrected_fixed_t0`) for the claim that the
device's own noise optimum sits at `J_C ≈ 14 mA/µm²`, ~3.5× DR-0001's
operating density, and that reaching it costs more power than the P_dc row
allows. **That column is real, correctly computed, and re-derives exactly**
— at `Nx=8`, `scope=in_box`, `V_CE` = 1.0 V it reads 2.2018 dB at
`typ`/−40 °C (`noise_optimum_jc_ma_um2` = 13.81) and 1.5208 dB at
`typ`/125 °C (14.56), spanning 10.33–19.53 mA/µm² of optimum density across
the five process labels, against the committed core's measured 3.97–4.50
mA/µm², i.e. 2.3–4.9× (≈ 3.2–3.5× at `typ`). Nothing about the issue's
arithmetic is wrong. What is wrong is treating it as the *same quantity* as
the circuit bench's `NFmin`. It is **not comparable**, in three independent
ways — each read out of `sim/hbt-characterization/README.md`'s own bench
definitions, not inferred:

- **It is a fixed-50 Ω-source NF minimised over `J_C`** (that README, §"NF —
  50 Ω-referenced noise figure at 2.4 GHz": `Rs = Z0 = RL = 50 Ω`, `NF_dB =
  10·log10(inoise_spectrum²/(4·k·T0·Rs))`). `NFmin` is minimised over
  *source impedance* at fixed bias. These are different minimisations of
  different functions, and they move in **opposite directions with `J_C`** —
  a fixed 50 Ω source favours high `J_C` (it pulls the device's own `Z_opt`
  down toward 50 Ω), while `NFmin` keeps improving as `J_C` falls.
- **It is referenced to T0 = 300.15 K**, not the RATIFIED 290 K (same README;
  the record exists *because* of the issue-#25 source-temperature erratum,
  and its `_corrected_fixed_t0` suffix names the 300.15 K reference it
  corrects *to*).
- **It is a different DUT** — a bare common-emitter `npn13G2` through ideal
  bias tees (that README: "a *bare, unmatched* common-emitter stage"), with
  no `Le` degeneration, no cascode, no `Lc` tank and no bias core attached,
  and its gain column is an `S21 = 2·Vout/Vin` transducer gain rather than
  the `sp`-analysis S21 the circuit bench reports.

The opposition in the first bullet is now **measured, not argued**. From
`records/20260926-180931-90b07a0.csv`, holding `I_C` ≈ 3.3–4.0 mA fixed and
sweeping total emitter area (the `s_fixi_*` family, mirror width scaled
`≈4096u/(Nx·m)`):

| variant | emitter units | `J_C` (mA/µm²) | worst-cell NFmin@290 (dB) | worst-cell P_dc (mW) |
|---|---|---|---|---|
| `s_ctrl_a8` | 8 | 3.97–4.50 | 3.424 | 9.77 |
| `s_fixi_a20` | 20 | 1.52–1.77 | 2.519 | 9.02 |
| `s_fixi_a40` | 40 | 0.71–0.87 | 2.094 | 8.67 |
| `s_fixi_a80` | 80 | 0.32–0.43 | **1.870** | **8.41** |

Moving **away** from the device bench's 14 mA/µm² "optimum" by a factor of
~35 improves the circuit's NF by 1.55 dB *and* lowers its power. The
device-bench corroboration is therefore withdrawn; everything below rests on
the circuit benches alone, as issue #52's second acceptance criterion
permits.

To be precise about what is withdrawn and what is not: the device record is
**not** shown to be wrong, and it is not retracted as evidence for the
question it was built to answer (where a 50 Ω-driven bare HBT's NF bottoms
out in `J_C`, which is DR-0001's §1 subject). What is withdrawn is its use as
*corroboration of a circuit-level `NFmin` claim*, and with it the inference
that the RATIFIED NF row requires a current density the P_dc row cannot
afford. The measured direction is the opposite one.

> Reproduce: the device-bench numbers with
> `python3 -c "import csv; [print(r['corner_label'], r['temp_c'],
> r['noise_optimum_jc_ma_um2'], r['noise_optimum_nf_db_corrected_fixed_t0'])
> for r in csv.DictReader(open('sim/hbt-characterization/records/20260921-124900-d6da30a-summary.csv'))
> if r['nx']=='8' and r['scope']=='in_box' and float(r['vce_v'])==1.0]"`;
> the circuit-bench table with `sim/lna-core-envelope/run_core_envelope.sh`,
> then `records/20260926-180931-90b07a0-variant-summary.csv` columns
> `jc_lo`/`jc_hi`, `nfmin290_hi`, `pdc_hi`.

### 2. The gain row is not out of reach — the "14.42 dB" figure leaves the output terminated in 50 Ω

The available-gain basis quoted on #52 — `|S21|_dB − 10·log₁₀(1 − |S11|²)` =
11.4604 + 2.9556 = **14.416 dB** at the nominal cell — re-derives exactly
(verified against `20260926-122301-088c734-summary.csv`, columns
`s21_db_min` and `s11_db_worst`). Applied per-cell it clears 15 dB at
**3 of 45** cells, exactly as the issue's own `## Verified corrections`
entry states.

But that figure applies an ideal conjugate match at the **input** and leaves
the **output in the bare 50 Ω port**. It is a lower bound on a matched
design's gain, not an upper one — and `spec/target-spec.md`'s S22 row
requires an output network to exist, so the assumption is not one #27 is
free to make. The committed core's output impedance, derived as
`Z = 50·(1+S22)/(1−S22)` from the same record's committed complex `S22` at
`typ`/27 °C/1.80 V, is **0.0427 + j76.50 Ω at the band-bottom sweep point
(2.4 GHz)** — parallel-equivalent **137 kΩ ∥ j76.5 Ω**, i.e. a near-lossless
current source (0.0457 + j77.92 Ω at band mid, 0.0489 + j79.34 Ω at band
top; the conclusion does not turn on which in-band point is quoted). A 50 Ω
termination throws away essentially all of its available power.

Charging the output tank's own loss at a realistic inductor Q — arithmetic
on the committed complex S-parameters, embedding a shunt `Rp = Q·ωLc` at
port 2, **not** a new simulation and **not** an inductor model
(`sim/lna-core-envelope/derive_committed_record_envelope.py`):

| output-tank Q | available gain, worst of 45 cells | nominal cell | cells > 15 dB |
|---|---|---|---|
| input match only (output at 50 Ω) | 13.07 dB | 14.42 dB | **3/45** |
| Q = 3 | 15.19 dB | 16.54 dB | **45/45** |
| Q = 5 | 17.40 dB | 18.75 dB | 45/45 |
| Q = 10 | 20.40 dB | 21.75 dB | 45/45 |
| Q = 20 | 23.37 dB | 24.73 dB | 45/45 |
| Q = ∞ (ideal, the committed model) | 41.34 dB | 43.95 dB | 45/45 |

Even at an implausibly poor Q = 3, the committed core clears the 15 dB row at
every one of the 45 cells with 0.19 dB to spare, and at a routine Q = 10 it
does so with **5.4 dB** of headroom over the worst cell. What that headroom
must still pay for is the matching networks' *own* insertion loss, which is
#27's budget and is deliberately not spent here.

**Numerical honesty about that table.** The figure is the *unilateral*
maximum gain `|S21|²/((1−|S11|²)(1−|S22|²))`, exact only as \|S12\| → 0.
Cross-checked against the exact Rollett MAG `|S21/S12|·(k − √(k²−1))` on the
same S-parameters, the two agree to **≤ 0.01 dB at every finite Q** — the
unilateral figure of merit U ≤ 7e-4 there — but differ by **~0.5 dB at
Q = ∞** (U = 0.090, because 1 − \|S22\|² collapses to ~1e-3 against a
lossless tank). Every load-bearing row above is a finite-Q row; the Q = ∞
row is an illustration with no physical referent and should not be quoted.

**So the "Gain row unreachable even under an ideal lossless match" finding
does not hold, and this record proposes it be treated as withdrawn.** What
the evidence supports instead is narrower and still worth recording: *the
gain row cannot be met by an input match alone; meeting it requires the
output network that the S22 row already requires, and how much of the
headroom survives is a function of inductor Q — which this PDK cannot model
at all (issue #5, upstream `2AMLogic/klayout-tools#1519`).*

> Reproduce: `sim/lna-core-envelope/derive_committed_record_envelope.py`
> (no PDK, no ngspice — it reads the committed record's own raw
> `corners/<id>/*.inband.dat` complex-S tables).

### 3. The NF row's own number was being compared against the wrong reference temperature

`spec/target-spec.md` RATIFIES the NF row at **T0 = 290 K**. The column the
Gain/NF disclosure notes quote for the noise floor —
`nfmin_sp_db_at_band_lo`, ngspice's own two-port `sp` `NFmin` — is
referenced to the **analysis temperature**, not to any fixed T0.

This is proven, not assumed. The committed record carries an *independently
computed* `.noise`-based `nf290` column (the Xb branch, noiseless `Rs`,
analytic 290 K source term). Re-referencing that column to each cell's
analysis temperature with the standard identity
`F(T₀) − 1 = (F(Tₐ) − 1)·Tₐ/T₀` — the same identity
`sim/hbt-characterization/rederive_nf_fixed_t0.py` uses for the issue-#25
correction — reproduces the committed `sp`-analysis `nf_sp_db_at_band_lo`
column (the Xa branch, a different analysis on a different DUT copy) to a
worst error of **9.2e-5 dB across all 45 cells**. No other reference
convention satisfies that identity.

The committed bench's own testbench template says as much in a comment —
`sim/lna-characterization/testbench/tb_lna_sparam.spice.tmpl`: *"NF_30015:
same quantity referenced to 300.15 K, for continuity with
sim/hbt-characterization/'s earlier records and with ngspice's own `sp` NF
(which references the analysis temperature)"*. So the convention was known
when the bench was written; what went wrong is that the **summary CSV's
`nfmin_sp_db_*` column was then quoted against a T0 = 290 K ratified row**,
in that record's report and in two `spec/target-spec.md` disclosure notes,
without applying the re-reference. This is a reading error downstream of a
correctly documented bench, not a bench defect.

Applying the same re-reference to `NFmin` **changes the numbers and moves
the binding cell**:

| | committed `nfmin_sp` (analysis-T referenced) | re-referenced to the RATIFIED T0 = 290 K |
|---|---|---|
| best cell | 2.0749 dB (`bcs`/−40 °C/1.98 V) | **1.7389 dB** (same cell) |
| nominal cell | 2.3817 dB | **2.4454 dB** |
| worst cell | 2.7275 dB (`wcs`/125 °C/1.62 V) | **3.4239 dB** (same cell) |
| cells under the 1.5 dB row | 0/45 | **0/45** |

The conclusion survives — 0 of 45 cells clear the row either way — but the
margin at the best cell is **0.24 dB, not 0.575 dB**, and the hot-corner
shortfall is **1.92 dB, not 1.23 dB**. Both the Gain and NF rows' disclosure
notes in `spec/target-spec.md` currently quote the un-re-referenced numbers.
Correcting them is a `spec/` edit and therefore the operator's act, not this
record's; it is listed as Option A below.

> Reproduce: `sim/lna-core-envelope/derive_committed_record_envelope.py`,
> output section 1 and 2; per-cell values in
> `sim/lna-core-envelope/records/20260926-122301-088c734-derived-envelope.csv`.

### 4. The achievable envelope, measured across the full 45-cell box

15 variants × 45 cells, counted against the RATIFIED rows
(`records/20260926-180931-90b07a0.csv`; the gain column used is the Q = 10
available gain from Evidence — 2, since the alternative assumes no output
network exists):

| variant | geometry | P_dc range (mW) | P_dc < 10 mW | G_A@Q=10 > 15 dB | \|S21\| > 15 dB *unmatched* | NFmin@290 < 1.5 dB | μ ≥ 1, 10 MHz–30 GHz |
|---|---|---|---|---|---|---|---|
| `s_ctrl_a8` (committed) | 8×1 | 7.19–9.77 | 45/45 | 45/45 | 0/45 | 0/45 | 0/45 |
| `s_fixj_a10` | 10×1, committed mirror | 8.48–11.80 | 17/45 | 45/45 | 0/45 | 0/45 | 0/45 |
| `s_fixi_a40` | 10×4 | 5.92–8.67 | 45/45 | 45/45 | 0/45 | 27/45 | 0/45 |
| `s_fixi_a80` | 10×8 | 5.29–8.41 | 45/45 | 45/45 | 0/45 | **30/45** | 0/45 |
| `t_equal` | 8×1 + 8×1 | 7.27–9.80 | 45/45 | 45/45 | 45/45 | 0/45 | 0/45 |
| `t_nfw` | 10×4 + 8×1 | 7.38–10.98 | 32/45 | 45/45 | 45/45 | 18/45 | 42/45 |
| `t_bal` | 10×4 + 10×2 | 6.27–9.38 | **45/45** | **45/45** | **45/45** | 15/45 | **45/45** |
| `t_lownf` | 10×8 + 10×2 | 5.59–9.14 | 45/45 | 45/45 | 45/45 | 27/45 | 18/45 |
| `t_full` | 8×1 + 8×1, committed mirror | 12.79–17.92 | 0/45 | 45/45 | 45/45 | 0/45 | 0/45 |

**The μ column is counted from the unrounded sweep points, and that matters.**
On this topology \|S12\| ≈ −95 dB makes μ ≈ 1/\|S22\|, and with an ideal
infinite-Q `Lc` driving \|S22\| → 1, μ sits within parts per *billion* of 1
over most of the out-of-band sweep: **115 of the 675 points** in this record
have a broadband μ minimum that rounds to `1.00000000` at 8 decimals. Taken
from that rounded column, `t_equal` would read 7/45 and `t_nfw` 45/45; taken
from the raw per-frequency counts (`n_broadband_pts_mu_lt_1`), they are
**0/45 and 42/45**. `t_bal`'s pass is the one that survives the stricter
count intact — **0 sub-unity points out of 6300** swept frequencies. This is
the same precision trap `spec/target-spec.md`'s S22 row already records for
`s22_mag_broadband_max` on this same bench ("count from the raw tables"), met
a second time on a different column; the parser now derives every μ verdict
from raw points so the next reader cannot inherit it.

The committed record is **not** affected by it and is corroborated here: its
own `n_broadband_pts_mu_lt_1` column says 45 of 45 cells dip below 1 over
2625 of 6300 swept points, which the control variant reproduces exactly, and
at 8 decimals the worst cell resolves to **0.99999592 at 595.66 MHz,
`bcs`/−40 °C/1.98 V** — the same cell and frequency
`spec/target-spec.md`'s stability row names. (Its own 6-decimal
`mu_broadband_min` column ties three cells at `0.999996`; the extra two
decimals break the tie in favour of the row's stated cell.) The pre-existing
out-of-band stability failure this record inherits is therefore exactly as
`spec/target-spec.md` describes it, and nothing in this campaign makes it
worse — every single-stage variant lands in the same 45/45 condition, and
the two-stage probes are the only things that move it, in both directions.

**No variant clears all three rows at all 45 cells, and on the NF row the
obstruction is always the same 15 cells.** Every one of the 15 variants fails
NF < 1.5 dB at **all 15 of its 125 °C cells**, and the passing cells are
filled strictly coldest-first: `s_fixi_a80`'s 30 are exactly the 15 −40 °C
plus 15 27 °C cells, `s_fixi_a40`'s 27 are 15 + 12, `t_bal`'s 15 are the
−40 °C cells alone (`nfmin290_db_worst` per cell, grouped by `temp_c`).
Decomposed by temperature (worst-cell NFmin@290):

| variant | −40 °C | 27 °C | **125 °C** |
|---|---|---|---|
| `s_ctrl_a8` | 1.739–2.222 | 2.192–2.718 | 2.849–3.424 |
| `s_fixi_a40` | 0.960–1.155 | 1.290–1.522 | 1.805–2.094 |
| `s_fixi_a80` | **0.796–0.931** | **1.105–1.286** | **1.601–1.870** |
| `t_bal` | 1.141–1.335 | 1.549–1.792 | 2.199–2.543 |
| `t_lownf` | 0.955–1.096 | 1.330–1.538 | 1.943–2.304 |

So, stated as an envelope:

- **P_dc < 10 mW and Gain > 15 dB hold together at 45/45 cells**, on more
  than one variant, and `t_bal` does it **with no matching network at all**
  (\|S21\| ≥ 18.60 dB at every cell at 6.27–9.38 mW) *and* holds μ ≥ 1 across
  the whole 10 MHz–30 GHz sweep at 45/45 — retiring the out-of-band stability
  failure every single-stage variant has (the committed core's minimum is
  μ = 0.99999592, 45/45 cells below 1).
- **Adding NF < 1.5 dB to that set holds at the 30 cold and nominal cells
  and fails at all 15 hot cells**, on every variant tried.
- The cheapest route to NF is **emitter area at constant current**, not
  current: `s_fixi_a80` buys 1.55 dB of NFmin over the committed core while
  *reducing* worst-cell P_dc by 1.36 mW.
- The trade is genuinely three-cornered, not two: pushing stage-1 area for
  NF in the two-stage topology (`t_lownf`) costs broadband stability
  (μ ≥ 1 at 18/45, minimum 0.99847812, three orders of magnitude worse than
  the control's dip) and is the only variant in the campaign that violates
  μ **in band** as well (15/45 cells). `t_bal` is the only variant of the
  fifteen that holds μ ≥ 1 at every cell and every swept frequency.

### 5. What none of this is verified against

Stated per `CLAUDE.md` rather than buried. **No inductor model exists in
this PDK** (issue #5, upstream `2AMLogic/klayout-tools#1519`): `Le`, `Lc`
and the two-stage probe's interstage block are ideal infinite-Q primitives,
so every gain/NF number here is the most optimistic case and every stability
number the least damped. The `Q = 3…50` table in Evidence — 2 is arithmetic
on measured S-parameters, not a passive model, and charges only the output
tank's loss, not the matching networks'. There is **no layout, no
extraction, no pads/package and no mismatch/Monte-Carlo** anywhere in this
evidence: an 80-unit emitter array is 9.2 µm² of emitter with a
correspondingly large `C_bc` and interconnect parasitic that these numbers
do not contain, so the `s_fixi_*` results are a statement about the device
physics of trading area for current density, **not** a claim that such an
array lays out and still measures this. The HBT process axis is **three**
real corners — `sf`/`fs` are documented duplicates of `typ` (issue #41).
And every variant except the control is a **probe**: nothing in `design/`
changes because of this record.

One variant is also partly **outside the model card's own validity box**:
`t_lownf` biases `V_BE1` to 0.6455–0.6460 V at its 3 `bcs`/125 °C cells,
below `sg13g2_hbt_mod.lib`'s 0.65 V floor (`model_card_flags` column of the
per-point CSV). Its numbers at those 3 of 45 cells are extrapolation, not
model-backed measurement, and are flagged rather than dropped. Every other
variant, including the control and `t_bal`, is `in_box` at all 45 cells on
all three of the card's limits (`V_BE`, `V_CE`, and the `ic < 0.003·Nx`
per-device current limit — checked per *device instance*, so the `m > 1`
variants stay inside it).

## Alternatives considered

- **Leave the analysis in issue #52 and open no record.** Rejected: two of
  the issue's premises do not survive re-derivation (Evidence 1 and 2) and
  one ratified row's disclosure note quotes a number against the wrong
  reference temperature (Evidence 3). Those belong in `spec/`'s append-only
  trail, not in an issue comment.
- **Propose relaxing the NF row to something the hot corner can meet
  (≈ 1.9 dB), or narrowing its temperature range.** **Explicitly refused.**
  `CLAUDE.md` forbids an agent relaxing a ratified row to make results pass,
  and the fact that this record *could* name the number that would pass is
  exactly why it must not propose it. Option D below hands that decision to
  the operator with the evidence attached and no recommendation.
- **Declare `t_bal` the new core and swap `design/lna.sch`.** Rejected as
  out of scope and premature: #52's scope guard excludes design changes, the
  two-stage DUT is a probe with no schematic, no interstage matching and no
  layout feasibility check, and its NF still misses the row at 15 cells. A
  topology change of that size needs its own issue, its own decision record
  and its own startup/linearity/IIP3 re-verification.
- **Fold this into #27.** Rejected for the reason #52 itself gives: #27 is
  blocked in practice on the inductor-model gap, and the device-sizing axis
  is not.

## Options for the operator

Presented as a menu with the evidence behind each, **with no
recommendation** — three of the four are `spec/` acts only the operator can
take.

**Option A — correct the two disclosure notes, change no ratified value.**
`spec/target-spec.md`'s NF and Gain rows currently quote
`NFmin` = 2.0749/2.3817/2.7275 dB (analysis-temperature referenced, Evidence
3) and "not reachable even under a lossless ideal matching network"
(input-match-only metric, Evidence 2). A ratification PR would restate them
as NFmin@290 = 1.7389/2.4454/3.4239 dB and as "not reachable by an input
match alone; reachable at Q ≥ 3 once the output network the S22 row already
requires exists". **No ratified value moves.** Cost: one `spec/` edit.
This is the only option that is purely a correction.

**Option B — keep all three rows and accept that the block is a
cold-and-nominal part until something changes.** Evidence 4 says P_dc and
Gain hold at 45/45 and NF holds at 30/45 (all the −40 °C and 27 °C cells).
Cost: the 125 °C cells stay failing-spec, disclosed, indefinitely. Buys:
nothing is relaxed and no design risk is taken. **Read the fine print
before choosing it**: the 30/45 figure is `s_fixi_a80`'s, not the committed
core's. On the DUT actually on `main` the NF row holds at **0 of 45** cells
(NFmin@290 1.739–3.424 dB), so "a cold-and-nominal part" is only true after
a device-sizing change this record deliberately does not make — an 8→80
unit emitter array whose layout cost is unmodelled (Evidence 5). Choosing B
as a *description of today's block* would be wrong; choosing it as a
*position on the spec* is coherent.

**Option C — spend the remaining levers this evidence has not exhausted,
before any spec question is asked.** The measured hot-cell gap is 0.10 dB
(best hot cell, `s_fixi_a80`) to 0.37 dB (worst hot cell). Levers not tried
here, each needing its own issue: a lower-`V_CE1` / higher-`V_CE2` cascode
split (the `V_CE` flatness the hbt record measures is weak but nonzero), a
base-resistance-optimised emitter layout (`r_b` is the dominant hot-corner
NF term and is a *layout* variable this bench cannot see), and the actual
input matching network, whose insertion loss adds to NF rather than
subtracting — so #27 is a *risk* to this row, not a remedy. Cost: design
cycles, with no guarantee 0.37 dB appears. Buys: the possibility that no
spec question needs asking at all.

**Option D — ask whether the NF row's binding conditions are the right
ones.** The row binds NF < 1.5 dB *across the full ratified corner box*,
which includes 125 °C. The measured hot-corner floor across 15 variants is
1.601 dB. **This record does not propose any change and names no
replacement number** — it records that the operator is the only party who
may decide whether a 2.4 GHz ISM LNA's NF row should bind at 125 °C, and
that if the answer is yes then Option B is the standing position.
Note for whoever rules on this: the two-key competitiveness rule
(`2AMLogic/2am#372`) was last verified not operational (see
`spec/target-spec.md` §"The ratification path actually used"), so any
*relaxation* would go through operator approval of a ratification PR, and
that PR would need this record superseded by one that states the new value
and its market rationale.

## Consequences

**Enabled**

- The gain question is closed as a spec worry: 45/45 cells clear > 15 dB at
  any inductor Q ≥ 3 with the output network the S22 row already requires,
  and a two-stage core clears it unmatched inside the power row. #27 can
  budget matching-network insertion loss against **5.4 dB** of measured
  headroom at Q = 10 rather than against a 0.58 dB deficit.
- The NF question is now a single, quantified number — **0.10–0.37 dB at
  125 °C** — instead of an open-ended "is this device capable at all".
- `sim/lna-core-envelope/` is a reusable envelope bench: the same runner
  answers "what does geometry/topology change X do to all four rows across
  all 45 cells" for any future candidate, with a control that hard-fails if
  it ever stops reproducing the committed campaign.
- The NF-reference-temperature trap is now caught by machine, not by
  reading: the new bench emits `nfmin290_db_*` beside the raw `sp` column
  at every point, so no future record can quote the wrong one by accident.
- So is the μ-precision trap. Every stability verdict in the new record is
  counted from unrounded per-frequency points (`n_inband_pts_mu_lt_1` /
  `n_broadband_pts_mu_lt_1`), and the record's own roll-up table says in
  plain text that its rounded minima are not pass/fail. This repo has now
  met the same trap twice on the same bench — `s22_mag_broadband_max` in
  `spec/target-spec.md`'s S22 row, and `mu_broadband_min` here — which is
  the sort of tool-and-method friction the canary exists to surface.

**Costs and constraints this imposes**

- **Two numbers in `spec/target-spec.md` are now known to be quoted against
  the wrong NF reference temperature** and will stay that way until an
  operator-approved ratification PR fixes them (Option A). That is a
  disclosed inaccuracy in a ratified document, not a comfortable state.
- **The `s_fixi_*` NF results are device-physics claims, not layout claims.**
  Acting on them means accepting an 8–10× emitter-area increase whose
  parasitic and matching cost is entirely unmodelled today.
- **The two-stage result carries a stability trade this record quantifies
  but does not resolve** (`t_bal` μ ≥ 1 at 45/45 vs `t_lownf` at 18/45).
  Any topology decision must re-check μ over the full sweep, per `CLAUDE.md`.
- **Nothing here is verified against a physical passive.** The whole gain
  argument turns on inductor Q, and this PDK ships no inductor model at all.

**Follow-up work this record does not do**

- The `spec/target-spec.md` edits of Option A (operator's ratification act).
- Any design change: no `design/lna.sch` edit, no topology decision, no
  matching network. #27 owns the networks; a topology change needs its own
  issue and record.
- The Option-C levers (cascode `V_CE` split, `r_b`-optimised emitter layout,
  input-network NF budget).
- IIP3 on any variant — this bench has no two-tone phase, and the DRAFT IIP3
  number is explicitly out of #52's scope.
