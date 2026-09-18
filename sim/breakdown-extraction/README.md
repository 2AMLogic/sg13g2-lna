# breakdown-extraction — `npn13G2` BVCEO / BVCER / BVCES from the model card

Issue [#20](https://github.com/2AMLogic/sg13g2-lna/issues/20). The ratified
bias/supply-topology decision record
[`spec/decision-records/0001-bias-supply-topology.md`](../../spec/decision-records/0001-bias-supply-topology.md)
(DR-0001) builds its breakdown-voltage budget on two **static** numbers — the
process-spec `BVCEO` (1.4 V min / 1.6 V target, no stated temperature and no
stated current criterion) and the VBIC card's own declared `vce_max = 1.6`,
`vbe_max = 1.6`, `vbc_max = 5.1`. Its own "What is NOT evidenced here" section
names the gap this experiment closes:

> **No committed breakdown testbench exists in this repo.** BVCEO here is a
> *process-spec* and *model-card* number, not a simulated extraction. […]
> Follow-up: #20.

This experiment extracts collector–emitter breakdown **from the committed
model card itself**, using its weak-avalanche parameters (`avc1 = 2.40`,
`avc2 = 10.81` in `sg13g2_hbt_mod.lib`), across the HBT process-corner grid ×
{−40, 27, 125} °C × `Nx` ∈ {1, 8}, for the open base (BVCEO) and for finite
and shorted base terminations (BVCER / BVCES).

**Scope and standing.** Everything here is a property of the **VBIC model
card**, not of silicon, and it is **evidence input** to DR-0001's breakdown
budget, not a re-ratification of it and not a claim against any
`spec/target-spec.md` row (none are ratified). Nothing here is an RF result:
this is a **DC-only** experiment — no port, no 50 Ω reference, no matching
network, no noise or S-parameter quantity anywhere.

## Why the naive bench does not work (and is committed here as a control)

DR-0001 and issue #20 both record an uncommitted spot check — quasi-open base
(1 GΩ to ground), emitter grounded, a voltage-driven `.dc` sweep of `V_CE` —
that produced a plausible-looking runaway at 27 °C, **never found the runaway
at all at −40 °C or +125 °C**, and snapped back to the leakage branch above
~3.0 V at 27 °C. No number from it was quoted anywhere.

The reason is structural, not a tuning problem. The open-base common-emitter
characteristic `I_CEO(V_CE)` is an **S-shaped snapback locus**: once
avalanche-generated base current is amplified by the device's own current
gain, the sustained current rises at a *falling* collector voltage. `I_C` is
therefore **not a single-valued function of `V_CE`**, a voltage-driven `.dc`
sweep has two or three solutions to choose from at every step, and ngspice's
continuation follows whichever branch its previous-point initial guess lands
on.

`V_CE`, by contrast, **is** single-valued in the forced collector current over
the same locus. So the extraction here **forces `I_C` and measures `V_CE`**
(Bench A), which removes the branch ambiguity entirely, and the naive
voltage-driven method is committed alongside it as an explicitly-labelled
**control** (Bench B, `role = control-open`) so the record carries the evidence
for why rather than asking a reader to take it on trust.

The control reproduces the reported failure exactly. In record
`20260918-212948-013274f`, at `RB` = 1 GΩ the voltage-driven sweep finds a
1 µA/finger runaway in **10 of 30 cells — every one of them at 27 °C** — and
reports a non-monotone `I_C(V_CE)` in most of the rest, against Bench A's
**60 of 60** fully-converged open-base cells at all three temperatures. A
second control at `RB` = 14 kΩ (`role = control-snapback`) shows the same
temperature-selective branch-following failure at a *finite* base impedance,
and can be cross-checked cell-for-cell against Bench A's answer for the same
grid points.

## What is extracted, and how (bench definitions)

Per `CLAUDE.md`, every recorded number carries its bench. Both benches use the
same DC topology and differ only in which quantity is driven.

### Bench A — current-driven continuation (`testbench/tb_bvceo_iforce.spice.tmpl`)

- **Circuit**: `Iforce 0 c` is an ideal DC current source injecting the forced
  collector current into node `c`; node `c` connects to nothing else, so the
  collector terminal current is *exactly* the forced value. `Rbe b e` is the
  base termination. `Ve e 0 dc 0` grounds the emitter through a 0 V source so
  `i(Ve)` is available as the emitter-terminal current. `XQ1`'s fourth
  terminal (`bn`, buried-layer/substrate) is tied to 0, i.e. to the emitter
  reference — the same connection
  `sim/hbt-characterization/testbench/tb_hbt_sweep.spice.tmpl` uses.
- **Analysis**: a `.control` loop of repeated `op` solves, `alter`-ing
  `Iforce` over a **logarithmic grid: 61 points, 8 points/decade, from
  `Nx`·1e-10 A up to `Nx`·3.16e-3 A**. Logarithmic stepping *is* the
  continuation: each successive Newton solve starts near the previous
  solution. The measured quantities per point are `v(c)` (= `V_CE`, the
  emitter being at 0 V), `v(b)` and `i(Ve)`.
- **Measured quantity**: `V_CE`. The forced current is the independent
  variable.
- **Current grid ceiling**: `Nx`·3.16e-3 A is deliberately set at the model
  card's **own declared current-validity ceiling** (`ic: <(0.003*Nx) A`). So
  "no avalanche-sustained branch was found" here always means *"none exists
  within the range the card is valid over"*, never *"the sweep was too
  short."*
- **Per-finger grid**: the current grid is multiplied by `Nx` inside the
  template, so the *current-density* grid — and hence every extraction
  criterion below — is `Nx`-invariant by construction. Every current quoted in
  this experiment is **per finger** unless stated otherwise.

### Bench B — voltage-driven `.dc` sweep (`testbench/tb_bvcer_vsweep.spice.tmpl`)

- **Circuit**: identical to Bench A except the collector drive — `Vce c 0` is
  an ideal DC voltage source (no series or load resistance, so there is no
  load line to intersect and no compliance limit), and `I_C = -i(Vce)` is
  measured.
- **Analysis**: `dc Vce 0.20 5.40 0.04` (131 points). The 0.04 V step is
  chosen so that **1.12 V** (DR-0001's worst-case `V_CE2`), **1.40 V**
  (`BVCEO` min), **1.60 V** (`vce_max`) and **2.00 V** (the top of the card's
  measured-range box `vce : 0.4 – 2.0 V`) all land exactly on the grid; the
  5.40 V ceiling sits just past the card's `vbc_max = 5.1`.
- **Where it is valid, and why it is used at all**: with the base tied to the
  emitter through a low impedance the device is **off** — the
  avalanche-generated base current is swallowed by `Rbe` instead of being
  amplified, so there is no regenerative feedback, no snapback, and
  `I_C(V_CE)` is monotone and single-valued over the whole swept range. That
  property is **asserted per cell**, not assumed: the summary CSV carries an
  `ic_monotone_in_vce` column, and it is `yes` in **60 of 60** held-base
  cells in the committed record.
- **Roles**: `leakage` (`RB` ∈ {1.4 kΩ, 1 mΩ} — the held-base read-out and the
  BVCER/BVCES extraction), `control-open` (`RB` = 1 GΩ — the naive method
  reproduced), `control-snapback` (`RB` = 14 kΩ — the same failure at a finite
  base impedance), `extended-probe` (ceiling raised to 12.00 V, 296 points,
  `Nx` = 8, explicitly **outside** model validity — see "What the model cannot
  tell us").

### Measurement-stream note (why the echoes go to their own file)

Both templates redirect their measurement output to a separate `*.meas` file
under `corners/<record-id>/` rather than leaving it on the console. ngspice's
dynamic-gmin-stepping `Note:` diagnostics are emitted by a different code path
and **do** interleave mid-line with console echoes on these cells — observed
producing rows like `VCE 2.80Note:`, which would silently corrupt a
measurement rather than fail loudly. A separate stream cannot be interleaved.
The full console log is still captured as `*.log` beside it, as the raw
evidence. The parser additionally applies a strict numeric-token test to every
field, so anything that is not a clean number is recorded as a **blank**, never
as a number.

## Extraction criteria

**A breakdown voltage is only defined together with its current criterion.**
The process spec's "1.4 V min / 1.6 V target" carries no stated criterion (and
no stated temperature), which is precisely why a single extracted number would
be misleading. Four criteria are therefore reported for every Bench A cell:

| Criterion | Meaning |
|---|---|
| `vce_at_1ua_per_nx_v` | measured `V_CE` at a forced `I_C` of **1 µA/finger** — the most conservative, "first sign of sustained avalanche" reading |
| `vce_at_10ua_per_nx_v` | at **10 µA/finger** |
| `vce_at_100ua_per_nx_v` | at **100 µA/finger** |
| `vce_at_500ua_per_nx_v` | at **500 µA/finger** = DR-0001's nominal operating current (`I_C` = 4.0 mA at `Nx` = 8) |
| `locus_min_vce_v` / `locus_has_foldback` | the **avalanche-sustaining voltage**: the minimum of the measured locus, flagged as a genuine fold-back only when that minimum is *interior* to the swept current range |

Values at the 1/10/100/500 µA criteria are interpolated linear-in-log(I) between
adjacent grid points (1, 10 and 100 µA/finger land exactly on the 8/decade grid;
500 µA/finger is interpolated).

On Bench B the corresponding figure is the `V_CE` at which `I_C`/finger first
reaches **1 µA** or **10 µA** — blank when it never does within the swept
range — plus a direct leakage read-out of `I_C`/finger at `V_CE` = 1.12, 1.40,
1.60 and 2.00 V.

## Why Bench A is open-base only (and finite-`RB` cells are split across benches)

Bench A (forced `I_C`) is the extraction for the **open base** and for base
impedances loose enough that an avalanche-sustained branch still exists —
`RB` = 14 kΩ and 1.4 kΩ are run on Bench A over the full grid for exactly that
reason, and 14 kΩ is where the sustaining branch is actually found.

With the base held **tightly** to the emitter the device is off: there is no
sustained branch for a forced current to land on, and forcing even 0.1 nA
drives the solver to tens or hundreds of volts and then into a self-heating
NaN. That is a property of the circuit, not a bug in the method, and it is
**committed as evidence rather than asserted**: four `role = probe` Bench A
cells at `RB` ∈ {140 Ω, 1 mΩ} (typ/27 °C, `Nx` ∈ {1, 8}) are run and recorded,
converge on only 36–43 of 61 points, and find a sustained branch in **0 of 4**
— the lowest `V_CE` anywhere on those loci is 3.7 V to 266 V, i.e. nowhere
near a physical breakdown. A probe cell's non-convergence is its *expected,
recorded* outcome and never counts as a run failure.

BVCER/BVCES at tight terminations is therefore read from **Bench B**, where
the held-base characteristic is monotone, single-valued, and the
voltage-driven sweep is sound (verified per cell, above).

## Why 1.4 kΩ, and why a bracket around it

DR-0001 biases the cascode base from an **RF-bypassed 11:1 resistive divider**
off `VDD` (`V_B2 = α·VDD`, `α = 11/12`). At a 100 µA divider current from a
1.8 V rail the divider is `R_total` = 18 kΩ, split 1.5 kΩ / 16.5 kΩ, whose
**Thevenin resistance is 1.5 kΩ ∥ 16.5 kΩ ≈ 1.375 kΩ** — the 1.4 kΩ value
swept here.

DR-0001 fixes the divider **ratio**, not its absolute impedance, so a single
value would be a number this experiment invented. A bracket is swept instead:

| `rb_label` | `RB` | What it represents |
|---|---|---|
| `open` | 1 TΩ | true open base ⇒ **BVCEO**. At the 0.4–0.9 V the base floats to, it leaks < 1 pA — under a part in 1e6 of the smallest swept current |
| `14k` | 14 kΩ | the **loose** end of the bracket (a 10 µA divider) ⇒ BVCER |
| `1p4k` | 1.4 kΩ | the **nominal** Thevenin value ⇒ BVCER |
| `140` | 140 Ω | the **tight** end (a 1 mA divider, or a strongly-bypassed base) ⇒ BVCER, method probe |
| `short` | 1 mΩ | base shorted to emitter ⇒ **BVCES** |
| `1g` | 1 GΩ | **not** an extraction — the quasi-open impedance of DR-0001's uncommitted spot check, run voltage-driven as the naive-method control |

Note that the *RF* bypass capacitor does not enter a DC bench at all: at DC the
cascode base sees the divider's Thevenin resistance, which is what is swept.
A real bypassed base is, if anything, **tighter** than 1.4 kΩ at the
frequencies where avalanche multiplication would matter, so the BVCER credit
reported below is conservative.

## Sweep grid

- **Corner labels**: `{typ, bcs, wcs, sf, fs}`, mapped onto `cornerHBT.lib`'s
  three **real** sections per `sim/README.md` → "Corner-label convention":
  `typ→hbt_typ`, `bcs→hbt_bcs`, `wcs→hbt_wcs`, and `sf`/`fs`→`hbt_typ` (no
  skewed HBT section exists in the installed PDK). **`sf` and `fs` rows are
  therefore numerically identical to `typ` by construction** — they are run
  and recorded anyway so the grid is literally the one `spec/target-spec.md`
  names, and every "N of M cells" count below includes them.
- **Temperature**: {−40, 27, 125} °C, via `.options temp=<T> tnom=27`.
- **`Nx`**: {1, 8}. `Nx = 8` is DR-0001's chosen device multiplicity; `Nx = 1`
  is the PDK default single-finger geometry (`le` = 0.96 µm, `we` = 0.12 µm).
- **Cell counts in record `20260918-212948-013274f`** (259 ngspice
  invocations):
  - Bench A, `RB` = open, `selft` ∈ {1, 0}: 60 cells (the BVCEO extraction)
  - Bench A, `RB` ∈ {14k, 1p4k}, `selft` = 1: 60 cells (the BVCER bracket)
  - Bench A, `RB` ∈ {140, short}, typ/27 °C: 4 probe cells
  - Bench B, `RB` ∈ {1p4k, short}: 60 cells (held-base leakage / BVCER,BVCES)
  - Bench B, `RB` = 1g: 30 control cells; `RB` = 14k: 30 control cells
  - Bench B, 12 V extended probe: 15 cells

## Self-heating

The card's thermal network is explicit:
`rth = 1*selft*3.26E+03*(4/Nx)**0.9` K/W, with **`selft = 1` by default** (the
PDK default; the VBIC thermal node is active). Setting `selft = 0` forces
`rth` to 0 and disables it.

**The extraction was run both ways.** Every open-base (BVCEO) cell is run at
`selft = 1` *and* `selft = 0`, over the whole grid. The result: self-heating is
**negligible for this extraction**. Largest
|BVCEO(`selft=1`) − BVCEO(`selft=0`)| over all 30 corner/temp/`Nx`
combinations is **0.0001 V** at the 1 µA/finger criterion and **0.0025 V** at
500 µA/finger — three to four orders of magnitude below the quantity being
extracted. That is expected: at 1.5 V and 500 µA/finger the dissipation is
0.75 mW/finger, and the interesting part of the locus sits far below that.

Bench B cells are run at `selft = 1` only. Held-base dissipation there is
sub-nanowatt (`I_C` ≤ 1e-10 A/finger across the whole sweep — see below), so
self-heating cannot move those numbers, and the open-base pairs above already
bound the sensitivity. The Bench A finite-`RB` cells are likewise `selft = 1`
only, for the same reason.

`selft` appears in every point id (`…_st0` / `…_st1`) and as its own column in
both summary CSVs, so **every recorded number states its self-heating state.**

## Results (record `20260918-212948-013274f`)

Full per-cell data: `records/20260918-212948-013274f-bvceo-summary.csv`
(Bench A) and `-heldbase-summary.csv` (Bench B); full loci in
`-bvceo-locus.csv` and `-heldbase-sweep.csv`; narrative in
`records/20260918-212948-013274f.md`.

### BVCEO (open base), 60 cells, both `selft` states

Minimum and maximum over all corners / `Nx` / `selft`, per temperature:

| Criterion | −40 °C min | 27 °C min | 125 °C min | grid min | grid max |
|---|---|---|---|---|---|
| 1 µA/finger | 1.4727 V | 1.4489 V | **1.3310 V** | 1.3310 V (`bcs`/125 °C) | 1.6954 V (`wcs`/−40 °C) |
| 10 µA/finger | 1.4985 V | 1.4922 V | 1.4021 V | 1.4021 V (`bcs`/125 °C) | 1.7216 V (`wcs`/27 °C) |
| 100 µA/finger | 1.5416 V | 1.5528 V | 1.4905 V | 1.4905 V (`bcs`/125 °C) | 1.7840 V (`wcs`/27 °C) |
| 500 µA/finger | 1.6301 V | 1.6550 V | 1.6126 V | 1.6126 V (`bcs`/125 °C) | 1.9050 V (`wcs`/27 °C) |

Three readings:

1. **The binding corner for breakdown is `bcs` (best-case speed), not
   `wcs`.** Higher β ⇒ lower `BVCEO` — the classic `BVCEO ≈ BVCBO/β^(1/n)`
   trade. This is the *opposite* corner from the one that binds NF
   (`wcs`/125 °C in `sim/hbt-characterization/`), so a single "worst corner"
   does not exist for this block and both must be carried.
2. **`BVCEO` falls with temperature, as expected** (β rises with `T`): at the
   1 µA/finger criterion the grid minimum drops 1.4727 → 1.4489 → 1.3310 V
   across −40 → 27 → 125 °C, a **0.142 V derating over the corner range**.
   The process-spec figure states no temperature; this quantifies what the
   hot-corner budget was silently absorbing.
3. **`Nx` invariance**: on a per-finger current criterion, the largest
   |BVCEO(`Nx`=1) − BVCEO(`Nx`=8)| at the same corner/temp/`selft` is
   **0.0003 V** at 1 µA/finger and 0.0004 V at 500 µA/finger. Breakdown scales
   with current *density*, not device size, in this card — so the `Nx` = 8
   design point inherits the `Nx` = 1 answer directly.

### Is this consistent with the process spec?

**Yes at the criteria that matter for the design, with one explicitly-stated
exception at the hot corner.**

- **At the 500 µA/finger criterion** (DR-0001's nominal operating current):
  the extracted `BVCEO` is **1.6126 – 1.9050 V** over the entire grid.
  **0 of 30** corner/temp/`Nx` combinations fall below the 1.4 V minimum, and
  **0 of 30** fall below the 1.6 V target. At this criterion the model is
  consistent with — in fact slightly better than — the process spec at *all
  three* temperatures.
- **At the 1 µA/finger criterion** (the most conservative reading): **2 of 30**
  combinations fall below the 1.4 V minimum — `bcs`/125 °C at `Nx` = 1 and at
  `Nx` = 8, both `selft` states, reaching **1.3310 V**, i.e. **0.069 V (4.9 %)
  below the 1.4 V spec minimum** — and **26 of 30** fall below the 1.6 V
  target. **The shortfall occurs only at +125 °C, and only on the `bcs`
  corner.** At −40 °C and 27 °C the grid minimum is above 1.4 V at every
  criterion.
- **The honest statement** is therefore: the model card's avalanche behaviour
  **brackets** the process-spec numbers rather than reproducing them, because
  the spec figure carries no current criterion. The spec's 1.4 V min / 1.6 V
  target corresponds to a criterion somewhere between 1 µA/finger and
  500 µA/finger at 27 °C. Read at the most conservative criterion and the
  hottest corner, the model is ~5 % below the spec minimum; read at the
  design's own operating current, it clears the 1.6 V *target* everywhere.
- **What this does NOT license.** The 1.6 V-everywhere result at 500 µA/finger
  is not grounds for relaxing DR-0001's 1.4 V budget. Per `CLAUDE.md`, agents
  do not relax a ratified spec to make results pass; and the 1 µA/finger
  reading is the one a conservative breakdown budget should use, because it is
  the first point at which the device sustains avalanche current at all.

### Margin against DR-0001's worst-case `V_CE`

DR-0001's worst-case device voltages are `V_CE1` = 1.097 V (`bcs`, +125 °C)
and `V_CE2` = 1.116 V (`wcs`, −40 °C), each held against the static
`BVCEO(min)` = 1.4 V for a stated ~20 % margin. Against the *extracted*
worst case:

| Device | Worst-case `V_CE` | vs. extracted `BVCEO` at its own corner/temp | Margin |
|---|---|---|---|
| `Q1` | 1.097 V (`bcs`/+125 °C) | 1.3310 V (`bcs`/125 °C, 1 µA/finger) | 0.234 V (**17.6 %**) |
| `Q1` | 1.097 V (`bcs`/+125 °C) | 1.6126 V (`bcs`/125 °C, 500 µA/finger) | 0.516 V (32.0 %) |
| `Q2` | 1.116 V (`wcs`/−40 °C) | 1.6954 V (`wcs`/−40 °C, 1 µA/finger) | 0.579 V (34.2 %) |

So DR-0001's ~20 % margin survives contact with the model's own avalanche
behaviour, but at the most conservative criterion it is **17.6 %, not 20.3 %**
— the extraction takes ~3 points off the stated margin at the hot corner, and
adds a large amount at the cold one. The budget is **not** invalidated; it is
now evidenced rather than assumed.

### BVCER / BVCES — the margin DR-0001 declined to spend

DR-0001 deliberately holds every device to the open-base `BVCEO`, noting that
`Q2`'s base is AC-grounded through a low impedance so its governing limit is
really `BVCER`/`BVCES`, and calling that "real additional margin" it does not
take credit for. This experiment quantifies it:

- **`RB` = 14 kΩ (loose end of the bracket, Bench A, 30 cells)** — the only
  finite termination at which the model *still* has an avalanche-sustained
  branch inside its own current-validity range. A sustaining branch is found
  in **21 of 30** cells, with sustaining voltage **2.0288 V**
  (`bcs`/125 °C/`Nx`=8) to 2.8405 V (`wcs`/27 °C/`Nx`=1); per temperature the
  minimum is 2.2376 V (−40 °C), 2.1704 V (27 °C), 2.0288 V (125 °C). At
  DR-0001's nominal 500 µA/finger the same locus sits at 2.1000–3.6700 V.
  **Even at this deliberately loose termination, breakdown is ≥ 2.03 V — a
  0.698 V (52 %) improvement on the worst-case open-base `BVCEO` of 1.3310 V
  at the same corner and temperature.**
- **`RB` = 1.4 kΩ (the nominal cascode-base Thevenin value, Bench A, 30
  cells)** — a sustained avalanche branch is found in only **4 of 30** cells.
  The locus is still descending through 3.03–102.6 V at the 500 µA/finger
  criterion and has not turned round by the top of the forced-current grid,
  which *is* the card's current-validity ceiling. **Within the range the card
  is valid over, this termination has no collector–emitter breakdown at all.**
- **`RB` = 140 Ω / short (BVCES, Bench A probes)** — **0 of 4** show a
  sustained branch: the same answer as 1.4 kΩ, more strongly.
- **Held-base leakage (Bench B, 60 cells, `RB` ∈ {1.4 kΩ, short})** —
  `I_C(V_CE)` is monotone in **60 of 60** cells (so the voltage-driven sweep
  is sound there), and the 1 µA/finger criterion is reached in **0 of 60**
  cells anywhere up to the 5.40 V ceiling — which is already past the card's
  `vbc_max = 5.1`. Worst-case leakage, at `bcs`/125 °C/`Nx`=1/`RB`=1.4 kΩ:
  **9.06e−11 A/finger at `V_CE` = 1.12 V**, 9.21e−11 A at 1.60 V, 9.33e−11 A
  at 2.00 V — i.e. sub-nanoamp per finger, sub-nanowatt, at DR-0001's
  worst-case cascode voltage.
- **Extended-ceiling probe (12.00 V, 15 cells, outside model validity)** —
  **0 of 15** reach 1 µA/finger; the largest current seen anywhere is
  6.14e−11 A/finger. The absence of a held-base runaway below 5.40 V is
  therefore not an artefact of where the primary sweep stops.

**Bottom line for DR-0001**: at the cascode base's actual DC Thevenin
impedance, `Q2` has **no collector–emitter breakdown mechanism within the
model card's validity range**. Its governing limit is the base–collector
junction (`vbc_max` = 5.1 V), not `BVCEO` — exactly as DR-0001 suspected. The
unspent margin is large: `Q2` operates at `V_CE` ≤ 1.116 V against a limit of
≥ 2.03 V even at a 10× looser base termination than the design's own.

Whether to **spend** that margin (a higher `VDD`, a different `α`) is a
decision-record question, not a simulation question. This experiment supplies
the number; it does not change the budget.

## What the model cannot tell us

Read these before quoting any number above.

1. **This is a model, not silicon.** Every figure here is a property of the
   committed VBIC card's weak-avalanche parameters (`avc1`, `avc2`) fitted to
   IHP's own measurement set. The card's header states the fit's measurement
   range: `vce : 0.4 – 2.0 V`, `vbe : 0.65 – 0.96 V`, `ic < 0.003·Nx A`,
   `T: −40 … +125 °C`. **`avc1`/`avc2` were not fitted against a breakdown
   measurement** — nothing in the PDK claims they were — so an extracted
   `BVCEO` is a *consequence* of a forward-operation fit, not a calibrated
   breakdown model. Agreement with the process-spec figure to within ~5 % is
   therefore a meaningful consistency check, not a verification of either
   number.
2. **Anything above `V_CE` = 2.0 V is outside the fit range.** The 14 kΩ
   sustaining voltages (2.03–2.84 V), the 5.40 V Bench B ceiling and the
   12 V extended probe are all extrapolations of the card beyond the range its
   authors validated. They are swept to answer *"does a runaway exist below
   the B-C limit?"* — a qualitative question — not to claim a breakdown
   voltage there. **No number above 2.0 V in this README is a claim about
   silicon.**
3. **Self-heating is bounded here, not modelled at the junction.** `selft=1`
   is active on the extraction cells and makes no material difference (above),
   but DR-0001 already notes that at a 125 °C ambient with `Nx`=8 the junction
   sits near 134 °C — past the card's own +125 °C validity ceiling. That
   caveat applies to the 125 °C rows here as it does everywhere else in
   `sim/`.
4. **No second-breakdown, no thermal runaway, no snapback-triggered
   destruction.** The VBIC card models weak avalanche multiplication only.
   Nothing here says the device *survives* any of these voltages, only where
   the model's own avalanche current becomes significant. Reliability limits
   (`vce_max = 1.6` on the card) are a separate, stricter constraint and
   remain the binding design rule.
5. **`sf`/`fs` are not independent corners.** They fall back to `hbt_typ`, so
   the grid has three distinct process points, not five. Counts of "N of 30
   cells" therefore over-weight `typ` 3:1:1.
6. **Partial cells are recorded, not discarded.** Several finite-`RB` Bench A
   cells converge on only ~46–58 of 61 points, and a few Bench B control cells
   truncate early. The truncation is itself data (it is *how* the naive method
   fails), so it is recorded as a partial cell with its converged-point count
   in the record and in the `n_converged` / `n_points` summary columns. A cell
   that produced no rows at all would be a hard failure; there were **none**
   in this record.

## Not a ratification

No row of `spec/target-spec.md` is ratified by anything here, and DR-0001's
decision is not reopened by anything here. This experiment is **evidence
input** to that record's breakdown budget — supplying, for the first time in
this repo, a committed testbench behind numbers the record previously had to
take from a datasheet. Per `sim/README.md`, everything under `records/`,
`corners/` and `netlist-snapshots/` is **append-only**: a re-run mints a new
`<record-id>` and never edits or deletes an existing one.

## Regeneration

```bash
export PDK_ROOT=/path/to/ihp-open-pdk   # parent dir containing ihp-sg13g2/
export PDK=ihp-sg13g2
sim/breakdown-extraction/run_breakdown_sweep.sh
```

Requires `ngspice` and `python3` on `PATH`. Does not require xschem, `klt`, or
an OSDI build step (`npn13G2` is a native ngspice VBIC level=9 model — see
`sim/pdk.json`). `PDK_ROOT`/`PDK` may be left unset if the PDK is installed
under one of the prefixes `sim/env.sh` checks. The run takes a few minutes and
mints a **new** `<record-id>`; the committed record is never overwritten.
