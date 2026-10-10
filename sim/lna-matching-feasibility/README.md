# lna-matching-feasibility — nominal-cell matching-network feasibility study

Issue [#186](https://github.com/2AMLogic/sg13g2-lna/issues/186), evidence
for [#27](https://github.com/2AMLogic/sg13g2-lna/issues/27) (input/output
matching network). It answers one design question at a single PVT cell:
**which matching topology and element values does the committed DUT admit
once the inductors are lossy, and which ratified rows can each candidate
plausibly meet there?** The fleet's 45-cell campaign can then grade a
designed network instead of a guess.

> **NOMINAL-CELL EXPLORATION, NOT A RESULT.** Every number in this directory
> comes from ONE PVT cell: `hbt_typ` / `mos_tt`, 27 °C, VDD = 1.80 V.
> `CLAUDE.md` requires PVT corners on every recorded result, so nothing here
> may be quoted as a result against a `spec/target-spec.md` row. The "rows
> met" columns only say on which side of a ratified bar a nominal-cell number
> falls. The stability gate (μ > 1 at every ratified cell before a match is
> called final) stays with #27. No file under `design/` or `spec/` is
> modified. The runner has no corner grid and no knob that adds one.

## Records

| Record | What it holds |
|---|---|
| [`20261010-201010-6aca84c`](records/20261010-201010-6aca84c.md) | First study: characterization, the base-feed what-if probe, 3 candidate topologies × 4 inductor-Q cases, each verified by a single-cell ngspice run |
| [`20261010-213251-3ccb391`](records/20261010-213251-3ccb391.md) | Issue [#190](https://github.com/2AMLogic/sg13g2-lna/issues/190): DC-reference sensitivity. 4 candidate / Q points re-run with an explicit `Rxoutdc` bench resistor (1e9 and 1e11 Ω) on the floating `xout` node and compared with the first record. Decks, logs, [sensitivity table](records/20261010-213251-3ccb391-sensitivity.csv) |
| [`20261010-233800-d1312cc`](records/20261010-233800-d1312cc.md) | Issue [#193](https://github.com/2AMLogic/sg13g2-lna/issues/193): finite resonant base-bias feed vs the ideal-choke bound. 8 feed variants (committed, ideal choke, EM spiral + tuning C tanks with ideal / PDK `cap_cmim` / bracketed parasitics), DC audit, NFmin and 50-ohm NF at 290 K, broadband mu/k/\|Delta\|, verified re-synthesized match for 3 feeds, go/no-go. Tables: [feeds](records/20261010-233800-d1312cc-feeds.csv), [band](records/20261010-233800-d1312cc-feeds-band.csv), [match](records/20261010-233800-d1312cc-match.csv) |

## Findings (record `20261010-201010-6aca84c`, nominal cell)

1. **Le is not an input-match lever on the committed DUT.** The input is
   set by `R3b`, the 330 Ω resistor feeding Q1's base from the AC-grounded
   `bref` node, not by the transistor. Zin at `rfin` is
   280.2 − j39.3 Ω at 2.44175 GHz. An ideal-Le sweep from 0.1 to 3 nH moves
   Re(Zin) only between 269 and 306 Ω. The optimum noise source impedance
   stays at about 85 Ω. Noise match and power match are therefore far
   apart, and no inductive-degeneration choice brings them together.
2. **R3b also sets the NF floor.** In the what-if probe, R3b's RF path is
   isolated by an ideal 1 µH choke. DC is unchanged: I_C1 is 3.9403 mA in
   both cases. With the feed isolated, the 290 K-referenced NFmin falls from
   2.445 dB to 0.467 dB (Le = 1 nH) and Zopt moves to about 465 + j50 Ω.
   Re(Zin) then tracks Le at roughly 1.08 kΩ/nH (the ω_T·Le term) and
   crosses Re(Zopt) near Le ≈ 0.3 nH, which makes the classical simultaneous
   noise/power match available. This is a probe, not a design proposal: a
   real feed would need its own bias and noise design. It does, however,
   point at the base-bias feed as the binding constraint on the ratified
   NF < 1.5 dB row. It is a sharper attribution than "bias point and device
   sizing".
3. **On the committed DUT every network that meets S11 < −10 dB costs NF.**
   Without a match, the nominal NF into 50 Ω is 2.588 dB (ngspice `sp`,
   300.15 K reference; record `20260926-122301-088c734` gives
   `nf290` = 2.6559 dB). At Q = 10 the best candidate reaches a worst-case
   in-band NF290 of 3.336 dB. The ratified NF row is not met at the nominal
   cell by any candidate.
4. **The output wants a three-element network.** The collector node is
   about 7.4 µS ∥ 20 fF. A two-element "Lc + series C" match would need
   Lc ≈ 24.7 nH at Q = 10, 39.5 nH at Q = 20 and 94 nH ideal; none of these
   is a realistic on-chip spiral. The committed Lc value (5 nH) plus a shunt
   C at `rfout` plus a series C reaches S22 ≈ −15.6 dB across the band at
   Q = 10. The 5-turn EM geometry (5.52 nH, Q = 8.5) used as Lc reaches
   −16.2 dB, with Cp = 0.41 pF and Cs = 0.36 pF.
5. **Gain clears 15 dB at Q = 10.** |S21| is 20.06–20.46 dB across the
   band for all three topologies, and 19.85–20.20 dB with the EM Lc.
6. **Every finite-Q candidate has μ > 1 at this cell, by a ppm-scale
   margin.** Every Q = 20, Q = 10 and EM candidate has μ > 1 at all 140
   frequencies from 10 MHz to 30 GHz. The minimum is 1 + 3.6e-7 at Q = 10
   (1 + 8.8e-8 at Q = 20), at the 10 MHz edge of the sweep, where both ports
   are DC-blocked. That margin is resolved: it is about 1000× the resolution
   of the 10-significant-digit S-parameter tables. It is simply small. The
   ideal-inductor case behaves differently by topology:
   - `lp_power` and `lp_noise`: μ − 1 is about −4.7e-12 at 27 and 29 of the
     140 points. That is below table resolution, so these points are μ = 1
     to table precision, i.e. the lossless limit. They are **not** evidence
     of μ < 1.
   - `hp_power`: μ − 1 reaches −7.7e-7 at 30 points, a resolved deficit
     (μ < 1).

   So inductor loss is what lifts the low-pass candidates from the lossless
   boundary μ = 1 to a resolved μ > 1, and it is what removes a real μ < 1
   deficit for `hp_power`. The committed unmatched DUT's 45-cell minimum is
   0.99999592. A ppm-scale margin at one cell is not a stability result.
7. **The ideal (infinite-Q) case is a bound, not a design.** Its output
   tank has an unbounded Q: S22 is about 0 dB at the band edges and S21 peaks
   at 44 dB. The unilateral solver is also least accurate here. For the
   power-target candidates it predicts a perfect band-centre match (S11 at
   the −300 dB numerical floor), but simulation gives −18.6 dB (`lp_power`)
   and −18.4 dB (`hp_power`). For `lp_noise` it predicts the −12 dB target,
   and simulation gives −10.3 dB.

### Ranked short list

The ranking basis is the Q = 10 case: rows met first, then lower worst-case
NF290, then higher broadband μ. Element values are for Q = 10 at
2.44175 GHz. Every topology uses the committed `Le` = 1 nH.

| Rank | Topology | Input network | Output network | Nominal-cell rows met at Q = 10 / EM Lc | Inductor feasibility |
|---|---|---|---|---|---|
| **1** | `lp_noise`: low-pass L-section, noise-weighted (\|S11(f_mid)\| ≤ −12 dB, minimum predicted NF) | series Lb 4.564 nH (R = 7.00 Ω) + shunt 0.626 pF at `rfin` | Lc 5 nH + shunt 0.504 pF at `rfout` + series 0.346 pF (EM Lc: 0.412 / 0.357 pF) | S11 −11.55 dB ✓, S22 −15.61 dB ✓, S21 20.06–20.24 dB ✓, μ ✓ (ppm margin); NF290 3.336 dB ✗ | Lb ≈ the extracted 4-turn geometry (L ratio 1.02, EM Q 10.3); Lc ≈ the 5-turn geometry |
| 2 | `hp_power`: high-pass L-section (series C + shunt Lp), conjugate power match | series 0.686 pF + shunt Lp 7.373 nH (R = 11.31 Ω) at `rfin` | as above | S11 −30.03 dB ✓, S22 −15.61 dB ✓, S21 20.24–20.45 dB ✓, μ ✓ (ppm); NF290 3.870 dB ✗ | Lp is 1.34× the largest extracted L: needs an unextracted larger spiral, a bondwire or an off-chip part |
| 3 | `lp_power`: low-pass L-section, conjugate power match | series Lb 6.503 nH (R = 9.98 Ω) + shunt 0.530 pF | as above | S11 −29.96 dB ✓, S22 −15.62 dB ✓, S21 20.31–20.46 dB ✓, μ ✓ (ppm); NF290 4.064 dB ✗ | Lb is 1.18× the largest extracted L |

**What remains open for the 45-cell run (#27):**

- `lp_noise` has only 1.55 dB of S11 margin at this cell. Whether it holds
  across process, temperature and supply is unknown. The −12 dB band-centre
  target is a policy choice in this bench (see "Method"), not a ratified
  number.
- The μ margin is ppm-scale and sits at the 10 MHz sweep edge, so it must be
  re-measured at every ratified cell.
- No candidate reaches NF < 1.5 dB while R3b feeds the base as committed
  (finding 2). That is a design question for #27 and #58, not a matching
  one.
- Passive tolerances (capacitor corners, inductor corners beyond the EM
  model's analytic scaling) and pad/ESD/bondwire parasitics are not
  modelled.

## Bench definitions

Every generated deck restates its bench in its header
(`netlist-snapshots/<record-id>/*.spice`), so a number cannot be separated
from the bench that produced it. The port, analysis and NF definitions
match those of [`../lna-characterization/`](../lna-characterization/README.md).
The verification decks differ in one respect, the floating output node
described under "DC operating point" below:

- **Ports**: ngspice `sp` port sources, `portnum` / `z0 = 50`, at both
  ports.
- **In-band S-parameters**: `sp lin 11 2.4e9 2.4835e9 1`. The `donoise`
  flag gives ngspice's two-port NF, NFmin, Rn and SOpt, which are referenced
  to the **analysis** temperature (300.15 K). NFmin is re-referenced to
  290 K with `F290 = 1 + (F_T − 1)·T/290`.
- **Stability**: `sp dec 40 1e7 3e10`, 140 frequencies from 10 MHz to
  30 GHz. Edwards–Sinsky μ, Rollett k and |Δ| are computed from the raw
  complex S-parameters by `matching_solver.py`. max |S11| and max |S22| are
  reported alongside as the negative-resistance check. k is ill-conditioned
  on this topology, for the reason given in `../lna-characterization/README.md`.
- **NF at T0 = 290 K**: a second, isolated copy of the matched amplifier
  with its own VDD. The 50 Ω source `Rs` and the 50 Ω load `RL` are both
  `noisy=0`. NF is `10·log10(1 + inoise² / (4·k·290·50))` over
  `noise … lin 21 2.4e9 2.4835e9` (4.175 MHz spacing). The reported value is
  a sampled maximum, not a continuous-band bound. Internal resistors,
  including the inductor-loss resistors, are noisy at the analysis
  temperature.
- **Transducer-gain cross-check**: `ac` at the band centre, `db(2·v(nfout))`
  against |S21|. They agree to better than 1e-4 dB for every candidate
  (`gt_minus_s21_db_mid`).
- **Solver option**: `.options gmin=1e-10`, the same override and reason as
  in `../lna-characterization/README.md`.
- **DC operating point (floating output node, verification decks only)**:
  In the `lnam` subcircuit of `tb_match_verify.spice.tmpl`, the DUT's
  `rfout` (node `xout`) connects only to capacitors: the committed 100 pF
  `Cout`, the shunt `Cpout` and the series `Csout`. It has no DC path. So
  every one of the 12 `verify_*.log` files in record
  `20261010-201010-6aca84c` repeatedly reports
  `singular matrix: check node xa.xout` / `xb.xout` (30 such lines per
  log). For each OP solve, dynamic gmin stepping, true gmin stepping and
  source stepping all fail. The operating point is reached only through
  ngspice's last-resort "transient op" fallback, which the logs show
  finishing successfully.
  - The resulting OP is consistent: I_C1 is 3.938–3.943 mA in every
    candidate. That is consistent with the 3.9403 mA from the
    characterization decks, which have no floating node and no
    singular-matrix warnings.
  - The small-signal numbers (`sp`, `noise`, `ac`) are unaffected. A
    purely capacitive node has a well-defined, non-singular admittance at
    every f > 0, and its DC voltage does not bias any device, because
    `Cout` blocks it from the collector.
  - The bench is therefore **not** identical to `lna-characterization`'s,
    whose logs show no singular-matrix warnings. Every verification OP in
    this record depends on the fallback convergence path.
  - Future records should give `xout` a DC-defining element, for example a
    very large `noisy=0` resistor to ground, with its effect on μ bounded
    against the ppm margin. This record has not been re-run with one.
    **Update (#190)**: record `20261010-213251-3ccb391` did this; see "DC reference on
    xout" below. The text above describes the historical record only.
- **DUT**: `design/netlist/lna.spice` is inlined verbatim except for the
  lines marked `BENCH EDIT`:
  - **Le loss** is a resistor in parallel with `Le`, with R = Q·ω_mid·Le
    (153.4 Ω at Q = 10). A *series* loss resistor of the same Q (1.53 Ω)
    would also carry Q1's ~3.9 mA emitter current and add about 6 mV of DC
    emitter degeneration. The mirror reference (Q3) does not see that drop,
    so a series R would shift I_C1 as well as add RF loss. A development run
    of this bench showed I_C1 falling by roughly 12 %; that run was not
    retained and is not quoted as evidence. The parallel form keeps the RF
    loss at the band centre and leaves DC untouched: I_C1 stays
    3.938–3.943 mA in every candidate. This concern applies to any
    series-R Le-loss model, for example the `le_q*` variants of
    `../lna-characterization/run_lna_variant.sh`.
  - **Lc** has a series loss resistor R = ω_mid·L/Q, or is the EM-extracted
    geometry instance.
  - **The input matching inductor** (Lb or Lp, outside the DUT) has a series
    loss resistor R = ω_mid·L/Q.
  - **Capacitors** are ideal.
  - Every loss resistor is frequency-independent, sized for the stated Q at
    2.44175 GHz.
- **EM inductor model**: `../models/sg13g2_inductor_em.spice` (stamped copy,
  hash-checked by the runner). Its stated limits carry over: three extracted
  geometries (1, 4 and 5 turns), one process point and one temperature.

### Q cases

| Case | Le | Lc | Input matching L |
|---|---|---|---|
| `ideal` | ideal | 5 nH ideal | ideal |
| `q20` | Q = 20 (parallel R) | 5 nH, Q = 20 (series R) | Q = 20 (series R) |
| `q10` | Q = 10 | 5 nH, Q = 10 | Q = 10 |
| `em` | Q = 10 | EM-extracted 5-turn geometry, tried first in the order 5-, 4-, 1-turn and taken if the output solve is feasible | Q = 10 |

The extracted spirals measure Q = 8.5 (5-turn) and Q = 10.3 (4-turn) at
2.44 GHz in this bench, so `q10` is the realistic basis for on-chip spirals.

## DC reference on xout (issue #190)

`tb_match_verify.spice.tmpl` now has an `@@XOUT_DC@@` slot in `lnam`.
`matching_solver.py solve --xout-rdc R[,R...]` fills it with one labelled
bench element, `Rxoutdc xout vss <R> noisy=0`: noiseless, from the DUT's
`rfout` node to the subcircuit ground, outside the DUT and outside any
matching network. Without `--xout-rdc` the slot is a comment and the deck is
the #186 deck (a unit test checks this line for line against the committed
snapshot). `run_dc_reference_study.sh` runs the bounded comparison
(`DCREF_STAGE=gen|run|finish|all`; it re-uses the characterization data of
record `20261010-201010-6aca84c`, which has no floating node and is
unchanged). It does not touch the historical record.

Record [`20261010-213251-3ccb391`](records/20261010-213251-3ccb391.md): nominal cell only, 4 candidate / Q
points (`lp_noise` and `hp_power` at Q = 10; `lp_noise` and `hp_power` ideal)
× R = 1e9 and 1e11 Ω = 8 decks, each compared with the retained #186 result of
the same point. Convergence is classified from the ngspice log
(`classify_convergence`), not from `BENCH_COMPLETE`: a log is "normal" only if
it has no singular-matrix warning, no failed gmin / source stepping and no
transient-op fallback.

Results (all nominal cell, full table in the record):

- **Convergence.** All 8 new logs: zero singular-matrix warnings, zero
  stepping failures, zero transient-op fallbacks. All 12 historical
  verification logs are flagged by the same classifier. The first-run OP now
  matches the characterization decks (I_C1 3.9402 mA).
- **Operating point.** At finite Q, I_C1 moves from 3.9384–3.9387 mA
  (historical fallback) to 3.9402 mA, +1.5 to +1.8 µA (0.04 %). The shift is
  identical at 1e9 and 1e11 Ω, so it comes from replacing the fallback OP by
  the converged one, not from the resistor's conductance.
- **What the resistor itself does.** Between 1e9 and 1e11 Ω the finite-Q
  decks differ by ≤ 8e-4 dB in S22 mid, ≤ 4e-6 dB in S11 / S21 mid, 0 in
  NF290, and ≤ 5.4e-11 in the broadband μ minimum; the ideal-Le decks (near
  lossless resonances) by ≤ 4.5e-3 dB in S22 and ≤ 6e-4 dB in S21. These are
  upper bounds on the resistor-attributable part, from two values only; they
  are not a proof for other values (see the limits below).
- **Historical vs. new, finite Q.** S21 mid +0.004 dB, NF290 −3e-4 dB, S22
  mid up to 0.27 dB, S11 mid unchanged at −12 dB for `lp_noise` but
  −68.4 → −66.3 dB for `hp_power`, which is a sub-0.001 change of |Γ| on a
  deep null and is not a meaningful dB comparison. These differences are
  attributed to the OP change above. That attribution is by elimination
  (they do not depend on R over two decades), not by a separate experiment.
- **μ margin.** Finite-Q broadband μ minimum is 1.0000003575 at 10 MHz
  before and after, for both R values (|Δμ| ≤ 4.2e-11, ≤ 1.2e-4 of the 3.6e-7
  margin, below the 1e-9 table-resolution floor used here; the
  frequency of the minimum is unchanged). By the pre-set criterion (a change
  of more than 10 % of the baseline margin, a margin driven to the table
  floor, or a moved minimum frequency) the resistor is **not material** at
  these two values. The ideal-Le points are separate: `hp_power` ideal has a
  resolved μ = 0.99999923 at 10 MHz, unchanged to 10 digits; `lp_noise` ideal
  is μ = 1 to table resolution before and after, so the frequency of its
  minimum (133 MHz vs 668 MHz) carries no information.
- **No stability claim.** This is two R values at 4 nominal-cell points on a
  ppm-scale margin at the sweep edge. It does not make any candidate stable.
  The PVT μ gate remains with #27.

Limits of this record:

- Two R values, four points, one cell. 1e9 Ω is the smaller, and its
  conductance (1e-9 S) is still tiny against Cout's admittance at 10 MHz
  (≈ 6e-3 S), ratio ≈ 2e-7, comparable in order to the 3.6e-7 margin; the
  measured effect is nevertheless below resolution. A much smaller R (e.g.
  1e6 Ω) was not tested and would very likely matter. `parse_rdc_list` refuses
  R < 1e6 Ω.
- The mu resolution floor (1e-9) is conservative against the ~1e-10 implied
  by `numdgt=10`; changes below it are reported as "below table resolution",
  not as zero.
- The 8 decks were run as separate single `ngspice -b` invocations on a
  shared host (no loop, no background jobs, no grid); each takes ~0.2 s.
  They are nominal-cell probes, not a PVT campaign, so the fleet / `klt sim`
  route was not used. A multi-corner confirmation with the DC reference is
  not in scope here.
- Historical evidence (record `20261010-201010-6aca84c`) is unchanged.

## Finite resonant base-feed study (issue #193)

Question: can a finite, model-backed parallel-LC tank in series with R3b
(`bref -R3b- b1f -[spiral || C]- b1`) recover a useful part of the noise
headroom that the ideal 1 uH choke of finding 2 exposes? The candidate set,
model provenance, validity flags, best-feed rule and go/no-go policy are in
[`feed-study-declaration.md`](feed-study-declaration.md), generated by
`feed_study.py declare` and committed (commit `d1312cc`) before the evidence run;
the record id carries that commit. Nominal cell only; R3b = 330 Ohm and the
DR-0003 reference are retained and the bias is never retuned.

Record [`20261010-233800-d1312cc`](records/20261010-233800-d1312cc.md)
(16 sequential single-process ngspice-46 decks, no grid, no fleet submission).

**Reproduce** (needs the pinned PDK and ngspice >= 46; one record, strictly
sequential):

```bash
export PDK_ROOT=/path/to/ihp-open-pdk PDK=ihp-sg13g2
MATCH_NGSPICE=/path/to/ngspice-46/bin/ngspice sim/lna-matching-feasibility/run_feed_study.sh
python3 -I -m unittest discover -s sim/lna-matching-feasibility/tests -v   # PDK-free
python3 -I sim/lna-matching-feasibility/feed_study.py declare | diff - sim/lna-matching-feasibility/feed-study-declaration.md
```

The runner refuses to start if the declaration is stale against the code. Stages
(`feed_study.py` subcommands): `tune-gen` / `plan` (measure the EM series
admittance, size the tank C), `scan-reduce`, `match-gen` / `match-solve` /
`match-reduce`. The unit tests replay the committed record byte for byte.

**Method points.**

- *Tank tuning.* For each EM geometry the series-branch admittance Yser(f) of the
  pi-model is measured (la driven, lb on a 0 V source). Its own self-capacitance
  Cser is inside Yser, so the tuning C satisfies Im(Yser + jwC) = 0 at 2.44175
  GHz exactly. The substrate shunts are not part of the tank; they load b1f / b1
  in the full simulation. Not optimized per variant.
- *Capacitor.* PDK `cap_cmim` (`cornerCAP.lib` cap_typ), sized square by the
  closed form and then measured as a one-port: realised C matches the target
  to < 0.001 %. The model has a 55 mOhm top-plate resistor and **no
  bottom-plate parasitic** (its header defers that to extraction). That
  evidence is missing; `em5_cmim_bp10` brackets it with an ASSUMED 10 % shunt at
  the base node, and `em5_cq30` brackets unknown capacitor loss (Q_C = 30).
  Neither bracket is a measurement.
- *DC validity.* `op` audit per variant: IC1/IC2, IB1, VBE/VCE/VBC, drop across
  R3b plus the feed, IDD and supply power. Flags: IC1 or IDD more than 1 % from
  the committed feed; VCE < 0.3 V or VBC > 0.4 V (bench policy, not PDK limits);
  any non-normal ngspice convergence.
- *Noise.* NFmin@290 (ngspice `sp` donoise NFmin, re-referenced from 300.15 K)
  and 50-ohm-source NF@290 (the separate `.noise` method) are tabulated
  separately; the sp-derived 50-ohm NF is cross-checked against `.noise`.
- *Matching.* The existing `lp_noise` (Q = 10) input match and the committed
  output network are re-synthesized from each feed's own characterization
  (the #186 characterization deck with the R3b line swapped) and verified with
  the #186 verification deck, with the #190 DC-reference convention
  (`Rxoutdc` = 1e11 Ohm). The matched DUT carries a Q = 10 parallel loss on Le
  (as in all #186 matched decks), which is why the matching table's "DUT NFmin"
  (Le at Q = 10) is higher than the feed table's (ideal Le).
- *Stability.* Edwards-Sinsky mu, Rollett k and |Delta| over 10 MHz-30 GHz (140
  points) for every variant, with the mu table-resolution floor (1e-9) and the
  counts of resolved vs unresolved points. k is ill-conditioned (|S12| ~ -95 dB).

**Results** (nominal cell; full tables in the record):

| Feed | NFmin@290 mid / worst (dB) | 50-ohm NF@290 mid / worst (dB) | dIC1 | Zopt mid (Ohm) | Matched NF290 worst (dB) |
|---|---|---|---|---|---|
| committed | 2.445 / 2.445 | 2.656 / 2.656 | 0 | 85.2 + j2.8 | 3.335 |
| ideal choke (bound) | 0.467 / 0.467 | 1.818 / 1.818 | 0 | 465.6 + j49.9 | 1.808 |
| em5 + ideal C | 1.481 / 1.514 | 2.112 / 2.126 | -0.084 % | 144.7 + j11.7 | 2.610 |
| em5 + cap_cmim | 1.484 / 1.516 | 2.113 / 2.127 | -0.084 % | 144.5 + j11.7 | not matched |
| em4 + ideal C | 1.497 / 1.536 | 2.119 / 2.136 | -0.054 % | 143.1 + j11.9 | not matched |
| em5 cmim, 10 % bottom plate (bracket) | 1.484 / 1.516 | 2.124 / 2.136 | -0.084 % | 136.8 + j34.7 | not matched |
| em5, Q_C = 30 (bracket) | 1.598 / 1.620 | 2.165 / 2.175 | -0.084 % | 133.9 + j10.2 | not matched |

- **Bias.** No variant is flagged. The spiral's winding resistance moves IC1 by at most
  -0.084 % (about 3.3 uA of 3.94 mA) and supply power by 0.006 mW; the
  operating points (VCE, VBC) are unchanged to the printed precision. The feed is DC-valid;
  the DC cost is negligible.
- **Noise floor is the binding constraint.** The best valid finite feed
  (`em5_cideal`, selected by the declared rule) gets NFmin@290 from 2.445 dB to
  1.48 dB at band centre but 1.51 dB at the 2.4 GHz band edge: even the
  optimum noise match exceeds the 1.5 dB row at that edge, and none of the
  band is near the declared 1.2 dB planning limit (1.5 dB minus a 0.3 dB
  allowance for PVT spread). The tank's peak impedance is only about 800 Ohm
  (Q x wL of a 5.4 nH, Q = 9.5 spiral), against R3b = 330 Ohm and the ideal
  choke's effectively unbounded isolation. The verified matched NF290 of
  the existing `lp_noise` network is 2.610 dB worst-in-band (S11 -11.4 dB,
  S22 -15.6 dB, |S21| 23.0-23.1 dB), 1.1 dB over the row.
- **The matching network is a second limit, even for the bound.** With
  the ideal choke, NFmin is 0.47 dB but the same existing `lp_noise` match gives
  1.81 dB, because that topology is constrained to |S11(f_mid)| <= -12 dB and
  its inductor (Q = 10) is lossy while Zopt (466 Ohm) and Zin (1.2 kOhm) are far from 50 Ohm.
  So even the idealized bound is not a GO under the declared policy
  (`noise_match_penalty`); a different input network would be a separate study.
- **Capacitor model.** Replacing the ideal C by the PDK `cap_cmim` changes NFmin by
  0.003 dB. The unmodelled bottom-plate parasitic moves Zin and Zopt (Zin from
  546 - j262 to 256 - j326 Ohm for an assumed 10 %) but not NFmin; capacitor loss does: Q_C = 30
  costs 0.12 dB. The real part of the capacitor evidence is missing (no
  extracted MIM bottom-plate or ESR beyond 55 mOhm).
- **Area.** `em5` + `cap_cmim`: spiral outer square 197.5 um (about 39,000 um^2
  with the 22.7 um MIM) as a lower bound on bounding boxes only; no keep-out, guard ring or
  routing. `em4` is larger (230 um) for no noise gain. `em1` (0.097 nH) cannot isolate:
  tuning C is 41 pF and its peak impedance is about 6 Ohm (measured, not simulated as a
  feed).
- **Stability and new resonances.** Every tank adds one parallel resonance
  at 2.442 GHz (|Z| about 800 Ohm) by construction; the spiral alone self-resonates
  at 8.96 GHz (em5) / 10.70 GHz (em4). The tank variants' broadband mu minimum is
  0.99999706 at 0.562 GHz (resolved mu < 1 at 58 of 140 points), essentially the
  committed bare DUT's own 0.99999683 at the same frequency, so the tank adds no new
  mu < 1 region; max |S11| becomes 0.86 at 2.51 GHz (committed: 0.814 at 10 MHz),
  below 1 everywhere. The ideal choke, by contrast, drops mu to 0.99925 at 2.51 GHz
  (91 resolved points) with |S11| up to 0.98: the bound is also the worse-behaved
  circuit. After matching, mu is 1.0000003575 at 10 MHz for all three
  verified feeds (the #186 ppm-scale margin, identical to the table resolution),
  so the tank neither helps nor hurts stability at this cell. This is not a stability claim.
- **Convergence.** All 16 logs show normal operating-point convergence: no
  singular-matrix warning, no failed gmin / source stepping, no transient-op fallback.

**Recommendation: NO-GO for a full-PVT campaign on this feed.** The binding
constraint is the noise floor of the finite isolation (a ~800 Ohm tank peak): the
tuned EM-spiral tank leaves NFmin@290 at 1.48-1.51 dB, already short of the
declared limit at the nominal cell. Remaining NF budget against the 1.5 dB row
after the verified match: -1.11 dB (over by 1.11 dB). What would be needed
(inference from the bound, not measured here) is much higher RF isolation than
a ~800 Ohm tank peak provides, and a different input network; each would be a
new study with its own declaration. Adopting any
feed change needs a decision record and the full PVT campaign (#27). The ideal-choke
bound is a diagnostic, not a design.

**Limits.** One cell, one process point for the EM model (no passive corners),
no bottom-plate or ESR evidence for the MIM, no pad/ESD/bondwire parasitics, no
layout parasitics or coupling of the spiral to the signal path, matched NF for
three feeds only (the other five are scanned, not matched), the tuning is a
single-frequency tune of the series branch, and the 50-ohm NF/matching numbers
are sampled at 21 / 11 points. The tank variants' ranking among themselves
(differences of 0.01-0.05 dB) is below any claim this single cell supports.

## Method

1. **Characterization** (`char.spice`, one ngspice run). For each Le-loss
   case it records the DUT two-port S-parameters and noise parameters. It
   then repeats with `Lc` replaced by an ideal 1 µH choke, which exposes the
   device's collector-node admittance:
   `Ydev = 1/(Z22 − Z_Cout) − 1/(jω·1µH)`. The run also includes an
   ideal-Le sweep and the three EM geometries as one-ports.
   `char_feed.spice`, a second run, repeats the Le sweep with R3b's RF path
   choked (finding 2).
2. **Input synthesis**. The input network is a two-element L-section:
   series element on the 50 Ω side, shunt element at `rfin`. The two
   orientations are low-pass (series L, shunt C) and high-pass (series C,
   shunt L).
   - *Power target*: |S11| = 0 at the port with the inductor's loss
     included. The lossless closed-form L-section (Pozar §5.1) seeds a
     damped Newton refinement.
   - *Noise target*: the element values that minimize the predicted NF290
     subject to |S11(f_mid)| ≤ −12 dB. The predicted NF is a Friis cascade
     of the lossy network (thermal at 300.15 K) and the DUT's
     F = Fmin + Rn/Gs·|Ys − Yopt|². The search is seeded by the lossless
     optimum on the mismatch circle, then runs a deterministic log grid with
     three refinements. The −12 dB target leaves 2 dB at the band centre for
     the band edges. It is a bench policy, recorded with the result.
3. **Output synthesis**. Lc (5 nH, or an EM geometry) is followed by the
   committed 100 pF `Cout`, a shunt Cp at `rfout` and a series Cs into 50 Ω,
   solved in closed form for a conjugate match at f_mid. A geometry is
   infeasible when it would need Cp < 0. The two-element Lc + series C
   solution is also solved and recorded for information only.
4. **Verification**. Each (candidate, Q case) pair is rendered as one deck
   and run once at the nominal cell: 12 decks. The solver's unilateral
   predictions are recorded beside the simulated numbers as a cross-check.
   For the Q = 20, Q = 10 and EM cases they agree to within 0.025 dB on NF.
   At f_mid, the simulated S22 is below −50 dB for every candidate, and the
   simulated S11 is below −50 dB for the power-target candidates (`lp_power`,
   `hp_power`). `lp_noise` lands on its −12 dB design target: −12.0 dB
   simulated.
5. **Reduction and ranking** use `matching_solver.py reduce`. The ranking
   rule is: rows met on the `q10` case, then lower worst-case NF290, then
   higher broadband μ.

**Inductor feasibility** compares each required L with the extracted
geometries' L at 2.44175 GHz, in four classes:

- within ±15 % of an extracted geometry: "EM-backed";
- inside the extracted L range: needs a non-extracted geometry, i.e. the
  EM-corrected analytic extrapolation;
- above the largest extracted L: a larger spiral, a bondwire or an off-chip
  part;
- below the smallest extracted L.

## Limits

- **One PVT cell** (see the caveat at the top).
- **Unilateral synthesis.** |S12| ≈ −95 dB makes this exact for practical
  purposes, except when the output Q is extreme (the `ideal` case). The
  verification decks are fully bilateral.
- **Constant-R Q model.** The loss resistor is sized at the band centre, so
  skin effect and substrate loss are not frequency-dependent, apart from the
  EM model's own ladder.
- **Ideal capacitors.** No MIM capacitor model or Q, no pads, ESD,
  bondwires or package.
- **Ideal choke in the feed what-if.** The probe's choke is ideal, so the
  probe shows what the R3b branch costs. It does not show what a realizable
  replacement would deliver.
- **μ margins are ppm-scale** at the 10 MHz sweep edge. The S-parameter
  tables carry 10 significant digits (`option numdgt=10`), so μ is resolved
  to roughly 1e-10.
  - The finite-Q margins (+8.8e-8 to +3.6e-7) are well above that
    resolution. They are resolved, just small.
  - The ideal-inductor `lp_*` deficits (about −4.7e-12) are below that
    resolution, so they read as μ = 1, the lossless limit.
  - The reducer counts points with μ ≤ 1 without a resolution tolerance.
    Its ideal-case counts therefore include those μ = 1 points.
- **Floating DC node in the verification decks** (see "Bench definitions").
  The OP comes from ngspice's transient-op fallback. The small-signal
  numbers do not depend on it. Record `20261010-213251-3ccb391` (#190)
  measured this: the fallback OP differs from the converged one by 0.04 %
  in I_C1, and S22 mid moves by up to 0.27 dB (see "DC reference on xout").
- **Simulator identity is a version banner only.** This record ran on an
  ngspice-46 binary borrowed from another sweep's build, because provisioned
  workers ship ngspice 42, which cannot load the PSP103 OSDI v0.4 builds.
  The record's Simulator line carries only the version banner. Future
  records should also capture the binary's sha256 and build identity
  (configure flags or source commit).

## Regenerating

```bash
export PDK_ROOT=/path/to/ihp-open-pdk PDK=ihp-sg13g2   # or let sim/env.sh find it
MATCH_NGSPICE=/path/to/ngspice-46/bin/ngspice \
  sim/lna-matching-feasibility/run_matching_study.sh
```

This needs ngspice ≥ 46, because the PDK's PSP103 OSDI builds target OSDI
v0.4, plus the OSDI models (`sim/tools/build-osdi.sh`) and python3. The run
is 14 sequential single-process ngspice invocations, about 30 s, with no
parallelism and no grid. The runner refuses an older ngspice, a missing
PDK or OSDI model, or a modified EM model copy, with exit code 3.

The DC-reference sensitivity comparison (#190) is regenerated with
`sim/lna-matching-feasibility/run_dc_reference_study.sh` (it needs the
characterization data of record `20261010-201010-6aca84c`). On a shared host
use `DCREF_STAGE=gen`, run the printed `ngspice -b` commands one at a time,
then `DCREF_STAGE=finish DCREF_RECORD_ID=<id>`.

Unit tests are stdlib-only, PDK-free and need no ngspice. They include a
byte-for-byte replay of every committed record:

```bash
python3 -I -m unittest discover -s sim/lna-matching-feasibility/tests -v
```

## Files

- `run_matching_study.sh`: the cold-start entry point.
- `run_dc_reference_study.sh`: the DC-reference sensitivity runner (#190).
- `matching_solver.py`: deck generation (`gen-char`), synthesis (`solve`,
  optionally with `--xout-rdc`), reduction (`reduce`) and the DC-reference
  comparison (`sensitivity`); stdlib only.
- `testbench/tb_match_char.spice.tmpl`, `tb_match_feedprobe.spice.tmpl`,
  `tb_match_verify.spice.tmpl`: the deck templates.
- `tests/test_matching_solver.py`: unit tests and the committed-record
  replay.
- `netlist-snapshots/<id>/`, `corners/<id>/`, `records/<id>*`: append-only
  evidence, per `../README.md`.
