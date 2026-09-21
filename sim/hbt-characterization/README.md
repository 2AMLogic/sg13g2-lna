# hbt-characterization — `npn13G2` noise-optimum device characterization

Issue [#7](https://github.com/2AMLogic/sg13g2-lna/issues/7): the
`Voinigescu`-style device-sizing exercise `spec/target-spec.md`'s NF row
names as still outstanding ("Actual optimum-NF bias current density is a
`Voinigescu`-style device-sizing exercise still to be done against
`sg13g2_hbt_mod.lib`"), and the device-level input the still-open
bias/supply-topology decision record (`spec/target-spec.md` "Open topology
question") needs. **This experiment characterizes the bare `npn13G2`
device, not a matched LNA** — it is a *device-characterization* study, not
a circuit claim: no matching network, no inductive degeneration, no S11/S22
bench exists in this repo yet (blocked on the inductor-model gap, issue
#5 / `klayout-tools#1517`). Its numbers are **input** to a future
bias/supply-topology decision record and to a future matched-LNA design —
not a claim against any row of `spec/target-spec.md` (none are ratified),
and specifically **not comparable to the NF/Gain target-spec rows**, which
describe a matched circuit this repo has not designed yet.

## Records in this experiment

`sim/` is append-only (`sim/README.md`): a re-run mints a new `<record-id>`
and never edits an older one. Two records exist:

| Record | Grid | Issue |
|---|---|---|
| `20260910-200059-7da7038` | `Nx=1` over `{typ,bcs,wcs,sf,fs} × {−40,27,125} °C × V_CE {0.8,1.0,1.2,1.4} V`, **plus a single `Nx=8` spot check** at `typ`/27 °C/`V_CE`=1.0 V. 1586 rows, 61 cells. | [#7](https://github.com/2AMLogic/sg13g2-lna/issues/7) |
| **`20260918-203652-4293920`** (current) | `Nx ∈ {1,8}`, **each across the full** `{typ,bcs,wcs,sf,fs} × {−40,27,125} °C × V_CE {0.6,0.8,1.0,1.2,1.4} V` grid. 3898 rows, 150 cells. Adds model-card validity-box flagging per row and a per-point convergence gate. | [#21](https://github.com/2AMLogic/sg13g2-lna/issues/21) |
| **`20260921-124900-d6da30a`** (correction record, no new simulation) | The −40 °C / 125 °C NF cells of **both** records above, algebraically re-referenced to the fixed `T0=300.15 K` they claim (3638 rows, 140 cells; 27 °C cells are identity and stay in the source records). See the erratum in "Bench definitions" below. | [#25](https://github.com/2AMLogic/sg13g2-lna/issues/25) |

The second record exists because
`spec/decision-records/0001-bias-supply-topology.md` (DR-0001) recommended
`npn13G2` `Nx = 8` while resting on (a) that single `Nx=8` spot check with
all corner behaviour *inferred* from `Nx=1` corner deltas, and (b) a
worst-case `V_CE1` of 0.54 V that sits **below** the first record's 0.8 V
`V_CE` floor. DR-0001 named both gaps itself in its §"What is NOT evidenced
here". Every table below is regenerated from the **current** record;
the earlier record's files are untouched, and its `Nx=1` numbers are
reproduced bit-for-bit by the new run wherever the two grids overlap
(spot-checked: `typ`/27 °C and `wcs`/125 °C noise-optimum NF at
`V_CE ∈ {0.8,1.0,1.2,1.4}`, and the whole `Nx=8` spot-check cell).

The third row is a different kind of record: it is the **correction
record** for the source-temperature defect the `NF` bench definition
carried from day one (see the erratum in "Bench definitions" below) —
a deterministic re-derivation of the committed data, not a re-run, with
the derivation script committed beside it. Where this README's "Results"
section quotes a −40 °C or 125 °C NF number from
`20260918-203652-4293920`, the corrected citable value is the
corresponding row/block of `20260921-124900-d6da30a`.

## What is measured, and how (bench definitions)

Per `CLAUDE.md`: "NF and S-param numbers carry their bench definitions.
Port impedances, bias points, and the exact ngspice analysis ... are
committed beside every recorded number." Every point in the sweep runs
**two independent DUT branches** in the same generated netlist (see
`testbench/tb_hbt_sweep.spice.tmpl`'s header comment for the full circuit
description), sharing only the corner-lib model card:

### fT — short-circuit current-gain (h21) 0 dB crossing

- **Circuit**: base driven by an ideal DC+AC current source (`Ib2`, no RF
  port, no 50 Ω convention — h21 is a unitless, port-independent
  short-circuit current-gain figure by definition); collector tied
  directly to an ideal DC voltage source (zero AC impedance = ideal
  short). `Ib2`'s DC value is `alter`ed every point to match the other
  branch's own measured base current at that bias, so both branches sit at
  the same operating point.
- **Analysis**: `ac dec 20 1MEG 3000G` (a wide log sweep of
  `h21 = -i(Vce2)/Ib2_ac`, `Ib2_ac=1A`), then `meas ac ... WHEN h21db=0` —
  the standard short-circuit-current-gain fT definition (not the model's
  own `.op`-queried `ft`, which this VBIC build does not expose as a named
  op-info field — `gm`, `cbe`, `cbc`, `cbcx`, `cbep`, `cbcp` ARE exposed
  via `show <device>`/`@<device>[param]`, verified empirically, but no
  single `ft` field is; the `.ac`-swept crossing is the primary method the
  issue names, so this experiment did not build a secondary
  `gm/(2*pi*Ctotal)` estimator from those fields).
- **Below a 1 nA Ic floor**, h21 never crosses 0 dB in the swept range (the
  device is effectively off); fT is reported blank (`NA` in the raw
  per-point log, empty CSV cell) rather than a bogus stale value — see the
  testbench header's "ngspice cross-plot vector gotcha" note for why this
  check has to happen immediately after the operating-point read, before
  any other analysis in the same loop iteration runs.

### NF — 50 Ω-referenced noise figure at 2.4 GHz

- **Circuit**: base and collector each fed through an **ideal bias tee** —
  a DC source in series with a 1 H inductor (at 2.4 GHz, `2*pi*f*L ≈
  1.5e10 Ω`, an effectively open RF choke, zero DC drop). The base's RF
  port is AC-coupled through a 1 F "ideal DC block" capacitor (`1/(2*pi*f*C)
  ≈ 6.6e-11 Ω` at 2.4 GHz, effectively a short) to a 50 Ω Thevenin source
  (`Rs=50`, driven by an ideal `Vin`); the collector's RF port is
  identically AC-coupled to a 50 Ω load `RL`.
- **`Rs` is pinned at `temp=27` (300.15 K) regardless of the swept ambient
  corner** — the standard Friis/IEEE noise-figure convention of holding
  the *source* reference temperature fixed while only the DUT's own
  ambient corner varies (ngspice's per-instance `temp=` override on a
  resistor, confirmed to work independently of `.options temp`). `RL` is
  **not** pinned — it inherits the swept ambient corner, on the reasoning
  that it represents on-die/on-board hardware at the same physical
  temperature as the DUT, not an external reference. This is a modelling
  choice, stated explicitly per this file's own requirement — see "Model
  limitations" below for what it does and does not capture.
- **Analysis**: `noise v(out) vin lin 1 2.4G 2.4G`, then
  `NF_dB = 10*log10(inoise_spectrum^2 / (4*k*T0*Rs))`, `T0=300.15 K`,
  `Rs=50 Ω` — the standard formula for noise figure referenced to a fixed
  source temperature, using ngspice's own input-referred total noise
  density (`inoise_spectrum`, which already includes every noise source in
  the circuit, referred to the `Vin` port).

### Erratum (issue #25): the committed NF numbers are ambient-source-referenced away from 27 °C

**The parenthetical in the bench definition above — "per-instance `temp=`,
confirmed to work independently of `.options temp`" — is wrong.** In
ngspice-46 a resistor's per-instance `temp=` override reaches only the
*resistance value's* temperature coefficients; the device's **thermal-noise
source is computed at the analysis temperature** (`.options temp`)
regardless. The source resistor's own noise in every committed NF cell was
therefore at the swept **ambient** corner temperature — 233.15 K at the
−40 °C cells, 300.15 K at 27 °C, 398.15 K at 125 °C — not at the fixed
`T0 = 300.15 K` the formula normalizes by. This is measured, not inferred:
`sim/lna-characterization/testbench/tb_resistor_noise_temp_probe.spice`
(issue #18's tree) places identical 50 Ω resistors in one `.options
temp=54` analysis, one carrying `temp=27`, and reads `T_eff = 327.15 K`
for **both** (issue
[#25](https://github.com/2AMLogic/sg13g2-lna/issues/25); the same
convention gap is documented against an independent bench in
`sim/lna-characterization/README.md`'s "Noise figure" section).

**Consequence for the committed records** — `records/20260910-200059-7da7038`
and `records/20260918-203652-4293920`:

- **The 27 °C cells are correct as documented** (ambient = `T0` exactly).
- **The −40 °C and 125 °C cells are not**: they are NF referenced to a
  source at the swept ambient temperature, not to the stated fixed
  `T0 = 300.15 K` — a different figure of merit than the records claim.
  Direction: −40 °C cells read too *low*, 125 °C cells too *high*; the
  effect is largest exactly at the noise optima (up to ≈1.0 dB at the
  `Nx=8` `bcs`/125 °C optimum).
- The correction is an exact algebraic re-referencing of the same
  committed `inoise_spectrum` values — no re-simulation. It is landed as
  the append-only correction record
  **`20260921-124900-d6da30a`** (`records/20260921-124900-d6da30a.md`,
  generated by `rederive_nf_fixed_t0.py`), which carries the corrected
  per-point NF, per-cell optima, and provenance for every affected row of
  both records. **Cite the correction record's numbers — not the source
  records' `nf_db` column — for any `Nx`/corner/temp comparison involving a
  −40 °C or 125 °C cell.** Two statements change rank, not just value:
  the whole-grid best-NF cell at `Nx=8` moves to `bcs`/125 °C (0.96 dB,
  was 1.97 at `bcs`/−40 °C), and `Nx=8`'s worst-in-grid cell flips from
  `wcs`/125 °C to `wcs`/−40 °C (2.50 dB, was 2.86/1.90 respectively) —
  every other qualitative conclusion of this file survives (see the
  correction record's "Impact" note).

**Going forward**, no future NF bench in this tree should rely on the
per-instance `temp=` behaviour at all: new benches adopt
`sim/lna-characterization/`'s shape — declare `Rs`/`RL` `noisy=0` and
re-introduce the source term analytically at an explicit `T0` (that
testbench reports both 290 K and 300.15 K references) — so a bench's
reference temperature is a stated parameter of the algebra instead of a
simulator behaviour to be relied on (issue #25, suggested resolution 3).

### Gain — 50 Ω-terminated transducer gain at 2.4 GHz

- **Same 50 Ω-terminated branch** as the NF bench above (shares the
  circuit; NF and gain are read from the same operating point).
- **Analysis**: `ac lin 1 2.4G 2.4G` with `Vin` a 1 V open-circuit
  (Thevenin) source, `Rs=Zo=RL=50 Ω`: `S21 = 2*Vout/Vin`, reported as
  `Gain_dB = 20*log10(|S21|)`. This is the standard SPICE two-port S21
  extraction for a source/load both equal to the reference impedance
  (`target-spec.md`'s 50 Ω port convention) — **not** the strict IEEE
  "available power gain" `Ga` (which requires the source conjugately
  matched to the DUT's own `Zin*`), and **not** a matched-LNA gain number:
  this is a *bare, unmatched* common-emitter stage between two 50 Ω
  terminations, so the reported gain is characteristically low or even
  negative at low bias — see "Results" below.

### J_C — collector current density

`J_C = Ic / (Nx * AE_UNIT_UM2)`, `AE_UNIT_UM2 = 0.1152 um^2` (the
`npn13G2` subckt's own default single-finger geometry,
`le=0.96um * we=0.12um`, from `sg13g2_hbt_mod.lib`'s `.param` block), `Ic`
read from the 50 Ω-branch's own `.op` (`@q.xq1.qnpn13g2[ic]`). `J_C` is
**not** forced onto a pre-chosen target grid — it is the *measured* result
of sweeping the base voltage `Vbb` (a dense, evenly-spaced grid, not an
`Ib`-current-source target, for numerical robustness — see "Sweep grid
derivation" below), read off directly at each point, exactly like a
Gummel-plot-based characterization.

## Sweep grid

- **Base voltage `Vbb`**: 26 points, `0.55 V + i*0.02 V` for
  `i = 0..25` (0.55 V to 1.05 V), applied through the input bias tee.
- **`V_CE`**: `{0.6, 0.8, 1.0, 1.2, 1.4} V` — the top of this range (1.4 V)
  equals `npn13G2`'s `BVCEO` **minimum** spec (1.4–1.6 V, per
  `target-spec.md` source (2)); no swept point ever *exceeds* 1.4 V, so
  this sweep never asks the device to operate past its own minimum-spec
  breakdown voltage — noted explicitly per the issue's own requirement.
  The 0.6 V point was added by #21 so that DR-0001's cold/low-supply/`wcs`
  worst case (`V_CE1` = 0.540 V) is bracketed by measurement instead of
  extrapolated from a 0.8 V floor. 0.6 V is still inside the model card's
  own `vce : 0.4–2.0 V` validity range; **0.54 V itself is still not a
  swept point** — the remaining extrapolation distance is 0.06 V rather
  than the 0.26 V DR-0001 had to cover.
- **Corner grid**: `{typ, bcs, wcs, sf, fs}` × `{-40, 27, 125} °C` — see
  `sim/README.md`'s "Corner label convention" section for why these five
  labels map onto `cornerHBT.lib`'s three real sections
  (`hbt_typ`/`hbt_bcs`/`hbt_wcs`), with `sf`/`fs` both falling back to
  `hbt_typ`. `bcs`/`wcs` are this fleet's "best/worst-case speed" HBT
  labels, the direct analogue of `sg13g2-bandgap`'s `mos_ff`/`mos_ss` pair
  — read `wcs` as this experiment's `ss`-equivalent wherever
  `target-spec.md` names an `ss`-corner binding condition.
- **`Nx` (emitter multiplicity)**: `Nx ∈ {1, 8}` — `Nx=1` is the PDK's
  default single-finger emitter, `Nx=8` is the geometry DR-0001
  recommends. **Both run the full corner × temp × `V_CE` grid.** (Record
  `20260910-200059-7da7038` had `Nx=8` as a single `typ`/27 °C/`V_CE`=1.0 V
  spot check only; #21 promoted it to a full grid because the spot check's
  own headline finding — noise-optimum `J_C` moving ~3× between `Nx=1` and
  `Nx=8` — is exactly the kind of `Nx`-dependence that makes inferring
  `Nx=8` corner behaviour from `Nx=1` corner deltas unsafe.) `Nx=1..10` is
  the model card's stated valid range, so both values are inside it.
- **Grid size**: `2 Nx × 5 corner labels × 3 temps × 5 V_CE = 150` cells ×
  `26` `Vbe` points = `3900` attempted points, `3898` in the CSV (two
  points dropped by the convergence gate below), from `150` `ngspice -b`
  invocations (one per `Nx × corner_label × temp × V_CE` cell, each
  internally sweeping all 26 `Vbb` points via `alter`+`dowhile` — see
  `sg13g2-opamp/sim/gm-id-characterization/run_gmid_sweep.sh` for the
  precedent this render→simulate→parse shape follows).

### Model-card validity box (`validity_flags` column)

`sg13g2_hbt_mod.lib` states its own validity range, which DR-0001 treats as
a hard design boundary and whose `ic` limit is load-bearing in DR-0001's
`Nx=8`-vs-`Nx=1` argument:

```
* Valid range for model
* ic: <(0.003*Nx) A   vbe :(0.65 - 0.96) V   vce :(0.4 - 2.0) V
* Temp: -40°C - +125°C
* Valid numbers: NX = 1 - 10
```

The sweep deliberately runs **outside** that box at the top and bottom of
the `Vbb` grid (the box is narrower than the ≥2 decades of `J_C` the fT/NF
curves need to be resolved). From record `20260918-203652-4293920` onward,
every row of `records/<record-id>.csv` therefore carries a
`validity_flags` column — empty when the point is inside the box,
otherwise a `;`-joined subset of
`{ic_high, vbe_low, vbe_high, vce_low, vce_high}`. (The first record has no
such column; its rows can be classified after the fact with the same three
limits.) Every swept temperature (−40/27/125 °C) and every swept `Nx`
(1, 8) is inside the card's last two limits by construction, so no flag
exists for those, and the two `vce_*` flags never fire with the committed
`V_CE` grid — they exist so an extended grid cannot silently escape the
box. In the current record **2187 of 3898 rows are inside the box**
(`ic_high` 841, `vbe_high` 748, `vbe_low` 750; a row can carry more than
one flag).

`records/<record-id>-summary.csv` reports each cell's noise optimum and
fT peak **twice**: once over all converged points (the original columns,
schema-compatible with the first record) and once restricted to in-box
points (`in_box_*` columns, appended). Where this README quotes a single
number it says which.

> **Self-heating is not covered by the box check.** The card's
> −40…+125 °C limit is an *ambient* corner range; `selft=1` means the
> junction runs hotter than ambient at every point (DR-0001 computes
> ΔT_j ≈ 9 K at its own `Nx=8` bias, ~60 K at the `Nx=1` noise optimum).
> A row can therefore be flagged in-box and still sit past the card's
> temperature ceiling at the 125 °C corner. This is inherent to the corner
> set, applies equally to the first record, and is **not** encoded in
> `validity_flags`.

### Per-point convergence gate

At `Nx=8` the VBIC electrothermal loop runs away at the cold/best-case-speed
corner with the highest `V_CE`: in cell `nx8_bcs_-40c_vce1.4v` the operating
point diverges to NaN above `Vbe ≈ 1.01 V` (`I_C` > 50 mA into
`rth = 1747 K/W`). ngspice then **echoes a stale gain/NF value carried over
from the previous plot** — the exact cross-plot hazard the testbench header
warns about — so a naive parser would record a plausible-looking but bogus
row. `run_hbt_sweep.sh` therefore drops any point whose block contains an
ngspice operating-point-failure marker (`operating point failed`, `The
operating point could not be simulated successfully`, `Timestep too
small`), and the record's `## Partial cells` field names every cell that
lost points. In the current record that is **one cell, two points**
(`Vbe` = 1.03 and 1.05 V at `nx8_bcs_-40c_vce1.4v`) — both already flagged
`ic_high;vbe_high`, i.e. far outside the model's validity box.

The gate is deliberately *not* a blanket match on `Error:`: `Error: measure
ftmeas when(WHEN) : out of interval` is the benign "h21 never crosses 0 dB"
case, which already has its own handling (blank fT) and whose gain/NF are
valid.

### Sweep grid derivation (why `Vbb` ∈ [0.55, 1.05] V)

The base-voltage range was calibrated empirically before committing to the
production grid (not guessed): a preliminary scan at `typ`/27 °C/`V_CE=1 V`
found fT rising monotonically from ~5 GHz at `Vbe=0.70 V` to a peak of
~416 GHz near `Vbe=0.94 V` (`J_C≈21.4 mA/um²`), then rolling off to
~149 GHz by `Vbe=1.06 V` (`J_C≈54.7 mA/um²`, into self-heating-dominated
high injection). The committed `[0.55, 1.05] V` range comfortably brackets
this peak with several decades of `J_C` margin on the low side (satisfying
"sweep `J_C` over ≥2 decades around the expected fT peak") while staying
numerically well-behaved (`.dc`-style voltage sweeps are far better
conditioned near an exponential I-V turn-on than trying to target a
specific `Ic` via a blind `Ib`-current guess).

## Results

All numbers in this section are from record
**`20260918-203652-4293920`** unless a row explicitly says otherwise.

Full per-point data: `records/<record-id>.csv` (3898 rows: `point_id`,
`corner_label`, `hbt_section`, `temp_c`, `nx`, `vce_v`, `vbe_v`, `ic_a`,
`jc_ma_um2`, `ft_hz`, `gain_db`, `nf_db`, `validity_flags`).
Per-`(corner_label, temp, Nx, V_CE)` cell summary (noise-optimum
`J_C`/NF/gain/fT and fT-peak `J_C`/fT, each both unrestricted and
restricted to the validity box): `records/<record-id>-summary.csv`.

### Noise-optimum NF vs `V_CE`, `Nx=1` (unrestricted optimum)

"Unrestricted" = the minimum-NF point in the cell regardless of the
validity box. **In 71 of the 75 `Nx=1` cells that point is outside the
box** (`ic_high` and/or `vbe_high`) — see the in-box table below and
"Why `Nx=8` and not `Nx=1`".

| corner/T | `V_CE`=0.6 | 0.8 | 1.0 | 1.2 | 1.4 | spread |
|---|---|---|---|---|---|---|
| `typ`/−40 °C | 5.759 | 5.605 | 5.576 | 5.551 | 5.533 | 0.227 |
| `typ`/27 °C | 6.621 | 6.393 | 6.317 | 6.311 | 6.353 | 0.310 |
| `typ`/125 °C | 7.821 | 7.534 | 7.443 | 7.450 | 7.503 | 0.378 |
| `bcs`/−40 °C | 4.696 | 4.539 | 4.446 | **4.445** | 4.498 | 0.251 |
| `bcs`/27 °C | 5.559 | 5.320 | 5.244 | 5.261 | 5.315 | 0.316 |
| `bcs`/125 °C | 6.712 | 6.456 | 6.357 | 6.365 | 6.426 | 0.355 |
| `wcs`/−40 °C | 6.790 | 6.704 | 6.673 | 6.644 | 6.617 | 0.173 |
| `wcs`/27 °C | 7.629 | 7.432 | 7.371 | 7.379 | 7.398 | 0.258 |
| `wcs`/125 °C | 8.824 | 8.578 | **8.514** | 8.534 | 8.573 | 0.310 |

(`sf` and `fs` reproduce `typ` exactly — both map to `hbt_typ`, see "Sweep
grid". `target-spec.md`'s NF row names `ss`/125 °C as its expected binding
corner; `wcs` is this experiment's `ss`-equivalent label.)

**The `V_CE=0.6 V` column is the new information here.** Restricted to
`V_CE ∈ {0.8,1.0,1.2,1.4} V` this table's worst spread is **0.099 dB** —
which is the "≤0.10 dB" flatness figure DR-0001 §Evidence 3 quotes, now
independently reproduced. **Adding the 0.6 V point widens the worst spread
to 0.378 dB**: at `Nx=1`, `NF(0.6 V) − NF(0.8 V)` is **+0.086 to
+0.287 dB** (mean +0.213 dB) across the nine corner/temp cells. So the
`V_CE`-flatness argument DR-0001 extrapolated below 0.8 V does **not** hold
at `Nx=1` — it is off by roughly 3×. It does hold at `Nx=8` (next table),
which is the geometry DR-0001 actually recommends.

### Noise-optimum NF vs `V_CE`, `Nx=8` (unrestricted optimum)

New in this record — the first `Nx=8` corner data of any kind.

| corner/T | `V_CE`=0.6 | 0.8 | 1.0 | 1.2 | 1.4 | spread |
|---|---|---|---|---|---|---|
| `typ`/−40 °C | 1.544 | 1.553 | 1.559 | 1.566 | 1.576 | 0.031 |
| `typ`/27 °C | 1.884 | 1.897 | 1.905 | 1.913 | 1.925 | 0.041 |
| `typ`/125 °C | 2.395 | 2.410 | 2.420 | 2.431 | 2.446 | 0.052 |
| `bcs`/−40 °C | **1.246** | 1.256 | 1.266 | 1.277 | 1.284 | 0.038 |
| `bcs`/27 °C | 1.533 | 1.548 | 1.558 | 1.572 | 1.583 | 0.050 |
| `bcs`/125 °C | 1.972 | 1.991 | 2.003 | 2.018 | 2.038 | 0.066 |
| `wcs`/−40 °C | 1.880 | 1.886 | 1.891 | 1.894 | 1.899 | 0.019 |
| `wcs`/27 °C | 2.272 | 2.282 | 2.288 | 2.294 | 2.302 | 0.030 |
| `wcs`/125 °C | 2.853 | 2.866 | 2.873 | 2.882 | **2.893** | 0.040 |

At `Nx=8` the `V_CE` dependence is **weaker, monotonic, and of the opposite
sign**: the worst spread over the *full* 0.6–1.4 V range is 0.066 dB, and
`NF(0.6 V) − NF(0.8 V)` is **−0.019 to −0.006 dB** — lowering `V_CE` to
0.6 V is very slightly *better*, not worse. Nothing surprising happens at
the bottom of the range.

**Grid-wide extremes**:

| | `Nx=1` | `Nx=8` |
|---|---|---|
| Best NF anywhere (unrestricted) | 4.445 dB, `bcs`/−40 °C/1.2 V, `J_C`=60.93 (`I_C`=7.02 mA) — **outside the box** | 1.246 dB, `bcs`/−40 °C/0.6 V, `J_C`=28.75 (`I_C`=26.50 mA) — **outside the box** |
| Best NF anywhere, in box | 5.071 dB, `bcs`/−40 °C/1.4 V, `J_C`=20.52 (`I_C`=2.36 mA) | 1.273 dB, `bcs`/−40 °C/0.8 V, `J_C`=17.99 (`I_C`=16.58 mA) |
| Binding corner (`wcs`/125 °C), unrestricted | 8.513 dB at 1.0 V, `J_C`=40.74 (`I_C`=4.69 mA) — outside the box | 2.853 dB at 0.6 V, `J_C`=13.03 (`I_C`=12.01 mA) — **inside the box** |
| Binding corner, in box | 8.729 dB at 1.4 V, `J_C`=25.84 (`I_C`=2.98 mA) | 2.853 dB at 0.6 V (same point) |
| fT peak anywhere | 6.002e11 Hz, `bcs`/−40 °C/1.4 V, `J_C`≈20.5 | 6.283e11 Hz, `bcs`/−40 °C/1.4 V, `J_C`≈23.2 |
| Cells whose unrestricted optimum is outside the box | **71 / 75** | **20 / 75** |

The ~600 GHz corner fT figures are well above the process spec's *typical*
300–350 GHz — expected corner-driven upside at a best-case-speed, cold
corner, not a contradiction (a "target"/"min" spec row bounds the nominal
device, not a fast-corner ceiling).

**The noise-optimum `J_C` and the fT-peak `J_C` are NOT the same point**
anywhere in the grid, at either `Nx` — noise-optimum `J_C` sits roughly
2–3× higher than fT-peak `J_C` at `Nx=1` (e.g. `typ`/27 °C/1.0 V: 45.78 vs
19.11 mA/µm²). This is the expected `Voinigescu`-style result: minimum-NF
current density is set by a different tradeoff (base resistance / shot
noise vs. gm) than maximum-fT current density (transit-time-limited).

### `Nx=8` vs `Nx=1`

At the one cell both records share (`typ`/27 °C/`V_CE`=1.0 V) — the new
record reproduces the old one exactly:

| Nx | Noise-optimum J_C (mA/µm²) | NF (dB) | Gain (dB) | in box? | fT-peak J_C | fT peak (Hz) |
|---|---|---|---|---|---|---|
| 1 | 45.78 | 6.32 | 8.54 | no (`ic_high;vbe_high`) | 19.11 | 4.15e11 |
| 8 | 15.52 | **1.90** | 23.69 | **yes** | 20.12 | 4.38e11 |

With the full grid in hand, that advantage is now checkable at every
corner rather than inferred. In-box noise-optimum NF at `V_CE`=0.8 V:

| corner/T | `Nx=1` (dB) | `Nx=8` (dB) | Δ |
|---|---|---|---|
| `typ`/−40 °C | 6.369 | 1.576 | 4.79 |
| `typ`/27 °C | 6.731 | 1.897 | 4.83 |
| `typ`/125 °C | 7.766 | 2.410 | 5.36 |
| `bcs`/−40 °C | 5.182 | 1.273 | 3.91 |
| `bcs`/27 °C | 5.730 | 1.548 | 4.18 |
| `bcs`/125 °C | 6.992 | 1.991 | 5.00 |
| `wcs`/−40 °C | 7.492 | 1.911 | 5.58 |
| `wcs`/27 °C | 7.848 | 2.282 | 5.57 |
| `wcs`/125 °C | 8.750 | 2.866 | **5.88** |

`Nx=8` is better by **3.9–5.9 dB at every corner**, and the advantage
*grows* toward the binding corner. The `Nx=1` spot-check comparison
(4.4 dB at `typ`/27 °C) was, if anything, the *least* favourable cell in
the grid for `Nx=8`.

Three findings carried over and corrected from the first record's
spot check:

1. **`J_C` at a given `Vbe` is *approximately*, not exactly, `Nx`-invariant
   — and the first record's README overstated this.** The earlier text
   claimed the `jc_ma_um2` column "matches to the digit at every shared
   `Vbe` point"; re-reading the same committed data shows it drifts
   monotonically with bias, reaching **+6.9 %** (`Nx=8` higher) at the top
   of the `Vbe` grid even in that one `typ`/27 °C/`V_CE`=1.0 V cell. Over
   the full grid the deviation reaches **+19.7 %** (worst point overall)
   and **+12.9 %** restricted to in-box points. The cause is self-heating,
   not a scaling bug: `rth = 3260·(4/Nx)^0.9` K/W falls as `Nx^−0.9` while
   dissipation rises as `Nx`, so ΔT_j rises as `Nx^0.1` — the `Nx=8` device
   runs *hotter* at equal `J_C` and therefore draws more `I_C` at equal
   `Vbe`. **Practical impact is small** because `I_C` is exponential in
   `Vbe`: a +6.5 % `J_C` offset is ~1.6 mV of `Vbe` at ~60 mV/decade, which
   is exactly the −1.1…−1.5 mV discrepancy measured against DR-0001's
   `Nx=1`-interpolated `V_BE` table (see "What this means…" below).
2. **The fT-peak `J_C` is nearly `Nx`-invariant** (19.1 vs 20.1 mA/µm² at
   `typ`/27 °C/1.0 V, ~5 % apart — intrinsic transit-time physics), **but
   the noise-optimum `J_C` is not** (45.8 vs 15.5 mA/µm², ~3× apart). This
   traces to `npn13G2`'s own base-resistance scaling: `sg13g2_hbt_mod.lib`'s
   `rbx`/`rbi` scale roughly as `1/Nx`, so a larger device's excess
   base-resistance noise contribution falls faster with `Nx` than its signal
   gain does, pulling the noise-optimum bias point down in current density
   as the device gets bigger. A real, model-grounded effect, not a
   testbench artifact: **noise-optimum `J_C` is not a fixed number
   independent of device sizing**, so a design at a third `Nx` must
   re-derive it rather than rescale either table here.
3. **`Nx` also decides whether the noise optimum is even a legal bias
   point.** The `Nx=1` optimum is outside the model card's validity box in
   71 of 75 cells (`ic ≥ 3 mA` and/or `vbe > 0.96 V`); the `Nx=8` optimum
   is outside in 20 of 75, all of them cold cells where `vbe_high` binds.
   Any `Nx=1` design would be quoting an NF the model card does not
   warrant.

## Model limitations

- **Self-heating is always active.** `npn13G2`'s subckt default is
  `selft=1` (this experiment does not override it), so every operating
  point above already includes the VBIC thermal subcircuit's own
  electrothermal feedback — visible in the results as fT and gain both
  falling with temperature and with high bias current (self-heating adds
  to the ambient corner temperature at high `Ic`). This experiment did not
  attempt to isolate "electrical-only" behavior by disabling `selft`.
- **No matching network anywhere in this bench.** Both NF and Gain are
  bare 50 Ω-terminated numbers on an *unmatched* common-emitter stage — no
  inductive source degeneration, no simultaneous noise/power match. A real
  matched LNA at the noise-optimum bias point will show substantially
  better NF and gain than the numbers in this file; do not compare these
  numbers directly against `target-spec.md`'s NF/Gain rows, which describe
  a matched circuit.
- **`Rs` (the noise source) is held at a fixed 300.15 K regardless of the
  swept ambient corner; `RL` is not.** This is the standard Friis/IEEE
  convention for the source, but is a modelling choice for the load — see
  "NF" bench definition above.
- **Erratum: the "held at a fixed 300.15 K" claim above is false for the
  committed records' −40 °C and 125 °C cells** — ngspice computed `Rs`'s
  noise at the swept ambient temperature there, so those cells' NF is
  ambient-source-referenced, not `T0`-referenced. See the erratum in the
  "NF" bench definition and the correction record
  `20260921-124900-d6da30a` above (issue
  [#25](https://github.com/2AMLogic/sg13g2-lna/issues/25)); the 27 °C
  cells and every non-NF column are unaffected.
- **No inductor model exists in this PDK** (`porting-plan.md`, confirmed
  upstream at `IHP-Open-PDK#685`/`#1101`) — irrelevant to this specific
  bench (it uses only ideal L/C/R primitives, not the PDK's own inductor
  device), but it is why no matching-network bench exists yet at all.
- **Emitter geometry is swept only in `Nx`, and only at two values** —
  `we`/`le` (the per-finger drawn dimensions) are left at the subckt's own
  defaults throughout; only the finger-count multiplier `Nx ∈ {1, 8}` is
  varied. Finding 3 above means results may **not** be interpolated to an
  intermediate `Nx`: the noise-optimum `J_C` moves ~3× between these two
  values, so a third geometry needs its own run (one line of
  `HBT_NX_LIST`).
- **Mismatch/statistical corners are out of scope** — only the deterministic
  `cornerHBT.lib` sections are swept, not `_mismatch`/`_stat` variants.
- **Two bias points in the grid have no data at all** — `Vbe` = 1.03 and
  1.05 V at `nx8_bcs_-40c_vce1.4v`, dropped by the convergence gate. The
  electrothermal runaway that causes it is arguably a *real* device limit
  rather than a numerical artifact (ΔT_j > 180 K at that bias), but this
  bench makes no claim either way: the points are simply absent, and both
  are far outside the model card's validity box.
- **`V_CE` = 0.54 V — DR-0001's true worst case — is still not a measured
  point.** The grid floor is 0.6 V. The remaining 0.06 V of extrapolation
  is covered by a monotonic, ≤0.02 dB/0.2 V trend at `Nx=8` (see Results),
  but it is an extrapolation.

## What this means for the bias/supply-topology decision (input, not the decision)

This experiment answers the question `target-spec.md`'s "Open topology
question" and NF row both name as missing: **where, in `J_C`/`V_CE` space,
does this device's noise optimum actually sit, and how much `BVCEO`
headroom does that leave?**

The noise-optimum region across the whole PVT grid clusters at
**`J_C` ≈ 22–67 mA/µm² at `Nx=1`** and **≈ 11–29 mA/µm² at `Nx=8`** (the
~3× shift of Finding 2 above), and in both cases is **nearly flat across
`V_CE`**: the noise-optimum NF varies by ≤0.10 dB across 0.8–1.4 V at
`Nx=1`, ≤0.05 dB at `Nx=8`, and — once the new 0.6 V point is included —
≤0.38 dB at `Nx=1` and ≤0.07 dB at `Nx=8`. That flatness is the headline
finding for the topology question: **this device's noise optimum does not,
by itself, push a design toward either a cascode or a single low-voltage
stage** — the NF cost of biasing at a lower `V_CE` (more headroom against
`BVCEO`, more amenable to a lower-voltage single-stage topology) is small
compared to the NF cost of biasing at the wrong current density: at
`typ`/27 °C/`V_CE=1.0 V` (raw per-point data, not just the optimum), NF is
8.79 dB at `J_C=5.01 mA/µm²` and 6.32 dB at the noise-optimum
`J_C=45.78 mA/µm²` — a 2.47 dB swing from under-biasing by one decade in
current density, at *fixed* `V_CE`. In other words: **`J_C` selection
dominates the noise-optimum decision; `V_CE` selection is a much weaker
second-order lever**, at least for the bare device in isolation (a real
cascode's own headroom-vs-linearity/output-swing tradeoffs are a separate,
circuit-level question this device-only bench cannot answer).

The one place that second-order lever is *not* negligible is the
low-`V_CE` end at `Nx=1`, which only became visible when 0.6 V was added
to the grid: there the penalty reaches +0.29 dB relative to 0.8 V. At
`Nx=8` it does not appear at all. **`V_CE`-flatness is therefore an
`Nx`-dependent statement, and must be quoted with its `Nx`.**

At the noise-optimum `J_C`, `V_CE=1.4 V` (the top of this sweep, equal to
`BVCEO`'s spec minimum) shows **no NF or fT penalty** relative to
`V_CE=0.8–1.2 V` at any corner/temp — meaning a topology that can afford to
run this device right at `V_CE≈BVCEO_min` gains nothing in NF/fT for doing
so, only reduced headroom margin. Combined with the ≤0.2 dB `V_CE`
flatness above, this is evidence *for* choosing `V_CE` primarily on
headroom-margin and breakdown-safety grounds (not on a noise-optimum
tradeoff this data does not show), and *against* assuming a cascode is
noise-optimum-mandated by this device alone — the eventual topology
decision record should weigh cascode-vs-single-stage on linearity/output
swing/supply-rail-count grounds, informed by (but not determined by) the
noise-optimum-`J_C` table above.

### Does record `20260918-203652-4293920` change DR-0001's recommendation?

**No.** `spec/decision-records/0001-bias-supply-topology.md` recommends a
cascode of two `npn13G2` `Nx = 8` devices at `I_C` = 4.0 mA nominal on a
1.8 V rail with `V_B2 = (11/12)·VDD`. Every input of that recommendation
that #21 was opened to check survives contact with the new data, so **this
work produces no superseding decision record.** (Decision records are
append-only and never edited in place — had the data contradicted DR-0001,
the correct response would have been a new record `0002-…` superseding
0001, not an edit to 0001. It did not, so nothing under
`spec/decision-records/` is touched by #21 at all.) Point by point:

| DR-0001 input | What the new data says | Verdict |
|---|---|---|
| §Evidence 2: `Nx=8` beats `Nx=1` on NF (4.4 dB, one cell, `typ`/27 °C) | 3.9–5.9 dB in-box advantage at **every** corner/temp; the advantage *grows* toward the binding corner (5.88 dB at `wcs`/125 °C) | **Confirmed and strengthened** — the cited cell was the least favourable one in the grid |
| §Evidence 2: the `Nx=1` optimum is outside the model card's validity box, the `Nx=8` one is inside | `Nx=1` optimum is out of box in **71/75** cells; `Nx=8` in 20/75, all cold cells where `vbe_high` binds. At the recommended `I_C` = 4.0 mA, `Nx=8`, every bracketing row is in box at every corner | **Confirmed** |
| §"`V_BE(T, corner)` — from committed evidence": `V_BE2 ∈ [0.7539, 0.9152] V`, interpolated from **`Nx=1`** rows | Measured directly at `Nx=8` (`V_CE`=1.0 V, `I_C`=4.75 mA): **[0.7526, 0.9140] V**, spread 0.1614 V (DR-0001: 0.1613 V). Every cell differs by **−1.1 to −1.5 mV**. Measured d`V_BE`/d`T` at `typ`: **−0.83 mV/°C**, identical to DR-0001's | **Confirmed to ~1.5 mV** |
| §"Worst-case corner table" margins | Re-evaluated with the `Nx=8` table: `V_CE1,max` 1.097 → **1.099 V** (margin 0.303 → **0.301 V**, 21.5 %); `V_CE2,max` 1.116 → **1.115 V** (margin 0.284 → **0.285 V**, 20.3 %); `V_CE1,min` 0.540 → **0.541 V** | **Unchanged** — every margin moves by ≤1.5 mV, none changes sign or ranking |
| §Evidence 1: backing off from the device optimum to `I_C` = 4.0–4.75 mA costs 0.20–0.43 dB (one cell) | Across all nine `bcs`/`typ`/`wcs` × temp cells at `V_CE`=0.8 V: **+0.149 to +0.526 dB** vs the cell's in-box optimum. Worst-corner (`wcs`/125 °C) bare-device NF at `I_C`=4.0 mA is **3.157 dB**, gain 16.45 dB, fT 2.08e11 Hz | **Confirmed**, range slightly wider than the single-cell figure |
| §Evidence 4: nothing is fT-limited at any corner | fT at the recommended bias is ≥2.08e11 Hz at every corner — ~87× the 2.4 GHz band | **Confirmed** |
| §"What is NOT evidenced here": `V_CE1` = 0.54 V is below the grid floor; the ≤0.10 dB flatness is the basis for expecting no surprise | At `Nx=8`, `NF(0.6 V) − NF(0.8 V)` = **−0.019 to −0.006 dB** — monotonic, and 0.6 V is slightly *better*. No surprise at the low-`V_CE` end for the recommended geometry | **Confirmed** |

**One supporting argument was luckier than it looked, and should be
re-read.** DR-0001 quoted "spread ≤ 0.10 dB across the whole 0.8–1.4 V
`V_CE` range" from **`Nx=1`** data and used it to expect no surprise down
at 0.54 V. That 0.099 dB figure reproduces exactly — but **it does not
extend below 0.8 V at `Nx=1`**: adding the 0.6 V point widens the `Nx=1`
worst-case spread to 0.378 dB, and `NF(0.6) − NF(0.8)` is +0.086…+0.287 dB
there. The extrapolation happens to be sound only because the recommended
device is `Nx=8`, where the same quantity is ≤0.066 dB over the *full*
0.6–1.4 V range. So the conclusion stands, but the `V_CE`-flatness
argument should be cited as an **`Nx=8` result from this record**, not as a
general property of `npn13G2` carried over from the `Nx=1` table.

Two caveats attach to the confirmation rather than to the recommendation:

- DR-0001's `V_BE` derivation relied on "`J_C` at a given `V_BE` is
  `Nx`-invariant in this model, verified in that experiment's README". As
  Finding 1 above records, that invariance is only approximate (up to
  +19.7 % in `J_C` over the full grid; the first record's README overstated
  it). The derivation is nonetheless sound *in outcome*, because the
  exponential `I_C(V_BE)` compresses even a 6.5 % `J_C` error into ~1.6 mV
  of `V_BE` — which is precisely the discrepancy measured. Future work
  should use the direct `Nx=8` rows rather than repeat the inference.
- `V_CE` = 0.54 V itself is still extrapolated, from 0.6 V rather than from
  0.8 V.

Nothing here touches the parts of DR-0001 that this experiment structurally
cannot evidence — no breakdown extraction (still #20), no matched-circuit
S-parameter/NF/k-factor/IIP3 claim (still #17), and no ratification of any
`spec/target-spec.md` row.

## Model card / process-spec cross-check

`spec/target-spec.md` cites `npn13g2`'s process-spec `IC07` figure
(3.8 µA at `AE=0.07×0.9 µm²`, i.e. a *reference gain point*, not a
noise-optimum current density) and `fT` target/min of 350/300 GHz. This
experiment's own fT-peak figures (`typ`/27 °C: ~415 GHz at `Nx=1`,
~438 GHz at `Nx=8`; grid-wide best case `bcs`/−40 °C: ~600 GHz at `Nx=1`,
~628 GHz at `Nx=8`) are consistent with — and at the nominal corner,
somewhat above — those process-spec numbers, a reasonable outcome given
the process-spec figures are themselves nominal/typical, not a
corner-swept simulation result.

## Regeneration

```bash
export PDK_ROOT=/path/to/ihp-open-pdk   # parent dir containing ihp-sg13g2/
export PDK=ihp-sg13g2
sim/hbt-characterization/run_hbt_sweep.sh
```

~1.5 minutes wall clock for the full 150-cell grid on a 2026-era laptop.
No OSDI build step is needed (`npn13G2` is a native ngspice VBIC model —
see `sim/pdk.json`). Requires `ngspice` on `PATH`; does not require
`xschem` or `klt`. Produces a new `<record-id>` under `records/`,
`corners/`, and `netlist-snapshots/` — append-only, per `sim/README.md`;
re-running never edits an existing record.

Every grid axis is overridable from the environment (space-separated), so
an older record's narrower grid stays reproducible without editing the
script — e.g. record `20260910-200059-7da7038`'s `Nx=1` main grid:

```bash
HBT_VCES="0.8 1.0 1.2 1.4" HBT_NX_LIST="1" \
  sim/hbt-characterization/run_hbt_sweep.sh
```

`HBT_CORNERS`, `HBT_TEMPS`, `HBT_VCES` and `HBT_NX_LIST` default to the
full grid documented under "Sweep grid" above. A cut-down grid is useful
for iterating on the testbench; **only full-grid runs should be committed
as records**, since every table in this README is a whole-grid statement.
