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

## What's here (issue #17)

- **`lna.sch`** — a cascode LNA: `Q1` (common-emitter input device) stacked
  under `Q2` (common-base cascode device), both `sg13g2_pr/npn13G2`
  (native VBIC, `Nx=8`), with `Q1`'s emitter inductively degenerated (`Le`)
  and `Q2`'s collector inductively loaded (`Lc`). `Q2`'s base bias (`vb2`)
  is an 11:1 resistive divider off `VDD`, RF-bypassed — DR-1's own
  `V_B2 = (11/12)*VDD` requirement, implemented as a resistor *ratio* (not
  an absolute value) exactly as the record specifies. Full node-by-node
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

## What this issue does NOT do

Per `CLAUDE.md`'s evidence discipline ("no claim without a testbench") and
this issue's own explicit scope: **no S-parameter, gain, NF, k-factor
(stability), or IIP3 claim is made by this schematic, its netlist, or this
README.** Those require the PVT-corner testbenches issue #18 will add under
`sim/`. The only simulation evidence cited below is a single DC operating-
point sanity check (typ corner, 27 °C, nominal `VDD`) confirming the
schematic converges and lands near DR-1's own nominal bias numbers — not a
performance result.

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
2. **`Q1`'s base bias network (`R1a`/`R1b`) is a first-order, single-corner
   placeholder**, not a finished bias generator. DR-1 specifies `Q2`'s base
   bias ratio explicitly but treats `Q1`'s `I_C` as "set by [a] bias current
   source" in the abstract, without naming a circuit. The divider here was
   sized by directly simulating this netlist (ngspice op point, `hbt_typ`
   section, 27 °C) until `I_C1` landed at DR-1's 4.0 mA nominal point — it
   is **not** validated over PVT and is **not** claimed to hold
   `I_C1 <= 4.5 mA` across corners (DR-1's own bias-network requirement). A
   more robust bias generator (e.g. a diode-connected `npn13G2`
   current-mirror reference, less `V_BE`-spread-sensitive than a raw
   divider) is flagged here as follow-up design work, not resolved by this
   issue.

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

## What has been verified in this environment (issue #17)

- **Netlisting**: `lna.sch` was netlisted headlessly with a real, fetched
  SG13G2 PDK install (`xschem -n -x -q -r`, command above) with **zero
  errors or warnings**, and the resulting `design/netlist/lna.spice`
  (committed) was checked device-by-device against the schematic's own
  header pin mapping — e.g. `XQ1 casc b1 e1 vss npn13G2 Nx=8`, `XQ2 outn
  vb2 casc vss npn13G2 Nx=8` — confirming the schematic is syntactically
  valid and wired exactly as documented, using only `npn13G2` (both active
  devices) and generic ideal `R`/`C`/`L` primitives for the passive
  network (only the inductors carry the explicit idealization caveat
  above — every active device is the PDK's real `npn13g2` model, per this
  issue's acceptance criteria).
- **Symbol resolution**: `lna.sym` was independently verified to resolve
  and hierarchically expand to the identical `lna.sch` netlist when
  instantiated from a throwaway wrapper schematic (`Xx1 vdd vss rfin rfout
  lna` expanded to the full device list above) — confirming a future
  testbench can instantiate `lna.sym` directly rather than only
  `.include`-ing the flat netlist.
- **DC operating-point sanity check**: `design/netlist/lna.spice`,
  `Vdd=1.80V`, ideal 50 Ω terminations on `rfin`/`rfout`, `cornerHBT.lib`'s
  `hbt_typ` section, 27 °C — ngspice `op` converged with **no errors**:
  `I_C1=4.068 mA`, `I_C2=4.062 mA`, `V_CE1=0.801 V`, `V_CE2=0.999 V`.
  Compare DR-1's own nominal-supply/`typ`/27 °C table: `I_C=4.0 mA`,
  `V_CE1=0.799 V`, `V_CE2=1.001 V` — this schematic's bias network lands
  within a few mV/µA of DR-1's own cited operating point at this single
  corner. **This is not a PVT sweep and not a performance result** — see
  "What this issue does NOT do" above.
