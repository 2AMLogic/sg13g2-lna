#### DC-reference sensitivity (nominal cell; baseline = historical floating-xout bench, record `20261010-201010-6aca84c`)

mu resolution floor 1e-09 (wrdata `numdgt=10`); a change is MATERIAL if it moves the broadband mu minimum by more than 10% of the baseline margin (mu - 1), drives the margin to the resolution floor, or moves the frequency of the minimum.

**finite-Q cases**

| Candidate | Q case | R_xout (Ohm) | I_C1 base / new (mA) | S11 mid base / new (dB) | S22 mid base / new (dB) | S21 mid base / new (dB) | dNF290 mid (dB) | dNF290 worst (dB) | mu min base | mu min new | f(mu min) base / new (Hz) | dmu / margin | verdict | OP convergence (new / base) |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| hp_power | q10 | 1e+09 | 3.93868 / 3.94021 | -68.36 / -66.25 | -62.95 / -62.70 | 20.4451 / 20.4489 | -3.676e-04 | -3.691e-04 | 1.0000003575 | 1.0000003575 | 1e+07 / 1e+07 | 1.163e-04 | within 10% of the baseline margin (|dmu| below table resolution) | normal / fallback/flagged |
| hp_power | q10 | 1e+11 | 3.93868 / 3.94021 | -68.36 / -66.25 | -62.95 / -62.70 | 20.4451 / 20.4489 | -3.676e-04 | -3.691e-04 | 1.0000003575 | 1.0000003574 | 1e+07 / 1e+07 | -3.471e-05 | within 10% of the baseline margin (|dmu| below table resolution) | normal / fallback/flagged |
| lp_noise | q10 | 1e+09 | 3.93844 / 3.94021 | -12.00 / -12.00 | -63.37 / -63.64 | 20.2365 / 20.2410 | -3.147e-04 | -3.148e-04 | 1.0000003575 | 1.0000003575 | 1e+07 / 1e+07 | 2.801e-05 | within 10% of the baseline margin (|dmu| below table resolution) | normal / fallback/flagged |
| lp_noise | q10 | 1e+11 | 3.93844 / 3.94021 | -12.00 / -12.00 | -63.37 / -63.64 | 20.2365 / 20.2410 | -3.147e-04 | -3.148e-04 | 1.0000003575 | 1.0000003575 | 1e+07 / 1e+07 | 3.479e-08 | within 10% of the baseline margin (|dmu| below table resolution) | normal / fallback/flagged |

**ideal cases**

| Candidate | Q case | R_xout (Ohm) | I_C1 base / new (mA) | S11 mid base / new (dB) | S22 mid base / new (dB) | S21 mid base / new (dB) | dNF290 mid (dB) | dNF290 worst (dB) | mu min base | mu min new | f(mu min) base / new (Hz) | dmu / margin | verdict | OP convergence (new / base) |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| hp_power | ideal | 1e+09 | 3.94032 / 3.94030 | -18.41 / -18.13 | -23.64 / -21.22 | 44.1649 / 44.4344 | -2.153e-04 | -2.118e-04 | 0.9999992329 | 0.9999992329 | 1e+07 / 1e+07 | -0.000e+00 | baseline mu < 1 (resolved deficit at the sweep edge); change reported, no margin claimed | normal / fallback/flagged |
| hp_power | ideal | 1e+11 | 3.94032 / 3.94030 | -18.41 / -18.13 | -23.64 / -21.22 | 44.1649 / 44.4350 | -2.153e-04 | -2.118e-04 | 0.9999992329 | 0.9999992329 | 1e+07 / 1e+07 | -0.000e+00 | baseline mu < 1 (resolved deficit at the sweep edge); change reported, no margin claimed | normal / fallback/flagged |
| lp_noise | ideal | 1e+09 | 3.94031 / 3.94030 | -10.28 / -10.23 | -27.61 / -25.16 | 43.7477 / 44.0685 | -2.748e-04 | -2.766e-04 | 1.0000000000 | 0.9999999999 | 1.33352e+08 / 6.68344e+08 | n/a | mu = 1 to table resolution (lossless limit); no resolved margin to protect | normal / fallback/flagged |
| lp_noise | ideal | 1e+11 | 3.94031 / 3.94030 | -10.28 / -10.23 | -27.61 / -25.16 | 43.7477 / 44.0691 | -2.748e-04 | -2.766e-04 | 1.0000000000 | 0.9999999999 | 1.33352e+08 / 6.68344e+08 | n/a | mu = 1 to table resolution (lossless limit); no resolved margin to protect | normal / fallback/flagged |

**Dependence on the resistor value** (largest minus smallest R of the same candidate / Q case; this is the part of the change that the resistor itself can be responsible for)

| Candidate | Q case | R pair (Ohm) | dI_C1 (A) | dS11 mid (dB) | dS22 mid (dB) | dS21 mid (dB) | dNF290 worst (dB) | dmu min | mu-min frequency same |
|---|---|---|---|---|---|---|---|---|---|
| hp_power | ideal | 1e+09 / 1e+11 | 0.00e+00 | 5.86e-04 | 3.11e-03 | 5.85e-04 | 0.00e+00 | 0.00e+00 | yes |
| hp_power | q10 | 1e+09 / 1e+11 | 0.00e+00 | 3.57e-06 | 8.12e-04 | 3.26e-06 | 0.00e+00 | -5.40e-11 | yes |
| lp_noise | ideal | 1e+09 / 1e+11 | 0.00e+00 | 1.30e-04 | 4.53e-03 | 5.81e-04 | 0.00e+00 | 0.00e+00 | yes |
| lp_noise | q10 | 1e+09 / 1e+11 | 0.00e+00 | 2.22e-09 | 2.54e-04 | 3.26e-06 | 0.00e+00 | -1.00e-11 | yes |

