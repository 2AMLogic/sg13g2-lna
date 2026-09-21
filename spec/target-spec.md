# Target specification

**Status: RATIFIED for the rows marked RATIFIED below**, by decision record
[0002 — first target-spec ratification](decision-records/0002-target-spec-first-ratification.md)
(issue [#19](https://github.com/2AMLogic/sg13g2-lna/issues/19); the operator's
approval of the ratification PR is the ratification act — see "The
ratification path actually used" below). **Explicitly NOT ratified by that
pass:** the IIP3 row's numeric target (kept DRAFT by an explicit
no-force-ratification decision, documented in its note), and every former
DRAFT *stretch* column (each recorded below with its rationale).

**No row was relaxed to make a result pass.** Every ratified value is the
former DRAFT target unchanged, or re-expressed with the better-conditioned
metric this topology's committed evidence demands (stability), or a
decision record's proposal made binding (supply, power). Every measured
shortfall of the as-committed design against a ratified row is disclosed in
that row's note with its root cause — the placeholder bias network
([#26](https://github.com/2AMLogic/sg13g2-lna/issues/26)), the absent
matching networks
([#27](https://github.com/2AMLogic/sg13g2-lna/issues/27)), and the
ideal-passive model limitation — the three findings the characterization
campaign itself published
([`measurements/README.md`](../measurements/README.md)).

## The ratification path actually used

The fleet's two-key mechanism
([`2AMLogic/2am#372`](https://github.com/2AMLogic/2am/issues/372)) was
re-verified **still not operational** when this issue was picked up
(2026-09-21: `2AMLogic/2am#372` is OPEN, carrying `loom:operator-only` +
`loom:epic` + `loom:operator-decision`), so the predecessor
ratification-via-PR standing policy
([`2AMLogic/2am#357`](https://github.com/2AMLogic/2am/issues/357)) is the
path actually used, exactly as issue #19's acceptance criteria direct: a
builder drafted this change on the evidence, and **the operator's approval
of the ratification PR is the ratification act**. Record
[0002](decision-records/0002-target-spec-first-ratification.md) is the
ratification record, including the per-row traceability (which testbench,
which record id, which commit each ratified row traces to). When the
two-key mechanism does land, any future *relaxation* of a row below must go
through its market-key competitiveness rule — until then, a superseding
decision record and operator approval is the only path.

## Port convention (stated explicitly, per `CLAUDE.md`) — now binding

**All S-parameters, gain, and match figures in this document are defined at
a 50 Ω reference impedance at both the input and output ports**, matching
the top-level README's own framing ("NF and S-param numbers carry their
bench definitions. Port impedances, bias points, and the exact ngspice
analysis ... are committed beside every recorded number"). Any future
testbench that departs from a 50 Ω port (e.g. an on-chip source impedance
sweep for noise-figure sensitivity) must state so explicitly beside its
result — it does not change this row's definition. The ratified noise-figure
reference temperature is **T0 = 290 K** (IEEE/Friis): the number to compare
against any datasheet or literature figure is the `nf290` column of the
committed campaign records (this also supersedes, for any future bench in
this repo, the 300.15 K reference used by the historical
`hbt-characterization` records — see
[#25](https://github.com/2AMLogic/sg13g2-lna/issues/25)).

## Where these numbers come from

Sources, cited per row below. The load-bearing source for every ratified row
is now this repo's own committed evidence (4).

1. **Classic inductive-degeneration LNA literature (topology-level, not
   device-specific).** D. K. Shaeffer and T. H. Lee, "A 1.5-V, 1.5-GHz CMOS
   Low Noise Amplifier," *IEEE JSSC*, 1997 — the standard reference for what
   an inductively-degenerated common-emitter/source LNA can achieve
   (simulated noise and power matching, achievable gain/NF/S11 ranges).
   S. P. Voinigescu et al., "A Scalable High-Frequency Noise Model for
   Bipolar Transistors with Application to Optimal Transistor Sizing for
   Low-Noise Amplifier Design," *IEEE JSSC*, 1997 — the standard SiGe-HBT
   noise-optimization reference. Both are topology/device-class references
   cited for **achievable-range** framing, not numbers to be transcribed as
   this block's targets.
2. **IHP SG13G2 process specification — read from this repo's actually
   resolved PDK checkout.** The provisional framing this section carried at
   DRAFT time ("commit `5e6d592`, read via the GitHub API … re-verify
   against the actually-resolved checkout once tooling access lands") is
   closed: every committed simulation record in this repo was generated
   against the checkout pinned in
   [`sim/pdk.json`](../sim/pdk.json) — **IHP-Open-PDK release `v0.3.0`,
   tag commit [`5cccb161`](https://github.com/IHP-GmbH/IHP-Open-PDK/commit/5cccb161f7492697cfa52eb14dc03beb00bdca9e)
   (2026-03-11)**, fetched via `klayout-tools`' `fetch-ihp-sg13g2.sh` and
   verified installed (`.fetched-version` = 0.3.0, 2026-09-10). Re-verified
   against that local install while drafting the ratification (2026-09-21):
   the load-bearing model-card statements are unchanged —
   `* Maximum collector-to-emitter voltage: 1.6`,
   `vce_max = 1.6`, validity box `ic < 0.003·Nx A`, `vbe 0.65–0.96 V`,
   `vce 0.4–2.0 V`, `−40…+125 °C`, `NX = 1–10`
   (`ihp-sg13g2/libs.tech/ngspice/models/sg13g2_hbt_mod.lib`), and
   `cornerHBT.lib` ships exactly **three** real HBT sections (`hbt_typ`,
   `hbt_bcs`, `hbt_wcs`) — see "Verification corners" below for what that
   means. Note the direction of the supersession: the `v0.3.0` release
   (March 2026) **predates** the provisional `main`-branch read (`5e6d592`,
   2026-09-01) — the actually-resolved, actually-used release is the
   authoritative citation; the later upstream `main` state is uninstalled
   drift, not the basis of record.
3. **This repo's own README thesis** — "sub-dB noise figures at low GHz are
   textbook SiGe territory" — retained strictly as the block's motivating
   aspiration. The characterization campaign has now *tested* it: the best
   measured `NFmin` is **0.600 dB** (ideal noise match), so the thesis is
   reachable **in principle** on this topology/device but remains
   **unproven for any real (finite-Q, lossy) matching network** — which is
   exactly why the NF stretch row below stays unratified.
4. **This repo's own committed evidence — the load-bearing source.**
   - [`decision-records/0001-bias-supply-topology.md`](decision-records/0001-bias-supply-topology.md)
     (issue #16, PR #22): the ratified-on-0002 cascode/1.8 V/Nx=8 bias plan
     and its breakdown-voltage budget.
   - `sim/hbt-characterization/` (issue #7, PR #8; record
     `20260910-200059-7da7038`): bare-`npn13G2` bias-space evidence — the
     device noise optimum and the NF-vs-`J_C` trade behind DR-0001's
     4.0 mA point.
   - `sim/lna-characterization/` (issue #18, PR #28, merged at `04ded14`;
     record `20260918-210908-4293920`): the circuit-level 45-cell PVT
     campaign — S-parameters, `nf290`/`NFmin`, in-band and broadband k/μ
     stability, two-tone IIP3 — against the committed DUT
     `design/netlist/lna.spice` (sha256 `79447449…389b69`), 138 ngspice
     invocations, cross-checked quantities as documented in that README.
   - `sim/breakdown-extraction/` (issue #20, PR #29, merged at `f7916e5`;
     record `20260918-212948-013274f`): BVCEO/BVCER/BVCES extraction from
     the model card's own weak-avalanche parameters across the corner ×
     temperature × Nx grid — the committed-testbench basis for the Supply
     row that DR-0001 had to do without.

## The topology question — resolved and ratified

The section this one replaces ("Open topology question this table does not
resolve") is closed:
[`decision-records/0001-bias-supply-topology.md`](decision-records/0001-bias-supply-topology.md)
proposed the answer (cascode, single 1.8 V rail, `npn13G2` at `Nx = 8`,
`I_C` = 4.0 mA nominal with the bias network mandated to hold
`I_C ≤ 4.5 mA` over all corners) and record 0002 ratifies it together with
this table's Supply and Power rows. DR-0001's own status field is updated by
0002 accordingly. The one DR-0001 follow-up that mattered to its budget —
"no committed breakdown testbench exists in this repo" — was closed in the
interim by issue #20's extraction bench (PR #29): at the operating-point
criterion (500 µA/finger = DR-0001's nominal `I_C`), extracted BVCEO is
**≥ 1.6126 V across all 60 cells** of the corner × temperature × Nx ×
self-heating grid, against DR-0001's worst-case device stress of 1.116 V —
the breakdown margin is simulated evidence now, not just a process-spec
number.

## Ratified target table

Every row below states what **is** binding and carries the note
**Status vs. the committed evidence** — the as-committed design's measured
standing against the row, with the failing-spec cases presented explicitly
rather than absorbed. "Src" cites the numbered sources above; the full
per-row trace (record id, CSV column, commit) lives in record
[0002](decision-records/0002-target-spec-first-ratification.md) §"Evidence".

| Parameter | Ratified value / definition | Binding conditions | Src | Status vs. the committed evidence |
|---|---|---|---|---|
| **Band** — RATIFIED | 2400–2483.5 MHz (2.4 GHz ISM), primary band | The band every other row's "across band" refers to; bench in-band sweep floors at 11 points across it | (4) | Closes former open item 1. The committed design, DR-0001's bias plan, and both committed campaigns are all built at 2.4 GHz (e.g. the hbt benches' 50 Ω NF at 2.4 GHz; the campaign's `sp lin 11 2.4e9 2.4835e9`). A 5–6 GHz variant is explicitly **out of scope** — unratified, would need its own decision record. |
| **Gain (S21)** — RATIFIED | **> 15 dB** (\|S21\|, 50 Ω ports) across the ratified band | Full ratified corner box below, with the DR-0001 bias mandate held (`I_C` = 4.0 mA, ≤ 4.5 mA); after input/output matching networks exist — verification gated on #26 + #27 | (1) + (4) | **FAILING-SPEC case, disclosed:** the as-committed (unmatched) DUT measures 12.63–12.74 dB at the nominal cell and −21.06…+14.22 dB across the 45-cell box (record `20260918-210908-4293920` summary CSV, `s21_db_min`/`s21_db_max`); the nominal shortfall (2.4 dB) is the absent input match: with \|S11\| = 0.933 and \|S12\| ≈ 1.9e−5 (−94 dB — the unilateral decomposition is exact for practical purposes), the conjugate-input-match available-gain basis is \|S21\|²/(1−\|S11\|²) ≈ 12.63 dB + 8.9 dB **≈ 21.5 dB**, so the 15 dB bar retains ≈ 6.5 dB of allowance for matching-network insertion loss and the finite-Q damping the campaign quantifies (~7.7 Ω series loss for Q ≈ 10 at 2.44 GHz). The target is **not relaxed**; the shortfall is attributed, not absorbed. |
| **Noise figure (NF)** — RATIFIED | **< 1.5 dB** across the ratified band, at **T0 = 290 K**, 50 Ω ports both ends | Full ratified corner box with the DR-0001 bias mandate held; after matching (#27); numbers from the `sp` analysis's 50 Ω port machinery per the campaign's bench definition | (2) + (3) + (4) | **FAILING-SPEC case, disclosed:** nominal-cell `nf290` = 1.867 dB (0.37 dB over target) while `NFmin` = 0.751 dB — the campaign's finding 3: ~1.1 dB of the present NF is the absent noise match, not the device. The ratified bar retains ≈ 0.75 dB of allowance for real matching-network loss (1.5 − 0.751). **Not relaxed; not met today.** The former stretch "< 1.0 dB (sub-dB)" is explicitly **NOT ratified**: best-cell `NFmin` 0.600 dB makes it reachable *in principle* (source (3) survives its first test) but it would demand < 0.25 dB of matching-network loss — unevidenced on any real SG13G2 inductor model (which do not exist yet, #27 / `2AMLogic/klayout-tools#1519`). It stays the repository's stated aspiration, unratified. |
| **Input match (S11)** — RATIFIED | **< −10 dB** across the ratified band, 50 Ω reference | Across the ratified corner box as far as the PDK's real sections allow — see "Not covered" for the L/C-mismatch axis; after #27 | (1) + (4) | **Not a failed match — the absence of one (disclosed):** `Cin`/`Cout` are 100 pF DC blocks, no base inductor exists; nominal in-band S11 = −0.575 dB, worst of 45 cells −0.244 dB — near-total reflection by construction. The −10 dB target is **unchanged** and binds the #27 matching design. Former stretch < −15 dB **NOT ratified** (no matched design exists to evidence it). |
| **Output match (S22)** — RATIFIED | **< −10 dB** across the ratified band, 50 Ω reference | Same as S11 | (1) + (4) | Same absence-of-match disclosure: nominal S22 = −0.0044 dB — a lossless reflection off the ideal `Lc` tank, \|S22\| ≈ 0.9995. 17 of 45 cells show broadband max \|S22\| = 1.000004 (+4 ppm, flagged for re-check once lossy inductor models exist, not dismissed). Target **unchanged**; binds #27. Former stretch < −15 dB **NOT ratified**. |
| **Stability** — RATIFIED, metric refined | **μ > 1 (Edwards–Sinsky)** — unconditional stability — measured **from 10 MHz to 30 GHz** (12× the upper band edge; the former DRAFT floor was ≥ 3× = 7.45 GHz), with **k, \|Δ\|, and the negative-resistance check (max \|S11\|, max \|S22\| < 1 with the other port at 50 Ω) reported alongside** | Every cell of the ratified corner box; the bench is the campaign's committed broadband sweep (40 pts/decade, 140 frequencies, `corners/<record-id>/*.stability.dat`) | `CLAUDE.md` + (4) | **FAILING-SPEC case, disclosed, and a metric refinement on evidence — not a relaxation:** the DRAFT row said "k > 1"; this campaign demonstrates k is *ill-conditioned on exactly this topology* (\|S12\| ≈ −94 dB makes Rollett's k a ratio of two nearly-cancelling fourth-decimal quantities: measured k spans −3.169…25.6 across the sweep), so the binding row pins the single necessary-and-sufficient, numerically robust distance metric, with k still *reported* per `CLAUDE.md`'s k-factor rule. μ > 1 is equivalent in assertion strength to k > 1 + /\|S12·S21\| > 1 (both ⇔ unconditional stability) — a binding claim no weaker than the DRAFT's. **Standing:** 40 of 45 cells measure μ < 1 somewhere in-band-or-broadband (min 0.99902, bcs/125 °C/1.98 V); in-band worst μ = 0.99952. The circuit as committed is *conditionally* stable — per `CLAUDE.md` this row **gates** the matching design: no match is final until μ > 1 holds across the sweep at every ratified cell. Ideal (infinite-Q) passives make the committed model the *least-damped* case — real inductor loss adds damping, so the bar is not evidenced-failing, but it is **unmet today**. Former stretch "k > 1.5" is **dropped** on this evidence (ill-conditioned metric; a μ-margin stretch was not evidenced and none is invented). |
| **IIP3** — numeric target **NOT RATIFIED** (kept DRAFT); measurement protocol RATIFIED | Numeric: former DRAFT **> 0 dBm** remains DRAFT — explicitly not ratified this pass and explicitly **not relaxed**. Protocol (binding definition for whenever the number is ratified): the two-tone transient bench of `sim/lna-characterization/testbench/tb_lna_iip3.spice.tmpl` — tones in the ratified band (f1 = 2.44140625 GHz, f2 = 2.44903564453125 GHz, Δ = 7.62939453125 MHz), FFT N = 65536 at 4 ps (bin = 3.814697265625 MHz), rectangular window, coherent bin-centered products, 1 µs discarded before the window, **double drive levels per cell with the 3:1 IM3 slope check mandatory**, ngspice `fft` + coherent-DFT cross-check | Number binding: at ratified 50 Ω ports, available-source-power-referred, after #26 (bias) and #27 (matching) re-measurement on this exact protocol — then a decision record of its own | `CLAUDE.md` + (4) | **The one row deliberately not force-ratified (tradeoff presented in full — values are never silently relaxed, but rows are not ratified without supporting evidence either):** the measured IIP3 is a *bias* result, not a linearity result — it spans **−22.0 to +9.7 dBm** tracking `I_C1`'s 25 µA–14.7 mA PVT spread (finding 1), and the nominal cell (−2.22 dBm at `I_C1` = 4.068 mA) is available-power-referred at an input absorbing only ~13 % of incident power (\|S11\| = 0.933): removing the mismatch inflation puts the device-plane intercept near **−11 dBm** at nominal, ≈ −9 dBm even at the best in-mandate cell (4.73 mA: −0.08 dBm measured − 8.9 dB). Current evidence therefore supports neither the draft bar nor any substitute number; the tone-spacing (7.63 MHz) base termination that dominates BJT IM3 will also change entirely once #26/#27 replace the 100 pF block and divider. Verdict: keep the draft bar DRAFT, ratify the protocol, bind the number after #26/#27 re-measure. Holding ≥ 0 dBm as a *design* ambition implies ~9–11 dB of linearity work inside the ratified < 10 mW / ≤ 4.5 mA envelope (levers with their costs: real emitter degeneration (NF cost), bias redistribution, derivative-suppression techniques) — a future design decision record, not a spec assertion. |
| **Supply** — RATIFIED | **1.80 V ± 10 %** (1.62–1.98 V), single rail, cascode `npn13G2` `Nx = 8` per [DR-0001](decision-records/0001-bias-supply-topology.md) (which record 0002 thereby ratifies) | The supply axis of the ratified corner box; `V_B2 = (11/12)·VDD` ratio-derived cascode base | (2) + (4) | Closes former open item 2. Basis: DR-0001's breakdown budget — worst-case device stress 1.116 V (`V_CE2`, α-low/VDD-high/wcs/−40 °C) and 1.097 V (`V_CE1`, α-high/VDD-high/bcs/125 °C) vs BVCEO(min) 1.4 V — now upgraded by committed extraction: **BVCEO ≥ 1.6126 V at the 500 µA/finger operating criterion across all 60 cells** (record `20260918-212948-013274f`); BVCER sustaining branches ≥ 2.03 V. The campaign swept exactly this ±10 % grid. Model-card lines re-verified against the resolved v0.3.0 checkout (2026-09-21); see source (2) and record 0002 for the honesty note on low-current criteria (at the 1 µA/finger *leakage* criterion two cells extract below 1.4 V — criterion-dependence stated, not hidden). |
| **Power (P_dc)** — RATIFIED | **< 10 mW** DC (whole block, core + bias network) | With the DR-0001 bias mandate held (`I_C ≤ 4.5 mA` over corners → DR-0001 budget ≤ 9.4 mW worst-case including bias overhead), across the ratified corner box; verification gated on #26 | (4) | **FAILING-SPEC case, disclosed:** the as-committed placeholder resistive divider violates the mandate at **21 of 45 cells** (`I_C1` to 14.697 mA) and this row at **20 of 45 cells** — worst P_dc **29.64 mW** at bcs/125 °C/1.98 V (finding 1; #26 is the gate). At the nominal cell the measured P_dc is **7.75 mW** (`I_DD` = 4.307 mA, summary CSV `pdc_w`) — in budget, inside the mandate. Target **unchanged**; the ratified row binds the #26 bias-network replacement. Former stretch "< 5 mW" **NOT ratified — dropped on the merits:** DR-0001 §1's NF-vs-power table shows the device wants `I_C` ≈ 4 mA (on the NF shoulder's flat top); < 5 mW needs `I_C` ≤ ~2.6 mA, spending ~0.2–0.5 dB of bare-device NF for a stretch that was never a requirement (dropping an unratified stretch is not a relaxation of the ratified bar). |

**IIP3 mismatch-inflation note** (the arithmetic behind that row's
device-plane numbers): with \|S11\| = 0.933 the delivered power fraction is
1−\|S11\|² ≈ 0.129, so an intercept extrapolated on the available-power axis
carries ≈ +8.9 dB over the delivered-power-plane device intercept; removing
the input match (driving the delivered fraction toward 1) removes that term.
Full arithmetic in record 0002 §"Evidence — IIP3".

## Verification corners (ratified)

**Process** {`typ` → `hbt_typ`, `bcs` → `hbt_bcs`, `wcs` → `hbt_wcs`; `sf`
and `fs` **fall back to `hbt_typ`** — `cornerHBT.lib` in the resolved v0.3.0
checkout ships exactly three real HBT sections, so `sf`/`fs` cells are
documented *duplicates* of `typ`, not independent corners (source (2);
`sim/README.md` §"Corner-label convention")} × **temperature** {−40, 27,
125} °C × **supply** {1.62, 1.80, 1.98} V. Read `wcs` as this repo's
`ss`-equivalent wherever older literature framing says "ss corner". This is
exactly the 45-cell grid the committed campaign ran.

**Not covered — recorded, not hidden:** passive-device corners
(`cornerCAP.lib`; there is no inductor SPICE/EM model at all in this PDK —
[#5](https://github.com/2AMLogic/sg13g2-lna/issues/5) / upstream
[`2AMLogic/klayout-tools#1519`](https://github.com/2AMLogic/klayout-tools/issues/1519),
both open at 0002's drafting) and therefore the L/C-mismatch axis the
former DRAFT S11/S22 binding corner named; mismatch/Monte-Carlo
(`*_mismatch`/`*_stat`); layout, parasitic extraction, pads/package; and
self-heating beyond the VBIC thermal network at ambient. These gaps gate
the *verification* of the ratified rows — they do not weaken the ratified
values themselves.

## Open items that gate verification of the ratified rows

1. **#26 — replace the placeholder bias divider.** Gates PVT verification of
   Gain, NF, IIP3 and Power (the campaign's finding 1: `I_C1` spans a ~590×
   range across the box, so no PVT performance number is currently
   characterizing what it appears to).
2. **#27 — design the input/output matching networks**, clearing the
   stability gate first (μ > 1 across 10 MHz–30 GHz at every ratified cell
   before any match is declared final, per `CLAUDE.md`). Blocked in practice
   on the inductor-model gap above. Gates Gain, NF, S11, S22, and the IIP3
   re-measurement that must precede that row's own ratification.
3. **Passive-model + mismatch coverage.** Until inductor models exist no
   S11/S22/gain/NF number is verified against a physical passive — the
   campaign's model-limitations statement stands: ideal passives make all
   of those numbers optimistic and stability numerically degenerate.
4. **#25 — NF source reference temperature.** For this spec the reference is
   pinned at T0 = 290 K from here on (the port-convention section); the
   historical hbt-characterization records' 300.15 K convention remains
   historical. Future benches in this repo use `nf290`.

Items 1 (band) and 4 (device noise-optimum sizing) of the former "must close
before ratification" list were closed by this record and DR-0001 (the hbt
record `20260910-200059-7da7038` supplies the optimum-bias table DR-0001
cites); item 2 (bias/supply topology) was closed by DR-0001 + 0002; item 3
(matching-network passives) is retained above as item 3.

Decision records live in [`spec/decision-records/`](decision-records/) —
one decision per record, `NNNN-<slug>.md`, numbered sequentially,
append-only: supersede, never edit. Start from
[`decision-records/TEMPLATE.md`](decision-records/TEMPLATE.md). A row above
is ratified only when a **ratified** decision record says so; record 0002
is that record for the RATIFIED rows of this table.
