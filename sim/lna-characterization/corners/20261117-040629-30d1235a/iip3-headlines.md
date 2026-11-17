## Two-tone IIP3 reduction (issue #337)

- Coverage: **COMPLETE** (45 cells x ['a1mv', 'a2mv'] per-cell levels + nominal-only ['a0p5mv', 'a4mv', 'a8mv']; 0 validation issue(s))
- IM3 slope check (3 +/- 0.15, README policy): valid 45, invalid 0, unknown 0 of 45 cells.
- The 3:1 IM3 slope assumption holds at every cell; every intercept below is accepted.
- Available-power-referred IIP3, 2 mV/tone [dBm] over valid cells: -3.1181 @ wcs/-40C/1.62V .. -0.9683 @ bcs/27C/1.98V
- Available-power-referred IIP3, 1 mV/tone [dBm] over valid cells: -3.1194 @ wcs/-40C/1.62V .. -0.9746 @ bcs/27C/1.98V
- Nominal cell (typ/27C/1.80V): IIP3 -2.0961 dBm at 1 mV/tone, -2.0905 dBm at 2 mV/tone, IM3 slope 2.998, I_C1 0.00394021 A, P_dc 0.0084858 W.
- Device-plane conversion (matched |S11| per cell, term -10*log10(1-|S11|^2) = +0.2408..+0.3152 dB): device-plane IIP3, 2 mV/tone [dBm]: -3.3976 @ wcs/-40C/1.62V .. -1.2712 @ bcs/27C/1.98V
- Draft > 0 dBm value (NOT a ratified target): 0 of 45 valid cells reach 0 dBm at 2 mV/tone. Observation only -- the IIP3 numeric row stays DRAFT; binding requires a decision record of its own.

### Bench definition (carried beside every number)

- Tones: f1 = 2441406250.0 Hz (bin 640), f2 = 2449035644.53125 Hz (bin 642), spacing = 7629394.53125 Hz; IM3 products at bins 638/644, IM5 floor sentinels at bins 636/646.
- FFT: uniform tstep = 4e-12 s, N = 65536 samples (tstop = 1.26214e-06 s), rectangular window (`set specwindow=none`), df = 1/(N*tstep) = 3814697.265625 Hz, tstart = 1e-06 s discarded; NPTS and the bin-resolution witness (fft_df) are recorded per point.
- Ports: 50 Ohm at both ends (Rs = RL = 50 Ohm); input power is the AVAILABLE source power per tone A^2/(8*Rs); output power per tone and per product is V_peak^2/(2*RL); IIP3 = Pin + (Pout - PIM3)/2.
- Drive levels: ['a1mv (0.001 V)', 'a2mv (0.002 V)'] at every PVT cell; nominal cell additionally ['a0p5mv', 'a4mv', 'a8mv'].
- Extraction: the deck reproduces testbench/tb_lna_iip3.spice.tmpl's control sequence verbatim (op -> OP echo -> tran -> linearize v(rfout) v(vin) -> NPTS -> coherent-DFT projection -> DFT echo -> fft), carried as a klt sim request; the FFT bin magnitudes return in the klt report (measurements[].expr read in the spectrum plot the template's own `fft` leaves current) and the template's OP/DFT echoes stay in the kept ngspice log. Primary IIP3 = FFT bins; `iip3_dbm_dft_crosscheck` = the template's independent coherent-DFT projection from the same log; `dft_fft_iip3_agreement_db` per point.
- ngspice: version/build per klt report `environment` (fleet runner); the DUT is design/netlist/lna.spice inlined verbatim (sha256 recorded in the record header).

### Stated limits of this method (README 'IIP3', restated)

1. Extrapolation, not a measured intercept: meaningful only while IM3 rises 3:1 with drive; cells failing the slope check contribute NO accepted intercept.
2. IM5 bins are numerical-floor sentinels; `im3_over_im5_db` is committed per point and the bench is not to be driven lower without re-checking that margin.
3. Clean harmonic/intermod separation comes from the wide 7.63 MHz spacing; narrowing it needs a proportionally longer record (wall-clock, not methodology).
4. tstep = 4 ps => 125 GHz Nyquist (~51x the tone), so transient truncation does not synthesize its own intermodulation; ngspice default reltol sets the floor in (2).
5. Steady state after tstart = 1 us is an argument (ns-scale poles), not a measurement.
6. Single-ended, single tone pair, in-band only: no blocker, out-of-band IM, AM-PM, P1dB.

