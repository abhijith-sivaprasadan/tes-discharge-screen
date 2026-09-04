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

**Phase C (the paired experiment) is done at MVP scope**: one technology
(packed bed), one process temperature (300 C), one load profile (flat),
solved under both discharge-limit formulations. Its original run left the
two formulations with unequal sizing degrees of freedom and mixed the
process and return temperature references (see the note at the top of
[Phase C](#phase-c-original-mvp-run-archived-diagnostic-only)), which
confounded "the discharge-limit shape changed" with "the two runs were also
allowed different durations" and inflated deliverable power with enthalpy
already present in the return stream. **[Phase C2](#phase-c2-matched-duration-family-experiment-the-corrected-comparison)**
fixes both (roadmap P0.1 and P0.2): ties power to energy capacity at the
same externally chosen duration in both formulations, and references
deliverable power consistently to the store's own return temperature. The
isolated shape effect is much smaller than Phase C's original number: a
total-cost delta ranging from +0.013% to +0.080% across a 2-12h duration
sweep, versus Phase C's original +0.22% at its own (confounded,
mis-referenced) durations. This is not the full 18-run technology-ranking
matrix (only packed bed has a Phase B dynamic sub-model yet), so whether the
technology ranking itself changes is not
answerable from this result.

Electricity prices are synthetic in every run so far: this working environment
has no `ENTSOE_API_KEY` configured, so the real ENTSO-E fetch path
(`electricity_price.py`, ported from PyNEXUS) is built and gated behind that
credential exactly the way PyNEXUS's own equivalent module is, but has not been
exercised against live data. See [Sequencing](#sequencing) below.

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
`outputs/packed_bed_dynamics/`.

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
always `E_cap / tau` in both, identically) and deliverable power is
referenced consistently to the store's own return temperature rather than
mixed with the process temperature (P0.1 and P0.2, both applied here), the
isolated effect of the SOC-dependent discharge limit is much smaller than
Phase C's original (confounded, unequal-duration, mis-referenced) estimate.
Swept across five design durations from 2h to 12h, the SOC-dependent
formulation costs **+0.013% to +0.080%** more than the constant-limit
baseline at the same duration -- real, and always in the direction Phase
A's constant-limit assumption predicted (SOC-dependent never costs less),
but still roughly an order of magnitude smaller than the +0.22% Phase C
originally reported, because that number also carried the duration
mismatch and temperature-reference bug documented above.

| Design duration (tau) | Constant limit cost (EUR/yr) | SOC-dependent cost (EUR/yr) | Delta | Constant E_cap (MWh) | SOC-dependent E_cap (MWh) |
|---:|---:|---:|---:|---:|---:|
| 2h | 4,019,225.76 | 4,019,765.19 | +0.013% | 45.87 | 45.87 |
| 4h | 4,000,234.86 | 4,001,593.65 | +0.034% | 50.43 | 50.99 |
| 6h | 3,993,618.08 | 3,996,217.31 | +0.065% | 54.99 | 55.71 |
| 8h | 3,992,555.33 | 3,995,758.35 | +0.080% | 54.99 | 58.85 |
| 12h | 3,996,426.99 | 3,999,416.67 | +0.075% | 60.75 | 63.38 |

All ten runs (five durations x two formulations) solved to `optimal` and
passed every independent verification check. The headline duration (6h,
chosen as a round middle point of the sweep, not cherry-picked for
magnitude) is tabulated in full below; every duration's fitted curve
safety, solver status, and delta is in the run manifest.

| | Constant limit (tau=6h) | SOC-dependent (tau=6h) | Delta |
|---|---:|---:|---:|
| Termination | optimal | optimal | |
| Annualised total cost (EUR/yr) | 3,993,618.08 | 3,996,217.31 | +2,599.23 (+0.065%) |
| Storage energy capacity (MWh-th) | 54.99 | 55.71 | +0.73 (+1.3%) |
| Storage power capacity (MW) | 9.16 | 9.29 | +0.12 (E_cap/tau, so it moves with E_cap) |
| Backup fuel cost (EUR/yr) | 1,014,756.09 | 1,030,227.14 | +15,471.05 |
| Electricity cost (EUR/yr) | 2,524,452.26 | 2,504,742.39 | -19,709.87 |
| Emissions (tCO2/yr) | 5,124.52 | 5,202.65 | +78.13 |
| Solve time | 10.8 s | 19.7 s | |

**Why energy capacity (and, through it, power) can still differ between the
two formulations at every tau in this table, more visibly than the P0.1-only
version of this experiment showed.** `design_duration_hours` ties power to
`E_cap / tau` identically in both -- the one degree of freedom Phase C's
original run left unequal -- but `E_cap` itself is still a free decision
variable in each formulation, and with P0.2's corrected reference the
SOC-dependent curve's power declines faster with state of charge than the
pre-P0.2 curve did (it no longer gets credited with enthalpy already
present in the return stream), so the optimiser leans on a somewhat larger
store to compensate. This is exactly the effect this comparison is meant to
isolate: the discharge-limit shape alone, at matched duration and with a
consistent temperature reference, still nudges the solver toward more
storage, just far less dramatically than Phase C's original (duration- and
reference-mismatched) result suggested.

**How the matched curves were built.** For each swept tau, the discharge
mass flow is solved for directly (`discharge_curve.mass_flow_for_target_duration`)
so the resulting curve's own reference power/energy ratio already equals
`1/tau`, then the bed is re-simulated at that mass flow and a fresh
piecewise curve fit -- a curve genuinely specific to that duration, not one
curve rescaled after the fact. `dispatch.py`'s `duration_matched` branch
checks this equality at model-build time and refuses a mismatched curve
rather than silently accepting one. Deliverable power (and, through
`mass_flow_for_target_duration`, the reference power this solves against)
is now computed per P0.2: referenced to the bed's own return temperature
`T_return`, with a quality gate at `T_process + delta_T_min_hot_side`
(`delta_T_min_hot_side = 0` here; see docs/DATA.md) applied on top, rather
than mixing the process and return temperature references the way Phase C's
original run did.

Every number above traces to `outputs/phase_c2_duration_matched/`: the
headline (6h) duration's hourly schedules and fitted curve breakpoints, and
a manifest with every swept duration's solver status, KPIs, verification
checks, and curve-fit safety numbers.

## Repository layout

```
src/tes_screen/   Python package: config schema, profile contract, provenance,
                  synthetic profiles, electricity price source, the annual
                  dispatch LP (constant and SOC-dependent) and its
                  verification, the Phase B packed-bed shadow twin, the
                  piecewise discharge-curve construction (C1), and the FMU
                  export adapter
modelica/         Authored Modelica model(s) for Phase B (not yet compiled here)
scripts/          Run harnesses: run_case.py (Phase A), run_packed_bed_dynamics.py
                  (Phase B curves), run_phase_c_experiment.py (the original,
                  archived paired comparison), run_phase_c2_duration_matched_experiment.py
                  (the corrected, matched-duration paired comparison)
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
started, FMU cross-check untestable in this environment) -> C (coupling and
the paired-run experiment; done at MVP scope, one technology/temperature/
profile pair, not the full 18-run matrix; original run superseded by C2 as
the shape-isolated comparison) -> C2 (matched-duration-family sizing fix;
removes the unequal-duration confound in C's original pairing; done, five
durations swept) -> D (harmonised comparison and sensitivity, optional
enrichment; not started).

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

# Run the Phase C paired constant-vs-SOC-dependent experiment (original,
# archived; unequal sizing degrees of freedom between formulations -- see
# Phase C's section above):
python scripts/run_phase_c_experiment.py

# Run the Phase C2 matched-duration-family experiment (corrected comparison):
python scripts/run_phase_c2_duration_matched_experiment.py
```
