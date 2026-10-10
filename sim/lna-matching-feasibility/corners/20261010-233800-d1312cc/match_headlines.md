#### Verified matched amplifier (existing noise-weighted `lp_noise` input match, Q = 10, re-synthesized per feed; DC reference Rxoutdc = 1e+11 Ohm)

| Feed | Input L / C (H, F) | NF290 worst / mid (dB) | DUT NFmin@290 mid (dB) | Predicted NF290 mid (dB) | S11 worst (dB) | S22 worst (dB) | |S21| min..max (dB) | mu bb min (f) | k bb min | max |S11| / |S22| bb | IC1 (mA) | OP convergence |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| committed (baseline) | 4.564e-09 / 6.26e-13 | 3.335 / 3.313 | 2.517 | 3.293 | -11.55 | -15.61 | 20.07..20.25 | 1.0000003575 (0.01 GHz) | 67.04 | 0.9990 / 1.0000 | 3.94021 | normal |
| ideal_choke (diagnostic bound) | 1.107e-08 / 3.418e-13 | 1.808 / 1.799 | 0.481 | 1.792 | -11.28 | -15.61 | 26.44..26.60 | 1.0000003575 (0.01 GHz) | 43.37 | 0.9996 / 1.0000 | 3.94021 | normal |
| em5_cideal (finite candidate) | 7.078e-09 / 4.787e-13 | 2.610 / 2.581 | 1.526 | 2.569 | -11.41 | -15.63 | 22.96..23.14 | 1.0000003575 (0.01 GHz) | 69.42 | 0.9994 / 1.0000 | 3.93690 | normal |

#### Go / no-go recommendation for a subsequent full-PVT campaign

- Best DC-valid finite feed: `em5_cideal`.
- Policy limit (declared): matched NF290 worst-in-band <= 1.5 - 0.3 = 1.20 dB, plus S11/S22 < -10 dB, |S21| > 15 dB, no resolved mu < 1, DC-valid, convergent.
- **Verdict: NO-GO**; binding constraint: `noise_floor`; failing gates: noise_floor.
- Verified matched NF290 worst-in-band 2.610 dB; DUT NFmin@290 worst-in-band 1.514 dB; remaining budget against the 1.5 dB row -1.110 dB.
- Ideal-choke diagnostic bound (same gates, not a design): verdict NO-GO, failing ['noise_match_penalty'], matched NF290 worst 1.808 dB.
- Feed area (lower bound, bounding boxes only): 39010 um^2.
