# manifests/artifacts

New raw simulation and signoff outputs live in the artifact store, not in git
(issue #222). Git keeps only a manifest naming each stored object by sha256.

## Layout

For a run of bench `<bench>` with record id `<run-id>`:

- `<bench>-<run-id>.manifest.json`: a `klt artifact` manifest
  (`schema_version` 1). Every entry's `uri` is `artifact:<key>`, a logical name
  only the artifact broker resolves. No bucket, endpoint or credential is ever
  written here.
- `<bench>-<run-id>.summary.md`: name, size and sha256 per object, for review.

Manifests are append-only like `sim/` evidence: a run id is never reused and a
committed manifest is never edited.

## Writing (fleet worker only)

`sim/env.sh` provides `sim_artifact_put <bench> <file>...`, which stages the
files in the git-ignored `sim/artifact-scratch/`, calls
`sim/tools/artifact_store.py put` (which runs `klt artifact put`) and, on
success only, writes the two files above and removes the originals. First
adopter: `SIM_ARTIFACT_STORE=1 sim/lna-matching-feasibility/run_dc_reference_study.sh`.

## Fail closed

The writer exits nonzero and writes nothing under `manifests/` if
`$KLT_ARTIFACT_BROKER` is unset, `klt` is missing or has no `artifact put`, or
the broker is unreachable or refuses. There is no local fallback and no
committing the raw bytes instead. Writing needs a klt with `artifact` (fleet
workers have one); the repo's pinned grader klt (`0.7.0`) is unchanged.

## Reading and checking

- `klt artifact verify manifests/artifacts/<bench>-<run-id>.manifest.json`
  re-hashes every object from the store (needs `$KLT_ARTIFACT_BROKER`).
- CI (`artifact-manifests` job, `.github/scripts/check-artifact-manifests.py`)
  validates the schema, accepts only `artifact:` URIs, rejects storage-location
  URIs, and fails if a stored object's sha256 matches any committed file.

Existing evidence under `sim/*/records`, `corners` and `netlist-snapshots` is
untouched; the envelope and breakdown replay jobs still read it from git.
