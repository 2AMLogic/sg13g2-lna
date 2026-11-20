# Work Log

## Archives

- [2026-09](work_log/WORK_LOG_2026-09.md)

### 2026-11-20

- **Issue #454** (closed): Share batch-set report collection between the variant and IIP3 runners
- **PR #464**: refactor(sim): share the batch-set report collector between the variant and IIP3 runners
- **Issue #433** (closed): docs: README.md:3-4 lede duplicates the PDK name ("on IHP SG13G2 on [IHP SG13G2]")
- **PR #462**: docs: name the PDK once in the README and CLAUDE.md ledes
- **Issue #439** (closed): Share the per-point IIP3 measurement calculation across both reducers
- **PR #444**: refactor: share the per-point IIP3 measurement across both reducers
- **Issue #446** (closed): check-signoff.sh does not gate on a T1 met-count regression
- **PR #455**: feat: gate check-signoff.sh on T1 met-item regressions vs the merge base
- **Issue #452** (closed): test_usage_errors' seg() == [] assertion is vacuous: class 2's non-archival is still unguarded
- **PR #457**: test: seed a previous pair so usage errors' no-archive assertion can fail
- **Issue #447** (closed): Pin the campaign IIP3 CSV column order in a test (the agreement-column splice is unguarded)
- **PR #453**: test: pin the campaign iip3.csv column order against the committed record header
- **Issue #443** (closed): No test covers native DRC exit class 7 (E_SELFCHECK), whose non-archival invariant is now a set-membership test
- **PR #451**: test: cover native DRC exit class 7's non-archival invariant
- **Issue #35** (closed): T1 item 11 (power delivery, structural): klt erc supply spec + LVS supply pairing — unmet until layout exists
- **PR #434**: feat(signoff): T1 item-11 power-delivery ERC evidence -- supply spec, negative controls, compound citation
- **Issue #425** (closed): Reuse the validated S-parameter log for the 290 K noise-figure cross-check
- **PR #445**: fix: reuse validated S-parameter measurements for the 290 K NF cross-check
- **Issue #437** (closed): Item-9 fixture suite has no case that fails when tree_digest's hash input changes
- **PR #442**: test: pin the item-9 corners tree digest against an independent sha256
- **Issue #435** (closed): Centralize native DRC cleanup so a failed klt version probe archives the previous report
- **PR #440**: fix: archive the previous native DRC pair at one exit point, not nine
- **Issue #428** (closed): Reuse the collected record paths for item 9 tree digests
- **PR #436**: refactor: reuse the evidence_files paths for item-9 tree digests
- **Issue #430** (closed): Root README status paragraph is stale: understates T1 met count and still calls the layout a partial bring-up with DRC not clean
- **PR #431**: docs: refresh stale README status paragraph and regenerate hygiene attest cascade
- **Issue #424** (closed): Gate extract_report.json connectivity (split_net_labels / merged_net_labels) in CI: an opened net is currently silent
- **PR #429**: feat: gate extract_report connectivity in the layout-freshness check
- **Issue #229** (closed): T1 item 3 (DRC clean): clean klt drc on the full-block GDS with coverage disclosed
- **PR #427**: feat(signoff): re-cite T1 item 3 (DRC clean) on the full-block GDS
- **PR #423**: feat(layout): assemble the full LNA block -- pads, inter-block routing, T1 item-2 evidence
- **Issue #228** (closed): T1 item 2 (layout): full-block LNA layout generator and GDS, beyond the 6-of-30-instance bring-up

### 2026-11-18

- **Issue #82** (closed): Auditor Capability Request: Python 3 unavailable on audit host
- **PR #419**: refactor: extract netlist value parse and pin parity with gate copy
- **Issue #410** (closed): inductance_lowfreq.py: netlist_values() is a second gate-side copy with no parity pin (unlike l_lowfreq)
- **PR #417**: chore(hygiene): hash eleven more CI-run gate self-tests in the item-10 envelope
- **Issue #414** (closed): repo-hygiene: 10 more CI-run gate self-tests are undeclared and unhashed (the #411 class)
- **PR #415**: fix(layout): reject router pin pairs closer than stub pitch plus Metal2 space
- **Issue #412** (closed): Router pin-collision guard accepts different-net stubs abutting at exactly the stub pitch
- **PR #407**: feat: gate re-derives netlist_H and drawn_over_netlist in inductance report
- **Issue #403** (closed): check-layout-freshness: the netlist half of inductance_report.json is still ungated
- **PR #413**: chore(hygiene): hash the layout-freshness self-test in the item-10 envelope
- **Issue #411** (closed): repo-hygiene: test-check-layout-freshness.sh is run by CI but absent from DECLARED_COMMANDS
- **PR #409**: feat: Router fails loudly when different-net Metal2 stubs would overlap
- **Issue #406** (closed): layout: Router asserts no two bias pins share an x, but never checks it
- **PR #408**: chore(signoff): hash inductance_lowfreq.py in the repo-hygiene inventory
- **Issue #404** (closed): repo-hygiene: inductance_lowfreq.py is not in HYGIENE_FILES, unlike native_drc_pair.py
- **PR #405**: feat(layout): draw the bias side with routed intra-block wiring
- **Issue #346** (closed): T1 item 2 (layout) part A: draw the bias-side instances (DR-0003 reference core, vb2 divider, decoupling) in lna_core
- **PR #402**: feat: gate verifies inductance report against realization geometry
- **Issue #400** (closed): check-layout-freshness does not cover inductance_report.json
- **PR #399**: feat(layout): draw the matching network and add a modeled_in_device scope category
- **Issue #347** (closed): T1 item 2 (layout) part B: draw the matching network (inductors via inductor2 PyCell, caps) and settle the loss-resistor partition
- **PR #397**: fix: blank lines in a run: block no longer truncate its collected commands
- **Issue #395** (closed): check-repo-hygiene.py: a blank line truncates a block-scalar run: body
- **PR #394**: ci: report required checks on merge-group runs
- **Issue #391** (closed): Merge queue: add the merge_group trigger and adapt the PR-metadata gates
- **PR #389**: fix: native-DRC pair check rejects non-dict provenance and null bindings
- **Issue #386** (closed): native-DRC pair check: non-dict provenance crashes, and null deck/pdk bindings are accepted
- **PR #385**: refactor: one native-DRC pair check, path-loaded by gate and layout
- **Issue #359** (closed): Consolidate native-DRC pair validation: one implementation instead of three

### 2026-11-17

- **PR #315**: refactor: consolidate five run_deck() deck gates into one sim_run_deck helper
- **Issue #300** (closed): Consolidate five duplicated run_deck() gates in lna-matching-feasibility runners into sim/env.sh
- **PR #377**: ci: resolve bare cold-start command words by basename in the exec-bit assertion
- **Issue #376** (closed): ci: the exec-bit assertion does not cover a basename-only documented command word (reduce_biasop.py)
- **PR #375**: ci: key the testbench-inventory executable-bit assertion on the command word, any extension
- **Issue #372** (closed): ci: no guard keeps a documented bare-path .py command executable (class of #367/#369)
- **PR #371**: fix: make rederive_nf_fixed_t0.py executable for record replay command
- **PR #370**: feat(signoff): generate the item-8 characterization report with a mechanically derived envelope
- **PR #368**: fix: make lna_variant_campaign.py executable for README reviewer-replay
- **PR #366**: test+ci: replay-gate the spec-envelope bench and unit-test its generator
- **PR #365**: docs: correct the nf spec_row rationale to match the pinned klt render
- **PR #362**: fix: run gated attest/signoff local checks via a pinned uvx klt fallback
- **PR #361**: sim: cite T1 item 5 with ratified-row klt sim corner envelopes
- **PR #360**: docs: align audit self-test header with post-#323 klt SKIP/FAIL policy
- **PR #358**: chore(loom): resync installed Loom to v0.19.1306
- **PR #356**: docs: note the ngspice-47 maxindex/minindex gap beside the issue-27 probe record reference
- **PR #355**: docs: mark pre-bleed characterization records superseded in root README
- **PR #354**: run_lna_variant: smoke-aware Claim/Reduction record lines
- **PR #353**: sim: matched-DUT two-tone IIP3 on the ratified protocol (93 pts + 45 op corners, 45-cell PVT box)
- **PR #351**: fix: TEMPERATURE SLICE disclosure names the grid's temperatures, not the requested slice
- **PR #349**: fix(sim): make sim_record_paths reservation monotonic, split its two mkdir failure modes
- **PR #348**: signoff: state taxonomy precedence for a variant study on a superseded DUT
- **Issue #369** (closed): Second instance of #367: rederive_nf_fixed_t0.py documented as a bare-path replay command but not executable
- **Issue #367** (closed): README reviewer-replay command fails as written: lna_variant_campaign.py is not executable
- **Issue #364** (closed): Ratified-row envelope bench has no CI replay gate or unit tests, unlike every sibling reducer
- **Issue #363** (closed): Envelope generator's rationale for the untagged nf measurement is refuted by the pinned klt render
- **Issue #357** (closed): run-local-checks.sh always skips the attest steps on workers (exact klt version match), hiding stale pinned manifests
- **Issue #352** (closed): run_lna_variant.sh record Claim/Reduction lines name the requested --temps slice on a smoke run, where the cell is 27 C
- **Issue #350** (closed): README.md:81,192 group records 20261114-025351-7a54cc2 and 20261101-023246-5bbb70c under 'the matched DUT now on main', but both ran on the superseded pre-bleed netlist
- **Issue #344** (closed): probe decks: maxindex/minindex unavailable in ngspice-47, so the frequency-attribution print never emits
- **Issue #337** (closed): post-match IIP3 re-measure on the ratified protocol (owed by #27 Test Plan; binds spec/target-spec.md line 171)
- **Issue #329** (closed): lna_variant_campaign: TEMPERATURE SLICE disclosure names the wrong temperature on a smoke+slice run
- **Issue #327** (closed): signoff/README.md:97 calls record 20261114-025351-7a54cc2 'historical-dut' where sim/lna-characterization/README.md calls it 'variant-exploration'
- **Issue #324** (closed): test-design-source-audit.sh header comment still describes absent klt as SKIP-only (stale after #323)
- **Issue #311** (closed): test flake / suspected sim_record_paths race: concurrency case fails again (wins=1 losses=7), now with per-caller evidence
- **Issue #233** (closed): T1 item 8 (characterization): one-command characterization report with generic envelope
- **Issue #231** (closed): T1 item 5 (corner verification): klt sim corner envelopes for the eight ratified rows
- **PR #343**: docs: reword the last two bare klt-pin restatements into the gated klayout-tools== form
- **PR #340**: fix: gate run_native_drc.py's docstring klt pin, restate README pins prefixed only
- **PR #338**: feat: gate the README prose klt/KLayout pins in check-klt-pin.sh
- **PR #335**: docs: state the pin-move netlist claims as evidence, not a 3.4.4-era attribution
- **PR #334**: records: matched-DUT 45-cell PVT verdict; |S22|>1 anomaly closed by fine-sweep probe
- **PR #331**: fix: derive native DRC full-scope NOTE from FULL_SCOPE_STATUSES, pin in tests
- **Issue #342** (closed): evidence: issue-27 probe record's |S22|>1 / mu<1 point counts are table recounts that disagree with the committed ngspice log (325 vs 334, 364 vs 365)
- **Issue #341** (closed): check-klt-pin.sh: two bare klt-pin restatements remain ungated (README.md:122, signoff/README.md:8)
- **Issue #339** (closed): check-klt-pin.sh still misses two klt/KLayout pin literals: run_native_drc.py's docstring and README.md:80's bare backticked versions
- **Issue #321** (closed): run_native_drc.py's not-full-scope NOTE hardcodes a fourth status subset that no test pins
- **Issue #320** (closed): check-klt-pin.sh's file loop still misses README.md and layout/README.md, so the prose klt/KLayout pins can drift
- **Issue #305** (closed): design/README.md misstates which xschem generated the committed netlist
- **Issue #27** (closed): design: LNA has no input/output matching network — S11 = -2.96 dB, S22 = -0.003 dB, broadband mu < 1 at 45/45 PVT cells (DR-0003 core)

### 2026-11-16

- **PR #317**: chore(loom): resync installed Loom to v0.19.1302
- **PR #319**: lna_variant_campaign: make a --temps slice disclose itself and unit-test the option
- **Issue #306** (closed): lna_variant_campaign: --temps slicing has no unit test; a narrower summarize slice under-checks coverage silently
- **PR #326**: docs(sim): index all 11 lna-characterization records by DUT and retire the stale 'current' labels
- **Issue #318** (closed): sim/lna-characterization/README.md's "Which DUT each record describes" table is stale: 3 of 9 records, and the one it calls "current main" is superseded
- **PR #323**: ci: fail audit suite on absent klt under CI
- **Issue #307** (closed): test-design-source-audit.sh still SKIPs green in CI when klt is absent from PATH (not just wrong-version)
- **PR #296**: fix(layout): accept clean_partial and not_checked native DRC verdicts across all three gates
- **PR #304**: ci: gate KLAYOUT_PIN and derive the audit suite's expected klt release
- **PR #314**: sim: land the matched DUT's -40/27 C PVT slices and the bleed match delta
- **PR #316**: docs(signoff): correct the item 5 bullet's absence claim, campaign count and DUT label
- **PR #281**: refactor(core-envelope): name the in-band gain metric and split parse_core_envelope main()
- **PR #308**: refactor: share one main() driver between the item-9/item-10 inventory checkers
- **Issue #290** (closed): run_native_drc.py STATUSES omits clean_partial, so a partial-scope native DRC run would be rejected as a failed run
- **Issue #312** (closed): layout/README.md and run_native_drc.py docstring overstate clean_partial reachability: klt 0.9.2's klayout engine cannot emit it
- **Issue #294** (closed): check-klt-pin.sh cannot gate test-design-source-audit.sh's klt version strings, so a future bump silently disables its klt cases
- **Issue #258** (closed): design: give the output-match node xout a DC path and re-run the matched DUT's 125 C cells
- **Issue #301** (closed): signoff/README.md item 5 says no klt sim envelope exists for the current DUT, three sentences before naming the one that does
- **Issue #276** (closed): Name the logic buried in parse_core_envelope.py: 404-line main() and the one gain metric #94 left inline
- **Issue #302** (closed): signoff checkers: main() is still duplicated after #274 (the largest remaining shared block)

### 2026-11-15

- **PR #293**: test: pin the variant campaign's bias-attribution claim generator
- **PR #259**: design: add DC bleed on xout, floating-node guard, 125 C batch record
- **PR #298**: docs: correct the pre-match/matched DUT claims in the status prose
- **PR #297**: test: pin Python corner-section map copies to sim/env.sh (#287)
- **Issue #279** (closed): sim: unit-test the variant campaign's bias-attribution claim generator (ic1_pct, span_scaled, the ±0.05 % branch)
- **Issue #260** (closed): PR #259 follow-up: add Rbleed to layout, rerun LVS, re-attest T1 items 1/10
- **Issue #271** (closed): docs: refresh status prose that still describes the pre-match DUT (README, signoff/README, lna-characterization README)
- **Issue #287** (closed): sim: reduce_biasref.py still holds a private copy of the corner-label -> MOS-section map that #283 consolidated on the shell side

- **PR #292**: sim: validate core-envelope base-netlist anchors up front and print per-variant substitution evidence
- **PR #291**: refactor: dedupe startup verdict rule and require across the sim reducers
- **PR #284**: refactor(signoff): consolidate inventory/envelope scaffolding into signoff_common.py
- **Issue #289** (closed): check-klt-pin.sh does not gate KLAYOUT_PIN, so the engine pin can skew between run_flow.sh and run_native_drc.py
- **Issue #280** (closed): Finish #160: dedupe the startup verdict rule and its thresholds across the two sim reducers
- **Issue #277** (closed): sim-core-envelope-lifecycle-tests fails intermittently: XQ1 geometry substitution did not match scratch netlist
- **Issue #274** (closed): Consolidate the duplicated signoff inventory/envelope scaffolding in .github/scripts
- **PR #285**: chore: bump pinned klayout-tools to 0.9.2 and regenerate layout and signoff evidence
- **Issue #272** (closed): Bump the klayout-tools pin 0.8.0 -> current release and regenerate layout and signoff evidence

### 2026-11-14

- **PR #286**: sim: move the corner-label -> PDK-section maps into sim/env.sh
- **PR #278**: chore: replace exit-0 npm script stubs with the real check runner
- **PR #275**: sim: run the inductor-loss variant campaign on the fleet and record 45 cells
- **PR #270**: docs: roadmap as of 2026-11-13
- **Issue #283** (closed): sim: the corner-label -> PDK-section maps are copy-pasted byte-identical across six run_*.sh runners — finish #50 and move them into sim/env.sh
- **Issue #273** (closed): Remove package.json placeholder scripts: npm test/check:ci/check:all/lint exit 0 without verifying anything
- **Issue #56** (closed): sim: replace the ideal inductors with EM-extracted lossy models from sg13g2-vco (removes the blocker on #27, T1 item 5 match and stability rows)

### 2026-11-08

- **PR #263**: sim: wait for batch capacity in core-envelope runner; record passing fleet gate (#58)

### 2026-11-06

- **Issue #255** (closed): Simplify: 8 inline importlib loaders replaced a one-line sha256 helper (+34 net LOC)

### 2026-11-05

- **PR #254**: refactor(sim): share one file-SHA-256 helper across sim scripts
- **PR #252**: feat(sim): publish 200-sample full-DUT DC mismatch campaign from fleet
- **Issue #253** (closed): Dedupe the file-SHA-256 helper copied across nine sim scripts
- **Issue #90** (closed): sim: measure full-DUT DC mismatch spread with a seeded fleet campaign and controls

### 2026-11-01

- **PR #249**: feat(sim): add matched-DUT variant to the LNA PVT variant campaign
- **PR #247**: feat(design): add lp_noise matching network to the LNA (nominal-cell, not final)

### 2026-10-29

- **Issue #238** (closed): T1 grading: attest items 1, 9, 10 with klt signoff --attest and re-grade against the current tiers doc
- **PR #240**: feat: attest T1 items 1, 9, 10 with klt signoff --attest

### 2026-10-28

- **Issue #241** (closed): test flake: sim-record-paths concurrency case fails intermittently (wins=1 losses=7)
- **PR #242**: test: report which term fails in sim_record_paths concurrency case

### 2026-10-27

- **Issue #235** (closed): Bump klayout-tools pin 0.7.0 → 0.8.0
- **PR #236**: chore: bump pinned klayout-tools to 0.8.0 and regenerate layout evidence

### 2026-10-24

- **Issue #222** (closed): Adopt the common artifact store for sim evidence (manifests in git, bytes via klt artifact)
- **PR #223**: feat: manifest-forward artifact store writer and CI check for new sim evidence

### 2026-10-23

- **Issue #224** (closed): main CI: matching-feasibility-tests replay fails with last-digit float diffs since 2026-10-21
- **PR #225**: ci: pin matching-feasibility-tests to ubuntu-24.04

### 2026-10-17

- **Issue #217** (closed): signoff: attest T1 item 10 (repo hygiene) with a tool-produced klt signoff --attest 10 envelope
- **PR #218**: feat(signoff): attest T1 item 10 with an audited repo-hygiene inventory

### 2026-10-15

- **Issue #182** (closed): signoff: attest T1 design sources with an audited artifact inventory
- **PR #183**: signoff: attest T1 item 1 with an audited design-source inventory

### 2026-10-14

- **Issue #46** (closed): README: embed the fleet burndown chart (one line)

### 2026-10-11

- **Issue #202** (closed): sim: fix tank-probe drive in the #200 requirements study and complete the run
- **Issue #207** (closed): sim: correct ideal-choke isolation attribution in the requirements reducer
- **PR #210**: sim: correct ideal-choke isolation attribution in the requirements reducer (#207)
- **Issue #208** (closed): Build/runtime failure on main: testbench inventory rejects layout/run_native_drc.py
- **PR #209**: signoff: classify layout/run_native_drc.py in the testbench inventory (#208)
- **Issue #128** (closed): sim: keep partially failed core-envelope campaigns resumable
- **PR #206**: sim: keep partially failed core-envelope campaigns resumable
- **Issue #200** (closed): sim: quantify feed-isolation and input-Q requirements after the Le study NO-GO
- **PR #205**: sim: voltage-driven tank probe and completed input-Q/feed-isolation requirements run (#200, #202)
- **Issue #185** (closed): layout: add a version-checked native PDK DRC runner and provenance checks
- **PR #204**: layout: version-checked native PDK DRC runner and provenance checks
- **PR #203**: sim: #200 requirements study -- declaration and stopped first run (probe control)
- **Issue #198** (closed): sim: jointly choose emitter degeneration and input match for the finite base feed
- **PR #199**: sim: joint Le / input-match study on the finite base feed (#198): NO-GO, noise floor binds
- **Issue #179** (closed): Auditor guard review: retain destructive reset and cleanup protection
- **Issue #174** (closed): Auditor guard review: retain unresolved-variable removal protection
- **Issue #153** (closed): Auditor guard review: retain shared stash protection
- **Issue #195** (closed): signoff: attest shipped measurement benches with an audited T1 item-9 inventory
- **PR #197**: signoff: attest shipped measurement benches with an audited T1 item-9 inventory
- **Issue #180** (closed): sim: bind manifest-backed RF aggregates to declared campaign points
- **PR #196**: sim: bind RF campaign aggregates to manifest-declared points (#180)
- **Issue #124** (closed): Auditor guard review: retain main-checkout write confinement

### 2026-10-10

- **Issue #193** (closed): sim: test a finite resonant base-bias feed against the ideal-choke noise bound
- **PR #194**: sim: finite resonant base-bias feed vs ideal-choke noise bound (#193)
- **PR #192**: sim: re-attempt #90 fleet MC campaign; still blocked by runner klt 0.5.0
- **Issue #190** (closed): sim: give matching verification decks a measured DC reference without hiding stability-margin sensitivity
- **PR #191**: sim: explicit DC reference on xout for matching verification decks, with measured sensitivity (#190)
- **Issue #187** (closed): measurements: use the derived 290 K noise floor in current reachability summaries
- **PR #189**: measurements: use derived 290 K noise floor in current reachability summaries (#187)
- **Issue #186** (closed): sim: nominal-cell matching-network feasibility study with lossy inductors (unblocks #27 design choice)
- **PR #188**: sim: nominal-cell matching-network feasibility study with lossy inductors (#186)
- **Issue #97** (closed): Auditor guard review: keep gh-api-rawfield-body-literal-at flagged
- **Issue #181** (closed): sim: derive comparable 290 K NFmin budgets and correct RF reachability prose
- **PR #184**: sim: derive comparable 290 K NFmin budgets and correct RF reachability prose
- **Issue #176** (closed): ci: verify the extracted SPICE output against the extraction report digest
- **PR #178**: ci: verify extracted SPICE output against extraction report digest
- **Issue #173** (closed): test: unit-test layout/pcell_env.py PDK resolution, PyCell digest, and generate.py grid snapping
- **PR #177**: test: unit-test pcell_env PDK resolution, digest, and _snap (#173)
- **Issue #172** (closed): test: unit-test sim/tools/reducer_common.py shared reducer helpers
- **PR #175**: test: unit-test sim/tools/reducer_common.py (#172)
- **PR #171**: sim: full-DUT DC mismatch campaign tooling; fleet run blocked by runner klt skew (#90)
- **Issue #162** (closed): test: unit-test layout/lvs_identity.py sidecar binding and malformed-sidecar handling
- **PR #169**: test: unit-test layout/lvs_identity.py sidecar binding (#162)
- **Issue #165** (closed): sim: validate core-envelope wrdata integrity before counting stability violations
- **PR #170**: sim: validate core-envelope wrdata integrity before counting stability violations
- **Issue #145** (closed): sim: replay breakdown summaries independently of the simulation runner
- **PR #168**: sim: replay breakdown summaries independently of the simulation runner (#145)
- **Issue #161** (closed): docs: refresh spec/README.md decision-records entry (directory exists, index 0001-0004)
- **PR #167**: docs: spec/README decision-records entry and index (#161)
- **Issue #155** (closed): sim: bind HBT model-validity evidence to the complete DUT device inventory
- **PR #166**: sim: bind HBT model-validity evidence to the complete DUT device inventory
- **Issue #150** (closed): sim: reject invalid RF log measurements before coverage classification
- **PR #164**: sim: reject invalid RF log measurements before coverage classification
- **Issue #160** (closed): Consolidate duplicated helpers across sim reducers
- **PR #163**: sim: consolidate duplicated reducer helpers (#160)
- **Issue #158** (closed): sim: distinguish synthetic gate verdicts from live campaign authorization
- **PR #159**: sim: distinguish synthetic gate verdicts from live campaign authorization
- **PR #157**: sim: offline campaign prep for emitter array and cascode split (#58 milestone A)
- **Issue #154** (closed): sim: audit startup settling over a physical-time waveform interval
- **PR #156**: sim: audit startup settling over a physical-time waveform interval
- **Issue #149** (closed): sim: validate and independently replay bias-reference phase reductions
- **PR #152**: sim: validate and independently replay bias-reference phase reductions (#149)
- **Issue #89** (closed): docs: disclose missing DC and RF statistical evidence for T1 item 6
- **PR #151**: docs: disclose missing DC and RF statistical evidence for T1 item 6
- **Issue #144** (closed): sim: reject malformed HBT measurement tokens before CSV publication
- **PR #148**: sim: reject malformed HBT measurement tokens before CSV publication (#144)
- **Issue #73** (closed): Install ratification/ee-key and ratification/market-key reviewer trees (product#151)
- **PR #147**: ratification: install the two-key reviewer variant (EE key + market key) (#73)
- **Issue #117** (closed): sim: validate and replay DC bias and startup reduction before accepting evidence
- **PR #146**: sim: validate and replay DC bias and startup reduction before accepting evidence
- **Issue #141** (closed): ci: generate the measurements results table and per-row verdicts from the summary CSV, with a drift gate
- **PR #143**: ci: generate results table and per-row verdicts from the summary CSV, with drift gate (#141)
- **Issue #70** (closed): docs: biasref-topology README and DR-0003 cite a Stage-1 record id (20260921-154716-f718094) that does not exist
- **PR #142**: docs: correct Stage-1 biasref record id citation (#70)
- **Issue #138** (closed): ci: verify schematic connectivity through headless xschem regeneration
- **PR #140**: ci: verify schematic connectivity through headless xschem regeneration
- **Issue #137** (closed): sim: validate cubic-region IIP3 before reporting accepted intercepts
- **PR #139**: sim: per-cell IIP3 method-validity check (#137)
- **Issue #134** (closed): sim: extend 290 K NF measurement across the in-band frequency grid
- **PR #136**: sim: extend 290 K NF measurement across the in-band frequency grid (#134)
- **Issue #133** (closed): sim: validate RF frequency grids before marking campaign points complete
- **PR #135**: sim: validate RF frequency grids before marking campaign points complete
- **Issue #130** (closed): layout: bind LVS verdicts to reference netlists and comparison requests
- **PR #132**: layout: bind LVS verdicts to reference netlists and comparison requests
- **Issue #129** (closed): docs: refresh signoff evidence status after DR-0003 re-baselining
- **PR #131**: docs(signoff): refresh evidence status after DR-0003 re-baselining
- **Issue #126** (closed): sim: guard core-envelope resume with input identity and immutable publication
- **PR #127**: sim: guard core-envelope resume with input identity and immutable publication
- **Issue #123** (closed): sim: prevent standalone NF derivations from overwriting historical evidence
- **PR #125**: sim: refuse to overwrite existing evidence in standalone NF derivations
- **Issue #118** (closed): sim: verify installed PDK identity against the release pin before recording results
- **PR #122**: sim: verify installed PDK identity against release pin in preflight
- **Issue #116** (closed): sim: record expected RF point coverage and validate complete drive pairs
- **PR #121**: sim: record expected RF point coverage and validate complete drive pairs
- **Issue #119** (closed): ci: extend layout freshness to extraction and scoped LVS report provenance
- **PR #120**: ci: extend layout freshness to extraction and scoped LVS report provenance

### 2026-10-09

- **Issue #113** (closed): sim: reserve record IDs atomically to prevent same-second evidence collisions
- **PR #115**: sim: atomic record-id reservation in sim_record_paths (#113)
- **Issue #108** (closed): ci: add a single local runner that mirrors the signoff.yml checks
- **PR #112**: ci: add a single local runner that mirrors the signoff.yml checks

### 2026-10-09

- **Issue #109** (closed): test: unit-test layout/lvs_reference.py partition and card-rewrite invariants
- **Issue #105** (closed): ci: add a shellcheck lint job for the sim runners and check scripts
- **Issue #104** (closed): test: unit-test parse_core_envelope.py against a trimmed wrdata fixture
- **PR #111**: test: unit-test layout/lvs_reference.py partition and card-rewrite invariants
- **PR #110**: ci: add pinned ShellCheck shell-lint job (#105)
- **PR #107**: test: unit-test parse_core_envelope.py against a trimmed wrdata fixture
- **Issue #101** (closed): tests: unit-test hbt-characterization/rederive_nf_fixed_t0.py (fixed-T0 NF correction) and run it in CI
- **Issue #100** (closed): signoff: bump the grader klt pin 0.6.0 → 0.7.0 to match the layout flow that mints the cited evidence
- **Issue #87** (closed): sim: validate committed-DUT variant reports and summarize ratified-row coverage
- **Issue #84** (closed): ci: enforce vendored inductor-model checksum provenance
- **Issue #94** (closed): Consolidate duplicated RF helpers in the core-envelope postprocessors
- **PR #103**: sim: unit-test rederive_nf_fixed_t0.py and run it in CI (#101)
- **PR #102**: signoff: bump grader klt pin 0.6.0 -> 0.7.0 to match the layout flow (#100)
- **PR #99**: sim: validate committed-DUT variant reports and summarize ratified-row coverage
- **PR #98**: ci: run vendored-model provenance check in signoff workflow
- **PR #96**: Consolidate duplicated RF helpers in the core-envelope postprocessors
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

