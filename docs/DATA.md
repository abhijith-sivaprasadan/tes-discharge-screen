# Data and parameter sources

Every material property, cost figure, and profile shape used in this repository is
recorded here with its source. Config files reference this document rather than
repeating citations inline.

## How these citations were assembled (read this first)

Parameters below were located using a web search tool. For most of them, the
primary paper or report itself could not be opened directly in this working
environment: the network policy here blocks direct fetches to the great majority
of academic publisher and repository domains (ScienceDirect, ResearchGate, NCBI/PMC,
MDPI, university repositories, government agency PDFs were all tried and blocked).
What follows is therefore built from the search tool's own quoted extracts of those
papers, not from having read the papers myself end to end.

This is a real limitation on citation confidence, not a formality. Each entry below
is marked:

- **[search-quoted]**: a specific number came back as a direct quote attributed to
  the named source in the search results. Reasonably trustworthy, but not
  independently confirmed against the primary PDF's actual table.
- **[assumption]**: no literature figure was found for this parameter in the time
  available. It is an engineering estimate, explicitly not a citation, and is
  flagged as such in the config file that uses it.

Before anything here is presented publicly as a finding rather than a screening
input, re-verify the search-quoted figures against the primary source directly.

Cost figures quoted in USD are used at face value against EUR-denominated config
fields, with no FX adjustment. This project is a relative technology comparison
under harmonised assumptions, not an investment-grade cost study, so an
uncorrected ~5-10% USD/EUR gap does not change which technology looks cheaper by
the wide margins the literature reports between technologies (single digits to
tens of $/kWh apart).

## Two-tank molten salt ("Solar Salt", NaNO3-KNO3 60:40 wt%)

| Parameter | Value | Source |
|---|---|---|
| Operating range | 290 C (cold tank) to 565 C (hot tank) | Kearney, D. (2003), "Solar Field/Tank Options for CSP Plants using Molten Salt," SunLab / NREL subcontract report. This 290/565 pair is the standard two-tank design point reproduced throughout the CSP literature. [search-quoted, standard figure] |
| Specific heat | ~1.55 kJ/kg K average; 1.57 to 1.49 kJ/kg K over 250-425 C | SQM / DLR, "Solar Salt: Thermal Property Analysis Report." [search-quoted] |
| Density | rho [kg/m3] = 2091 - 0.641 x T[C], valid 260-593 C | Solar-salt density correlation reported in CSP thermal-storage property literature. [search-quoted; specific originating paper not independently re-opened] |
| Storage CAPEX | 22-30 $/kWh-th (two-tank, industrial scale) | Albrecht, K.J. et al. (2016), "Rock bed thermal storage: Concepts and costs," AIP Conference Proceedings 1734, 050003. [search-quoted] |
| Standing loss fraction/hour | 0.0005 (0.05%/h) | [assumption] insulated large tank, order-of-magnitude estimate; no per-hour loss figure for a specific tank design was found in the time available. |
| Storage power CAPEX ($/MW) | see config | [assumption] represents pumps and heat exchangers; no literature figure specific to this cost component was found. |

## Packed-bed sensible store (granite rock, this project's primary case)

| Parameter | Value | Source |
|---|---|---|
| Density | 2400 kg/m3 | Granite thermal-property literature, corroborated across an ACS Omega (2023) experimental study of granite/soapstone as CSP storage media and a 2025 ScienceDirect dataset paper on natural-stone thermophysical properties for heat storage. [search-quoted] |
| Specific heat | 790 J/kg K (individual samples reported 767-942 J/kg K) | Same sources as density. [search-quoted] |
| Thermal conductivity | ~2.5 W/m K (2.43-2.56 W/m K reported) | Same sources as density. [search-quoted] |
| Storage CAPEX | commonly cited <10, and specifically 5-8 $/kWh-th at scale (>1000 MWh-th) | Albrecht, K.J. et al. (2016), AIP Conference Proceedings 1734, 050003, "Rock bed thermal storage: Concepts and costs." [search-quoted] |
| Standing loss fraction/hour | 0.001 (0.1%/h) | [assumption] insulated packed bed, larger surface-to-volume ratio than a tank, order-of-magnitude estimate. |
| Storage power CAPEX ($/MW) | see config | [assumption] represents blowers/ducting/heat exchanger; no literature figure found. |

This is the technology the project's own hypothesis expects to show the largest
effect from the SOC-dependent discharge correction, because a packed bed develops
the strongest thermocline (falling outlet temperature) of the three.

### Phase B dynamic sub-model parameters (packed bed only)

`src/tes_screen/packed_bed_dynamics.py`'s default bed adds parameters the
Phase A annual model does not need: a particle size (for the interphase heat
transfer correlation) and air (HTF) properties.

| Parameter | Value | Source |
|---|---|---|
| Particle diameter | 0.03 m | [assumption] typical crushed-rock/gravel size in packed-bed CSP designs; no single citable figure was pinned down in the time available, so this is stated as a round, order-of-magnitude engineering choice, not a literature quote. |
| Porosity (packing void fraction) | 0.4 | [assumption] typical random-packed crushed rock; a common round figure in the packed-bed literature, not tied to one specific source this session. |
| Air density, specific heat, viscosity, thermal conductivity | rho=0.565 kg/m3, cp=1085 J/kgK, mu=3.1e-5 Pa.s, k=0.0454 W/mK | [textbook-standard] standard air property-table values (e.g. Incropera & DeWitt, *Fundamentals of Heat and Mass Transfer*) at a representative bed operating temperature (~350 C); interpolated from memory of standard tables, not independently re-verified against a table this session. Treat as order-of-magnitude, not exact. |
| Volumetric heat transfer coefficient (h_v) | derived, not assumed | Wakao, N., Kaguei, S. (1982), *Heat and Mass Transfer in Packed Beds*, Gordon and Breach. Nu = 2 + 1.1 Re^0.6 Pr^(1/3) (valid 15 < Re < 8500), scaled to a volumetric coefficient via the packing's specific surface area a_v = 6(1-eps)/d_p. A well-established, widely-cited correlation from general domain knowledge, not confirmed via search this session; deriving h_v from more fundamental quantities (particle size, flow rate, fluid properties) is more defensible than asserting a single bare h_v number, which is why this project computes it rather than picking one. |
| Governing equations | Schumann two-phase model, axial conduction neglected | Schumann, T.E.W. (1929), "Heat transfer: A liquid flowing through a porous prism," *Journal of the Franklin Institute*, 208(3), 405-416. Foundational, universally-cited packed-bed TES formulation; the same structure Zanganeh et al. (2012, see above) and the wider literature use. |

## High-temperature PCM (single-salt sodium nitrate, NaNO3)

| Parameter | Value | Source |
|---|---|---|
| Melting point | ~306 C | Kenisarin, M.M. (2010), "High-temperature phase change materials for thermal energy storage," Renewable and Sustainable Energy Reviews 14(3), 955-970. Widely reproduced figure for this well-known review; not independently re-opened this session. [search-quoted, standard figure] |
| Latent heat of fusion | ~177 kJ/kg | Same source. [search-quoted, standard figure] |
| Storage CAPEX | ~50-120 $/kWh-th for inorganic eutectic/nitrate PCM systems | Hirschey, J.R., Kumar, N. et al., "Review of Low-Cost Organic and Inorganic Phase Change Materials with Potential Application in Thermal Energy Storage," OSTI/Purdue technical report. [search-quoted] |
| Standing loss fraction/hour | 0.0007 | [assumption] between the tank and packed-bed estimates; no literature figure found. |
| Storage power CAPEX ($/MW) | see config | [assumption] represents the heat-exchanger network around the PCM module; no literature figure found. |

NaNO3's ~306 C melting point sits close to the 300 C steam process case, which is
deliberate: a latent-heat store only behaves like the "near-constant discharge
temperature" idealisation this project tests against if it is actually discharging
across its phase change near the process temperature. It is a poor match for the
400 C air process case (no common nitrate-salt PCM melts that high with useful
latent heat); the 400 C case is therefore only run for molten salt and packed bed
until a suitable high-temperature PCM composition is sourced.

## Phase B scope: packed bed only, for now

Only the packed-bed technology has a dynamic sub-model (Phase B) at this
commit, matching the project's own stated priority (a single technology
fully verified beats three unfinished) and the spec's expectation that
packed bed is where the SOC-dependent correction should matter most. The
packed-bed dynamic model is also adiabatic (no ambient heat loss term): that
is a deliberate scope choice, not an oversight. Phase A already accounts for
standing loss at the annual scale (`storage.standing_loss_fraction_per_hour`);
adding a second, redundant loss term inside the hours-long discharge
sub-model would double-count it and would also break the exact energy
conservation identity this module's strongest verification check
(`test_energy_conservation_holds_to_near_machine_precision`) depends on.
Molten-salt and PCM dynamic sub-models do not exist yet.

## Round-trip charge/discharge efficiency

`storage.eta_charge` and `storage.eta_discharge` (0.95/0.95 across all three
technology configs) are **[assumption]**, not literature-cited: they represent
heat-exchanger approach-temperature losses in a harmonised, technology-neutral
way so the comparison isolates the effect this project actually tests (the
discharge-power limit shape), rather than burying it under uninvestigated
efficiency differences. A real PCM store typically loses more to subcooling and
superheat than a sensible store does to approach temperature alone; using equal
efficiencies here is a deliberate simplification, stated plainly rather than
disguised as a finding.

## Synthetic load profiles

`src/tes_screen/synthetic_profiles.py` generates three load shapes: flat
continuous, two-shift, and seasonal. **These are synthetic profiles, not
measurements of any real site.** They exist to exercise the storage economics
under different duty cycles (continuous baseload, on/off industrial shifts,
winter-heavy seasonal demand), not to represent a specific plant. Shape
parameters (shift hours, seasonal amplitude) are named, documented arguments in
that module, not hidden constants.

## Synthetic electricity prices

`src/tes_screen/electricity_price.py` implements a real ENTSO-E day-ahead price
fetch, gated behind an `ENTSOE_API_KEY` environment variable that is not set in
this working environment (following the exact deferral pattern PyNEXUS itself
uses for the same reason: `data/entsoe.py` there is likewise built and unit-tested
but has never been run against a live credential). Until a key is available, Phase
A runs use a declared-synthetic price series with realistic daily/weekly shape and
volatility, generated by the same module. Every result produced from it is labeled
synthetic on the same screen, per the project's governing rules.
