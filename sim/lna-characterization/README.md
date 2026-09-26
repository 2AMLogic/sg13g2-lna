# lna-characterization — circuit-level S-parameters, NF, stability and IIP3 of `design/lna.sch`

Issue [#18](https://github.com/2AMLogic/sg13g2-lna/issues/18): the first
**circuit-level** simulation campaign in this repo. Where
[`../hbt-characterization/`](../hbt-characterization/README.md) (issue #7)
characterized the bare `npn13G2` *device*, this experiment characterizes the
committed cascode LNA *circuit* — `design/lna.sch`, via its committed
netlist `design/netlist/lna.spice` (issue #17, PR #23) — at the 50 Ω port
convention `spec/target-spec.md` states, across a process × temperature ×
supply PVT grid.

**Nothing here is a conformance claim.** `spec/target-spec.md` is now
RATIFIED for the rows decision record
[0002](../../spec/decision-records/0002-target-spec-first-ratification.md)
marks RATIFIED (issue #19's ratification, PR #32) — DRAFT only for the
IIP3 numeric target and the stretch columns; this campaign is the
*evidence* that ratification used, not a pass/fail verdict against it. And
several of the numbers below fall short of their targets — see "Results"
and "What these numbers do and do not license" — which is why each
ratified row's note gates conformance verdicts on the #26/#27 re-runs
rather than on this campaign's numbers.

### Which DUT each record describes — read this before quoting any number

This directory holds **three** append-only records, and they characterize
**three different circuits**. A number quoted from the wrong one is a
statement about a design that no longer exists.

| Record | DUT sha256 (first 16) | The circuit it characterizes | Standing |
|---|---|---|---|
| `20260918-210908-4293920` | `79447449c494d601` | original cascode, **placeholder resistive base-bias divider** (issue #17 / PR #23) | **historical** |
| `20260921-131646-d6da30a` | `fd7c18ab8d4cea52` | `npn13G2` **mirror-reference** bias (PR #34) | **historical** |
| **`20260926-122301-088c734`** | **`23f9445b01dbec99`** | **DR-0003 flat-reference bias core** (issue #33 / PR #40, commit `e25df3b`) — current `main` | **current** |

The headline numbers, findings narrative and every figure quoted below are
from the **current** record unless a sentence explicitly names a historical
one. Re-baselined under issue
[#49](https://github.com/2AMLogic/sg13g2-lna/issues/49); the two historical
records are untouched (`../README.md` §"Append-only rule") and remain the
only valid source for statements about the DUTs *they* ran.

> **Headline conclusion, stated up front so it is not buried:** the DUT as
> committed has **no input or output matching network** — `Cin`/`Cout` are
> 100 pF DC blocks, not matching elements, and there is no base
> inductor. Its measured `S11 = −3.07 dB` and `S22 = −0.0044 dB` (nominal
> cell) are therefore not a *failed* match, they are the **absence** of
> one. Per `CLAUDE.md` ("Stability is a spec row … before any matching is
> declared final") and issue #18's own framing, **this result gates the
> matching network: the matching network is not done, and this bench says
> so numerically rather than by assertion.**
>
> **Second headline, new with the DR-0003 re-baseline and more consequential
> than the first:** `NFmin` — the noise figure this circuit would deliver
> under a *lossless, ideal* source-impedance noise match — is **2.0749 dB
> at the best of the 45 cells, 2.3817 dB at the nominal cell, 2.7275 dB at
> the worst**. Every one of those is **above** the RATIFIED `NF < 1.5 dB`
> row. A matching network can only move NF *down towards* `NFmin`, never
> below it, so **at this operating point the ratified NF row is not
> reachable by matching at all** — it is short by 0.575 dB even at the best
> cell, under an assumption (lossless match, infinite-Q passives) that is
> already optimistic. That is a measurement, not a verdict on the spec: the
> ratified value is untouched here, and what it implicates is the bias
> point and device sizing, not only issue #27's absent matching network.

## What is measured, and how (bench definitions)

Per `CLAUDE.md`: "NF and S-param numbers carry their bench definitions.
Port impedances, bias points, and the exact ngspice analysis (.sp/.noise)
are committed beside every recorded number." Everything in this section is
also written into the generated decks themselves
(`netlist-snapshots/<record-id>/*.spice`), so a committed number can never
be separated from the bench that produced it.

### The DUT, and how it gets into the deck

`design/netlist/lna.spice` is xschem's **flat** netlist of `design/lna.sch`
— its top-level `.subckt lna vdd vss rfin rfout` / `.ends` markers are
emitted as full-line comments (`**.subckt …`). `run_lna_sweep.sh`
uncomments exactly those two markers, drops the trailing `.end`, and
`r`-includes the result into each template at `@@LNA_SUBCKT@@`. **No device
line is altered.** The runner records `design/netlist/lna.spice`'s sha256 in
the record so a later reader can tell which schematic revision a number
belongs to, and the inlined `.subckt` is visible inside every committed
snapshot rather than being `.include`d from elsewhere.

Bias comes from the DUT's own on-chip network off a single ideal `VDD`
source — there is no external bias tee and no forced operating point. In
the current record that network is the **DR-0003 flat-reference core**
(`sg13_hv_pmos`/`sg13_hv_nmos` + `npn13G2`, issue #33 / PR #40), not the
`R1a`/`R1b` resistive divider the two historical records ran. The measured
operating point (`I_C1`, `I_C2`, `V_CE1`, `V_CE2`, `V_BE1`, `I_DD`, `P_dc`)
is echoed by every deck and lands in the summary CSV, so every
S-parameter/NF/IIP3 number below carries the bias point it was taken at.

Because the DUT now instantiates MOS devices, every deck additionally loads
`cornerMOShv.lib`'s section for the cell (`typ→mos_tt`, `bcs→mos_ff`,
`wcs→mos_ss`, `sf→mos_sf`, `fs→mos_fs` — `cornerMOShv` ships all five real
sections, so only the HBT side duplicates) and `pre_osdi`-loads the PSP103.6
OSDI models. That mapping is identical to
[`../lna-bias-pvt/run_biasop_sweep.sh`](../lna-bias-pvt/), so the two
benches describe the same 45 cells. Unlike the HBT-only pre-DR-0003 decks,
this bench therefore **requires** [`../tools/build-osdi.sh`](../tools/build-osdi.sh)
to have been run; the runner refuses to start without the `.osdi` binaries
rather than producing a partial record.

### S-parameters (S11, S21, S12, S22) — `sp` analysis, 50 Ω both ports

- **Circuit**: `Xa` in `testbench/tb_lna_sparam.spice.tmpl`, driven by
  ngspice's own `sp`-analysis port sources — independent voltage sources
  carrying `portnum 1 z0 50` / `portnum 2 z0 50`. This is exactly
  `spec/target-spec.md`'s "50 Ω reference impedance at both the input and
  output ports" convention, applied by ngspice's own two-port machinery
  rather than by a hand-rolled `2*Vout/Vin` extraction.
- **Analysis**: `sp lin 11 2.4e9 2.4835e9 1` — 11 points across the full
  2400–2483.5 MHz band (ratified by DR-0002). The trailing `1` is `sp`'s
  `donoise` flag
  (see NF below).
- **Reported**: |S11|, |S21|, |S12|, |S22| in dB and linear magnitude, per
  frequency point, per PVT cell, in `records/<record-id>-sparam.csv`; the
  raw *complex* S-parameters are in `corners/<record-id>/*.inband.dat`, so
  any derived quantity here can be re-derived independently.
- **Cross-check**: the `.noise` branch's independently-computed transducer
  gain (`Xb`, below) agrees with `|S21|²` to **0.0000 dB at all 45 cells**
  (the full precision the CSV records) — both are in the summary CSV
  (`gain_ac_db_at_band_lo`, `gain_ac_minus_s21_db`) precisely so the
  agreement is checkable, not asserted. Two different analyses (`sp` port
  sources vs. an `ac` sweep of a Thevenin-driven second DUT copy) landing on
  the same number is the evidence that the 50 Ω port convention is applied
  consistently in both.

### Noise figure — `.noise`, 50 Ω source, two stated reference temperatures

Two NF numbers are produced by two *independent* methods in the same deck.
They agree to **≤ 0.0001 dB at every 27 °C cell** — which is the only
temperature at which they are the *same quantity* (see the cross-check note
after the list):

1. **ngspice's own two-port NF** from the `sp` analysis above (`donoise`
   flag set), which references the analysis temperature. Reported as
   `nf_sp_db`, alongside **`NFmin`** — the noise figure this circuit would
   give under an *ideal* source-impedance noise match, which is the number
   that says how much of the NF gap is the missing input match rather than
   the device.
2. **A `.noise`-based NF** in a second, electrically isolated DUT copy
   (`Xb`), with its own ideal `VDD` source so the two branches cannot load
   each other at RF: a 50 Ω Thevenin source (`Rs`) and a 50 Ω load (`RL`),
   `noise v(nfout) vin lin 1 <f> <f>` at the band bottom, middle and top,
   with
   `NF_dB = 10*log10(1 + inoise_spectrum² / (4·k·T0·Rs))`.

**`Rs` and `RL` are declared `noisy=0`, and the source's thermal noise is
re-introduced analytically at a chosen `T0`.** This is a deliberate
methodology correction relative to `../hbt-characterization/`, stated here
per this tree's own rule that a modelling choice is written down rather than
inferred:

- ngspice-46's per-instance `temp=` on a resistor does **not** pin that
  resistor's *noise* temperature the way the earlier experiment's bench
  assumed. **This is measured, not asserted**:
  [`testbench/tb_resistor_noise_temp_probe.spice`](testbench/tb_resistor_noise_temp_probe.spice)
  is a standalone, PDK-free deck that puts two identical 50 Ω resistors —
  one carrying `temp=27`, one not — in the same `.options temp=54` analysis
  and backs out each one's effective noise temperature from its own measured
  `onoise_spectrum`. Both come out at **327.15 K**: the override is honoured
  for the resistance value's tempco, and ignored for the noise source.
  Computing the source term analytically removes that dependency entirely.
  (`../hbt-characterization/README.md` states the opposite behaviour as
  fact — "confirmed to work independently of `.options temp`". That record
  is append-only and is not edited here; the discrepancy, and what it means
  for that experiment's −40 °C/125 °C NF cells, is filed as
  [issue #25](https://github.com/2AMLogic/sg13g2-lna/issues/25).)
- The standard two-port noise-figure definition **excludes** the load
  resistor's own noise; making `RL` noiseless is not an approximation but
  the definition.
- Both reference temperatures are reported, per frequency: **`nf290`** (the
  IEEE/Friis `T0 = 290 K` convention, the number to compare against any
  datasheet or literature figure) and **`nf30015`** (`T0 = 300.15 K`, for
  continuity with `../hbt-characterization/`'s earlier records, which used
  that reference). They differ by ~0.05 dB; quoting one as the other is
  exactly the kind of silent bench drift this repo's rules exist to
  prevent.

**How to read the two methods' agreement (this is a result, not a caveat).**
On the current record `nf_sp_db` and `nf30015_db` match to **≤ 0.0001 dB
across all 15 cells at 27 °C**, and diverge by up to **0.50 dB at −40 °C**
and **0.66 dB at 125 °C**. That is not a discrepancy — it is the *expected*
signature of the two definitions, and it is why the analytic source term
exists:

| Cells | `nf_sp_db` references | `nf30015_db` references | max difference |
|---|---|---|---|
| 27 °C (15/45) | 300.15 K (= the analysis temperature) | 300.15 K (fixed) | **0.0001 dB** |
| −40 °C (15/45) | 233.15 K | 300.15 K (fixed) | 0.5029 dB |
| 125 °C (15/45) | 398.15 K | 300.15 K (fixed) | 0.6595 dB |

ngspice's own `sp` noise figure **references the analysis temperature**, so
away from 27 °C it is an *ambient*-referenced NF, not a `T0`-referenced one.
At the single temperature where the two definitions coincide they agree to
one part in 10⁴ — which validates both implementations — and everywhere else
the difference is an exact, predictable re-referencing. **`nf290` is the
number to quote**; `nf_sp_db` is the independent implementation check, not a
second opinion about the same quantity. This is the same trap
[issue #25](https://github.com/2AMLogic/sg13g2-lna/issues/25) describes in
the precedent bench, caught here because both numbers are committed side by
side instead of one being quietly chosen.

### Stability — k, μ and |Δ|, in-band **and** out-of-band

`CLAUDE.md`: "Stability is a spec row, not an afterthought: k-factor /
stability circles across the band, at PVT corners, before any matching is
declared final." `spec/target-spec.md`'s stability row asks for "k > 1 …
across band and out-of-band to at least 3× the upper band edge" at the
"worst-case process/temp/supply corner combination".

- **In-band**: k, μ and |Δ| are computed **inside the deck** from the same
  `sp` run as the S-parameters (not only in post-processing), at all 11
  in-band points, with the standard definitions:
  - `Δ = S11·S22 − S12·S21`
  - `k = (1 − |S11|² − |S22|² + |Δ|²) / (2·|S12·S21|)` (Rollett)
  - `μ = (1 − |S11|²) / (|S22 − S11*·Δ| + |S12·S21|)` (Edwards–Sinsky;
    `μ > 1` ⟺ unconditional stability, as a **single** sufficient *and*
    necessary test, and `μ` is additionally a *distance*: it is the radius
    of the largest load-reflection-coefficient disc centred on the Smith
    chart origin that contains no unstable termination)
- **Out-of-band**: a second `sp dec 40 1e7 3e10` sweep — **10 MHz to
  30 GHz**, i.e. 12× the upper band edge (the spec row asks for ≥ 3×,
  7.4505 GHz) and ~240× below the lower edge, at 40 points/decade
  (140 frequencies). k, μ, |Δ|, |S11|, |S21| and |S22| are written per
  frequency to `corners/<record-id>/*.stability.dat`.
- **Stability *circles* are not drawn as circles**, and that is deliberate:
  `μ` is the exact scalar equivalent of "does the input/output stability
  circle intersect the unit Smith chart" — it is the distance from the
  chart centre to the nearest unstable termination. Reporting `min μ` per
  cell over 140 frequencies is strictly more informative (and far more
  reviewable in a CSV) than 140 plotted circle pairs, and it is computed
  from the same raw complex S-parameters, which are committed if anyone
  wants the circles themselves.
- **Plus a condition-number-free red-flag check**: `max |S11|` and
  `max |S22|` over the broadband sweep, *with the other port terminated in
  its 50 Ω reference*. Either exceeding 1 means that port presents a
  negative real impedance under the reference termination — a direct
  oscillation warning that, unlike k, does not degrade numerically when both
  ports are nearly totally reflective (see next section).

#### Why k is ill-conditioned on this circuit (read before quoting a k number)

**Re-checked against the DR-0003 DUT (record `20260926-122301-088c734`) —
the conclusion survives, the illustrative numbers changed.** This section
rests on `|S12|` being tiny, which is a property of the bias point, not a
constant; it was re-derived rather than assumed when the core changed.

This DUT is a cascode with an almost purely *reactive* load (`Lc` to an
ideal `VDD`) and **no matching at either port**. The DR-0003 core loads the
input noticeably harder than the old divider did, so `|S11|` fell from
≈ 0.935 to **0.7026** — but `|S22| = 0.99949` is still essentially on the
unit circle and the cascode's reverse isolation is still excellent:
`|S12| = 1.670e-5` (**−95.54 dB**, worst cell −90.16 dB). In Rollett's k
both the numerator and the denominator are therefore still small (nominal
cell, 2.4 GHz):

```
numerator   = 1 − |S11|² − |S22|² + |Δ|²   =  1 − 0.49367 − 0.99898 + 0.49313 = 4.837e-4
denominator = 2·|S12·S21|                  =  2 · 1.670e-5 · 3.7869          = 1.265e-4
k = 3.8235   (the deck's own in-deck value: 3.824708)
```

so **k is still a ratio of two small quantities**, each assembled from
differences in the fourth decimal place of quantities that are themselves
≈ 1. What changed is the *sign* of the numerator: with `|S11|` off the unit
circle the cancellation is no longer near-total, so in-band k is now
comfortably positive (min **3.3899** over all 45 cells, was 0.346) instead
of straddling zero. Out of band it still swings hard — broadband
`k = −3.5301` at 50.1 MHz (bcs/125 °C/1.98 V) — because the same
cancellation returns wherever `|S11|` climbs back toward 1.

The conclusion is therefore unchanged: k is a real result but a *badly
conditioned* one, and quoting a k number as a robust margin — in either
direction, including the reassuring in-band 3.39 — would be dishonest. `μ`
does not have this problem (no small denominator; it is bounded and
continuous), which is why `μ` is reported alongside k everywhere and is the
number to reason from. The negative-resistance check above
(|S11|/|S22| > 1) is the third, independent view.

### `gmin` and the DR-0003 core — the one numeric solver override, and its measured cost

Both templates set **`.options gmin=1e-10`**. This is **not** ngspice-46's
default (the default is `1e-12`) and it is **not** what the two pre-DR-0003
records ran under — those decks carried no `gmin` override at all. It is
stated here, and in both deck headers, rather than left to be discovered in
a diff, because a solver override that is invisible is indistinguishable
from a silent numeric change.

**Why it is there.** The DR-0003 flat-reference bias core (PR #40) does not
converge without it at the coldest/lowest-rail cells. On the first
un-overridden re-baseline attempt, `bcs/−40 °C/1.62 V`, `sf/−40 °C/1.62 V`,
`sf/−40 °C/1.80 V` and `fs/−40 °C/1.62 V` all lost their operating point:
ngspice-46's dynamic gmin stepping, true gmin stepping, source stepping and
the transient-op fallback each failed in turn and the `op` aborted with
`Timestep too small`, taking the whole cell's `sp`/`.noise`/stability output
with it (and, with it, four cells of the 45-cell grid). The bias-network
change is what moved — the RF bench did not.

**What it costs, measured rather than asserted.** Re-running the *nominal*
cell (which converges either way) from its own committed snapshot, with and
without the override:

| Quantity | `gmin` default (1e-12) | `gmin = 1e-10` | relative move |
|---|---|---|---|
| `NFmin` @ 2.4 GHz | 2.38165037 dB | 2.38165216 dB | 7.5e-7 |
| `nf290` @ band lo | 2.65592 dB | 2.65592 dB | < 1e-6 |
| \|S21\| @ band lo | 11.5657 dB | 11.5657 dB | < 1e-6 |
| μ @ 2.4 GHz | 1.00035307 | 1.00035309 | 2e-8 |
| k @ 2.4 GHz (ill-conditioned) | 3.824535 | 3.824708 | **4.5e-5** |
| `I_C1` | 3.94032 mA | 3.94030 mA | 5e-6 |

Every recorded quantity moves in the **7th significant figure or beyond**.
The single largest relative move anywhere is `4.5e-5`, on Rollett's k —
exactly the quantity the section above documents as a ratio of two
nearly-cancelling fourth-decimal differences on this topology, so a
fifth-decimal sensitivity there is the expected behaviour of an
ill-conditioned metric, not evidence that `gmin` moved the circuit. `gmin`
is a conductance, not a noise source, so it introduces no noise term; at
`1e-10 S` it is 0.1 nA of leakage per junction per volt against a mA-scale
bias.

**Reproducing that table** needs no PDK corner knowledge — the two decks
differ by one `sed`:

```bash
R=20260926-122301-088c734
D=sim/lna-characterization/netlist-snapshots/$R/sp_typ_27c_vdd1.80v.spice
sed 's/ gmin=1e-10//' "$D" > /tmp/nogmin.sp     # the default-gmin twin
ngspice -b "$D" ; ngspice -b /tmp/nogmin.sp     # (retarget the wrdata paths first)
```

### IIP3 — two-tone transient, coherent FFT

`CLAUDE.md`: "IIP3 via two-tone transient with the tone spacing and FFT
parameters recorded; state the method's limits." All of the following is
written into every generated IIP3 deck's header as well as here.

- **Source**: two series `sin()` generators forming one Thevenin source
  behind `Rs = 50 Ω`, load `RL = 50 Ω` — the same 50 Ω port convention.
- **Tones** (both inside the band): `f1 = 2.44140625 GHz`,
  `f2 = 2.449035… GHz`, **tone spacing = 7.62939453125 MHz**. The measured
  IM3 products `2f1 − f2 = 2.43377… GHz` and `2f2 − f1 = 2.45667… GHz` are
  also in band.
- **FFT parameters**: uniform transient step **`tstep = 4 ps`**, `tstop`
  chosen so the FFT record is **`N = 65536` samples** (`ngspice` reports
  `zero padding: 0`), window **`none` (rectangular)**, giving bin
  resolution **`df = 1/(N·tstep) = 3.814697265625 MHz`**. `tstart = 1 µs` of
  transient is discarded before the window opens.
- **Coherence by construction**: every tone and every measured product is
  placed on an exact bin centre — `f1` = bin 640, `f2` = bin 642, IM3 at
  bins 638/644, IM5 at bins 636/646. With an integer number of cycles in the
  record, a rectangular window leaks nothing, so no window correction and no
  zero padding are applied (and none should be).
- **Two independent extractions per point**: ngspice's `fft`, and a direct
  coherent DFT (projection of the same linearized waveform onto cos/sin at
  each frequency over the same window), computed *before* `fft` switches the
  current plot. Both IIP3 numbers are in the CSV
  (`iip3_dbm`, `iip3_dbm_dft_crosscheck`); they agree to ≈0.01 dB.
- **Powers**: input is the **available** source power per tone,
  `A²/(8·Rs)`; output power per tone and per product is `V_peak²/(2·RL)`.
  `IIP3 = P_in + (P_out − P_IM3)/2`, the standard extrapolation.
- **Drive levels**: every PVT cell is run at **two** levels (1 mV and 2 mV
  peak open-circuit per tone), so the 3:1 IM3 slope the extrapolation
  assumes is *checked at every cell* (`im3_slope_2pt` in the summary CSV)
  rather than assumed at one. The nominal cell additionally runs 0.5 mV,
  4 mV and 8 mV, giving a 24 dB drive range at one cell.

#### Stated limits of this IIP3 method

1. **Extrapolation, not a measured intercept.** IIP3 is by definition an
   extrapolated quantity; it is meaningful only while IM3 rises 3:1 with
   drive. The committed `im3_slope_2pt` per cell (and the 5-level sweep at
   the nominal cell) is what establishes that — if a slope departs from 3,
   the corresponding IIP3 number must be discarded, not explained.
2. **Numerical noise floor.** The IM5 bins are measured purely as a floor
   sentinel. At the 1 mV drive the IM5 amplitude is ~5e-11 V and does *not*
   scale as the 5th power, i.e. those bins are at the transient solver's
   numerical floor, not a real 5th-order product. The IM3 bins sit ~45 dB
   above that floor at the lowest drive level, which is the margin that
   makes the IIP3 numbers trustworthy; the ratio is committed per point as
   `im3_over_im5_db`. **Do not push this bench to lower drive levels without
   re-checking that margin.**
3. **Harmonic-vs-intermod distinguishability**: with `df = 3.81 MHz` and a
   7.63 MHz tone spacing, the IM3 products land 2 bins from the tones and
   nothing else in the spectrum (harmonics at ~4.9/7.3 GHz, the tones
   themselves) falls within ±1 bin of a measured product, so no product is
   contaminated by a neighbour. The price of that clean separation is a
   *wide* tone spacing (7.6 MHz) relative to a real ISM-band two-tone test;
   narrowing it requires a proportionally longer record and is a
   wall-clock, not a methodology, limit.
4. **`tstep = 4 ps` ⇒ 125 GHz Nyquist**, ~51× the tone frequency, chosen so
   transient truncation error does not synthesize its own intermodulation.
   That, plus ngspice's default `reltol`, is what sets the floor in (2).
5. **Steady state is assumed after `tstart = 1 µs`.** The DUT's slowest
   pole is the 100 pF blocking capacitors into ~50 Ω–1 kΩ (ns-scale), so
   1 µs is ~3 orders of magnitude of margin; no envelope transient survives
   into the window. This is an argument, not a measurement — if the bias
   network ever gains a slow node (a real current mirror with a large
   bypass), `tstart` must be re-derived.
6. **Single-ended, single-tone-pair, in-band only.** No blocker test, no
   out-of-band IM, no AM-PM, no P1dB. Those are separate benches.

## PVT grid and corner scope

**Full grid, no reduction**: `{typ, bcs, wcs, sf, fs} × {−40, 27, 125} °C ×
{1.62, 1.80, 1.98} V = 45 cells`, and **both phases run at every cell** —
45 S-parameter/NF/stability decks and 90 two-tone IIP3 decks (2 drive levels
× 45 cells), plus 3 extra drive levels at the nominal cell = **138 `ngspice
-b` invocations** per record.

- **Process labels**: the five-label fleet convention mapped onto
  `cornerHBT.lib`'s **three** real sections — see
  [`../README.md`](../README.md) § "Corner-label convention": `typ→hbt_typ`,
  `bcs→hbt_bcs`, `wcs→hbt_wcs`, and `sf`/`fs` **both fall back to
  `hbt_typ`** because this PDK ships no skewed HBT section. **Read `wcs` as
  this repo's `ss`-equivalent** wherever `spec/target-spec.md` names an
  `ss`-corner binding condition, and read the `sf`/`fs` rows as *duplicates
  of `typ`*, not as independent corners: `spec/target-spec.md`'s S11/S22
  rows name "fs/sf process corners (L/C mismatch)" as their binding corner,
  and **this campaign cannot exercise that corner at all** — not merely
  because the HBT sections are missing, but because the L/C mismatch it
  refers to lives in passives that are *ideal* in this netlist (next
  section). That is a real coverage gap against the spec's exercisable
  corner box, recorded here rather than papered over.
  **On the MOS side the five labels are real**, since the DR-0003 core
  landed: `cornerMOShv.lib` ships all five sections, so
  `typ→mos_tt`, `bcs→mos_ff`, `wcs→mos_ss`, `sf→mos_sf`, `fs→mos_fs` map
  straight through. The `sf`/`fs` cells are therefore **no longer bit-identical
  to `typ`** on the current record the way they were on the two historical,
  HBT-only ones — they differ through the bias core's MOS devices while
  still sharing `typ`'s HBT section. The difference is real but *small*,
  because the DR-0003 reference is well regulated: across all nine
  (temp, VDD) pairs `I_C1` moves by ≤ 0.05 % between `typ`, `sf` and `fs`,
  and `NFmin` by ≤ 0.0001 dB. Do not read `sf`/`fs` as independent
  RF corners on the strength of that — they still carry `typ`'s HBT
  section, and the HBT is what sets the RF behaviour. The coverage gap
  above is unchanged: it is about the *passives*, which have no corner
  models at all.
- **Supply**: ±10 % around the 1.8 V nominal rail
  (`spec/decision-records/0001-bias-supply-topology.md`, status now
  **ratified** — its proposal made binding by decision record
  [0002](../../spec/decision-records/0002-target-spec-first-ratification.md)
  as the 1.80 V ± 10 % supply row). If that record's nominal changes, this
  axis changes with it.
- **Not covered**: passive corners (`cornerCAP.lib` and any inductor corner
  data) — the DUT's passives are ideal primitives with no corner models to
  sweep; mismatch/Monte-Carlo (`*_mismatch`/`*_stat` sections) — a separate
  campaign; and self-heating beyond what `npn13G2`'s own VBIC thermal
  network does at the stated ambient.

## Model limitations (what these numbers are NOT verified against)

1. **Every passive in the DUT is an ideal lumped primitive.** `Le = 1 nH`
   and `Lc = 5 nH` are generic SPICE `L` elements — **infinite Q, no
   series resistance, no substrate coupling, no self-resonance** — because
   SG13G2's open PDK ships **no simulatable SPICE/EM model for any on-chip
   inductor** (issue #5, upstream
   [`2AMLogic/klayout-tools#1519`](https://github.com/2AMLogic/klayout-tools/issues/1519),
   open). The 100 pF capacitors and the bias resistors are likewise generic
   ideal `C`/`R`, not `cap_cmim`/`rsil` PDK devices. **The only real PDK
   models in the DUT are the two `npn13G2` HBTs and — since the DR-0003
   core landed (PR #40) — the `sg13_hv_pmos`/`sg13_hv_nmos` devices of the
   flat-reference bias core.** Consequences, stated plainly:
   - **Gain is optimistic.** A real 5 nH load inductor at 2.44 GHz with
     Q ≈ 10 has ~7.7 Ω of series loss; the ideal one has none.
   - **NF is optimistic.** That same loss sits partly at the input (`Le`)
     and adds directly to NF; a real `Le` also shifts the optimum source
     impedance.
   - **S11/S22 are optimistic *and* mis-positioned**: a lossless reactive
     load puts |Γ| essentially on the unit circle (hence |S22| ≈ −0.004 dB),
     and finite Q both pulls it inward and moves the resonance.
   - **Stability is the most affected of all.** Inductor loss is a *damping*
     term; an infinite-Q model is the least stable case for the passive
     network and the most numerically degenerate case for k (see above).
   **No S11/S22/gain/NF/stability number in this tree is verified against
   silicon, or even against a physical passive model, until that gap
   closes.**
2. **`sf`/`fs` are not real HBT corners** in this PDK (above). On the two
   historical records that made 18 of the 45 cells numerically identical to
   their `typ` counterparts; on the current record they differ, but only
   through the DR-0003 core's MOS devices (≤ 0.05 % on `I_C1`,
   ≤ 0.0001 dB on `NFmin`) — the HBT that sets the RF behaviour is still
   `hbt_typ` in all three. They are committed as such, deliberately, rather
   than being silently dropped.
3. **Which bias network a record describes is a property of the record, not
   of this bench.** The two historical records characterize DUTs whose base
   bias came from a bare `V_BE`-referenced resistive divider
   (`20260918-210908-4293920`) and from an `npn13G2` mirror reference
   (`20260921-131646-d6da30a`). The current record
   (`20260926-122301-088c734`) characterizes the **DR-0003 flat-reference
   core** (PR #40). The measured `ic1_a`/`pdc_w` columns in each record's
   summary CSV are how you check a bias claim against the DUT that record
   actually ran — never across records.
4. **No layout, no parasitic extraction, no package/pad model.** Schematic
   netlist only.
5. **Noise**: only the devices' own VBIC noise sources plus the analytic
   source term. No 1/f corner validation (irrelevant at 2.4 GHz), no
   substrate/supply-coupled noise, ideal noiseless `VDD`.

## Results

See [`records/`](records/) for the append-only per-run records (three of
them — see "Which DUT each record describes" above). The current record's
headline numbers are reproduced in its own `records/<record-id>.md` and
summarized against the target-spec rows in
[`../../measurements/README.md`](../../measurements/README.md) — which is
the document to read for "what does this mean for the spec".

### Headline numbers — record `20260926-122301-088c734` (DR-0003 core)

45 of 45 cells completed; **no failed cells**. Nominal cell means
typ/27 °C/1.80 V.

| Quantity | Nominal | Worst of 45 | Best of 45 |
|---|---|---|---|
| in-band \|S21\| | 11.4604 … 11.5657 dB | **10.2748 dB** (wcs/125 °C/1.62 V) | 12.3539 dB (bcs/−40 °C/1.98 V) |
| in-band S11 | −3.0657 dB | **−2.9616 dB** (bcs/−40 °C/1.98 V) | −3.2227 dB (wcs/125 °C/1.62 V) |
| in-band S22 | −0.0044 dB | **−0.0033 dB** (bcs/−40 °C/1.98 V) | −0.0059 dB (wcs/125 °C/1.62 V) |
| `nf290` (worst in-band point per cell) | 2.6559 dB | **3.7759 dB** (wcs/125 °C/1.62 V) | 1.8432 dB (bcs/−40 °C/1.98 V) |
| **`NFmin`** @ 2.4 GHz | **2.3817 dB** | **2.7275 dB** (wcs/125 °C/1.62 V) | **2.0749 dB** (bcs/−40 °C/1.98 V) |
| in-band μ (min) | 1.000353 | **1.000275** (bcs/125 °C/1.98 V) | 1.000404 (wcs/125 °C/1.98 V) |
| in-band k (min) | 3.824708 | **3.389937** (wcs/125 °C/1.98 V) | — |
| broadband μ (min, 10 MHz–30 GHz) | 0.999997 | **0.99999592** at 595.7 MHz (bcs/−40 °C/1.98 V) | — |
| broadband k (min) | −2.792214 | **−3.530083** at 50.1 MHz (bcs/125 °C/1.98 V) | — |
| max \|S11\| broadband | 0.813574 | **0.817548** at 10 MHz (bcs/125 °C/1.62 V) | — |
| max \|S22\| broadband | 1.0000000 | **1.00000018** at 188.4 MHz (bcs/125 °C/1.98 V) | — |
| IIP3 (2 mV/tone) | −1.4171 dBm | **−2.3219 dBm** (wcs/−40 °C/1.62 V) | +0.4979 dBm (bcs/125 °C/1.98 V) |
| `I_C1` | 3.9403 mA | **4.1511 mA** (bcs/−40 °C/1.98 V) | 3.6573 mA (wcs/125 °C/1.62 V) |
| `P_dc` | 8.4860 mW | **9.7683 mW** (bcs/125 °C/1.98 V) | 7.1866 mW (wcs/125 °C/1.62 V) |

### The three questions this re-baseline was run to answer

**1. Is the ratified `NF < 1.5 dB` row still reachable under an ideal noise
match? No — not at this operating point.** `NFmin` is the floor a lossless,
ideal source-impedance transformation would reach, and on this DUT it is
**2.0749 dB at the best cell** (bcs/−40 °C/1.98 V), **2.3817 dB nominal**,
**2.7275 dB at the worst cell**. That is **0.575 / 0.882 / 1.228 dB above
the ratified 1.5 dB bar** respectively, and **0 of 45 cells** have
`NFmin < 1.5 dB`. Since no passive matching network can take NF *below*
`NFmin` — and a real, finite-Q one lands above it — the NF row cannot be
met by matching alone here. The historical `20260918…` record's argument
("~1.1 dB of the present NF is the absent noise match", `NFmin` 0.600 dB
best / 0.751 dB nominal) was an argument **about a different circuit** and
does not transfer. Two secondary facts make the same point from the other
side: the nominal `nf290 − NFmin` gap is now only **0.274 dB** (was
~1.1 dB) — i.e. the DR-0003 core already sits close to its own noise
optimum, so there is very little left for a matching network to recover —
and `nf290` itself is **2.6559 dB nominal**, 1.16 dB over the bar. **This
is a measurement, not a spec verdict**: nothing ratified is touched here,
and the row's reachability is now a bias-point/device-sizing question as
much as a matching question (#27).

**2. Does the in-band μ < 1 residue persist? No — it is retired.**
**0 of 45 cells** have in-band μ < 1 (worst **1.000275**, bcs/125 °C/
1.98 V), and in-band k is now positive everywhere (min 3.3899). On the
`20260918…` record it was 40 of 45. **The broadband residue does persist**:
45 of 45 cells dip below 1 somewhere in 10 MHz–30 GHz, minimum
**0.99999592** (−4.1 ppm) at 595.7 MHz, bcs/−40 °C/1.98 V. The amplifier is
still *conditionally*, not unconditionally, stable by the ratified
metric — the failure has simply moved entirely out of band.

**3. Does the `|S22| > 1` residue persist? Yes, at raw precision — and the
"0 of 45" reading is a rounding artefact, stated here rather than
inherited.** The summary CSV records `s22_mag_broadband_max` to six
decimals, which rounds this record's maximum to `1.000000`; counting from
that column gives "0 of 45". Counting from the raw 140-frequency
`corners/*.stability.dat` tables instead gives **45 of 45 cells with
\|S22\| > 1, maximum 1.00000018 (+0.18 ppm)** at 188.4 MHz,
bcs/125 °C/1.98 V. For comparison, re-counted the same way: the
`20260918…` record is 31 of 45 at +3.71 ppm and the `20260921…` record is
45 of 45 at +0.17 ppm. So the residue **shrank ~20× in magnitude** versus
the original record and did **not** disappear. At 0.18 ppm it remains
indistinguishable from the numerical resolution of a lossless port, so
issue #27's disposition is unchanged: re-check once a *lossy* inductor
model exists, do not dismiss.

Per-artifact layout of a record `<record-id>`:

| Path | Content |
|---|---|
| `records/<record-id>.md` | human-readable record: bench definitions, PVT grid, PDK/ngspice versions, DUT sha256, headline numbers |
| `records/<record-id>-sparam.csv` | one row per (PVT cell × in-band frequency): S11/S21/S12/S22 (dB and linear), k, μ, \|Δ\|, NF, NFmin |
| `records/<record-id>-iip3.csv` | one row per (PVT cell × drive level): P_in, P_out, P_IM3, gain, IIP3, OIP3, DFT cross-check, IM3/IM5 margin, FFT parameters |
| `records/<record-id>-summary.csv` | one row per PVT cell: operating point, worst-case in-band S-params/NF, in-band and broadband k/μ/\|Δ\| minima with the frequency each occurs at, negative-resistance check, IIP3 at both drive levels, IM3 slope |
| `netlist-snapshots/<record-id>/*.spice` | the exact generated deck for every point |
| `corners/<record-id>/*.log` | raw `ngspice -b` output for every point |
| `corners/<record-id>/*.inband.dat` | raw complex in-band S-parameters + k/μ/\|Δ\|/NF/NFmin |
| `corners/<record-id>/*.stability.dat` | raw broadband k/μ/\|Δ\|/\|S11\|/\|S21\|/\|S22\|, 140 frequencies |

## Regenerating

```bash
export PDK_ROOT=/path/to/ihp-open-pdk   # parent dir containing ihp-sg13g2/
export PDK=ihp-sg13g2
sim/lna-characterization/run_lna_sweep.sh
```

Requires `ngspice` (≥ 46), `python3`, **and the OSDI device models** — build
or check them with [`../tools/build-osdi.sh`](../tools/build-osdi.sh) (see
[`../README.md`](../README.md) §"OSDI device models"). The OSDI requirement
is new as of the DR-0003 core: `npn13G2` is still a native ngspice VBIC
model needing no compile step, but the committed DUT now also instantiates
`sg13_hv_pmos`/`sg13_hv_nmos` (PSP103.6 via OSDI), so both `cornerMOShv.lib`
and the `.osdi` binaries must be present or the runner refuses to start.
Still **no** xschem and no `klt`. A full run is 138 `ngspice -b`
invocations; `LNA_SWEEP_JOBS=<n>` sets how many run concurrently (default
`min(6, ncpu/3)`). Each point writes only its own files, so the numbers are
identical at any concurrency — set `LNA_SWEEP_JOBS=1` to prove it (record
`20260926-122301-088c734` was run that way, on a shared host).

Each run mints a **new** `<record-id>` (`<UTC date>-<UTC time>-<short git
sha>`); nothing under an existing `records/`, `corners/` or
`netlist-snapshots/` is ever edited or deleted (`../README.md` §"Append-only
rule").

**Plumbing check without a full campaign**: `LNA_SWEEP_SMOKE=1
sim/lna-characterization/run_lna_sweep.sh` runs the identical flow over the
single nominal cell in ~1 min (measured 58 s on the host that produced
the current record). A smoke record is a real record but is *not* a
PVT campaign — do not commit one as evidence.

**Re-deriving the CSVs from the committed raw logs alone** (no ngspice, no
PDK install needed) — this is how a reviewer checks that the committed CSVs
really are what the committed logs say:

```bash
sim/lna-characterization/parse_lna_sweep.py \
  --corners-dir sim/lna-characterization/corners/<record-id> \
  --sparam-csv /tmp/check-sparam.csv \
  --iip3-csv   /tmp/check-iip3.csv \
  --summary-csv /tmp/check-summary.csv
diff /tmp/check-summary.csv sim/lna-characterization/records/<record-id>-summary.csv
```

## What these numbers do and do not license

**Do**: treat the current record as the evidence base for any statement
about the DUT on `main`; use `NFmin` and the measured operating point to
size the *missing* input matching network — and to argue about whether the
ratified NF row is reachable at this bias point at all (it is not, see
"The three questions" above); use the broadband μ/|S11|/|S22| data as the
stability baseline any future matching network must be re-checked against.

**Do not**: quote any number here as "meets spec" (the as-committed DUT
predates the #27 matching re-run the ratified rows' notes gate conformance
on, and ideal passives bound what these numbers mean); quote
gain/NF/S11/S22 as achievable silicon performance (ideal
passives, §Model limitations); declare the matching network final (there
isn't one, and stability has not been shown unconditional); quote k
without μ beside it (§Why k is ill-conditioned); mix numbers **across**
records (§Which DUT each record describes — the three records are three
different circuits); or read a `|S22| > 1` / μ count off the summary CSV
without checking the raw `*.stability.dat` tables, whose ppm-scale residues
the CSV's six-decimal columns round away.
