v {xschem version=3.4.6 file_version=1.2
* lna -- cascode LNA core (issue #17), implementing EXACTLY the topology and
* supply voltage spec/decision-records/0001-bias-supply-topology.md (DR-1,
* "proposed", merged via PR #22) specifies. No independent topology choice
* is made in this schematic; every numeric value below either restates a
* DR-1 number verbatim or is cited as a first-order placeholder pending a
* future design record (never invented as a "final" number).
*
* --------------------------------------------------------------- topology
* Q1 (common-emitter input device) stacked under Q2 (common-base cascode
* device), both sg13g2_pr/npn13G2 (native VBIC, ngspice level=9), Nx=8 --
* per DR-1 "Decision": "Both devices npn13G2, Nx = 8." Substrate pin (S) of
* both devices tied to vss, matching sim/hbt-characterization's own
* testbench convention (XQ1 c b e 0 npn13G2 Nx=...).
*
*   Q1  C=casc (cascode interconnect, = Q2's E)   B=b1   E=e1   S=vss
*   Q2  C=outn (drives the output coupling cap)   B=vb2  E=casc S=vss
*
* Le  emitter degeneration inductor, Q1's e1 node to vss.
* Lc  collector load inductor, vdd to Q2's outn node.
* Cin  input DC-block / AC-couple, rfin (50 Ohm port, per
*      spec/target-spec.md "Port convention") to b1.
* Cout output DC-block / AC-couple, outn to rfout (50 Ohm port).
* Cvdd supply bypass, vdd to vss (assumes clean external VDD decoupling
*      is also present off-chip; this is not a substitute for that).
*
* ------------------------------------------------- idealized inductors (!)
* Le and Lc are the generic xschem `ind` primitive (a bare SPICE L device),
* NOT an instance of sg13g2_pr/inductor.sym. This is deliberate, not an
* oversight: issue #5 (closed) confirmed, and
* 2AMLogic/klayout-tools#1519 tracks upstream, that SG13G2's open-source PDK
* ships NO simulatable SPICE/EM model for any on-chip inductor geometry --
* sg13g2_pr/inductor.sym's own `format=` string has no backing `.subckt`,
* it is LVS/layout-pcell-only (IHP-Open-PDK#1101). Using that PDK symbol
* here would net-list to an unresolved device and silently look
* PDK-accurate when it is not. Le=1nH and Lc=5nH below are therefore
* explicitly-labeled idealized/lumped placeholder values -- plausible
* orders of magnitude for 2.4 GHz inductive source/load degeneration, NOT
* a matching-network design result. DR-1's own breakdown-voltage budget
* already accounts for this: both inductors' DC series resistance is taken
* as 0 Ohm (DR-1 "DC network equations", the conservative direction for
* breakdown), so nothing here contradicts that record. A real value can
* only be committed once #5's tracked upstream gap closes (self-run
* openEMS/FastHenry extraction, or a future PDK release) or this repo picks
* a documented extraction methodology of its own -- neither has happened
* yet, so DO NOT read Le/Lc's values below as a verified matching result.
*
* ------------------------------------------------------- bias generation
* Q2's base bias (vb2) implements DR-1's ratio requirement exactly:
* "V_B2 = alpha*VDD, alpha = 11/12 = 0.9167 (an 11:1 resistive divider off
* VDD, RF-bypassed), NOT an absolute reference." R2b:R2a = 11:1
* (R2a=1k top/VDD side, R2b=11k bottom/vss side) gives
* V_B2 = VDD * R2b/(R2a+R2b) = (11/12)*VDD exactly, independent of the
* absolute resistor values chosen (matching-only requirement, not an
* absolute-value one) -- Cbyp2 RF-bypasses vb2 to vss per DR-1.
*
* Q1's base bias (b1) is NOT specified by DR-1 (which treats Q1's I_C as
* "set by [a] bias current source" in the abstract, without naming a
* circuit). R1a/R1b below are a first-order placeholder divider whose
* value was found by directly simulating this netlist (ngspice op point,
* hbt_typ section, 27C, VDD=1.80V, R1b=10k fixed, R1a swept) until the
* simulated I_C1 landed at DR-1's I_C=4.0mA nominal point -- R1a=10.6k
* gives I_C1 ~= 4.07mA, V_B1 ~= 0.845V at that corner. This is a SIMULATED
* divider value (unlike the rest of this header's V_BE1 discussion, which
* was superseded by this direct simulation once it was available), but it
* is still only a single-corner (typ/27C) placeholder: it is NOT claimed
* to hold I_C1 <= 4.5mA over PVT (DR-1's own bias-network requirement)
* since a simple two-resistor divider is beta- and temperature-sensitive,
* and DR-1's own cited V_BE(T,corner) spread (0.7539-0.9152V) implies this
* divider's current will move well outside the 4.5mA ceiling at some
* corners without a PVT sweep this issue does not commit. A more robust
* bias generator (e.g. a diode-connected npn13G2 current mirror reference,
* less V_BE-spread-sensitive than a raw divider) is flagged as follow-up
* design work in design/README.md, not resolved here.
*
* Sanity op-point (ngspice, hbt_typ section, 27C, VDD=1.80V, ideal 50 Ohm
* terminations on rfin/rfout, ONLY this netlist -- not a claimed LNA result,
* just confirmation the schematic converges and lands near DR-1's nominal
* operating point): I_C1=4.068mA, I_C2=4.062mA, V_CE1=0.801V, V_CE2=0.999V
* -- compare DR-1's own nominal-supply/typ/27C table: I_C=4.0mA,
* V_CE1=0.799V, V_CE2=1.001V. This is a single-point convergence check
* reproducible from design/netlist/lna.spice plus a Vdd/Vss/50 Ohm-terminated
* testbench and cornerHBT.lib's hbt_typ section; it is NOT a PVT sweep and
* NOT an S-parameter/NF/gain/IIP3 result (issue #18's scope).
*
* ---------------------------------------------------------------- pins
* vdd, vss  -- DR-1: "a single 1.8 V rail, nominal" (+-10% supply corner
*              set is spec/target-spec.md's, unchanged by this schematic).
* rfin, rfout -- 50 Ohm-referenced RF ports, per spec/target-spec.md
*              "Port convention". No S-parameter, gain, NF, k-factor, or
*              IIP3 claim is made by this schematic or its netlist -- that
*              is issue #18's scope, against benches not yet committed.
*
* This schematic and its derived netlist (design/netlist/lna.spice) are a
* topology/device-selection commit only, per CLAUDE.md's evidence
* discipline ("no claim without a testbench"): nothing here is simulated
* LNA performance.
}
G {}
K {}
V {}
S {}
E {}

* --- Q2: cascode (common-base) device ---
C {sg13g2_pr/npn13G2.sym} 0 200 0 0 {name=Q2 model=npn13G2 spiceprefix=X Nx=8}
N 20 170 20 140 {}
C {lab_pin.sym} 20 140 0 0 {name=l1 lab=outn}
N -20 200 -60 200 {}
C {lab_pin.sym} -60 200 0 0 {name=l2 lab=vb2}
N 20 230 20 260 {}
C {lab_pin.sym} 20 260 0 0 {name=l3 lab=casc}
N 20 200 60 200 {}
C {lab_pin.sym} 60 200 0 0 {name=l4 lab=vss}

* --- Q1: common-emitter input device ---
C {sg13g2_pr/npn13G2.sym} 0 600 0 0 {name=Q1 model=npn13G2 spiceprefix=X Nx=8}
N 20 570 20 540 {}
C {lab_pin.sym} 20 540 0 0 {name=l5 lab=casc}
N -20 600 -60 600 {}
C {lab_pin.sym} -60 600 0 0 {name=l6 lab=b1}
N 20 630 20 660 {}
C {lab_pin.sym} 20 660 0 0 {name=l7 lab=e1}
N 20 600 60 600 {}
C {lab_pin.sym} 60 600 0 0 {name=l8 lab=vss}

* --- Le: emitter degeneration inductor (e1 -> vss), IDEALIZED, see header ---
C {ind.sym} 20 780 0 0 {name=Le value=1n m=1}
N 20 750 20 700 {}
C {lab_pin.sym} 20 700 0 0 {name=l9 lab=e1}
N 20 810 20 860 {}
C {lab_pin.sym} 20 860 0 0 {name=l10 lab=vss}

* --- Lc: collector load inductor (vdd -> outn), IDEALIZED, see header ---
C {ind.sym} 20 -160 0 0 {name=Lc value=5n m=1}
N 20 -190 20 -240 {}
C {lab_pin.sym} 20 -240 0 0 {name=l11 lab=vdd}
N 20 -130 20 -80 {}
C {lab_pin.sym} 20 -80 0 0 {name=l12 lab=outn}

* --- Cin: input DC-block / AC-couple (rfin -> b1) ---
C {capa.sym} -500 600 0 0 {name=Cin value=100p m=1}
N -500 570 -500 520 {}
C {lab_pin.sym} -500 520 0 0 {name=l13 lab=rfin}
N -500 630 -500 680 {}
C {lab_pin.sym} -500 680 0 0 {name=l14 lab=b1}

* --- Cout: output DC-block / AC-couple (outn -> rfout) ---
C {capa.sym} 500 -100 0 0 {name=Cout value=100p m=1}
N 500 -130 500 -180 {}
C {lab_pin.sym} 500 -180 0 0 {name=l15 lab=outn}
N 500 -70 500 -20 {}
C {lab_pin.sym} 500 -20 0 0 {name=l16 lab=rfout}

* --- Cbyp2: RF-bypass Q2's cascode base per DR-1 ("RF-bypassed") ---
C {capa.sym} 420 -40 0 0 {name=Cbyp2 value=100p m=1}
N 420 -70 420 -120 {}
C {lab_pin.sym} 420 -120 0 0 {name=l17 lab=vb2}
N 420 -10 420 40 {}
C {lab_pin.sym} 420 40 0 0 {name=l18 lab=vss}

* --- Cvdd: supply bypass (vdd -> vss) ---
C {capa.sym} 620 600 0 0 {name=Cvdd value=100p m=1}
N 620 570 620 520 {}
C {lab_pin.sym} 620 520 0 0 {name=l19 lab=vdd}
N 620 630 620 680 {}
C {lab_pin.sym} 620 680 0 0 {name=l20 lab=vss}

* --- R2a/R2b: Q2 base bias divider, 11:1 ratio off VDD per DR-1 ---
C {res.sym} 300 -160 0 0 {name=R2a value=1k m=1}
N 300 -190 300 -240 {}
C {lab_pin.sym} 300 -240 0 0 {name=l21 lab=vdd}
N 300 -130 300 -80 {}
C {lab_pin.sym} 300 -80 0 0 {name=l22 lab=vb2}

C {res.sym} 300 60 0 0 {name=R2b value=11k m=1}
N 300 30 300 -20 {}
C {lab_pin.sym} 300 -20 0 0 {name=l23 lab=vb2}
N 300 90 300 140 {}
C {lab_pin.sym} 300 140 0 0 {name=l24 lab=vss}

* --- R1a/R1b: Q1 base bias divider, first-order placeholder, see header ---
C {res.sym} -300 340 0 0 {name=R1a value=10.6k m=1}
N -300 310 -300 260 {}
C {lab_pin.sym} -300 260 0 0 {name=l25 lab=vdd}
N -300 370 -300 420 {}
C {lab_pin.sym} -300 420 0 0 {name=l26 lab=b1}

C {res.sym} -300 660 0 0 {name=R1b value=10k m=1}
N -300 630 -300 580 {}
C {lab_pin.sym} -300 580 0 0 {name=l27 lab=b1}
N -300 690 -300 740 {}
C {lab_pin.sym} -300 740 0 0 {name=l28 lab=vss}

* --- top-level pins ---
C {iopin.sym} -700 -400 0 0 {name=p1 lab=vdd}
C {iopin.sym} -700 1000 0 0 {name=p2 lab=vss}
C {iopin.sym} -700 600 0 0 {name=p3 lab=rfin}
C {iopin.sym} 900 -100 0 0 {name=p4 lab=rfout}
