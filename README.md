# sg13g2-lna

A SiGe HBT low-noise amplifier on IHP SG13G2 on
[IHP SG13G2](https://github.com/IHP-GmbH/IHP-Open-PDK), IHP's open-source 130 nm SiGe BiCMOS PDK — designed by AI agents driving
[klayout-tools](https://github.com/2AMLogic/klayout-tools) and the
open-source xschem + ngspice flow.

**Status: core schematic and simulation campaigns committed.** The cascode
core lives in [`design/`](design/), with characterization benches and records
under [`sim/`](sim/). Input/output matching remains open in issue #27. The
block's layout is still pending: [`layout/`](layout/) holds only a partial
bring-up of the cascode core and the DR-0003 bias island, whose DRC and LVS
are not clean (issue #63). The committed [`T1 report`](signoff/t1-report.json)
currently records zero T1 items met; these artifacts do not establish signoff.

**Built agent-native.** Every specification, decision record, testbench, and
line of documentation here is produced by AI agents working from a ratified
spec and an append-only evidence trail — not human-authored work that agents
merely assisted with. Verification is the product: every claim traces to a
recorded result under PVT corners. Where the agents hit friction with the
open-source tooling — most often
[klayout-tools](https://github.com/2AMLogic/klayout-tools) — that friction is
filed as a public issue against the tool itself, so the fix benefits everyone
using this PDK, not just this repo.

## Why this block, on this PDK

A low-noise amplifier is the other half of the RF flank (with sg13g2-vco):
small-signal, noise-figure-driven, and impossible to fake with a topology
port from the CMOS canaries. SG13G2's HBTs are the reason to build it here —
sub-dB noise figures at low GHz are textbook SiGe territory, and no open-PDK
open-tool LNA with a committed, reproducible NF evidence chain is publicly
available. That gap is the repo's reason to exist.

The honest centerpiece is **noise figure and S-parameters with open tools**.
ngspice's `.sp` S-parameter analysis and noise analysis carry assumptions
(port definitions, source impedance) that must be stated with every number.
Inductive-degeneration matching leans on the same PDK passive models the VCO
canary characterizes — coordinate through klayout-tools issues, not by
copying numbers across repos without their derivations.

*Consumers / related:* `sg13g2-sat-rx` — a Ka-band LNA on the same PDK that
cites this repo as prior art; a different block, not a port of this one.

## Target specification

The detailed table — band, gain, noise figure, input/output match
(S11/S22), stability, IIP3, and supply/power, each row source-cited and the
50 Ω port convention stated explicitly — lives in
[`spec/target-spec.md`](spec/target-spec.md). This section stays
deliberately thin: rows are ratified per
[`spec/decision-records/0002-target-spec-first-ratification.md`](spec/decision-records/0002-target-spec-first-ratification.md)
(issue #19; the IIP3 numeric target and the former stretch columns are
explicitly unratified), and rows get numbers only from
committed benches. See [`spec/README.md`](spec/README.md) for the full
spec-directory index, including the porting plan and decision-record
process.

## Reproducing the results

This section is an index. It holds no numbers. Every result lives in an
append-only record under `sim/<experiment>/records/`, and the bench that
produced it is defined in that experiment's own README. Cite the record,
not this page. [`sim/README.md`](sim/README.md) is the authoritative
convention for the tree: directory layout, `<record-id>` naming, the
append-only rule and the corner-label mapping.

### Toolchain prerequisites

| Tool | Pin | Where the pin lives | Needed for |
|---|---|---|---|
| IHP-Open-PDK | tag `v0.3.0`, variant `ihp-sg13g2` | [`sim/pdk.json`](sim/pdk.json) | every ngspice bench. Fetch with klayout-tools' `scripts/fetch-ihp-sg13g2.sh`, then point `PDK_ROOT` at the directory that contains `ihp-sg13g2/`. [`sim/env.sh`](sim/env.sh) resolves `PDK_ROOT`/`PDK` from the environment first, then from the usual open_pdks prefixes. |
| ngspice | 46 or newer | `sim/pdk.json` (`ngspice_actually_used`), [`sim/lna-characterization/README.md`](sim/lna-characterization/README.md) §"Regenerating" | every bench. Each record's `## PDK` field states the exact `ngspice -v` it ran with. For the benches that use the OSDI models below (`biasref-topology`, `lna-bias-pvt`, `lna-characterization`, `lna-core-envelope`), older builds cannot load those binaries: ngspice-42 fails with `psp103.osdi couldn't be loaded!`. `hbt-characterization` and `breakdown-extraction` use only the native VBIC `npn13G2` and load no OSDI. |
| OSDI device models (`psp103`, `psp103_nqs`, `r3_cmc`, `mosvar`) | compiled from the PDK's own Verilog-A with OpenVAF-Reloaded `v24.0.1mob`, checksum-pinned | [`sim/tools/build-osdi.sh`](sim/tools/build-osdi.sh), restated in `sim/pdk.json` `osdi_toolchain` | every bench that instantiates `sg13_hv_pmos`/`sg13_hv_nmos`: `biasref-topology`, `lna-bias-pvt`, `lna-characterization`, `lna-core-envelope`. Run `sim/tools/build-osdi.sh` once per PDK install, and run `sim/tools/build-osdi.sh --check` to verify. The output goes into the PDK install and is not committed here. |
| python3 (stdlib only) | none | each runner's preflight | the result parsers and derivation scripts. |
| klayout-tools (`klt`), signoff | `0.7.0` | [`.github/workflows/signoff.yml`](.github/workflows/signoff.yml), [`signoff/README.md`](signoff/README.md) | only the T1 signoff gate. The ngspice benches do not need `klt`. |
| klayout-tools (`klt`), layout evidence | `0.7.0` PyPI release, run as `uvx --isolated --from klayout-tools==0.7.0 klt` | [`layout/run_flow.sh`](layout/run_flow.sh) (`KLT_RELEASE`), [`layout/README.md`](layout/README.md) | the `klt drc`/`extract`/`lvs` reports under `layout/lna_core/`. Layout generation also needs the pip `klayout` package (`0.30.12` was used) and the two PyCell shims from `layout/tools/fetch-pcell-deps.sh`. |
| klayout-tools (`klt`), inductor-variant campaign | floor `>= 0.7.0`, recorded in `sim/pdk.json` `klt_variant_campaign.min_version` (the single source; `run_lna_variant.sh` reads it and fails fast below it). It needs a `klt` with `expr` measurements and `options.osdi_preload` / `options.stage_model_inputs`, which `0.6.0` lacks (all three first appear in the klayout-tools `0.7.0` changelog). Developed with client `klt 0.7.0`. This is a floor, not the signoff pin. | [`sim/lna-characterization/README.md`](sim/lna-characterization/README.md) §"Status of the 45-cell run" and §"Nominal-cell probe" | the `klt sim` inductor-variant campaign (`sim/lna-characterization/run_lna_variant.sh`). The batch path also needs a fleet runner image with the same features. The runner image recorded in that section (`klt 0.5.0`) lacks them, which is why the 45-cell run has not been executed. |

xschem is not needed to rerun anything. The circuit-level benches consume
the committed netlist [`design/netlist/lna.spice`](design/netlist/lna.spice)
directly.

### Cold start: the smallest end-to-end check

This is one nominal PVT cell (`typ`, 27 °C, 1.80 V) of the
`lna-characterization` bench. It runs one `sp`/`.noise`/stability deck and
two IIP3 drive levels, so it is fine on a laptop.

```bash
git clone https://github.com/2AMLogic/sg13g2-lna.git && cd sg13g2-lna
export PDK_ROOT=/path/to/pdk-root   # parent dir containing ihp-sg13g2/ (IHP-Open-PDK v0.3.0)
export PDK=ihp-sg13g2
sim/tools/build-osdi.sh             # once per PDK install
sim/tools/build-osdi.sh --check     # OSDI models present and loadable
LNA_SWEEP_SMOKE=1 LNA_SWEEP_JOBS=1 sim/lna-characterization/run_lna_sweep.sh
```

The run mints a new `<record-id>` under `sim/lna-characterization/`
(`records/`, `corners/`, `netlist-snapshots/`). Compare its nominal-cell
row with the same row of the current record's `-summary.csv` (see the
table below). A smoke record is a plumbing check, not a PVT campaign, so do
not commit it as evidence. Every runner fails its preflight with exit 3 and
a named message when the PDK, ngspice, `cornerHBT.lib` or a required
`.osdi` model is missing.

Some checks need no PDK and no ngspice. They re-derive committed
artefacts from committed raw data, and CI runs the first and last of them:

```bash
python3 -I -m unittest discover -s sim/lna-characterization/tests -v   # reduction-code unit tests
sim/lna-characterization/parse_lna_sweep.py \
  --corners-dir sim/lna-characterization/corners/<record-id> \
  --sparam-csv /tmp/sparam.csv --iip3-csv /tmp/iip3.csv --summary-csv /tmp/summary.csv
diff /tmp/summary.csv sim/lna-characterization/records/<record-id>-summary.csv
sim/lna-core-envelope/derive_committed_record_envelope.py --out /tmp/envelope.csv
diff /tmp/envelope.csv sim/lna-core-envelope/records/20260926-122301-088c734-derived-envelope.csv
sim/models/check_sources.sh            # vendored inductor model still matches its recorded sha256
.github/scripts/check-signoff.sh       # T1 verdict of record is current (needs klt 0.7.0)
```

The shell runners and checks are linted in CI by the `shell-lint` job
([`signoff.yml`](.github/workflows/signoff.yml)) with ShellCheck **0.10.0**
(official release tarball, sha256-verified in the workflow). To reproduce
it locally, install that exact version (for example from the
[koalaman/shellcheck v0.10.0 release](https://github.com/koalaman/shellcheck/releases/tag/v0.10.0)
into a scratch directory, or `uvx --from shellcheck-py==0.10.0.1 shellcheck`),
confirm `shellcheck --version` reports `0.10.0`, then run from the repo root:

```bash
mapfile -d '' -t files < <(
  {
    git ls-files -z -- 'sim/*.sh' 'layout/*.sh' '.github/scripts/*.sh'
    git ls-files -z -- '.github/scripts/*' | while IFS= read -r -d '' f; do
      case "${f##*/}" in *.*) continue ;; esac   # extensionless only
      head -n 1 "$f" | grep -Eq '^#![[:space:]]*(/usr/bin/env[[:space:]]+)?(/[^[:space:]]*/)?bash([[:space:]]|$)' \
        && printf '%s\0' "$f"
    done
  } | sort -z -u
)
[ "${#files[@]}" -gt 0 ] || { echo "empty discovery" >&2; exit 1; }
shellcheck --shell=bash --severity=warning "${files[@]}"   # expect exit 0, 23 files today
```

Discovery covers tracked files only, so `.loom/`, `.claude/`, `.agents/`,
the root `loom.sh`, evidence and the extensionless Python checks are out of
scope. `--shell=bash` makes the source-only `sim/env.sh` lint as Bash.
`-x` is deliberately not used, so no host-dependent `source` paths are
followed.

Full PVT grids are larger. `run_lna_sweep.sh` alone is 138 ngspice
invocations, and `lna-core-envelope` is 675 decks. Each runner states its
size and its concurrency knob (`*_JOBS`) in its own README. Run full grids
on a machine you control. On the shared Loom dispatch workers, multi-corner
grids go to the batch fleet as `klt sim` requests rather than being
launched by hand. `run_lna_variant.sh` is the bench already written that
way.

### Campaign index and the record of record

Each experiment's README carries its regeneration command, its bench
definitions and its method limits. "Current" below means the record to
cite today. Historical records stay committed under the append-only rule
and are the only valid source for statements about the DUT or grid *they*
ran, but they must not be quoted as the present state of the design.

| Experiment | Entry point | OSDI | Current record | Historical / other |
|---|---|---|---|---|
| [`hbt-characterization/`](sim/hbt-characterization/README.md): `npn13G2` fT/NF/gain device sweep | `run_hbt_sweep.sh` | no | `20260918-203652-4293920` (full `Nx ∈ {1,8}` grid), read together with the **correction record** `20260921-124900-d6da30a`. That correction re-references the −40 °C / 125 °C NF cells and is the citable value for them. It is generated by `rederive_nf_fixed_t0.py` with no new simulation. | `20260910-200059-7da7038`: first, narrower grid, superseded by the current record. Its off-27 °C NF cells are also corrected by `20260921-124900-d6da30a`. |
| [`breakdown-extraction/`](sim/breakdown-extraction/README.md): BVCEO/BVCER/BVCES from the model card | `run_breakdown_sweep.sh` | no | `20260918-212948-013274f` (only record) | none |
| [`biasref-topology/`](sim/biasref-topology/README.md): DR-0003 flat bias-reference design-space probes | `run_biasref_sweep.sh` | yes | `20260921-173323-2aeafef`: five phases. Phases A–C repeat Stage 1, and Phases D–E add the sized Stage-2 core that `design/` now carries. | `20260921-160018-a46ed37`: the Stage-1 (Phases A–C) record from PR #38. The experiment README and DR-0003 cite it as `20260921-154716-f718094`, but no record with that id exists in the tree. The committed Stage-1 files are the `20260921-160018-a46ed37` set (issue #70). |
| [`lna-bias-pvt/`](sim/lna-bias-pvt/README.md): DC op-point PVT sweep of the committed bias generator | `run_biasop_sweep.sh` | yes | `20260921-173552-2aeafef`: run on the current DR-0003 core. Its DUT sha256 matches today's `design/netlist/lna.spice`. | `20260921-132025-d6da30a`: run on the earlier `npn13G2` mirror-reference bias (PR #34). That DUT no longer exists. |
| [`lna-characterization/`](sim/lna-characterization/README.md): circuit-level S-params, NF, stability, IIP3 | `run_lna_sweep.sh` | yes | `20260926-122301-088c734`: DR-0003 flat-reference core, the current `main` DUT | `20260918-210908-4293920` (placeholder divider bias) and `20260921-131646-d6da30a` (mirror-reference bias). Each describes a different, superseded circuit. See that README's §"Which DUT each record describes". The issue-#56 inductor-loss variant campaign (`run_lna_variant.sh`) has no committed record yet. See §"Status of the 45-cell run". |
| [`lna-core-envelope/`](sim/lna-core-envelope/README.md): achievable (gain, NF, P_dc) envelope over DUT variants | `run_core_envelope.sh`, plus `derive_committed_record_envelope.py` (PDK-free) | yes | `20260926-180931-90b07a0` (15 variants × 45 cells) and `20260926-122301-088c734-derived-envelope.csv`. The second is a derivation from the current `lna-characterization` record, not a simulation. | none |

Two `sim/` directories are support code, not experiments, and hold no
records. [`sim/tools/`](sim/tools/) holds `build-osdi.sh`, covered
above. [`sim/models/`](sim/models/SOURCE.md) holds the vendored
EM inductor model: `SOURCE.md` gives its provenance, and
`check_sources.sh` checks its integrity.

The block-level T1 verdict is not a `sim/` record. It is the rolling
[`signoff/t1-report.json`](signoff/t1-report.json), regenerated and
drift-checked as described in [`signoff/README.md`](signoff/README.md).

## License

Apache-2.0.
