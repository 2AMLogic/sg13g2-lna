# Issue #231 -- ratified-row `klt sim` envelope verdicts (20261117-054141-bdebb4d)

Reduced by `sim/lna-characterization/reduce_spec_envelopes.py` from the four
committed report envelopes in `reports/` (do not edit by hand; re-run the
reducer with `--check` to replay). Corner box per request: process
{typ, bcs, wcs} x VDD {1.62, 1.80, 1.98} V x T {-40, 27, 125} C = 27 cells.

## Run provenance (per envelope)

| analysis | engine | PDK | klt (collector) | backend |
|---|---|---|---|---|
| `matched_op` | ngspice 47 | ihp-sg13g2 fetched:0.3.0 | 0.9.3.dev291+g9ddf73155117 | batch |
| `matched_sp_band` | ngspice 47 | ihp-sg13g2 fetched:0.3.0 | 0.9.3.dev291+g9ddf73155117 | batch |
| `matched_sp_stab` | ngspice 47 | ihp-sg13g2 fetched:0.3.0 | 0.9.3.dev291+g9ddf73155117 | batch |
| `matched_noise` | ngspice 47 | ihp-sg13g2 fetched:0.3.0 | 0.9.3.dev291+g9ddf73155117 | batch |

## Per-envelope verdict

| analysis | envelope status | corners passed | corners failed |
|---|---|---|---|
| `matched_op` (DC operating point (op)) | **pass** | 27/27 | 0/27 |
| `matched_sp_band` (In-band S-parameters (sp, 11 pts, 2.4-2.4835 GHz)) | **pass** | 27/27 | 0/27 |
| `matched_sp_stab` (Broadband stability (sp, dec 40, 10 MHz-30 GHz)) | **pass** | 27/27 | 0/27 |
| `matched_noise` (Noise (290 K-referred, 11 pts in band)) | **fail** | 0/27 | 27/27 |

## Per-ratified-row verdict (binding corner = worst-value corner)

| ratified row | measurement | limits | worst value | binding corner | verdict |
|---|---|---|---|---|---|
| `ic1` | `matched_op.ic1` | `{"max": 0.0045}` | 0.00415097376 A | `bcs/1.980V/-40C` | pass |
| `power` | `matched_op.pdc` | `{"max": 0.01}` | 0.0097681213 W | `bcs/1.980V/125C` | pass |
| `gain` | `matched_sp_band.s21_db_min` | `{"min": 15.0}` | 18.7162981 dB | `wcs/1.620V/125C` | pass |
| `s11` | `matched_sp_band.s11_db_worst` | `{"max": -10.0}` | -11.11244 dB | `bcs/1.980V/-40C` | pass |
| `s22` | `matched_sp_band.s22_db_worst` | `{"max": -10.0}` | -14.965332 dB | `wcs/1.620V/125C` | pass |
| `mu` | `matched_sp_stab.mu_min` | `{"min": 1.0}` | 1.00000037  | `typ/1.620V/-40C` | pass |
| `negres` | `matched_sp_stab.s11_mag_max` | `{"max": 1.0}` | 0.998995826  | `bcs/1.980V/-40C` | pass |
| `negres` | `matched_sp_stab.s22_mag_max` | `{"max": 1.0}` | 0.999999631  | `typ/1.620V/-40C` | pass |
| `nf` | `matched_noise.nf290_db_worst` | `{"max": 1.5}` | 4.37793746 dB | `wcs/1.980V/125C` | **fail** |

## Bench-equivalence anchors (PR #334 45-cell matched-DUT verdict)

The 45-cell box of `issue-27-matched-pvt-verdict.md` includes the `sf`/`fs`
labels (ratified duplicates of `typ` at the HBT) which these envelopes do not
re-run; where the benches are equivalent the numbers must agree to the
committed record's printed precision, modulo the ngspice 46/47 note in the
bench README.

| measurement | PR #334 worst (45 cells) | this envelope worst (27 cells) |
|---|---|---|
| `matched_op.ic1` | 4.151 mA (pre-match record 20260926-122301-088c734 box) | 0.00415097376 A at `bcs/1.980V/-40C` |
| `matched_op.pdc` | 9.7611 mW (bcs/27C/1.98V (125C slice ran no op request there)) | 0.0097681213 W at `bcs/1.980V/125C` |
| `matched_sp_band.s21_db_min` | 18.7163 dB (wcs/125C/1.62V) | 18.7162981 dB at `wcs/1.620V/125C` |
| `matched_sp_band.s11_db_worst` | -11.1124 dB (bcs/-40C/1.98V) | -11.11244 dB at `bcs/1.980V/-40C` |
| `matched_sp_band.s22_db_worst` | -14.9653 dB (wcs/125C/1.62V) | -14.965332 dB at `wcs/1.620V/125C` |
| `matched_sp_stab.mu_min` | 1.000000370 (identical at every cell (numerical resolution)) | 1.00000037  at `typ/1.620V/-40C` |
| `matched_sp_stab.s11_mag_max` | 0.998996 (bcs/-40C/1.98V) | 0.998995826  at `bcs/1.980V/-40C` |
| `matched_sp_stab.s22_mag_max` | 0.999999631 (identical at every cell) | 0.999999631  at `typ/1.620V/-40C` |
| `matched_noise.nf290_db_worst` | 4.3779 dB (wcs/125C/1.98V) | 4.37793746 dB at `wcs/1.980V/125C` |

## Reading notes

- The `mu` row's margin over 1 sits at the 10 MHz sweep floor at
  numerical resolution (~4e-7 in PR #334, identical at every cell): the
  Edwards-Sinsky denominator collapses onto |S22| there, so the margin is
  the low-frequency asymptote of the Q~10 lossy output network, not a
  transistor-physics margin. A value below 1 at that floor is a
  numerical-resolution event, not a demonstrated instability dip; the
  fine-resolution probe in the committed verdict record covers this.
- `nf` is expected to fail at every cell until #58 lands (DR-0004);
  nothing here relaxes the ratified row.
- The 125 C `pdc`/`ic1` cells fill the gap PR #334 recorded (its 125 C
  slice ran no op request; the envelope's op request covers all 27 cells).

