# Work Log

### 2026-10-14

- **Issue #46** (closed): README: embed the fleet burndown chart (one line)

### 2026-10-11

- **Issue #202** (closed): sim: fix tank-probe drive in the #200 requirements study and complete the run
- **Issue #207** (closed): sim: correct ideal-choke isolation attribution in the requirements reducer
- **PR #210**: sim: correct ideal-choke isolation attribution in the requirements reducer (#207)
- **Issue #208** (closed): Build/runtime failure on main: testbench inventory rejects layout/run_native_drc.py
- **PR #209**: signoff: classify layout/run_native_drc.py in the testbench inventory (#208)
- **Issue #128** (closed): sim: keep partially failed core-envelope campaigns resumable
- **PR #206**: sim: keep partially failed core-envelope campaigns resumable
- **Issue #200** (closed): sim: quantify feed-isolation and input-Q requirements after the Le study NO-GO
- **PR #205**: sim: voltage-driven tank probe and completed input-Q/feed-isolation requirements run (#200, #202)
- **Issue #185** (closed): layout: add a version-checked native PDK DRC runner and provenance checks
- **PR #204**: layout: version-checked native PDK DRC runner and provenance checks
- **PR #203**: sim: #200 requirements study -- declaration and stopped first run (probe control)
- **Issue #198** (closed): sim: jointly choose emitter degeneration and input match for the finite base feed
- **PR #199**: sim: joint Le / input-match study on the finite base feed (#198): NO-GO, noise floor binds
- **Issue #179** (closed): Auditor guard review: retain destructive reset and cleanup protection
- **Issue #174** (closed): Auditor guard review: retain unresolved-variable removal protection
- **Issue #153** (closed): Auditor guard review: retain shared stash protection
- **Issue #195** (closed): signoff: attest shipped measurement benches with an audited T1 item-9 inventory
- **PR #197**: signoff: attest shipped measurement benches with an audited T1 item-9 inventory
- **Issue #180** (closed): sim: bind manifest-backed RF aggregates to declared campaign points
- **PR #196**: sim: bind RF campaign aggregates to manifest-declared points (#180)
- **Issue #124** (closed): Auditor guard review: retain main-checkout write confinement

### 2026-10-10

- **Issue #193** (closed): sim: test a finite resonant base-bias feed against the ideal-choke noise bound
- **PR #194**: sim: finite resonant base-bias feed vs ideal-choke noise bound (#193)
- **PR #192**: sim: re-attempt #90 fleet MC campaign; still blocked by runner klt 0.5.0
- **Issue #190** (closed): sim: give matching verification decks a measured DC reference without hiding stability-margin sensitivity
- **PR #191**: sim: explicit DC reference on xout for matching verification decks, with measured sensitivity (#190)
- **Issue #187** (closed): measurements: use the derived 290 K noise floor in current reachability summaries
- **PR #189**: measurements: use derived 290 K noise floor in current reachability summaries (#187)
- **Issue #186** (closed): sim: nominal-cell matching-network feasibility study with lossy inductors (unblocks #27 design choice)
- **PR #188**: sim: nominal-cell matching-network feasibility study with lossy inductors (#186)
- **Issue #97** (closed): Auditor guard review: keep gh-api-rawfield-body-literal-at flagged
- **Issue #181** (closed): sim: derive comparable 290 K NFmin budgets and correct RF reachability prose
- **PR #184**: sim: derive comparable 290 K NFmin budgets and correct RF reachability prose
- **Issue #176** (closed): ci: verify the extracted SPICE output against the extraction report digest
- **PR #178**: ci: verify extracted SPICE output against extraction report digest
- **Issue #173** (closed): test: unit-test layout/pcell_env.py PDK resolution, PyCell digest, and generate.py grid snapping
- **PR #177**: test: unit-test pcell_env PDK resolution, digest, and _snap (#173)
- **Issue #172** (closed): test: unit-test sim/tools/reducer_common.py shared reducer helpers
- **PR #175**: test: unit-test sim/tools/reducer_common.py (#172)
- **PR #171**: sim: full-DUT DC mismatch campaign tooling; fleet run blocked by runner klt skew (#90)
- **Issue #162** (closed): test: unit-test layout/lvs_identity.py sidecar binding and malformed-sidecar handling
- **PR #169**: test: unit-test layout/lvs_identity.py sidecar binding (#162)
- **Issue #165** (closed): sim: validate core-envelope wrdata integrity before counting stability violations
- **PR #170**: sim: validate core-envelope wrdata integrity before counting stability violations
- **Issue #145** (closed): sim: replay breakdown summaries independently of the simulation runner
- **PR #168**: sim: replay breakdown summaries independently of the simulation runner (#145)
- **Issue #161** (closed): docs: refresh spec/README.md decision-records entry (directory exists, index 0001-0004)
- **PR #167**: docs: spec/README decision-records entry and index (#161)
- **Issue #155** (closed): sim: bind HBT model-validity evidence to the complete DUT device inventory
- **PR #166**: sim: bind HBT model-validity evidence to the complete DUT device inventory
- **Issue #150** (closed): sim: reject invalid RF log measurements before coverage classification
- **PR #164**: sim: reject invalid RF log measurements before coverage classification
- **Issue #160** (closed): Consolidate duplicated helpers across sim reducers
- **PR #163**: sim: consolidate duplicated reducer helpers (#160)
- **Issue #158** (closed): sim: distinguish synthetic gate verdicts from live campaign authorization
- **PR #159**: sim: distinguish synthetic gate verdicts from live campaign authorization
- **PR #157**: sim: offline campaign prep for emitter array and cascode split (#58 milestone A)
- **Issue #154** (closed): sim: audit startup settling over a physical-time waveform interval
- **PR #156**: sim: audit startup settling over a physical-time waveform interval
- **Issue #149** (closed): sim: validate and independently replay bias-reference phase reductions
- **PR #152**: sim: validate and independently replay bias-reference phase reductions (#149)
- **Issue #89** (closed): docs: disclose missing DC and RF statistical evidence for T1 item 6
- **PR #151**: docs: disclose missing DC and RF statistical evidence for T1 item 6
- **Issue #144** (closed): sim: reject malformed HBT measurement tokens before CSV publication
- **PR #148**: sim: reject malformed HBT measurement tokens before CSV publication (#144)
- **Issue #73** (closed): Install ratification/ee-key and ratification/market-key reviewer trees (product#151)
- **PR #147**: ratification: install the two-key reviewer variant (EE key + market key) (#73)
- **Issue #117** (closed): sim: validate and replay DC bias and startup reduction before accepting evidence
- **PR #146**: sim: validate and replay DC bias and startup reduction before accepting evidence
- **Issue #141** (closed): ci: generate the measurements results table and per-row verdicts from the summary CSV, with a drift gate
- **PR #143**: ci: generate results table and per-row verdicts from the summary CSV, with drift gate (#141)
- **Issue #70** (closed): docs: biasref-topology README and DR-0003 cite a Stage-1 record id (20260921-154716-f718094) that does not exist
- **PR #142**: docs: correct Stage-1 biasref record id citation (#70)
- **Issue #138** (closed): ci: verify schematic connectivity through headless xschem regeneration
- **PR #140**: ci: verify schematic connectivity through headless xschem regeneration
- **Issue #137** (closed): sim: validate cubic-region IIP3 before reporting accepted intercepts
- **PR #139**: sim: per-cell IIP3 method-validity check (#137)
- **Issue #134** (closed): sim: extend 290 K NF measurement across the in-band frequency grid
- **PR #136**: sim: extend 290 K NF measurement across the in-band frequency grid (#134)
- **Issue #133** (closed): sim: validate RF frequency grids before marking campaign points complete
- **PR #135**: sim: validate RF frequency grids before marking campaign points complete
- **Issue #130** (closed): layout: bind LVS verdicts to reference netlists and comparison requests
- **PR #132**: layout: bind LVS verdicts to reference netlists and comparison requests
- **Issue #129** (closed): docs: refresh signoff evidence status after DR-0003 re-baselining
- **PR #131**: docs(signoff): refresh evidence status after DR-0003 re-baselining
- **Issue #126** (closed): sim: guard core-envelope resume with input identity and immutable publication
- **PR #127**: sim: guard core-envelope resume with input identity and immutable publication
- **Issue #123** (closed): sim: prevent standalone NF derivations from overwriting historical evidence
- **PR #125**: sim: refuse to overwrite existing evidence in standalone NF derivations
- **Issue #118** (closed): sim: verify installed PDK identity against the release pin before recording results
- **PR #122**: sim: verify installed PDK identity against release pin in preflight
- **Issue #116** (closed): sim: record expected RF point coverage and validate complete drive pairs
- **PR #121**: sim: record expected RF point coverage and validate complete drive pairs
- **Issue #119** (closed): ci: extend layout freshness to extraction and scoped LVS report provenance
- **PR #120**: ci: extend layout freshness to extraction and scoped LVS report provenance

### 2026-10-09

- **Issue #113** (closed): sim: reserve record IDs atomically to prevent same-second evidence collisions
- **PR #115**: sim: atomic record-id reservation in sim_record_paths (#113)
- **Issue #108** (closed): ci: add a single local runner that mirrors the signoff.yml checks
- **PR #112**: ci: add a single local runner that mirrors the signoff.yml checks

### 2026-10-09

- **Issue #109** (closed): test: unit-test layout/lvs_reference.py partition and card-rewrite invariants
- **Issue #105** (closed): ci: add a shellcheck lint job for the sim runners and check scripts
- **Issue #104** (closed): test: unit-test parse_core_envelope.py against a trimmed wrdata fixture
- **PR #111**: test: unit-test layout/lvs_reference.py partition and card-rewrite invariants
- **PR #110**: ci: add pinned ShellCheck shell-lint job (#105)
- **PR #107**: test: unit-test parse_core_envelope.py against a trimmed wrdata fixture
- **Issue #101** (closed): tests: unit-test hbt-characterization/rederive_nf_fixed_t0.py (fixed-T0 NF correction) and run it in CI
- **Issue #100** (closed): signoff: bump the grader klt pin 0.6.0 → 0.7.0 to match the layout flow that mints the cited evidence
- **Issue #87** (closed): sim: validate committed-DUT variant reports and summarize ratified-row coverage
- **Issue #84** (closed): ci: enforce vendored inductor-model checksum provenance
- **Issue #94** (closed): Consolidate duplicated RF helpers in the core-envelope postprocessors
- **PR #103**: sim: unit-test rederive_nf_fixed_t0.py and run it in CI (#101)
- **PR #102**: signoff: bump grader klt pin 0.6.0 -> 0.7.0 to match the layout flow (#100)
- **PR #99**: sim: validate committed-DUT variant reports and summarize ratified-row coverage
- **PR #98**: ci: run vendored-model provenance check in signoff workflow
- **PR #96**: Consolidate duplicated RF helpers in the core-envelope postprocessors
- **Issue #64** (closed): test: unit tests and a CI job for the lna-characterization result-reduction code
- **Issue #69** (closed): docs: add a 'Reproducing the results' index to the top-level README (T1 items 9 and 10)
- **Issue #72** (closed): sim: pin and preflight the klt version floor for the inductor-variant campaign (currently prose only)
- **Issue #75** (closed): ci: mechanically check that record ids cited in docs resolve to committed sim/ evidence
- **Issue #63** (closed): layout: bring up the klt layout/DRC/LVS flow on the core + bias island (T1 items 2, 3, 4)
- **Issue #66** (closed): Dedupe PVT corner->section tables repeated across sim run scripts
- **Issue #67** (closed): ci: enforce the sim/ append-only rule mechanically (fail PRs that modify or delete committed records)
- **Issue #83** (closed): ci: replay the committed core-envelope derivation against retained RF data
- **Issue #86** (closed): ci: layout evidence freshness gate (GDS hash vs provenance, regenerated LVS reference vs committed)
- **Issue #78** (closed): Auditor: retain literal @path comment-body guard
- **Issue #88** (closed): ci: check the committed netlist's device inventory against design/lna.sch, and drop the leaked local sch_path
- **Issue #80** (closed): signoff: enforce the partial-layout scope guard before accepting met block rows
- **Issue #79** (closed): Auditor: refine unresolved-variable confinement guard for temporary LVS diagnostics
- **PR #65**: test: unit tests and CI job for lna-characterization reduction code
- **PR #71**: docs: add a 'Reproducing the results' index to the top-level README
- **PR #74**: sim: preflight klt >= 0.7.0 for the inductor-variant campaign (#72)
- **PR #76**: ci: check cited record ids resolve to sim/ evidence
- **PR #77**: layout: bring up the klt layout/DRC/LVS flow on the core + bias island (#63)
- **PR #81**: ci: enforce the sim/ append-only rule mechanically (#67)
- **PR #85**: ci: replay the committed core-envelope derivation against retained RF data
- **PR #91**: ci: layout-freshness gate for committed layout evidence
- **PR #92**: ci: netlist-freshness gate for lna.sch vs committed netlist (#88)
- **PR #93**: ci: layout-citation scope guard in the signoff drift check (#80)

### 2026-10-08

- **Issue #57** (closed): spec: correct the NF and Gain disclosure notes per decision record 0004, Option A (no ratified value changes)
- **PR #62**: spec: correct NF and Gain disclosure notes per decision record 0004, Option A

### 2026-10-08

- **PR #60**: sim: stamped EM inductor model and lossy-inductor variant bench (issue #56, partial: 45-cell run blocked on fleet klt)

### 2026-09-26

- **PR #54**: spec: DR-0004 draft — the achievable (gain, NF, P_dc) envelope on npn13G2, plus the lna-core-envelope campaign behind it
- **PR #53**: sim: move the runners' shared PDK/record/pool scaffolding into sim/env.sh
- **PR #51**: sim: re-baseline the lna-characterization PVT campaign against the DR-0003 bias core
- **Issue #52** (closed): spec/design: RATIFIED gain (>15 dB) and NF (<1.5 dB) rows are unreachable by matching alone on the DR-0003 core — available-gain basis 14.42 dB, NFmin 2.07 dB at the best of 45 cells
- **Issue #50** (closed): sim: de-duplicate the five run_*_sweep.sh runners — 22 lines identical in all five, helper trio copy-pasted 3x
- **Issue #49** (closed): sim: re-baseline the lna-characterization PVT campaign against the DR-0003 bias core — the #37-deferred RF re-characterization, never filed

### 2026-09-25

- **PR #48**: chore(signoff): bump klt pin 0.5.0 -> 0.6.0, re-vendor tiers doc
- **Issue #47** (closed): signoff: bump the klt pin 0.5.0 → 0.6.0, re-vendor the tiers doc, retire the stale release-lag narrative

### 2026-09-22

- **PR #44**: docs: align living docs with DR-0002's partial target-spec ratification
- **PR #43**: docs: state cornerHBT.lib's three real sections and add consumers note
- **Issue #45** (closed): dep-recheck-fingerprint named-dependency drops cross-repo dependency bullets (OWNER/REPO#N) — false VERDICT=clear
- **Issue #41** (closed): 2am: reuse rule 9 — cornerHBT.lib ships three HBT corners, not five — a consumer's correction that never travelled here
- **Issue #39** (closed): docs: refresh stale pre-#32 nothing-is-ratified framing in measurements/README.md, spec/porting-plan.md, sim/README.md

### 2026-09-21

- **PR #40**: feat: swap the bias island to the DR-0003 flat-reference core (4.0 mA re-land)
- **PR #38**: feat: add bias-reference DR-0003, OSDI toolchain, and probe bench
- **PR #36**: feat: add klt signoff block manifest with CI verdict-drift gate
- **PR #34**: fix: replace Q1's placeholder divider bias with an npn13G2 mirror reference
- **PR #32**: docs(spec): ratify target-spec rows via decision record 0002
- **PR #31**: docs(sim): re-reference hbt NF records to fixed T0, add erratum
- **Issue #37** (closed): bias core: land DR-0003 Stage 2 amp-servo flat-current swap (4.0 mA re-land)
- **Issue #33** (closed): design: flat PVT bias reference for Q1 — the 4.0 mA nominal / corner-bar trade issue #26 sized around
- **Issue #30** (closed): Commit a klt signoff block manifest so this block's T1 state is graded, not hand-read
- **Issue #26** (closed): design: replace Q1's placeholder resistive base-bias divider — measured I_C1 spans 25 uA..14.7 mA over PVT
- **Issue #25** (closed): sim: hbt-characterization's NF bench does not pin the source reference temperature (ngspice per-instance temp= is ignored for resistor noise)
- **Issue #19** (closed): spec: ratify spec/target-spec.md via the fleet two-key mechanism

### 2026-09-18

- **PR #29**: feat(sim): committed BVCEO/BVCER/BVCES breakdown-extraction testbench for npn13G2
- **PR #28**: sim: circuit-level S-parameter, NF, stability and IIP3 campaign against design/lna.sch
- **PR #24**: feat(sim): full Nx=8 corner grid + V_CE=0.6 V point for hbt-characterization
- **PR #23**: feat(design): add cascode LNA schematic and derived netlist
- **Issue #21** (closed): Extend hbt-characterization: full Nx=8 corner grid and V_CE=0.6 V point
- **Issue #20** (closed): Committed BVCEO / BVCER breakdown-extraction testbench for npn13G2
- **Issue #18** (closed): sim: S-parameter, NF, stability, and IIP3 testbenches against design/lna.sch
- **Issue #17** (closed): design/lna.sch: schematic and derived netlist for the ratified bias/supply topology

### 2026-09-16

- **PR #22**: docs(spec): propose a 1.8 V cascode bias/supply topology in decision record 0001
- **Issue #16** (closed): Decision record: LNA bias/supply topology (cascode vs. single-stage) and supply voltage

### 2026-09-11

- **PR #15**: chore: remove dead _sg13g2_env_self variable in sim/env.sh
- **PR #12**: chore: remove dead _sg13g2_sim_dir variable in sim/env.sh
- **PR #10**: Remove dead _sg13g2_repo_root variable in sim/env.sh
- **Issue #14** (closed): Remove dead _sg13g2_env_self variable in sim/env.sh
- **Issue #13** (closed): Remove dead _sg13g2_sim_dir variable in sim/env.sh
- **Issue #11** (closed): Remove dead _sg13g2_sim_dir variable in sim/env.sh
- **Issue #9** (closed): Remove dead _sg13g2_repo_root variable in sim/env.sh

### 2026-09-10

- **PR #8**: sim: npn13G2 noise-optimum device characterization (fT, NF@50Ω, gain vs J_C/V_CE, HBT corner grid)
- **Issue #7** (closed): sim: `npn13g2` noise-optimum device characterization (fT, NF@50 Ω, gain vs J_C and V_CE at 2.4 GHz) across the HBT corner grid — the device-level input the bias/supply-topology decision record needs
