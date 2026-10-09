# Work Log

### 2026-10-09

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
