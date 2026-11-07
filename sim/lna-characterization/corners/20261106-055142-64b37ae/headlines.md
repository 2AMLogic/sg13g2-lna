**COVERAGE INCOMPLETE** -- 32 validation issue(s); no complete-grid or pass claim may be drawn from this summary.

### Variant `matched` -- committed matched DUT (design/netlist/lna.spice, verbatim) (30 cells)

- |S21| mid-band [dB]: n/a
- NF @290 K mid-band [dB]: min 2.548 @ bcs/-40C/1.98V, max 3.539 @ wcs/27C/1.98V
- NFmin (sp) mid-band [dB]: n/a
- |S11| mid-band [dB]: n/a
- |S22| mid-band [dB]: n/a
- mu min 10 MHz..30 GHz: n/a
- max |S22| 10 MHz..30 GHz: n/a
- NF @290 K worst SAMPLED point [dB]: max 3.561 at 2.4835 GHz, wcs/27C/1.98V -- noise lin 11 pts 2.4..2.4835 GHz (8.35 MHz spacing); sampled maximum, not a continuous-band bound -- a peak narrower than the spacing can be missed

Ideal baseline not requested; no ratified-row coverage summary.

## Validation issues

- unreadable_report variant=matched analysis=sp_band matched_sp_band.report.json: Expecting value: line 1 column 1 (char 0)
- missing_cell variant=matched analysis=sp_band cell=typ/-40C/1.62V
- missing_cell variant=matched analysis=sp_band cell=typ/-40C/1.80V
- missing_cell variant=matched analysis=sp_band cell=typ/-40C/1.98V
- missing_cell variant=matched analysis=sp_band cell=typ/27C/1.62V
- missing_cell variant=matched analysis=sp_band cell=typ/27C/1.80V
- missing_cell variant=matched analysis=sp_band cell=typ/27C/1.98V
- missing_cell variant=matched analysis=sp_band cell=bcs/-40C/1.62V
- missing_cell variant=matched analysis=sp_band cell=bcs/-40C/1.80V
- missing_cell variant=matched analysis=sp_band cell=bcs/-40C/1.98V
- missing_cell variant=matched analysis=sp_band cell=bcs/27C/1.62V
- missing_cell variant=matched analysis=sp_band cell=bcs/27C/1.80V
- missing_cell variant=matched analysis=sp_band cell=bcs/27C/1.98V
- missing_cell variant=matched analysis=sp_band cell=wcs/-40C/1.62V
- missing_cell variant=matched analysis=sp_band cell=wcs/-40C/1.80V
- missing_cell variant=matched analysis=sp_band cell=wcs/-40C/1.98V
- missing_cell variant=matched analysis=sp_band cell=wcs/27C/1.62V
- missing_cell variant=matched analysis=sp_band cell=wcs/27C/1.80V
- missing_cell variant=matched analysis=sp_band cell=wcs/27C/1.98V
- missing_cell variant=matched analysis=sp_band cell=sf/-40C/1.62V
- missing_cell variant=matched analysis=sp_band cell=sf/-40C/1.80V
- missing_cell variant=matched analysis=sp_band cell=sf/-40C/1.98V
- missing_cell variant=matched analysis=sp_band cell=sf/27C/1.62V
- missing_cell variant=matched analysis=sp_band cell=sf/27C/1.80V
- missing_cell variant=matched analysis=sp_band cell=sf/27C/1.98V
- missing_cell variant=matched analysis=sp_band cell=fs/-40C/1.62V
- missing_cell variant=matched analysis=sp_band cell=fs/-40C/1.80V
- missing_cell variant=matched analysis=sp_band cell=fs/-40C/1.98V
- missing_cell variant=matched analysis=sp_band cell=fs/27C/1.62V
- missing_cell variant=matched analysis=sp_band cell=fs/27C/1.80V
- missing_cell variant=matched analysis=sp_band cell=fs/27C/1.98V
- missing_report variant=matched analysis=sp_stab no matched_sp_stab.report.json (or unreadable)

