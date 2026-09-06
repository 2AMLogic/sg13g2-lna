# Porting plan — what transfers, and what is genuinely novel RF work

**Status: engineering input, not a ratified decision.** This document is
the required reading for anyone starting design work on this block. It does
not ratify the target spec (`target-spec.md` remains DRAFT, gated on a
future spec-ratification issue) — it records what the fleet's existing
SG13G2 blocks already teach about this PDK, and draws a hard line around
the RF-specific work this block cannot borrow from anywhere in the fleet.

**This block has no same-block sibling.** Every other spec-scaffolding
issue in this fleet ("bootstrap the block") has been a second-or-third PDK
port of an already-ratified design (`sg13g2-ldo` from `gf180-ldo`,
`sky130-ldo`; `sg13g2-bandgap` from `gf180-bandgap`, `sky130-bandgap`).
There is no `gf180-lna` or `sky130-lna` to port from. What this document
can do instead is name the nearest mature siblings **on the same PDK
deck** — `sg13g2-bandgap`, `sg13g2-pll`, `sg13g2-ldo` — and separate what
they teach about the SG13G2 deck itself (which transfers) from what an LNA
specifically needs (which does not exist anywhere in the fleet yet, RF
small-signal work being categorically different from bandgap/PLL/LDO's
DC-and-lock-loop concerns).

**Sources checked** (read first, per the issue body, rather than starting
from a blank page):

- `2AMLogic/sg13g2-bandgap` `spec/porting-plan.md`,
  `spec/decision-records/0001-bipolar-device-selection.md`,
  `spec/decision-records/0002-supply-voltage-scope.md`,
  `spec/README.md` — the most mature block on this PDK deck, and the only
  other block in the fleet that has already had to decide "which SG13G2
  bipolar device" (its `npn13g2`-vs-`pnpMPA` decision record is the closest
  precedent for a bipolar-device choice, even though this block's choice —
  `npn13g2` as an RF gain device, not a bandgap core device — is a
  different question with a different answer).
- `2AMLogic/sg13g2-pll` `spec/porting-plan.md`, `spec/README.md`,
  `spec/decision-records/DR-002-supply-device-flavor.md` — the other
  RF-adjacent block in the fleet (a PLL's VCO touches small-signal
  oscillator design, closer in spirit to this block than a bandgap or LDO),
  and its `spec/README.md` index structure is the one this repo's own
  `spec/README.md` mirrors. Notably, `sg13g2-pll`'s own porting plan records
  that **no target spec exists yet** for that block either, pending its
  own architecture decision records — the same "decisions before numbers"
  posture this document takes for the bias/topology question below.
- `2AMLogic/sg13g2-ldo` `README.md` (target-spec section — this block keeps
  its table in the top-level README rather than a separate `spec/` file)
  and `spec/porting-plan.md` — the fleet's other single-stage analog block
  on this PDK, useful for the "port a known circuit, PDK is the variable"
  framing this block explicitly cannot use (there is no known circuit to
  hold constant here).
- `IHP-GmbH/IHP-Open-PDK`, `main` branch, commit
  [`5e6d592`](https://github.com/IHP-GmbH/IHP-Open-PDK/commit/5e6d592e4002946a4616f798c357f0f3c06cf3b6)
  (2026-09-01) — read directly for this issue, since `klt`'s PDK-resolver
  step has not run for this repo yet. **A public-repo `main` read is
  provisional until `klt`'s actually-resolved PDK checkout is known** — the
  same caveat `sg13g2-bandgap/spec/porting-plan.md` states for itself.
  Specifically:
  - `ihp-sg13g2/libs.doc/doc/SG13G2_os_process_spec.pdf` (Rev. 1.2,
    2023-12-20), §1 "General Information" and §3.1 "npn13g2" — the HBT's
    fT/fmax/BVCEO/BF/IC07 numbers cited in `target-spec.md`.
  - `ihp-sg13g2/libs.tech/ngspice/models/sg13g2_hbt_mod.lib` and
    `sg13g2_hbt_stat.lib` — the VBIC (Rev. 1.15) SPICE model card and its
    statistical/mismatch counterpart for `npn13g2` (a 4-terminal device
    with an internal thermal pseudo-node — see §4 below for the LVS
    implication `sg13g2-bandgap`'s plan already flagged).
  - `ihp-sg13g2/libs.tech/ngspice/models/cornerHBT.lib` — the five-corner
    (tt/ff/ss/fs/sf) HBT corner file this repo's `target-spec.md`
    verification-corners section cites.
  - Passive/matching-network model surface checked and found **thinner
    than the active-device surface**: `ihp-sg13g2/libs.tech/ngspice/models/`
    has no file resembling an inductor SPICE model (searched for `induct*`
    in that directory — none found), while MIM/MOM capacitor models exist
    (`capacitors_mod.lib`, `cap_cmomf.lib`, `cap_cmomi.lib`,
    `cornerCAP.lib`) and a varactor model exists
    (`sg13g2_svaricaphv_mod.lib`) for potential future tunable-matching
    work. What exists instead for inductors is layout-side only:
    `ihp-sg13g2/libs.tech/klayout/python/sg13g2_pycell_lib/ihp/inductor2_code.py`
    / `inductor3_code.py` (pycell generators) and xschem symbols
    (`ihp-sg13g2/libs.tech/xschem/sg13g2_pr/inductor.sym`,
    `inductor3.sym`). **Whether a corresponding SPICE (or S-parameter/EM)
    model ships anywhere in this PDK for inductor devices — as opposed to
    only a layout generator and a schematic symbol — was not resolved by
    this issue** and is this repo's single highest-priority open tooling
    question (§4, item 1); it directly gates whether inductive source/load
    degeneration (this block's entire matching-network approach, per
    `CLAUDE.md`) can be simulated at all before layout extraction exists.

## 1. What carries over unchanged (transfers from the SG13G2 deck siblings)

- **The verification discipline.** PVT-cornered testbenches
  (−40/27/125 °C × supply × process corner), append-only `sim/` records, no
  claim without a testbench (`CLAUDE.md`; the convention all three named
  siblings already follow). Nothing about this being an RF block changes
  this — if anything, `CLAUDE.md`'s house rules go further here (a
  dedicated stability-spec-row requirement, an honest-IIP3-method
  requirement) than any sibling's spec needs to state, precisely because
  small-signal/noise/linearity claims are easier to overstate than a DC
  reference voltage or a lock time.
- **The decision-record process itself.** One decision per record,
  numbered sequentially, never rewritten once ratified — superseded
  instead. `sg13g2-bandgap` uses `NNNN-<slug>.md`; this repo has no
  decision records yet, and will start its own `spec/decision-records/`
  directory the same way once the first decision (the bias/topology
  question in `target-spec.md`) is ready to record.
- **The friction protocol.** Tool gaps get filed generically against
  `klayout-tools`, design specifics stay out of that tracker — unchanged by
  which block or PDK triggered the gap. The inductor-model question in
  "Sources checked" above is exactly the kind of gap this protocol exists
  for, once it is confirmed (rather than merely suspected from a directory
  listing) to be a real tooling absence rather than a file this survey
  missed.
- **`npn13g2` as a known, well-characterized device.** `sg13g2-bandgap`'s
  DR-0001 already did the first characterization pass on this exact device
  (VBIC Rev. 1.15, BF target 650, `BVCEO` target 1.6 V / min 1.4 V) for a
  DC bandgap-core use case. The device numbers transfer directly (same
  device, same model card); the **use case does not** — a bandgap core
  wants a stable, low-noise DC operating point far from breakdown, while an
  RF gain stage wants to bias near the device's peak-fT current density
  (per Voinigescu-style optimum-NF sizing, `target-spec.md` source 1) and
  cares about `BVCEO` as a hard ceiling on *signal-swing* headroom, not
  merely a DC reliability margin. `sg13g2-bandgap`'s LVS/thermal-pseudo-node
  tooling-friction finding (its plan's §"Tooling friction anticipated in
  advance", item 1: the VBIC self-heating thermal node `t`/`Rt`/`cth`/`rth`
  needs correct pseudo-node handling in extraction) transfers unchanged —
  this block will exercise the identical device model, so the identical
  LVS risk applies.
- **The general "port target-spec structure" shape**, not the numbers.
  `sg13g2-ldo` and `sky130-ldo`'s target-spec tables (Input/Output/Load/…)
  and `sg13g2-bandgap`'s seven-row shape both establish the convention of a
  DRAFT status banner, a sourced "where these numbers come from" section,
  and a per-row Src citation — `target-spec.md` in this repo follows that
  shape, adapted to RF headline parameters (band/gain/NF/S11/S22/IIP3/
  supply-power) instead of DC ones.

## 2. What is genuinely novel RF work (no sibling precedent — this block's canary value)

None of `sg13g2-bandgap`, `sg13g2-pll`, or `sg13g2-ldo` have had to answer
any of the following. This is, per the issue framing, exactly why this
block's canary value is real rather than a relabeled CMOS port:

- **S-parameter and noise-figure bench methodology with ngspice's `.sp` and
  `.noise` analyses.** No sibling repo runs either analysis — bandgap/PLL/
  LDO verification is DC operating-point, transient, and (for the PLL)
  phase-noise/lock-time focused. Port impedance conventions, source-pull
  assumptions, and de-embedding (if any) are new ground this repo's README
  already names as "the first work."
- **Inductive source/load degeneration and its passive-model dependency.**
  As found in "Sources checked" above, this PDK's inductor support may be
  layout-pycell-and-symbol-only with no confirmed SPICE/EM model — a
  question none of the three siblings needed to ask, since none of them
  uses on-chip spiral inductors in their core topology. If confirmed, this
  is this block's first `klayout-tools` friction filing, and it blocks
  simulating S11/S22/gain at all (not just confirming a target — the
  testbench itself has no passive model to drive) until resolved.
  `sg13g2-pll`'s own architecture decision record
  (`DR-001-pll-architecture.md`, which chose between a current-starved CMOS
  ring and an HBT-based LC-tank VCO) is the closest sibling precedent for
  "does an inductor-dependent topology work on this PDK," but that
  decision was about *architecture selection*, not about verifying an
  inductor SPICE model exists — worth reading for context, not reusable
  for this specific gap.
- **Bias/supply topology under a genuinely low breakdown-voltage device.**
  See `target-spec.md`'s "Open topology question." The CMOS-canary supply
  decisions this fleet already has (`sg13g2-bandgap` DR-0002,
  `sg13g2-pll` DR-002) reason about MOS gate-oxide voltage ratings across
  a 1.2 V-LV-core-vs-3.3 V-HV-IO menu — a completely different constraint
  shape than a bipolar `BVCEO` ceiling that a cascode stage must actively
  avoid exceeding node-by-node. The decision-record *process* transfers;
  none of the reasoning in those two records does.
- **Stability (k-factor / stability-circle) analysis across PVT, in-band
  and out-of-band.** Not a concept any DC or lock-loop block in this fleet
  needs — a bandgap or LDO does not have a small-signal instability failure
  mode in the RF sense, and a PLL's loop stability (phase margin of the
  feedback loop) is a different mathematical object than a two-port's
  k-factor. `CLAUDE.md`'s explicit "stability is a spec row, not an
  afterthought" rule exists because this repo, uniquely in the fleet, needs
  it.
- **Honest IIP3 measurement via two-tone transient.** No sibling repo
  measures a linearity figure at all — DC blocks don't have a two-tone
  linearity concept, and this repo's own `CLAUDE.md` calls out that the
  method's limits (tone spacing, FFT parameters, aliasing risk in a
  transient-domain two-tone sim) must be stated honestly alongside any
  number. This is new testbench-design work end to end.
- **Device noise-optimum sizing.** `sg13g2-bandgap`'s device work sizes
  `npn13g2` for DC matching/mismatch (the `A.al` matching-coefficient
  condition its plan cites). This block instead needs a
  Voinigescu-style optimum bias-current-density-for-minimum-NF derivation
  against `sg13g2_hbt_mod.lib`'s actual (not yet examined by this issue)
  noise parameters — a different device-characterization question with no
  fleet precedent.

## 3. Next steps

This plan and `target-spec.md` are inputs to: (a) a future
spec-ratification issue for the target-spec table, (b) a decision record
resolving the bias/supply-topology question, and (c) confirming or refuting
the suspected inductor-SPICE-model gap (item 2 above) — which, if
confirmed, should be filed against `klayout-tools` per this repo's friction
protocol before any matching-network schematic work proceeds. Nothing in
this document authorizes schematic, layout, or simulation work ahead of
those steps.
