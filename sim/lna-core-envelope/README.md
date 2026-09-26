# lna-core-envelope — what (gain, NF, P_dc) is achievable on this core at all

**Experiment owner**: issue
[#52](https://github.com/2AMLogic/sg13g2-lna/issues/52).
**Status**: evidence. Nothing here is a conformance claim against any
`spec/target-spec.md` row, and nothing here changes `design/`.

**Contents** (hand-maintained; this repo has no TOC generator)

- [What question this answers, and why it needed its own bench](#what-question-this-answers-and-why-it-needed-its-own-bench)
- [Records in this experiment](#records-in-this-experiment)
- [What is measured, and how (bench definitions)](#what-is-measured-and-how-bench-definitions)
- [NF conventions on this bench — three different quantities](#nf-conventions-on-this-bench--three-different-quantities)
- [Three gain metrics, and which one binds what](#three-gain-metrics-and-which-one-binds-what)
- [The variant table](#the-variant-table)
- [Results](#results)
- [Model limitations](#model-limitations)
- [Regeneration](#regeneration)

## What question this answers, and why it needed its own bench

`sim/lna-characterization/` measures **the committed DUT**. Its most recent
record (`20260926-122301-088c734`, the DR-0003 re-baseline) shows the
as-committed core missing two RATIFIED rows — Gain (S21) > 15 dB and
NF < 1.5 dB — and issue #52 asks a question that record cannot answer:
**what envelope of (gain, NF, P_dc) is reachable on `npn13G2` at all, and
does an emitter-geometry, device-count or two-stage change move it?**

Answering that requires simulating DUTs that are *not* the committed
netlist. So this experiment exists as its own directory, with its own
record ids, so that no variant number can ever be mistaken for a
measurement of `design/lna.sch`. The committed netlist runs here too, as
the control variant `s_ctrl_a8`, and the parser **refuses to write a
record** unless that control reproduces
`sim/lna-characterization/records/20260926-122301-088c734-summary.csv` —
it currently reproduces it to a worst relative difference of `0.000e+00`
across all 45 cells and all six compared columns, so every variant number
below sits on a bench proven identical to the committed campaign's.

## Records in this experiment

| Record | What it is |
|---|---|
| `20260926-180931-90b07a0` | The campaign: 15 DUT variants × the ratified 45-cell PVT grid = 675 `sp`/`.noise`/stability decks. Per-point CSV, per-variant roll-up CSV, record `.md`. |
| `20260926-122301-088c734-derived-envelope.csv` | **Derivation, not simulation.** Two columns issue #52 needs that the committed `lna-characterization` record does not carry, computed from that record's own committed raw `.dat` tables by `derive_committed_record_envelope.py`: `NFmin` re-referenced to the RATIFIED T0 = 290 K, and the available-gain envelope vs collector-tank inductor Q. Deterministic; no PDK, no ngspice. The source record is untouched (append-only, `sim/README.md`). |

## What is measured, and how (bench definitions)

Per `CLAUDE.md` — *"NF and S-param numbers carry their bench definitions"* —
here they are, and they are deliberately **identical** to
`sim/lna-characterization/`'s so the two experiments' records can be read
side by side:

- **Ports**: ngspice `sp`-analysis port sources at **z0 = 50 Ω at both
  ports**, matching `spec/target-spec.md`'s ratified port convention. `sp`
  yields S11/S21/S12/S22 directly plus, with its `donoise` flag set,
  ngspice's own two-port NF/NFmin.
- **In-band sweep**: 11 points, 2.4 GHz … 2.4835 GHz (the ratified band).
  Every in-band figure in a record is the **worst** of those 11 points
  unless the column name says otherwise.
- **Broadband stability sweep**: 10 MHz … 30 GHz at 40 points/decade
  (140 frequencies), with k, μ (Edwards–Sinsky) and |Δ| computed *in the
  deck* from the `sp` S-parameters, plus max |S11|/|S22| for the
  negative-resistance check. `spec/target-spec.md`'s stability row binds
  **μ > 1 over this whole sweep at every cell**.
- **Noise figure**, second branch: a second, electrically isolated copy of
  the DUT driven from a 50 Ω Thevenin source into a 50 Ω load, with **both
  `Rs` and `RL` declared `noisy=0`** and the source term re-introduced
  analytically at an explicit reference temperature — the shape issue #25
  concluded every future NF bench in this tree should use. `nf290` (the
  RATIFIED T0 = 290 K reference) and `nf30015` are both reported.
- **Operating point**: `.op` before every AC analysis; `I_C1`, `I_C2`,
  `I_B1`, `V_CE1`, `V_CE2`, `V_BE1`, `I_DD`, `P_dc` are recorded per point,
  and `P_dc`/`I_C1` are checked against the RATIFIED < 10 mW row and
  DR-0001's ≤ 4.5 mA mandate per cell.
- **Current density**: `J_C = I_C1 / (Nx · m · A_E)`, `A_E = 0.1152 µm²`
  (`npn13G2`'s own default single-finger geometry, `le=0.96µm ×
  we=0.12µm`) — the identical definition `sim/hbt-characterization/` uses.
- **Model-card validity**: every point carries a `model_card_flags` column
  checking `V_BE ∈ [0.65, 0.96] V`, `V_CE ∈ [0.4, 2.0] V` and the card's
  `ic < 0.003·Nx A` per-device current limit. A point outside the box is
  flagged, not silently reported as if it were in it.
- **Solver**: `.options temp=<T> tnom=27 gmin=1e-10` in every deck,
  identical to the lna-characterization bench (that record quantifies the
  gmin override's cost as ≤ 4.5e-5 relative on any quantity).
- **PVT grid**: `{typ, bcs, wcs, sf, fs} × {−40, 27, 125} °C ×
  {1.62, 1.80, 1.98} V` = 45 cells per variant. **`sf` and `fs` are
  documented duplicates of `typ`** — `cornerHBT.lib` in the pinned v0.3.0
  checkout ships exactly three real HBT sections (see `sim/README.md`
  §"Corner-label convention" and issue #41) — so the HBT process axis is
  three real corners, not five. The MOS side (`cornerMOShv.lib`) does ship
  five real sections, and the bias core rides them, so the five labels are
  not wholly redundant; but no HBT-dominated conclusion here may be stated
  as resting on five independent process corners.

## NF conventions on this bench — three different quantities

Issue #52 asks explicitly whether the device-bench NF convention
(`sim/hbt-characterization/`) and the circuit-bench one
(`sim/lna-characterization/`, and therefore this bench) are comparable.
They are **not**, and there are three distinct differences, each measurable:

1. **Reference temperature of ngspice's own `sp` NF.** ngspice's two-port
   `sp` noise figure — the `NF`/`NFmin` vectors, and therefore the
   committed `nf_sp_db_*` / `nfmin_sp_db_*` columns — is referenced to the
   **analysis temperature**, not to any fixed T0. This is proven, not
   assumed: `derive_committed_record_envelope.py` re-references the
   committed record's *independently computed* `.noise`-based `nf290`
   column (Xb branch, analytic 290 K source term) to each cell's analysis
   temperature and reproduces the committed `sp`-analysis `nf` column (Xa
   branch) to a worst error of **9.2e-5 dB over all 45 cells**. No other
   reference convention satisfies that identity.

   `spec/target-spec.md`'s NF row is RATIFIED at **T0 = 290 K**. So the raw
   `nfmin_sp_db` column is not the quantity that row binds, and this
   bench emits `nfmin290_db_*` beside it (never instead of it), using the
   same algebraic re-reference `sim/hbt-characterization/
   rederive_nf_fixed_t0.py` uses for the #25 correction:
   `F(T₀) − 1 = (F(Tₐ) − 1)·Tₐ/T₀`. The correction is not cosmetic: on the
   committed record it moves `NFmin` from a 2.0749–2.7275 dB span to
   **1.7389–3.4239 dB** — *better* than reported at the cold cells,
   *worse* at the hot ones, and it moves which cell is binding.

2. **Optimised over source impedance vs. optimised over bias.** The
   `hbt-characterization` records' `noise_optimum_nf_db_*` columns are the
   minimum, **over the `J_C` sweep**, of a **fixed-50 Ω-source** noise
   figure. `NFmin` here is the minimum **over source impedance** at a fixed
   bias. They are different minimisations of different functions, and they
   move in **opposite directions with `J_C`**: a fixed 50 Ω source favours
   high `J_C` (which pulls the device's own `Z_opt` down toward 50 Ω),
   while `NFmin` keeps improving as `J_C` falls. The campaign below
   measures exactly that opposition (see Results), so this is not an
   argument either.

3. **Different DUT.** The device bench measures a bare common-emitter
   `npn13G2` through ideal bias tees. This bench measures the whole
   cascode with `Le` degeneration, the `Lc` tank, the cascode divider and
   the DR-0003 bias core attached — all of which contribute noise and
   loading.

**Consequence, stated plainly**: issue #52's device-level corroboration —
"the bare device's own noise optimum is 2.20 dB at `typ`/−40 °C … at
`J_C` ≈ 14 mA/µm², roughly 3.5× the current density DR-0001 operates at" —
is a 50 Ω-source figure at a 300.15 K reference on a different DUT, and it
**points the wrong way** for the circuit's NF. It is withdrawn as
corroboration here; the conclusions in this experiment and in the decision
record it feeds rest on the circuit benches alone.

## Three gain metrics, and which one binds what

The discussion on issue #52 uses one figure, the "available-gain basis"
`|S21|_dB − 10·log₁₀(1 − |S11|²)`. That number is real, and this bench
reports it (`gain_in_match_basis_db_min`), but it is worth being explicit
about what it assumes: it applies an ideal conjugate match at the **input**
and leaves the **output terminated in the bare 50 Ω port**. It is
therefore *not* "the gain after matching" — it is the gain after **input**
matching only, and #27's scope is both networks (the RATIFIED S22 row
requires the output one to exist).

This bench reports three:

| column | what it is | what it is good for |
|---|---|---|
| `s21_db_min` | measured \|S21\| at 50 Ω ports, worst in-band point | the raw, unmatched measurement — no assumptions at all |
| `gain_in_match_basis_db_min` | + ideal conjugate **input** match, output still 50 Ω | a **lower** bound on a matched design's gain |
| `ga_max_q10_db_min` | two-port available gain, **both** ports conjugate matched, with `Lc` degraded to Q = 10 | the honest envelope |

`ga_max_qQ` is **arithmetic on the measured S-parameters, not a new
simulation and not an inductor model**: a finite-Q inductor of reactance
`X = 2πf·Lc` presents a parallel loss resistance `Rp = Q·X`, so embedding
that shunt conductance at port 2 (via S→Y→S) turns the measured two-port
into the same circuit with a Q-limited tank. It charges the tank's own
loss — the dominant term, since the committed `Lc` is an ideal infinite-Q
primitive — but **not** the matching networks' own insertion loss, which is
#27's to budget. Read it as an upper bound with the biggest known loss term
already subtracted, not as a prediction.

Why this matters: the committed core's output looks, under ideal passives,
like **0.0427 + j76.50 Ω** at the band-bottom sweep point (2.4 GHz; `Zout`
= 50·(1+S22)/(1−S22) from the committed complex `S22` at `typ`/27 °C/
1.80 V) — a parallel-equivalent **137 kΩ ∥ j76.5 Ω**, i.e. a near-lossless
current source. It varies little across the band: 0.0457 + j77.92 Ω
(133 kΩ ∥ j77.9 Ω) at band mid, 0.0489 + j79.34 Ω (129 kΩ ∥ j79.3 Ω) at
band top. Leaving that terminated in 50 Ω throws away essentially all of
the available power. That single modelling choice is the whole difference
between "14.42 dB, 0.58 dB short of the row" and "20.40 dB at the worst of
45 cells with a Q = 10 tank".

One numerical caveat on the `ga_max_*` columns, stated because the
approximation is not uniformly good: they are the **unilateral** maximum
gain `|S21|²/((1−|S11|²)(1−|S22|²))`, which is exact only as \|S12\| → 0.
Cross-checked against the exact Rollett MAG `|S21/S12|·(k − √(k²−1))` on
the committed record's own S-parameters, the two agree to **≤ 0.01 dB at
every finite Q** (Mason's unilateral figure of merit U ≤ 7e-4 there) but
diverge by **~0.5 dB at Q = ∞** (U reaches 0.090, because 1 − \|S22\|² →
1e-3 inflates it). So the finite-Q rows are trustworthy to a hundredth of
a dB and the `Q = ∞` row should be read as an order-of-magnitude
illustration only — which is also the row that has no physical meaning.

## The variant table

Every variant is a **probe**, not a design. Single-stage variants are the
committed `design/netlist/lna.spice` with **exactly three substituted
lines** — the two RF cascode device lines' geometry and the DR-0003 island
mirror `XMis`'s width — and the runner aborts if any substitution stops
matching. Two-stage variants come from the committed
`dut/lna_2stage.spice.tmpl`, whose header documents its construction line
by line.

| variant | topology | stage geometry `Nx × m` | `XMis` | family / what it isolates |
|---|---|---|---|---|
| `s_fixj_a2` … `s_fixj_a10` | 1 stage | 2×1, 4×1, 6×1, 10×1 | 512u (committed) | **A1 fix-`J_C`.** The DR-0003 core is a *density* mirror (Q3 `Nx=1` against Q1 `Nx=8`), so `I_C` tracks `Nx` and `J_C` stays put. This family is issue #52's literal *"more parallel emitter area at the same `J_C`"* question — and it is a pure **power** axis. |
| `s_ctrl_a8` | 1 stage | 8×1 | 512u | **CONTROL** — the committed netlist. Must reproduce record `20260926-122301-088c734`. |
| `s_fixi_a4` … `s_fixi_a80` | 1 stage | 4×1, 10×1, 10×2, 10×4, 10×8 | 1024u … 51.2u (`≈4096u/(Nx·m)`) | **A2 fix-`I_C`.** Mirror scaled inversely with emitter area so `I_C` re-lands near the committed ~3.9 mA. Holds DC power roughly fixed and sweeps `J_C` instead — the power-neutral lever the committed campaign never exercised. `m > 1` reaches total emitter areas past the model card's `Nx ≤ 10` limit **as parallel device instances**, each individually in-box. |
| `t_equal` | 2 stage | 8×1 + 8×1 | 273u | **B.** Equal split inside the power row. |
| `t_nfw` | 2 stage | 10×4 + 8×1 | 110u | **B.** NF-weighted (big first stage). |
| `t_bal` | 2 stage | 10×4 + 10×2 | 75u | **B.** Gain/NF balanced. |
| `t_lownf` | 2 stage | 10×8 + 10×2 | 45u | **B.** Lowest-NF two-stage inside the power row. |
| `t_full` | 2 stage | 8×1 + 8×1 | 512u (committed) | **B, deliberately over budget** — the naive "just add a second stage" case, kept so the power cost is a measured row and not an assertion. |

## Results

Full per-variant roll-up: `records/20260926-180931-90b07a0.md`. Per-cell
data: `records/20260926-180931-90b07a0.csv`. Counted against the RATIFIED
rows (Gain > 15 dB; NF < 1.5 dB at T0 = 290 K; P_dc < 10 mW; μ > 1 over
10 MHz–30 GHz), over all 45 cells:

| variant | P_dc < 10 mW | \|S21\| > 15 dB *unmatched* | G_A > 15 dB at Q=10 | NFmin@290 < 1.5 dB | μ ≥ 1 broadband |
|---|---|---|---|---|---|
| `s_ctrl_a8` (committed) | 45/45 | 0/45 | **45/45** | 0/45 | 0/45 |
| `s_fixj_a10` | 17/45 | 0/45 | 45/45 | 0/45 | 0/45 |
| `s_fixi_a20` | 45/45 | 0/45 | 45/45 | 12/45 | 0/45 |
| `s_fixi_a40` | 45/45 | 0/45 | 45/45 | 27/45 | 0/45 |
| `s_fixi_a80` | 45/45 | 0/45 | 45/45 | **30/45** | 0/45 |
| `t_equal` | 45/45 | 45/45 | 45/45 | 0/45 | 0/45 |
| `t_nfw` | 32/45 | 45/45 | 45/45 | 18/45 | 42/45 |
| `t_bal` | **45/45** | **45/45** | **45/45** | 15/45 | **45/45** |
| `t_lownf` | 45/45 | 45/45 | 45/45 | 27/45 | 18/45 |
| `t_full` | 0/45 | 45/45 | 45/45 | 0/45 | 0/45 |

**The μ column is counted from the raw sweep points, not from the roll-up's
rounded minimum** — and that distinction changes two of these rows, so it is
worth stating how it was found rather than only that it was. On this
topology \|S12\| ≈ −95 dB makes μ ≈ 1/\|S22\|, and `Lc` is an ideal
infinite-Q primitive, so \|S22\| → 1 and μ sits within parts per *billion*
of 1 across most of the out-of-band sweep. A `mu_broadband_min` column
rounded to 8 decimals therefore prints `1.00000000` for cells that do dip
below 1 somewhere: 115 of the 675 points here round that way. Counted on
the unrounded values (`n_broadband_pts_mu_lt_1` in the per-point CSV,
`mu_bb_viol`/`mu_bb_pts_lt_1` in the roll-up), `t_equal` holds μ ≥ 1 at
**0** of 45 cells rather than 7, and `t_nfw` at **42** of 45 rather than 45
— while `t_bal`'s pass is real: **0 sub-unity points out of 6300** swept
frequencies. `spec/target-spec.md`'s S22 row records the identical trap on
the identical bench for `s22_mag_broadband_max` ("count from the raw
tables"); this parser now does the counting itself so a reader cannot
inherit it.

Five findings, each a measured row rather than an argument:

1. **At constant `J_C`, emitter area is only a power knob.** The A1 family
   spans `J_C` = 3.87–4.55 mA/µm² whatever `Nx` is, because the DR-0003
   core mirrors by density. `s_fixj_a10` buys 0.70 dB of input-matched gain
   and 0.29 dB of NFmin over the control and breaches the P_dc row at
   **28 of 45 cells** doing it. Issue #52's literal "more parallel emitter
   area at the same `J_C`" lever is measured, and it does not pay.

2. **At constant `I_C`, emitter area is a free NF knob — and it is the
   opposite of what the device bench's 50 Ω-source optimum suggests.**
   Going from the committed 8 units to 80 (`s_fixi_a80`) drops `J_C` from
   4.28 to 0.32–0.43 mA/µm² — *away from* the device bench's ~14 mA/µm²
   "noise optimum" — and improves worst-cell NFmin@290 from **3.424 dB to
   1.870 dB** while *lowering* worst-cell P_dc from 9.77 to 8.41 mW. This
   is finding (2) of the NF-conventions section, measured.

3. **The NF row's binding constraint is temperature, not power.** No
   variant clears NF < 1.5 dB at **any** of the 15 hot (125 °C) cells. The
   best hot-cell NFmin@290 anywhere in the campaign is `s_fixi_a80`'s
   **1.601 dB** (best hot cell) / **1.870 dB** (worst hot cell). At −40 °C
   and 27 °C the row is comfortably clear on the same variant
   (0.796–1.286 dB).

4. **A second stage closes the gain row inside the power row,
   unmatched.** `t_bal` (10×4 + 10×2 on one shared bias core, `XMis` 75u)
   measures **\|S21\| ≥ 18.60 dB at every one of the 45 cells with no
   matching network at all**, at P_dc 6.27–9.38 mW — 0/45 violations of the
   < 10 mW row. `t_full` (the naive "duplicate the stage at full current")
   is the control for the cost: 12.79–17.92 mW, 45/45 violations.

5. **One two-stage variant — and only one — retires the out-of-band
   stability failure the committed core has.** Every single-stage variant
   dips below μ = 1 somewhere in 10 MHz–30 GHz at 45/45 cells (the control's
   minimum is 0.99999592, matching the committed record; 2625 of its 6300
   swept points are sub-unity). `t_bal` holds **μ ≥ 1 at 45/45 cells with
   0 sub-unity points out of 6300** across the whole sweep. It is the only
   variant here that does: `t_nfw` reaches 42/45 (23 sub-unity points in 3
   cells), and `t_lownf`, which pushes stage-1 area further for NF, falls
   back to 18/45 with a minimum of 0.99847812 — three orders of magnitude
   worse than the control's dip — and is the only variant that also
   violates μ **in band** (15/45 cells). `t_equal` and `t_full` hold at
   0/45. Gain, NF and stability trade against each other here; the campaign
   quantifies the trade rather than picking a winner.

**No variant clears all three RATIFIED rows at all 45 cells.** The closest
are `t_bal` (power ✔ 45/45, gain ✔ 45/45, stability ✔ 45/45, NF ✔ 15/45)
and `s_fixi_a80` / `t_lownf` (NF ✔ 27–30/45, but 0/45 on the hot cells).
**`t_lownf` additionally leaves the model card's validity box at 3 of its
45 cells** (`bcs`/125 °C, all three supplies: `V_BE1` = 0.6455–0.6460 V
against the card's 0.65 V floor — `model_card_flags` column), so its
numbers at those cells are extrapolation, not model-backed measurement;
every other variant is `in_box` at all 45 cells. What all of this means for
the spec is a decision for the operator, not for this bench: see
`spec/decision-records/0004-achievable-gain-nf-power-envelope.md`.

## Model limitations

Everything `sim/lna-characterization/README.md` §"Model limitations" says
applies here unchanged, because it is the same bench. The three that bound
what any number above can be trusted to mean:

- **No inductor model exists in this PDK.** `Le`, `Lc` and the two-stage
  probe's `Cc` are ideal infinite-Q SPICE primitives (issue
  [#5](https://github.com/2AMLogic/sg13g2-lna/issues/5), upstream
  [`2AMLogic/klayout-tools#1519`](https://github.com/2AMLogic/klayout-tools/issues/1519)).
  Every gain/NF/S11/S22 number here is the **most optimistic** case and
  every stability number the **least damped** case. The single finite-Q
  figure anywhere in this experiment is `ga_max_qQ`, and it is arithmetic
  on measured S-parameters, not a passive model.
- **No layout, no extraction, no pads/package.** An 80-unit emitter array
  (`s_fixi_a80`, `t_lownf`) is 9.2 µm² of emitter and a correspondingly
  large base-collector capacitance and interconnect parasitic. None of that
  is in these numbers. The `s_fixi_a*` NF results are therefore a statement
  about the **device physics** of trading area for current density, not a
  claim that an 80-unit array lays out and still measures this.
- **No mismatch / Monte Carlo**, and the HBT process axis is three real
  corners with `sf`/`fs` duplicated from `typ`.

## Regeneration

```bash
export PDK_ROOT=/path/to/ihp-open-pdk PDK=ihp-sg13g2
sim/tools/build-osdi.sh                       # once, for the PSP103.6 models
sim/lna-core-envelope/run_core_envelope.sh    # ~675 decks, serial, ~11 min
```

The runner is deliberately **serial** — one `ngspice` at a time, no job
pool. `CORE_ENV_SMOKE=1` runs one nominal cell; `CORE_ENV_VARIANTS="a b"`
restricts the variant list; `CORE_ENV_RECORD_ID=<id>` pins the record id and
(with the runner's resume behaviour, which skips any deck whose log already
reached `BENCH_COMPLETE`) lets an interrupted campaign finish as one record.

The derivation half needs no PDK and no ngspice at all:

```bash
sim/lna-core-envelope/derive_committed_record_envelope.py
```
