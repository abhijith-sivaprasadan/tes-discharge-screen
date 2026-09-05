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

## Results at a glance

Phase 0 (scaffold) and Phase A (annual quasi-steady dispatch, constant
discharge limit) are done. Full methodology, every table, every figure,
and the phase-by-phase sequencing narrative are in
**[`docs/RESULTS.md`](docs/RESULTS.md)** -- this table is the one-line
summary, not the full story.

| Phase | Status | Headline finding |
|---|---|---|
| [Phase A](docs/RESULTS.md#phase-a-baseline-results-flat-load-synthetic-priceload) | Done | Constant-discharge-limit annual dispatch baseline, solved and verified. |
| [Phase B](docs/RESULTS.md#phase-b-packed-bed-dynamic-sub-model) | Done (packed bed) | Python shadow twin + Modelica model + FMU export; verified via 3 analytic limits and an FMU cross-check (P4). Molten salt/PCM have closed-form sub-models, no Modelica twin. |
| [P0.3](docs/RESULTS.md#p03-is-scalar-soc-a-sufficient-packed-bed-state) | Done | Scalar SOC is **not** a sufficient state: near-term deliverable power scatters up to 220% at matched SOC across constructed bed states. Reported, not hidden. |
| [Phase C](docs/RESULTS.md#phase-c-original-mvp-run-archived-diagnostic-only) | Archived | Original paired comparison confounded unequal sizing, mismatched temperature reference, and discharge-capability timing. Superseded by C2. |
| [Phase C2](docs/RESULTS.md#phase-c2-matched-duration-family-experiment-the-corrected-comparison) | Done | Confounds fixed: isolated SOC-dependent-shape cost delta is **+0.000% to +0.038%** across a 2-12h duration sweep (vs. Phase C's confounded +0.22%). |
| [Phase C3](docs/RESULTS.md#phase-c3-full-technology-ranking-matrix) | Done | Full technology-ranking matrix (packed bed / molten salt / PCM x 2 temperatures x 3 load profiles, 15 paired cases, 30 solves): **the SOC-dependent correction never changes which technology is cheapest.** |
| [P0.4](docs/RESULTS.md#p04-start-of-hour-vs-end-of-hour-discharge-capability) | Done | Start-of-hour discharge-capability reference removes a third confound from Phase C's original pairing. |
| [P0.5](docs/RESULTS.md#p05-preventing-pathological-simultaneous-cycling-under-negative-prices) | Done | Optional MILP cycling-prevention mode, ahead of ever running against real (sometimes negative) electricity prices. |
| [P1](docs/RESULTS.md#p1-the-modular-area-scaling-law) | Done | Modular-area bed scaling: the normalized discharge curve collapses **exactly** (0.0 deviation) across a 0.25x-4x sweep. |
| [P2.1](docs/RESULTS.md#p21-duration-family-capability-curves-as-committed-evidence) | Done (packed bed) | Duration-family capability curves committed as standalone evidence. |
| [P3](docs/RESULTS.md#p3-dynamic-model-hardening) | Done | Discretisation convergence checked (0.007% cost / 0.14 MWh sizing sensitivity); correlation-domain validity checks added; Ergun/blower parasitic power computed (reported, not wired into economics). |
| [P4](docs/RESULTS.md#p4-fmumodelica-verification----done-run-outside-this-environment) | Done (run outside this sandbox) | FMU-vs-Python-twin cross-check over an 8h discharge: **0.23% max temperature deviation, 0.0029% relative energy deviation.** The roadmap's own "single strongest verification story." |
| [P5](docs/RESULTS.md#p5-economics-sensitivity-not-one-assumed-number) | Done | SOC-dependent cost delta stays flat (+0.019% to +0.020%) across an 8x storage-power-CAPEX sweep; gas price is the single most powerful lever found. |
| [P6](docs/RESULTS.md#p6-the-model-fidelity-decision-map) | Done | Annual objective mostly insensitive, but SOC-dependent sizing **collapses to zero** once the temperature-quality requirement crosses a threshold. This project's own configs sit safely outside that regime. |
| [Phase D](docs/RESULTS.md#phase-d-harmonised-comparison-and-sensitivity) | Done | Boundary-harmonisation table; Morris sensitivity (temperature-quality dominates every other factor by >10x); technology-selection map (packed bed cheapest at all 25 combinations tested). |
| P7 (real ENTSO-E prices) | Not done | Pending `ENTSOE_API_KEY` registration; pulled forward ahead of default sequencing at explicit user request. |

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

## Limitations

Stated here explicitly, per this project's own honesty checklist
(`TES_SCREEN_SPEC.md` section 8), rather than left for a reader to
discover or ask about. This list is a floor, not a ceiling -- many more
specific limitations are stated inline throughout this document (P0.3's
scalar-SOC insufficiency finding, the synthetic nature of every load and
price series, each technology's own citation tier in `docs/DATA.md`); this
section exists so the minimum set is visible in one place, on the same
screen as the rest of the project's own framing, not buried in a data
appendix.

- **No experimental validation.** Nothing in this repository has been checked
  against measured data from a real storage installation. Every check
  performed is *verification* (against governing physics, an analytic
  limit, or an independent recomputation) -- see Governing rule 1 above.
- **No degradation or cycling effects.** No thermal or chemical
  degradation of any storage medium, no cycle-life or capacity-fade
  modelling, no limit on cycling frequency beyond P0.5's own pathological-
  simultaneous-cycling prevention (a numerical artifact fix, not a
  physical cycling-cost model).
- **No containment or materials engineering.** No structural, corrosion,
  containment-failure, or materials-compatibility modelling for any
  technology at any temperature. Material property sets are literature
  values, cited and used as inputs, not independently verified against a
  primary source in every case (see each citation's own tier in
  `docs/DATA.md`).
- **Single-node process representation.** The industrial process this
  project screens against is one aggregate hourly heat demand at one
  delivery temperature (`process.annual_peak_load_mw`,
  `process.delivery_temperature_c`) -- not a spatially or thermally
  distributed process, multiple simultaneous temperature levels, or
  process-side dynamics of any kind.
- **Perfect foresight.** The annual dispatch LP (`dispatch.py`) solves the
  full 8,760-hour horizon at once, with complete knowledge of every hour's
  load and price in advance. There is no rolling-horizon or model-
  predictive re-optimisation, and no representation of forecast
  uncertainty; every result in this repository is an ideal-information
  upper bound on achievable performance, not a forecast-realistic one.

## Full results, methodology, and every figure

Every phase's full write-up -- methodology, complete tables, every committed
figure, and the sub-findings that don't fit in a one-line summary -- lives in
**[`docs/RESULTS.md`](docs/RESULTS.md)**, linked from the table above. For a
capability inventory (what's actually built vs. not, independent of the
results narrative), see [`docs/MODEL_CARD.md`](docs/MODEL_CARD.md). For every
material property and its citation tier, see [`docs/DATA.md`](docs/DATA.md).
The original build spec and roadmap are
[`TES_SCREEN_SPEC.md`](TES_SCREEN_SPEC.md) and
[`TES_DISCHARGE_SCREEN_CLAUDE_CODE_ROADMAP.md`](TES_DISCHARGE_SCREEN_CLAUDE_CODE_ROADMAP.md).

## Repository layout

```
src/tes_screen/   Python package: config schema, profile contract, provenance,
                  synthetic profiles, electricity price source, the annual
                  dispatch LP (constant and SOC-dependent) and its
                  verification, the Phase B packed-bed shadow twin (including
                  P1's scale_parallel_bed), the molten-salt and PCM dynamic
                  sub-models (molten_salt_dynamics.py, pcm_dynamics.py), the
                  technology-agnostic piecewise discharge-curve construction
                  (C1), the P0.3 temperature-field constructors, and the FMU
                  export adapter
modelica/         Authored Modelica model(s) for Phase B (packed bed only --
                  molten salt and PCM have no Modelica twin; compiled and
                  cross-checked outside this environment, see P4)
scripts/          Run harnesses: run_case.py (Phase A), run_packed_bed_dynamics.py
                  (Phase B curves), run_phase_c_experiment.py (the original,
                  archived paired comparison), run_phase_c2_duration_matched_experiment.py
                  (the corrected, matched-duration paired comparison, packed
                  bed only), run_phase_c_full_matrix_experiment.py (Phase C3's
                  full technology-ranking matrix), run_state_sufficiency_experiment.py
                  (P0.3's state-sufficiency test), run_scaling_law_experiment.py
                  (P1's scaling-law check), run_capability_curves_experiment.py
                  (P2.1's duration-family capability curves and P3.3's
                  Ergun/blower diagnostics, packed bed only),
                  run_convergence_experiment.py (P3.1's spatial/temporal
                  discretisation convergence check),
                  run_economics_sensitivity_experiment.py (P5's CAPEX and
                  secondary-parameter sensitivity sweeps, cost
                  decomposition, and binding-constraint diagnosis),
                  run_model_fidelity_map_experiment.py (P6's theta_req x
                  tau decision map), run_technology_selection_map_experiment.py
                  (Phase D.3's duration x temperature technology-ranking
                  map), run_morris_sensitivity_experiment.py (Phase D.2's
                  Morris global sensitivity screening)
tests/            Physics and contract tests, not syntax tests
configs/          One YAML per case; no parameter lives in source
outputs/          Committed run evidence: config + schedule + solver/verification manifest
docs/             Full results and methodology (RESULTS.md), model card,
                  data citations
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
# docs/RESULTS.md#phase-c-original-mvp-run-archived-diagnostic-only):
python scripts/run_phase_c_experiment.py

# Run the Phase C2 matched-duration-family experiment (corrected comparison,
# packed bed only):
python scripts/run_phase_c2_duration_matched_experiment.py

# Run the P1 scaling-law exit-criterion check (does the normalized curve
# collapse across bed sizes?):
python scripts/run_scaling_law_experiment.py

# Run the Phase C3 full technology-ranking matrix (packed bed, molten salt,
# PCM x every valid process temperature x every load profile; writes
# outputs/phase_c_full_matrix/, including the per-technology figures):
python scripts/run_phase_c_full_matrix_experiment.py

# Run the P2.1 duration-family capability-curve experiment (packed bed
# only; also reports P3.2/P3.3's correlation-validity and Ergun/blower
# diagnostics; writes outputs/capability_curves/tau_{X}h/{case_name}/):
python scripts/run_capability_curves_experiment.py

# Run the P3.1 spatial/temporal discretisation convergence check (does
# resolution change the annual dispatch LP's own sizing/cost decision?):
python scripts/run_convergence_experiment.py

# Run the P5 economics sensitivity sweeps (storage power CAPEX 0x-8x, seven
# secondary parameters one-at-a-time, cost decomposition, binding-constraint
# diagnosis; writes outputs/economics_sensitivity/):
python scripts/run_economics_sensitivity_experiment.py

# Run the P6 model-fidelity decision map (theta_req x tau x load profile;
# writes outputs/model_fidelity_map/, including the per-profile heatmaps):
python scripts/run_model_fidelity_map_experiment.py

# Run Phase D.3's technology-selection map (temperature x duration,
# extends C3's ranking across durations; writes outputs/technology_selection_map/):
python scripts/run_technology_selection_map_experiment.py

# Run Phase D.2's Morris global sensitivity screening (writes
# outputs/morris_sensitivity/):
python scripts/run_morris_sensitivity_experiment.py

# Run the P4 FMU-vs-shadow-twin cross-check. Requires fmpy and a compiled
# PackedBedThermocline.fmu matching your platform (this project's own FMU
# is win64-only; see docs/RESULTS.md's P4 section for why and how it was
# actually run):
python scripts/run_fmu_cross_check_experiment.py path/to/PackedBedThermocline.fmu
```
