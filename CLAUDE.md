# sg13g2-lna — agent instructions

Open-source canary block: a sige hbt low-noise amplifier on ihp sg13g2,
on IHP SG13G2, IHP's open-source 130 nm SiGe BiCMOS PDK, designed and verified by AI agents.

- **PDK**: IHP SG13G2 (https://github.com/IHP-GmbH/IHP-Open-PDK). Open-source flow: xschem + ngspice for
  design/sim, klayout-tools (`klt`) for layout work.
- **This is a new block, not a port.** Start from the inductive-degeneration
  LNA literature and the PDK's HBT + passive models. No sibling repo has RF
  small-signal work to borrow.
- **NF and S-param numbers carry their bench definitions.** Port impedances,
  bias points, and the exact ngspice analysis (.sp/.noise) are committed
  beside every recorded number. A gain or NF claim without its bench is not
  a result.
- **Stability is a spec row, not an afterthought**: k-factor / stability
  circles across the band, at PVT corners, before any matching is declared
  final.
- **Linearity is measured honestly**: IIP3 via two-tone transient with the
  tone spacing and FFT parameters recorded; state the method's limits.
- **Friction protocol (the canary's job)**: every time klayout-tools is
  awkward, missing a capability, or wrong for what you need, file an issue at
  `2AMLogic/klayout-tools` describing the tool gap generically — that tracker
  is scoped to the tool, so keep design-specific detail out of it and
  describe the gap, not the design.
- **Verification is the product**: no claim without a testbench; PVT corners
  on every recorded result; `sim/` results are append-only evidence.
- Spec changes go through `spec/` with a decision record; agents do not
  relax the ratified spec to make results pass.
