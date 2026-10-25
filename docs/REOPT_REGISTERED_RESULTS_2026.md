# Annual re-optimisation experiment: recorded evidence, 26 October 2026

GitHub Actions full-year experimental run:
[40246357647](https://github.com/abhijith-sivaprasadan/tes-discharge-screen/actions/runs/40246357647).
Three artifact files, one per synthetic load shape: `reoptimised-techno-economic-flat`,
`reoptimised-techno-economic-seasonal`,
`reoptimised-techno-economic-two_shift`.

The experiment registered 12 solves per shape: packed-bed and two-tank
molten-salt storage at 300 C, original 6 h duration-matched SOC-dependent
formulation, each technology's control, three altered storage CAPEX
multipliers (0.5/1.5/2) and two standing-loss multipliers (0.5/2).
The other technology is held at its separately re-solved control cost
for each single-factor comparison. 36 planned solves, **35 saved optimal
and independently schedule-verified**, one **NO_LOADABLE_SOLUTION** at flat
load / molten salt / 0.5x CAPEX. This does not prove mathematical
infeasibility or permit substituting a fabricated cost.

| Profile | Packed bed control (EUR) | Molten salt control (EUR) | 0.5x molten salt CAPEX result | Verified cost-winner flips |
|---|---:|---:|---|---:|
| Flat | 4,005,145.32 | 4,075,957.34 | No loadable solution | 0 |
| Two-shift | 2,817,469.77 | 2,944,140.94 | 2,840,575.97 | 0 |
| Seasonal | 2,890,904.65 | 2,991,423.82 | 2,909,320.64 | 0 |

At 0.5x molten-salt CAPEX, the solved technology cost difference over
unchanged packed bed is +EUR 23,106.20 (two-shift) and +EUR 18,415.99
(seasonal). These *observed evaluated grid points* are close enough
to motivate a **new explicitly post-hoc, labelled exploratory**
switch-threshold study; none was solved or asserted here.
No ranking flip in solved cases is **not** a proof there are no switches
between or outside the registered multipliers.

The original simplified physical model and economic asymmetry
(packed-bed blower priced, molten-salt pumping parasitic unpriced)
are preserved; no confidence intervals or empirical cost bounds are
inferred. Unit tests and three dedicated scenario-matrix workflow jobs
passed, but independent plant-based thermal validation is absent.
