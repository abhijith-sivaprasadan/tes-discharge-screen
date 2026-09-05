# Model card

## Status: Phase 0, A, B (packed bed with full verification; molten salt and PCM with closed-form sub-models only), P0.3 (state-sufficiency test), C (MVP scope, archived), C2 (matched-duration fix, packed bed only), P0.4 (start-of-hour capability fix), P0.5 (MILP cycling prevention), C3 (full technology-ranking matrix), P2.1 (duration-family capability curves), P3.1-P3.3 (discretisation convergence, correlation-domain checks, Ergun pressure drop/blower power), P5 (economics sensitivity), P6 (model-fidelity decision map), and Phase D (boundary harmonisation table, Morris global sensitivity screening, technology-selection map) built; P4 (FMU/Modelica verification): model compiled and cross-check script built, but not yet run against the real FMU -- blocked by this environment's platform/network constraints, not by the model or the comparison method

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
- **Molten-salt and PCM dynamic sub-models (`src/tes_screen/molten_salt_dynamics.py`,
  `src/tes_screen/pcm_dynamics.py`).** Closed-form, not time-stepped PDEs
  like the packed bed: a two-tank molten salt store's outlet temperature is
  exactly the hot-tank temperature for as long as any usable inventory
  remains (no thermocline mechanism exists in a two-tank system), so
  discharge capability declining near depletion is modelled as a flow
  taper across a small `heel_fraction` ([assumption]) rather than a
  temperature one; a PCM store discharges through three physically real
  regimes (superheat sensible, latent, subcooled sensible), each a simple
  closed-form energy balance. Both share the packed bed's own piecewise-fit
  contract (`(state_of_charge, deliverable_power_mw)` in, a
  `PiecewiseDischargeCurve` out) via `discharge_curve.py`'s
  now-technology-agnostic `fit_piecewise_curve_from_power_curve`/
  `verify_piecewise_curve_against_power_curve` (factored out of the
  packed-bed-specific wrappers, verified non-breaking by the full existing
  test suite before either new module was written). Because these models
  are closed-form rather than discretized, their own tests
  (`tests/test_molten_salt_dynamics.py`, `tests/test_pcm_dynamics.py`, 25
  tests total) check that the implementation matches its own specified
  physics (outlet temperature holds exactly at the hot-tank/melting-point
  value where the physics says it should, mass flow solved for a target
  duration reproduces that duration to `1e-9` relative, and so on) rather
  than checking numerical accuracy against an independent analytic limit
  the way the packed bed's B4 checks do -- **neither has a Modelica twin or
  an FMU cross-check**, a real, stated difference in verification depth
  from Phase B's own packed-bed treatment, not an oversight. PCM's
  piecewise fit is worth a specific note: its three-regime curve is not
  globally concave (a convex corner where the flat latent plateau meets the
  rising superheat ramp), so the fit's usual "exact for a concave curve"
  safety argument does not apply on its own; verified empirically instead
  (`test_piecewise_fit_safety_is_checked_not_assumed`, swept over 3-30
  segments) that the construction's actual mechanism -- taking the minimum
  over every segment's own secant line extended across the whole domain,
  not just the nominally containing one -- still gives exactly 0.0
  overestimate, and the module docstring/test comment explain why.
- **Phase C3, the full technology-ranking matrix
  (`scripts/run_phase_c_full_matrix_experiment.py`,
  `outputs/phase_c_full_matrix/`).** The comparison C2 could not run (only
  packed bed had a Phase B dynamic sub-model): every technology x every
  process temperature it is configured for x every synthetic load profile,
  at the same matched `design_duration_hours = 6h` and the same P0.2/P0.4
  corrections C2 established. 5 valid technology/temperature combinations
  (packed bed and molten salt at 300 C and 400 C; PCM only at 300 C, no
  suitable high-temperature nitrate-salt PCM composition found) x 3
  profiles (`flat`, `two_shift`, `seasonal`) = 15 paired cases, 30 solves,
  all `optimal` and independently verified. **Finding, stated plainly: the
  SOC-dependent correction never changes which technology is cheapest** --
  packed bed remains cheapest in all 6 (temperature, profile) groups under
  both formulations, with a total-cost delta of at most +0.031% anywhere in
  the matrix. Molten salt's own delta is smaller than packed bed's at every
  matched pair (e.g. +0.006% vs. +0.020% at 300 C flat), consistent with
  this project's own control-case hypothesis. **PCM's delta is exactly
  0.000% in every case, but this is a sizing artifact, not evidence its
  discharge shape is inconsequential**: the optimiser builds exactly zero
  PCM storage capacity at this design duration, under both formulations, in
  every profile -- PCM's combined capex (80,000 EUR/MWh-th +
  40,000 EUR/MW) is far above packed bed's or molten salt's, so it is
  cheaper to serve the load entirely from the heater/boiler than to build
  any PCM store at all, and the SOC-dependent constraint is therefore never
  exercised. The 300 C and 400 C rows are pairwise numerically identical
  for packed bed and for molten salt, each for its own stated,
  parameter-choice reason (identical 80 C span in both packed-bed configs;
  molten salt's fixed 565 C/290 C tank temperatures and a pass/fail quality
  gate both process temperatures clear trivially), not a bug. One
  matplotlib figure per technology (`outputs/phase_c_full_matrix/figures/`)
  overlays each curve's analytic shape, its piecewise fit, and the
  constant-limit reference. See README's Phase C3 section for the full
  15-row and 6-row tables.

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

## P2.1: duration-family capability curves

`scripts/run_capability_curves_experiment.py` commits the discharge curves
C2/C3 already build internally (to feed paired dispatch solves) as
standalone evidence in their own right: one `manifest.json` per (design
duration, case) under `outputs/capability_curves/tau_{X}h/{case_name}/`,
recording geometry, mass flow/flux, Reynolds/Prandtl/Nusselt numbers, the
volumetric heat transfer coefficient (`flow_diagnostics`, a new function
factoring these out of `volumetric_heat_transfer_coefficient`'s own
Wakao-Kaguei correlation -- non-breaking, `volumetric_heat_transfer_coefficient`
is now a thin wrapper over it), temperatures, resolution, the process
quality threshold, and an explicit scaling-family definition, alongside the
curve data and its piecewise-fit breakpoints as CSVs. **Packed bed only**
(both process-temperature cases): the roadmap's own framing of this section
is specific to the packed bed's mass-flow/thermocline trade-off; neither
molten salt (no thermocline) nor PCM (near-isothermal latent plateau)
carries that design tension. P2.2 (a full swept capability envelope) is
explicitly deferred by the roadmap itself and not attempted. Swept across
the same 2h-12h duration grid C2 uses: shorter durations draw at higher
mass flow/flux, and the piecewise fit's own safety margin against
overestimating deliverable power tightens correspondingly (2h: 6.8e-05 MW
max overestimate; 12h: 8.0e-07 MW), a real if minor pattern the per-duration
curve data surfaces that C2's own segment-count robustness check did not
previously tabulate. See README's P2.1 section for the full table.

## P3.1: spatial and temporal discretisation convergence

`scripts/run_convergence_experiment.py` sweeps `n_nodes` (20, 40, 80, 160)
and `n_steps` (500, 1000, 2000, 4000) independently against a finer
reference (`n_nodes=160, n_steps=4000`), comparing outlet-temperature
trajectory, thermocline breakthrough time (standard literature midpoint
definition, not this project's own process-quality threshold -- see the
script's own docstring for why that threshold is never crossed by any
packed-bed config in this repository), useful-energy fraction, the fitted
curve's own breakpoints, and -- the roadmap's own emphasized "strongest
metric" -- the SOC-dependent duration-matched dispatch LP's own sized
`E_cap`, power rating, and total cost. **Finding: node count dominates
discretisation error, not timestep count** (10.23 C max outlet deviation
at the coarsest spatial point vs. 1.26 C at the coarsest temporal point),
**and this project's own default resolution (`n_nodes=40`) reproduces the
fine-grid annual dispatch decision to within 0.007% total cost and 0.14
MWh sized energy capacity**, against a strict 1.0% [assumption]
convergence threshold -- despite a real ~5.7 C / ~9-10 percentage-point
local curve-shape error at that same resolution. Every prior Phase
C/C2/C3/P2.1 result, all built at this same default resolution, is
therefore confirmed to already be converged at the level that matters
(checked against a finer-resolution run, this project's own "verified"
sense, not "validated" against measured data), not merely assumed. See
README's P3.1 section for the full table.

## P3.2: correlation-domain validity checks

`flow_diagnostics` (`packed_bed_dynamics.py`) now records whether its own
Reynolds number falls inside the Wakao-Kaguei correlation's stated
validity domain (`WAKAO_KAGUEI_REYNOLDS_VALIDITY_RANGE = (15, 8500)`) and
raises a `RuntimeWarning` -- not a silent extrapolation -- when it does
not (`tests/test_packed_bed_dynamics.py`'s P3.2 block forces this with a
deliberately tiny mass flux and checks the warning fires). Every mass flow
this project's own case configs and duration sweeps actually use stays
comfortably inside the domain (Re 117-705 across the full
`outputs/capability_curves/` duration grid), recorded explicitly in each
run's own manifest rather than merely asserted.

## P3.3: Ergun pressure drop and blower parasitic power

`ergun_pressure_drop_and_blower_power` (`packed_bed_dynamics.py`) adds the
Ergun-equation pressure drop (Ergun, 1952; `docs/DATA.md`) and the blower
electric power it implies at an explicit `blower_efficiency` config field
(0.65, [assumption], `docs/DATA.md`) -- an optional, documented extension
per the roadmap's own instruction, reported in each duration's own
`outputs/capability_curves/` manifest, **not wired into `dispatch.py`'s
own economics** (every case's objective still uses
`economics.storage_capex_eur_per_mw` unchanged, so no existing committed
result changes). Blower power ranges from 0.32% of reference rated
thermal power at the longest (12h) design duration tested up to 8.64% at
the shortest (2h) -- Ergun's turbulent term scales with the square of
superficial velocity, so shorter, higher-flow designs pay a
disproportionately larger parasitic-power penalty, exactly the physical
trade-off the roadmap named as the reason to add this. Wiring it into the
dispatch LP's own objective is a natural next step, not attempted here.

## P5: economics sensitivity, not one assumed number

`scripts/run_economics_sensitivity_experiment.py`: rather than defend or
replace the single assumed `storage_capex_eur_per_mw` value
`docs/DATA.md` itself already flags as uncited, sweeps every parameter the
roadmap names for one representative case (`packed_bed_300c_flat`, flat
profile, duration-matched at tau=6h, both formulations) -- storage power
CAPEX at 0x-8x of the assumed value (P5.1), seven secondary parameters
one-at-a-time (energy CAPEX, gas price, carbon price, electric-heater
efficiency, standing loss, round-trip efficiency, price volatility, plus
process load factor via the three existing profile shapes; P5.2), and a
full cost decomposition (annualised energy/power CAPEX, electricity, fuel,
carbon) plus a binding-constraint classification at every point (P5.3).
31 sensitivity points, 62 solves, all optimal and independently verified;
every cost decomposition cross-checked to reproduce the solver's own
objective exactly, not assumed to match. **Findings**: the SOC-dependent
delta is essentially flat (+0.019% to +0.020%) across the entire 8x power-
CAPEX range, a real robustness result for the headline finding; gas price
is the single most powerful lever tested, capable of pricing storage out
of the market entirely (0.5x -- `E_cap` exactly 0, delta exactly 0.000%,
the same degenerate pattern Phase C3 found for PCM) or of tripling `E_cap`
and producing the largest delta in the study (2x -- +0.0647%) while
flipping the system to full electrification (zero backup-boiler fuel/
carbon cost); lower process load factor (peakier profiles) counter-
intuitively *increases* optimal storage size rather than decreasing it;
and the electric heater's own capacity, not the backup boiler or unmet
heat, is what binds in every single sensitivity point tested except the
one where storage is priced out entirely. See README's P5 section for the
full tables and the illustrative before/after cost decomposition.

## P4: FMU/Modelica verification -- compiled outside this environment, cross-check still blocked here

`apt-cache search openmodelica` finds no package in this container's
default repositories, and the container's own outbound network gateway
returns a hard `403` to OpenModelica's own distribution host
(`build.openmodelica.org`) and to Ubuntu's `ppa.launchpadcontent.net`
mirror -- an allowlist policy, not a transient failure. `fmpy` itself is
pip-installable (PyPI is reachable) but consumes an already-compiled FMU;
with no `omc` compiler reachable, there is nothing for it to consume. The
roadmap's own P4.1 environment step cannot be completed *here*.

That was worked around outside this environment: the user compiled
`modelica/tes_screen/package.mo`'s `PackedBedThermocline` model with
OpenModelica/OMEdit locally, which surfaced a real bug this session had no
way to catch on its own -- the package declared `package
TesScreen`/`end TesScreen;` inside a directory named `tes_screen`,
violating Modelica's file-system package-name-matching convention -- fixed
here, along with every reference to the old name. The resulting FMU
(confirmed valid FMI 2.0 Co-Simulation from its own `modelDescription.xml`)
contains only `binaries/win64/`; this sandbox is Linux with no Wine, so it
cannot be executed here either. `scripts/run_fmu_cross_check_experiment.py`
implements the P4.2 comparison (matched parameters on both sides,
including the fixed `h_v=5800 W/(m3.K)` the Modelica model itself does not
recompute) and is ready to run wherever the FMU can actually load; it was
smoke-tested end to end here with a stubbed FMU call, but the real FMU
numbers are not yet in this document.

## P6: the model-fidelity decision map

`scripts/run_model_fidelity_map_experiment.py` answers the more general
question every prior paired comparison (C2, C3, P5) sidestepped by only
ever running at this project's own case configs' one specific
temperature-quality regime: under what conditions does the SOC-dependent
correction materially change the decision, at all? Sweeps a dimensionless
`theta_req = (T_required_out - T_return) / (T_hot - T_return)` (P6.1) x
design duration tau (2h/6h/12h) x 3 load profiles = 45 grid points, 90
solves, all optimal and independently verified. This project's own two
packed-bed configs both sit at `theta_req = -0.25` (their own deliberate
20 C return-temperature margin above process temperature) -- reproduced
here as an explicit internal consistency check (`theta_req=-0.25, tau=6h,
flat` matches Phase C2/C3's own published 54.99/55.20 MWh, +0.0200% cost
exactly, even though this script builds curves independently).
**Finding: the annual objective stays insensitive over most of the domain
(33/45 grid points classified "constant model adequate"), but power/
energy sizing collapses from a small bias to complete infeasibility --
the SOC-dependent formulation sizes to exactly 0 MWh while the
temperature-blind constant-limit formulation still sizes 46-61 MWh -- in
12/45 points, once the temperature-quality requirement crosses a
duration-dependent threshold** (between theta_req 0.5-0.75 at the
shortest duration tested, 2h; between 0.75-0.9 at 6h and 12h, since
longer durations draw at lower mass flow and degrade more gracefully,
P2.1's own finding). Zero grid points fell in the intermediate
"potentially useful" band -- a genuinely bimodal split, not a gradual
one. This is the first result in this repository to actually demonstrate
the packed-bed thermocline degradation effect the project's own opening
hypothesis describes in its dramatic, technology-feasibility-changing
form, rather than the small (<0.1%) cost-only effect every prior paired
comparison found at this project's own case configs' own, much safer,
temperature-quality regime. One matplotlib heatmap per load profile
(`outputs/model_fidelity_map/figures/`), coloured by annual-cost bias with
materially-design-changing cells labelled directly. See README's P6
section for the full grid table and figures.

## Phase D: harmonised comparison and sensitivity

`TES_SCREEN_SPEC.md` section 7's three deliverables. **D.1, boundary
harmonisation table (README.md)**: done -- lifetime, discount rate, CAPEX
figures and citation tier, what is/is not inside each technology's own
power/BOP capex, round-trip efficiency, standing loss, for all three
technologies. Building it surfaces a real inconsistency rather than
resolving one: only packed bed has a computed parasitic-load estimate
(P3.3) and the deepest verification story (analytic limits,
discretisation convergence, an authored Modelica twin); molten salt and
PCM have neither, a real, stated gap in verification depth, not an
oversight, tracing back to Phase B's own stated priority ("one technology
fully verified beats three unfinished"). **D.3, technology-selection map
(`scripts/run_technology_selection_map_experiment.py`)**: done -- extends
Phase C3's single-duration ranking (tau=6h) across the full 2-temperature
x 5-duration grid C2 sweeps, 25 combinations, 50 solves, all verified.
Packed bed remains cheapest everywhere; the ranking never flips. A
secondary nuance the duration sweep surfaces: PCM's own "priced out
entirely" finding (C3) holds at tau=6h and longer, but at shorter
durations (2h, 4h) the constant-limit formulation finds slightly more
economic value in PCM than the no-storage baseline while the SOC-dependent
formulation still lands on exactly the no-storage cost at every duration
-- a small-scale illustration of this project's own central theme, never
changing which technology wins overall. **D.2, Morris global sensitivity
screening (`scripts/run_morris_sensitivity_experiment.py`, SALib)**: done
-- perturbs all five spec-named factors together (material cost, heat
transfer coefficient via `simulate_discharge`'s own h_v override,
discount rate, price volatility, `theta_req` reusing P6's own axis)
along 8 randomized trajectories, 48 sample points, 96 solves, all
verified. Response: SOC-dependent-vs-constant cost bias, packed bed only,
tau=6h, flat profile. **`theta_req` dominates every other factor by more
than an order of magnitude** (`mu_star` 7.14 vs. energy CAPEX's 0.607 and
discount rate's 0.424), with `sigma` (8.02) exceeding its own `mu_star` --
Morris's own signature of a highly nonlinear, cliff-like effect, not a
smooth one -- quantitatively confirming P6's own finding rather than
merely restating it. Price volatility and the heat transfer coefficient
itself are both essentially negligible (`h_v_multiplier`'s `mu_star` is
over 3,000x smaller than `theta_req`'s), a quantitative confirmation of
P3.1's own qualitative finding that the sizing/cost decision is robust to
h_v's precise magnitude even though the raw curve shape is not.

## What does not exist yet

- **P2.2, the full swept capability envelope** (sweep feasible mass flow at
  each physical state, choose the highest net-useful power after
  parasitics): explicitly deferred by the roadmap itself until the simpler
  duration-family comparison (P2.1, done above) is confirmed correct. Not
  attempted.
- **P3.3's blower parasitic power wired into the dispatch LP's own
  economics.** Currently computed and reported alongside each duration's
  discharge curve only; `dispatch.py`'s objective still uses
  `economics.storage_capex_eur_per_mw` unchanged. A natural next step, not
  attempted here since it would change every existing committed cost
  result and was not asked for.
- **P3.4, temperature-dependent air/material properties.** The roadmap's
  own instruction is "do not rush this": re-verify current property values
  against a primary/open source first, then decide whether constant
  properties are even inadequate. Not attempted in this pass, consistent
  with that instruction rather than as an oversight.
- **Real electricity price data.** Every run so far uses synthetic prices
  (`synthetic_daily_price_profile`); the real ENTSO-E fetch path
  (`electricity_price.py`) exists but `load_electricity_price`'s
  `"entso_e"` path still raises `NotImplementedError` for the actual
  bidding-zone/date-range call (`fetch_and_record_entsoe` must be called
  directly), and no `ENTSOE_API_KEY` has been available to test it against
  until now.
- **The FMU-vs-shadow-twin cross-check (roadmap P4).** No OpenModelica
  toolchain (`omc`) is installed in this working environment, so the
  Modelica model has been authored but never compiled, and this project's
  intended strongest verification story (the build spec's own words) has
  not been run. Re-checked directly this session, not re-asserted:
  `apt-cache search openmodelica` finds nothing in this container's
  default repositories, and the container's outbound network gateway
  returns a hard `403` to OpenModelica's own distribution host
  (`build.openmodelica.org`) and to Ubuntu's `ppa.launchpadcontent.net`
  mirror -- an allowlist policy, not a transient failure, so this is a
  fixed environment constraint, not something a retry or different mirror
  would resolve. `fmu.py` fails loudly and specifically when the toolchain
  is absent rather than silently skipping.
- **A Modelica twin or FMU cross-check for molten salt or PCM.** Both are
  closed-form models (see Phase C3 above), verified against their own
  specified physics, not against an independent analytic limit or a
  compiled FMU the way the packed bed's B4 checks are -- a real,
  stated difference in verification depth, not an oversight.
- **Explicit heat-exchanger modelling.** `delta_T_min_hot_side` (P0.2) is
  carried as an explicit parameter but set to `0.0` everywhere in this
  repository ([assumption]; docs/DATA.md); a real HX approach-temperature
  model, if added, would replace that placeholder rather than the
  parameter itself.
- PCM at 400 C: no common nitrate-salt PCM composition was found in this
  session's research with a melting point usefully close to 400 C, so that
  combination is left undone rather than forced (docs/DATA.md, README).
- **A dedicated PCM economics sweep.** Phase D.3's duration sweep (2h-12h)
  already showed PCM's own "priced out entirely" result is duration-
  dependent, not universal (it builds nonzero capacity at 2h/4h under the
  constant-limit formulation); whether a different PCM capex figure would
  make it competitive enough to actually exercise the SOC-dependent
  correction under *either* formulation is not tested -- P5's own economics
  sensitivity axes were run on packed bed only.
- **A `theta_req`-equivalent axis for molten salt or PCM.** P6's own
  `theta_req` (packed-bed thermocline-specific) does not transfer directly
  to molten salt (no thermocline) or PCM (a different, three-regime
  degradation shape); a comparable model-fidelity map for either
  technology would need its own axis definition, not attempted here.
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
and not against any measurement. The molten-salt and PCM dynamic sub-models (Phase C3) are closed-form, not
discretized, so their own checks confirm the implementation matches its
specified physics rather than checking numerical accuracy against an
analytic limit; neither has a Modelica twin or an FMU cross-check. The
Phase C/C2/C3 piecewise discharge-curve construction is checked for safety
(it must never claim more deliverable power than the underlying curve
shows) against that same curve's own data at every design duration swept
in C2 and every technology/temperature combination in C3 -- including PCM,
whose curve is not globally concave, where safety was verified empirically
across 3-30 segments rather than assumed from the curve's shape -- and
Phase C's original paired-run finding was checked for stability across
four different segment counts before its own confound (unequal sizing
degrees of freedom between the two formulations) was found and corrected
in C2. P0.3 goes a step further than
verifying the curve's own construction: it checks whether the curve's
underlying premise (that total energy determines outlet capability) holds
at all outside the one trajectory it was fit from, and finds that it does
not -- a limitation surfaced by testing, not assumed away. None of that is
validation. Nothing in this repository has been checked against measured
data from a real storage installation, and the current inputs (load
profile, electricity price) are declared synthetic, not measurements of any
real site or market.
