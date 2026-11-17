# Issue #27 — the matched DUT's 45-cell PVT verdict and the `\|S22\| > 1` anomaly investigation

This note assembles, from **already committed** evidence, the full-grid verdict
the matching network has been waiting for since PR #247 landed the `lp_noise`
match as "nominal-cell, not final", and it closes the one open item #258's
convergence note explicitly left with this issue: the 17-of-45-cells
`\|S22\| > unity` anomaly. It is a synthesis and a local single-corner probe —
**no new batch-fleet campaign was run**; every grid number below is quoted from
committed records with the record, analysis and column named.

## Claim

The committed matched DUT (`design/netlist/lna.spice` sha256
`151aec66ade8f05257795721527b580014edda14793bdafb2a0816d1a212ec64`, commit
`dd6c5be`) meets the ratified **input-match**, **output-match**, **gain** and
**stability** rows at **every cell of the 45-cell PVT box** — the gate
`CLAUDE.md` set ("stability … at PVT corners, before any matching is declared
final") therefore passes and the match may be called final **at numerical
resolution, conditional on the Q ≈ 10 inductor-loss model** (that condition is
the substance of §Anomaly below, not a footnote). The ratified **NF** row stays
failing (0 of 45 cells), now with the finite-Q input loss measured inside the
delta; the **IIP3** numeric row stays DRAFT and unbound (no post-match IIP3
re-measure exists). Nothing ratified is relaxed; `spec/target-spec.md` is not
modified by this issue.

## The 45-cell grid, assembled

Three single-temperature slices of the same harness on the same committed DUT
(the only `present-dut` evidence for this circuit, per the README's
"Do" paragraph): `20261106-054735-64b37ae` (125 °C, 15 cells,
noise/sp_band/sp_stab), `20261116-022647-eacd53a` (27 °C, 15 cells, all four
analyses) and `20261116-023212-eacd53a` (−40 °C, 15 cells, all four analyses).
45/45 cells report every analysis `pass`; every number below is the
`<record-id>-summary.csv` column named, reduced over all 45 rows. In-band =
the bench's 11-point 2.4–2.4835 GHz grid; broadband = the `sp_stab`
10 MHz–30 GHz sweep (140 points).

| Quantity (column) | Worst of 45 | Best of 45 | Ratified row | Verdict |
|---|---|---|---|---|
| in-band S11 (`s11_db_worst`) | **−11.1124 dB** (bcs/−40 °C/1.98 V) | −12.2128 dB (wcs/125 °C/1.62 V) | < −10 dB | **45/45 meet it** |
| in-band S22 (`s22_db_worst`) | **−14.9653 dB** (wcs/125 °C/1.62 V) | −15.6384 dB (fs/27 °C/1.62 V) | < −10 dB | **45/45 meet it** |
| in-band \|S21\| (`s21_db_min`) | **18.7163 dB** (wcs/125 °C/1.62 V) | 20.9116 dB (bcs/−40 °C/1.98 V) | > 15 dB | **45/45 meet it** |
| broadband μ (`mu_min`) | **1.000000370**, identical at every cell | — | μ > 1, 10 MHz–30 GHz | **45/45 meet it, at numerical resolution** (§Margin) |
| broadband k (`k_min`) | **49.1460** (wcs/125 °C/1.62 V) | 105.0737 (bcs/−40 °C/1.98 V) | reported beside μ | reported; min > 1 |
| in-band μ (`mu_band_min`) | **5.5707** (wcs/125 °C/1.62 V) | 6.0382 (fs/27 °C/1.62 V) | — | large in-band margin |
| in-band k (`k_band_min`) | **605.357** (wcs/125 °C/1.62 V) | 1284.30 (bcs/−40 °C/1.98 V) | — | — |
| max \|S11\| broadband (`s11_mag_max`) | **0.998996** (bcs/−40 °C/1.98 V) | 0.998990 (wcs/125 °C/1.62 V) | < 1 (negative-resistance check) | 45/45 < 1 |
| max \|S22\| broadband (`s22_mag_max`) | **0.999999631**, identical at every cell | — | < 1 (negative-resistance check) | 45/45 < 1 |
| `nf290_db_worst` | **4.3779 dB** (wcs/125 °C/1.98 V) | 2.5691 dB (bcs/−40 °C/1.98 V) | < 1.5 dB @ 290 K | **0/45 meet it — failing, disclosed** |
| `pdc` (27 °C and −40 °C slices; the 125 °C slice ran no `op` request) | **9.7611 mW** (bcs/27 °C/1.98 V) | — | < 10 mW | under the bar where measured; for 125 °C the pre-match record `20260926-122301-088c734` measured 9.7683 mW at the worst cell and the only DC change since is the 100 kΩ bleed (≤ 20 µA, ≤ 0.04 mW) |

For contrast, the same columns on the **pre-match** DUT (record
`20260926-122301-088c734`, nominal cell): S11 −3.0657 dB, S22 −0.0044 dB,
`nf290` 2.6559 dB, broadband μ_min 0.999997, broadband k_min −2.792214,
max \|S22\| 1.00000018 (+0.18 ppm, 45 of 45 cells, recounted from raw tables).
The match moved S11 by −8.5 dB, S22 by −15.6 dB, added ~8.7 dB of in-band
gain, crossed broadband μ from below 1 to above 1 at every cell — and cost
**+0.68 dB of nominal `nf290`** (2.6559 → 3.3355 dB, both worst-in-band-point
per cell): that is the Q ≈ 10 loss the match was synthesized with, ~7 Ω in
series with a ~70 Ω input inductor reactance at 2.44 GHz, kept explicit
precisely so this cost is measured rather than hidden. The NF row's failure is
therefore now attributable to the device/bias floor (`NFmin` above the bar, per
the spec table's own note) **plus** the finite-Q input loss — and it is not
reachable by re-matching at this bias point. The row stays failing, openly.

## The μ margin, and why it is quoted as "numerical resolution"

`mu_min = 1.000000370` at **every** cell of the box — identical to nine
decimals across a 100 °C, ±10 % supply, four-corner process spread. Two facts
identify what that number is:

1. It sits at the **10 MHz sweep floor**: the fine-resolution probe below finds
   `mu_min` exactly at 10.000 MHz, rising monotonically above it, with no
   interior dip anywhere in 9911 points to 3 GHz (and the committed 140-point
   grid covers 3–30 GHz, where in-band μ ≥ 5.57 and k ≥ 49 far from 1).
2. At that floor, μ = 1/\|S22\| to printed precision (1/0.999999631 =
   1.000000369 ≈ 1.000000370), because \|S12\| ≈ −94 dB makes the
   Edwards–Sinsky denominator collapse onto \|S22\| there — the μ margin and
   the \|S22\| margin are **one number**, the low-frequency asymptote of a
   passive output network whose loss is dominated by the Q ≈ 10 models.

So the honest reading is: μ > 1 at every sampled point of every cell, the
sampling is not hiding a dip (fine sweep), and the margin over 1 — 3.7 × 10⁻⁷ —
is set by the modeled inductor loss, not by transistor physics (a real
active-device margin would track PVT; this one does not move at all). That is
why the verdict above says "at numerical resolution, conditional on the Q ≈ 10
inductor-loss model", and why the anomaly investigation below matters: it is
the direct measurement of what happens when that loss is removed.

## The `\|S22\| > 1` anomaly — investigated, and the hypothesis is refuted

The issue's hypothesis: the 17-of-45-cells `\|S22| > unity` excess (max
1.000004 at 237–398 MHz, record `20260918-210908-4293920`; re-counted at
+0.18 ppm max on the DR-0003 core, record `20260926-122301-088c734`) is
"presumably a numerical-resolution artifact of the current lossless model".
**The probe refutes the artifact reading: the excess is real.** What the lossy
model does is supply the damping that removes it.

**Bench.** Three decks under
`netlist-snapshots/issue-27-s22-anomaly-probe/` (committed with this note):
port sources, `gmin`/`tnom`, the μ/k expressions and the 50 Ω port convention
are byte-identical to the campaign's `sp_stab` bench
(`netlist-snapshots/20261116-023212-eacd53a/matched_sp_stab.*`); the sweep is
`sp dec 4000 1e7 3e9` — 9911 points, ~71× the committed 140-point density —
over 10 MHz–3 GHz, the region where every recorded anomaly lives
(188–600 MHz historically; the probe's own findings below). Engine: local
ngspice-47, the same build the Spot fleet runner images carry; PDK
`ihp-sg13g2` 0.3.0 (`/home/ubuntu/share/pdk`, tarball marker). Corner: the
**worst historical offender cell** bcs/125 °C/1.98 V (the +4 ppm cell), plus
bcs/−40 °C/1.98 V as the DR-0003 core's worst-μ-dip cell. Single-corner local
debug probe per the host rules — not a grid, not a campaign.

- **A — the committed lossy DUT, inlined verbatim** (both corners): max
  \|S22\| = **0.999999631** at 10.000 MHz — the committed grid's own value to
  all nine printed decimals — μ_min = 1.000000370, k_min 642.985 (125 °C) /
  800.591 (−40 °C), and **zero** points out of 9911 with \|S22\| > 1, μ < 1 or
  k < 1, at either corner.
- **B — a lossless variant of the same matched network** (`Rle` deleted,
  `Rlc`/`Rlb` → 0; a hypothetical circuit that exists only inside the probe
  deck, marked with `PROBE EDIT` comments, and **not committed anywhere as a
  design**): max \|S22\| = **1.000743220** at 2288.2 MHz, with \|S22\| > 1
  across **412.8–2536.6 MHz (325 points)**; μ_min = **0.997165** at
  2414.1 MHz (364 points < 1); k_min = **−37.20** at 469.4 MHz.

**Conclusion.** A +743 ppm \|S22\| excess, robust across 325 fine-swept
points, is three orders of magnitude above solver round-off: the lossless
matched network genuinely presents **active negative resistance** at port 2
over a wide band — the same mechanism class the original 17-cell anomaly
showed at +1…+4 ppm under those (earlier, unmatched) networks, and which the
#56 variant study already localized to the collector branch (Lc's Q resolves
μ; Le's does not — README §"The answer #27 was waiting for"). The probe adds
the fine-resolution half the 140-point grid could not show: no narrower-than-grid
spike exists in the lossy DUT, and the lossless counterpart's excess is far
too large to be numerical. **Disposition: the anomaly is closed as
understood-and-damped, not dismissed.** The committed Q ≈ 10 loss models
(`sim/models/sg13g2_inductor_em.spice` sha256 `6f24f9857ab7810c91bda5f6307e78f1dfcbe2afd750bb023e28156ded06d6a0`,
provenance in `sim/models/SOURCE.md`; per-element loss resistors `Rle`/`Rlc`/`Rlb`
in the committed netlist) are what makes the amplifier unconditionally stable
— the stability verdict is conditional on them, and any future inductor
re-model must re-run this gate (that requirement is the PR's stated follow-on).

## What this issue leaves open (honestly)

- **NF < 1.5 dB (ratified): failing, 0/45 cells**, 2.5691–4.3779 dB. Not
  relaxed; attributed per the spec table's own note to the bias-point/device
  floor, now with the measured ~0.68 dB finite-Q input-match cost on top. A
  design change (bias/device) is the only path; that is a different issue.
- **IIP3 (number DRAFT, protocol ratified): no post-match IIP3 measurement
  exists.** The three slices ran noise/op/sp_band/sp_stab only; the protocol
  binds the number "after #27's matching network re-measures on this exact
  protocol" — that re-measure is still owed and is not part of this PR.
- **Mismatch/Monte-Carlo: none**, as the README's Model limitations item 6
  states for this whole tree; the ppm-scale μ margin makes that gap explicit
  rather than academic.
- `design/lna.sch` / `design/netlist/lna.spice` are deliberately **byte-identical**
  to `main` in this PR: the committed records' DUT sha256
  (`151aec66ade8f052…`) is computed over the whole netlist file including its
  volatile `** sch_path:` header, so regenerating the netlist for a
  comment-only schematic edit would re-baseline the sha and orphan the three
  committed slices as untraceable DUTs (the exact failure the README documents
  for record `20261101-023117-5bbb70c`). The schematic's own "NOT a final
  match" note describes the state at its commit; the evidence trail above is
  what supersedes it, append-only.

## Provenance

- **Timestamp / author**: 2026-11-17T00:20:00Z, Loom Builder (agent), issue #27.
- **New simulation**: the three local single-corner probe runs above only;
  their decks, full 9911-point tables and ngspice logs are committed under
  `netlist-snapshots/issue-27-s22-anomaly-probe/`. No batch-fleet job was
  submitted and no committed record, deck, snapshot or corner file was
  modified (append-only).
- Every grid number: the named `-summary.csv` column of the three committed
  slices. Every probe number: the named deck's committed `.log` (summary
  lines) and `.table.txt` (full sweep).
