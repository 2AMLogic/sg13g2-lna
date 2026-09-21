# lna-bias-pvt — DC op-point PVT sweep of the Q1 bias generator

Issue [#26](https://github.com/2AMLogic/sg13g2-lna/issues/26): the
acceptance bench for the Q1 bias-generator replacement (placeholder
resistive `R1a`/`R1b` divider → 8:1 density-matched `npn13G2`
current-mirror reference). Where
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

## Cold-start / regeneration

```bash
export PDK_ROOT=/path/to/ihp-open-pdk   # parent dir containing ihp-sg13g2/
export PDK=ihp-sg13g2
sim/lna-bias-pvt/run_biasop_sweep.sh
```

Requires `ngspice` and the PDK resolution `../env.sh` performs; requires
neither xschem, python3, nor an OSDI build step (`npn13G2` is a native
ngspice VBIC model — see [`../pdk.json`](../pdk.json)). `BIASOP_JOBS=<n>`
bounds concurrency (concurrency changes wall-clock only); `BIASOP_SMOKE=1`
runs the nominal cell only as a plumbing check.

Every run mints a new timestamped record under `records/`, with generated
decks under `netlist-snapshots/<record-id>/` and raw ngspice logs under
`corners/<record-id>/`; nothing under an existing record is ever edited
(see [`../README.md`](../README.md)).
