# 0000: <short title>

<!--
Copy this file to spec/decision-records/NNNN-<slug>.md and fill it in.
Use the next unused NNNN (zero-padded 4 digits). One decision per record.
A decision record is required for every spec change (see CLAUDE.md: "Spec
changes go through spec/ with a decision record"). Do not delete or rewrite
a ratified record — supersede it with a new one.

Numbering rule: before picking NNNN, check every filename already in this
directory on `main` (including superseded records) and use one greater than
the highest number found — never guess or reuse a number, and re-check if
another record may have landed concurrently, to avoid a collision.

Convention note: this repo uses sg13g2-bandgap's / gf180-bandgap's
`NNNN-<slug>.md` numbering (sky130-bandgap instead uses `DR-NNN-<slug>.md`).
Either sibling convention was acceptable; this one was picked for this repo
in record 0001 because it matches the nearest sibling on the same PDK.
Nothing about the choice is load-bearing, but keep it consistent from here.

Status vocabulary, and what a record may and may not do:

- `proposed`  — the record states a recommendation and its evidence. It does
                NOT ratify any row of `spec/target-spec.md`.
- `ratified`  — this fleet ratifies target-spec rows through a two-key
                (EE-key + market-key) protocol: a builder drafts the
                ratification as a separate PR on the evidence, and key-holder
                approval is the ratification act. A `proposed` record becomes
                the *basis* of such a PR; it never ratifies itself.
- `superseded by NNNN` — replaced; the text is kept unchanged (append-only).
-->

- **Status**: proposed | ratified | superseded by NNNN
- **Date**: YYYY-MM-DD
- **Decided by**: <name / role>
- **Issue**: #N

## Context

What forced this decision? One short paragraph: the constraint, the
measurement, or the conflict that made the current spec inadequate. Link to
the issue, the simulation evidence in `sim/`, or the prior record it revises.

## Decision

The decision, stated as a change to the spec — the parameter and its new
value, or the approach now recommended. Be specific enough that design work
can lock to it without further interpretation.

## Evidence

Per `CLAUDE.md` ("no claim without a testbench"), cite the specific
`sim/<experiment>/records/` rows — record id, corner, temperature, bias
point — that each number rests on, not just the literature. Say plainly
where a number is *not* backed by a committed testbench.

## Alternatives considered

- **<alternative>** — why it was not chosen.
- **<alternative>** — why it was not chosen.

## Consequences

What follows from this: what becomes possible, what becomes harder, which
testbenches or corner sets change, what work is invalidated or must be
re-run. Include the bad consequences, not just the good ones.
