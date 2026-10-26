# Exploratory molten-salt discharge-parasitic proxy sensitivity

**Status:** prospective code design relative to these numerical runs, but
post-hoc in the broader research programme: the focus cases were deliberately
chosen after seeing the fidelity-dependent price crossover.

This is a direct re-optimisation, not just a fixed-hour cost adjustment.
The existing Pyomo dispatch objective already supports an optional
electricity-price-times-thermal-discharge-power multiplier. Its code calls
that input `blower_specific_power_mw_per_mw`, but this study repurposes
the same generic cost mathematics as an **uncalibrated liquid-salt
pumping/handling auxiliary electricity price proxy**.

For each of three load profiles, two discharge formulations, and four
dimensionless auxiliary ratios (0, 0.0001, 0.0005 and 0.001 MW_e/MW_th),
re-optimize the complete 8,760-hour dispatch. The ratio is a
hypothetical scenario; no corresponding pump-head, hydraulic curve,
viscosity, mass flow, material/corrosion or vendor specification has been
validated. A result at 0.0001 must not be called a measured pump
coefficient. Packed bed retains its previously modelled priced blower in
the original comparator; **complete physical parity is still missing**.

Focus cost factors: flat 0.3850; two-shift 0.3930; seasonal 0.3965.
Each run preserves its source configuration SHA-256 and independent
post-solve physics checks. The comparator reference costs and full
hourly evidence are in the associated validated `targeted-*.json`
archives, not reverse-engineered or changed here.

The key outcome is whether any extra auxiliary electricity assumption
removes the narrow original model-specific cost selection disagreement.
Even if it does, the result is a **fragility diagnostic**, not a robust
procurement choice, cost confidence bound, or field-validated study.
