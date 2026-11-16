# Issue #258 -- `xout` DC bleed: matched-DUT convergence at PVT

- **Change under test**: `Rbleed xout vss 100k` added to `design/lna.sch`; netlist regenerated
  (`design/netlist/lna.spice` sha256 `151aec66ade8f05257795721527b580014edda14793bdafb2a0816d1a212ec64`).
  Before: `xout` touched only capacitors (singular matrix at DC; 18 of 45 cells failed per the #27 note).
  Value reasoning: 100 kOhm is 10 uS against the 50 Ohm port's 20 mS (about 0.05 %).
- **Bench**: unchanged `matched` variant of `lna_variant_campaign.py` (50 Ohm ports, `sp_band` /
  `sp_stab` / `noise` requests, `.options gmin=1e-10`, same cell map). Only addition: the `--temps` /
  `LNA_TEMPS` slice option, so each request stays well under the 3600 s fleet job ceiling.
- **Backend**: Spot batch fleet only (`KLT_SIM_BACKEND=batch`). No local ngspice grid was run.

## Per-cell convergence

| Slice | Record | Cells | Result | Job ids |
|---|---|---|---|---|
| 125 C (5 corners x 3 VDD) | `20261106-054735-64b37ae` | 15 | **15/15 converged**, all three analyses `pass`, reduction complete | noise `klt-sim-4b509a629618`, sp_band `klt-sim-268bf7f63976`, sp_stab `klt-sim-97444dec1ec2` |
| -40 C and 27 C (30 cells) | `20261106-055142-64b37ae` | 30 | `noise` request converged 30/30 (job `klt-sim-313184ef752c`); `sp_band` and `sp_stab` **NOT RUN**: fleet returned `batch_no_capacity` (256 vCPU running, `BATCH_MAX_VCPU=224`, quota shared with ci-spot). Coverage incomplete. **Annotated 2026-11-16**: the `sp_band`/`sp_stab` gap closed by records `20261116-022647-eacd53a` (27 C) and `20261116-023212-eacd53a` (-40 C), 15/15 cells each (rows below); the `noise` numbers here remain the first-pass evidence for those 30 cells. | noise `klt-sim-313184ef752c`; sp_band submit rejected |
| 27 C only (retry, 15 cells) | `20261106-055453-64b37ae` | 15 | **NOT RUN**: `batch_no_capacity` again (224 vCPU running). No usable report. **Annotated 2026-11-16**: superseded by record `20261116-022647-eacd53a`; this retry never produced a report. | none |
| 27 C slice (5 corners x 3 VDD, 2026-11-16) | `20261116-022647-eacd53a` | 15 | **15/15 converged**, all four analyses (`noise`, `op`, `sp_band`, `sp_stab`) `pass`, reduction complete | noise `klt-sim-73d61093b9a4`, op `klt-sim-315d960c58b5`, sp_band `klt-sim-6ff951463704`, sp_stab `klt-sim-e6044fc359b6` |
| -40 C slice (5 corners x 3 VDD, 2026-11-16) | `20261116-023212-eacd53a` | 15 | **15/15 converged**, all four analyses `pass`, reduction complete | noise `klt-sim-541914b4f7b9`, op `klt-sim-5f2fe2b54c06`, sp_band `klt-sim-2ce19a9153d2`, sp_stab `klt-sim-827f2fc4112b` |

The three 125 C S-parameter values the record `20261106-054735-64b37ae` reports (S21 18.9-19.9 dB,
S11 -11.9 to -12.7 dB mid-band, NF290 3.89-4.35 dB mid-band) are bench results for those 15 cells only.
Per the retry rule in `CLAUDE.md` and the issue, the failed submits were **not** replaced by local runs.

The 2026-11-16 re-run (records `20261116-022647-eacd53a` and `20261116-023212-eacd53a`) went through the
runner's `--batch-set` path with `--wait-for-capacity 600` / `--capacity-retries 3` — the submit backoff
landed in `aba06ed` (2026-11-14), eight days **after** the two `batch_no_capacity` rejections above, which
is why this attempt was made rather than slicing the grid further. Both slices completed with every job
`state done` / `status pass` and no capacity rejection. No local ngspice run replaced any failed submit.

## Nominal-cell match delta (bleed vs. pre-bleed)

Post-bleed minus pre-bleed, in-band **worst** S11 / S22 (the only S-parameter summary the pre-bleed
record carries: max |S| dB over the 11-point 2.4-2.4835 GHz grid), at the nominal cell typ / 27 C /
VDD = 1.80 V, both sides through the same `matched` variant of `lna_variant_campaign.py`:

| Quantity | Pre-bleed (`20261101-023246-5bbb70c`, DUT sha256 `2575cbbc0045...`) | Post-bleed (`20261116-022647-eacd53a`, DUT sha256 `151aec66ade8...`) | Delta |
|---|---|---|---|
| In-band worst S11 [dB] | -11.5509 | -11.5470 | **+0.0039 dB** |
| In-band worst S22 [dB] | -15.6090 | -15.6014 | **+0.0076 dB** |

The bleed moves nominal in-band matching by ~4 mdB / ~8 mdB — negligible, as designed: 100 kOhm is
10 uS against the 50 Ohm port's 20 mS (about 0.05 % shunt admittance at any in-band frequency). The
baseline is the committed single-cell record `20261101-023246-5bbb70c`, **not** `20261101-104711-4d7f140`
(that run was a `noise` request stopped before any `sp` analysis, so it has no S11/S22; see the issue's
"Verified corrections").

## Not established (explicit open items)

- [x] **-40 C / 27 C S-parameter and stability cells (30 cells, sp_band + sp_stab) on the fleet.** ~~Re-run with
  `LNA_VARIANTS=matched LNA_TEMPS=27` then `LNA_TEMPS=-40` when the fleet has capacity.~~ **Resolved 2026-11-16**:
  both slices ran on the Spot batch fleet — 27 C as record `20261116-022647-eacd53a`, -40 C as record
  `20261116-023212-eacd53a`, **15/15 cells converged in each**, every analysis `pass`, job ids in the table above.
  No local ngspice grid.
- [x] **Nominal-cell match delta.** ~~The comparison of 27 C typ/1.80 V S11/S22 with the bleed against the 27
  converged cells of run `20261101-104711-4d7f140` needs the 27 C `sp_band` result, which was not obtained.~~
  **Resolved 2026-11-16**: the delta is stated in "Nominal-cell match delta" above — in-band worst
  S11 +0.0039 dB, S22 +0.0076 dB — against the committed pre-bleed record `20261101-023246-5bbb70c`, **not**
  `20261101-104711-4d7f140` (a `noise`-only run that never produced S-parameters; the issue's "Verified
  corrections" replaced the baseline).
- [ ] No NF or stability pass/fail claim is made. At 125 C the stability sweep reports `mu_min` and
  `max|S22|` of exactly 1.0000 (the `n_mu_lt1` flag is 0 with the violation frequency at 1e12 Hz), which looks
  like a sweep-edge artifact rather than a margin; the `|S22| > 1` anomaly stays with #27. **Annotated 2026-11-16**:
  the -40 C and 27 C slices show the same sweep-edge pattern (`mu_min` 1.0000004 and `max|S22|` 0.999999631 at
  every cell, `n_mu_lt1` = 0 everywhere, k_min 57.5-105.1), so no stability margin is claimed at any temperature.
  No spec row is changed.
