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
- **`V_CE`**: `{0.8, 1.0, 1.2, 1.4} V` — the top of this range (1.4 V)
  equals `npn13G2`'s `BVCEO` **minimum** spec (1.4–1.6 V, per
  `target-spec.md` source (2)); no swept point ever *exceeds* 1.4 V, so
  this sweep never asks the device to operate past its own minimum-spec
  breakdown voltage — noted explicitly per the issue's own requirement.
- **Corner grid**: `{typ, bcs, wcs, sf, fs}` × `{-40, 27, 125} °C` — see
  `sim/README.md`'s "Corner label convention" section for why these five
  labels map onto `cornerHBT.lib`'s three real sections
  (`hbt_typ`/`hbt_bcs`/`hbt_wcs`), with `sf`/`fs` both falling back to
  `hbt_typ`. `bcs`/`wcs` are this fleet's "best/worst-case speed" HBT
  labels, the direct analogue of `sg13g2-bandgap`'s `mos_ff`/`mos_ss` pair
  — read `wcs` as this experiment's `ss`-equivalent wherever
  `target-spec.md` names an `ss`-corner binding condition.
- **`Nx` (emitter multiplicity)**: `Nx=1` (the PDK's default single-finger
  emitter) across the full grid above, plus a single **area-scaling spot
  check** at `Nx=8`, `typ`/27 °C/`V_CE=1.0 V` only (not a second full
  grid — issue #7's scope is "plus one larger emitter-area/multiplicity so
  area scaling is visible", a spot check, not a second sweep).
- **Grid size**: `5 corner labels × 3 temps × 4 V_CE × 26 Vbe points =
  1560` `Nx=1` points, `+ 26` `Nx=8` points `= 1586` total data rows, from
  `61` `ngspice -b` invocations (one per `corner_label × temp × V_CE × Nx`
  cell, each internally sweeping all 26 `Vbb` points via `alter`+`dowhile`
  — see `sg13g2-opamp/sim/gm-id-characterization/run_gmid_sweep.sh` for the
  precedent this render→simulate→parse shape follows).

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

Full per-point data: `records/<record-id>.csv` (1586 rows: `point_id`,
`corner_label`, `hbt_section`, `temp_c`, `nx`, `vce_v`, `vbe_v`, `ic_a`,
`jc_ma_um2`, `ft_hz`, `gain_db`, `nf_db`). Per-`(corner_label, temp, Nx,
V_CE)` cell summary (noise-optimum `J_C`/NF/gain/fT, and fT-peak
`J_C`/fT): `records/<record-id>-summary.csv`.

### Noise-optimum `J_C`, nominal corner (`typ`/27 °C, `Nx=1`)

| V_CE (V) | Noise-optimum J_C (mA/um²) | NF (dB) | Gain (dB) | fT at that point (Hz) |
|---|---|---|---|---|
| 0.8 | 37.85 | 6.39 | 8.11 | 3.25e11 |
| 1.0 | 45.78 | 6.32 | 8.54 | 3.16e11 |
| 1.2 | 55.14 | 6.31 | 8.86 | 2.77e11 |
| 1.4 | 51.69 | 6.35 | 8.74 | 3.12e11 |

### Noise-optimum `J_C`, binding corner (`wcs`/125 °C, `Nx=1`)

`target-spec.md`'s NF row names `ss process corner, 125 °C` as its expected
binding corner; `wcs` is this experiment's `ss`-equivalent label (see
"Sweep grid" above).

| V_CE (V) | Noise-optimum J_C (mA/um²) | NF (dB) | Gain (dB) | fT at that point (Hz) |
|---|---|---|---|---|
| 0.8 | 30.85 | 8.58 | 5.86 | 2.19e11 |
| 1.0 | 40.74 | **8.51** | 6.39 | 1.99e11 |
| 1.2 | 42.47 | 8.53 | 6.52 | 2.24e11 |
| 1.4 | 39.44 | 8.57 | 6.36 | 2.63e11 |

**Noise-optimum `J_C` and its NF, stated explicitly, across the whole
grid (`Nx=1`)**:

- **Best case anywhere in the grid**: `bcs`/−40 °C/`V_CE=1.2 V`,
  `J_C=60.93 mA/um²` → **NF=4.44 dB**, gain=11.21 dB, fT=3.58e11 Hz.
- **Worst case (the binding corner)**: `wcs`/125 °C/`V_CE=1.0 V`,
  `J_C=40.74 mA/um²` → **NF=8.51 dB**, gain=6.39 dB, fT=1.99e11 Hz.
- **fT peak anywhere in the grid**: `bcs`/−40 °C/`V_CE=1.4 V`,
  `J_C≈20.5 mA/um²` → fT=6.00e11 Hz (600 GHz) — a best-case-speed,
  cold-temperature corner result; well above the process spec's *typical*
  300–350 GHz fT figures, which is expected corner-driven upside, not a
  contradiction of the spec (a "target"/"min" spec row bounds the nominal
  device, not a fast-corner ceiling).
- **The noise-optimum `J_C` and the fT-peak `J_C` are NOT the same
  point** anywhere in the grid — noise-optimum `J_C` sits roughly
  **2–3× higher** than fT-peak `J_C` at every corner/temp/`V_CE`
  combination checked (e.g. `typ`/27 °C/`V_CE=1.0 V`: noise-optimum
  `J_C=45.78`, fT-peak `J_C=19.11 mA/um²`). This is the expected
  `Voinigescu`-style result: minimum-NF current density is set by a
  different tradeoff (base resistance / shot noise vs. gm) than
  maximum-fT current density (transit-time-limited), and the two do not
  coincide.

### Area-scaling spot check (`Nx=8` vs `Nx=1`, `typ`/27 °C/`V_CE=1.0 V`)

| Nx | Noise-optimum J_C (mA/um²) | NF (dB) | Gain (dB) | fT-peak J_C (mA/um²) | fT peak (Hz) |
|---|---|---|---|---|---|
| 1 | 45.78 | 6.32 | 8.54 | 19.11 | 4.15e11 |
| 8 | 15.52 | **1.90** | 23.69 | 20.11 | 4.38e11 |

Two findings:

1. **`J_C` at a given `Vbe` is identical between `Nx=1` and `Nx=8`** (the
   raw CSV's `jc_ma_um2` column matches to the digit at every shared `Vbe`
   point) — confirms the model scales `Ic` linearly with `Nx` at fixed
   bias, as expected for ideal multi-finger scaling.
2. **The fT-peak `J_C` is nearly `Nx`-invariant** (19.1 vs 20.1 mA/um²,
   ~5% apart — intrinsic transit-time physics, expected to be
   `Nx`-independent), **but the noise-optimum `J_C` is not**
   (45.8 vs 15.5 mA/um², ~3× apart). This traces to `npn13G2`'s own base
   resistance scaling — `sg13g2_hbt_mod.lib`'s `rbx`/`rbi` parameters scale
   roughly as `1/Nx`, so a larger device's *excess base-resistance noise*
   contribution (a significant NF term) falls faster with `Nx` than its
   signal gain does, pulling the noise-optimum bias point down in current
   density as the device gets bigger. This is a real, model-grounded
   effect, not a testbench artifact — flagged here because it directly
   matters to the future topology decision record: **noise-optimum `J_C`
   is not a fixed number independent of device sizing**, so a future
   matching-network design will need to re-derive it for whatever specific
   emitter geometry the topology decision settles on, not reuse this
   experiment's `Nx=1` table verbatim at a different `Nx`.

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
- **No inductor model exists in this PDK** (`porting-plan.md`, confirmed
  upstream at `IHP-Open-PDK#685`/`#1101`) — irrelevant to this specific
  bench (it uses only ideal L/C/R primitives, not the PDK's own inductor
  device), but it is why no matching-network bench exists yet at all.
- **Emitter geometry is not swept beyond the `Nx=1`/`Nx=8` spot check** —
  `we`/`le` (the per-finger drawn dimensions) are left at the subckt's own
  defaults throughout; only the finger-count multiplier `Nx` is varied.
- **Mismatch/statistical corners are out of scope** — only the deterministic
  `cornerHBT.lib` sections are swept, not `_mismatch`/`_stat` variants.

## What this means for the bias/supply-topology decision (input, not the decision)

This experiment answers the question `target-spec.md`'s "Open topology
question" and NF row both name as missing: **where, in `J_C`/`V_CE` space,
does this device's noise optimum actually sit, and how much `BVCEO`
headroom does that leave?**

The noise-optimum region across the whole PVT grid clusters at
**`J_C` ≈ 35–65 mA/um²**, essentially **flat across `V_CE`** (the
noise-optimum NF varies by well under 0.2 dB across the full 0.8–1.4 V
`V_CE` range at every corner/temp checked — see the per-corner tables
above). That flatness is the headline finding for the topology question:
**this device's noise optimum does not, by itself, push a design toward
either a cascode or a single low-voltage stage** — the NF cost of biasing
at a lower `V_CE` (more headroom against `BVCEO`, more amenable to a
lower-voltage single-stage topology) is small (≤0.2 dB) compared to the
NF cost of biasing at the wrong current density: at `typ`/27 °C/`V_CE=1.0
V` (raw per-point data, not just the optimum), NF is 8.79 dB at
`J_C=5.01 mA/um²` and 6.32 dB at the noise-optimum `J_C=45.78 mA/um²` — a
2.47 dB swing from under-biasing by one decade in current density, at
*fixed* `V_CE`. In other words: **`J_C` selection dominates the
noise-optimum decision; `V_CE` selection is a much weaker second-order
lever**, at least for the bare device in isolation (a real cascode's own
headroom-vs-linearity/output-swing tradeoffs are a separate, circuit-level
question this device-only bench cannot answer).

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

## Model card / process-spec cross-check

`spec/target-spec.md` cites `npn13g2`'s process-spec `IC07` figure
(3.8 µA at `AE=0.07×0.9 µm²`, i.e. a *reference gain point*, not a
noise-optimum current density) and `fT` target/min of 350/300 GHz. This
experiment's own fT-peak figures (`typ`/27 °C: ~415 GHz; grid-wide best
case `bcs`/−40 °C: ~600 GHz) are consistent with — and at the nominal
corner, somewhat above — those process-spec numbers, a reasonable outcome
given the process-spec figures are themselves nominal/typical, not a
corner-swept simulation result.

## Regeneration

```bash
export PDK_ROOT=/path/to/ihp-open-pdk   # parent dir containing ihp-sg13g2/
export PDK=ihp-sg13g2
sim/hbt-characterization/run_hbt_sweep.sh
```

No OSDI build step is needed (`npn13G2` is a native ngspice VBIC model —
see `sim/pdk.json`). Requires `ngspice` on `PATH`; does not require
`xschem` or `klt`. Produces a new `<record-id>` under `records/`,
`corners/`, and `netlist-snapshots/` — append-only, per `sim/README.md`;
re-running never edits an existing record.
