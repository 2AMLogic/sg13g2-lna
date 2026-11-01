# sim/pre-match-dut — frozen pre-#27 DUT

`lna.pre27.spice` is byte-identical to `design/netlist/lna.spice` as of
`5bbb70c` (sha256 `23f9445b01dbec997a2247e40deb6fcaf09b4c2a4a3301c0aae2d37ad27768d1`),
i.e. the DUT **without** the #27 matching network. The matching-feasibility,
variant-campaign, bias-PVT and core-envelope tooling synthesize their own
matching networks around the bare DUT and replay committed records against it,
so they read this frozen copy instead of the live design netlist (which now
carries the network). Do not edit it; it is a historical input.
