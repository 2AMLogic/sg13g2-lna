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
 * Q1's base bias (b1) is NOT specified by DR-1 as a circuit (which treats
 * Q1's I_C as "set by [a] bias current source" in the abstract, without
 * naming a circuit). This sheet implements that source (issue #26,
 * replacing the single-corner R1a/R1b placeholder divider it carried
 * before) as an 8:1 density-matched npn13G2 current-mirror reference:
 *
 *   - Q3, a diode-connected npn13G2 with Nx=1, sits at the SAME emitter
 *     current density as Q1 (Nx=8): Q3 carries I_C1/8, so both devices
 *     sit on the same point of the same V_BE(T,corner) curve -- the Nx
 *     invariance sim/hbt-characterization verified in its "Area-scaling
 *     spot check". V_BE match, not a resistor ratio, now defines I_C1, so
 *     the exponential V_BE-vs-divider race that swung I_C1 over
 *     0.025..14.7 mA across the PVT box (issue #26's evidence) is gone:
 *     Q1 tracks Q3, and the pair's residual spread is only its feed's.
 *   - The R3a vdd->bref feed resistor is DELETED (issue #33 / DR-0003
 *     Stage 2; the DR's own consequence list required exactly this
 *     deletion). The bref island is fed by Mis, the output bank of the
 *     DR-0003 Option-A flat-reference core: the unchanged Stage-1
 *     self-biased Widlar PTAT skeleton (Mb/Qb/Rp, Ma/Qa, Rseed --
 *     supply-independent, 0.90% worst supply move, PR #38's measured
 *     evidence), the Kuijk sum branch (Mv/Rsum/Qc building
 *     V_BG = V_BE(Qc) + I_ptat*Rsum at vbg: the V_BE-anchored CTAT
 *     tone plus the Stage-1 PTAT term), and the amp-servo loop
 *     (sg13_hv_nmos pair Mnp1/Mnp2, resistor tail Rtail, PMOS diode
 *     load Mld + mirror Mlm) that holds V_BG across the bare resistor
 *     Rl through Mref, so I_ref = V_BG/Rl is flat, and Mis (12.8:1
 *     mirror of the servo branch) copies it into the island. The
 *     mirror transfer stays beta-independent across the corner box
 *     (npn13G2's beta at this density spans ~240..2500, so mirror and
 *     base-current errors stay in the low percent -- measured, in the
 *     bias-pvt records).
 *   - R3b couples the reference island (bref) to b1. The mirror diode
 *     alone would present ~65 Ohm (1/gm at ~0.4 mA) at b1 and load the RF
 *     input; instead Cbref RF-grounds the island itself and b1 looks into
 *     330 Ohm of R3b in series with that AC ground -- replacing the OLD
 *     divider's ~5.1 kOhm Thevenin with a lower, purely resistive RF
 *     path. This CHANGES the (unmatched) input network's RF behaviour;
 *     the S-param/NF consequences are measured, not asserted, by the
 *     benches in sim/lna-characterization re-run against this same
 *     netlist. The DC drop across R3b (I_B1*R3b; I_B1 spans
 *     ~1.6..16 uA over the corner box) moves I_C1 by only a few percent
 *     at every cell -- measured in sim/lna-bias-pvt's sweep.
 *   - Sizing (DR-0003 Stage-2 swap): the flat core re-lands I_C1 at
 *     DR-0001's 4.0 mA plan-table entry: record
 *     sim/lna-bias-pvt/records/20260921-173552-2aeafef measures
 *     I_C1 = 3.9403 mA at typ/27C/VDD=1.80V -- -1.49% vs the 4.0 mA
 *     entry, inside the +/-3% tolerance DR-0003's Stage-2 sizing
 *     amendment states with its own measurements. The 45-cell PVT grid
 *     (sim/lna-bias-pvt, bar columns byte-identical to issue #26's
 *     sweep) spans I_C1 3.657..4.151 mA and P_dc 7.187..9.768 mW: inside
 *     DR-1's I_C1 <= 4.5 mA bias-network mandate and
 *     spec/target-spec.md's P_dc < 10 mW row (both ratified by
 *     DR-0002, issue #32) at EVERY cell, with margins 7.75% / 2.32%.
 *     The old committed family (R3a feed) held 2.26..4.08 mA at a
 *     deliberate 3.06 mA nominal, 24% below the plan entry, because
 *     its supply-tracked envelope could not hold both bars at 4.0 mA
 *     -- the wall DR-0003 measured and closed (Option-B diode feeds
 *     refuted at every traced current, single-junction feed families
 *     formally impossible at 4.0 mA, the widescreen flat family
 *     measured: core-level island spread +0.75%/-1.02% over the whole
 *     design-space box in
 *     sim/biasref-topology/records/20260921-173323-2aeafef). Neither
 *     row is relaxed by this change, and the rows DR-0002 left DRAFT
 *     (e.g. the IIP3 numeric target) stay DRAFT pending their own
 *     decision record.
 *
 * Sanity op-point (ngspice, hbt_typ+mos_tt sections, 27C, VDD=1.80V,
 * ideal 50 Ohm terminations on rfin/rfout, ONLY this netlist -- not a
 * claimed LNA result, just confirmation the schematic converges to the
 * intended bias point): I_C1=3.940mA, I_C2=3.935mA, V_CE1=0.803V,
 * V_CE2=0.997V -- from the acceptance record
 * sim/lna-bias-pvt/records/20260921-173552-2aeafef matching this
 * netlist's sha256. This is a
 * single-point convergence check reproducible from design/netlist/lna.spice
 * plus a Vdd/Vss/50 Ohm-terminated testbench and cornerHBT.lib's hbt_typ
 * section; the 45-cell PVT evidence -- and every number in the sizing
 * bullet above -- lives in sim/lna-bias-pvt/records/, NOT here. It is NOT
 * an S-parameter/NF/gain/IIP3 result (issue #18's scope).
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

* --- Q1 bias generator (issue #26 -> issue #33 / DR-0003): flat reference ---
* The R3a vdd->bref feed resistor is GONE (deleted -- DR-0003: "the R3a
* re-size the issue named happens as a deletion inside the Stage-2 core
* swap"). The bref island is now fed by Mis, the output bank of the
* DR-0003 Option-A staged flat-reference core: the self-biased Widlar
* PTAT skeleton inherited unchanged from PR #38's Stage 1 (Mb/Qb/Rp,
* Ma/Qa, Rseed), this Stage 2's Kuijk sum branch (Mv/Rsum/Qc), and the
* amp-servo loop (Mnp1/Mnp2/Rtail, Mld/Mlm) that holds the servoed
* branch current I_ref = V_BG/Rl through Mref and mirrors it into the
* island. Full sizing rationale, measured evidence, and the stated
* nominal tolerance live in
* spec/decision-records/0003-flat-pvt-bias-reference.md and the
* sim/biasref-topology + sim/lna-bias-pvt records -- not here. b1
* still sits one R3b away from the bref island so the RF port sees a
* finite (330 Ohm) bias impedance; Cbref RF-grounds the reference
* island -- both unchanged from issue #26's design.
C {sg13g2_pr/sg13_hv_pmos.sym} -1500 200 0 0 {name=Mb model=sg13_hv_pmos w=10u l=1u ng=1 m=1}
N -1480 170 -1460 150 {}
C {lab_pin.sym} -1460 150 0 0 {name=l100 lab=vdd}
N -1480 200 -1460 200 {}
C {lab_pin.sym} -1460 200 0 0 {name=l101 lab=vdd}
N -1520 200 -1540 200 {}
C {lab_pin.sym} -1540 200 0 0 {name=l102 lab=nc_b}
N -1480 230 -1460 250 {}
C {lab_pin.sym} -1460 250 0 0 {name=l103 lab=nc_b}
C {sg13g2_pr/npn13G2.sym} -1500 600 0 0 {name=Qb model=npn13G2 spiceprefix=X Nx=8}
N -1480 570 -1460 550 {}
C {lab_pin.sym} -1460 550 0 0 {name=l104 lab=nc_b}
N -1520 600 -1540 600 {}
C {lab_pin.sym} -1540 600 0 0 {name=l105 lab=nc_a}
N -1480 630 -1460 650 {}
C {lab_pin.sym} -1460 650 0 0 {name=l106 lab=nc_e}
N -1480 600 -1460 600 {}
C {lab_pin.sym} -1460 600 0 0 {name=l107 lab=vss}
C {res.sym} -1500 880 0 0 {name=Rp value=3.4k m=1}
N -1500 850 -1500 820 {}
C {lab_pin.sym} -1500 820 0 0 {name=l108 lab=nc_e}
N -1500 910 -1500 950 {}
C {lab_pin.sym} -1500 950 0 0 {name=l109 lab=vss}
C {sg13g2_pr/sg13_hv_pmos.sym} -1320 200 0 0 {name=Ma model=sg13_hv_pmos w=10u l=1u ng=1 m=1}
N -1300 170 -1280 150 {}
C {lab_pin.sym} -1280 150 0 0 {name=l110 lab=vdd}
N -1300 200 -1280 200 {}
C {lab_pin.sym} -1280 200 0 0 {name=l111 lab=vdd}
N -1340 200 -1360 200 {}
C {lab_pin.sym} -1360 200 0 0 {name=l112 lab=nc_b}
N -1300 230 -1280 250 {}
C {lab_pin.sym} -1280 250 0 0 {name=l113 lab=nc_a}
C {sg13g2_pr/npn13G2.sym} -1320 600 0 0 {name=Qa model=npn13G2 spiceprefix=X Nx=1}
N -1300 570 -1280 550 {}
C {lab_pin.sym} -1280 550 0 0 {name=l114 lab=nc_a}
N -1340 600 -1360 600 {}
C {lab_pin.sym} -1360 600 0 0 {name=l115 lab=nc_a}
N -1300 630 -1280 650 {}
C {lab_pin.sym} -1280 650 0 0 {name=l116 lab=vss}
N -1300 600 -1280 600 {}
C {lab_pin.sym} -1280 600 0 0 {name=l117 lab=vss}
C {res.sym} -1140 -80 0 0 {name=Rseed value=10meg m=1}
N -1140 -110 -1140 -150 {}
C {lab_pin.sym} -1140 -150 0 0 {name=l118 lab=vdd}
N -1140 -50 -1140 -10 {}
C {lab_pin.sym} -1140 -10 0 0 {name=l119 lab=nc_a}
C {sg13g2_pr/sg13_hv_pmos.sym} -1000 200 0 0 {name=Mv model=sg13_hv_pmos w=10u l=1u ng=1 m=1}
N -980 170 -960 150 {}
C {lab_pin.sym} -960 150 0 0 {name=l120 lab=vdd}
N -980 200 -960 200 {}
C {lab_pin.sym} -960 200 0 0 {name=l121 lab=vdd}
N -1020 200 -1040 200 {}
C {lab_pin.sym} -1040 200 0 0 {name=l122 lab=nc_b}
N -980 230 -960 250 {}
C {lab_pin.sym} -960 250 0 0 {name=l123 lab=vbg}
C {res.sym} -1000 420 0 0 {name=Rsum value=18.4k m=1}
N -1000 390 -1000 360 {}
C {lab_pin.sym} -1000 360 0 0 {name=l124 lab=vbg}
N -1000 450 -1000 490 {}
C {lab_pin.sym} -1000 490 0 0 {name=l125 lab=cb3}
C {sg13g2_pr/npn13G2.sym} -1000 700 0 0 {name=Qc model=npn13G2 spiceprefix=X Nx=1}
N -980 670 -960 650 {}
C {lab_pin.sym} -960 650 0 0 {name=l126 lab=cb3}
N -1020 700 -1040 700 {}
C {lab_pin.sym} -1040 700 0 0 {name=l127 lab=cb3}
N -980 730 -960 750 {}
C {lab_pin.sym} -960 750 0 0 {name=l128 lab=vss}
N -980 700 -960 700 {}
C {lab_pin.sym} -960 700 0 0 {name=l129 lab=vss}
C {sg13g2_pr/sg13_hv_nmos.sym} -800 300 0 0 {name=Mnp1 model=sg13_hv_nmos w=10u l=1u ng=1 m=1}
N -780 270 -760 250 {}
C {lab_pin.sym} -760 250 0 0 {name=l130 lab=gsvo}
N -820 300 -840 300 {}
C {lab_pin.sym} -840 300 0 0 {name=l131 lab=vbg}
N -780 300 -760 300 {}
C {lab_pin.sym} -760 300 0 0 {name=l132 lab=vss}
N -780 330 -760 350 {}
C {lab_pin.sym} -760 350 0 0 {name=l133 lab=es}
C {sg13g2_pr/sg13_hv_nmos.sym} -640 300 0 0 {name=Mnp2 model=sg13_hv_nmos w=10u l=1u ng=1 m=1}
N -620 270 -600 250 {}
C {lab_pin.sym} -600 250 0 0 {name=l134 lab=dn}
N -660 300 -680 300 {}
C {lab_pin.sym} -680 300 0 0 {name=l135 lab=vl}
N -620 300 -600 300 {}
C {lab_pin.sym} -600 300 0 0 {name=l136 lab=vss}
N -620 330 -600 350 {}
C {lab_pin.sym} -600 350 0 0 {name=l137 lab=es}
C {res.sym} -720 560 0 0 {name=Rtail value=9.53k m=1}
N -720 530 -720 500 {}
C {lab_pin.sym} -720 500 0 0 {name=l138 lab=es}
N -720 590 -720 630 {}
C {lab_pin.sym} -720 630 0 0 {name=l139 lab=vss}
C {sg13g2_pr/sg13_hv_pmos.sym} -480 200 0 0 {name=Mld model=sg13_hv_pmos w=10u l=1u ng=1 m=1}
N -460 170 -440 150 {}
C {lab_pin.sym} -440 150 0 0 {name=l140 lab=vdd}
N -460 200 -440 200 {}
C {lab_pin.sym} -440 200 0 0 {name=l141 lab=vdd}
N -500 200 -520 200 {}
C {lab_pin.sym} -520 200 0 0 {name=l142 lab=dn}
N -460 230 -440 250 {}
C {lab_pin.sym} -440 250 0 0 {name=l143 lab=dn}
C {sg13g2_pr/sg13_hv_pmos.sym} -320 200 0 0 {name=Mlm model=sg13_hv_pmos w=10u l=1u ng=1 m=1}
N -300 170 -280 150 {}
C {lab_pin.sym} -280 150 0 0 {name=l144 lab=vdd}
N -300 200 -280 200 {}
C {lab_pin.sym} -280 200 0 0 {name=l145 lab=vdd}
N -340 200 -360 200 {}
C {lab_pin.sym} -360 200 0 0 {name=l146 lab=dn}
N -300 230 -280 250 {}
C {lab_pin.sym} -280 250 0 0 {name=l147 lab=gsvo}
C {sg13g2_pr/sg13_hv_pmos.sym} -160 200 0 0 {name=Mref model=sg13_hv_pmos w=40u l=1u ng=1 m=1}
N -140 170 -120 150 {}
C {lab_pin.sym} -120 150 0 0 {name=l148 lab=vdd}
N -140 200 -120 200 {}
C {lab_pin.sym} -120 200 0 0 {name=l149 lab=vdd}
N -180 200 -200 200 {}
C {lab_pin.sym} -200 200 0 0 {name=l150 lab=gsvo}
N -140 230 -120 250 {}
C {lab_pin.sym} -120 250 0 0 {name=l151 lab=vl}
C {res.sym} -160 420 0 0 {name=Rl value=26k m=1}
N -160 390 -160 360 {}
C {lab_pin.sym} -160 360 0 0 {name=l152 lab=vl}
N -160 450 -160 490 {}
C {lab_pin.sym} -160 490 0 0 {name=l153 lab=vss}
C {sg13g2_pr/sg13_hv_pmos.sym} -860 -160 0 0 {name=Mis model=sg13_hv_pmos w=512u l=1u ng=1 m=1}
N -840 -190 -820 -210 {}
C {lab_pin.sym} -820 -210 0 0 {name=l154 lab=vdd}
N -840 -160 -820 -160 {}
C {lab_pin.sym} -820 -160 0 0 {name=l155 lab=vdd}
N -880 -160 -900 -160 {}
C {lab_pin.sym} -900 -160 0 0 {name=l156 lab=gsvo}
N -840 -130 -820 -110 {}
C {lab_pin.sym} -820 -110 0 0 {name=l157 lab=bref}

C {res.sym} -300 600 0 0 {name=R3b value=330 m=1}
N -300 570 -300 520 {}
C {lab_pin.sym} -300 520 0 0 {name=l27 lab=bref}
N -300 630 -300 680 {}
C {lab_pin.sym} -300 680 0 0 {name=l28 lab=b1}

C {sg13g2_pr/npn13G2.sym} -500 100 0 0 {name=Q3 model=npn13G2 spiceprefix=X Nx=1}
N -480 70 -480 40 {}
C {lab_pin.sym} -480 40 0 0 {name=l29 lab=bref}
N -520 100 -560 100 {}
C {lab_pin.sym} -560 100 0 0 {name=l30 lab=bref}
N -480 130 -480 160 {}
C {lab_pin.sym} -480 160 0 0 {name=l31 lab=vss}
N -480 100 -440 100 {}
C {lab_pin.sym} -440 100 0 0 {name=l32 lab=vss}

C {capa.sym} 420 460 0 0 {name=Cbref value=100p m=1}
N 420 430 420 380 {}
C {lab_pin.sym} 420 380 0 0 {name=l33 lab=bref}
N 420 490 420 540 {}
C {lab_pin.sym} 420 540 0 0 {name=l34 lab=vss}

* --- top-level pins ---
C {iopin.sym} -700 -400 0 0 {name=p1 lab=vdd}
C {iopin.sym} -700 1000 0 0 {name=p2 lab=vss}
C {iopin.sym} -700 600 0 0 {name=p3 lab=rfin}
C {iopin.sym} 900 -100 0 0 {name=p4 lab=rfout}
