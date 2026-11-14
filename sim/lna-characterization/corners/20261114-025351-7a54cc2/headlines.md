### Variant `ideal` -- ideal Le and Lc (as committed) (45 cells)

- |S21| mid-band [dB]: min 10.308 @ wcs/125C/1.62V, max 12.285 @ bcs/-40C/1.98V
- NF @290 K mid-band [dB]: min 1.843 @ bcs/-40C/1.98V, max 3.775 @ wcs/125C/1.62V
- NFmin (sp) mid-band [dB]: min 2.075 @ bcs/-40C/1.98V, max 2.727 @ wcs/125C/1.62V
- |S11| mid-band [dB]: min -3.228 @ wcs/125C/1.62V, max -2.964 @ bcs/-40C/1.98V
- |S22| mid-band [dB]: min -0.006 @ wcs/125C/1.62V, max -0.003 @ bcs/-40C/1.98V
- mu min 10 MHz..30 GHz: min 1.0000 @ bcs/-40C/1.98V, max 1.0000 @ wcs/125C/1.80V
- max |S22| 10 MHz..30 GHz: min 1.0000 @ wcs/125C/1.62V, max 1.0000 @ bcs/125C/1.98V
- NF @290 K worst SAMPLED point [dB]: max 3.776 at 2.4 GHz, wcs/125C/1.62V -- noise lin 11 pts 2.4..2.4835 GHz (8.35 MHz spacing); sampled maximum, not a continuous-band bound -- a peak narrower than the spacing can be missed
- I_C1 [mA]: min 3.6573 @ wcs/125C/1.62V, max 4.1511 @ bcs/-40C/1.98V
- DC emitter lift v(e1) [mV]: min -0.000 @ sf/27C/1.98V, max 0.000 @ typ/27C/1.62V

### Variant `lc_em` -- Lc = EM-extracted 5-turn model, Le ideal (45 cells)

- |S21| mid-band [dB]: min 10.022 @ wcs/125C/1.62V, max 12.169 @ bcs/-40C/1.98V
- NF @290 K mid-band [dB]: min 1.865 @ bcs/-40C/1.98V, max 3.833 @ wcs/125C/1.62V
- NFmin (sp) mid-band [dB]: min 2.094 @ bcs/-40C/1.98V, max 2.764 @ wcs/125C/1.62V
- |S11| mid-band [dB]: min -3.228 @ wcs/125C/1.62V, max -2.964 @ bcs/-40C/1.98V
- |S22| mid-band [dB]: min -1.171 @ wcs/125C/1.62V, max -0.747 @ bcs/-40C/1.98V
- mu min 10 MHz..30 GHz: min 1.0134 @ bcs/-40C/1.98V, max 1.0167 @ wcs/125C/1.62V
- max |S22| 10 MHz..30 GHz: min 0.9811 @ wcs/125C/1.62V, max 0.9857 @ bcs/-40C/1.98V
- NF @290 K worst SAMPLED point [dB]: max 3.835 at 2.4 GHz, wcs/125C/1.62V -- noise lin 11 pts 2.4..2.4835 GHz (8.35 MHz spacing); sampled maximum, not a continuous-band bound -- a peak narrower than the spacing can be missed
- I_C1 [mA]: min 3.6573 @ wcs/125C/1.62V, max 4.1510 @ bcs/-40C/1.98V
- DC emitter lift v(e1) [mV]: min -0.000 @ typ/-40C/1.80V, max 0.000 @ wcs/27C/1.98V
- Bias attribution: I_C1 within +/-0.05 % of `ideal` at every cell -- the deltas above are inductor loss, not a bias shift.

### Variant `le_q20` -- Le + series R for Q=20 @ 2.44175 GHz, Lc ideal (45 cells)

- |S21| mid-band [dB]: min 9.974 @ wcs/125C/1.62V, max 11.973 @ bcs/-40C/1.98V
- NF @290 K mid-band [dB]: min 1.909 @ bcs/-40C/1.98V, max 3.844 @ wcs/125C/1.62V
- NFmin (sp) mid-band [dB]: min 2.132 @ bcs/-40C/1.98V, max 2.768 @ wcs/125C/1.62V
- |S11| mid-band [dB]: min -3.200 @ wcs/125C/1.62V, max -2.953 @ bcs/-40C/1.98V
- |S22| mid-band [dB]: min -0.006 @ wcs/125C/1.62V, max -0.003 @ bcs/-40C/1.98V
- mu min 10 MHz..30 GHz: min 1.0000 @ bcs/-40C/1.98V, max 1.0000 @ wcs/125C/1.80V
- max |S22| 10 MHz..30 GHz: min 1.0000 @ wcs/125C/1.62V, max 1.0000 @ bcs/125C/1.80V
- NF @290 K worst SAMPLED point [dB]: max 3.845 at 2.4 GHz, wcs/125C/1.62V -- noise lin 11 pts 2.4..2.4835 GHz (8.35 MHz spacing); sampled maximum, not a continuous-band bound -- a peak narrower than the spacing can be missed
- I_C1 [mA]: min 3.4958 @ wcs/125C/1.62V, max 3.8739 @ bcs/125C/1.98V
- DC emitter lift v(e1) [mV]: min 2.693 @ wcs/125C/1.62V, max 2.975 @ bcs/125C/1.98V
- Bias attribution: **I_C1 shifts up to -8.97 % vs `ideal`** (worst bcs/-40C/1.98V). The RF deltas above are NOT inductor loss alone -- this variant's loss resistor is in series with Le and carries Q1's DC emitter current, adding real emitter degeneration. See README 'Bias confound'.

### Variant `le_q10` -- Le + series R for Q=10 @ 2.44175 GHz, Lc ideal (45 cells)

- |S21| mid-band [dB]: min 9.646 @ wcs/125C/1.62V, max 11.651 @ bcs/-40C/1.98V
- NF @290 K mid-band [dB]: min 1.973 @ bcs/-40C/1.98V, max 3.911 @ wcs/125C/1.62V
- NFmin (sp) mid-band [dB]: min 2.187 @ bcs/-40C/1.98V, max 2.807 @ wcs/125C/1.62V
- |S11| mid-band [dB]: min -3.174 @ wcs/125C/1.62V, max -2.941 @ bcs/-40C/1.98V
- |S22| mid-band [dB]: min -0.006 @ wcs/125C/1.62V, max -0.003 @ bcs/-40C/1.98V
- mu min 10 MHz..30 GHz: min 1.0000 @ bcs/-40C/1.62V, max 1.0000 @ wcs/125C/1.80V
- max |S22| 10 MHz..30 GHz: min 1.0000 @ wcs/125C/1.62V, max 1.0000 @ bcs/125C/1.62V
- NF @290 K worst SAMPLED point [dB]: max 3.912 at 2.4 GHz, wcs/125C/1.62V -- noise lin 11 pts 2.4..2.4835 GHz (8.35 MHz spacing); sampled maximum, not a continuous-band bound -- a peak narrower than the spacing can be missed
- I_C1 [mA]: min 3.3154 @ bcs/-40C/1.62V, max 3.6604 @ bcs/125C/1.98V
- DC emitter lift v(e1) [mV]: min 5.088 @ bcs/-40C/1.62V, max 5.623 @ bcs/125C/1.98V
- Bias attribution: **I_C1 shifts up to -16.10 % vs `ideal`** (worst bcs/-40C/1.98V). The RF deltas above are NOT inductor loss alone -- this variant's loss resistor is in series with Le and carries Q1's DC emitter current, adding real emitter degeneration. See README 'Bias confound'.

### Variant `le_q5` -- Le + series R for Q=5 @ 2.44175 GHz, Lc ideal (45 cells)

- |S21| mid-band [dB]: min 9.005 @ wcs/125C/1.62V, max 10.997 @ bcs/-40C/1.98V
- NF @290 K mid-band [dB]: min 2.094 @ bcs/-40C/1.98V, max 4.041 @ wcs/125C/1.62V
- NFmin (sp) mid-band [dB]: min 2.289 @ bcs/-40C/1.98V, max 2.884 @ wcs/125C/1.62V
- |S11| mid-band [dB]: min -3.125 @ wcs/125C/1.62V, max -2.915 @ bcs/-40C/1.98V
- |S22| mid-band [dB]: min -0.006 @ wcs/125C/1.62V, max -0.003 @ bcs/-40C/1.98V
- mu min 10 MHz..30 GHz: min 1.0000 @ bcs/125C/1.98V, max 1.0000 @ wcs/125C/1.80V
- max |S22| 10 MHz..30 GHz: min 1.0000 @ wcs/-40C/1.62V, max 1.0000 @ bcs/125C/1.62V
- NF @290 K worst SAMPLED point [dB]: max 4.042 at 2.4 GHz, wcs/125C/1.62V -- noise lin 11 pts 2.4..2.4835 GHz (8.35 MHz spacing); sampled maximum, not a continuous-band bound -- a peak narrower than the spacing can be missed
- I_C1 [mA]: min 2.9145 @ bcs/-40C/1.62V, max 3.3139 @ bcs/125C/1.98V
- DC emitter lift v(e1) [mV]: min 8.946 @ bcs/-40C/1.62V, max 10.181 @ bcs/125C/1.98V
- Bias attribution: **I_C1 shifts up to -26.87 % vs `ideal`** (worst bcs/-40C/1.98V). The RF deltas above are NOT inductor loss alone -- this variant's loss resistor is in series with Le and carries Q1's DC emitter current, adding real emitter degeneration. See README 'Bias confound'.

### Variant `lc_em_le_q10` -- Lc = EM 5-turn model AND Le Q=10 (45 cells)

- |S21| mid-band [dB]: min 9.359 @ wcs/125C/1.62V, max 11.535 @ bcs/-40C/1.98V
- NF @290 K mid-band [dB]: min 1.998 @ bcs/-40C/1.98V, max 3.977 @ wcs/125C/1.62V
- NFmin (sp) mid-band [dB]: min 2.208 @ bcs/-40C/1.98V, max 2.849 @ wcs/125C/1.62V
- |S11| mid-band [dB]: min -3.174 @ wcs/125C/1.62V, max -2.941 @ bcs/-40C/1.98V
- |S22| mid-band [dB]: min -1.171 @ wcs/125C/1.62V, max -0.746 @ bcs/-40C/1.98V
- mu min 10 MHz..30 GHz: min 1.0133 @ bcs/-40C/1.98V, max 1.0167 @ wcs/125C/1.62V
- max |S22| 10 MHz..30 GHz: min 0.9811 @ wcs/125C/1.62V, max 0.9858 @ bcs/-40C/1.98V
- NF @290 K worst SAMPLED point [dB]: max 3.978 at 2.4 GHz, wcs/125C/1.62V -- noise lin 11 pts 2.4..2.4835 GHz (8.35 MHz spacing); sampled maximum, not a continuous-band bound -- a peak narrower than the spacing can be missed
- I_C1 [mA]: min 3.3155 @ bcs/-40C/1.62V, max 3.6603 @ bcs/125C/1.98V
- DC emitter lift v(e1) [mV]: min 5.089 @ bcs/-40C/1.62V, max 5.623 @ bcs/125C/1.98V
- Bias attribution: **I_C1 shifts up to -16.11 % vs `ideal`** (worst bcs/-40C/1.98V). The RF deltas above are NOT inductor loss alone -- this variant's loss resistor is in series with Le and carries Q1's DC emitter current, adding real emitter degeneration. See README 'Bias confound'.

## Ideal-baseline ratified-row coverage (sampled bench results only)

- Coverage: **COMPLETE** (grid `full`, 45 expected cells per analysis; 0 validation issue(s))

- **In-band minimum |S21| [dB]** -- FAILS target at the worst sampled cell
  - target: > 15 dB (strict inequality; equality fails) (spec/target-spec.md: Gain (S21))
  - worst: 10.2748 @ wcs/125C/1.62V; valid/expected cells 45/45
  - measurement: `sp_band.s21_db_min` (min over cells); sampling: sp lin 11 pts 2.4-2.4835 GHz; vecmin(db(s_2_1)) over the 11 points
  - ports: 50 Ohm reference at both ports (sp port sources with portnum/z0; 50 Ohm Thevenin source with noiseless Rs/RL for .noise)
- **Worst in-band |S11| [dB]** -- FAILS target at the worst sampled cell
  - target: < -10 dB (strict inequality; equality fails) (spec/target-spec.md: Input match (S11))
  - worst: -2.96163 @ bcs/-40C/1.98V; valid/expected cells 45/45
  - measurement: `sp_band.s11_db_worst` (max over cells); sampling: sp lin 11 pts 2.4-2.4835 GHz; vecmax(db(s_1_1)) over the 11 points
  - ports: 50 Ohm reference at both ports (sp port sources with portnum/z0; 50 Ohm Thevenin source with noiseless Rs/RL for .noise)
- **Worst in-band |S22| [dB]** -- FAILS target at the worst sampled cell
  - target: < -10 dB (strict inequality; equality fails) (spec/target-spec.md: Output match (S22))
  - worst: -0.003347 @ bcs/-40C/1.98V; valid/expected cells 45/45
  - measurement: `sp_band.s22_db_worst` (max over cells); sampling: sp lin 11 pts 2.4-2.4835 GHz; vecmax(db(s_2_2)) over the 11 points
  - ports: 50 Ohm reference at both ports (sp port sources with portnum/z0; 50 Ohm Thevenin source with noiseless Rs/RL for .noise)
- **Broadband minimum mu (Edwards-Sinsky)** -- FAILS target at the worst sampled cell
  - target: > 1 (strict inequality; equality fails) (spec/target-spec.md: Stability)
  - worst: 0.999996 @ bcs/-40C/1.98V; valid/expected cells 45/45
  - measurement: `sp_stab.mu_min` (min over cells); sampling: sp dec 40 pts/decade 10 MHz-30 GHz; vecmin(mu) over the sweep
  - ports: 50 Ohm reference at both ports (sp port sources with portnum/z0; 50 Ohm Thevenin source with noiseless Rs/RL for .noise)
- **NF at T0 = 290 K, band maximum of 11 sampled points [dB]** -- FAILS target at the worst sampled cell
  - target: < 1.5 dB (strict inequality; equality fails) (spec/target-spec.md: Noise figure (NF))
  - worst: 3.77586 @ wcs/125C/1.62V at 2.4 GHz; valid/expected cells 45/45
  - measurement: `noise.nf290_db_worst` (max over cells); sampling: noise lin 11 pts 2.4..2.4835 GHz (8.35 MHz spacing); sampled maximum, not a continuous-band bound -- a peak narrower than the spacing can be missed
  - ports: 50 Ohm reference at both ports (sp port sources with portnum/z0; 50 Ohm Thevenin source with noiseless Rs/RL for .noise)

### Not covered / disclosures

- NF290 is the maximum over a discrete frequency grid (the same grid for every variant; see the row's sampling text); a peak narrower than the grid spacing can be missed, so this is not continuous-band coverage. Records produced before issue #134 are three-point (lo/mid/hi) and are not comparable as full-grid results.
- ngspice sp-analysis port NF / NFmin (nf_sp_db_*, nfmin_sp_db_*) are distinct from the ratified T0 = 290 K value (nf290_db_*); only nf290_db_worst is compared with the NF target.
- DC bias current and DC power are NOT measured by these three requests; the Power and bias rows are not covered.
- Two-tone IIP3 is NOT measured by these three requests; the IIP3 row is not covered.
- Supply (VDD) and band are configured bench conditions, not independently measured compliance results.
- Comparisons describe sampled bench results only (the `ideal` variant is the frozen UNMATCHED pre-#27 DUT with ideal passives; `matched` is the committed design/netlist/lna.spice with its modelled finite-Q passives). A numeric pass does not establish matched physical performance, complete spec compliance, signoff, or T1 item 5.
- No missing observable is inferred from another campaign or DUT.

