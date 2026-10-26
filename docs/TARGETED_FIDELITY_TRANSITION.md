# Fine-grid follow-up: fidelity-induced technology choice (exploratory)

The broad fixed-CAPEX comparison has a narrowed technology choice crossover
between **0.375 and 0.400×** nominal molten-salt CAPEX, depending on profile.
At the coarse grid there is no confirmed constant-vs-SOC-dependent winner
difference. Previous unresolved cells must not be interpreted as losses.

**Post-hoc disclosure:** these additional factors were selected after
inspecting the coarse grid and interpolating the *location to investigate*.
No interpolated cost or interpolated winner is treated as numerical evidence.
Every chosen point must be independently solved and verified. No prospective
preregistration, independent external replication or parameter uncertainty
distribution is claimed.

The targeted factor grids are documented and fixed in
`scripts/run_targeted_fidelity_transition.py` before the new jobs run:

| Load | Molten-salt CAPEX factors (packed-bed remains 1.0x) |
|---|---|
| Flat | 0.3825, 0.3850, 0.3875 |
| Two-shift | 0.3925, 0.3930, 0.3935 |
| Seasonal | 0.3965, 0.3980, 0.3990 |

Every case runs both physical formulations for both technologies under
the **same 8,760h synthetic prices, heat load and six-hour design
duration**. Packed bed is independently solved once per formulation/profile,
not counted as a new solve at each other technology price factor. Original
model parameters are not altered except the specified molten-salt
energy and discharge-power CAPEX coefficients. Per-case objectives,
configuration digests, verifications, and full 8,760-hour model
schedules/configs are attached in the Actions artifact.

A confirmed winner disagreement at such extremely close hypothetical
costs means only **that the screening model's technology-selection
boundary is sensitive to discharge fidelity**. It is not proof the
simpler model is empirically wrong or that one technology should be
purchased. Pumping auxiliary energy for molten salt is not priced,
and raw cost assumptions are not validated against plant procurement.
A genuine robustness assessment requires harmonised fluid-handling
electricity cost and externally sourced costs.

The comparison code withholds all rankings involving a cell whose
solver lacks an independently verified optimal solution. It neither
interpolates a missing value nor treats it as proof of infeasibility.

Run:

```sh
uv run python -m scripts.run_targeted_fidelity_transition \
  --profile two_shift --output runs/targeted-two_shift.json
```
