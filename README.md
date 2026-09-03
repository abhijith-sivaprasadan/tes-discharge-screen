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
solved under both discharge-limit formulations. The SOC-dependent limit
increases annualised cost by 0.22% and required power capacity by 75% for
this case; see [Phase C](#phase-c-the-paired-experiment-mvp-scope) below for
the full numbers. This is not the full 18-run technology-ranking matrix
(only packed bed has a Phase B dynamic sub-model yet), so whether the
technology ranking itself changes is not answerable from this result.

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

Discharge curves (state of charge vs. deliverable power above the 300 C
process temperature) were generated at three draw rates and committed with
their generating bed config: `outputs/packed_bed_dynamics/`.

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

## Phase C: the paired experiment (MVP scope)

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
                  (Phase B curves), run_phase_c_experiment.py (the paired comparison)
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
profile pair, not the full 18-run matrix) -> D (harmonised comparison and
sensitivity, optional enrichment; not started).

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

# Run the Phase C paired constant-vs-SOC-dependent experiment:
python scripts/run_phase_c_experiment.py
```
