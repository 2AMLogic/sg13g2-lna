# Work Log Archive — 2026-09

Sections moved byte-for-byte from [WORK_LOG.md](../WORK_LOG.md) by `loom-daemon work-docs archive`.

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
