# Roadmap

sg13g2-lna is a SiGe HBT low-noise amplifier on IHP SG13G2, built to reach the
T1 (sim-validated) checklist in
[`signoff/design-evidence-tiers.md`](signoff/design-evidence-tiers.md) with an
open-tool evidence chain for noise figure and S-parameters.

Status as of 2026-11-13, `main` @ `7a54cc2d`; tracker state as read that day.
This is the repo's first roadmap. It plans and holds no results: numbers live
in the `sim/` records, the verdict in [`signoff/t1-report.json`](signoff/t1-report.json).

## Where it stands

**T1: 3 of 11 items met** (`signoff/t1-report.json`, graded by `klt` 0.8.0).
The tracker is [#4](https://github.com/2AMLogic/sg13g2-lna/issues/4).

| Item | State | Evidence or open work |
|---|---|---|
| 1 Design sources | met | `signoff/attest/item1.envelope.json` (PR #240) |
| 2 Layout | unmet, no evidence | `layout/lna_core/` draws 6 instances of the netlist; #228 |
| 3 DRC clean | unmet, no evidence | partial-cell `drc_report.json` reads `clean` under `klt` 0.8.0 and is deliberately uncited (`signoff/README.md`); #229 |
| 4 LVS clean | unmet, check failed | `layout/lna_core/lvs_full_report.json` reads `mismatch`; #230 |
| 5 Corner verification | unmet, no evidence | no `klt sim` envelope for the current DUT; #231, behind #27 and #58 |
| 6 Monte Carlo | unmet, no evidence | DC mismatch campaign `20261105-080636-5383b49` exists (PR #252) but is not a `klt yield` envelope and reads the pre-match DUT; #68 |
| 7 Post-layout | unmet, no evidence | needs a complete, LVS-matched layout; #232 |
| 8 Characterization report | unmet, no evidence | `measurements/README.md` is descriptive and reads a historical record; #233 |
| 9 Testbenches shipped | met | `signoff/attest/item9.envelope.json` |
| 10 Repo hygiene | met | `signoff/attest/item10.envelope.json` |
| 11 Power delivery | unmet, no evidence | needs items 2 to 4 first; #35 |

**Design.** The spec is ratified for band, gain, NF, S11, S22, stability,
supply and power (decision record 0002); the IIP3 numeric target is still
DRAFT. The DR-0003 flat bias core is in `design/`. PR #247 added a first
matching network (`lp_noise`, nominal-cell, not final), so
`design/netlist/lna.spice` is now a matched DUT; the pre-match netlist is
frozen in `sim/pre-match-dut/`.

**Evidence for the matched DUT is thin.** The only committed
`lna-characterization` record on the current netlist,
`20261101-023246-5bbb70c`, is a three-point smoke run. The 45-cell records
(`20260926-122301-088c734`, bias record `20260921-173552-2aeafef`) describe
the pre-match DUT. The matched DUT failed DC convergence in 18 of 45 cells
because net `xout` has no DC path (#258).

**Noise figure.** Decision record 0004 (ruled 2026-10-08) keeps the ratified
NF row and spends the untried design levers first (Option C). The first lever,
the larger emitter array, is #58: its one-cell fleet gate is recorded (PR #263)
and its 45-cell campaign ran to completion but was not published.

## Now

No open issue is ready to draw today. Items 1 and 2 have no issue yet.

1. **Refresh the status prose after PR #247 and PR #252.** `README.md` still
   calls `20260926-122301-088c734` "the current `main` DUT" and says the bias
   record's DUT hash "matches today's" netlist; `sim/lna-characterization/README.md`
   §"Status of the 45-cell run" still describes a `klt 0.5.0` runner image;
   `signoff/README.md` says no statistical evidence exists at all. Done when
   each statement names the DUT its record actually ran, `check-record-citations`
   and `check-repo-hygiene.py` pass, and the item 10 attestation is refreshed.
2. **Bump the `klt` pin from 0.8.0.** PyPI carries 0.9.1 and the batch runner
   reported 0.9.0 in the `20261105-080636-5383b49` record, so campaign clients
   and the signoff pin have diverged. Done when `check-klt-pin.sh` passes on
   the new pin, `layout/lna_core/` evidence and `signoff/t1-report.json` are
   regenerated, and the partial-layout scope guard still holds (no row turns
   `met` on a 6-instance cell). Precedent: #235.
3. **Account for `Rbleed` in the layout scope, on the PR #259 branch.**
   PR #259 adds `Rbleed xout vss 100k` and fails `layout-freshness` because
   `layout/lna_core/realization.json` no longer partitions the netlist.
   Done when `Rbleed` is assigned (drawn, or listed out of scope with its
   reason), `layout/run_flow.sh` is rerun, and `layout-freshness` and the
   item 1 and item 10 attestations pass in CI. Issue #260, which is parked
   on PR #259 while PR #259 waits on exactly this work.

## Next

- **Finish #258: full PVT record of the matched DUT.** Unblocked once PR #259
  merges. The 125 C slice is in that PR; the -40 C and 27 C slices stopped on
  batch capacity. Done when a 45-cell record on the post-bleed netlist is
  committed with per-cell convergence status and the nominal match delta.
- **Close out #27 (matching network) at PVT.** Needs the #258 record; the
  upstream blocker it names, klayout-tools#1519, is closed. Done when S11, S22
  and broadband stability are read at all 45 cells on the matched DUT and the
  network is declared final or re-sized with a new record.
- **Re-scope or close #56 (lossy inductor models).** The EM model is vendored
  (`sim/models/`) and the matched DUT already carries finite-Q loss elements;
  the runner gap it was parked on predates the 0.9.0 batch runner. Done when
  the six-variant 45-cell record is committed or the issue says why the
  matched-DUT campaign supersedes it.
- **Item 5 envelopes (#231), then the characterization report (#233).** After
  #27. Done when each ratified row has a `klt sim` envelope at the full corner
  box, IIP3 is declared as an unratified gap, and one documented command
  regenerates the report.
- **Full-block layout (#228).** After #27 fixes the component list. Done when
  `realization.json` has no un-drawn instance and `generate.py` reproduces the
  committed GDS hash.

## Later

- **DRC, LVS, post-layout and power delivery on the full block (#229, #230,
  #232, #35).** Question first: can an LVS route recognize `npn13G2` and reach
  `match`? #230 expects the PDK runset path through `klt lvs`; the upstream gap
  it cited (klayout-tools#4309) is closed, and whether a released `klt` carries
  the fix is unchecked.
- **RF statistical evidence for item 6.** Question first: which ratified rows
  are statistical for this block, and does the PDK give passive mismatch models
  to run them against? `spec/target-spec.md` §"Statistical coverage" lists S11,
  S22 and stability as statistically unmeasured.
- **Further NF levers under decision record 0004.** Question first: does the
  larger emitter array (#58) move the NF pass count enough to adopt it?

## Blocked and waiting

- **PR #259** is held for an operator decision with `layout-freshness` and
  `attest` red. Item 1 re-attestation needs xschem 3.4.4, the version CI pins;
  the dispatch workers reported 3.4.7.
- **#58** needs a ruling: the fleet control replay missed the 1e-6 replay
  tolerance, so the reducer refused to publish; the issue recommends a bounded
  investigation first.
- **#68** needs a ruling: close it as delivered by #89 and #90, or re-file the
  RF-chain Monte Carlo as a new issue.
- **#227** (live `klt artifact verify`) needs a ruling on who runs it; a
  Builder cannot meet its acceptance on a shared dispatch host.
- **#201** (native PDK DRC) waits on a worker with a compatible standalone
  KLayout. The runner, `layout/run_native_drc.py`, is committed.

## Not planned

- Relaxing a ratified row to make a result pass (`CLAUDE.md`). Decision
  record 0004 records Options B and D as not taken.
- Citing the 6-instance bring-up for items 2, 3 or 4 (`layout/README.md`).
