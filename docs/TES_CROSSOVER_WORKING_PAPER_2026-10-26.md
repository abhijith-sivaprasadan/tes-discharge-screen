# When does discharge-model fidelity change thermal-storage technology selection?

**Author:** Abhijith Sivaprasadan · **Date:** 26 October 2026 · **Status:** Author working paper (not peer-reviewed) · **Evidence:** [GitHub Actions fine-grid run 40344628085](https://github.com/abhijith-sivaprasadan/tes-discharge-screen/actions/runs/40344628085), [hypothetical auxiliary reoptimizations run 40354076547](https://github.com/abhijith-sivaprasadan/tes-discharge-screen/actions/runs/40354076547)

> **Scope.** An independently checked, post-hoc *computational counterexample* under synthetic prices and load profiles. Not a physically validated storage model, externally calibrated cost range, engineering recommendation or study of observed market outcomes.

## Abstract

Annual energy-system models often represent thermal-storage discharge with a constant power limit despite the decline in usable, process-quality heat during discharge. We examine whether a constant-power versus trajectory-derived SOC-dependent limit changes the **identity of the cheapest selected thermal-storage technology** in a full-year synthetic industrial-heat optimization. The original 36-attempt non-adaptive CAPEX/standing-loss sensitivity found **no selection reversal** in 35 verified solutions (one unsolved attempt). A subsequent *post-hoc* zoom around a hypothesized molten-salt cost crossover produced 23 verified optimal solutions in 24 distinct attempts across flat, two-shift and seasonal heat demand. Six matched-factor choices differed between discharge formulations; one additional seasonal pairing was unresolved. Every verified 8,760-hour schedule, model-input JSON and total annual objective was independently reconstructed from source files; maximum cost-accounting deviation was **4.66 × 10⁻¹⁰ EUR**. However, the annual price advantage behind these differences was only a few tens to hundreds of euros against several-million-euro annual system cost. In a distinct 24-solve sensitivity screen, adding a hypothetical discharge-linked electrical-load proxy as small as **0.0001–0.0005 MW-e/MW-th** removed the molten-salt cost advantage at the representative matched factors. This establishes a **numerical decision sensitivity**, not robust economic superiority, a calibrated pumping rate, or empirical investment implications.

## 1. System and verification boundary

The repository compares packed-bed and two-tank molten-salt storage serving industrial process heat at **300 °C**. A Pyomo/HiGHS full-year (8,760 hour) capacity/dispatch model dispatches an electric heater, storage and fuel boiler under three entirely **synthetic** load shapes and recurring electricity-price patterns. Storage energy and rating are optimized using the common six-hour design-duration convention. The annual objective is a capital recovery factor (6% discount rate, 25-year life) times an assumed MWh/MW capital-cost model plus hourly electricity, boiler fuel/carbon, unmet heat penalties, and the charged packed-bed blower parasitic.

Two alternative discharge constraints are compared: a constant rated power limit, and a trajectory-derived piecewise SOC-dependent power envelope. The latter is built from an authored dynamic packed-bed thermocline model or simplified molten-salt dynamic representation. The repository documents analytic-limit checks, discretisation experiments and a Modelica/Python twin comparison. Those are **verification** against internal/related models—not independent facility **validation**. A scalar SOC does not completely determine a packed bed's thermal state under arbitrary internal temperature distributions, as the project's earlier tests demonstrate.

**Unequal economics:** the packed bed prices modelled blower power; a separately physically calibrated molten-salt pump load is absent from the primary comparisons. Technology costs are illustrative inputs, not a matched vendor procurement quote. Temperature, material compatibility, integration, degradation and maintenance are not externally validated.

## 2. Study sequence and registration honesty

The first fixed economic and standing-loss study registered 36 annual solution attempts under the originally assumed economic factors and had **35 independently verified optimal results and one no-loadable-solution**. Its already recorded conclusion was **no technology choice reversal**. At 0.5× salt CAPEX, salt remained more expensive than packed bed by €23,106/year in two-shift and €18,416/year in seasonal operation. The missing flat molten-salt case is not counted as infeasible or a losing candidate.

**Then**—after inspecting those results—the coarse and finer salt CAPEX ranges were selected, so the selection-crossing experiments were *post-hoc exploratory*, not independent preregistered confirmation. At each factor both physical formulations for both technologies used identical heat load, prices and six-hour design duration; packed-bed reference solves reused identical proven outputs rather than inflating the number of independent solves. No uncomputed intermediate cost is reported as solved.

### Exact exploratory fine-grid results

Delta = optimized annual **molten salt cost minus packed bed cost**, EUR/year. Positive chooses packed bed, negative chooses molten salt. The numbers below are derived from the [complete 8,760h hourly evidence artifact](https://github.com/abhijith-sivaprasadan/tes-discharge-screen/actions/runs/40344628085), not from interpolation.

| Load | Salt CAPEX factor | Constant discharge Δ EUR/yr | SOC-dependent Δ EUR/yr | Formulation decision |
|---|---:|---:|---:|---|
| Flat | 0.3825 | -31.01 | -647.74 | Same (salt) |
| **Flat** | **0.3850** | **+324.92** | **-291.72** | **Different** |
| Flat | 0.3875 | +680.86 | +64.23 | Same (packed) |
| **Two-shift** | **0.3925** | **+55.18** | **-234.86** | **Different** |
| **Two-shift** | **0.3930** | **+163.74** | **-126.30** | **Different** |
| **Two-shift** | **0.3935** | **+272.31** | **-17.73** | **Different** |
| **Seasonal** | **0.3965** | **+77.58** | **-548.05** | **Different** |
| Seasonal | 0.3980 | +358.17 | No loaded solution | **Indeterminate** |
| **Seasonal** | **0.3990** | **+545.13** | **-80.67** | **Different** |

23 of 24 unique annual optimization attempts were solver-optimal and passed stored heat, SOC, terminal, objective and unmet-load verification. Four unchanged packed-bed reference records per profile were reused in paired comparisons; they were **not** counted as new solves. The independently reconstructed capital-recovery and hourly cost terms matched all 23 recorded annual objectives to at most **4.66 × 10⁻¹⁰ EUR**, with source hashes and hour ordering checked.

## 3. Auxiliary-cost fragility: a distinct 24-solve screen

The hypothetical cost proxy is an additional `electricity_price[t] × MW-thermal-discharge[t] × β` term with β expressed as MW-e/MW-th. This reuses the existing dispatch solver's generic discharge-linked auxiliary electricity term; **it is not a pump-head or flow calculation**. Three source-selected economic focus cases were independently re-optimized at β = 0, 0.0001, 0.0005, and 0.001, in both discharge formulations. All 24 new solves passed original physical verification; they are a **separate** study from the 23/24 fine-grid results. The packed-bed comparator is unchanged.

The table shows re-optimized SOC-dependent **salt minus packed bed** objective in EUR/year:

| Load and fixed salt CAPEX | β = 0 | β = 0.0001 | β = 0.0005 | β = 0.001 |
|---|---:|---:|---:|---:|
| Flat / 0.3850 | -291.72 | -192.55 | +204.00 | +699.13 |
| Two-shift / 0.3930 | -126.30 | +28.09 | +645.34 | +1416.23 |
| Seasonal / 0.3965 | -548.05 | -406.97 | +157.02 | +861.60 |

The original molten-salt cost winner vanishes by the smallest tested extra proxy in two-shift operation and by β=0.0005 in flat and seasonal operation. The constant-power formulation selects packed bed throughout these focused additional-auxiliary scenarios. All such factor choices are arbitrary **screening parameters**, not an experimentally determined pump consumption range or statistical confidence interval. Small absolute rankings also warrant numerical-solver tolerance scrutiny and a genuine measured installed-cost range before stronger claims.

A separate analytic *fixed-dispatch* threshold estimate is present in the companion audit as an interpretation aid, but it must **never** be conflated with the new re-optimized scenarios above.

## 4. What the result does and does not establish

**Supported:** for this specified stylised model, after a prior broad null result, there exist six evaluated cost/profile conditions under which the constant-discharge representation and SOC-dependent representation select different least-cost technologies at matched economic input factors. The exact annual solutions and cost accounting are reproducible. These are deliberately near-ties, and a small extra cost can change the decision.

**Not supported:** an industrial plant's actual lowest-cost storage medium, an empirically derived CAPEX threshold, accurate molten-salt hydraulic load, multiple independent plant replications, field validation of SOC-only discharge capability, general mitigation pathway predictions, actual Dutch/Swedish/Indian electricity market benefits, causal evidence, statistical significance, or peer-reviewed acceptance.

**Next requirements for external publication:** harmonized installed CAPEX/OPEX and parasitic electricity bounds with original vendor/literature citations; verified molten-salt pump/heat-exchanger operation; measured dynamic discharge profiles; prospectively chosen parameters independent of this post-hoc localization; and independent comparison against a validated facility model.

## Reproducibility, source evidence and references

- [Registered broad annual sensitivity](REOPT_REGISTERED_RESULTS_2026.md), source code `scripts/run_technology_reoptimisation.py`.
- [Original exploratory study](POSTHOC_FIDELITY_CROSSOVER.md), source `scripts/run_posthoc_fidelity_crossover.py`.
- [Fine-grid archive and protocol](TARGETED_FIDELITY_TRANSITION.md), source `scripts/run_targeted_fidelity_transition.py`.
- [Uncalibrated auxiliary-cost screen](AUXILIARY_PROXY_SCREEN.md), source `scripts/run_auxiliary_proxy_sensitivity.py`.
- Independent cost/provenance audit `scripts/audit_posthoc_fidelity_evidence.py`, with tampering negative controls `tests/test_posthoc_evidence_audit.py`.
- Archived GitHub Actions [full-year fine-grid evidence](https://github.com/abhijith-sivaprasadan/tes-discharge-screen/actions/runs/40344628085), [24-solve auxiliary proxy output](https://github.com/abhijith-sivaprasadan/tes-discharge-screen/actions/runs/40354076547). Actions artifacts expire: pin/copy exact bytes before treating this as permanently archived.
- Related literature (not presented as the experimental source): [Storage modeling review (2020)](https://doi.org/10.1088/2516-1083/ab9894); [Packed-bed heat storage review (2025)](https://doi.org/10.1016/j.est.2025.116516); [Thermal storage techno-economics (2024)](https://doi.org/10.1016/j.energy.2024.133500); [Modelica thermal storage validation example (2024)](https://doi.org/10.1186/s40517-024-00302-9).

**Disclosure:** this author-prepared working report has benefited from AI-assisted computational auditing and drafting. Claims remain anchored in source-backed verified model artifacts; all external publication decisions and source attribution require author review.
