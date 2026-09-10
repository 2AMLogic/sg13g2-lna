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
different install than what a script used.

**No OSDI compile step is needed yet.** `sim/hbt-characterization/` (the
first experiment in this tree) instantiates only `npn13G2`, a native
ngspice VBIC (level=9) bipolar model — unlike `sg13g2-bandgap`'s and
`sg13g2-opamp`'s MOS/resistor testbenches, it never loads a Verilog-A/OSDI
device, so there is no `sim/tools/build-osdi.sh` in this repo (yet). A
future experiment that instantiates a MOS or resistor device will need to
port that script from a sibling repo — see `pdk.json`'s
`device_models_used_by_this_repo_so_far` note.

## Directory / naming convention

```
sim/
  README.md            this file — the authoritative convention
  pdk.json              pinned PDK revision (see "PDK pin" above)
  env.sh                 PDK_ROOT/PDK resolution, sourced by every testbench
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
`spec/porting-plan.md` both describe `cornerHBT.lib` as shipping "the five
process corners {tt, ff, ss, fs, sf}". **Verified against the pinned PDK
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

No row of `spec/target-spec.md`'s DRAFT target table is ratified by
anything in this tree. Every experiment's `README.md` and record restate
that disclaimer locally: results here are device-characterization *input*
to a future decision record, not a conformance claim against a DRAFT
target-spec row.

## Testbenches landed so far

- **[`hbt-characterization/`](hbt-characterization/README.md)** — the
  first testbench in this tree (issue #7): `npn13G2` fT, 50 Ω-referenced
  noise figure at 2.4 GHz, and 50 Ω-terminated transducer gain at 2.4 GHz,
  swept over collector current density (via a dense base-voltage sweep)
  and `V_CE` ∈ {0.8, 1.0, 1.2, 1.4} V, across the HBT process-corner grid
  above × {−40, 27, 125} °C. Device-level input to the still-open
  bias/supply-topology decision record (`target-spec.md` "Open topology
  question") — not the decision itself, and not a claim against any
  `target-spec.md` row.
