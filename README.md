# tes-discharge-screen

[![CI](https://github.com/abhijith-sivaprasadan/tes-discharge-screen/actions/workflows/ci.yml/badge.svg)](https://github.com/abhijith-sivaprasadan/tes-discharge-screen/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python 3.10-3.13](https://img.shields.io/badge/Python-3.10--3.13-3776AB.svg)](pyproject.toml)

Techno-economic screening of thermal storage for industrial process heat, with
dynamically-informed discharge constraints.

**This is not:**

- **Not** a validated model of any real storage installation.
- **Not** a claim of expertise in high-temperature storage materials, containment,
  degradation or thermal cycling. The material property sets are literature values,
  clearly cited, used as inputs, not as contributions.
- **Not** a design tool. It is a screening framework.
- **Not** a claim that the SOC-dependent formulation is novel. Packed-bed
  thermoclines are extensively studied. The contribution, if any, is the systematic
  comparison of what the simplification costs across technologies under harmonised
  boundaries.

## The question

Annual techno-economic optimisation of thermal energy storage almost always
represents the store as an energy reservoir with a **constant** charge and discharge
power limit, the same way an electricity model represents a battery. For a
sensible-heat store serving a process at a fixed temperature, that is wrong: outlet
temperature falls as the store discharges, so deliverable power at or above the
process temperature declines with state of charge, and the last portion of stored
energy is unusable for that load. For two-tank molten salt and for latent (PCM)
storage, discharge temperature is roughly constant, so the simplification is close
to correct.

This project derives a state-of-charge-dependent discharge limit from a targeted
dynamic model, carries it into an annual optimisation as a piecewise-linear
constraint, and measures whether sizing conclusions or the technology ranking
change. A null result is a real result and will be reported first and plainly if
that is what comes out.

## Status

Phase 0 (scaffold and contracts) and Phase A (annual quasi-steady core,
constant discharge limit) are both done to their own exit criteria: see
[Phase A baseline results](#phase-a-baseline-results-flat-load-synthetic-priceload)
below. Phase B (targeted dynamic sub-model) is built for the packed-bed
technology only, matching the project's own priority (one technology fully
verified beats three unfinished): a Python shadow twin
(`packed_bed_dynamics.py`), a Modelica model of the identical physics
(`modelica/tes_screen/package.mo`), and an FMU export adapter (`fmu.py`).
No OpenModelica toolchain is available in this working environment, so the
Modelica model has been authored but not compiled, and the FMU-vs-shadow-twin
cross-check (this project's intended strongest verification story) has not
been run; the shadow twin's own correctness instead rests on three analytic
limits, all passing. See [Phase B](#phase-b-packed-bed-dynamic-sub-model)
below. Molten-salt and PCM dynamic sub-models do not exist yet.

**Scalar SOC is not shown to be a sufficient state, and this is reported
rather than hidden.** [P0.3](#p03-is-scalar-soc-a-sufficient-packed-bed-state)
constructs several bed states at matched total energy but different spatial
structure and finds near-term deliverable power scattering by up to 220%
(115% even restricted to states reachable by discharging alone) at the same
SOC -- so Phase B/C's discharge curve is a **trajectory-derived SOC
capability curve**, accurate along the one specific bed-state history it
was built from, not a validated general `Pmax(SOC)` law. This does not
invalidate Phase C/C2 below (both use exactly that one trajectory,
consistently), but it is a real limitation to carry forward, stated
explicitly rather than assumed away.

**Phase C (the paired experiment) is done at MVP scope**: one technology
(packed bed), one process temperature (300 C), one load profile (flat),
solved under both discharge-limit formulations. Its original run left the
two formulations with unequal sizing degrees of freedom, mixed the process
and return temperature references, and bound discharge capability by the
post-dispatch state rather than the pre-dispatch one (see the note at the
top of [Phase C](#phase-c-original-mvp-run-archived-diagnostic-only)),
which confounded "the discharge-limit shape changed" with "the two runs
were also allowed different durations," inflated deliverable power with
enthalpy already present in the return stream, and inflated the power the
SOC-dependent formulation appeared to need on top of both.
**[Phase C2](#phase-c2-matched-duration-family-experiment-the-corrected-comparison)**
fixes all three (roadmap P0.1, P0.2, and [P0.4](#p04-start-of-hour-vs-end-of-hour-discharge-capability)):
ties power to energy capacity at the same externally chosen duration in
both formulations, references deliverable power consistently to the
store's own return temperature, and bounds discharge capability by what
was actually on hand before each hour's own discharge. The isolated shape
effect is much smaller than Phase C's original number: a total-cost delta
ranging from +0.000% to +0.038% across a 2-12h duration sweep -- at the two
shortest durations, indistinguishable from the constant-limit baseline to
solver tolerance -- versus Phase C's original +0.22% at its own
(confounded, mis-referenced, over-conservative) durations. This is not the
full 18-run technology-ranking matrix (only packed bed has a Phase B
dynamic sub-model yet), so whether the technology ranking itself changes is
not answerable from this result.

Electricity prices are synthetic in every run so far: this working environment
has no `ENTSOE_API_KEY` configured, so the real ENTSO-E fetch path
(`electricity_price.py`, ported from PyNEXUS) is built and gated behind that
credential exactly the way PyNEXUS's own equivalent module is, but has not been
exercised against live data. Real ENTSO-E prices go negative at times, which a
pure LP with independent charge/discharge variables can exploit
pathologically; **[P0.5](#p05-preventing-pathological-simultaneous-cycling-under-negative-prices)**
adds an optional MILP operating-mode binary (`storage.cycling_prevention_mode
== "milp_binary"`) that prevents it, ahead of ever actually needing to run
against negative prices. See [Sequencing](#sequencing) below.

## Governing rules

1. **Verified is not validated.** Verified means checked against its own physics, an
   analytic limit, or an independent hand calculation. Validated means checked
   against independent measured data. This project will contain a great deal of the
   first and none of the second.
2. **No result without a recorded solver status.** Every stored result carries
   solver name, termination condition, objective value, and wall time.
3. **Documentation ships in the same commit as the capability.** Not the next one.
4. **Never weaken the physics to make a test pass.**
5. **No number in a figure or table that cannot be traced** to a config file, a data
   provenance record, and a solver status.
6. **Assumptions live in config, never in source.** No magic constants.

## Phase A baseline results (flat load, synthetic price/load)

This is the constant-discharge-limit baseline only, not yet the SOC-dependent
comparison Phase C exists to produce, so there is no ranking finding to report
here: the numbers below show the model runs, solves to optimality, and passes
every independent check across all three technologies and both process
temperatures, on real (if synthetic-input) numbers rather than placeholders.

| Case | Termination | Annualised cost (EUR/yr) | Sized capacity (MWh-th) | Sized power (MW) | Max balance residual |
|---|---|---:|---:|---:|---:|
| packed_bed, 300 C | optimal | 3,992,456 | 54.99 | 7.42 | 8.9e-16 |
| molten_salt, 300 C | optimal | 4,071,018 | 36.80 | 4.85 | 8.9e-16 |
| pcm, 300 C | optimal | 4,172,472 | 13.80 | 4.85 | 8.9e-16 |
| packed_bed, 400 C | optimal | 3,992,456 | 54.99 | 7.42 | 8.9e-16 |
| molten_salt, 400 C | optimal | 4,071,018 | 36.80 | 4.85 | 8.9e-16 |

The cost ranking (packed bed cheapest, PCM most expensive) tracks the CAPEX
ranking in `docs/DATA.md` directly, which is the expected, sanity-checking
result for a model that is purely economic at this stage.

**A real limitation, stated rather than hidden:** the 300 C and 400 C rows for
each technology are numerically identical. `dispatch.py` never reads
`delivery_temperature_c`, `medium`, or `storage.temperature_max_c`/`min_c` -
Phase A's storage block is a temperature-agnostic MWh reservoir, exactly like
the constant-limit battery-style model this project's own opening thesis
describes as the flawed standard practice. Nothing in Phase A can move with
process temperature yet, by construction; that only becomes possible once
Phase B's dynamic sub-model derives an actual temperature-aware discharge
curve and Phase C wires it in. `tests/test_dispatch.py::test_process_temperature_has_no_effect_on_phase_a_result`
locks this in as an explicit, checked property rather than a silent surprise,
and is expected to need updating once Phase C lands.

**PCM was not run at 400 C.** Sodium nitrate's ~306 C melting point (the PCM
config's basis; `docs/DATA.md`) does not sit usefully close to a 400 C process:
no common nitrate-salt PCM composition was found with a high enough melting
point and useful latent heat in this session's research. Rather than force an
unfit config to get a sixth row, that combination is left undone until a
suitable high-temperature PCM composition is sourced.

Every case's full schedule, config, and solver/verification manifest:
`outputs/<case_name>/`.

## Phase B: packed-bed dynamic sub-model

A one-dimensional, two-phase (solid/fluid) transient model of the packed
bed's discharge (Schumann's 1929 formulation; `docs/DATA.md`), authored twice:
as a pure-Python shadow twin (`src/tes_screen/packed_bed_dynamics.py`) and as
a Modelica model of the identical governing equations
(`modelica/tes_screen/package.mo`), following OpenSteamOpt's shadow-twin
pattern. The twin's own correctness rests on three analytic limits (the build
spec's B4), all passing:

| Analytic check | Result |
|---|---|
| Zero draw rate, zero loss: outlet stays at the initial (charged) temperature | pass, exact to 1e-9 C |
| Infinite heat transfer coefficient: single-node bed reduces to a well-mixed tank's closed-form exponential response | pass, matches to 1e-3 relative / 1e-2 C absolute |
| Energy conservation: cumulative outlet enthalpy flow equals stored-energy loss | pass, to 1e-9 relative (near machine precision) |

Discharge curves (state of charge vs. deliverable power) were generated at
three draw rates and committed with their generating bed config:
`outputs/packed_bed_dynamics/`. **Call this a trajectory-derived SOC
capability curve, not a universal packed-bed `Pmax(SOC)` law** (roadmap
P0.3's own documentation-language instruction): it comes from one specific
trajectory (a fully-charged, spatially uniform bed, discharged continuously
at one mass flow), and [P0.3](#p03-is-scalar-soc-a-sufficient-packed-bed-state)
below finds real evidence that total stored energy alone does not determine
near-term deliverable power for other, differently-shaped bed states at the
same total energy.

**Temperature semantics (roadmap P0.2).** `discharge_power_curve` separates
three temperatures an earlier version of this module conflated: `T_process`
(the process's service temperature), `delta_T_min_hot_side` (minimum
heat-exchanger approach above it, `0.0` throughout this repository --
`docs/DATA.md`'s own [assumption] note), and `T_return` (the HTF
temperature entering the bed, an explicit simulation input, never derived
from `T_process`). `storage_heat_mw` (net thermal power extracted from the
bed, `m_dot * cp * (T_out - T_return)`) is referenced to the same
temperature the bed's own stored-energy accounting uses, so a fully
depleted bed reports exactly zero rather than a negative number that
happened to get clipped, and integrating it against time now reproduces
the bed's own stored-energy drop (checked directly, not assumed:
`test_integrated_storage_heat_matches_the_beds_own_stored_energy_drop`).
`deliverable_power_mw` then applies a quality gate on top of that --
zero whenever the outlet cannot clear `T_required_out = T_process +
delta_T_min_hot_side`, even though the bed still holds recoverable
sensible energy at that point -- and it is this gated stream, not the
ungated `storage_heat_mw`, that Phase C's piecewise construction fits and
the dispatch LP sees. Before this fix, deliverable power was computed
against `T_process` while stored energy was computed against `T_return`,
so whenever the two differed, enthalpy already present in the return
stream was counted as if storage had supplied it -- inflating every
SOC-dependent sizing result derived from this curve, including Phase C's
original one.

**What has not been done, and why.** No OpenModelica toolchain (`omc`) or
`fmpy` is installed in this working environment, so the Modelica model above
has been authored but never compiled, and the FMU-vs-shadow-twin cross-check
that the build spec calls "the single strongest verification story available
here" has not been run. `fmu.py` (ported from OpenSteamOpt's identical
`find_omc()` pattern) fails loudly and specifically when the toolchain is
absent rather than silently skipping; `tests/test_modelica_contract.py`
statically checks the authored Modelica source instead, the same
toolchain-independent pattern OpenSteamOpt itself uses for CI. Molten-salt and
PCM dynamic sub-models do not exist yet: packed bed is the technology the
project's hypothesis expects to show the largest effect, and a single
technology fully verified is worth more here than three left unfinished.

## P0.3: is scalar SOC a sufficient packed-bed state?

A packed bed is a distributed-temperature system: two beds holding the same
total stored energy can have that energy arranged very differently along
the bed (a sharp thermocline near one end vs. a broad, smeared one), and
Phase B/C's discharge curve reads deliverable power off total energy alone,
from a single trajectory. Whether that is actually a safe reduction --
whether scalar SOC is *sufficient* to predict near-term outlet capability,
not just correlated with it along the one trajectory the curve was fit from
-- is an empirical question the single-trajectory construction cannot
answer by itself. The roadmap's own short-term research test (P0.3) checks
this directly, rather than assuming it.

**The finding, stated first and plainly, and not softened: scalar SOC is
not a sufficient state for this bed model.** `state_sufficiency.py`
constructs four temperature fields at matched total energy (uniform,
`step_hot_at_inlet`, its mirror image `step_hot_at_outlet`, and a broad
`smeared` ramp -- same energy, different spatial arrangement, by
construction; see the module for exactly how) at three energy fractions
(0.3, 0.5, 0.7), discharges each briefly (30 minutes, ~1.5-2.5% of a full
breakthrough discharge, at the same mass flow and return temperature every
time: `scripts/run_state_sufficiency_experiment.py`), and reads deliverable
power off each at several short-term checkpoints. At fixed total energy,
deliverable power ranges as widely as **~0 MW to ~0.26 MW** across the
profile family -- a relative scatter (max-min)/mean of up to **220%** at
some (energy fraction, checkpoint) pairs, against an explicit 5% threshold
this experiment would have needed to stay under to call scalar SOC
adequate. Even restricted to the three profiles reachable by discharging
alone (excluding `step_hot_at_inlet`, which places the hot block where cold
fluid enters first -- not reachable without an external recharge or mixing
step, since a real discharge always erodes from the inlet), the scatter is
still **up to 115%**. Both numbers, and the full per-(energy fraction,
checkpoint, profile) table, are in `outputs/state_sufficiency/`.

**Why, physically.** At a short time horizon, near-term deliverable power
is governed mainly by how much hot material sits immediately upstream of
the outlet, not by the bed's total energy content. `step_hot_at_outlet`
puts hot material right at the outlet, so it stays near full power for the
whole 30-minute window regardless of how little energy the rest of the bed
holds; `step_hot_at_inlet` puts the same total energy where the incoming
cold fluid meets it first, so a warming front has to propagate the length
of the bed before any of it reaches the outlet at all, and in this
30-minute window essentially none of it does. Total energy is the same;
near-term capability is not remotely the same.

**What this does and does not mean for Phase C/C2.** It does not invalidate
those results: Phase C/C2's own trajectory (a uniform, fully-charged bed
discharging continuously) is one specific, reachable state history, and the
curve is accurate along that specific history -- the piecewise
construction's own safety checks (against that trajectory's actual data)
still hold. What it does mean is that the curve should not be read as a
general `Pmax(SOC)` relation that would also hold for a bed reaching the
same SOC by a different route (partial discharge/recharge cycling, for
instance) -- exactly the caveat the roadmap asks this project to carry
until a state-sufficiency test exists. It also flags a specific, concrete
limitation for any future work that lets the annual LP's storage cycle
partially (charge and discharge within an hour, or repeatedly): the
piecewise limit currently used would not necessarily be trustworthy there,
since it was never tested against non-uniform states at all.

**Per the roadmap's own instruction not to hide a negative result here**:
this is reported as a real, structural limitation of the scalar-SOC
reduction for this bed model, not rounded down or explained away. A fifth
profile family the roadmap names (states drawn from realistic
charge/discharge histories) needs a charging dynamic model this project
does not have and is left undone rather than approximated; see
`state_sufficiency.py`'s own module docstring.

## Phase C (original MVP run): archived, diagnostic only

**This section documents the project's original paired run, kept for the
record. It is superseded by [Phase C2](#phase-c2-matched-duration-family-experiment-the-corrected-comparison)
as the paired comparison of discharge-limit shape and should not be read as
this project's current headline finding.** The run below let each
formulation pick its own power rating independently: the constant-limit
baseline's power was a free decision variable, while the SOC-dependent
case tied charge power to the discharge curve's own fixed power/energy
ratio. Reading its own committed manifest back, this meant the two runs
being compared were not actually the same duration of storage: the
constant-limit run solved to a 7.41h store (54.99 MWh / 7.42 MW) and the
SOC-dependent run to a 3.88h store (50.43 MWh / 12.98 MW). Part of the
"SOC-dependent needs 75% more power" result below is therefore duration,
not discharge-limit shape -- the two things this comparison was meant to
isolate were never actually separated. The data and numbers below are
unchanged from the original run (not deleted, per this project's own rule
against overwriting evidence); the finding they were used to support has
been withdrawn in favour of Phase C2's matched comparison.

**The finding, stated first and plainly:** for packed bed at 300 C with a
flat load profile, replacing the constant discharge limit with the
SOC-dependent one increases annualised total cost by **0.22%** (+8,823
EUR/yr on a ~4.0M EUR/yr baseline), decreases the optimal storage energy
capacity by **8.3%** (54.99 to 50.43 MWh-th), and increases the required
power capacity by **75%** (7.42 to 12.98 MW). This is a real but modest
effect for this one case, not a dramatic one and not a null one: the
constant-limit simplification understates how much power capability a
packed bed needs to deliver the same load, which is exactly the direction
this project's hypothesis predicted, at a scale worth stating honestly
rather than rounding up or down.

This is the MVP the build spec's own section 10 and 8 describe as "a
complete piece of work": one technology (packed bed), one process
temperature (300 C), one load profile (flat), both discharge-limit
formulations, solved and independently verified. It is **not** the full
18-run matrix (3 technologies x 2 temperatures x 3 profiles): only packed
bed has a Phase B dynamic sub-model, so there is no second technology to
rank against yet, and "does the technology ranking change" is not
answerable from this result.

| | Constant limit (Phase A baseline) | SOC-dependent (Phase C) | Delta |
|---|---:|---:|---:|
| Termination | optimal | optimal | |
| Annualised total cost (EUR/yr) | 3,992,456 | 4,001,279 | +8,823 (+0.22%) |
| Storage energy capacity (MWh-th) | 54.99 | 50.43 | -4.56 (-8.3%) |
| Storage power capacity (MW) | 7.42 | 12.98 | +5.57 (+75.0%) |
| Backup fuel cost (EUR/yr) | 1,035,235 | 1,028,777 | -6,459 |
| Electricity cost (EUR/yr) | 2,497,270 | 2,508,949 | +11,678 |
| Emissions (tCO2/yr) | 5,228 | 5,195 | -33 |
| Solve time | 8.3 s | 22.5 s | |

**The piecewise construction and its safety, checked, not assumed.**
Following the same technique as OpenSteamOpt's boiler fuel curve
(`rto.py`), the discharge curve becomes a small set of linear constraints,
`p_dis[t] <= a_i*level[t] + b_i*E_cap` for every segment `i`
simultaneously, kept strictly linear even with storage energy capacity as
a free decision variable by tying the fitted curve's power/energy ratio to
`E_cap` rather than treating power and energy capacity as independent
(charge power is tied the same way when unfixed, so the two runs compare
on equal footing: same sizing degrees of freedom, only the discharge
constraint itself differs). This construction is exact for a concave curve
and only ever safe (never overestimates deliverable power) for one; the
packed-bed discharge curve is empirically concave (flat near full charge,
steepening toward depletion), checked against the underlying data at 3,
5, 8, and 12 segments, not assumed from the curve's shape.

**More segments barely changes the answer**, exactly per the build spec's
own C1 instruction to check this: sized capacity and power were identical
(50.43 MWh, 12.98 MW) at every segment count from 3 to 12, and total cost
varied by under 350 EUR (under 0.01%) across that range. 5 segments (the
spec's own suggested default) is what the headline table above uses.

Every number above traces to `outputs/phase_c_packed_bed_300c_flat/`:
both hourly schedules, the fitted curve's breakpoints, and a manifest with
both runs' solver status, every verification check's pass/fail, and the
full segment-count robustness table.

## Phase C2: matched-duration-family experiment (the corrected comparison)

**The finding, stated first and plainly:** once both formulations are tied
to the same design duration (`storage.design_duration_hours`, so power is
always `E_cap / tau` in both, identically), deliverable power is referenced
consistently to the store's own return temperature rather than mixed with
the process temperature, and the discharge-capability constraint reads the
pre-dispatch state rather than the post-dispatch one (P0.1, P0.2, and P0.4,
all applied here), the isolated effect of the SOC-dependent discharge limit
is much smaller than Phase C's original (confounded, unequal-duration,
mis-referenced, and overly conservative) estimate. Swept across five design
durations from 2h to 12h, the SOC-dependent formulation costs
**+0.000% to +0.038%** more than the constant-limit baseline at the same
duration -- at the two shortest durations, indistinguishable from the
constant-limit baseline to solver tolerance -- against the +0.22% Phase C
originally reported, and smaller again than the +0.013%-to-+0.080% range
P0.1+P0.2 alone (without P0.4) produced.

| Design duration (tau) | Constant limit cost (EUR/yr) | SOC-dependent cost (EUR/yr) | Delta | Constant E_cap (MWh) | SOC-dependent E_cap (MWh) |
|---:|---:|---:|---:|---:|---:|
| 2h | 4,019,225.76 | 4,019,225.76 | +0.000% | 45.87 | 45.87 |
| 4h | 4,000,234.86 | 4,000,235.89 | +0.000% | 50.43 | 50.43 |
| 6h | 3,993,618.08 | 3,994,416.32 | +0.020% | 54.99 | 55.20 |
| 8h | 3,992,555.33 | 3,993,991.36 | +0.036% | 54.99 | 56.94 |
| 12h | 3,996,426.99 | 3,997,959.30 | +0.038% | 60.75 | 62.46 |

All ten runs (five durations x two formulations) solved to `optimal` and
passed every independent verification check. The headline duration (6h,
chosen as a round middle point of the sweep, not cherry-picked for
magnitude) is tabulated in full below; every duration's fitted curve
safety, solver status, and delta is in the run manifest.

| | Constant limit (tau=6h) | SOC-dependent (tau=6h) | Delta |
|---|---:|---:|---:|
| Termination | optimal | optimal | |
| Annualised total cost (EUR/yr) | 3,993,618.08 | 3,994,416.32 | +798.24 (+0.020%) |
| Storage energy capacity (MWh-th) | 54.99 | 55.20 | +0.22 (+0.4%) |
| Storage power capacity (MW) | 9.16 | 9.20 | +0.04 (E_cap/tau, so it moves with E_cap) |
| Backup fuel cost (EUR/yr) | 1,014,756.09 | 1,021,514.11 | +6,758.02 |
| Electricity cost (EUR/yr) | 2,524,452.26 | 2,515,586.48 | -8,865.78 |
| Emissions (tCO2/yr) | 5,124.52 | 5,158.65 | +34.13 |
| Solve time | 8.8 s | 21.6 s | |

**Why P0.4 shrinks the gap further.** `dispatch.py`'s piecewise
discharge-capability constraint used to bound `p_dis[t]` using `level[t]`,
the *post*-dispatch state the storage balance defines in terms of that same
hour's own `p_dis[t]` -- backwards, since capability at the start of an hour
should depend on what was on hand before that hour's own discharge drew it
down. Reading the correct, pre-dispatch state (`level_start[t]`, always at
least as large as `level[t]` whenever that hour is a net discharge) relaxes
the bound, so the SOC-dependent formulation now needs less headroom to
deliver the same load than the uncorrected constraint implied -- shrinking
the apparent penalty at every duration, and making it disappear to solver
tolerance at 2h and 4h. See [P0.4](#p04-start-of-hour-vs-end-of-hour-discharge-capability)
below for the full mechanism and a short-horizon case where the effect is
large enough to flip which formulation needs more power outright.

**Why energy capacity (and, through it, power) can still differ between the
two formulations at every tau in this table.** `design_duration_hours` ties
power to `E_cap / tau` identically in both -- the one degree of freedom
Phase C's original run left unequal -- but `E_cap` itself is still a free
decision variable in each formulation, and the SOC-dependent curve's power
still declines with state of charge (that is the whole discharge-limit
shape this comparison is meant to isolate), so the optimiser leans on a
somewhat larger store to compensate. That the gap it needs is now this
small, once every other confound is corrected, is itself the headline
result.

**How the matched curves were built.** For each swept tau, the discharge
mass flow is solved for directly (`discharge_curve.mass_flow_for_target_duration`)
so the resulting curve's own reference power/energy ratio already equals
`1/tau`, then the bed is re-simulated at that mass flow and a fresh
piecewise curve fit -- a curve genuinely specific to that duration, not one
curve rescaled after the fact. `dispatch.py`'s `duration_matched` branch
checks this equality at model-build time and refuses a mismatched curve
rather than silently accepting one. Deliverable power (and, through
`mass_flow_for_target_duration`, the reference power this solves against)
is computed per P0.2: referenced to the bed's own return temperature
`T_return`, with a quality gate at `T_process + delta_T_min_hot_side`
(`delta_T_min_hot_side = 0` here; see docs/DATA.md) applied on top, rather
than mixing the process and return temperature references the way Phase C's
original run did; the discharge-capability constraint itself uses
`storage.discharge_capability_reference = "start_of_hour"` per P0.4.

**A solver note, not a modelling one.** At 7-9h durations, P0.4's corrected
(less self-damped) formulation turned out to be numerically harder for
HiGHS's default simplex method on this particular curve shape -- not
infeasible, just slow enough that a couple of durations near tau=8h failed
to find any feasible solution within the configured time limit. Switching
`solve_dispatch`'s solver option to HiGHS's interior-point method (every
decision variable in this model is continuous, so IPM is a legitimate,
generally-applicable choice, not a one-off workaround) resolves it,
verified to reproduce the identical objective value on every
already-passing case, not just paper over the new one.

Every number above traces to `outputs/phase_c2_duration_matched/`: the
headline (6h) duration's hourly schedules and fitted curve breakpoints, and
a manifest with every swept duration's solver status, KPIs, verification
checks, and curve-fit safety numbers.

## P0.4: start-of-hour vs. end-of-hour discharge capability

**The bug.** `dispatch.py`'s piecewise discharge-capability constraint,
`p_dis[t] <= a_i*level_ref[t] + b_i*E_cap`, used `level[t]` as `level_ref[t]`
-- but `level[t]` is the *post*-dispatch state: `storage_balance`'s own
equation defines it in terms of that same hour's `p_dis[t]` and `p_ch[t]`.
Physically, what an hour's discharge is *capable of* should depend on what
was actually on hand before that hour's own discharge drew it down --
`level_start[t]` (`soc_init_fraction * E_cap` at `t=0`, `level[t-1]`
otherwise, the same "previous" term `storage_balance` already computed) --
not what's left over afterward.

**Why this mattered, not just as a technicality.** Because the curve is
increasing in level (more stored energy, more deliverable power), and
discharging only ever lowers the level within an hour, bounding `p_dis[t]`
by the *smaller*, post-discharge `level[t]` made the constraint tighter than
physically justified whenever an hour was a net discharge -- self-
referentially so, since `level[t]` is itself defined in terms of `p_dis[t]`.
Substituting the storage balance into the constraint shows the effective
bound was the correct (start-of-hour) one divided by `(1 + a_i/eta_discharge)`
-- always a shrinkage, never a relaxation. This directly inflated how much
power capacity the SOC-dependent formulation appeared to need relative to
the constant-limit baseline, on top of the separate P0.1 and P0.2 confounds.

**The fix, and why it stays an explicit choice, not a silent replacement.**
`storage.discharge_capability_reference` (`"start_of_hour"` or
`"end_of_hour"`) is a new required config field, validated exactly like
`discharge_limit_mode`: required when `discharge_limit_mode ==
"soc_dependent"`, must be null otherwise (the constant limit doesn't depend
on level at all, so a given value there would mean nothing).
`dispatch.py`'s `build_model` defensively re-checks this too, not just
`config.py`'s loader, since `build_model` is public API tests and scripts
call directly on hand-built configs -- an invalid or missing value must
never silently fall back to one behaviour or the other. Both remain fully
supported: this is a modelling choice with a roadmap-recommended default for
this screening model (`start_of_hour`), not a bug that only had one correct
fix.

**Quantified, per the roadmap's own acceptance criterion**, at a short
72-hour horizon with nearly-free storage economics (forcing both
formulations to actually build storage rather than collapsing to
`E_cap = 0`): switching from `end_of_hour` to `start_of_hour` drops the
SOC-dependent formulation's required power rating from 10.38 MW to 9.60 MW
-- enough to flip which formulation needs more power than the other
outright, since the constant-limit baseline needs exactly 10.0 MW (its own
free-sizing decision variable, unaffected by this fix) at this case.
`end_of_hour` needing *more* power than the constant baseline matches Phase
C's original framing; `start_of_hour` needing *less* undercuts that framing
as itself partly an artifact of this bug, not a robust physical result on
its own. `tests/test_dispatch.py`'s P0.4 test block reproduces this
exactly, alongside a build-time check confirming an invalid or missing
`discharge_capability_reference` is rejected rather than silently
defaulted, and a pair of curve-safety checks confirming each reference mode
is verified against the state it actually uses (checking `end_of_hour`'s
solved discharge against the post-dispatch level, and `start_of_hour`'s
against the independently reconstructed pre-dispatch one, not the same
column for both).

## P0.5: preventing pathological simultaneous cycling under negative prices

**The problem, reproduced, not just theorised about.** A pure LP with
independent nonnegative `p_ch[t]`/`p_dis[t]` variables can exploit negative
electricity prices: draw heater electricity purely to collect the
negative-price payment, discharge the store in the same hour to make room
for it in the heat balance, then charge the store right back up beyond what
`c_charge_limit` alone would allow. Mathematically feasible, physically
meaningless, and it burns real round-trip losses (`eta_charge`,
`eta_discharge`) for no net storage benefit -- and with real ENTSO-E data
(not yet fetched in this working environment; see Status above), negative
hours actually occur. Given a case with generous headroom (large heater
capacity, sizeable charge/discharge power, moderate round-trip efficiency)
and a deep negative-price window, this reproduces exactly: the LP charges
at its full 20 MW limit while simultaneously discharging 13-18 MW, hour
after hour, with the store pinned at full capacity throughout -- not
storing and releasing energy, just churning it to launder negative-price
electricity.

**The fix.** `storage.cycling_prevention_mode` (`"none"` or
`"milp_binary"`) is a new required config field. `"milp_binary"` adds a
per-hour binary `z[t]` and two constraints,
`p_ch[t] <= charge_power_bound_mw * z[t]` and
`p_dis[t] <= discharge_power_bound_mw * (1 - z[t])`, forcing at most one
direction active per hour -- the roadmap's own preferred, "research-grade"
option (explicitly not wasted effort, since the target KTH project values
MILP formulations). `"none"` keeps the original LP available, unchanged,
for nonnegative-price diagnostics (every case config in this repository
still uses it; none of them carry negative prices).

**A modelling subtlety the naive version of this fix gets wrong.** The
textbook big-M pattern needs `M` to be a genuine numeric constant. But
`p_ch_max` in this model is very often itself a Pyomo *expression* in a
sizing variable (`E_cap/tau`, `discharge_curve.k * E_cap`, or `P_rated`
directly) -- using it as `M` in `p_ch_max * z[t]` would multiply two
variables together, a nonlinear term no MILP solver can handle.
`charge_power_bound_mw`/`discharge_power_bound_mw` are computed as genuine
numeric constants instead, built from the same numeric bounds already
declared for `E_cap`/`P_rated`'s own domains (`peak * 24 * 10` MWh,
`peak * 5` MW) rather than an arbitrary big number -- the roadmap's own
"use defensible capacity bounds" instruction, followed literally.

**Quantified, per the roadmap's own acceptance criteria**
(`tests/test_dispatch.py`'s P0.5 block): in the reproducing case above (a
10-hour deep-negative-price window), the LP mode shows 5 hours of material
simultaneous charge and discharge; `milp_binary` shows zero. The MILP
formulation still terminates optimal and passes every independent
verification check under the negative-price profile ("negative price tests
behave sensibly"). Its total cost (68,203 EUR) is provably never lower than
the LP's own (the MILP constraints are a strict restriction of the LP's
feasible region -- true by construction, not just observed) and is indeed
measurably higher than the LP's (66,734 EUR), confirming the LP's
apparently cheaper answer was exactly the exploited pathology's value, not
a genuinely better dispatch MILP is leaving on the table. The original LP
mode continues to solve and verify normally under ordinary nonnegative
synthetic prices, exactly as every other case in this repository already
relies on.

## Repository layout

```
src/tes_screen/   Python package: config schema, profile contract, provenance,
                  synthetic profiles, electricity price source, the annual
                  dispatch LP (constant and SOC-dependent) and its
                  verification, the Phase B packed-bed shadow twin, the
                  piecewise discharge-curve construction (C1), the P0.3
                  temperature-field constructors, and the FMU export adapter
modelica/         Authored Modelica model(s) for Phase B (not yet compiled here)
scripts/          Run harnesses: run_case.py (Phase A), run_packed_bed_dynamics.py
                  (Phase B curves), run_phase_c_experiment.py (the original,
                  archived paired comparison), run_phase_c2_duration_matched_experiment.py
                  (the corrected, matched-duration paired comparison),
                  run_state_sufficiency_experiment.py (P0.3's state-sufficiency test)
tests/            Physics and contract tests, not syntax tests
configs/          One YAML per case; no parameter lives in source
outputs/          Committed run evidence: config + schedule + solver/verification manifest
docs/             Model card, data citations, verification notes
```

## Reused patterns

This project depends on ideas from two existing repositories, not on their code.
Neither is modified; nothing is imported across repositories.

- **PyNEXUS** (`optimization/dispatch.py`, `data/provenance.py`): the storage block
  pattern (level, charge/discharge, standing loss, terminal condition), the
  provenance record pattern, and the annual run harness.
- **OpenSteamOpt** (`src/opensteamopt/{fmu,twin,rto}.py`): the Modelica/FMI 2.0
  export path, the shadow-twin cross-check, the piecewise-linear construction (used
  here for the SOC-dependent discharge curve, `discharge_curve.py`), and
  the profile contract validation.

## Sequencing

Phase 0 (scaffold, done) -> A (annual quasi-steady core, constant discharge
limit; done to its exit criterion) -> B (targeted dynamic sub-model and
shadow twin; packed bed done to its exit criterion, molten salt and PCM not
started, FMU cross-check untestable in this environment) -> P0.3 (state-
sufficiency test; done -- scalar SOC found insufficient across the
constructed profile family, so Phase B's curve is documented as
trajectory-derived, not a general law) -> C (coupling and the paired-run
experiment; done at MVP scope, one technology/temperature/profile pair, not
the full 18-run matrix; original run superseded by C2 as the shape-isolated
comparison) -> C2 (matched-duration-family sizing fix; removes the
unequal-duration confound in C's original pairing; done, five durations
swept) -> P0.4 (start-of-hour discharge capability reference; done --
removes a third confound from C's original pairing, folded into C2's own
sweep) -> P0.5 (MILP simultaneous-cycling prevention; done -- optional
`cycling_prevention_mode`, ahead of ever running against real, sometimes
negative, ENTSO-E prices) -> D (harmonised comparison and sensitivity,
optional enrichment; not started).

## Development

```
uv venv
uv pip install -e ".[dev]"
pytest
ruff check .

# Solve one Phase A case end to end and write outputs/<case_name>/:
python scripts/run_case.py configs/packed_bed_300c_flat.yaml

# Generate and commit Phase B packed-bed discharge curves:
python scripts/run_packed_bed_dynamics.py

# Run the P0.3 state-sufficiency experiment (is scalar SOC enough?):
python scripts/run_state_sufficiency_experiment.py

# Run the Phase C paired constant-vs-SOC-dependent experiment (original,
# archived; unequal sizing degrees of freedom between formulations -- see
# Phase C's section above):
python scripts/run_phase_c_experiment.py

# Run the Phase C2 matched-duration-family experiment (corrected comparison):
python scripts/run_phase_c2_duration_matched_experiment.py
```
