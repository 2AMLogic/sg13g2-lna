# lna-bias-pvt — DC op-point PVT sweep of the Q1 bias generator

Issue [#26](https://github.com/2AMLogic/sg13g2-lna/issues/26): the
acceptance bench for the Q1 bias-generator replacement (placeholder
resistive `R1a`/`R1b` divider → 8:1 density-matched `npn13G2`
current-mirror reference); re-run for issue
[#33](https://github.com/2AMLogic/sg13g2-lna/issues/33) / DR-0003
Stage 2, whose flat-reference core swap replaced the `R3a` feed in the
same committed netlist (the bench's DUT is always the committed
`design/netlist/lna.spice`; the two bars and their columns/verdicts are
byte-identical in meaning across the swap — see
[`../biasref-topology/`](../biasref-topology/README.md) for the
core-level design-space benches and
[`../../spec/decision-records/0003-flat-pvt-bias-reference.md`](../../spec/decision-records/0003-flat-pvt-bias-reference.md)
for the decision record and its Stage-2 sizing amendment). Where
[`../lna-characterization/`](../lna-characterization/README.md) (issue
[#18](https://github.com/2AMLogic/sg13g2-lna/issues/18)) measures the LNA's
*RF* behaviour, this experiment measures only the *DC operating point* of
the committed netlist across the PVT grid — the two quantities issue #26's
acceptance criteria are stated in.

**What is ratified vs. draft at the time of the first records.** DR-0002
(issue #32, merged 2026-09-21) ratified `spec/target-spec.md`'s Power
(< 10 mW) and Supply rows and DR-0001 (with its `I_C1 <= 4.5 mA`
mandate); DR-0002's Power-row binding conditions explicitly name issue
#26 — the bias-generator work this experiment evidences — as its
verification gate. The IIP3 numeric row stays DRAFT pending its own
decision record. These records are that gate's evidence, with every
number traceable to the bench that produced it.

## What is measured, and how (bench definitions)

Per `CLAUDE.md`: every recorded number carries its bench definition, and
the bench is committed beside the results.

- **The DUT** is the committed `design/netlist/lna.spice` (xschem-generated
  from `design/lna.sch`), inlined verbatim into each generated deck with
  only xschem's own commented-out `**.subckt`/`**.ends` markers uncommented
  and the trailing `.end` dropped — the same convention
  `../lna-characterization/run_lna_sweep.sh` uses; no device line is
  altered. The runner records the netlist's sha256 in every record.
- **The grid** is the *identical* 45-cell PVT grid the issue's divider
  evidence (and issue #18's campaign) used:
  `{typ,bcs,wcs,sf,fs} × {−40,27,125} °C × {1.62,1.80,1.98} V`, mapped onto
  `cornerHBT.lib`'s three real sections (`sf`/`fs` duplicate `hbt_typ` —
  see [`../README.md`](../README.md) "Corner-label convention").
- **The analysis** is a DC operating point (`op`) per cell, with the
  operating-point probes named — and the node naming pinned — in
  [`testbench/tb_lna_biasop.spice.tmpl`](testbench/tb_lna_biasop.spice.tmpl):
  `I_C1`, `I_C2` (the cascode stack), `I_C3`, `I_B1` (the mirror), `V_B1`,
  `V_BREF`, `V_CE1`, `V_CE2`, `V_BE1`, `I_DD`, and `P_dc = VDD·I_DD`.
- **The two bars evaluated per cell** (both cited by issue #26, both
  unratified):
  - DR-1's bias-network requirement (from
    [`spec/decision-records/0001-bias-supply-topology.md`](../../spec/decision-records/0001-bias-supply-topology.md)):
    `I_C1 ≤ 4.5 mA` at every cell;
  - `spec/target-spec.md`'s Power row (ratified by DR-0002):
    `P_dc < 10 mW` at every cell.
- **Startup / latch check** (issue #26's Test Plan edge case):
  `testbench/tb_lna_startup.spice.tmpl` ramps VDD 0 V → target in 1 µs,
  holds to 12 µs, and the runner checks `I_C1`'s settling window agrees with
  itself (no ringing) and with the `op` bench's value at the same cell (no
  latch to a different stable state), at the nominal cell and at the two
  extreme cells that bracket the old divider's measured min/max bias
  (`bcs/125 °C/1.98 V`, `wcs/−40 °C/1.62 V`).

  **Waveform settling audit (issue #154).** The deck samples only `n`,
  `n-10`, `n-25` of the transient (24.5 ns of a 12 us run), so the verdict
  above is a tail-sample check. `reduce_biasop.startup_waveform_audit` is a
  separately reported audit of every retained `startup_*.dat` sample in the
  physical-time window **2 us <= t <= 12 us** (ramp ends at 1 us plus a 1 us
  margin; the retained waveforms are within 0.6 % of final at 1.5 us). It
  applies the same tolerances (spread <= 2 %, every sample within 5 % of the
  paired DC `I_C1`, positive current) and requires finite values, strictly
  increasing time, >= 1000 in-window samples, window endpoints covered and a
  max sample gap <= 5 ns (5x the 1 ns step). Failures are named errors
  (`WaveformTruncatedError`, `WaveformNonfiniteError`,
  `WaveformNonmonotonicError`, `WaveformCoverageError`,
  `WaveformSampleGapError`), never PASS. Limit: excursions shorter than the
  1 ns sampling or outside the window are not seen. It never alters the
  historical three-sample verdicts. Replay with `--waveform-audit-csv`;
  reassessment of 20260921-173552-2aeafef is the derivation record
  `records/20260921-173552-2aeafef-startup-waveform-audit.{csv,md}`.

## Method limits (what this experiment does NOT measure)

- **No RF claim of any kind.** Replacing the divider *changes the RF
  impedance presented at `b1`*: the old divider's ~5.1 kΩ Thevenin becomes
  `R3b` (330 Ω) into a `Cbref`-grounded reference island. The
  S-parameter / gain / NF / k-factor / IIP3 consequences are measured by
  re-running [`../lna-characterization/run_lna_sweep.sh`](../lna-characterization/run_lna_sweep.sh)
  against the same committed netlist — not here.
- **No mismatch sections**: the grid uses `hbt_typ`/`hbt_bcs`/`hbt_wcs`,
  not the `_mismatch`/`_stat` variants, matching the fleet-wide campaign
  convention this grid mirrors. Physical mirror matching (Q1↔Q3 adjacency)
  is a layout-time concern this DC record does not encumber.
- **Ideal passives**: the mirror resistors are generic ideal SPICE `R`s
  with no tolerance or tempco — exactly like every other passive in this
  schematic (see `design/README.md`'s idealization notes). Resistor-ratio
  tolerance therefore does not appear in these numbers and must be
  budgeted before any ratified claim.
- **Model validity box**: `sg13g2_hbt_mod.lib` states its own validity
  range (`vbe` 0.65–0.96 V, `vce` 0.4–2.0 V, T −40…+125 °C, `ic` < 3 mA·Nx).
  The committed records show every instance riding inside that box; the
  closest calls are Q3's cold-`wcs` `V_BREF` and Q2's hot `V_CE1` margins.

## Statistical observables (T1 item 6): none measured yet

This bench's DC observables are the block's **initial statistical
observables**. They are `I_C1` (against DR-0001's `I_C1 ≤ 4.5 mA` mandate)
and the full-DUT total `I_DD` and `P_dc = VDD·I_DD` (against the ratified
< 10 mW Power row). They come first because they describe the same
committed DUT as the RF benches. They are also directly set by the DR-0003
core's mirror/servo devices, whose mismatch moves the bias current.

**Monte Carlo evidence for them is absent.** No record under
[`records/`](records/) is a statistical run. Every record is the
deterministic 45-cell corner grid described above, and the corner spread it
reports is process/temperature/supply spread, not a mismatch distribution.
The coverage gaps, kept separate:

- **Device mismatch is supported by the PDK models but not exercised.** The
  pinned PDK ships `*_mismatch`/`*_stat` sections for both device families
  in this DUT (`npn13G2` in `cornerHBT.lib`; `sg13_hv_pmos`/`sg13_hv_nmos`
  in `cornerMOShv.lib`). This bench loads only the nominal sections (see
  "No mismatch sections" above). It has not been verified that loading
  those sections actually injects stochastic parameters into the
  instantiated VBIC and PSP103.6/OSDI devices.
- **Resistor and passive tolerance: no bench covers it.** The bias
  resistors are ideal SPICE `R`s (see "Ideal passives" above). A device
  mismatch run on this netlist would therefore still hold every resistor
  ratio exact. Resistor-ratio tolerance needs its own treatment and is not
  part of the device-mismatch campaign.

The first campaign on these observables is
[#90](https://github.com/2AMLogic/sg13g2-lna/issues/90). **It is open and
has not been run.** As scoped, it is a fleet-submitted `klt sim`
`monte_carlo` request through this bench at one nominal point (27 °C,
1.80 V, nominal process sections). When its record lands, the resulting
distribution has these limits:

- It is a DC distribution at **one operating point**. It does not
  establish yield across the PVT box.
- It covers **device mismatch only**, and only as far as the campaign
  shows that sampling reaches the instantiated models. It covers no
  resistor/passive tolerance.
- It says nothing statistical about any RF row (gain, NF, IIP3, S11/S22,
  stability). Those are disclosed as unmeasured in
  [`../lna-characterization/`](../lna-characterization/README.md).
- An observed tail count against the 4.5 mA or 10 mW bar is a finite-sample
  observation, not a qualified yield figure or `klt yield` verdict.

The spec-level statement is
[`spec/target-spec.md`](../../spec/target-spec.md) §"Statistical coverage
(T1 item 6)".

## Cold-start / regeneration

```bash
export PDK_ROOT=/path/to/ihp-open-pdk   # parent dir containing ihp-sg13g2/
export PDK=ihp-sg13g2
sim/lna-bias-pvt/run_biasop_sweep.sh
```

Requires `ngspice`, the PDK resolution `../env.sh` performs, and —
since the DR-0003 Stage-2 core swap — the OSDI device models (the DUT
instantiates `sg13_hv_pmos`/`sg13_hv_nmos`, PSP103.6 via OSDI: run
[`../tools/build-osdi.sh`](../tools/build-osdi.sh) `--check` first; see
[`../README.md`](../README.md) "OSDI device models"); it needs python3 (stdlib only, for the reducer below) but not
xschem (`npn13G2` itself stays a native ngspice VBIC model —
see [`../pdk.json`](../pdk.json)). `BIASOP_JOBS=<n>` bounds concurrency
(concurrency changes wall-clock only); `BIASOP_SMOKE=1` runs the
nominal cell only as a plumbing check.

The BIASOP/STARTUP reduction is [`reduce_biasop.py`](reduce_biasop.py)
(issue #117): it validates required keys, finite values, one result per
point, the exact log inventory and every startup/op pair, and writes the two
CSVs only if all of that holds (exit 2 otherwise). Measured bar violations
and non-PASS startup verdicts are results, not malformed input. The record
prose takes its coverage counts and startup wording from the validated
reduction. Replay a retained record into scratch paths with
`reduce_biasop.py --corners-dir corners/<id> --summary-csv /tmp/s.csv --startup-csv /tmp/u.csv`
(add `--require-audit` for DR-0003-era logs); the unit tests in `tests/`
do this for both committed records and compare bytes. Smoke runs
(`BIASOP_SMOKE=1`) now also run only the nominal startup cell, since the
extreme startup cells have no op counterpart in a nominal-only run.

Every run mints a new timestamped record under `records/`, with generated
decks under `netlist-snapshots/<record-id>/` and raw ngspice logs under
`corners/<record-id>/`; nothing under an existing record is ever edited
(see [`../README.md`](../README.md)).
