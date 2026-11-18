# Work Log Archive — 2026-09

Sections moved byte-for-byte from [WORK_LOG.md](../WORK_LOG.md) by `loom-daemon work-docs archive`.

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
