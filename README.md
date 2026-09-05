# sg13g2-lna

A SiGe HBT low-noise amplifier on IHP SG13G2 on
[IHP SG13G2](https://github.com/IHP-GmbH/IHP-Open-PDK), IHP's open-source 130 nm SiGe BiCMOS PDK — designed by AI agents driving
[klayout-tools](https://github.com/2AMLogic/klayout-tools) and the
open-source xschem + ngspice flow.

**Status: just opened.** Nothing is designed yet. The first work is
the S-parameter and noise testbench methodology — proving what ngspice can and cannot measure before any transistor is sized.

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

## Target specification (DRAFT — engineering to ratify)

Deliberately thin until the bench methodology lands: band, gain, noise
figure, input/output match (S11/S22), IIP3, supply/power. Rows get numbers
only from committed benches; the 50 Ω port convention is stated explicitly.

## License

Apache-2.0.
