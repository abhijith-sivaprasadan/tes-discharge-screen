# Registered re-optimisation under cost and standing-loss assumptions

This experiment tests whether the saved cost rankings persist **after actually
re-solving** the 8,760-hour optimisation. Previously published differences
between saved objective values are *not* break-even CAPEX estimates.

Scope: two technologies (packed bed, molten salt), process 300°C, and each
registered load profile. Both alternatives use the same synthetic heat-load
profile, synthetic electricity prices, six-hour duration-matched storage
power/energy sizing and SOC-dependent discharge curves.

A fixed, non-adaptive design independently perturbs either BOTH storage CAPEX
terms by 0.5, 1.0, 1.5 or 2.0 ×, or standing loss by 0.5, 1.0 or 2.0 ×.
Each perturbation applies to **only one technology**; the unchanged competitor
remains at its baseline solved objective. Both prices are assumed, not
literature-validated. Comparisons are only made between cases with the same
load shape, horizon and service boundary.

```bash
python -m scripts.run_technology_reoptimisation --profile flat --output runs/reopt-flat.json
python -m scripts.run_technology_reoptimisation --profile seasonal --output runs/reopt-seasonal.json
```

The GH Actions experiment writes machine-readable per-technology and per-axis
objectives and flags observed grid-point ranking changes. No post-hoc bisection,
market-cost intervals, CAPEX break-even extrapolation or effect significance
is inferred. The two stores remain **asymmetric in auxiliary-load economics**:
packed bed includes priced blower use; molten salt pump energy is not
modelled. Repeat with harmonised auxiliary cost boundaries before a
technology-selection recommendation. Physics and source costs are still
screening-level; no plant measurements were introduced.
