#### Characterization (nominal cell, band centre 2.44175 GHz)

| Le-loss case | Zin at rfin (Ohm) | Zopt (Ohm) | Rn (Ohm) | NFmin @290 K (dB) | NF into 50 Ohm (sp, 300.15 K ref, dB) | Ydev (S) | S12 (dB) |
|---|---|---|---|---|---|---|---|
| ideal | 280.2175-39.3483j | 85.1712+2.7983j | 24.569 | 2.4451 | 2.5878 | 0.0000+0.0003j | -95.23 |
| q20 | 281.4449-40.4779j | 86.3930+2.8487j | 25.336 | 2.4818 | 2.6367 | 0.0000+0.0003j | -95.22 |
| q10 | 282.5812-41.6128j | 87.5763+2.9007j | 26.092 | 2.5174 | 2.6843 | 0.0000+0.0003j | -95.22 |

Ideal-Le sweep at the band centre -- degeneration as an input-match lever, as committed (R3b = 330 Ohm feeds the base from the AC-grounded `bref` node) and in the what-if probe with R3b's RF path choked (DC unchanged: I_C1 3.9403 mA as committed, 3.9403 mA choked):

| Le (nH) | Zin, committed (Ohm) | Zopt, committed (Ohm) | NFmin290, committed (dB) | Zin, R3b choked (Ohm) | Zopt, R3b choked (Ohm) | NFmin290, R3b choked (dB) |
|---|---|---|---|---|---|---|
| 0.1 | 274.6-90.9j | 85.4528+3.2642j | 2.4539 | 238.2-931.2j | 464.6042+63.5841j | 0.4678 |
| 0.2 | 271.0-82.3j | 85.4143+3.2120j | 2.4527 | 345.9-925.8j | 464.6866+62.0557j | 0.4677 |
| 0.3 | 269.3-74.1j | 85.3775+3.1600j | 2.4515 | 454.1-925.0j | 464.7763+60.5287j | 0.4675 |
| 0.5 | 269.9-60.0j | 85.3096+3.0561j | 2.4494 | 670.8-937.3j | 464.9693+57.4777j | 0.4673 |
| 0.7 | 273.5-49.5j | 85.2488+2.9527j | 2.4475 | 886.1-968.0j | 465.1855+54.4315j | 0.4671 |
| 1 | 280.2-39.3j | 85.1713+2.7983j | 2.4451 | 1200.9-1047.8j | 465.5511+49.8711j | 0.4668 |
| 1.5 | 290.2-30.9j | 85.0778+2.5430j | 2.4421 | 1686.9-1262.8j | 466.2748+42.2947j | 0.4664 |
| 2 | 297.4-27.3j | 85.0289+2.2903j | 2.4404 | 2102.0-1559.8j | 467.1350+34.7475j | 0.4661 |
| 3 | 306.3-24.8j | 85.0637+1.7929j | 2.4409 | 2673.9-2286.1j | 469.2783+19.7426j | 0.4660 |

EM-extracted inductor geometries at 2.44175 GHz (one-port, la and sub grounded):

| Geometry | turns | outer diameter (um) | L (nH) | Q |
|---|---|---|---|---|
| em1 | 1 | 64.1 | 0.0971 | 4.08 |
| em4 | 4 | 230.2 | 4.4857 | 10.29 |
| em5 | 5 | 197.5 | 5.5181 | 8.50 |

#### Candidates (verified by single-cell ngspice runs)

| Candidate | Q case | input elements | Lc | output C | S11 worst | S22 worst | S21 min..max | NF290 worst | mu min 10M-30G | rows met (S11,S22,S21,NF,mu) |
|---|---|---|---|---|---|---|---|---|---|---|
| lp_power | ideal | Lb 7.0766 nH, Cp 0.4633 pF | 5.000 nH | Cs 0.0253 pF, Cp 0.8112 pF | -18.56 dB | -0.00 dB | 14.50..44.03 dB | 3.568 dB | 1.000000000 @ 133.4 MHz (27/140 pts <= 1) | Y,n,n,n,n (1/5) |
| lp_power | q20 | Lb 6.7927 nH, Cp 0.4953 pF | 5.000 nH | Cs 0.2424 pF, Cp 0.6000 pF | -29.55 dB | -9.91 dB | 23.53..24.04 dB | 3.822 dB | 1.000000088 @ 10 MHz (0/140 pts <= 1) | Y,n,Y,n,Y (3/5) |
| lp_power | q10 | Lb 6.5028 nH, Cp 0.5295 pF | 5.000 nH | Cs 0.3465 pF, Cp 0.5043 pF | -29.96 dB | -15.62 dB | 20.31..20.46 dB | 4.064 dB | 1.000000357 @ 10 MHz (0/140 pts <= 1) | Y,Y,Y,n,Y (4/5) |
| lp_power | em | Lb 6.5028 nH, Cp 0.5295 pF | em5 (5.518 nH) | Cs 0.3574 pF, Cp 0.4123 pF | -29.97 dB | -16.19 dB | 20.08..20.20 dB | 4.065 dB | 1.000000332 @ 10 MHz (0/140 pts <= 1) | Y,Y,Y,n,Y (4/5) |
| hp_power | ideal | Cs 0.6004 pF, Lp 8.0565 nH | 5.000 nH | Cs 0.0253 pF, Cp 0.8112 pF | -18.41 dB | -0.00 dB | 14.50..44.16 dB | 3.570 dB | 0.999999233 @ 10 MHz (30/140 pts <= 1) | Y,n,n,n,n (1/5) |
| hp_power | q20 | Cs 0.6419 pF, Lp 7.7159 nH | 5.000 nH | Cs 0.2424 pF, Cp 0.6000 pF | -29.63 dB | -9.90 dB | 23.50..24.03 dB | 3.719 dB | 1.000000088 @ 10 MHz (0/140 pts <= 1) | Y,n,Y,n,Y (3/5) |
| hp_power | q10 | Cs 0.6862 pF, Lp 7.3726 nH | 5.000 nH | Cs 0.3465 pF, Cp 0.5043 pF | -30.03 dB | -15.61 dB | 20.24..20.45 dB | 3.870 dB | 1.000000357 @ 10 MHz (0/140 pts <= 1) | Y,Y,Y,n,Y (4/5) |
| hp_power | em | Cs 0.6862 pF, Lp 7.3726 nH | em5 (5.518 nH) | Cs 0.3574 pF, Cp 0.4123 pF | -29.92 dB | -16.18 dB | 20.02..20.18 dB | 3.871 dB | 1.000000332 @ 10 MHz (0/140 pts <= 1) | Y,Y,Y,n,Y (4/5) |
| lp_noise | ideal | Lb 5.0702 nH, Cp 0.5622 pF | 5.000 nH | Cs 0.0253 pF, Cp 0.8112 pF | -10.28 dB | -0.00 dB | 14.19..43.75 dB | 2.827 dB | 1.000000000 @ 133.4 MHz (29/140 pts <= 1) | Y,n,n,n,n (1/5) |
| lp_noise | q20 | Lb 4.8120 nH, Cp 0.5938 pF | 5.000 nH | Cs 0.2424 pF, Cp 0.6000 pF | -11.56 dB | -9.90 dB | 23.24..23.77 dB | 3.088 dB | 1.000000088 @ 10 MHz (0/140 pts <= 1) | Y,n,Y,n,Y (3/5) |
| lp_noise | q10 | Lb 4.5637 nH, Cp 0.6260 pF | 5.000 nH | Cs 0.3465 pF, Cp 0.5043 pF | -11.55 dB | -15.61 dB | 20.06..20.24 dB | 3.336 dB | 1.000000357 @ 10 MHz (0/140 pts <= 1) | Y,Y,Y,n,Y (4/5) |
| lp_noise | em | Lb 4.5637 nH, Cp 0.6260 pF | em5 (5.518 nH) | Cs 0.3574 pF, Cp 0.4123 pF | -11.55 dB | -16.18 dB | 19.85..19.98 dB | 3.337 dB | 1.000000332 @ 10 MHz (0/140 pts <= 1) | Y,Y,Y,n,Y (4/5) |

Solver prediction (unilateral, from the characterization data) vs. the verification run, band centre:

| Candidate | Q case | S11 pred / sim (dB) | S22 pred / sim (dB) | NF290 pred / sim (dB) | I_C1 (mA) | P_dc (mW) | max\|S11\| / max\|S22\| 10M-30G | 2-element Lc+series-C would need Lc (nH) |
|---|---|---|---|---|---|---|---|---|
| lp_power | ideal | -300.0 / -18.6 | -268.8 / -24.3 | 3.518 / 3.518 | 3.9403 | 8.5095 | 0.999972691 / 1.000000000 | 93.97 |
| lp_power | q20 | -298.9 / -63.3 | -300.0 / -55.6 | 3.768 / 3.776 | 3.9418 | 8.4894 | 0.999648487 / 0.999999912 | 39.54 |
| lp_power | q10 | -297.7 / -68.9 | -300.0 / -62.0 | 4.005 / 4.021 | 3.9422 | 8.4900 | 0.999295519 / 0.999999643 | 24.73 |
| lp_power | em | -297.7 / -70.1 | -300.0 / -63.0 | 4.005 / 4.022 | 3.9420 | 8.4889 | 0.999295518 / 0.999999668 | 24.73 |
| hp_power | ideal | -300.0 / -18.4 | -268.8 / -23.6 | 3.518 / 3.518 | 3.9403 | 8.6011 | 1.000000000 / 1.000000000 | 93.97 |
| hp_power | q20 | -300.0 / -60.2 | -300.0 / -59.0 | 3.651 / 3.659 | 3.9427 | 8.4919 | 0.999999048 / 0.999999912 | 39.54 |
| hp_power | q10 | -300.0 / -68.4 | -300.0 / -62.9 | 3.786 / 3.804 | 3.9387 | 8.4831 | 0.999997944 / 0.999999643 | 24.73 |
| hp_power | em | -300.0 / -71.1 | -300.0 / -61.7 | 3.786 / 3.805 | 3.9386 | 8.4829 | 0.999997944 / 0.999999668 | 24.73 |
| lp_noise | ideal | -12.0 / -10.3 | -268.8 / -27.6 | 2.802 / 2.802 | 3.9403 | 8.6129 | 0.999963410 / 1.000000000 | 93.97 |
| lp_noise | q20 | -12.0 / -12.0 | -300.0 / -54.0 | 3.054 / 3.064 | 3.9391 | 8.4827 | 0.999503333 / 0.999999912 | 39.54 |
| lp_noise | q10 | -12.0 / -12.0 | -300.0 / -63.4 | 3.293 / 3.313 | 3.9384 | 8.4802 | 0.998993614 / 0.999999643 | 24.73 |
| lp_noise | em | -12.0 / -12.0 | -300.0 / -64.6 | 3.293 / 3.314 | 3.9420 | 8.4889 | 0.998993616 / 0.999999668 | 24.73 |

Inductor feasibility against the three EM-extracted geometries (L and Q at 2.44175 GHz above):

| Candidate | Q case | Le (1 nH) | input matching L | Lc |
|---|---|---|---|---|
| lp_power | q10 | inside the extracted L range, nearest em4 (L ratio 0.22); needs a non-extracted geometry (EM-corrected analytic extrapolation) | Lb 6.503 nH: above the largest extracted L (5.52 nH, ratio 1.18); larger spiral (unextracted), bondwire or off-chip | near em5 (L ratio 0.91; EM-backed geometry) |
| lp_power | em | inside the extracted L range, nearest em4 (L ratio 0.22); needs a non-extracted geometry (EM-corrected analytic extrapolation) | Lb 6.503 nH: above the largest extracted L (5.52 nH, ratio 1.18); larger spiral (unextracted), bondwire or off-chip | EM geometry em5 (extracted) |
| hp_power | q10 | inside the extracted L range, nearest em4 (L ratio 0.22); needs a non-extracted geometry (EM-corrected analytic extrapolation) | Lp 7.373 nH: above the largest extracted L (5.52 nH, ratio 1.34); larger spiral (unextracted), bondwire or off-chip | near em5 (L ratio 0.91; EM-backed geometry) |
| hp_power | em | inside the extracted L range, nearest em4 (L ratio 0.22); needs a non-extracted geometry (EM-corrected analytic extrapolation) | Lp 7.373 nH: above the largest extracted L (5.52 nH, ratio 1.34); larger spiral (unextracted), bondwire or off-chip | EM geometry em5 (extracted) |
| lp_noise | q10 | inside the extracted L range, nearest em4 (L ratio 0.22); needs a non-extracted geometry (EM-corrected analytic extrapolation) | Lb 4.564 nH: near em4 (L ratio 1.02; EM-backed geometry) | near em5 (L ratio 0.91; EM-backed geometry) |
| lp_noise | em | inside the extracted L range, nearest em4 (L ratio 0.22); needs a non-extracted geometry (EM-corrected analytic extrapolation) | Lb 4.564 nH: near em4 (L ratio 1.02; EM-backed geometry) | EM geometry em5 (extracted) |

Ranking (basis: the q10 case -- rows met, then lower worst NF290, then higher broadband mu): 1. `lp_noise`, 2. `hp_power`, 3. `lp_power`
