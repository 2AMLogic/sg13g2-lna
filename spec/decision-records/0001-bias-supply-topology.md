# 0001: LNA bias/supply topology and supply voltage

- **Status**: proposed
- **Date**: 2026-09-16
- **Decided by**: Builder (Loom), issue #16
- **Issue**: [#16](https://github.com/2AMLogic/sg13g2-lna/issues/16)
  (sub-issue of the T1 gap tracker [#4](https://github.com/2AMLogic/sg13g2-lna/issues/4))

**This record is `proposed`, not `ratified`.** It does **not** ratify
`spec/target-spec.md`'s Supply or Power rows, or any other row. Ratification
of those rows is a separate, later PR through this fleet's two-key (EE-key +
market-key) protocol; this record is the evidence base such a PR would cite.
`spec/target-spec.md` remains DRAFT in its entirety.

## Context

`spec/target-spec.md` §"Open topology question this table does not resolve"
leaves the bias/supply topology undecided, and its Supply row is a
placeholder ("TBD — bounded by `npn13g2`'s BVCEO (1.4 V min / 1.6 V target);
range 1.2–3.3 V") rather than a number. The Power row depends on it. The
schematic sub-issue (#17) cannot be drawn until this is settled.

The forcing constraint is that `npn13G2`'s breakdown voltage is *lower than
this fleet's usual supply rails*. Three independent, independently checkable
statements of that limit:

| Source | Statement |
|---|---|
| `SG13G2_os_process_spec.pdf` Rev. 1.2 §3.1 (via `spec/target-spec.md` Src (2)) | `npn13g2` **BVCEO: target 1.6 V, min 1.4 V** |
| `ihp-sg13g2/libs.tech/ngspice/models/sg13g2_hbt_mod.lib` header comment | `* Maximum collector-to-emitter voltage: 1.6` |
| same file, `.model npn13G2_NX_vbic npn` card | `vce_max = 1.6`, `vbe_max = 1.6`, `vbc_max = 5.1` |

The same model card also states its own validity box, which this record
treats as a hard design boundary:

```
* Valid range for model
* ic: <(0.003*Nx) A   vbe :(0.65 - 0.96) V   vce :(0.4 - 2.0) V
* Temp: -40°C - +125°C
* Valid numbers: NX = 1 - 10
```

A 3.3 V rail across one device is 2.4× BVCEO(min); split across two stacked
devices it is still 1.65 V each — above both BVCEO(min) **and** the model
card's own `vce_max`. So the supply cannot simply be inherited from
`sg13g2-bandgap`/`sg13g2-ldo`; it has to be derived from the breakdown
budget. That derivation is this record.

## Decision

**Topology: cascode.** A common-emitter input device `Q1` with inductive
emitter degeneration, stacked under a common-base cascode device `Q2` whose
base is AC-grounded through a bypass capacitor, with an inductive (tuned)
collector load. Both devices `npn13G2`, `Nx = 8`.

**Supply: a single 1.8 V rail**, nominal, with the ±10 % supply corner set
`spec/target-spec.md` §"Verification corners" already specifies
(**1.62 / 1.80 / 1.98 V**).

**Bias plan** (the numbers design work may lock to):

| Quantity | Value | Set by |
|---|---|---|
| `VDD` | 1.80 V ±10 % | supply |
| `I_C` (both devices) | **4.0 mA** nominal; bias network must hold `I_C ≤ 4.5 mA` over all corners | bias current source |
| Device geometry | `npn13G2`, `Nx = 8` (`A_E = 8 × 0.1152 µm²`), `J_C ≈ 4.3 mA/µm²` at nominal | device sizing |
| `V_B2` (cascode base) | **`V_B2 = α·VDD`, `α = 11/12 = 0.9167`** (an 11:1 resistive divider off `VDD`, RF-bypassed), NOT an absolute reference | bias network |
| `V_CE1` nominal | 0.80 V | `α·VDD − V_BE2` |
| `V_CE2` nominal | 1.00 V | `VDD − V_CE1` |
| `P_dc` nominal | 7.2 mW (core), ≤ 9.4 mW worst case incl. bias overhead | `VDD × I_C` |

The single load-bearing subtlety is that **`V_B2` is derived from `VDD` by a
ratio, not from an absolute (e.g. bandgap) reference.** That choice is what
splits supply tolerance between the two devices instead of dumping all of it
onto `Q2`, and it is what keeps `Q2`'s base–collector junction reverse-biased
at every supply value (see below). A fixed-`V_B2` variant of the same
topology was evaluated and is worse; see "Alternatives considered".

## Breakdown-voltage budget

### Design rule

Every device's **`V_CE` ≤ BVCEO(min) = 1.4 V at every corner**, using the
process-spec *minimum*, never the 1.6 V target. No credit is taken for the
fact that `Q2`'s base is AC-grounded through a low impedance (where the
governing limit is BVCER/BVCES, approaching the `vbc_max = 5.1` B-C limit,
rather than the open-base BVCEO) — that is real additional margin, but this
repo has no committed testbench extracting it, so it is **not** spent here.
See "Consequences" for the follow-up that would quantify it.

### DC network equations

With the emitter of `Q1` at ground through the degeneration inductor and the
collector of `Q2` at `VDD` through the load inductor:

```
V_CE1 = V_B2 − V_BE2 = α·VDD − V_BE2
V_CE2 = VDD − V_CE1  = (1 − α)·VDD + V_BE2
V_BC2 = V_B2 − VDD   = (α − 1)·VDD          [< 0 for all VDD, since α < 1]
```

Both inductors' series resistance is taken as **0 Ω**, which is the
conservative direction for breakdown: the degeneration inductor's DC drop
(`I_C·R_LE ≤ 12 mV` for `R_LE ≤ 3 Ω` at 4 mA) can only *reduce* `V_CE1`, and
the load inductor's DC drop can only *reduce* `V_CE2`. No inductor model
exists in this PDK (issue #5), so no value is assumed beyond that bound.

`V_BC2 < 0` unconditionally is a structural property of the ratio-derived
`V_B2`: **`Q2` cannot saturate at any supply voltage or temperature**, which
is what makes the low-supply end of the tolerance box safe without spending
breakdown margin at the high end.

### `V_BE(T, corner)` — from committed evidence, not a textbook TC

The budget needs `V_BE2` over PVT at the operating current density. Taken
from `sim/hbt-characterization/records/20260910-200059-7da7038.csv`
(`Nx=1`, `V_CE = 1.0 V` rows — `J_C` at a given `V_BE` is `Nx`-invariant in
this model, verified in that experiment's README §"Area-scaling spot check"),
linearly interpolated in `V_BE` between the two bracketing grid rows at
`J_C = 5.16 mA/µm²` (`= I_C 4.75 mA` at `Nx=8`, the top of the bias range):

| corner | −40 °C | 27 °C | 125 °C | bracketing rows used (`vbe_v` → `jc_ma_um2`) |
|---|---|---|---|---|
| `bcs` | 0.8938 V | 0.8396 V | **0.7539 V** | 0.89→4.5007 / 0.91→7.9790; 0.83→3.8948 / 0.85→6.5422; 0.75→4.7081 / 0.77→7.0463 |
| `typ` | 0.9036 V | 0.8511 V | 0.7665 V | 0.89→3.4251 / 0.91→5.9718; 0.85→5.0072 / 0.87→7.6753; 0.75→3.6801 / 0.77→5.4735 |
| `wcs` | **0.9152 V** | 0.8636 V | 0.7815 V | 0.91→4.5064 / 0.93→7.0072; 0.85→3.7779 / 0.87→5.8158; 0.77→4.1416 / 0.79→5.9176 |

So over the full `{bcs, typ, wcs} × {−40, 27, 125} °C` box:

```
V_BE2 ∈ [0.7539 V (bcs/125 °C), 0.9152 V (wcs/−40 °C)]     spread 0.161 V
```

(Measured d`V_BE`/d`T` at fixed `J_C`, `typ`: (0.7665 − 0.9036)/165 °C =
**−0.83 mV/°C** — notably smaller in magnitude than the −2 mV/°C Si-BJT rule
of thumb, which is why this budget uses the measured table rather than a
textbook coefficient.)

`α` is a resistor *ratio*, so its tolerance is matching-limited; **±2 %** is
budgeted (`α ∈ [0.8984, 0.9350]`).

### Worst-case corner table

`V_CE1 = α·VDD − V_BE2` is maximised by (high `α`, high `VDD`, low `V_BE2`);
`V_CE2 = (1−α)·VDD + V_BE2` is maximised by (low `α`, high `VDD`, high
`V_BE2`). Both extremes are evaluated, and the temperature that produces each
is named:

| Case | Worst-case inputs | Value | Margin to BVCEO(min) 1.4 V |
|---|---|---|---|
| **`V_CE1` max** | `α`=0.9350, `VDD`=1.98 V, `V_BE2`=0.7539 V (`bcs`, **+125 °C**) | 0.9350×1.98 − 0.7539 = **1.097 V** | **0.303 V (21.6 %)** |
| **`V_CE2` max** | `α`=0.8984, `VDD`=1.98 V, `V_BE2`=0.9152 V (`wcs`, **−40 °C**) | 0.1016×1.98 + 0.9152 = **1.116 V** | **0.284 V (20.3 %)** |
| `V_CE1` min | `α`=0.8984, `VDD`=1.62 V, `V_BE2`=0.9152 V (`wcs`, −40 °C) | 0.8984×1.62 − 0.9152 = 0.540 V | n/a — checked against `V_CE,sat` and the model's 0.4 V validity floor |
| `V_CE2` min | `α`=0.9350, `VDD`=1.62 V, `V_BE2`=0.7539 V (`bcs`, +125 °C) | 0.0650×1.62 + 0.7539 = 0.859 V | n/a |
| `V_BC2` max (least reverse) | `α`=0.9350, any `VDD` | (0.9350−1)×1.62 = −0.105 V | reverse-biased ⇒ no saturation |

**The worst temperature corner is not the same for the two devices**: `Q1`'s
worst case is **hot** (+125 °C, where `V_BE2` collapses and the cascode base
pushes `V_C1` up), `Q2`'s worst case is **cold** (−40 °C, where `V_BE2` rises
and `V_C1` with it is pulled down, leaving more of `VDD` across `Q2`). Both
were evaluated; neither is the nominal 27 °C case, which is exactly why the
27 °C-only check is insufficient.

Nominal-supply, per-temperature values (`typ`, `VDD` = 1.80 V, `α` = 0.9167):

| T | `V_BE2` | `V_CE1` | `V_CE2` |
|---|---|---|---|
| −40 °C | 0.9036 V | 0.746 V | 1.054 V |
| 27 °C | 0.8511 V | **0.799 V** | **1.001 V** |
| 125 °C | 0.7665 V | 0.884 V | 0.916 V |

The nominal operating point lands on `V_CE` = 0.80 V and 1.00 V — two points
the characterization sweep actually measured (`{0.8, 1.0, 1.2, 1.4} V` grid),
so the nominal design point is inside the evidence, not extrapolated from it.

### Self-heating

`sg13g2_hbt_mod.lib` gives the thermal network explicitly:
`rth = 1*selft*3.26E+03*(4/Nx)**0.9` K/W with `selft=1` by default. At
`Nx = 8`: `rth = 3260 × (4/8)**0.9 = 1747 K/W`. Junction rise at the worst-case
per-device dissipation in the table above (`I_C` = 4.5 mA, `V_CE` ≈ 1.12 V,
`P` = 5.0 mW):

```
ΔT_j = 1747 K/W × 5.0 mW ≈ 8.8 K       (≈ 7 K at the nominal 4.0 mA point)
```

So `T_j ≤ T_ambient + ~9 K`. This is the second reason `Nx = 8` rather than
`Nx = 1`: there `rth = 3260 × (4/1)**0.9 = 11 352 K/W`, and the `Nx=1`
noise-optimum bias (`J_C` = 45.78 mA/µm² ⇒ `I_C` = 5.27 mA at `V_CE` = 1.0 V,
record row `typ`/27 °C) dissipates 5.3 mW into that thermal resistance —
**ΔT_j ≈ 60 K**, which at the 125 °C ambient corner puts the junction near
185 °C, far outside the model card's own −40…+125 °C validity range.

## Evidence

All rows below are from record `20260910-200059-7da7038` under
`sim/hbt-characterization/records/` (issue #7 / PR #8, merged 2026-09-10);
bench definitions — 50 Ω-referenced NF at 2.4 GHz, `Rs` pinned at 300.15 K,
unmatched common-emitter, self-heating active — are in
`sim/hbt-characterization/README.md`. **These are bare-device numbers, not
matched-LNA numbers**; they are cited here only for *where in bias space the
device wants to sit*, never as a gain/NF claim against `spec/target-spec.md`.

### 1. The bias-current range (the primary citation asked for by #16)

All rows `point_id = nx8_typ_27c_vce1.0v` (`Nx=8`, `typ`, 27 °C,
`V_CE = 1.0 V`), raw per-point CSV:

| `vbe_v` | `ic_a` | `jc_ma_um2` | `nf_db` | `gain_db` | `ft_hz` |
|---|---|---|---|---|---|
| 0.83 | 2.840e−3 | 3.081 | 2.330 | 16.88 | 2.67e11 |
| 0.85 | 4.754e−3 | 5.158 | 2.109 | 19.58 | 3.35e11 |
| 0.87 | 7.337e−3 | 7.962 | 1.992 | 21.46 | 3.85e11 |
| 0.91 | 1.431e−2 | 15.522 | **1.905** (device optimum) | 23.69 | 4.32e11 |

This is the bias-current decision in one table. The device's own noise
optimum at `Nx=8` is `I_C` = 14.3 mA — **25.7 mW at 1.8 V**, 2.6× over the
DRAFT Power target. Backing off to `I_C` = 4.0–4.75 mA costs **0.20–0.43 dB**
of bare-device NF and saves ~70 % of the DC power. That is the trade this
record takes: the recommended range is **`I_C` = 3–5 mA, nominal 4.0 mA**,
which sits on the flat shoulder of the NF-vs-`J_C` curve, not at its minimum.

### 2. Why `Nx = 8`, not `Nx = 1`

`records/…-summary.csv`, `typ`/27 °C/`V_CE`=1.0 V: `Nx=1` noise-optimum is
`J_C` = 45.78 mA/µm² → NF 6.32 dB; `Nx=8` is `J_C` = 15.52 mA/µm² → NF
**1.90 dB** (README §"Area-scaling spot check"). Beyond the 4.4 dB
bare-device NF difference, the `Nx=1` optimum is **outside the model card's
own validity box on both axes**: `I_C` = 5.27 mA vs. the stated
`ic < 0.003·Nx A` = 3 mA limit, and `V_BE` ≈ 1.02 V vs. the stated
`vbe : 0.65–0.96 V` range. The recommended `Nx=8` point (`I_C` = 4.0 mA ⇒
0.50 mA/finger; `V_BE` 0.83–0.90 V over temperature) is inside both.

### 3. Why `V_CE` was chosen on headroom, not on noise

`records/…-summary.csv`, noise-optimum NF vs. `V_CE` at fixed corner:

| corner/T | `V_CE`=0.8 | 1.0 | 1.2 | 1.4 |
|---|---|---|---|---|
| `typ`/27 °C | 6.393 dB | 6.318 | 6.311 | 6.353 |
| `typ`/125 °C | 7.534 | 7.443 | 7.450 | 7.503 |
| `wcs`/27 °C | 7.432 | 7.371 | 7.379 | 7.398 |
| `wcs`/125 °C | 8.578 | **8.514** | 8.534 | 8.573 |

Spread ≤ 0.10 dB across the whole 0.8–1.4 V `V_CE` range at every corner
shown. The characterization README states the same conclusion independently:
"`J_C` selection dominates the noise-optimum decision; `V_CE` selection is a
much weaker second-order lever", and "this device's noise optimum does not,
by itself, push a design toward either a cascode or a single low-voltage
stage." **This record therefore does not claim the cascode is
noise-motivated** — it is chosen on the breakdown/stability/gain grounds
argued below, and `V_CE` is spent on breakdown margin because the evidence
says NF does not care.

### 4. Binding-corner sanity

`wcs`/125 °C (`wcs` is this repo's `ss`-equivalent HBT label, per
`sim/README.md`) at `V_CE` = 1.0 V, `Nx=1`: noise-optimum NF 8.51 dB, gain
6.39 dB, fT 1.99e11 Hz — i.e. the device still has ~200 GHz of fT at the
worst corner, two orders of magnitude above the 2.4 GHz band. Nothing in the
recommended bias plan is fT-limited at any corner.

### What is NOT evidenced here

- **No `Nx=8` corner data exists.** The `Nx=8` rows are a single spot check
  at `typ`/27 °C/`V_CE`=1.0 V. Corner behaviour at `Nx=8` is inferred from
  the `Nx=1` corner deltas. Follow-up: #21.
- **No committed breakdown testbench exists in this repo.** BVCEO here is a
  *process-spec* and *model-card* number, not a simulated extraction. The
  VBIC card does carry weak-avalanche parameters (`avc1 = 2.40`,
  `avc2 = 10.81`), so an extraction is possible — but an uncommitted spot
  check run while drafting this record converged onto the leakage branch at
  −40 °C and +125 °C and produced a runaway only at 27 °C, i.e. a naive
  open-base DC sweep is not a trustworthy bench, and no number from it is
  quoted anywhere in this record. Follow-up: #20.
- **No matched-circuit claim.** No S-parameter, NF, gain, k-factor or IIP3
  number for the *LNA* is claimed by this record. Those require the
  schematic (#17) and benches that do not exist yet.
- **`V_CE1` = 0.54 V at the cold/low-supply/`wcs` extreme is below the
  characterized `V_CE` grid floor (0.8 V)**, though above the model's 0.4 V
  validity floor. The ≤0.10 dB `V_CE` flatness above is the basis for
  expecting no NF surprise there; #17 must confirm it by simulation rather
  than inherit the assumption.

## Alternatives considered

- **3.3 V rail, single-stage common-emitter with inductive load** — with an
  inductive load the DC collector voltage *is* the rail, so `V_CE` = 3.3 V =
  2.4× BVCEO(min). Rejected outright.
- **3.3 V rail, two-device cascode** — 1.65 V per device nominal (1.82 V at
  +10 %): above BVCEO(min) 1.4 V *and* above the model card's own
  `vce_max = 1.6`. Rejected. Surviving 3.3 V would need three or more stacked
  devices, adding noise and consuming the very headroom the stack was built
  to create.
- **3.3 V rail, single stage with a resistive `V_CE`-dropping load** — works
  for breakdown (drop 2.3 V across the load resistor), but the dropping
  resistor alone dissipates 2.3 V × 4 mA = **9.2 mW**, busting the DRAFT
  Power target before the device is biased, and puts a noisy resistor at the
  highest-impedance node. Rejected on power.
- **1.5 V rail (the SG13G2 LV-MOS rail), same cascode** — `α·1.5 − V_BE2`
  puts `V_CE1` at 0.52 V nominal and 0.47 V at −40 °C, below the
  characterized `V_CE` grid (floor 0.8 V) and close to the model card's 0.4 V
  validity floor. Rejected as a *nominal* choice for lack of evidence, not
  for breakdown (breakdown margin would actually improve). This is the
  fallback if a 1.8 V rail turns out to be unavailable at the system level
  **and** the characterization grid is extended down to `V_CE` ≈ 0.6 V.
- **Single-stage common-emitter on a dedicated ~1.0–1.2 V rail** — the
  strongest alternative: lowest power (4.0–4.8 mW, meeting the DRAFT Power
  *stretch*), one device to protect, simplest bias. Rejected because (a) with
  an inductive load `V_CE` = `VDD` identically, so 100 % of the supply
  tolerance is charged against a single 1.4 V budget — at 1.2 V +10 % only
  0.08 V of margin remains for RF swing, model error and any temperature
  derating of BVCEO itself; a 1.0 V rail restores ~0.30 V of margin but makes
  the entire breakdown case hostage to an external regulator's accuracy
  rather than to an on-die resistor ratio; (b) without a cascode, `C_bc`
  Miller feedback makes the k-factor row — which `CLAUDE.md` insists is "a
  spec row, not an afterthought" — materially harder at 2.4 GHz with a
  300+ GHz-fT device, and couples the input and output matching networks;
  (c) the >15 dB gain target is harder from one unbuffered stage. **This
  alternative should be revisited** if #17's stability analysis shows the CE
  stage clears k > 1.5 with margin, since it wins outright on power.
- **Cascode with `V_B2` from an absolute (bandgap-referenced) bias instead of
  a `VDD` ratio** — same topology, but `V_CE1` becomes supply-independent and
  therefore *all* supply tolerance lands on `Q2`: `V_CE2,max` = 1.98 − 0.735 =
  **1.245 V**, margin 0.155 V (11 %) instead of 0.284 V (20 %), and `V_BC2`
  goes forward at the low-supply corner. Rejected: it nearly halves the
  breakdown margin for no benefit.
- **Deferring the decision until an inductor model exists** — rejected. The
  inductor-model gap (#5, upstream `klayout-tools#1519`) blocks the
  *matching-network* values, not the DC bias stack; nothing in this record
  depends on an inductor's inductance, only on the ≤3 Ω series-resistance
  bound used conservatively above.

## Consequences

**Enabled**

- `spec/target-spec.md`'s Supply row has a concrete proposal to ratify
  (1.8 V ±10 %) and the Power row a derived one (7.2 mW nominal, ≤9.4 mW
  worst case) — via the separate two-key ratification PR, not this record.
- #17 can draw the schematic against fixed numbers: two `npn13G2` `Nx=8`
  devices, `I_C` = 4.0 mA, `V_B2` = (11/12)·`VDD`, inductive degeneration and
  load, cascode base RF-bypassed.

**Costs and constraints this imposes**

- **The DRAFT Power stretch (<5 mW) is given up.** At 1.8 V it would require
  `I_C` < 2.8 mA, which walks further down the NF shoulder in §Evidence 1.
  The <10 mW *target* is met with ~0.6 mW of headroom, so the bias network
  must hold `I_C ≤ 4.5 mA` over corners and cost ≤0.5 mW itself — a real
  constraint on the bias design, not a free parameter.
- **Output swing is breakdown-limited to ~0.28 V peak** at the collector in
  the worst corner. `spec/target-spec.md`'s IIP3 row is an *extrapolated
  intercept*, not a delivered power, so it is not directly threatened — but
  the two-tone bench must keep both tones well inside that swing and record
  their amplitudes (as `CLAUDE.md` already requires), and **any future
  large-signal blocker or P1dB row may not be satisfiable at this rail** and
  would reopen this record.
- **1.8 V exceeds the SG13G2 LV-MOS rating.** `sg13g2_moslv_parm.lib` gives
  `VGS_MAX = VDS_MAX = 1.6 V`; `VDD,max` here is 1.98 V. Any MOS in the bias
  network must therefore be the HV flavour (`sg13g2_moshv_parm.lib`:
  `VDS_MAX = 3.0 V`), or the bias network must be built from HBTs and
  resistors. This is a binding constraint on #17.
- **`Nx` is not free downstream.** The characterization README's own warning
  applies: noise-optimum `J_C` moved ~3× between `Nx=1` and `Nx=8`, so if
  #17 changes the emitter geometry, the bias current in this record must be
  re-derived, not rescaled.
- **The 125 °C corner runs the junction ~9 K past the model card's stated
  validity ceiling** once self-heating is included (`T_j` ≈ 134 °C at a
  125 °C ambient). This is inherent to the corner set, not to this topology —
  it applies equally to the existing characterization record — but results at
  that corner carry that caveat.

**Follow-up work this record does not do**

- A committed breakdown-extraction testbench under `sim/` (BVCEO by forced-
  `I_B` continuation, plus BVCER/BVCES with a finite base impedance), so the
  ~20 % margin above can be checked against the model's own avalanche
  behaviour and the unclaimed BVCER credit can be quantified —
  [#20](https://github.com/2AMLogic/sg13g2-lna/issues/20).
- Extension of `sim/hbt-characterization/` to a full `Nx=8` corner grid and
  to `V_CE` = 0.6 V —
  [#21](https://github.com/2AMLogic/sg13g2-lna/issues/21).
- Ratification of the Supply/Power rows through the two-key protocol
  (tracked separately as #19).
