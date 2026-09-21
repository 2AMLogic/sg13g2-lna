# biasref-topology — flat PVT bias-reference design-space probes (issue #33 / DR-0003)

Issue [#33](https://github.com/2AMLogic/sg13g2-lna/issues/33) tracks the
flat PVT bias reference the committed `R3a`-feed mirror family cannot be
(DR-0001's 4.0 mA plan-table entry + the two ratified 45-cell bars). This
experiment is the **design-space evidence** behind the decision record
[`spec/decision-records/0003-flat-pvt-bias-reference.md`](../../spec/decision-records/0003-flat-pvt-bias-reference.md):
it measures the candidate families *before* any netlist locks, exactly the
order the issue's first acceptance criterion requires.

It is the first experiment in this tree that instantiates a MOS device
(`sg13_hv_pmos`, PSP103.6 via OSDI — see
[`../README.md`](../README.md) "OSDI device models" and
[`../tools/build-osdi.sh`](../tools/build-osdi.sh)).

## What is measured, and how (bench definitions)

Per `CLAUDE.md`: every recorded number carries its bench definition, and
the bench is committed beside the results. Three benches, one runner:

- **Phase A — `testbench/tb_mpa_diode.spice.tmpl`**: the `pnpMPA`
  diode-connected terminal drop (emitter fed, base+collector at vss —
  the substrate-PNP diode orientation a CMOS-style bandgap island uses)
  at forced feed currents {0.52 mA, 100 µA, 20 µA}, over
  `{typ,bcs,wcs} × {−40,27,125} °C` using the same `cornerHBT.lib`
  sections the committed 45-cell grid uses (`pnpMPA` is cornered by the
  same sections' `sgp_mpa_*` scalars — verified against the pinned
  install). The Curator pass of #33 inserted this device as Option B
  with its adequacy explicitly "not traced"; this bench is that trace.
- **Phase B — `testbench/tb_core_minigrid.spice.tmpl`**: the Option-A
  **first-increment core** — the self-biased Widlar PTAT skeleton, built
  from the PDK's own compact models: a diode-connected `sg13_hv_pmos`
  over the degenerated feedback leg (`npn13G2` `Nx=8`, emitter → `Rp`
  3.4 kΩ), a plain diode leg (`Nx=1`) whose base is cross-coupled to
  the feedback leg's base, a 10 MΩ startup seed on the plain-leg node,
  and a 21:1 output copy (`w=210u` mirror of the 10 µm loop legs) into
  the same `Nx=1` reference-island diode the committed netlist biases.
  Measured over `{typ,bcs,wcs} × {−40,27,125} °C × {1.62,1.80,1.98} V`,
  with the MOS corner mapped per
  [`../README.md`](../README.md) "Corner-label convention"
  (`typ→mos_tt`, `bcs→mos_ff`, `wcs→mos_ss`).
- **Phase C — `testbench/tb_core_startup.spice.tmpl`**: supply-ramp
  startup/latch check of the same skeleton at the three cells the
  committed `lna-bias-pvt` startup bench uses (`bcs/125 °C/1.98 V`,
  `wcs/−40 °C/1.62 V`, `typ/27 °C/1.80 V`): VDD ramps 0 V → target in
  1 µs, holds to 12 µs; the runner requires the island-current's last
  samples agree (settled, no ringing) and match the same cell's `op`
  value (no latch to a different stable state). This is the committed
  startup-bench convention, applied to the new core, because a
  self-biased PTAT loop has a genuine zero-current degenerate state the
  committed feedforward mirror family does not — the seed leg
  (`Rseed`) exists for exactly that reason and this bench is its
  evidence.
- **Phase D (Stage 2) — `testbench/tb_servo_minigrid.spice.tmpl`**: the
  complete DR-0003 Stage-2 flat core, whose device lines are the Stage-2
  core section of the committed `design/netlist/lna.spice` verbatim:
  the Phase-B skeleton unchanged, plus the Kuijk sum branch (`XMv`
  PTAT copy off the `nc_b` bus, `Rsum`, sum-branch diode `XQc`, node
  `V_BG = V_BE(Qc) + I_ptat·Rsum`), the amp-servo loop (`sg13_hv_nmos`
  input pair `XMnp1`/`XMnp2` — this tree's first nmos devices —
  resistor tail `Rtail`, PMOS diode load `XMld` + mirror `XMlm`, output
  node = the bank gate bus), the bare-resistor transduction branch
  (`XMref` + `Rl`: `I_ref = V_BG/Rl`) and the 12.8:1 island bank
  (`XMis`) into the same `XQ3` island diode. Same 27-cell box as Phase
  B. Evidences the Stage-2 core's own flatness (whole-box island
  spread vs nominal) and the servo's transparency (|vl − vbg|); records
  the sizing input behind DR-0003's Stage-2 sizing amendment. The two
  RATIFIED 45-cell bars are NOT evaluated here —
  [`../lna-bias-pvt/`](../lna-bias-pvt/README.md)'s record owns those
  against the swapped netlist.
- **Phase E (Stage 2) — `testbench/tb_servo_startup.spice.tmpl`**: the
  committed 3-cell ramp convention applied to the Phase-D core — the
  seed leg boots the skeleton AND the now-closing servo loop settles
  to the Phase-D op value at every cell, or the verdict records it.
  Same degenerate-state discipline as Phase C, plus the servo's own
  banks-off state and its amp-driven escape.

## Method limits (what this experiment does NOT measure)

- **No LNA instantiation, no RF claim of any kind.** These are probes
  of the reference core only; the committed
  [`../lna-characterization/`](../lna-characterization/README.md) benches
  own the RF consequences of any eventual bias change.
- **No flatness claim for the skeleton.** The Phase-B core's output tone
  is PTAT by design (hot/cold gains ≈ 1.35/0.77). It is the
  supply-independent *stage* of DR-0003 Option A — Phase D is the flat
  trim's measured evidence (island spread +0.75%/−1.02 % over the whole
  27-cell box), still a *bench-level* claim about the reference core,
  not the LNA.
- **Solver aids, not physics (Phases D/E).** The Phase-D/E decks' explicit
  `gmin=1e-10` is VALUE-IDENTICAL to ngspice's own default (no numeric
  shift); making it explicit selects ngspice's working gmin-stepping
  fallback — the implicit default aborts with singular iterations at the
  bcs/−40 °C/1.62 V cell. The Phase-E ramp's fine initial tran step
  (1e-9) is the sg13g2-bandgap fleet's own documented cure
  (closed-loop-startup / closed-loop-vref-pvt headers, issues #58/#151)
  for ngspice's VBIC boot-desert "Timestep too small" abort, which the
  committed 5e-8 step hits at the bcs/125 °C cell inside the first
  microsecond. The ramp shape and every verdict criterion are the
  committed ones unchanged.
- **No mismatch sections**: the grid uses the committed 45-cell
  convention (`hbt_typ`/`hbt_bcs`/`hbt_wcs` and single `mos_*` sections,
  no `_mismatch`/`_stat` variants). The 21:1 output mirror in
  particular must be centroid-matched at layout time before any
  ratified number.
- **Ideal resistors**: `Rp`/`Rseed` are generic ideal SPICE `R`s with
  no tolerance or tempco — the same idealization every committed bench
  and the committed schematic itself uses; resistor matching is a
  layout-time budget item.
- **Model validity boxes**: every `npn13G2` instance rides inside the
  model card's stated ranges; the `sg13_hv_pmos` instances run at
  |V_SD| well under the HV card's rating, honoring DR-0001's binding
  "any MOS in the bias network must be the HV flavour" constraint
  (1.98 V > the LV MOS 1.6 V VDS/VGS maximum).

## Why the committed-family comparison number is what it is

The runner compares the skeleton's island-current supply sensitivity
against the committed `R3a`-feed family **the identical way** (worst
per-(corner,T) move of the Q3 reference leg across the {1.62, 1.80,
1.98} V sweep, read out of the committed 45-cell record's own CSV): both
numbers are worst-case per-(corner,T) moves of the same physical
quantity, so the ~0.9% vs ~47% headline is a like-for-like ratio, not a
mixed-bench statistic.

## Cold-start / regeneration

```bash
export PDK_ROOT=/path/to/ihp-open-pdk   # parent dir containing ihp-sg13g2/
export PDK=ihp-sg13g2
sim/tools/build-osdi.sh --check         # OSDI models present + loadable
sim/biasref-topology/run_biasref_sweep.sh
```

Requires `ngspice` on PATH and the OSDI device models in
`$PDK_ROOT/$PDK/libs.tech/ngspice/osdi/` (built/loaded by
[`../tools/build-osdi.sh`](../tools/build-osdi.sh) — `sg13_hv_pmos` is
PSP103.6, a Verilog-A/OSDI device, unlike this tree's `npn13G2`-only
benches). `BIASREF_JOBS=<n>` bounds concurrency (wall-clock only);
`BIASREF_SMOKE=1` runs nominal cells only as a plumbing check. Every run
mints a new timestamped record under `records/`, with generated decks
under `netlist-snapshots/<record-id>/` and raw ngspice logs under
`corners/<record-id>/`; nothing under an existing record is ever edited
(see [`../README.md`](../README.md)).

## Records in this experiment

- `20260921-154716-f718094` — the Stage-1 record (PR #38's committed
  evidence): the Option-B disproof table (hot/nominal feed-family ratio
  1.392/1.335/1.326 at 0.52 mA/100 µA/20 µA — all worse than the
  committed npn family's own 1.277), the Option-A skeleton mini-grid
  (supply independence 0.90% vs the committed family's 47.4% measured
  identically; PTAT residual tone hot/cold ≈ 1.355/0.766 at the binding
  cells), and the seed-leg startup PASS at all three ramp cells. Backs
  DR-0003.
- `20260921-173323-2aeafef` — the five-phase record (issue #33's Stage-2
  increment; Phases A-C reproduce `20260921-154716-f718094`'s numbers
  byte-identically): Phases D/E add the complete Stage-2 core
  (skeleton + Kuijk sum branch + amp-servo loop + `V_BG/Rl`
  transduction + 12.8:1 island bank) — island current spread
  **+0.75%/−1.02%** of nominal over the whole 27-cell box, worst servo
  transduction error **1.06 mV**, supply move ≤ 0.51% per (corner,T),
  closing-loop startup PASS ×3. The sizing evidence behind DR-0003's
  Stage-2 sizing amendment; the ratified 45-cell bars on the swapped
  netlist live in
  [`../lna-bias-pvt/records/20260921-173552-2aeafef`](../lna-bias-pvt/records/20260921-173552-2aeafef.md).
