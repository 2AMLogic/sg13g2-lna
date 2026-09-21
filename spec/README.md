# spec

Target specification and decision records. Spec changes require a decision
record — per `CLAUDE.md`, agents do not relax the ratified spec to make
results pass.

```
spec/
  README.md               this file
  target-spec.md           per-corner target-spec table (band, gain,
                            NF, S11/S22, stability, IIP3, supply/power) —
                            rows ratified by decision record 0002 (issue
                            #19); the IIP3 numeric target and the former
                            stretch columns are explicitly unratified
                            (see the table). See the top-level README's
                            "Target specification" section for the short
                            pointer
  porting-plan.md           what carries over from the SG13G2-deck siblings
                            (sg13g2-bandgap, sg13g2-pll, sg13g2-ldo) and
                            what is genuinely novel RF work with no fleet
                            precedent
  decision-records/         one decision per record, numbered sequentially,
                            append-only (create this directory when the
                            first record is ready to write — copy a
                            TEMPLATE.md from a sibling repo such as
                            sg13g2-bandgap/spec/decision-records/ to start
                            it)
```

See [`target-spec.md`](target-spec.md) for the target table (rows ratified
by decision record 0002, issue #19; the IIP3 numeric target and the former
stretch columns restated DRAFT/unratified as marked there) and the 50 Ω
port convention it states explicitly, and
[`porting-plan.md`](porting-plan.md) for the nearest-sibling analysis and
the open tooling questions gating design work (`porting-plan.md` remains
engineering-input; the topology question it carried is resolved by
decision record 0001). A value or
decision becomes settled only when a decision record in
`decision-records/` says so; a record is never deleted or rewritten once
ratified — a later change supersedes it with a new record rather than
editing history in place (same append-only convention as `sim/`, see
[`sim/README.md`](../sim/README.md)).
