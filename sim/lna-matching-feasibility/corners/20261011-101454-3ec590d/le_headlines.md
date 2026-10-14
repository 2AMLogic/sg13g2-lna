#### 1 nH controls vs record `20261010-233800-d1312cc` (declared tolerances)

| Control | Quantity | This study | Record | abs diff | Tolerance | Within |
|---|---|---|---|---|---|---|
| committed | nf290_db_worst | 3.335299067 | 3.335299067 | 0.000e+00 | 0.001 | yes |
| committed | nf290_db_mid | 3.312960726 | 3.312960726 | 0.000e+00 | 0.001 | yes |
| committed | s11_db_worst | -11.54694688 | -11.54694688 | 0.000e+00 | 0.001 | yes |
| committed | s22_db_worst | -15.61018514 | -15.61018514 | 0.000e+00 | 0.001 | yes |
| committed | s21_db_min | 20.0674723 | 20.0674723 | 0.000e+00 | 0.001 | yes |
| committed | mu_bb_min | 1.000000357 | 1.000000357 | 0.000e+00 | 1e-09 | yes |
| committed | ic1_rel | 0.00394021 | 0.00394021 | 0.000e+00 | 1e-05 | yes |
| committed | input_series_rel | 4.563740739e-09 | 4.563740739e-09 | 0.000e+00 | 1e-06 | yes |
| committed | input_shunt_rel | 6.259953541e-13 | 6.259953541e-13 | 0.000e+00 | 1e-06 | yes |
| ideal_choke | nf290_db_worst | 1.807966612 | 1.807966612 | 0.000e+00 | 0.001 | yes |
| ideal_choke | nf290_db_mid | 1.798964442 | 1.798964442 | 0.000e+00 | 0.001 | yes |
| ideal_choke | s11_db_worst | -11.27691744 | -11.27691744 | 0.000e+00 | 0.001 | yes |
| ideal_choke | s22_db_worst | -15.61253407 | -15.61253407 | 0.000e+00 | 0.001 | yes |
| ideal_choke | s21_db_min | 26.43560063 | 26.43560063 | 0.000e+00 | 0.001 | yes |
| ideal_choke | mu_bb_min | 1.000000357 | 1.000000357 | 0.000e+00 | 1e-09 | yes |
| ideal_choke | ic1_rel | 0.00394021 | 0.00394021 | 0.000e+00 | 1e-05 | yes |
| ideal_choke | input_series_rel | 1.106829074e-08 | 1.106829074e-08 | 0.000e+00 | 1e-06 | yes |
| ideal_choke | input_shunt_rel | 3.417631188e-13 | 3.417631188e-13 | 0.000e+00 | 1e-06 | yes |
| em5_cideal | nf290_db_worst | 2.610428734 | 2.610428734 | 0.000e+00 | 0.001 | yes |
| em5_cideal | nf290_db_mid | 2.580779463 | 2.580779463 | 0.000e+00 | 0.001 | yes |
| em5_cideal | s11_db_worst | -11.40641994 | -11.40641994 | 0.000e+00 | 0.001 | yes |
| em5_cideal | s22_db_worst | -15.62803212 | -15.62803212 | 0.000e+00 | 0.001 | yes |
| em5_cideal | s21_db_min | 22.95551489 | 22.95551489 | 0.000e+00 | 0.001 | yes |
| em5_cideal | mu_bb_min | 1.000000357 | 1.000000357 | 0.000e+00 | 1e-09 | yes |
| em5_cideal | ic1_rel | 0.0039369 | 0.0039369 | 0.000e+00 | 1e-05 | yes |
| em5_cideal | input_series_rel | 7.078094158e-09 | 7.078094158e-09 | 0.000e+00 | 1e-06 | yes |
| em5_cideal | input_shunt_rel | 4.787149056e-13 | 4.787149056e-13 | 0.000e+00 | 1e-06 | yes |

#### Per point: noise floor vs verified matched NF (nominal cell; T0 = 290 K; `lp_noise` Q = 10 re-synthesized per point)

| Point | Le (nH) | Lb / Cp | NFmin@290 ideal Le mid / worst | NFmin@290 Le Q10 mid / worst | NFmin@290 Le Q5 mid | Verified NF290 mid / worst | S11 / S22 worst | \|S21\| min | mu bb min | IC1 (mA) | DC flags | Gates failing |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| `committed_le1p00` | 1 | 4.564 nH / 0.626 pF | 2.445 / 2.445 | 2.517 / 2.520 | 2.584 | 3.313 / **3.335** | -11.55 / -15.61 | 20.07 | 1.0000003575 | 3.94021 | none | noise_floor |
| `ideal_choke_le1p00` | 1 | 11.068 nH / 0.342 pF | 0.467 / 0.467 | 0.481 / 0.482 | 0.494 | 1.799 / **1.808** | -11.28 / -15.61 | 26.44 | 1.0000003575 | 3.94021 | none | noise_match_penalty |
| `em5_cideal_le1p00` | 1 | 7.078 nH / 0.479 pF | 1.481 / 1.514 | 1.526 / 1.558 | 1.567 | 2.581 / **2.610** | -11.41 / -15.63 | 22.96 | 1.0000003575 | 3.93690 | none | noise_floor |
| `committed_le0p10` | 0.1 | 4.721 nH / 0.578 pF | 2.454 / 2.454 | 2.461 / 2.461 | 2.468 | 3.296 / **3.317** | -11.50 / -15.61 | 24.80 | 1.0000003573 | 3.94021 | none | noise_floor |
| `committed_le0p30` | 0.3 | 4.586 nH / 0.603 pF | 2.452 / 2.452 | 2.474 / 2.474 | 2.494 | 3.268 / **3.289** | -11.54 / -15.61 | 23.90 | 1.0000003573 | 3.94021 | none | noise_floor |
| `committed_le0p60` | 0.6 | 4.532 nH / 0.617 pF | 2.448 / 2.449 | 2.492 / 2.493 | 2.533 | 3.273 / **3.294** | -11.54 / -15.61 | 22.26 | 1.0000003574 | 3.94021 | none | noise_floor |
| `em5_cmim_le0p10` | 0.1 | 7.484 nH / 0.427 pF | 1.489 / 1.521 | 1.494 / 1.526 | 1.498 | 2.637 / **2.666** | -11.46 / -15.63 | 27.88 | 1.0000003573 | 3.93690 | none | noise_floor |
| `em5_cmim_le0p30` | 0.3 | 7.164 nH / 0.441 pF | 1.488 / 1.520 | 1.501 / 1.533 | 1.514 | 2.566 / **2.595** | -11.23 / -15.63 | 26.86 | 1.0000003573 | 3.93690 | none | noise_floor |
| `em5_cmim_le0p60` | 0.6 | 6.986 nH / 0.473 pF | 1.486 / 1.518 | 1.513 / 1.545 | 1.538 | 2.544 / **2.570** | -11.43 / -15.63 | 25.10 | 1.0000003574 | 3.93690 | none | noise_floor |
| `em5_cmim_le1p00` | 1 | 7.069 nH / 0.479 pF | 1.484 / 1.516 | 1.529 / 1.560 | 1.570 | 2.583 / **2.612** | -11.41 / -15.63 | 22.95 | 1.0000003575 | 3.93690 | none | noise_floor |
| `ideal_choke_le0p10` | 0.1 | 12.934 nH / 0.259 pF | 0.468 / 0.468 | 0.469 / 0.469 | 0.471 | 1.982 / **1.983** | -11.25 / -15.51 | 32.28 | 1.0000003572 | 3.94021 | none | noise_match_penalty |
| `ideal_choke_le0p30` | 0.3 | 11.341 nH / 0.309 pF | 0.468 / 0.468 | 0.472 / 0.472 | 0.476 | 1.808 / **1.811** | -11.26 / -15.55 | 30.49 | 1.0000003573 | 3.94021 | none | noise_match_penalty |
| `ideal_choke_le0p60` | 0.6 | 10.778 nH / 0.338 pF | 0.467 / 0.467 | 0.476 / 0.476 | 0.484 | 1.757 / **1.763** | -11.26 / -15.59 | 28.50 | 1.0000003574 | 3.94021 | none | noise_match_penalty |

#### Band-centre NF decomposition (dB; `pred` terms are solver predictions, the rest simulated)

| Point | Zin (Le Q10) | Zopt (Le Q10) | Intrinsic floor (ideal Le) | + Le loss (Q10) | + mismatch (pred) | + input-network loss (pred) | + residual | = verified NF290 mid | Le feasibility |
|---|---|---|---|---|---|---|---|---|---|
| `committed_le1p00` | 282.6-41.6j | 87.6+2.9j | 2.445 | +0.072 | +0.197 | +0.579 | +0.020 | 3.313 | inside the extracted L range, nearest em4 (L ratio 0.22); needs a non-extracted geometry (EM-corrected analytic extrapolation) |
| `ideal_choke_le1p00` | 1159.2-1144.4j | 479.6+52.3j | 0.467 | +0.014 | +0.007 | +1.304 | +0.007 | 1.799 | inside the extracted L range, nearest em4 (L ratio 0.22); needs a non-extracted geometry (EM-corrected analytic extrapolation) |
| `em5_cideal_le1p00` | 548.7-276.6j | 149.0+12.3j | 1.481 | +0.045 | +0.171 | +0.872 | +0.012 | 2.581 | inside the extracted L range, nearest em4 (L ratio 0.22); needs a non-extracted geometry (EM-corrected analytic extrapolation) |
| `committed_le0p10` | 275.5-90.5j | 85.7+3.3j | 2.454 | +0.007 | +0.230 | +0.598 | +0.007 | 3.296 | near em1 (L ratio 1.03; EM-backed geometry) |
| `committed_le0p30` | 271.6-74.0j | 86.1+3.2j | 2.452 | +0.022 | +0.205 | +0.582 | +0.008 | 3.268 | inside the extracted L range, nearest em1 (L ratio 3.09); needs a non-extracted geometry (EM-corrected analytic extrapolation) |
| `committed_le0p60` | 274.4-55.5j | 86.7+3.1j | 2.448 | +0.044 | +0.193 | +0.575 | +0.012 | 3.273 | inside the extracted L range, nearest em1 (L ratio 6.18); needs a non-extracted geometry (EM-corrected analytic extrapolation) |
| `em5_cmim_le0p10` | 384.9-393.1j | 145.2+13.1j | 1.489 | +0.005 | +0.223 | +0.917 | +0.004 | 2.637 | near em1 (L ratio 1.03; EM-backed geometry) |
| `em5_cmim_le0p30` | 423.3-344.2j | 146.0+12.9j | 1.488 | +0.014 | +0.179 | +0.882 | +0.005 | 2.566 | inside the extracted L range, nearest em1 (L ratio 3.09); needs a non-extracted geometry (EM-corrected analytic extrapolation) |
| `em5_cmim_le0p60` | 482.0-300.2j | 147.2+12.6j | 1.486 | +0.027 | +0.162 | +0.862 | +0.007 | 2.544 | inside the extracted L range, nearest em1 (L ratio 6.18); needs a non-extracted geometry (EM-corrected analytic extrapolation) |
| `em5_cmim_le1p00` | 547.7-275.4j | 148.7+12.3j | 1.484 | +0.045 | +0.171 | +0.871 | +0.012 | 2.583 | inside the extracted L range, nearest em4 (L ratio 0.22); needs a non-extracted geometry (EM-corrected analytic extrapolation) |
| `ideal_choke_le0p10` | 237.8-941.9j | 466.0+63.8j | 0.468 | +0.001 | +0.021 | +1.490 | +0.002 | 1.982 | near em1 (L ratio 1.03; EM-backed geometry) |
| `ideal_choke_le0p30` | 450.4-957.0j | 469.0+61.3j | 0.468 | +0.004 | +0.001 | +1.332 | +0.003 | 1.808 | inside the extracted L range, nearest em1 (L ratio 3.09); needs a non-extracted geometry (EM-corrected analytic extrapolation) |
| `ideal_choke_le0p60` | 763.5-1012.6j | 473.5+57.4j | 0.467 | +0.009 | +0.003 | +1.275 | +0.004 | 1.757 | inside the extracted L range, nearest em1 (L ratio 6.18); needs a non-extracted geometry (EM-corrected analytic extrapolation) |

#### Shortlist and brackets

- Shortlisted `em5_cmim` point (declared rule, verified numbers only): `em5_cmim_le0p60` (all non-noise gates).

| Variant | Le loss | NF290 mid / worst (dB) | S11 / S22 worst (dB) | \|S21\| min (dB) | mu bb min | IC1 (mA) | dIC1 vs committed 1 nH | VBE1 (V) | VE1 (mV) | Pdc (mW) | DC flags |
|---|---|---|---|---|---|---|---|---|---|---|---|
| shortlisted | parallel, Q = 10 | 2.544 / 2.570 | -11.43 / -15.63 | 25.10 | 1.0000003574 | 3.93690 | -0.084 % | 0.8435 | 0.000 | 8.4799 | none |
| bracket `q5par` | parallel, Q = 5 | 2.562 / 2.589 | -11.21 / -15.63 | 24.85 | 1.0000003574 | 3.93690 | -0.084 % | 0.8435 | 0.000 | 8.4799 | none |
| bracket `q10ser` | series, Q = 10 | 2.544 / 2.569 | -11.36 / -15.63 | 24.81 | 1.0000003574 | 3.63847 | -7.658 % | 0.8403 | 3.354 | 7.9427 | DC_BIAS_SHIFT_IC1 (-7.66 %); DC_BIAS_SHIFT_IDD (-6.40 %) |

#### Go / no-go for a subsequent full-PVT campaign

- Policy limit (declared, bench policy): verified matched NF290 worst-in-band <= 1.5 - 0.3 = 1.20 dB; the ratified row is 1.5 dB.
- **Verdict: NO-GO**; binding constraint: `noise_floor`; failing gates: noise_floor, le_q_bracket.
- Shortlisted verified NF290 worst-in-band 2.570 dB; DUT NFmin@290 worst-in-band (Le Q = 10) 1.545 dB; remaining budget against the 1.5 dB row -1.070 dB; worse-Q bracket NF290 worst 2.589 dB.
- Effect of choosing Le on the finite feed: shortlisted vs `em5_cmim_le1p00` (committed 1 nH): -0.043 dB verified NF290 worst-in-band.
- Ideal-choke diagnostic (not a design): best point `ideal_choke_le0p60`, verified NF290 worst 1.763 dB; gates failing: noise_match_penalty.
