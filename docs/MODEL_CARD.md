# Model card

## Status: Phase 0 (scaffold) and Phase A (annual quasi-steady core) built

This card documents what is actually built at this commit, not what the project
intends to build. It will be rewritten section by section as each phase lands,
per the rule that documentation ships in the same commit as the capability it
describes.

## What exists today

- A case config schema (`src/tes_screen/config.py`), five required sections
  (`process`, `storage`, `supply`, `economics`, `optimization`) with per-field
  validation.
- A profile contract (`src/tes_screen/profiles.py`): required columns,
  consecutive zero-based hours, finite values, a sign contract.
- A provenance record module (`src/tes_screen/provenance.py`): source,
  checksum, calendar completeness, for whenever a real fetched dataset is
  recorded.
- Synthetic profile generators (`src/tes_screen/synthetic_profiles.py`): three
  load shapes (flat, two-shift, seasonal) and a daily-cycle electricity price
  series. Every profile they produce is explicitly synthetic; see docs/DATA.md.
- An electricity price module (`src/tes_screen/electricity_price.py`): a real
  ENTSO-E day-ahead fetch path, ported from PyNEXUS, gated behind an
  `ENTSOE_API_KEY` that is not configured in this working environment, so it
  has never been exercised against live data. `supply.electricity_price_source:
  synthetic` is what every run so far actually uses.
- **The Phase A annual dispatch LP** (`src/tes_screen/dispatch.py`): a generic
  storage block (level, charge, discharge, standing loss, terminal condition)
  serving a process heat load from an electric heater and a fossil backup
  boiler, with storage energy capacity and power rating as solver decision
  variables, HiGHS via Pyomo. The storage discharge limit is **constant**: this
  is the baseline the project exists to test against, not the corrected model.
- Independent verification (`src/tes_screen/verification.py`): energy-balance
  closure, an independently-recomputed storage-balance identity, the terminal
  condition actually binding when forced to, and an independent objective
  reconstruction, all checked against the raw extracted solution rather than
  against Pyomo's own internal expressions.
- One real, solved, verified case: packed-bed sensible storage, 300 C steam
  process, flat load, full 8,760-hour horizon. `outputs/packed_bed_300c_flat/`
  carries its config, hourly schedule, and a manifest with solver status and
  every verification check's pass/fail. Molten-salt and PCM configs exist with
  literature-cited parameters but have not been run.

## What does not exist yet

- The targeted dynamic sub-model (Phase B): no Modelica model, no FMU export,
  no shadow twin.
- The state-of-charge-dependent discharge limit (Phase C): the whole reason
  this project exists. Nothing has been compared against the constant-limit
  baseline yet, so there is no finding, null or otherwise, to report.
- Runs for molten salt, PCM, the two-shift and seasonal load profiles, or the
  400 C process temperature.
- A live ENTSO-E price fetch.
- Sensitivity analysis, the boundary-harmonisation table, or the
  technology-selection map (Phase D).

## Intended eventual scope, once later phases land

A screening comparison of thermal storage technologies (two-tank molten salt,
packed-bed sensible, high-temperature PCM) for industrial process heat, testing
whether a state-of-charge-dependent discharge limit (derived from a verified
dynamic sub-model) changes sizing or ranking conclusions relative to the constant
discharge limit almost every annual techno-economic model uses. See the project
README for the full framing.

## Validation status

Verified, not validated, and the distinction matters: the Phase A model's
energy balance, storage identity, terminal condition, and objective have each
been independently recomputed from the solved output and checked against the
solver's own reported numbers (`verification.py`), and that check is run on
every solve, not only once. None of that is validation. Nothing in this
repository has been checked against measured data from a real storage
installation, and the current inputs (load profile, electricity price) are
declared synthetic, not measurements of any real site or market.
