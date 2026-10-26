# Exploratory post-hoc technology/fidelity crossover test — 26 Oct 2026

## Why this follow-up exists

The completed, registered [re-optimisation screening](REOPT_REGISTERED_RESULTS_2026.md)
found no technology-choice reversal in **35 verified solves out of 36
attempted**. In particular, molten-salt 0.5x CAPEX was only
EUR 23,106.20 more expensive annually than unchanged packed bed in the
two-shift profile, and EUR 18,415.99 more expensive in the seasonal profile.
The 0.5x flat-load molten-salt case returned **no loadable solver solution**,
which does not prove mathematical infeasibility.

Since the new CAPEX factors were selected *after seeing those results*, this
is **post-hoc exploratory work, not a prospectively registered confirmatory
study**. A winner flip here would establish a model-specific sensitivity, not
a statistically identified transition nor a validated market cost boundary.

## Test design and exact comparison

- Identical 8,760-hour synthetic electricity tariff, heat-demand profiles,
  equipment capacities, reference process temperature (300 °C), and six-hour
  power/energy design duration in both competing technologies.
- Both **constant-discharge-power** and **SOC-dependent-discharge** formulations
  are solved for packed bed and molten salt at every economic point.
- Only molten-salt energy and power CAPEX are jointly multiplied by one of
  `0.25, 0.35, 0.375, 0.4, 0.425, 0.45, 0.5, 1.0`. The packed-bed
  configuration is fixed at 1.0x and solved once per formulation/profile,
  then reused in each paired comparison (not incorrectly counted as 8
  new independent solves).
- Three independently executed annual load profiles:
  `flat`, `two_shift`, `seasonal`.
- **Primary output:** the difference between molten-salt and packed-bed
  total annual objectives under each formulation at the **same factor**,
  and whether the winning technology differs between formulations.
- **Secondary:** change in sizing under each formulation. All actual
  solver states, checked physical constraints and derived configuration
  SHA-256 hashes are preserved. Any no-loadable-solution cell is
  explicitly indeterminate, with **no interpolation** or assigned
  economic objective.
- All costs are defined by current illustrative YAML assumptions, not
  measured procurement costs. Packed bed includes computed blower
  power consumption; no corresponding molten-salt pump parasitic model
  exists. Even a fidelity-dependent flip is therefore **not** a
  technology procurement recommendation.

## Reproduce

```bash
uv sync --all-extras --frozen
uv run python -m pytest -q tests/test_posthoc_fidelity_crossover.py
uv run python -m scripts.run_posthoc_fidelity_crossover \
  --profile two_shift --output runs/posthoc-two_shift.json
```

The dedicated workflow runs each profile independently and uploads its
unmodified JSON output to three artifact archives. This design answers a
narrower and more valuable scientific question than a generic CAPEX sweep:
**can the discharge-model simplification switch the cheapest technology
where the synthetic economic margins are close?** It may instead reinforce
the null result. Either result must be reported alongside missing cases and
the source/auxiliary boundary, without suppressing unfavourable results.
