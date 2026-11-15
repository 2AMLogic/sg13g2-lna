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
| -40 C and 27 C (30 cells) | `20261106-055142-64b37ae` | 30 | `noise` request converged 30/30 (job `klt-sim-313184ef752c`); `sp_band` and `sp_stab` **NOT RUN**: fleet returned `batch_no_capacity` (256 vCPU running, `BATCH_MAX_VCPU=224`, quota shared with ci-spot). Coverage incomplete. | noise `klt-sim-313184ef752c`; sp_band submit rejected |
| 27 C only (retry, 15 cells) | `20261106-055453-64b37ae` | 15 | **NOT RUN**: `batch_no_capacity` again (224 vCPU running). No usable report. | none |

The three 125 C S-parameter values the record `20261106-054735-64b37ae` reports (S21 18.9-19.9 dB,
S11 -11.9 to -12.7 dB mid-band, NF290 3.89-4.35 dB mid-band) are bench results for those 15 cells only.
Per the retry rule in `CLAUDE.md` and the issue, the failed submits were **not** replaced by local runs.

## Not established (explicit open items)

- [ ] **-40 C / 27 C S-parameter and stability cells (30 cells, sp_band + sp_stab) on the fleet.** Re-run with
  `LNA_VARIANTS=matched LNA_TEMPS=27` then `LNA_TEMPS=-40` when the fleet has capacity.
- [ ] **Nominal-cell match delta.** The comparison of 27 C typ/1.80 V S11/S22 with the bleed against the 27
  converged cells of run `20261101-104711-4d7f140` needs the 27 C `sp_band` result, which was not obtained.
  No delta is claimed.
- [ ] No NF or stability pass/fail claim is made. At 125 C the stability sweep reports `mu_min` and
  `max|S22|` of exactly 1.0000 (the `n_mu_lt1` flag is 0 with the violation frequency at 1e12 Hz), which looks
  like a sweep-edge artifact rather than a margin; the `|S22| > 1` anomaly stays with #27. No spec row is
  changed.
