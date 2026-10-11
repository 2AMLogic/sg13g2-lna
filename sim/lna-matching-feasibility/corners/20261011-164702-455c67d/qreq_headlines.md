#### Input-Q requirements map (PREDICTIONS; retained #198 characterization, Le = 0.6 nH, Le/Lc/output loss fixed at the retained Q = 10 convention)

| Arm | Input Q | Lb / Cp | pred NF290 mid / worst (dB) | pred S11 mid / worst (dB) | crosses 1.5 / 1.2 (worst) |
|---|---|---|---|---|---|
| `em5_cmim` | 5 | 5.740 nH / 0.570 pF | 2.944 / **2.975** | -12.00 / -11.34 | no / no |
| `em5_cmim` | 10 (Q10 replay ok) | 6.986 nH / 0.473 pF | 2.536 / **2.563** | -12.00 / -11.45 | no / no |
| `em5_cmim` | 20 | 7.763 nH / 0.420 pF | 2.312 / **2.345** | -12.00 / -11.44 | no / no |
| `em5_cmim` | 40 | 8.184 nH / 0.397 pF | 2.192 / **2.230** | -12.00 / -11.49 | no / no |
| `em5_cmim` | lossless | 8.629 nH / 0.372 pF | 2.066 / **2.109** | -12.00 / -11.48 | no / no |
| `ideal_choke` | 5 | 7.696 nH / 0.473 pF | 2.330 / **2.340** | -12.00 / -11.32 | no / no |
| `ideal_choke` | 10 (Q10 replay ok) | 10.778 nH / 0.338 pF | 1.753 / **1.759** | -12.00 / -11.30 | no / no |
| `ideal_choke` | 20 | 13.104 nH / 0.273 pF | 1.334 / **1.339** | -12.00 / -11.20 | yes / no |
| `ideal_choke` | 40 | 14.500 nH / 0.243 pF | 1.054 / **1.060** | -12.00 / -11.13 | yes / yes |
| `ideal_choke` | lossless | 16.064 nH / 0.215 pF | 0.702 / **0.709** | -12.00 / -11.07 | yes / yes |

#### Threshold crossings (predictions within the sampled topology/search)

- `em5_cmim` NF290 worst <= 1.5: not reached within tested range; lossless bound crosses: no
- `em5_cmim` NF290 worst <= 1.2: not reached within tested range; lossless bound crosses: no
- `ideal_choke` NF290 worst <= 1.5: min tested Q 20
- `ideal_choke` NF290 worst <= 1.2: min tested Q 40

#### Feed-isolation bracket (measured; brackets are HYPOTHETICAL REQUIREMENT PROXIES, the retained EM model is the control)

| Arm | Rqbr (Ohm) | isolation \|Ztank\| mid / band-min (Ohm) | NFmin@290 Q10 mid / worst (dB) | IC1 (mA) | dIC1 vs control | DC flags |
|---|---|---|---|---|---|---|
| `em5_cmim` |  | 797.9 / 733.0 | 1.513 / **1.545** | 3.93699 | +0.000 % | none |
| `ideal_choke` |  | 797.9 / 733.0 | 0.476 / **0.476** | 3.94030 | +0.084 % | none |
| `bracket_r400` | 400.0 | 266.4 / 262.0 | 1.977 / **1.986** | 3.93705 | +0.002 % | none |
| `bracket_r200` | 200.0 | 159.9 / 158.5 | 2.158 / **2.162** | 3.93710 | +0.003 % | none |
| `bracket_r100` | 100.0 | 88.9 / 88.5 | 2.317 / **2.317** | 3.93720 | +0.005 % | none |
| `ideal_choke` |  | infinite (ideal 1 uH) | 0.476 / **0.476** | (retained) |  | none |

Probe control arm vs retained-derived tank: |Z| mid 797.9 Ohm measured vs 797.9 Ohm derived (declared tolerance 1%).

#### Boundary verification (declared rule; verified numbers, still hypothetical requirement proxies)

| Boundary | Arm | Input Q | pred NF290 worst (11f) | verified NF290 mid / worst (21f) | verified worst (11f) | residual (11f) | S11 / S22 worst | \|S21\| min | mu bb min |
|---|---|---|---|---|---|---|---|---|---|
| `cmim_lossless` | `em5_cmim` | lossless | 2.109 | 2.072 / 2.115 | 2.115 | +0.006 | -11.45 / -15.63 | 26.70 | 1.0000003574 |
| `choke_q40` | `ideal_choke` | 40 | 1.060 | 1.057 / 1.063 | 1.063 | +0.003 | -11.05 / -15.50 | 30.99 | 1.0000003574 |
| `choke_lossless` | `ideal_choke` | lossless | 0.709 | 0.704 / 0.712 | 0.712 | +0.002 | -10.97 / -15.46 | 31.85 | 0.9994731627 |

#### Requirements summary (sampled; predictions and proxies, not feasibility)

- `em5_cmim` at the 1.5 dB row: not reached within the tested input-Q range; the lossless bound does not cross.
- `em5_cmim` at the 1.2 dB planning limit: not reached within the tested input-Q range; the lossless bound does not cross.
- `ideal_choke` at the 1.5 dB row: input Q >= 20 (tested).
- `ideal_choke` at the 1.2 dB planning limit: input Q >= 40 (tested).
- Feed isolation at the 1.2 dB planning limit (DUT NFmin@290 worst): not reached at any sampled finite isolation (the unbracketed retained tank included); the only sampled point at or below the planning limit is the ideal-choke diagnostic bound.

#### Campaign verdict (bench policy; only an unmodified-model verified point can GO)

- Policy limit (declared): verified matched NF290 worst-in-band <= 1.5 - 0.3 = 1.20 dB; the ratified row is 1.5 dB.
- **Verdict: NO-GO**; binding constraint: `noise_floor`; failing gates: noise_floor.
- Physical candidate (the `em5_cmim` control verification): NF290 worst 2.570 dB, DUT NFmin@290 worst 1.545 dB, budget against the 1.5 dB row -1.070 dB.
