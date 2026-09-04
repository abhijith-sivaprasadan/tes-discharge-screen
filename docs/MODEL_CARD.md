# Model card

## Status: Phase 0, A, B (packed bed only), P0.3 (state-sufficiency test), C (MVP scope, archived), C2 (matched-duration fix), P0.4 (start-of-hour capability fix), and P0.5 (MILP cycling prevention) built

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
  deliverable power) at three draw rates are generated and committed with
  their generating config (`outputs/packed_bed_dynamics/`,
  `scripts/run_packed_bed_dynamics.py`). The heat transfer coefficient is
  derived from the Wakao-Kaguei correlation (docs/DATA.md) rather than
  assumed as a bare number.
- **Temperature semantics fix (roadmap P0.2).** `discharge_power_curve`
  (`packed_bed_dynamics.py`) separates `T_process`, `delta_T_min_hot_side`
  (`0.0` throughout, [assumption]; docs/DATA.md), and `T_return`
  (`simulate_discharge`'s own `inlet_temperature_c`, an explicit input,
  never derived from `T_process`). Net storage heat is now referenced to
  T_return -- the same reference the bed's own stored-energy accounting
  uses -- with a quality gate (`deliverable_power_mw`, zero below
  `T_process + delta_T_min_hot_side`) applied on top, rather than computing
  deliverable power directly against T_process while stored energy used
  T_return. Before this fix, whenever the two references differed, enthalpy
  already present in the return stream was counted as if storage had
  supplied it. Checked, not assumed: a fully depleted bed now reports
  exactly zero net storage heat, low-grade heat below the quality gate is
  distinguished from heat that is genuinely gone, and the integral of net
  storage heat over time reproduces the bed's own stored-energy drop
  (`tests/test_packed_bed_dynamics.py`'s P0.2 test block).
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
- **P0.3, the state-sufficiency experiment.** `src/tes_screen/state_sufficiency.py`
  constructs temperature fields at matched total stored energy but different
  spatial structure (uniform, a sharp step with the hot block at the inlet,
  its mirror image with the hot block at the outlet, and a broad linear
  ramp), verified to hit their target energy fraction via
  `packed_bed_dynamics.bed_stored_energy_j` (factored out of
  `simulate_discharge`'s own internal energy accounting so both use exactly
  the same physics). `simulate_discharge` itself now accepts either a
  scalar (uniform, every existing call site) or a per-node array initial
  temperature field. `scripts/run_state_sufficiency_experiment.py` discharges
  each constructed field briefly (30 min, three energy fractions) and reads
  deliverable power off several short-term checkpoints
  (`outputs/state_sufficiency/`). **Finding: scalar SOC is not sufficient**
  -- deliverable power at matched total energy scatters by up to 220%
  (115% even restricted to states reachable by discharging alone) across
  the profile family, against a 5% [assumption] threshold for "adequate."
  Reported as a real, structural limitation, not hidden or rounded away, per
  the roadmap's own instruction. Phase B's discharge curve is documented
  from here on as a **trajectory-derived SOC capability curve** (accurate
  along the one bed-state history it was built from), not a validated
  general `Pmax(SOC)` law; this does not invalidate Phase C/C2 below, which
  both use exactly that one trajectory, consistently. See README's P0.3
  section for the full physical explanation and numbers.
- **Phase C, MVP scope (archived; superseded by C2 below).** The
  piecewise-linear discharge-curve construction (`src/tes_screen/discharge_curve.py`,
  C1) and the SOC-dependent dispatch LP (`dispatch.py`'s `soc_dependent`
  mode), run as a paired comparison against the constant-limit baseline for
  one case: packed bed, 300 C, flat load (`scripts/run_phase_c_experiment.py`,
  `outputs/phase_c_packed_bed_300c_flat/`). Both runs terminate optimal with
  every verification check passing, and the piecewise construction's safety
  (it must never let the LP claim more deliverable power than the discharge
  curve shows is achievable) was checked against the underlying curve data
  and confirmed stable across 3, 5, 8, and 12 segments. **The original
  finding is withdrawn as a shape-isolated comparison**: reading the run's
  own manifest, the constant-limit run solved to a 7.41h store (54.99 MWh /
  7.42 MW) and the SOC-dependent run to a 3.88h store (50.43 MWh / 12.98
  MW) -- the two formulations had unequal sizing degrees of freedom, so the
  reported +0.22% cost / +75% power delta conflated the discharge-limit
  shape with a duration mismatch neither run controlled for. Data kept,
  unmodified, as an archived record; see Phase C2.
- **Phase C2, matched-duration-family sizing fix (roadmap P0.1).** Adds
  `storage.design_duration_hours` to the case config (`config.py`), a
  `duration_matched` sizing branch in `dispatch.py` that ties power to
  `E_cap / tau` identically in both formulations (removing Phase C's
  unequal-DOF confound), and `discharge_curve.mass_flow_for_target_duration`,
  which solves in closed form for the discharge mass flow whose own
  reference power/energy ratio equals `1/tau`, so each swept duration gets a
  curve genuinely refit at that duration rather than one curve rescaled
  after the fact. `dispatch.py` checks this equality at model-build time and
  raises rather than silently accepting a mismatched curve.
  `scripts/run_phase_c2_duration_matched_experiment.py` sweeps five design
  durations (2h-12h), all ten runs (five durations x two formulations)
  terminate optimal with every verification check passing
  (`outputs/phase_c2_duration_matched/`). This run also incorporates P0.2's
  temperature-reference fix and P0.4's start-of-hour discharge-capability
  fix (both below), re-run against the corrected `dispatch.py`/
  `discharge_power_curve` and superseding this same script's earlier
  (P0.1-only, then P0.1+P0.2-only) output. **The corrected finding**: the
  shape-isolated cost delta is +0.000% to +0.038% across the sweep --
  indistinguishable from the constant-limit baseline to solver tolerance at
  the two shortest durations -- against Phase C's original (confounded,
  mis-referenced, over-conservative) +0.22%. See README's Phase C2 section
  for the full sweep table.
- **P0.4, start-of-hour discharge capability.** `dispatch.py`'s piecewise
  discharge-capability constraint bound `p_dis[t]` using `level[t]`, the
  *post*-dispatch state `storage_balance` defines in terms of that same
  hour's own `p_dis[t]` -- backwards, since capability at the start of an
  hour should depend on what was on hand before that hour's own discharge
  drew it down. Fixed by reading `level_start[t]` (the same pre-dispatch
  "previous" term `storage_balance` already computed, factored out and
  shared) instead, gated behind a new required config field,
  `storage.discharge_capability_reference` (`"start_of_hour"` or
  `"end_of_hour"`, validated in `config.py` and re-checked defensively in
  `build_model` itself since it is called directly by tests/scripts too,
  not only via `load_config`). Both modes remain fully supported; neither
  silently replaces the other. Quantified per the roadmap's own acceptance
  criterion: at a short 72h, nearly-free-storage case,
  `discharge_capability_reference` moves the SOC-dependent formulation's
  required power from 10.38 MW (`end_of_hour`) to 9.60 MW (`start_of_hour`)
  -- enough to flip which formulation needs more power than the
  constant-limit baseline's own 10.0 MW outright
  (`tests/test_dispatch.py`'s P0.4 test block). Also required switching
  `solve_dispatch`'s HiGHS solver option to the interior-point method: the
  corrected, less self-damped formulation was numerically harder for
  HiGHS's default simplex on some duration-matched curve shapes (a couple
  of durations near tau=8h failed to find a feasible solution within the
  configured time limit, not because they were infeasible), and IPM
  resolves it, confirmed to reproduce identical objective values on every
  already-passing case. See README's P0.4 section for the full mechanism.
- **P0.5, MILP simultaneous-cycling prevention.** A pure LP with
  independent nonnegative `p_ch[t]`/`p_dis[t]` can exploit negative
  electricity prices by charging and discharging simultaneously in the same
  hour -- draw heater electricity purely for the negative-price payment,
  discharge to make room for it in that hour's heat balance, charge back up
  beyond `c_charge_limit` alone -- physically meaningless, and real ENTSO-E
  data (not yet fetched here) does go negative. Reproduced directly, not
  just theorised: a generously-sized case with a deep negative-price window
  shows 5 hours of material simultaneous charge (at its 20 MW limit) and
  discharge (13-18 MW), the store pinned at full capacity throughout.
  `storage.cycling_prevention_mode` (`"none"` or `"milp_binary"`, new
  required field) adds a per-hour binary `z[t]` with
  `p_ch[t] <= charge_power_bound_mw * z[t]` and
  `p_dis[t] <= discharge_power_bound_mw * (1 - z[t])` when enabled --
  the roadmap's own preferred option, since the target KTH project values
  MILP formulations. `charge_power_bound_mw`/`discharge_power_bound_mw` are
  genuine numeric constants (built from the same bounds already declared
  for `E_cap`/`P_rated`'s own domains), not the `p_ch_max`/`p_dis_max`
  expressions themselves, which are often Pyomo expressions in a sizing
  variable and would make the big-M term nonlinear (Var times Var) if used
  directly. In the reproducing case, `milp_binary` shows zero hours of
  simultaneous cycling, still terminates optimal, passes every
  verification check, and its total cost is provably never lower than the
  LP's own (a strict restriction of the LP's feasible region) -- confirmed
  measurably higher here, showing the LP's cheaper answer was exactly the
  pathology's value. The original LP mode (`"none"`) is unchanged and
  remains every existing case's default. See README's P0.5 section for the
  full numbers.

## Scaling law

The dispatch LP rescales one reference bed's fitted discharge curve to
whatever storage energy capacity a case actually sizes, linearly
(`p_dis[t] <= a_i*level[t] + b_i*E_cap`) -- which implicitly assumes the
*normalized* curve (state of charge vs. fraction of full-charge power) has
the same shape at any capacity, not just the one the reference bed happens
to be. Before P1, that rested on an abstract "same duration ratio"
argument with no stated physical mechanism for why it should hold.

`src/tes_screen/packed_bed_dynamics.py`'s `scale_parallel_bed` gives it
one, per roadmap P1.1's "modular area scaling" family: cross-sectional
area and mass flow scale together by the same factor; bed length, particle
diameter, porosity, material properties, and node count all stay fixed.
Under this specific family, mass flux `G = m_dot/A` -- and therefore
Reynolds number, the Wakao-Kaguei Nusselt number, the volumetric heat
transfer coefficient, and every coefficient in `simulate_discharge`'s
governing PDE, none of which reference area directly -- stays exactly
fixed, not merely approximately. The simulated fluid/solid temperature
field is therefore identical at every scale factor; only the *totals*
built from it (stored energy, deliverable power) scale with area, and a
normalized curve -- a ratio of two equally-scaled quantities -- should
collapse onto the reference exactly.

**Checked, not assumed** (`scripts/run_scaling_law_experiment.py`,
`tests/test_scaling_law.py`, `outputs/scaling_law/`): swept across five
scale factors (0.25x, 0.5x, 1x, 2x, 4x of the default reference bed's
10 m² cross-section), the maximum deviation between each scaled run's
normalized curve and the reference run's -- in both state of charge and
power fraction, at every recorded timestep -- is **exactly 0.0**, not just
below the [assumption] 1e-6 threshold set to catch a real breakdown of the
family. The fitted curve's own `k = P_reference/E_reference` ratio (what
`dispatch.py`'s `duration_matched` branch actually checks a curve against)
is likewise identical to machine precision across all five scale factors.
**Exit criterion met: the modular-area-scaling approximation is supported**,
not merely asserted -- this is the specific, defensible geometric family
the roadmap asked for, replacing the earlier abstract assumption, with the
invariance proven exact for this bed model rather than approximately
small.

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
- **Explicit heat-exchanger modelling.** `delta_T_min_hot_side` (P0.2) is
  carried as an explicit parameter but set to `0.0` everywhere in this
  repository ([assumption]; docs/DATA.md); a real HX approach-temperature
  model, if added, would replace that placeholder rather than the
  parameter itself.
- PCM at 400 C: no common nitrate-salt PCM composition was found in this
  session's research with a melting point usefully close to 400 C, so that
  combination is left undone rather than forced (docs/DATA.md, README).
- Runs for the two-shift and seasonal load profiles: built
  (`synthetic_profiles.py`) but only the flat profile has been run so far.
- A live ENTSO-E price fetch.
- Sensitivity analysis, the boundary-harmonisation table, or the
  technology-selection map (Phase D).
- **A reduced-order state beyond scalar SOC.** P0.3 found scalar SOC
  insufficient but did not build a replacement (e.g. thermocline position/
  front width, or a useful-energy-weighted SOC, as the roadmap itself
  suggests); the annual dispatch LP still uses the scalar-SOC piecewise
  curve, now with that limitation documented rather than resolved.
- **The fifth state-sufficiency profile family** (states drawn from
  realistic charge/discharge histories): needs a charging dynamic model,
  which this project does not have (Phase B is discharge-only).

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
and not against any measurement. The Phase C/C2 piecewise discharge-curve
construction is checked for safety (it must never claim more deliverable
power than the underlying curve shows) against that same curve's own data
at every design duration swept in C2, and Phase C's original paired-run
finding was checked for stability across four different segment counts
before its own confound (unequal sizing degrees of freedom between the two
formulations) was found and corrected in C2. P0.3 goes a step further than
verifying the curve's own construction: it checks whether the curve's
underlying premise (that total energy determines outlet capability) holds
at all outside the one trajectory it was fit from, and finds that it does
not -- a limitation surfaced by testing, not assumed away. None of that is
validation. Nothing in this repository has been checked against measured
data from a real storage installation, and the current inputs (load
profile, electricity price) are declared synthetic, not measurements of any
real site or market.
