# TES-Discharge Screen — computational research freeze, 26 October 2026

**Status:** Portfolio / author working-paper research milestone. **Not** peer-reviewed, externally validated, or a technology procurement recommendation.

## Identity and immutable reference

- Research source/code commit after [PR #6](https://github.com/abhijith-sivaprasadan/tes-discharge-screen/pull/6): `1e96c115278f872e406e19c25f9fecb19e375abe`.
- Freeze date: 2026-10-26. A separately named snapshot branch may be created after the freeze record is merged; only an exact commit hash, not a movable branch name, identifies reproducible code.
- Working manuscript (text): [TES_CROSSOVER_WORKING_PAPER_2026-10-26.md](TES_CROSSOVER_WORKING_PAPER_2026-10-26.md). Publication-ready peer-reviewed status **not claimed**.
- Prior [PR #5](https://github.com/abhijith-sivaprasadan/tes-discharge-screen/pull/5): registered 36-case screening, 35 verified, 1 no-loadable-solution; **no** selection reversal in that original registered study.
- PR #6: source-audited post-hoc economic crossover, 23 verified / 24 attempted distinct 8,760-hour optimizations; six matched-economic-factor formulation choice disagreements, one unresolved seasonal cell. No statistical inference, market threshold or external replication.
- Separate **24 solved/verified** hypothetical auxiliary-cost proxy optimizations; representative SOC-dependent molten salt advantages disappear at tested ratios 0.0001–0.0005 MW-e/MW-th, but these are **uncalibrated arbitrary sensitivity coefficients**, not a measured molten-salt pumping model.

## Verified research claims

The narrow conditional claim is that the **synthetic model's selected least-cost technology can depend on discharge representation near a deliberately searched economic crossover**. For example, at the *post-hoc selected* two-shift, molten-salt CAPEX multiplier 0.3930, the constant model favors packed bed by about EUR 164 annually, while the SOC-dependent model favors molten salt by about EUR 126 annually. With the additional hypothetical auxiliary ratio of 0.0001 MW-e/MW-th in a separately re-solved case, molten salt is no longer cheaper. Neither result implies a meaningful real-world installed-cost difference.

Independent research evidence audit reconstructed all 23 archived optimal-solver schedules from **8,760 hourly records each** with config and schedule SHA256 checks; maximum cost difference to saved solved objective 4.66e-10 EUR. All nine Python/OS combinations in GitHub Actions [CI 40356868003](https://github.com/abhijith-sivaprasadan/tes-discharge-screen/actions/runs/40356868003) passed before PR #6 merged.

## Original raw evidence (finite retention)

- [Targeted source-hashed annual schedules/configs, run 40344628085](https://github.com/abhijith-sivaprasadan/tes-discharge-screen/actions/runs/40344628085): `tes-posthoc-targeted-flat-raw`, `tes-posthoc-targeted-two_shift-raw`, `tes-posthoc-targeted-seasonal-raw`.
- [Auxiliary proxy reoptimizations, run 40354076547](https://github.com/abhijith-sivaprasadan/tes-discharge-screen/actions/runs/40354076547): `tes-auxiliary-proxy-flat`, `tes-auxiliary-proxy-two_shift`, `tes-auxiliary-proxy-seasonal`.
- The above Actions artifacts expire; their SHA256 and original ZIP files were included in an independently constructed offline research evidence package dated 2026-10-26. **No institutional DOI or permanent trusted archive is claimed.** The auxiliary probe artifacts preserve aggregate solver verifications but not independent hourly dispatch for all 24 runs; they carry weaker archival granularity than the initial fine-grid evidence.

## Remaining explicit scientific exclusions

1. No independently validated industrial facility data or external measured thermal cycling at a calibrated plant.
2. The packed-bed internal-state structure cannot universally be recovered from a single SOC; the curves are trajectory-derived.
3. A priced packed-bed blower exists but no physically harmonized, measured molten-salt pump auxiliary is incorporated; the new proxy sensitivity illustrates the fragility without resolving this mismatch.
4. No harmonized installed CAPEX/OPEX from validated original equipment quotes or robust input uncertainties; economic factors of 0.38–0.40 of an illustrative salt cost were chosen **after prior results**.
5. No external journal acceptance, validated general technology selection map, actual observed tariffs at this model's scenario boundary, or inferential estimate of real market likelihood.

## Maintenance policy

Freeze **new hypothesis-driven scope and UI/features**; preserve original experiment outputs and protocols. Maintain CI, security and reproducibility fixes, and correct materially wrong statements with separately labelled revisions. The GitHub repo remains editable; a snapshot branch is **not** equivalent to repository archival, copyright deposit, an immutable signed release or DOI.

Any future real-world inference requires measured molten-salt hydraulics, externally sourced complete installed cost, independent plant thermal response and a prospectively frozen validation plan. Do not disguise those as already completed work.
