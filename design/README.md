# design/

Schematics (xschem) and netlists for the cascode LNA core (issue #17),
implementing exactly the topology and supply voltage
[`spec/decision-records/0001-bias-supply-topology.md`](../spec/decision-records/0001-bias-supply-topology.md)
(DR-1, "proposed", merged via PR #22) specifies.

```
design/
  xschemrc         repo xschem config: resolves the SG13G2 PDK, adds this
                    repo's own symbol/testbench directories to the library
                    path (fleet convention, ported from
                    sg13g2-opamp/design/xschemrc / sg13g2-bandgap's)
  lna.sch           the LNA core schematic
  lna.sym           hierarchical-instantiation symbol for the above, for a
                     future testbench (issue #18) to instantiate directly
  netlist/lna.spice  xschem-generated netlist (committed -- reviewable in
                     git, same convention every sibling canary uses)
```

## What's here (issues #17, #26)

- **`lna.sch`** — a cascode LNA: `Q1` (common-emitter input device) stacked
  under `Q2` (common-base cascode device), both `sg13g2_pr/npn13G2`
  (native VBIC, `Nx=8`), with `Q1`'s emitter inductively degenerated (`Le`)
  and `Q2`'s collector inductively loaded (`Lc`). `Q2`'s base bias (`vb2`)
  is an 11:1 resistive divider off `VDD`, RF-bypassed — DR-1's own
  `V_B2 = (11/12)*VDD` requirement, implemented as a resistor *ratio* (not
  an absolute value) exactly as the record specifies. `Q1`'s base bias is
  the 8:1 density-matched mirror-reference generator issue #26 replaced
  the placeholder divider with (honesty caveat 2 below states the
  measured envelope and the two design consequences). Full node-by-node
  wiring, the reasoning behind every non-DR-1-mandated choice, and a
  reproducible single-point ngspice sanity check are in the schematic's own
  header comment — read that first; this README is a pointer, not a
  re-derivation.
- **`lna.sym`** — hierarchical-instantiation symbol, pins `vdd`, `vss`,
  `rfin`, `rfout` matching `lna.sch`'s own `iopin` list and order exactly.
- **`netlist/lna.spice`** — the netlist `lna.sch` regenerates to (see
  "Running xschem / regenerating the netlist" below). This is a **flat**
  netlist (xschem emits its top-level `.subckt`/`.ends` lines as full-line
  SPICE comments, `**.subckt ...`, when the schematic is netlisted
  directly rather than instantiated via `lna.sym` elsewhere) — a future
  testbench either `.include`s it directly, or instantiates it via
  `lna.sym` in a hierarchical schematic of its own (both were verified to
  work — see "What has been verified" below).

## What these design issues do NOT do

Per `CLAUDE.md`'s evidence discipline ("no claim without a testbench") and
the schematic issues' own explicit scope: **no S-parameter, gain, NF,
k-factor (stability), or IIP3 claim is made by this schematic, its netlist,
or this README.** Those live in the PVT-corner testbenches issue #18 added
under `sim/`, which are re-run against this same netlist after the issue
#26 bias change. The simulation evidence cited below is the DC evidence:
the single-point sanity check of the schematic's header (typ corner, 27 °C,
nominal `VDD`) and the 45-cell op-point sweep of `sim/lna-bias-pvt/` —
not an RF performance result.

## Two honesty caveats this schematic makes explicit (read `lna.sch`'s
## header for the full reasoning)

1. **`Le` and `Lc` (the source-degeneration and load inductors) are
   idealized/lumped values** (generic xschem `ind` primitive, a bare SPICE
   `L`), **not** `sg13g2_pr/inductor.sym`. Issue #5 (closed) confirmed, and
   [`2AMLogic/klayout-tools#1519`](https://github.com/2AMLogic/klayout-tools/issues/1519)
   tracks upstream, that SG13G2's open-source PDK ships **no simulatable
   SPICE/EM model** for any on-chip inductor geometry — the PDK's own
   `inductor.sym` is LVS/layout-pcell-only, with no backing `.subckt`.
   Using that PDK symbol here would net-list to an unresolved device while
   silently looking PDK-accurate. `Le=1nH`, `Lc=5nH` are plausible
   orders of magnitude for 2.4 GHz inductive degeneration/loading, **not**
   a matching-network design result — no real value can be committed until
   #5's tracked upstream gap closes or this repo adopts a documented
   extraction methodology of its own.
2. **`Q1`'s base bias is an 8:1 density-matched `npn13G2` current-mirror
   reference (issue #26)** — the placeholder resistive divider this README
   used to describe is gone. `R1a`/`R1b` are removed; a diode-connected
   `Q3` (`Nx=1`) sits at `Q1`'s emitter-current density, fed from `VDD`
   through `R3a` (2.45 kΩ), and couples to `b1` through `R3b` (330 Ω), with
   the reference island RF-grounded by `Cbref`. Measured over the same
   45-cell PVT grid issue #18's campaign uses
   ([`../sim/lna-bias-pvt/`](../sim/lna-bias-pvt/README.md), the record
   whose `## DUT` sha256 matches this netlist): `I_C1` spans 2.26..4.08 mA (the divider's
   evidence recorded 0.025..14.7 mA) and `P_dc` spans 4.36..9.41 mW —
   inside DR-0001's `I_C1 <= 4.5 mA` bias-network mandate and the
   `P_dc < 10 mW` Power row (both ratified by DR-0002, whose Power-row
   binding conditions name this very issue as the verification gate) at
   **every** cell, with a supply-ramp startup/latch
   check at the extreme corners. Two things this README states rather than
   lets a reader discover late:
   - **The nominal lands at 3.06 mA, deliberately below DR-1's 4.0 mA
     table entry.** The mirror family's residual PVT envelope (the
     reference feed tracks `VDD - V_BE3`, whose headroom swings
     ~0.95..1.23 across the corner box) times a 4.0 mA nominal lands the
     worst cell at ~5.2 mA / ~10.7 mW — outside both bars above; no
     flatter reference family fits this schematic's `npn13G2` + ideal
     R/C/L vocabulary and the 1.62 V / -40 °C headroom wall (a
     bandgap-class reference needs a PMOS mirror loop — the OSDI
     toolchain this repo deliberately does not ship, see
     [`../sim/pdk.json`](../sim/pdk.json) — or more stacked-`V_BE`
     headroom than the rail leaves). The flat-reference design space is
     tracked in issue #33; no spec row is relaxed by this change, the
     (~24 % off nominal) trade is stated rather than papered over, and
     the rows DR-0002 left DRAFT (e.g. the IIP3 numeric target) stay
     DRAFT pending their own decision record.
   - **The RF impedance at `b1` changed.** The old divider's ~5.1 kΩ
     Thevenin is now 330 Ω into an RF-grounded reference island — a real
     change to the (unmatched) input network, whose S-parameter / gain /
     NF / stability consequences are *measured* by re-running the issue
     #18 benches against this same netlist (see
     [`../sim/lna-characterization/`](../sim/lna-characterization/README.md)),
     not estimated here. The matching-network work (issue #27) inherits
     whatever those benches report.

## Running xschem / regenerating the netlist

```bash
export PDK_ROOT=/path/to/ihp-open-pdk   # parent dir containing ihp-sg13g2/
export PDK=ihp-sg13g2
cd design && xschem --rcfile ./xschemrc lna.sch   # interactive
```

To regenerate the committed netlist headlessly (no X server needed) — the
**one documented command** this issue's acceptance criteria names:

```bash
export PDK_ROOT=/path/to/ihp-open-pdk
export PDK=ihp-sg13g2
cd design
xschem -n -x -q -r --rcfile ./xschemrc -o ./netlist ./lna.sch
```

Same fleet convention `sg13g2-opamp/design/README.md` and
`sg13g2-bandgap/design/README.md` use (`xschem -n -x -q -r`: netlist,
headless X, quiet, regenerate-existing). The netlist lands in
`design/netlist/lna.spice` and is committed (reviewable in git). Re-run
this command any time `lna.sch` changes — a stale committed netlist is a
review-blocking discrepancy, not a cosmetic one, per this repo's
"regenerated on design change" evidence discipline.

**A resolvable SG13G2 PDK install is required** (`PDK_ROOT`/`PDK` pointing
at an `ihp-sg13g2/` open_pdks-shaped directory — see `CLAUDE.md`;
klayout-tools' own `scripts/fetch-ihp-sg13g2.sh` fetches a pinned
IHP-Open-PDK release into that shape; `sim/pdk.json` records the pinned
release this repo's evidence targets). This repo does not vendor the PDK
itself.

## What has been verified in this environment (issues #17, #26)

- **Netlisting**: `lna.sch` was netlisted headlessly with a real, fetched
  SG13G2 PDK install (`xschem -n -x -q -r`, command above) with **zero
  errors or warnings**, and the resulting `design/netlist/lna.spice`
  (committed) was checked device-by-device against the schematic's own
  header pin mapping — e.g. `XQ1 casc b1 e1 vss npn13G2 Nx=8`, `XQ2 outn
  vb2 casc vss npn13G2 Nx=8`, and since issue #26 the mirror reference
  `XQ3 bref bref vss vss npn13G2 Nx=1` plus `R3a`/`R3b`/`Cbref` —
  confirming the schematic is syntactically valid and wired exactly as
  documented, using only `npn13G2` (all active devices) and generic ideal
  `R`/`C`/`L` primitives for the passive network (only the inductors
  carry the explicit idealization caveat above — every active device is
  the PDK's real `npn13g2` model).
- **Symbol resolution**: `lna.sym` was independently verified to resolve
  and hierarchically expand to the identical `lna.sch` netlist when
  instantiated from a throwaway wrapper schematic (`Xx1 vdd vss rfin rfout
  lna` expanded to the full device list above) — confirming a future
  testbench can instantiate `lna.sym` directly rather than only
  `.include`-ing the flat netlist.
- **DC operating-point sanity check** (re-run after the issue #26 bias
  change): `design/netlist/lna.spice`, `Vdd=1.80V`, ideal 50 Ω terminations
  on `rfin`/`rfout`, `cornerHBT.lib`'s `hbt_typ` section, 27 °C — ngspice
  `op` converged with **no errors**: `I_C1=3.056 mA`, `I_C2=3.052 mA`,
  `V_CE1=0.814 V`, `V_CE2=0.986 V` (the issue #26 sizing — see honesty
  caveat 2 — lands deliberately below DR-1's 4.0 mA plan table to hold the
  hard corner bars). **This is not a performance result** — see "What
  these design issues do NOT do" above; the 45-cell PVT evidence lives in
  `sim/lna-bias-pvt/records/`.
