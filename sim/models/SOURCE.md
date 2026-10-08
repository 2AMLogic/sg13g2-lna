# sim/models/ -- provenance of vendored model files

## sg13g2_inductor_em.spice

| Field | Value |
|---|---|
| Source repository | `2AMLogic/sg13g2-vco` |
| Source path | `sim/inductor-model/sg13g2_inductor_em.spice` |
| Source commit (full sha) | `7278463b26344e9fdbcb2d7683cd3a1739d0bf6f` (2026-09-10, "sim: EM-extract the SG13G2 spiral-inductor PCell with openEMS and fit ...") |
| File sha256 | `6f24f9857ab7810c91bda5f6307e78f1dfcbe2afd750bb023e28156ded06d6a0` |
| File size | 8687 bytes |
| License | Apache-2.0 (SPDX header inside the file) |
| Fetched | 2026-10-08, `gh api -H 'Accept: application/vnd.github.raw' 'repos/2AMLogic/sg13g2-vco/contents/sim/inductor-model/sg13g2_inductor_em.spice?ref=7278463b26344e9fdbcb2d7683cd3a1739d0bf6f'` |

**The master lives in `sg13g2-vco`. This copy is a byte-identical stamp and is
NOT to be edited here.** If the model needs to change, change it in
`sg13g2-vco`, then re-stamp: fetch the new file at a pinned commit, replace the
copy, and update the three provenance rows above in the same commit.

Integrity check (exits 0 when the copy still matches the sha256 above, non-zero
otherwise):

    sim/models/check_sources.sh

The script reads the recorded sha256 out of this file, so the table above is
the single source of truth.

### What the model is, and what it is not (restated from the file's own header)

1. Not an EM lookup table for arbitrary geometry: three geometries were
   extracted (1, 4 and 5 turns); elsewhere it is an EM-corrected analytic
   model and the correction is an unvalidated extrapolation.
2. Not a PVT extraction: one process point (typical metal and substrate
   conductivity) and one temperature. All corner and temperature dependence
   is inherited from the analytic model's `mc_rsh`, `mc_rsub` and `tc1`
   scaling -- an EM level with analytic scaling, not an EM corner.
3. Not silicon: no measured device backs any of it.

Method, mesh/boundary convergence and accuracy limits are in
`sg13g2-vco`: `sim/inductor-model/em-extraction/README.md` (at the commit above
or later).
