# Model card

## Status: Phase 0 (scaffold and contracts)

No storage or dispatch model exists in this repository yet. This card documents
what is actually built at this commit, not what the project intends to build. It
will be rewritten section by section as each phase lands, per the rule that
documentation ships in the same commit as the capability it describes.

## What exists today

- A case config schema (`src/tes_screen/config.py`) with five required sections
  (`process`, `storage`, `supply`, `economics`, `optimization`) and per-field
  validation. It has no connection to any solver; it only defines and checks the
  shape of a case.
- A profile contract (`src/tes_screen/profiles.py`) for hourly CSV inputs: required
  columns, consecutive zero-based hours, finite values, a sign contract. It does not
  yet load any real data source.
- A provenance record module (`src/tes_screen/provenance.py`) for recording source,
  checksum, and calendar completeness of an input series. Nothing in the repository
  calls it against a real dataset yet.

## What does not exist yet

- Any storage physics, dynamic or quasi-steady.
- Any optimisation model, LP or otherwise.
- Any economic calculation.
- Any use of real electricity price or load data.
- Any result of any kind.

## Intended eventual scope, once later phases land

A screening comparison of thermal storage technologies (two-tank molten salt,
packed-bed sensible, high-temperature PCM) for industrial process heat, testing
whether a state-of-charge-dependent discharge limit (derived from a verified
dynamic sub-model) changes sizing or ranking conclusions relative to the constant
discharge limit almost every annual techno-economic model uses. See the project
README for the full framing.

## Validation status

Not applicable yet: there is no model to validate or fail to validate. Once a model
exists, this section will state plainly that it is verified against its own
physics, analytic limits, and independent hand calculations, and that it has not
been validated against measured data from a real storage installation.
