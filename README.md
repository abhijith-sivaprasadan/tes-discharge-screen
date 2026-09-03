# tes-screen

[![CI](https://github.com/abhijith-sivaprasadan/tes-screen/actions/workflows/ci.yml/badge.svg)](https://github.com/abhijith-sivaprasadan/tes-screen/actions/workflows/ci.yml)
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

Phase 0 (scaffold and contracts) and Phase A (annual quasi-steady core, constant
discharge limit) are built. One case has an actual, verified, committed run:
packed-bed sensible storage, 300 C steam process, flat load profile, full
8,760-hour horizon, HiGHS/Pyomo LP, solved to optimality with every independent
check in `verification.py` passing (`outputs/packed_bed_300c_flat/`). Molten-salt
and PCM configs exist with literature-cited parameters (`docs/DATA.md`) but have
not been run yet; the two-shift and seasonal load profiles and the 400 C process
case likewise exist but are unrun. No dynamic sub-model (Phase B) and no
SOC-dependent discharge correction (Phase C) exist yet: the constant discharge
limit is the only formulation implemented so far, which is deliberate, since
Phase A's whole job is to be a fair, unbiased baseline of current practice.

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

## Phase A baseline result (packed bed, 300 C, flat load, synthetic price/load)

This is the constant-discharge-limit baseline only, not yet the SOC-dependent
comparison Phase C exists to produce, so there is no ranking or correction to
report here. It exists to show the model runs, solves to optimality, and passes
every independent check, on real (if synthetic-input) numbers rather than
placeholders.

| KPI | Value |
|---|---|
| Solver | HiGHS, termination: optimal |
| Sized storage capacity | 55.0 MWh-th |
| Sized storage power | 7.4 MW |
| Annualised total cost | 3,992,456 EUR/yr |
| Max heat-balance residual | 8.9e-16 MW (machine precision) |
| Unmet heat | 0 MWh |

Full schedule, config, and solver/verification manifest:
`outputs/packed_bed_300c_flat/`.

## Repository layout

```
src/tes_screen/   Python package: config schema, profile contract, provenance,
                  synthetic profiles, electricity price source, the Phase A
                  dispatch LP, and its independent verification checks
scripts/          Annual run harness (scripts/run_case.py)
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
  export path, the shadow-twin cross-check, the piecewise-linear construction, and
  the profile contract validation.

## Sequencing

Phase 0 (scaffold, done) -> A (annual quasi-steady core, constant discharge limit;
one case run and verified, others configured but unrun) -> B (targeted dynamic
sub-model and shadow twin, not started) -> C (coupling and the paired-run
experiment, the deliverable) -> D (harmonised comparison and sensitivity, optional
enrichment).

## Development

```
uv venv
uv pip install -e ".[dev]"
pytest
ruff check .

# Solve one case end to end and write outputs/<case_name>/:
python scripts/run_case.py configs/packed_bed_300c_flat.yaml
```
