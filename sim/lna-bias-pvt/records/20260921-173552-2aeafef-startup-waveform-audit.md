# Startup waveform audit of record 20260921-173552-2aeafef (derivation, issue #154)

- **Source:** the retained `corners/20260921-173552-2aeafef/startup_*.dat`
  waveforms (`wrdata` of `@q.xdut.xq1.qnpn13g2[ic]`, `tran 1e-9 1.2e-5`) and
  the retained op/startup logs of that record. No new simulation.
- **Method:** `sim/lna-bias-pvt/reduce_biasop.py --waveform-audit-csv`
  (`startup_waveform_audit`). Every sample with 2 us <= t <= 12 us is checked:
  (max-min)/mean <= 2 % and every sample within +/-5 % of the paired DC
  `I_C1`; inputs must be finite, strictly time-ordered, max gap <= 5 ns,
  >= 1000 samples, window ends covered. Tolerances are those of the
  historical three-sample check.
- **Result:** all three startup cells PASS (10001 samples each, 1 ns
  spacing). The historical three-sample verdicts in
  `20260921-173552-2aeafef-startup.csv` are unchanged (column
  `historical_verdict` repeats them).
- **Limits:** the 1 ns sample spacing bounds what is resolvable; excursions
  shorter than the retained spacing, or after 12 us, are not covered.
- This record is append-only; the source record was not edited.
