# sim/ — ngspice testbenches and append-only evidence

This directory holds ngspice testbenches and their results for the
sg13g2-lna canary block, following the same evidence-record convention the
fleet's more mature SG13G2 ports (`sg13g2-bandgap`, `sg13g2-opamp`)
established. Per `CLAUDE.md`: **verification is the product, no claim
without a testbench**, and results here are **append-only evidence** — a
re-run mints a new, timestamped record; nothing under `records/`,
`netlist-snapshots/` or `corners/` is ever edited or deleted after it
lands.

## PDK pin

Every record in this tree is generated against the PDK revision pinned in
[`pdk.json`](pdk.json) (currently `IHP-Open-PDK` tag `v0.3.0`, fetchable
via `klayout-tools`' `scripts/fetch-ihp-sg13g2.sh`). Every record's own
`## PDK` field additionally states the exact `PDK_ROOT`/`ngspice -v` the
run used, so a later reader can tell whether their own environment matches
without re-deriving it from the pin file alone.

`source env.sh` resolves `PDK_ROOT`/`PDK` the same way `sg13g2-bandgap` and
`sg13g2-opamp` do (env vars first, then the usual open_pdks install
prefixes) — every testbench's `run_*.sh` sources it, and an interactive
`ngspice` session can too, so nothing here can silently drift onto a
different install than what a script used. It also carries the shared
runner surface documented below.

## Shared runner surface (`sim/env.sh`)

Every `run_*_sweep.sh` opens the same way: resolve the PDK, refuse to run
without it, mint a `<record-id>`, create the output dirs, then render decks
and (for the concurrent benches) schedule `ngspice -b` runs. That
scaffolding lives once, in `env.sh`, and each runner calls it:

| Helper | Contract |
|---|---|
| `sim_require_pdk <script-name> [--osdi]` | The preflight. Any miss — no resolvable PDK, no `ngspice` on PATH, no `cornerHBT.lib`, or (with `--osdi`) no `cornerMOShv.lib`/`.osdi` models — prints `"<script-name>: …"` on **stderr** and exits **3**. The `<script-name>` argument is what keeps that message prefix per-runner. On success it sets `NGSPICE_VERSION`, `MODELS_LIB` and, with `--osdi`, `MOS_LIB`/`OSDI_DIR`. Paths come from `env.sh`'s own `SG13G2_NGSPICE_MODELS`, so there is exactly one definition of where the model libs live. |
| `sim_record_paths` | Mints `RECORD_ID` (`<YYYYMMDD>-<HHMMSS>-<short-git-sha>`, UTC) and sets + creates `SNAPSHOTS_OUT`, `CORNERS_OUT`, `RECORDS_DIR` under the caller's `SCRIPT_DIR`. |
| `sim_jobs <var-name>` | Sets `<var-name>` to `min(6, ncpu/3)`, floor 1, unless it is already set in the environment — an explicit `*_JOBS` knob wins. |
| `sim_pool_init <jobs>` / `sim_pool_spawn <fn> <args…>` | The bash-4.3 `wait -n` job pool. `SIM_POOL_SPAWNED` counts what was scheduled (what a record quotes as "N ngspice invocations"). |
| `sim_render <tmpl> <out> <sed-args…>` | Applies the caller's own substitutions, then `@@MODELS_LIB@@`/`@@MOS_LIB@@`/`@@OSDI_DIR@@`; if `SIM_DUT_SUBCKT` is set, splices that file in at `@@LNA_SUBCKT@@`. |
| `sim_check_log <point-id> <log> <rc>` | Per-point gate: non-zero `rc`, any pattern the runner put in `SIM_LOG_FAIL_PATTERNS`, or a missing `BENCH_COMPLETE` marker fails the point and appends its id to `${FAILED_LIST}`. |

**What deliberately does NOT move into `env.sh`**: sweep grids,
`HBT_SECTION_OF`/`MOS_SECTION_OF` maps, per-experiment template
substitutions, `*_SMOKE` overrides, `python3` requirements, and the
bespoke failure criteria of `hbt-characterization` and
`breakdown-extraction` (both count emitted `PT ` lines against an expected
`N_POINTS`, and both are deliberately serial, so neither uses
`sim_pool_spawn` or `sim_check_log`). Those are **bench definitions** — per
"Bench definitions carry with every number" below, they stay visible in
the runner that owns them.

**OSDI device models: needed as of `sim/biasref-topology/` and — since the
DR-0003 Stage-2 core swap put `sg13_hv_pmos`/`sg13_hv_nmos` into the
committed `design/netlist/lna.spice` itself — `sim/lna-bias-pvt/` and
`sim/lna-characterization/` too (issue #33; the latter re-baselined under
issue #49).**
The first experiments in this tree instantiate only `npn13G2` and
`pnpMPA` — native ngspice models (VBIC level=9 and Gummel-Poon level=1)
loaded by `cornerHBT.lib`'s own sections, no compile step. The
bias-reference work (DR-0003) instantiated the MOS device those
HBT-only precedes never did: `sg13_hv_pmos`, PSP103.6, a Verilog-A
compact model ngspice can only load as an OSDI-compiled library
(IHP-Open-PDK v0.3.0 ships the Verilog-A sources but no prebuilt
`.osdi` binaries). `sim/tools/build-osdi.sh` — ported from
`sg13g2-bandgap`'s, the fleet precedent for this same pinned PDK, with
identical compiler pins — compiles the PDK's own Verilog-A sources with
a checksum-pinned `OpenVAF-Reloaded v24.0.1mob`; `--check` verifies the
models are present and loadable. Every bench that instantiates a MOS
(or r3_cmc resistor) device `pre_osdi`-loads from
`$PDK_ROOT/$PDK/libs.tech/ngspice/osdi/` — those benches refuse to run
without them (see each runner's preflight). `pdk.json`'s
`device_models_used_by_this_repo_so_far` and `osdi_toolchain` block
restate the device inventory and pins.

## Directory / naming convention

```
sim/
  README.md            this file — the authoritative convention
  pdk.json              pinned PDK revision (see "PDK pin" above)
  env.sh                 PDK_ROOT/PDK resolution + the shared runner
                          helpers, sourced by every testbench
  <experiment-slug>/     one directory per distinct claim under test
    README.md            testbench rationale, bench definitions (port
                          impedance, bias-network idealizations, frequency),
                          the exact ngspice analyses used, model
                          limitations, and a regeneration command (required)
    testbench/
      tb_<name>.spice.tmpl   the testbench netlist generation template(s)
    run_*.sh              the cold-start entry point for this experiment
    netlist-snapshots/
      <record-id>/
        <point-id>.spice    the exact generated netlist for that grid point
    corners/
      <record-id>/
        <point-id>.log      raw ngspice batch output for that grid point
    records/
      <record-id>.md         append-only human-readable summary
      <record-id>.csv         append-only parsed/machine-readable data
```

- **`<experiment-slug>`** — short, kebab-case, one directory per distinct
  claim being tested (e.g. `hbt-characterization`), not per run.
- **`<record-id>`** — `<YYYYMMDD>-<HHMMSS>-<short-git-sha>` (UTC), e.g.
  `20260910-153000-7da7038`. A re-run mints a new `<record-id>`; nothing
  under an existing one is ever edited.

## Corner-label convention: `cornerHBT.lib` has three sections, not five

`spec/target-spec.md`'s "Verification corners" section and
`spec/porting-plan.md` described `cornerHBT.lib` as shipping "the five
process corners {tt, ff, ss, fs, sf}" at the time this convention was
recorded; `target-spec.md`'s Verification corners section now records the
three-section reality. **Verified against the pinned PDK
install (`v0.3.0`): `cornerHBT.lib` actually defines three real sections
— `hbt_typ`, `hbt_bcs`, `hbt_wcs`** (plus `_mismatch`/`_stat` variants of
each) — no skewed `sf`/`fs`-equivalent HBT section exists. This is the
same situation `sg13g2-bandgap/sim/README.md`'s "Directory / naming
convention" section already documents and solves for its own HBT-bearing
testbenches: a five-label PVT grid (`typ`, `bcs`, `wcs`, `sf`, `fs`, mirroring
`cornerMOShv.lib`'s five labels for consistency across the fleet) is
mapped onto the HBT device's own three real sections, with the two skewed
labels (`sf`, `fs`) falling back to `hbt_typ`:

```
typ -> hbt_typ
bcs -> hbt_bcs   (best-case speed)
wcs -> hbt_wcs   (worst-case speed)
sf  -> hbt_typ   (no skewed HBT section exists; falls back to typical)
fs  -> hbt_typ   (no skewed HBT section exists; falls back to typical)
```

Every experiment in this tree that sweeps HBT process corners uses this
exact mapping and states it in its own README — this file records the
convention once so it is not silently re-derived (or missed) per
experiment. This is a documentation/PDK-content discrepancy between this
repo's own `spec/` documents and the installed PDK, not a `klayout-tools`
gap (`klt` resolves PDK paths; it does not author corner-lib content) —
noted here per `CLAUDE.md`'s friction protocol, not filed externally.

**MOS-bearing benches use the sibling fleet's MOS-label mapping.** Since
`sim/biasref-topology/` (issue #33) instantiates `sg13_hv_pmos`, a
MOS-corner mapping is needed too. `cornerMOShv.lib` — unlike
`cornerHBT.lib` — ships all five real sections (`mos_tt`, `mos_ss`,
`mos_ff`, `mos_sf`, `mos_fs`, verified against the pinned install), so
the five-label grid maps straight through, using the same pairing
`sg13g2-bandgap/sim/lib/pvt_preflight.sh` established for this PDK:

```
typ -> mos_tt      bcs -> mos_ff      wcs -> mos_ss
sf  -> mos_sf      fs  -> mos_fs
```

The HBT mapping above and this MOS mapping are used together by any
generated deck that instantiates both device families — `sim/biasref-topology/`'s
runner, `sim/lna-bias-pvt/`'s, and (since the DR-0003 core landed in the
committed DUT) `sim/lna-characterization/`'s. A consequence worth stating
where the convention lives: on a bench that instantiates **both**
families, `sf`/`fs` cells are no longer numerically identical to `typ` —
the HBT side still duplicates `hbt_typ`, but the MOS side is a real,
distinct section. They are still not independent *RF* corners wherever an
HBT sets the RF behaviour.

## Append-only rule

`records/*.md`, `records/*.csv`, `netlist-snapshots/**` and `corners/**`
files are **never** edited or deleted after creation. A correction or a
re-run always mints a new `<record-id>`.

## Bench definitions carry with every number

Per `CLAUDE.md`: "NF and S-param numbers carry their bench definitions.
Port impedances, bias points, and the exact ngspice analysis (.sp/.noise)
are committed beside every recorded number." Every experiment's own
`README.md` states the port impedance, bias-network idealizations
(ideal bias tees / ideal source and load terminations), and the exact
ngspice analysis (`.op`, `.ac`, `.noise`) used for each reported quantity
— this file does not restate those per-experiment details.

## Spec ratification: not claimed here

Nothing in this tree ratifies a `spec/target-spec.md` row: ratification is
a decision-record act, and it happened via decision record
[0002](../spec/decision-records/0002-target-spec-first-ratification.md)
(issue [#19](https://github.com/2AMLogic/sg13g2-lna/issues/19), merged as
PR #32) — which marked the band, gain, NF, S11/S22, stability, supply and
power rows RATIFIED and left the IIP3 numeric target and every stretch
column DRAFT. Every experiment's `README.md` and record keeps its local
disclaimer: results here are device-characterization *evidence* — the
input record 0002 was ratified against — not a conformance claim against
a target-spec row.

## Testbenches landed so far

- **[`hbt-characterization/`](hbt-characterization/README.md)** — the
  first testbench in this tree (issue #7, extended by issue #21):
  `npn13G2` fT, 50 Ω-referenced noise figure at 2.4 GHz, and
  50 Ω-terminated transducer gain at 2.4 GHz, swept over collector current
  density (via a dense base-voltage sweep) and `V_CE` ∈
  {0.6, 0.8, 1.0, 1.2, 1.4} V, across the HBT process-corner grid above ×
  {−40, 27, 125} °C, at emitter multiplicity `Nx` ∈ {1, 8}. Device-level
  input to `spec/decision-records/0001-bias-supply-topology.md` — not the
  decision itself, and not a claim against any `target-spec.md` row.
  Two records: `20260910-200059-7da7038` (#7, `Nx=1` grid + one `Nx=8`
  spot check, `V_CE` ≥ 0.8 V) and `20260918-203652-4293920` (#21, both
  `Nx` across the full grid, `V_CE` down to 0.6 V, with model-card
  validity-box flags per row). Per the append-only rule above the first
  record is untouched; see that experiment's README §"Records in this
  experiment" for which tables come from which.
- **[`lna-characterization/`](lna-characterization/README.md)** — the first
  **circuit-level** testbench in this tree (issue #18), run against
  `design/lna.sch` via its committed netlist: ngspice `sp` S-parameters
  (S11/S21/S12/S22) at 50 Ω ports across the 2400–2483.5 MHz band
  (ratified by DR-0002),
  noise figure at two stated reference temperatures cross-checked against
  ngspice's own two-port `sp` NF (plus `NFmin`), k/μ/|Δ| stability in-band
  **and** out-of-band from 10 MHz to 30 GHz, and two-tone transient IIP3
  with committed tone-spacing/FFT parameters — over the full
  {typ, bcs, wcs, sf, fs} × {−40, 27, 125} °C × {1.62, 1.80, 1.98} V grid.
  Evidence *for* the spec ratification (issue #19 → decision record 0002),
  not a conformance claim;
  its own README states why the DUT's ideal-passive models (no PDK inductor
  model exists — issue #5) bound what these numbers can be trusted to mean.
- **[`breakdown-extraction/`](breakdown-extraction/README.md)** — issue
  #20: `npn13G2` collector–emitter breakdown extracted from the model
  card's own weak-avalanche parameters, over the same corner × {−40, 27,
  125} °C grid × `Nx` ∈ {1, 8}. BVCEO (open base) and BVCER/BVCES
  (finite and shorted base terminations) are both extracted by a
  **current-driven continuation** — the collector current is forced and
  `V_CE` measured — because the voltage-driven `.dc` sweep the naive
  method uses follows whichever branch of the S-shaped snapback locus
  its initial guess lands on, and that failure is reproduced as a
  committed control. Evidence for
  `spec/decision-records/0001-bias-supply-topology.md`'s breakdown
  budget; DC-only, no RF port or 50 Ω reference anywhere, and not a
  claim against any `target-spec.md` row.
- **[`biasref-topology/`](biasref-topology/README.md)** — issue #33 /
  DR-0003: the flat-bias-reference design-space probes, **the first
  bench in this tree to instantiate a MOS device** (`sg13_hv_pmos`,
  PSP103.6 via OSDI — the toolchain `sim/tools/build-osdi.sh` exists
  for). Three benches in one runner: the `pnpMPA` diode trace (Option
  B's "not traced" adequacy question, answered measured — its feed
  family is PVT-worse than the committed npn family at every traced
  current), the Option-A first-increment core (the self-biased Widlar
  PTAT skeleton: supply independence 0.90% worst-case across the ±10%
  VDD swing vs the committed feed family's 47.4% measured the identical
  way, with the residual PTAT tone DR-0003's Stage-2 core must trim),
  and the seed-leg supply-ramp startup check (PASS at the three
  committed startup cells). Its Stage-2 increment (same runner,
  phases D/E) adds the complete sized flat core — skeleton + Kuijk sum
  branch (`XMv`/`Rsum`/`XQc` building `V_BG = V_BE + I_ptat*Rsum`) +
  amp-servo loop (the tree's first `sg13_hv_nmos` instances,
  `XMnp1`/`XMnp2`) + bare-resistor transduction (`I_ref = V_BG/Rl`)
  + 12.8:1 island bank — evidencing the core's own whole-box island
  spread (+0.75%/-1.02% vs nominal) and its closing-loop startup, the
  sizing input behind DR-0003's Stage-2 sizing amendment. Design-space
  input to DR-0003 — no `target-spec.md` claim, no LNA instantiation;
  the two RATIFIED 45-cell bars on the swapped netlist are
  [`lna-bias-pvt/`](lna-bias-pvt/README.md)'s own record, not this
  one's.
- **[`lna-core-envelope/`](lna-core-envelope/README.md)** — issue #52: what
  (gain, NF, P_dc) envelope is achievable on `npn13G2` **at all**, as
  distinct from what the committed DUT measures. Re-runs
  `lna-characterization/`'s own sp/NF/stability bench, character-for-
  character, over 15 DUT **variants** across the same 45-cell PVT grid
  (675 decks): a constant-`J_C` emitter-area family, a constant-`I_C`
  current-density family (emitter area 4 … 80 unit emitters, mirror width
  scaled inversely), and four two-stage cascades on one shared bias core.
  The committed netlist runs as the control variant `s_ctrl_a8` and the
  parser **refuses to write a record** unless it reproduces
  `lna-characterization` record `20260926-122301-088c734` (it currently
  reproduces it to `0.000e+00` relative difference at all 45 cells). Also
  carries a derivation-only half — no PDK, no ngspice — that re-references
  that committed record's `NFmin` to the RATIFIED T0 = 290 K (ngspice's
  `sp` NF is **analysis-temperature** referenced, proven against the
  record's own independent `.noise` column to 9.2e-5 dB) and computes its
  gain envelope against collector-tank inductor Q. Evidence for
  `spec/decision-records/0004-achievable-gain-nf-power-envelope.md`; every
  variant except the control is a **probe**, nothing under `design/`
  changes because of it, and no number here is a `target-spec.md`
  conformance claim.
