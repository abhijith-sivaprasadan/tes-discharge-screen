# Full results and methodology

This file carries the complete, phase-by-phase write-up: methodology, every
committed table and figure, and the sub-findings that don't fit on the
README's own front page. The [README](../README.md#results-at-a-glance) has
the one-line-per-phase summary and links back into this file's sections; the
non-claims, governing rules, limitations, repository layout, and setup/run
commands all live there, not here.

For what's actually built vs. not (a capability inventory rather than a
results narrative), see [`MODEL_CARD.md`](MODEL_CARD.md). For every material
property and its citation tier, see [`DATA.md`](DATA.md).

## Sequencing

Phase 0 (scaffold, done) -> A (annual quasi-steady core, constant discharge
limit; done to its exit criterion) -> B (targeted dynamic sub-model and
shadow twin; packed bed done to its exit criterion with a Modelica twin,
analytic-limit checks, and an FMU cross-check (run outside this
environment, see P4 below, since this sandbox can't compile or execute
one); molten salt and PCM later got their own closed-form dynamic sub-models, see
C3, but neither has a Modelica twin) -> P0.3 (state-sufficiency test; done
-- scalar SOC found insufficient across the constructed profile family, so
Phase B's curve is documented as trajectory-derived, not a general law) ->
C (coupling and the paired-run experiment; done at MVP scope, one
technology/temperature/profile pair, not the full matrix; original run
superseded by C2 as the shape-isolated comparison) -> C2 (matched-
duration-family sizing fix; removes the unequal-duration confound in C's
original pairing; done, five durations swept, packed bed only) -> P0.4
(start-of-hour discharge capability reference; done -- removes a third
confound from C's original pairing, folded into C2's own sweep) -> P0.5
(MILP simultaneous-cycling prevention; done -- optional
`cycling_prevention_mode`, ahead of ever running against real, sometimes
negative, ENTSO-E prices) -> P1 (modular-area-scaling law; done -- a
specific, checked geometric scaling family, exact 0.0 deviation across a
0.25x-4x sweep, replacing the earlier abstract "same duration ratio"
assumption) -> C3 (full technology-ranking matrix; done -- molten-salt and
PCM dynamic sub-models built, 15 paired cases across 5 technology/temperature
combinations x 3 load profiles, all solved and verified; the SOC-dependent
correction never flips which technology is cheapest, and PCM's own
zero-effect result is a sizing artifact at this design duration, not
evidence its discharge shape does not matter -- stated plainly, not hidden)
-> P2.1 (duration-family capability curves committed as standalone
evidence; done, packed bed only -- P2.2's full swept envelope explicitly
deferred by the roadmap itself, not attempted) -> P3.1 (spatial/temporal
discretisation convergence; done -- the project's own default resolution
reproduces the fine-grid annual dispatch decision to 0.007% cost / 0.14
MWh sizing, validating every prior committed result's numerical resolution
choice rather than merely assuming it) -> P3.2 (correlation-domain
validity checks; done -- every run now records whether its own Reynolds
number falls inside the Wakao-Kaguei correlation's stated domain and warns
loudly if not; every case config in this repository does) -> P3.3 (Ergun
pressure drop and blower parasitic power; done -- reported alongside each
duration's discharge curve, not wired into dispatch.py's own economics;
P3.4, temperature-dependent properties, deliberately not attempted per the
roadmap's own "do not rush this" instruction) -> P4 (FMU/Modelica
verification; done, run outside this environment -- this sandbox cannot
compile or execute an FMU at all (no OpenModelica package reachable, no
Wine), so the model was compiled and cross-checked on the user's own
machine instead, agreeing with the Python shadow twin to within 0.23% of
the full temperature swing over an 8h discharge) -> P5 (economics
sensitivity; done -- storage power CAPEX swept 0x-8x with the
SOC-dependent delta staying essentially flat throughout (+0.019% to
+0.020%), seven secondary parameters swept one-at-a-time, full cost
decomposition and binding-constraint classification at all 31 points;
gas price is the single most powerful lever found, capable of pricing
storage out of the market entirely or tripling it and flipping the system
to full electrification) -> P6 (model-fidelity decision map; done -- 45
grid points across theta_req x tau x 3 profiles, 90 solves, all verified;
the annual objective stays insensitive over most of the domain, but power/
energy sizing collapses from a small bias to complete infeasibility -- the
SOC-dependent model refuses to build any storage at all -- once the
temperature-quality requirement gets high enough, with the exact
threshold depending on design duration; this project's own actual case
configs sit safely outside that regime, which is itself a finding, not an
evasion) -> D (harmonised comparison and sensitivity, TES_SCREEN_SPEC.md
section 7, done in full: D.1 boundary harmonisation table -- surfaces a
real, stated inconsistency in parasitic-load and verification depth
across technologies rather than resolving one; D.2 Morris global
sensitivity screening -- theta_req dominates every other factor
(material cost, heat transfer coefficient, discount rate, price
volatility) by more than an order of magnitude, quantitatively confirming
P6's own cliff with a nonlinearity signature (sigma > mu_star) rather than
a smooth effect, while the heat transfer coefficient itself is essentially
negligible to the sizing decision; D.3 technology-selection map -- packed
bed cheapest at every one of 25 (technology, temperature, duration)
combinations tested, extending C3's ranking-never-flips finding across
the full duration dimension). Real ENTSO-E price data (the roadmap's own
P7) is being pulled forward ahead of its default sequencing, at explicit
user request; not yet wired in as of this commit (pending an
ENTSOE_API_KEY).

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

**What has not been done, and why -- confirmed, not just assumed (roadmap
P4).** No OpenModelica toolchain (`omc`) is installed in this working
environment, so the Modelica model above has been authored but never
compiled, and the FMU-vs-shadow-twin cross-check that the build spec calls
"the single strongest verification story available here" has not been
run. This was re-checked directly (not re-asserted from an earlier
session's note): `apt-cache search openmodelica` finds no package in this
container's default repositories, and the container's own outbound
network gateway returns a hard `403` to OpenModelica's own distribution
host (`build.openmodelica.org`) and to Ubuntu's `ppa.launchpadcontent.net`
mirror -- an allowlist-based policy, not a transient failure, so no retry
or alternative mirror would succeed either. `fmu.py` (ported from
OpenSteamOpt's identical `find_omc()` pattern) fails loudly and
specifically when the toolchain is absent rather than silently skipping;
`tests/test_modelica_contract.py` statically checks the authored Modelica
source instead, the same toolchain-independent pattern OpenSteamOpt itself
uses for CI. Molten-salt and PCM now have their own closed-form dynamic
sub-models (see Phase C3), but neither has a Modelica twin: only packed
bed's physics was judged to justify one, and a compiled cross-check for it
remains blocked by the same environment constraint.

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

This was one technology (packed bed) at one duration family; see
[Phase C3](#phase-c3-full-technology-ranking-matrix) below for the same
correction applied across every technology, temperature, and load profile
this project has a dynamic sub-model for.

## Phase C3: full technology-ranking matrix

**The finding, stated first and plainly: the SOC-dependent discharge-limit
correction does not change which technology is cheapest, anywhere in this
matrix.** This is the question Phase C2 explicitly could not answer (only
packed bed had a Phase B dynamic sub-model): with `molten_salt_dynamics.py`
and `pcm_dynamics.py` now built (this session), every technology this
project can model is compared, at every process temperature it is
configured for, under every synthetic load profile, all at the same
matched design duration (`storage.design_duration_hours = 6h`, P0.1's
sizing fix) and the same P0.2/P0.4 corrections Phase C2 established.

**Scope: 5 valid technology/temperature combinations, not 6.** Packed bed
and molten salt each have a 300 C and a 400 C case; PCM only has a 300 C
case (sodium nitrate's ~306 C melting point does not sit usefully close to
a 400 C process, and no suitable high-temperature nitrate-salt PCM
composition was found -- `configs/pcm_300c_flat.yaml`'s own comment,
unchanged by this experiment). x 3 load profiles (`flat`, `two_shift`,
`seasonal`, `synthetic_profiles.py`) = **15 paired cases, 30 solves, every
one `optimal` and independently verified.**

| Temperature | Profile | Technologies compared | Cheapest (constant) | Cheapest (SOC-dependent) | Ranking flipped? |
|---:|---|---|---|---|:---:|
| 300 C | flat | molten_salt, packed_bed, pcm | packed_bed | packed_bed | No |
| 300 C | two_shift | molten_salt, packed_bed, pcm | packed_bed | packed_bed | No |
| 300 C | seasonal | molten_salt, packed_bed, pcm | packed_bed | packed_bed | No |
| 400 C | flat | molten_salt, packed_bed | packed_bed | packed_bed | No |
| 400 C | two_shift | molten_salt, packed_bed | packed_bed | packed_bed | No |
| 400 C | seasonal | molten_salt, packed_bed | packed_bed | packed_bed | No |

Packed bed is cheapest in every group, under both formulations --
**including now that packed bed's own quantified blower parasitic load is
actually priced**, not just reported. An earlier version of this matrix
computed packed bed's Ergun/blower power (P3.3) but never charged it to
any technology's operating cost -- a real fairness gap, since packed bed
was winning a comparison partly on the strength of an operating cost the
model itself excluded for that one technology, while molten salt and PCM
never had one to exclude in the first place. `dispatch.py`'s
`blower_specific_power_mw_per_mw` now prices `ratio * p_dis[t]` at the
same hour's electricity rate for every packed-bed case here (ratio =
0.0109 MW electric per MW thermal at this matrix's tau=6h design point --
lower than P3.3's own often-quoted ~8.6% figure, which is reported at a
much shorter, higher-mass-flow 2h duration; Ergun's pressure drop is
superlinear in mass flow, so the ratio itself is duration-dependent, not
a fixed technology constant). The full per-case deltas, with the added
blower cost broken out:

| Technology | Temp (C) | Profile | Constant cost (EUR/yr) | SOC-dependent cost (EUR/yr) | Delta | Blower cost (EUR/yr, both legs) | Delta E_cap (MWh) |
|---|---:|---|---:|---:|---:|---:|---:|
| packed_bed | 300 | flat | 4,004,309.70 | 4,005,145.32 | +0.021% | ~10,489 / ~10,532 | 0.00 |
| packed_bed | 300 | two_shift | 2,817,116.20 | 2,817,469.77 | +0.013% | ~15,866 / ~15,891 | 0.00 |
| packed_bed | 300 | seasonal | 2,890,012.76 | 2,890,904.65 | +0.031% | ~14,920 / ~14,998 | +0.02 |
| packed_bed | 400 | flat | 4,004,309.70 | 4,005,145.32 | +0.021% | ~10,489 / ~10,532 | 0.00 |
| packed_bed | 400 | two_shift | 2,817,116.20 | 2,817,469.77 | +0.013% | ~15,866 / ~15,891 | 0.00 |
| packed_bed | 400 | seasonal | 2,890,012.76 | 2,890,904.65 | +0.031% | ~14,920 / ~14,998 | +0.02 |
| molten_salt | 300 | flat | 4,075,713.26 | 4,075,957.34 | +0.006% | 0 (no model) | ~0.00 |
| molten_salt | 300 | two_shift | 2,944,030.16 | 2,944,140.94 | +0.004% | 0 (no model) | 0.00 |
| molten_salt | 300 | seasonal | 2,991,108.49 | 2,991,423.82 | +0.011% | 0 (no model) | +0.07 |
| molten_salt | 400 | flat | 4,075,713.26 | 4,075,957.34 | +0.006% | 0 (no model) | ~0.00 |
| molten_salt | 400 | two_shift | 2,944,030.16 | 2,944,140.94 | +0.004% | 0 (no model) | 0.00 |
| molten_salt | 400 | seasonal | 2,991,108.49 | 2,991,423.82 | +0.011% | 0 (no model) | +0.07 |
| pcm | 300 | flat | 4,178,028.84 | 4,178,028.84 | +0.000% | 0 (no model) | 0.00 |
| pcm | 300 | two_shift | 3,059,527.90 | 3,059,527.90 | +0.000% | 0 (no model) | 0.00 |
| pcm | 300 | seasonal | 3,132,422.34 | 3,132,422.34 | +0.000% | 0 (no model) | 0.00 |

Two things worth stating plainly about this fix's actual effect. First,
**it moved the absolute numbers, not the finding**: pricing the blower
raised packed bed's own annual cost by ~10,500-15,900 EUR/yr (about
0.26-0.56% of its own total cost) at every (temperature, profile) point,
and packed bed is still cheaper than molten salt by roughly
70,000-100,000 EUR/yr and PCM by over 170,000 EUR/yr at every point -- an
order of magnitude more margin than the blower cost consumed. The
constant-vs-SOC-dependent delta itself barely moved (e.g. 300 C flat:
+0.020% before this fix, +0.021% after), exactly as expected: the same
fixed ratio applies to `p_dis[t]` identically in both legs of the
comparison, so it is not a new source of asymmetry between the two
formulations, only a real cost previously missing from packed bed's
comparison against the *other two* technologies. Second, molten salt and
PCM's own numbers above are bit-identical to before this fix (confirmed
against the previously committed values): they pass `None` for
`blower_specific_power_mw_per_mw` and always have, so nothing about their
own cost changed -- only packed bed's did, which is exactly the asymmetry
this fix was meant to correct, not eliminate. **The asymmetry is smaller
now, not gone**: molten salt and PCM still have no parasitic-load model
of any kind (D.1's boundary-harmonisation table below still flags this).

**Molten salt's own correction is smaller than packed bed's at every
matched (temperature, profile) pair** (e.g. 300 C flat: +0.006% vs.
+0.021%) -- consistent with this project's own opening hypothesis and the
control-case comment already in `configs/molten_salt_300c_flat.yaml`
("molten salt discharges at a near-constant temperature, so the
SOC-dependent correction should barely move it"). It is not literally
zero: `molten_salt_dynamics.py`'s own `heel_fraction` taper (deliverable
flow declining linearly across the last 5% of tank inventory,
[assumption]) does occasionally bind, which is why the two-tank model's
own delta is small but nonzero rather than exactly 0.

**PCM's delta is exactly 0.000% in every case, but for a reason that must
not be glossed over: the model builds exactly zero PCM storage capacity at
this matched design duration, under both formulations, in every profile.**
`outputs/phase_c_full_matrix/run_manifest.json` shows `e_cap_mwh` at
(numerically) 0 for all six PCM entries. PCM's combined capex
(80,000 EUR/MWh-th + 40,000 EUR/MW, `configs/pcm_300c_flat.yaml`) is far
above packed bed's (7,000 + 20,000) and molten salt's (26,000 + 60,000);
at `design_duration_hours = 6h`, tying required power directly to
`E_cap / 6`, it is cheaper for the optimiser to serve the load entirely
from the electric heater and backup boiler than to build any PCM storage
at all. **The SOC-dependent discharge-limit correction is therefore never
actually exercised for PCM in this matrix** -- its "delta = 0.000%" is a
sizing artifact of this specific design duration and cost structure, not
evidence that PCM's three-regime discharge shape is inconsequential. A
shorter or longer design duration, or different PCM capex assumptions,
could change this; that sweep was not run here. **Update: Phase D.3's own
duration sweep (below) later ran the duration half of this** and found
PCM does build nonzero capacity under the constant-limit formulation at
shorter durations (2h, 4h) -- see [D.3](#d3-technology-selection-map) for
the numbers. A dedicated PCM capex sweep is still not run.

**Why the 300 C and 400 C rows are pairwise identical for packed bed and
for molten salt.** This is expected, not a bug, and traces to this specific
matrix's own parameter choices, the same way the already-documented Phase A
temperature-agnostic-dispatch limitation does:

- **Packed bed:** `configs/packed_bed_300c_flat.yaml`
  (`temperature_max_c=400`, `temperature_min_c=320`) and
  `packed_bed_400c_flat.yaml` (`500`/`420`) both have exactly the same
  80 C span, and the bed model has no absolute-temperature dependence
  (constant material properties) -- so the simulated normalized discharge
  curve is identical between the two cases, and so is every downstream
  number.
- **Molten salt:** `molten_salt_dynamics.py` deliberately holds the hot/cold
  tank temperatures fixed at 565 C/290 C for both process-temperature
  cases (see the module's own docstring), since the two YAML configs use
  `temperature_min_c` for two different concepts and only
  `process_temperature_c` should vary between them. Process temperature
  enters the curve only through a pass/fail quality gate that both 300 C
  and 400 C clear trivially (565 C comfortably exceeds either), so the two
  temperature cases are, by this model's own construction, the same case.

**The headline, restated plainly.** Once matched-duration sizing (P0.1),
consistent temperature referencing (P0.2), start-of-hour discharge
capability (P0.4), and packed bed's own blower parasitic-load cost are all
applied, the SOC-dependent discharge-limit correction moves total
annualised cost by at most +0.031% anywhere in this 15-case matrix, never
changes which technology is cheapest in any of the 6 (temperature,
profile) groups, and for two of the three technologies (molten salt, and
especially PCM) the effect is smaller still or entirely unexercised. The
technology ranking Phase A's constant-limit baseline already found (packed
bed cheapest, PCM most expensive) is unchanged by moving to the corrected
SOC-dependent model, and survives correctly pricing the one operating cost
this project can actually quantify that it had previously been excluding
for the technology that wins.

**A staleness note, stated rather than left for a reader to discover.**
Only this section (C3) and Phase D.3 below have been re-run against the
blower-parasitic-cost fix. Phase C2 above, P5, P6, and D.2 all still
report costs computed *before* that fix -- their own packed-bed absolute
cost numbers do not include the blower term, though the fix's own effect
on any of them would be small and one-sided (it raises packed bed's own
cost by under 1% and applies identically to both compared legs in every
one of those experiments too, per C3's own finding above), not a reason
to doubt their qualitative conclusions, only a reason not to quote their
absolute EUR figures as if they already included it.

**One figure per technology**, each overlaying the analytic deliverable-power
curve, its 5-segment piecewise fit, and the constant-limit reference power,
at every process temperature that technology has:

![Packed bed discharge curves](outputs/phase_c_full_matrix/figures/packed_bed.png)
![Molten salt discharge curves](outputs/phase_c_full_matrix/figures/molten_salt.png)
![PCM discharge curves](outputs/phase_c_full_matrix/figures/pcm.png)

The packed-bed and molten-salt figures visibly confirm the "pairwise
identical" note above: their 300 C and 400 C curves are drawn exactly on
top of each other. The PCM figure shows the three-regime shape
(superheat ramp, latent plateau, subcooled ramp) the piecewise fit
approximates -- worth looking at even though, per the finding above, the LP
never actually built any PCM capacity to use it against.

**How this was built.** `scripts/run_phase_c_full_matrix_experiment.py`
builds one discharge curve per (technology, temperature) combination --
reused across all three load profiles, since the curve depends on the
technology's own physics and process temperature, not on how demand varies
over the year -- via each technology's own `mass_flow_for_target_duration`
at `tau = 6h` (mirroring `discharge_curve.mass_flow_for_target_duration`'s
closed-form approach for packed bed; `molten_salt_dynamics.py` and
`pcm_dynamics.py` each implement their own), then fits it through the same
technology-agnostic piecewise construction
(`discharge_curve.fit_piecewise_curve_from_power_curve`) all three
technologies now share. Every fit's overestimate against its own source
curve is at most 4.3e-6 MW (packed bed; molten salt and PCM both exactly
0.0), confirmed in the run manifest, not assumed. Every number above
traces to `outputs/phase_c_full_matrix/`: `case_deltas.csv` (the 15-row
per-case table), `ranking_table.csv` (the 6-row ranking-flip table),
`run_manifest.json` (every case's full KPIs, solver status, and
verification result), and `figures/`.

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

## P1: the modular-area-scaling law

**The assumption, stated plainly for the first time.** The dispatch LP
rescales one reference bed's fitted discharge curve to whatever storage
energy capacity a case actually sizes, linearly
(`p_dis[t] <= a_i*level[t] + b_i*E_cap`) -- implicitly assuming the
*normalized* curve (state of charge vs. fraction of full-charge power) has
the same shape at any physical bed size, not just the one the reference
bed happens to be. Every result in this repository already depends on this
holding; before P1 it rested on an abstract "same duration ratio" argument
with no stated physical mechanism for why it should.

**A specific, defensible scaling family, not an abstract one.**
`packed_bed_dynamics.scale_parallel_bed(reference_config,
reference_mass_flow_kg_per_s, scale_factor)` implements the roadmap's own
"modular area scaling": cross-sectional area and mass flow scale together
by the same factor; bed length, particle diameter, porosity, material
properties, and node count all stay fixed. Under this family, mass flux
`G = m_dot/A` -- and therefore Reynolds number, the Wakao-Kaguei Nusselt
number, the volumetric heat transfer coefficient, and every coefficient in
`simulate_discharge`'s governing PDE, none of which reference area
directly -- stays exactly fixed, not merely approximately. The simulated
temperature field is therefore identical at every scale factor; only the
*totals* built from it scale with area, and a normalized curve, a ratio of
two equally-scaled quantities, should collapse onto the reference exactly.
The function returns the scaled config *and* the scaled mass flow
together, not the config alone: scaling area without mass flow by the same
factor would silently break the fixed-mass-flux invariant the whole family
depends on.

**Checked, not assumed.** `scripts/run_scaling_law_experiment.py` sweeps
five scale factors (0.25x, 0.5x, 1x, 2x, 4x of the default reference bed's
10 m² cross-section) and compares each scaled run's normalized curve
against the reference (1x) run's, at every recorded timestep, in both
state of charge and power fraction.

| Scale factor | Area (m²) | Mass flow (kg/s) | k = P_ref/E_ref (MW/MWh) | Max SOC deviation | Max power-fraction deviation |
|---:|---:|---:|---:|---:|---:|
| 0.25x | 2.5 | 0.75 | 0.205968 | 0.0 | 0.0 |
| 0.5x | 5.0 | 1.50 | 0.205968 | 0.0 | 0.0 |
| 1x | 10.0 | 3.00 | 0.205968 | 0.0 | 0.0 |
| 2x | 20.0 | 6.00 | 0.205968 | 0.0 | 0.0 |
| 4x | 40.0 | 12.00 | 0.205968 | 0.0 | 0.0 |

**Exit criterion met, exactly, not just within tolerance**: the maximum
deviation across every scale factor is `0.0`, against an [assumption]
threshold of `1e-6` set to actually catch a real breakdown of the family
rather than pass by construction. The fitted curve's own
`k = P_reference/E_reference` ratio -- what `dispatch.py`'s
`duration_matched` branch checks a discharge curve against before
accepting it (P0.1) -- is likewise identical to machine precision across
all five scale factors. This is a stronger result than "small enough to
support the approximation": for this bed model, under this specific
scaling family, the approximation is exact, because the underlying physics
genuinely does not depend on cross-sectional area at all. Every number
above traces to `outputs/scaling_law/`: the full normalized-curve table
across all five scale factors and a manifest with the exit-criterion
verdict.

**What this does and does not establish.** This confirms the "same
reference bed, physically bigger or smaller via area" scaling dispatch.py
already performs implicitly for every case in this repository -- checked
against this bed model's own physics (P1's governing rule 1 sense of
"verified"), not against independent measured data. It is a
different operation from P0.1's `mass_flow_for_target_duration`, which
varies mass flow at *fixed* area to reach a target design duration --
deliberately changing mass flux (and therefore the curve's own shape) per
duration, not preserving it. The two are complementary, not competing:
P0.1 answers "what does a bed of a different *duration* look like,"
P1 answers "does a bed of a different *size* at the same duration look the
same, just bigger."

## P2.1: duration-family capability curves as committed evidence

**What this adds, and what it does not.** Every prior duration-family run
(C2, C3) builds a discharge curve at each design duration *internally*, to
feed a pair of annual dispatch solves, and records only the paired-solve
KPIs on disk -- the curve itself, and the flow physics that produced it,
were a means to an end, not committed evidence. P2.1 asks for the curves
themselves, at the same duration grid C2 already sweeps (2h-12h), each with
a manifest recording geometry, mass flow and mass flux, Reynolds/Prandtl/
Nusselt numbers, the volumetric heat transfer coefficient, temperatures,
resolution, the process quality threshold, and the scaling family
definition -- self-contained enough to audit by hand without re-running
anything. `scripts/run_capability_curves_experiment.py` does exactly that
and nothing more: **P2.2 (a full swept capability envelope choosing the
highest net-useful power after parasitics at each physical state) is
explicitly deferred by the roadmap itself** ("Do not jump to this until
the simpler duration-family comparison is correct") and is not attempted.

**Scope: packed bed only.** The roadmap's own framing of this section is
specific to the packed bed's mass-flow/thermocline trade-off ("higher flow
-> potentially lower outlet temperature / faster thermocline movement").
Two-tank molten salt has no thermocline to move at all
(`molten_salt_dynamics.py`'s own module docstring), and PCM's near-
isothermal latent plateau does not develop one either, so neither
technology carries the design tension this section exists to
characterise. Both technologies already have their own
`mass_flow_for_target_duration` (built for Phase C3), so extending this
script to them would be mechanical if ever needed; the roadmap does not
ask for it here, so it was not done.

| Duration (tau) | Mass flow (kg/s) | Mass flux (kg/m2s) | Re | Pr | Nu | h_v (W/m3K) | Fit max overestimate (MW) |
|---:|---:|---:|---:|---:|---:|---:|---:|
| 2h | 7.28 | 0.728 | 704.8 | 0.741 | 52.91 | 9,608 | 6.8e-05 |
| 4h | 3.64 | 0.364 | 352.4 | 0.741 | 35.59 | 6,463 | 1.2e-05 |
| 6h | 2.43 | 0.243 | 234.9 | 0.741 | 28.33 | 5,146 | 4.3e-06 |
| 8h | 1.82 | 0.182 | 176.2 | 0.741 | 24.16 | 4,387 | 2.1e-06 |
| 12h | 1.21 | 0.121 | 117.5 | 0.741 | 19.37 | 3,518 | 8.0e-07 |

(Both `packed_bed_300c_flat` and `packed_bed_400c_flat` produce bit-identical
rows -- the same expected consequence of the two configs sharing an
identical 80 C span already documented under [Phase C3](#phase-c3-full-technology-ranking-matrix)
above, reproduced here rather than treated as a new surprise.)

**A real, if minor, pattern the curve data itself surfaces:** the
piecewise fit's own safety margin against overestimating deliverable power
tightens monotonically as duration shortens -- 6.8e-05 MW at 2h down to
8.0e-07 MW at 12h, a ~100x range, all still far below anything that would
matter at MW-scale dispatch. Shorter durations draw at a higher mass flow
(and therefore mass flux, Reynolds number, and heat transfer coefficient),
which steepens the discharge curve's shape near depletion; a fixed
5-segment piecewise fit tracks a steeper curve slightly less tightly. This
was already implicitly present in C2's own segment-count robustness check
(3-12 segments barely move the sized answer) but had not previously been
tabulated across the duration grid itself.

Every number above traces to `outputs/capability_curves/`: one
`manifest.json`, `discharge_power_curve.csv`, and
`piecewise_curve_breakpoints.csv` per (duration, case) under
`tau_{X}h/{case_name}/`, plus a top-level `run_manifest.json` aggregating
every case's full duration sweep and stating the scaling-family definition
explicitly (the duration family P0.1/P2.1 both use -- fixed geometry,
mass flow varies per duration -- is a different operation from P1's
modular-area family -- fixed mass flux, area varies at fixed duration --
restated here since P2.1 is the section that actually asked for it to be
recorded alongside the curve data).

## P3: dynamic-model hardening

### P3.1: spatial and temporal discretisation convergence

**The finding, stated first and plainly: this project's own default
resolution (`n_nodes=40`) already gives the same annual dispatch decision
a much finer grid would, even though its raw discharge-curve shape carries
a real, non-trivial local error.** `scripts/run_convergence_experiment.py`
sweeps node count (20, 40, 80, 160) and timestep count (500, 1000, 2000,
4000) independently against a finer reference (`n_nodes=160,
n_steps=4000`), then -- per the roadmap's own instruction that this is
"the strongest metric" -- checks whether the SOC-dependent duration-matched
dispatch LP's own sized `E_cap`, power rating, and total cost move with
resolution, not just the raw curve.

| Sweep | Max outlet-temperature deviation (C) | Breakthrough-time deviation (h) | E_cap deviation (MWh) | Total-cost deviation |
|---|---:|---:|---:|---:|
| Spatial, N=20 (steps=4000) | 10.23 | -0.081 | +0.257 | +0.0154% |
| Spatial, N=40 (steps=4000) | 5.57 | -0.033 | +0.131 | +0.0069% |
| Spatial, N=80 (steps=4000) | 2.19 | -0.012 | +0.038 | +0.0023% |
| Temporal, steps=500 (N=160) | 1.26 | +0.015 | +0.018 | +0.0012% |
| Temporal, steps=1000 (N=160) | 0.56 | +0.003 | +0.008 | +0.0005% |
| Temporal, steps=2000 (N=160) | 0.19 | +0.003 | +0.003 | +0.0002% |
| **Project default (N=40, steps=1500)** | **5.71** | **-0.033** | **+0.136** | **+0.0071%** |

(Reference: N=160, steps=4000 -- 0 deviation from itself by construction,
omitted. "Breakthrough time" here is the standard packed-bed-literature
midpoint definition -- outlet temperature crossing halfway between the
initial and inlet temperatures -- not this project's own process-quality
threshold: every packed-bed config in this repository holds
`inlet_temperature_c` a fixed 20 C above its own `process_temperature_c`
by design, so outlet temperature, which only ever approaches the inlet
temperature from above, can never actually cross that threshold in any
finite discharge; a threshold tied to it would report "never breaks
through" at every resolution and say nothing about discretisation error.)

**Two real, separable results here.** First: node count, not timestep
count, dominates the discretisation error -- the spatial sweep's outlet
deviation (10.23 C at N=20) is an order of magnitude larger than the
temporal sweep's (1.26 C at the coarsest, 500-step, point), consistent with
`simulate_discharge`'s own backward-Euler time-stepping being
unconditionally stable (temporal error shrinks fast) while spatial
resolution controls how sharply the thermocline front itself is resolved.
Second, and more important: **despite a genuinely large ~5.7 C / ~9-10
percentage-point curve-shape error at the project's own default N=40 (see
the breakpoint deviations in `outputs/convergence/run_manifest.json`), the
downstream annual dispatch decision moves by only 0.007% in total cost and
0.14 MWh in sized energy capacity relative to the fine-grid reference** --
against a deliberately strict [assumption] 1.0% convergence threshold.
**Every prior Phase C/C2/C3/P2.1 result in this repository, all of which
used this same N=40 default, is therefore confirmed to already be
converged at the level that actually matters (the sizing/cost decision),
not merely assumed to be** -- checked against a finer-resolution run of
this bed model's own governing equations (this project's own "verified,"
not "validated," sense: governing rule 1), applied to its own numerical
resolution choice rather than only its governing physics.

Every number above traces to `outputs/convergence/run_manifest.json`: the
full spatial sweep, temporal sweep, and project-default entry, each with
its own curve-shape deviations and paired dispatch-LP KPIs.

### P3.2: correlation-domain validity checks

The Wakao-Kaguei correlation `flow_diagnostics` uses (`Nu = 2 +
1.1*Re^0.6*Pr^(1/3)`) is only stated valid over `15 < Re < 8500`
(`WAKAO_KAGUEI_REYNOLDS_VALIDITY_RANGE`, `packed_bed_dynamics.py`). Every
call now records whether its own Reynolds number actually falls inside
that range (`FlowDiagnostics.reynolds_within_correlation_validity_range`)
and raises a loud `RuntimeWarning` -- not a silent extrapolation -- the
moment it does not (`tests/test_packed_bed_dynamics.py`'s own P3.2 block
forces this with a deliberately tiny mass flux and checks the warning
fires). Every mass flow this repository's own case configs and duration
sweeps actually use stays comfortably inside the validity domain: Re
ranges from 117 (12h design duration) to 705 (2h design duration) across
the full `outputs/capability_curves/` duration grid, both well clear of
the [15, 8500] bounds -- recorded explicitly in each duration's own
`manifest.json`, not merely asserted.

### P3.3: Ergun pressure drop and blower parasitic power

**What this adds.** `ergun_pressure_drop_and_blower_power` computes the
Ergun-equation pressure drop across the bed (Ergun, 1952 -- the textbook-
standard laminar-plus-turbulent packed-bed correlation) at a given mass
flow, and the blower electric power it implies at an explicit, [assumption]-
labelled `blower_efficiency` (0.65, typical industrial centrifugal blower
range 0.55-0.75; `docs/DATA.md`) -- an optional, documented extension per
the roadmap's own instruction, reported alongside each duration's discharge
curve in `outputs/capability_curves/`, **not wired into `dispatch.py`'s own
economics**: every case's objective still uses
`economics.storage_capex_eur_per_mw` as its blower/ducting/HX capital-cost
proxy exactly as before, so no existing committed result changes. This
makes that proxy's *operating*-cost counterpart computable and reportable
for the first time, rather than silently replacing it.

| Design duration (tau) | Mass flow (kg/s) | Blower power (W) | Blower power / reference rated thermal power |
|---:|---:|---:|---:|
| 2h | 7.28 | 54,615 | 8.64% |
| 4h | 3.64 | 7,291 | 2.31% |
| 6h | 2.43 | 2,298 | 1.09% |
| 8h | 1.82 | 1,027 | 0.65% |
| 12h | 1.21 | 339 | 0.32% |

**This is exactly the physical trade-off the roadmap named as the reason
to add it.** Shorter design durations mean higher mass flow for the same
reference energy capacity, and Ergun's own turbulent term scales with the
*square* of superficial velocity: blower parasitic power at the shortest
(2h) duration is over 25x larger, as a fraction of rated thermal power,
than at the longest (12h) duration tested. In absolute terms it stays
small throughout this project's own reference-bed scale (tens of watts to
tens of kilowatts against a store rated in the hundreds of kW to low MW),
but the *trend* -- parasitic losses growing sharply as design duration
shortens -- is a real, physically grounded operating penalty this
project's economics did not previously capture at all, exactly the
"vague blower/ducting/HX power CAPEX story" the roadmap names. Wiring it
into the dispatch LP's own objective (so shorter-duration, higher-flow
designs pay for their own parasitic losses in the annual cost, not just an
external observation) is a natural next step, not attempted here.

Every number above traces to each duration's own `manifest.json` under
`outputs/capability_curves/tau_{X}h/{case_name}/pressure_drop`.

### P3.4: temperature-dependent properties -- deliberately not attempted

The roadmap's own instruction for this item is "do not rush this," and
explicitly asks that current air-property values be re-verified against a
primary/open source *first*, before deciding whether constant properties
are even inadequate: "a constant-property model with a sensitivity check
is preferable to a black-box property dependency nobody can explain in an
interview." Not attempted in this pass, consistent with that instruction
rather than as an oversight.

## P4: FMU/Modelica verification -- done, run outside this environment

The roadmap calls the FMU-vs-shadow-twin cross-check "the single strongest
verification story available here." This working environment cannot
compile or execute the FMU itself, full stop: `apt-cache search
openmodelica` finds no package in this container's default repositories,
the container's own outbound network gateway returns a hard `403` to
OpenModelica's own distribution host, and the FMU that was eventually
compiled elsewhere turned out to contain only Windows (`win64`) binaries,
which this Linux sandbox with no Wine cannot load either. Every step below
therefore ran on the user's own machine (OpenModelica/OMEdit, Windows),
with the resulting artifacts reported back and committed here
(`outputs/fmu_cross_check/`) -- this project's only result in this
document that was not produced inside this session.

**Getting there took three real attempts, each one informative, not just
a clean run:**

1. Compiling `modelica/tes_screen/package.mo`'s `PackedBedThermocline`
   model surfaced a bug this session had no way to catch on its own: the
   package declared `package TesScreen`/`end TesScreen;` inside a
   directory named `tes_screen`, violating Modelica's file-system
   package-name-matching convention. OMEdit's error named it exactly;
   fixed here, along with every reference to the old name
   (`scripts/build_packed_bed_fmu.mos`, `tests/test_modelica_contract.py`).
2. The first cross-check run (a uniform 60s FMU communication step)
   crashed outright (`fmi2GetReal failed`, `division leads to inf or nan`).
   The second (a uniform 0.05s step, 1200x finer) didn't crash, but the
   outlet temperature blew up to ~-4.6e10 C by t=6.6s -- then
   *recovered*, matching the Python shadow twin to <1e-3 C for the
   remaining ~1780s of that diagnostic run. That pattern (huge but
   bounded, decaying back to correct behaviour) diagnoses a transient
   numerical artifact, not a persistent instability: `PackedBedThermocline`
   imposes an instantaneous t=0 step change from a uniform 400 C bed to a
   320 C inlet, and `fluidCapacityPerVolume` (245 J/(m3.K)) is ~4600x
   below `solidCapacityPerVolume` (1.14e6), so that step change drives an
   extremely fast inlet boundary-layer transient the FMU's internal
   Co-Simulation solver needs a much finer communication step to resolve
   -- confirmed by the FMU's own `modelDescription.xml`, which publishes
   `DefaultExperiment stepSize="0.002"`, 25x finer than the step that
   still blew up.
3. `tes_screen.fmu.simulate_fmu_staged` (added for this) runs the FMU
   with a *variable* communication step via fmpy's low-level `FMU2Slave`
   interface rather than one uniform step: 90s at the FMU's own
   recommended 0.002s to get safely past the transient, then the
   already-validated 0.05s for the remainder of the discharge. That run
   is the result below.

**Result** (`scripts/run_fmu_cross_check_experiment.py`, full 8h
discharge, `mass_flow=3.0 kg/s`, `inlet=320 C`, `initial=400 C`, and a
*fixed* `h_v=5800 W/(m3.K)` on both sides -- the Modelica model's own
fixed parameter, passed to the Python twin via
`heat_transfer_coefficient_override_w_per_m3k` so neither side silently
recomputes it and turns a solver comparison into a hidden physics
comparison):

| Metric | Value |
|---|---:|
| Max absolute outlet-temperature deviation | 0.184 C (over an 80 C discharge swing) |
| RMSE (outlet temperature) | 0.092 C |
| Breakthrough-time deviation | -13.7 s (FMU crosses the midpoint 13.7s before the twin, of a ~17,260s/4.8h breakthrough) |
| Relative delivered-energy deviation | +0.0029% |

The deviation trace (`outputs/fmu_cross_check/fmu_vs_twin.png`) is a
smooth curve, not noise: it peaks near the steepest part of the
thermocline front (~t=3.7h, +0.15 C) and troughs during the descent
(~t=5.8h, -0.18 C) -- the expected signature of two independent numerical
schemes (the Python twin's own hand-derived implicit backward-Euler
stepping vs. OpenModelica's internal DAE solver) resolving the same
moving front slightly differently, not a modelling discrepancy. **Two
independent implementations of Schumann's governing equations, solved by
two genuinely different numerical methods, agree to within 0.23% of the
full temperature swing and 0.003% of delivered energy over an 8-hour
transient.** This is "verified," in this project's own stated sense
(governing rule 1): checked against an independent implementation of the
same physics, not against measured data -- but it is the strongest such
check in this repository, exactly as the roadmap said it would be.

## P5: economics sensitivity, not one assumed number

**The point of this section, stated as the roadmap itself states it:**
this project's headline results (Phase A, C2, C3) each rest on one assumed
value per economic parameter -- most visibly `storage_capex_eur_per_mw`,
which `docs/DATA.md` itself already flags as having "no literature figure
found." Rather than search harder for a single citation and treat it as
universal, `scripts/run_economics_sensitivity_experiment.py` sweeps every
parameter the roadmap names, for one representative case
(`packed_bed_300c_flat`, flat profile, duration-matched at tau=6h, both
discharge-limit formulations), and reports the full cost decomposition and
which constraint actually binds at every point -- 31 sensitivity points,
62 solves, all `optimal` and independently verified, every cost
decomposition cross-checked to reproduce the solver's own objective
exactly.

**A coupling worth stating up front.** Duration-matched sizing ties power
to `E_cap / tau` identically in both formulations (P0.1) -- necessary to
keep the constant-vs-SOC-dependent comparison unconfounded, per this
repository's own hard-won lesson -- but it also means storage power CAPEX
(P5.1) and storage energy CAPEX (P5.2) are not fully decoupled here: both
ultimately scale the same combined per-MWh capex rate
(`storage_capex_eur_per_mwh + storage_capex_eur_per_mw / tau`), since
power is never an independent sizing decision in this mode. A fully
decoupled power-CAPEX sensitivity would need non-duration-matched sizing,
reopening the unequal-sizing-degrees-of-freedom confound P0.1 fixed;
matched sizing was kept instead, for consistency with every other paired
comparison in this repository.

### P5.1: storage power CAPEX (0x-8x of the assumed value)

| Multiplier | Constant E_cap (MWh) | SOC-dependent E_cap (MWh) | Constant cost (EUR/yr) | SOC-dependent cost (EUR/yr) | Delta | Binding constraint |
|---:|---:|---:|---:|---:|---:|---|
| 0x | 59.54 | 59.78 | 3,978,543 | 3,979,302 | +0.0191% | electric heater capacity |
| 0.25x | 59.54 | 59.54 | 3,982,425 | 3,983,190 | +0.0192% | electric heater capacity |
| 0.5x | 59.53 | 59.54 | 3,986,306 | 3,987,071 | +0.0192% | electric heater capacity |
| 1x (assumed) | 54.99 | 55.20 | 3,993,618 | 3,994,416 | +0.0200% | electric heater capacity |
| 2x | 50.43 | 50.49 | 4,007,471 | 4,008,267 | +0.0199% | electric heater capacity |
| 4x | 41.30 | 41.37 | 4,031,721 | 4,032,497 | +0.0192% | electric heater capacity |
| 8x | 36.73 | 36.73 | 4,072,017 | 4,072,829 | +0.0199% | electric heater capacity |

**Finding: sized capacity responds monotonically to power CAPEX (59.5 to
36.7 MWh across the sweep, as expected -- more expensive power makes less
storage worthwhile), but the SOC-dependent-vs-constant cost delta barely
moves at all (+0.0191% to +0.0200% across an 8x range in the assumed
value).** The discharge-limit-shape effect this whole project measures is,
at least for this case, essentially insensitive to how the storage power
CAPEX assumption is set -- a real robustness result for the headline
finding, not merely a consequence of narrow bounds (0x to 8x is a
deliberately wide, roadmap-suggested range).

### P5.2: secondary sensitivities (one axis at a time)

| Axis | Value | Constant E_cap (MWh) | SOC-dependent E_cap (MWh) | Delta | Binding constraint |
|---|---:|---:|---:|---:|---|
| Energy CAPEX | 0.5x | 59.54 | 59.87 | +0.0190% | electric heater capacity |
| Energy CAPEX | 1x | 54.99 | 55.20 | +0.0200% | electric heater capacity |
| Energy CAPEX | 2x | 45.87 | 45.87 | +0.0195% | electric heater capacity |
| Gas price | 0.5x | 0.00 | 0.00 | **+0.0000%** | **storage priced out entirely** |
| Gas price | 1x | 54.99 | 55.20 | +0.0200% | electric heater capacity |
| Gas price | 2x | 84.95 | 89.33 | **+0.0647%** | electric heater capacity |
| Carbon price | 0.5x | 41.30 | 41.30 | +0.0036% | electric heater capacity |
| Carbon price | 1x | 54.99 | 55.20 | +0.0200% | electric heater capacity |
| Carbon price | 2x | 68.63 | 71.13 | +0.0163% | electric heater capacity |
| Heater efficiency | 0.90 | 33.10 | 33.23 | +0.0039% | electric heater capacity |
| Heater efficiency | 0.95 | 44.19 | 44.53 | +0.0089% | electric heater capacity |
| Heater efficiency | 0.99 (assumed) | 54.99 | 55.20 | +0.0200% | electric heater capacity |
| Standing loss | 0.5x | 55.14 | 55.45 | +0.0184% | electric heater capacity |
| Standing loss | 1x | 54.99 | 55.20 | +0.0200% | electric heater capacity |
| Standing loss | 2x | 54.69 | 54.69 | +0.0227% | electric heater capacity |
| Round-trip efficiency | 0.85 | 32.86 | 32.86 | +0.0057% | electric heater capacity |
| Round-trip efficiency | 0.90 | 43.45 | 43.45 | +0.0111% | electric heater capacity |
| Round-trip efficiency | 0.95 (assumed) | 54.99 | 55.20 | +0.0200% | electric heater capacity |
| Price volatility | 0.5x amplitude | 45.87 | 46.73 | +0.0182% | electric heater capacity |
| Price volatility | 1x (assumed) | 54.99 | 55.20 | +0.0200% | electric heater capacity |
| Price volatility | 2x amplitude | 54.99 | 55.01 | +0.0038% | electric heater capacity |
| Load factor | 1.00 (flat) | 54.99 | 55.20 | +0.0200% | electric heater capacity |
| Load factor | 0.73 (two-shift) | 78.23 | 78.72 | +0.0097% | electric heater capacity |
| Load factor | 0.75 (seasonal) | 70.58 | 71.13 | **+0.0308%** | electric heater capacity |

**Three findings worth calling out specifically, none of them obvious in
advance:**

1. **Gas price is the single most powerful lever in this whole study, in
   both directions.** At half the assumed gas price, storage is priced out
   of the market *entirely* -- optimal `E_cap` is exactly 0 MWh under both
   formulations, and the SOC-dependent delta is exactly 0.000%, the same
   degenerate pattern Phase C3 found for PCM at this case's own design
   duration (a discharge-limit correction cannot matter to a store that is
   never built). At double the assumed gas price, `E_cap` roughly *triples*
   relative to the zero-gas-price-sensitivity point and the SOC-dependent
   delta (+0.0647%) is the **largest measured anywhere in this entire
   study** -- and, per the cost decomposition below, the system stops using
   the backup boiler at all (`fuel_cost_eur` and `carbon_cost_eur` both
   exactly 0), a full-electrification regime the base case never reaches.
2. **Lower process load factor means *more* optimal storage, not less** --
   counter-intuitive at first glance. The peakier two-shift (load factor
   0.73) and seasonal (0.75) profiles both size *larger* stores (78.2 and
   70.6 MWh) than the flat baseline (55.0 MWh, load factor 1.0), and the
   seasonal profile's own SOC-dependent delta (+0.0308%) is the
   second-largest in the study. A peakier profile creates a bigger
   buy-low/avoid-boiler arbitrage opportunity for storage to exploit, more
   than offsetting its lower average utilisation.
3. **Doubling price volatility does not double sized storage capacity, and
   the reason is a capacity constraint, not economics.** Going from 1x to
   2x daily price amplitude leaves `E_cap` essentially unchanged (54.99 to
   54.99 MWh) even though total cost drops sharply (deeper price troughs
   make charging much cheaper) -- because, per the binding-constraint
   column, the electric heater's own 15 MW capacity, not the price
   incentive, is what actually limits how much of the daily price swing the
   system can exploit at this size.

**The binding-constraint column is itself a finding.** Across all 31
sensitivity points -- a power-CAPEX range spanning 0x to 8x and seven
independent secondary axes -- the electric heater's own capacity is what
binds in every single case except the one where storage is priced out of
the market entirely (gas price at 0.5x). Neither the backup boiler's own
capacity nor genuine unmet heat ever binds anywhere in this sensitivity
space for this case: whatever else changes, it is the rate at which the
system can charge the store, not fuel or emissions economics on their own,
that structurally limits this case's behaviour.

### P5.3: cost decomposition

Every sensitivity point's total cost is broken into annualised energy-
capacity CAPEX, annualised power/BOP CAPEX, electricity, backup fuel, and
carbon, recomputed independently from each solved schedule's own per-hour
columns and checked to reproduce the solver's own objective value exactly
(to float precision) at every single point, not assumed to match. The gas
price sensitivity above gives the clearest illustration of *why* the
optimum moves, per P5.3's own purpose:

| | Base case (gas price 1x) | Gas price 2x |
|---|---:|---:|
| Annualised energy CAPEX (EUR/yr) | 30,110 | 46,520 |
| Annualised power CAPEX (EUR/yr) | 14,338 | 22,152 |
| Electricity (EUR/yr) | 2,524,452 | 4,188,409 |
| Backup fuel (EUR/yr) | 1,014,756 | **0** |
| Carbon (EUR/yr) | 409,961 | **0** |
| **Total (EUR/yr)** | **3,993,618** | **4,257,080** |

Doubling gas price does not just make the existing dispatch pattern more
expensive -- it changes the *system's own qualitative behaviour*: the
backup boiler goes entirely unused (zero fuel and zero carbon cost, not
merely reduced), and the case becomes fully electrified, with a larger
store built specifically to absorb the electric heater's own output during
cheap hours rather than share the load with fossil backup at all. Blower/
parasitic electricity (P3.3) is deliberately **not** included in this
decomposition's total: it is a rated, not annually-integrated, diagnostic
figure (`outputs/capability_curves/`), and summing it in here would
require assuming an annual duty cycle this project has not adopted.

Every number above traces to `outputs/economics_sensitivity/run_manifest.json`:
all 31 points, both formulations, full KPIs, cost decomposition, and
binding-regime classification for each.

## P6: the model-fidelity decision map

**Every paired comparison before this one -- C2, C3, P5 -- was run at this
project's own actual case configs' one specific temperature-quality
regime.** Roadmap P6 asks the more general, and more useful, question:
*under what conditions does the detailed discharge representation
materially change the system-level decision, at all?* This is the first
experiment in this repository to actually leave that one regime and map
the surrounding space.

**The axis that matters is a dimensionless one.** Rather than sweep raw
process temperature (not transferable between cases), P6.1 defines
`theta_req = (T_required_out - T_return) / (T_hot - T_return)`: 0 means the
process only needs the store barely above its own return temperature
(nearly all stored heat is useful); 1 means the process needs almost the
store's own fully-charged temperature (only the hottest sliver is useful,
and outlet-temperature degradation should matter strongly). **This
project's own two packed-bed case configs both sit at `theta_req = -0.25`**
-- negative, because both deliberately hold the return temperature 20 C
*above* the process temperature (the "usable floor" design choice
documented since Phase A) -- which is exactly why
[P3.1](#p31-spatial-and-temporal-discretisation-convergence) already found
the quality gate can never bind for either config: they sit comfortably
outside the regime where degradation matters at all. `theta_req = -0.25,
tau = 6h, flat` is this repository's own already-published Phase C2/C3
headline case; this script's own internal consistency check
(`scripts/run_model_fidelity_map_experiment.py`, built independently,
parameterised by `theta_req` rather than reading `process_temperature_c`
off a case config directly) reproduces it exactly: `E_cap` 54.99/55.20
MWh, +0.0200% cost, matching the published numbers to two decimal places.

**The finding, in the roadmap's own suggested structure ("only say this if
the corrected experiment supports it" -- it does): the annual objective is
relatively insensitive over most of the domain tested, but power and
energy sizing go from a small bias to complete infeasibility -- the
SOC-dependent model refuses to build any storage at all -- once the
temperature-quality requirement gets high enough, and how high depends on
design duration.** Of the 45 grid points swept (`theta_req` in
{-0.25, 0.25, 0.5, 0.75, 0.9} x tau in {2h, 6h, 12h} x 3 load profiles, 90
solves, all `optimal` and independently verified), **33 fall in the
"constant model adequate" region and 12 in "additional fidelity materially
changes design"** -- none fell in the intermediate "potentially useful"
band at all, a real bimodal split, not a gradual one.

| theta_req | tau=2h | tau=6h | tau=12h |
|---:|---|---|---|
| -0.25 | adequate (bias 0.00%) | adequate (bias 0.02-0.03%) | adequate (bias 0.02-0.07%) |
| 0.25 | adequate (bias 0.00%) | adequate (bias 0.01-0.03%) | adequate (bias 0.02-0.07%) |
| 0.50 | adequate (bias 0.00%) | adequate (bias 0.01-0.03%) | adequate (bias 0.02-0.07%) |
| 0.75 | **materially changes design** (E_cap: 45.9 -> 0 MWh, cost bias 3.95-7.80%) | adequate (bias 0.01-0.03%) | adequate (bias 0.02-0.07%) |
| 0.90 | **materially changes design** (E_cap: 45.9 -> 0 MWh) | **materially changes design** (E_cap: 55.0 -> 0 MWh) | **materially changes design** (E_cap: 60.8 -> 0 MWh) |

(Cost-bias ranges are across the three load profiles at that grid point;
`E_cap` values shown are the constant-limit sizing collapsing to the
SOC-dependent formulation's exactly-zero sizing, not a small percentage
move.)

**The mechanism, read directly off the underlying sizing, not inferred.**
The constant-limit formulation's own sized `E_cap` is *completely
insensitive* to `theta_req` (45.868 / 54.987 / 60.753 MWh at tau=2h/6h/12h,
identical at every `theta_req` tested) -- the same already-documented Phase
A property (`dispatch.py`'s constant-limit block never reads process
temperature at all) showing up here as a genuine blind spot: a model that
cannot see temperature cannot possibly notice that it has walked into a
regime where a packed bed's own physics makes storage worthless. The
SOC-dependent formulation, which *can* see it, sizes identically to the
constant model at low `theta_req` and then drops to **exactly zero MWh**
once the piecewise discharge curve's own effective full-charge SOC range
shrinks enough that building any packed-bed storage stops paying for
itself at all -- a categorical, not incremental, disagreement between the
two models about whether this technology should even be considered.

**Duration changes where the cliff is, not whether one exists.** The flip
happens between `theta_req = 0.5` and `0.75` at the shortest duration
tested (2h) but needs `theta_req` between `0.75` and `0.9` at 6h and 12h --
longer design durations draw at a lower mass flow (P2.1's own finding),
giving a less steeply-degrading discharge curve that stays viable to a
higher temperature-quality requirement before collapsing. Short-duration,
high-temperature-utilisation designs are the most exposed combination
found in this map.

**Restating the roadmap's own P6.3 template, since the data now actually
supports it:** dynamic fidelity is far more important for equipment
sizing and technology feasibility than for total annual cost in the
adequate region -- but once a design crosses into the high-`theta_req`,
short-duration corner, the disagreement stops being about cost bias at all
and becomes a disagreement about whether the technology is viable in the
first place, which no amount of the constant model's own cost-sensitivity
analysis (P5) could have surfaced, since it never varies temperature in
the first place.

**One figure per load profile** (P6.1's own explicit instruction), each a
`theta_req` x `tau` heatmap coloured by annual-cost bias, with the
materially-design-changing cells labelled directly:

![Model-fidelity decision map: flat](outputs/model_fidelity_map/figures/flat.png)
![Model-fidelity decision map: two-shift](outputs/model_fidelity_map/figures/two_shift.png)
![Model-fidelity decision map: seasonal](outputs/model_fidelity_map/figures/seasonal.png)

**Scope and thresholds, stated plainly.** Packed bed only: `theta_req` is
defined from the thermocline model's own `T_hot`/`T_return`, and molten
salt has no thermocline to degrade in the first place (Phase C3's own
finding), so this map's whole premise does not transfer to it directly.
The 5%/5%/1% classification thresholds are the roadmap's own suggested
screening values, explicitly labelled [assumption] in the run manifest,
not universal truths -- per the roadmap's own instruction not to present
them as anything more. Every number above traces to
`outputs/model_fidelity_map/run_manifest.json`: all 45 grid points, both
formulations' full KPIs, the bias/region classification, and the
consistency-check result.

## Phase D: harmonised comparison and sensitivity

`TES_SCREEN_SPEC.md` section 7's own three deliverables, only attempted
after Phase C had produced its result (it had, well before this).

### D.1: boundary harmonisation table

**The spec's own words: "This table is arguably the most transferable
artefact the project produces, since inconsistent boundaries are exactly
the problem the field complains about."** Building it surfaces exactly
that problem inside this project's own repository, not just in the wider
field it critiques.

| | Packed bed | Molten salt | PCM |
|---|---|---|---|
| Storage lifetime | 25 yr | 25 yr | 25 yr |
| Discount rate | 6% | 6% | 6% |
| Currency / cost basis year | EUR, no explicit base year in any cited source | EUR, no explicit base year | EUR, no explicit base year |
| Energy CAPEX | 7,000 EUR/MWh-th [search-quoted, Albrecht et al. 2016] | 26,000 EUR/MWh-th [search-quoted, Albrecht et al. 2016] | 80,000 EUR/MWh-th [search-quoted, Hirschey et al.] |
| Power/BOP CAPEX | 20,000 EUR/MW [assumption] | 60,000 EUR/MW [assumption] | 40,000 EUR/MW [assumption] |
| What's *inside* power/BOP CAPEX | Blowers, ducting, heat exchanger (lumped, not itemised) | Pumps, heat exchangers (lumped, not itemised) | PCM heat-exchanger network (lumped, not itemised) |
| Round-trip efficiency (charge/discharge) | 0.95 / 0.95 [assumption] | 0.95 / 0.95 [assumption] | 0.95 / 0.95 [assumption] |
| Standing loss (fraction/hour) | 0.001 [assumption] | 0.0005 [assumption] | 0.0007 [assumption] |
| **Parasitic-load modelling** | **Ergun/blower power computed (P3.3) and priced into operating cost (`dispatch.py`'s `blower_specific_power_mw_per_mw`, applied in C3 and D.3 below)** | **None computed** | **None computed** |
| **Dynamic sub-model verification depth** | **Full: Modelica FMU cross-check (P4, 0.23% max deviation over an 8h discharge), 3 analytic-limit checks, discretisation convergence checked (P3.1)** | **Closed-form; checked only against its own specified physics** | **Closed-form; checked only against its own specified physics** |

What's *outside* every technology's storage boundary and priced
identically across all three: the electric heater and backup boiler
(capacity, efficiency, fuel cost, emission factor, carbon price) --
supply-side equipment, not storage, and taken byte-for-byte identical
across every case config in this repository, so it introduces no
cross-technology inconsistency of its own.

**The inconsistency this table itself surfaces, stated plainly rather
than smoothed over:** parasitic-load modelling and dynamic-model
verification depth are *not* harmonised across technologies, and this was
true before this table was ever built -- only packed bed has a computed
parasitic-power estimate (P3.3), now actually priced into its own
operating cost (C3, D.3), and a genuinely deep verification story
(analytic limits, discretisation convergence, a compiled and cross-checked
Modelica/FMU twin, P4); molten salt and PCM have neither, because their
own closed-form sub-models were built later, in less depth, and by design
(Phase B's own stated priority: "one technology fully verified beats three
unfinished"). Pricing packed bed's own parasitic load *narrowed* this
asymmetry (it no longer gets a free pass on an operating cost the model
can actually compute for it) but did not remove it: molten salt and PCM
still have no parasitic-load model at all, not even a cruder placeholder,
so the technology-ranking comparisons below still likely understate their
own true operating costs relative to packed bed's, in a direction this
project cannot currently quantify. Every technology-vs-technology cost
comparison in this repository (Phase A, C3, this section's own D.3) is
therefore conditional not just on the CAPEX figures' own mixed [assumption]/
[search-quoted] provenance, already flagged throughout `docs/DATA.md`, but
on an unequal verification and completeness depth between technologies
that a boundary table alone cannot fix -- only make visible.

### D.2: Morris global sensitivity screening

**Every prior sensitivity result in this repository (P5) is one-at-a-
time.** Morris elementary-effects screening (SALib) perturbs all five
factors the spec names together, along randomized trajectories through
the whole space at once: `economics.storage_capex_eur_per_mwh` (0.5x-2x),
a multiplier on the Wakao-Kaguei correlation's own `h_v` output (0.5x-2x,
via `simulate_discharge`'s existing override parameter), `discount_rate`
(3%-10%), electricity price volatility (0.5x-2x daily amplitude), and
`theta_req` (P6's own dimensionless temperature-quality axis, reused
directly, spanning -0.25 to 0.9). Response: the SOC-dependent-vs-constant
annual-cost bias %, packed bed only, tau=6h, flat profile. 8 trajectories
x 6 (5 factors + baseline) = 48 sample points, 96 solves, all `optimal`
and independently verified.

| Factor | mu_star (mean absolute effect) | sigma (nonlinearity/interaction) |
|---|---:|---:|
| **theta_req** | **7.14** | **8.02** |
| energy_capex_multiplier | 0.607 | 0.907 |
| discount_rate | 0.424 | 0.586 |
| price_volatility_multiplier | 0.0198 | 0.0055 |
| h_v_multiplier | 0.0022 | 0.0019 |

**The temperature-quality requirement dominates every other factor by
more than an order of magnitude, and its own screening confirms --
quantitatively, not just visually -- the cliff P6 already found.**
`theta_req`'s `mu_star` (7.14) is roughly 12x the next-largest factor
(energy CAPEX, 0.607), and its `sigma` *exceeds* its own `mu_star` (8.02
vs. 7.14) -- Morris's own standard signature of a highly nonlinear,
interaction-heavy effect, not a smooth, additive one, exactly what a
screening should show for a factor whose effect is "small everywhere
except past a cliff" rather than "proportionally large everywhere."
Energy CAPEX and discount rate have real, moderate, roughly comparable
effects, both still over an order of magnitude below `theta_req`. Price
volatility and -- notably -- **the heat transfer coefficient itself are
essentially negligible** (`h_v_multiplier`'s `mu_star` is over 3,000x
smaller than `theta_req`'s): even deliberately doubling or halving the
Wakao-Kaguei correlation's own output barely moves the SOC-dependent-vs-
constant cost bias at this reference bed's scale, a quantitative
confirmation of P3.1's own qualitative finding that this project's
sizing/cost decision is robust to the underlying heat-transfer physics'
own precise magnitude, even though the raw curve shape is not.

**Scope, stated plainly**: packed bed only, one duration, one profile --
`h_v` and `theta_req` are both thermocline-specific concepts that do not
transfer to molten salt or PCM without their own separate
parameterisation, and this screens what drives the *size* of the fidelity
correction for the one technology this project's dynamic-modelling
apparatus was built around, not a cross-technology ranking-change Sobol
study (a substantially larger undertaking the spec's own wording, "Sobol
*or* Morris," does not require choosing). Every number traces to
`outputs/morris_sensitivity/run_manifest.json`: all 48 samples, their
responses, and the full Morris analysis output (`mu`, `mu_star`,
`mu_star_conf`, `sigma` for every factor).

### D.3: technology-selection map

**Extends Phase C3's single-duration technology ranking (packed bed
cheapest at every valid technology/temperature/profile combination, at
tau=6h) across the full duration dimension C3 held fixed.** For each of 2
process temperatures x 5 design durations (2h-12h, C2's own grid), every
valid technology's curve is rebuilt at that duration exactly as C3 does,
and both discharge-limit formulations solved duration-matched. 25
(technology, temperature, duration) combinations, 50 solves, all
`optimal` and independently verified.

| Temperature | Duration | Cheapest (constant) | Cheapest (SOC-dependent) | Flipped? |
|---:|---:|---|---|:---:|
| 300 C | 2h | packed_bed | packed_bed | No |
| 300 C | 4h | packed_bed | packed_bed | No |
| 300 C | 6h | packed_bed | packed_bed | No |
| 300 C | 8h | packed_bed | packed_bed | No |
| 300 C | 12h | packed_bed | packed_bed | No |
| 400 C | 2h | packed_bed | packed_bed | No |
| 400 C | 4h | packed_bed | packed_bed | No |
| 400 C | 6h | packed_bed | packed_bed | No |
| 400 C | 8h | packed_bed | packed_bed | No |
| 400 C | 12h | packed_bed | packed_bed | No |

**Packed bed is cheapest everywhere in this map, under both
formulations, at every duration tested -- the ranking does not flip
anywhere.** This is consistent with, and extends, C3's own finding: the
technology-cost gaps this project's own boundary-harmonisation table
above already flags as resting on unequal CAPEX confidence levels
(packed bed's own 7,000 EUR/MWh-th vs. PCM's 80,000 EUR/MWh-th, over an
order of magnitude apart) are simply too large for any duration-dependent
sizing effect within this map to close.

**One secondary nuance the duration sweep surfaces that C3's single tau=6h
point did not:** PCM's own "priced out entirely, exactly matching the no-
storage baseline cost" finding from C3 holds at tau=6h and longer (8h,
12h: constant and SOC-dependent both land on exactly the same
4,178,029 EUR/yr no-storage cost), but at *shorter* durations (2h, 4h) the
constant-limit formulation finds slightly more value in building some PCM
capacity than the no-storage baseline (4,172,676 and 4,176,567 EUR/yr
respectively, roughly 0.03-0.13% cheaper) -- while the SOC-dependent
formulation still lands on exactly the no-storage cost at *every* duration
tested. A small effect, and it never changes which technology wins
overall, but it is a clean, small-scale illustration of this project's own
central theme: the temperature-blind constant model can see slightly more
economic value in a technology than the SOC-dependent model, which
correctly discounts capacity PCM's own three-regime discharge shape
cannot actually deliver.

**Explicitly a conditional map, not an absolute one**, per the spec's own
instruction: conditional on every boundary tabulated in D.1 above,
including the stated unequal CAPEX citation confidence and unequal
parasitic-load/verification depth between technologies. Every number
traces to `outputs/technology_selection_map/run_manifest.json`.

