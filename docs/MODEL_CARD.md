# Model card

## Status: Phase 0, A, B (packed bed only), and C (MVP scope) built

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
- Five real, solved, verified cases, Phase A's own exit criterion (three
  technologies, both process temperatures, minus the one combination noted
  below as deliberately not run): packed-bed, molten-salt, and PCM sensible/
  latent storage, at 300 C and 400 C, flat load, full 8,760-hour horizon each.
  `outputs/<case_name>/` carries each one's config, hourly schedule, and a
  manifest with solver status and every verification check's pass/fail. All
  five terminate optimal with every check passing; the cost ranking
  (packed bed cheapest, PCM most expensive) tracks the CAPEX ranking in
  docs/DATA.md, the expected sanity check for a purely economic model at this
  stage. See README's Phase A results table for the numbers.
- **A documented, checked limitation**: the 300 C and 400 C result for a given
  technology is numerically identical in Phase A, because `dispatch.py` never
  reads `delivery_temperature_c`, `medium`, or
  `storage.temperature_max_c`/`min_c` itself. Phase A's storage block is a
  temperature-agnostic MWh reservoir, by construction;
  `tests/test_dispatch.py::test_process_temperature_has_no_effect_on_phase_a_result`
  checks this explicitly. Phase C's SOC-dependent mode still does not read
  those config fields inside `dispatch.py` either; process temperature enters
  the *pipeline* only through the externally-fitted discharge curve
  (`discharge_curve.fit_piecewise_discharge_curve`'s own
  `process_temperature_c` argument), not through the LP itself. The
  limitation this bullet originally described (Phase A alone has no
  temperature-awareness at all) is still exactly true; the pipeline as a
  whole now does, but only via that one external argument.

- **Phase B, packed bed only**: a one-dimensional two-phase (solid/fluid)
  packed-bed thermocline discharge model (Schumann 1929; docs/DATA.md),
  authored twice per the build spec's B1/B3: a pure-Python shadow twin
  (`src/tes_screen/packed_bed_dynamics.py`, backward-Euler time-stepping, a
  closed-form forward sweep at each step) and a Modelica model of the
  identical continuous governing equations
  (`modelica/tes_screen/package.mo`). Discharge curves (state of charge vs.
  deliverable power above the process temperature) at three draw rates are
  generated and committed with their generating config
  (`outputs/packed_bed_dynamics/`, `scripts/run_packed_bed_dynamics.py`).
  The heat transfer coefficient is derived from the Wakao-Kaguei correlation
  (docs/DATA.md) rather than assumed as a bare number.
- **Three analytic checks (B4), all passing**: zero draw rate holds the
  outlet at the initial temperature exactly; a single-node bed with h_v to
  infinity matches the closed-form well-mixed-tank exponential response to
  1e-3 relative / 1e-2 C absolute; cumulative outlet energy equals the bed's
  own stored-energy loss to 1e-9 relative (near machine precision), checked
  at every timestep. `tests/test_packed_bed_dynamics.py`.
- An FMU export adapter (`src/tes_screen/fmu.py`), ported from OpenSteamOpt's
  `find_omc()` pattern, and `tests/test_modelica_contract.py`, a
  toolchain-independent static check on the authored Modelica source (same
  pattern OpenSteamOpt's own `test_modelica_contract.py` uses).
- **Phase C, MVP scope**: the piecewise-linear discharge-curve construction
  (`src/tes_screen/discharge_curve.py`, C1) and the SOC-dependent dispatch LP
  (`dispatch.py`'s `soc_dependent` mode), run as a paired comparison against
  the constant-limit baseline for one case: packed bed, 300 C, flat load
  (`scripts/run_phase_c_experiment.py`, `outputs/phase_c_packed_bed_300c_flat/`).
  Both runs terminate optimal with every verification check passing. The
  finding: the SOC-dependent limit increases annualised cost by 0.22% and
  required power capacity by 75% for this case, while storage energy capacity
  falls by 8.3%. See README's Phase C section for the full table. The
  piecewise construction's safety (it must never let the LP claim more
  deliverable power than the discharge curve shows is achievable) is checked
  against the underlying curve data, not assumed from the construction alone;
  the result was also confirmed stable across 3, 5, 8, and 12 segments (C1's
  own robustness instruction), with sized capacity and power identical at
  every count tested.

## What does not exist yet

- **The FMU-vs-shadow-twin cross-check.** No OpenModelica toolchain (`omc`)
  or `fmpy` is installed in this working environment, so the Modelica model
  has been authored but never compiled, and this project's intended
  strongest verification story (the build spec's own words) has not been
  run. `fmu.py` fails loudly and specifically when the toolchain is absent
  rather than silently skipping.
- Molten-salt and PCM dynamic sub-models: not started. Packed bed is the
  technology the project's hypothesis expects to show the largest effect
  from the SOC-dependent correction, so it was prioritised alone rather than
  leaving three unfinished.
- **The full 18-run technology-ranking matrix** (3 technologies x 2 process
  temperatures x 3 load profiles, both discharge-limit formulations): not
  started. Only packed bed has a Phase B dynamic sub-model, so there is no
  second technology to rank against yet; "does the ranking change" is not
  answerable from the one MVP case run so far.
- PCM at 400 C: no common nitrate-salt PCM composition was found in this
  session's research with a melting point usefully close to 400 C, so that
  combination is left undone rather than forced (docs/DATA.md, README).
- Runs for the two-shift and seasonal load profiles: built
  (`synthetic_profiles.py`) but only the flat profile has been run so far.
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

Verified, not validated, and the distinction matters: the dispatch model's
energy balance, storage identity, terminal condition, and objective have each
been independently recomputed from the solved output and checked against the
solver's own reported numbers (`verification.py`), for both the constant and
SOC-dependent formulations, and that check is run on every solve, not only
once. The Phase B packed-bed shadow twin is checked against three closed-form
analytic limits, not against a compiled FMU (no OpenModelica toolchain here)
and not against any measurement. The Phase C piecewise discharge-curve
construction is checked for safety (it must never claim more deliverable
power than the underlying curve shows) against that same curve's own data,
and the paired-run finding is checked for stability across four different
segment counts. None of that is validation. Nothing in this repository has
been checked against measured data from a real storage installation, and the
current inputs (load profile, electricity price) are declared synthetic, not
measurements of any real site or market.
