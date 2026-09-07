"""PCM CAPEX sensitivity: does the technology ranking survive a corrected
storage-CAPEX citation?

Usage: python scripts/run_pcm_capex_sensitivity_experiment.py

A follow-up primary-source audit (docs/DATA.md, this session) found that
this project's own PCM `storage_capex_eur_per_mwh` (80,000 EUR/MWh-th,
`configs/pcm_300c_flat.yaml`) was set against a wrong citation: the paper
it cited (Hirschey et al. 2021) reviews *low-temperature* PCMs (0-65 C) for
*building* HVAC, not the high-temperature nitrate-salt PCM this project
actually screens (melting ~306 C). A corrected search found high-temperature
encapsulated-PCM (EPCM) system costs clustering around 15-21 $/kWh-th
(docs/DATA.md's corrected PCM row has the full citation trail) -- well
below the 80,000 EUR/MWh-th (~80-90 $/kWh-th) this project's own committed
results (Phase C3, Phase D.3) were generated against.

This script does not silently change that number: every already-committed
result stays exactly as run, at the capex figure it was actually run
against, with that figure's own now-corrected citation status stated
plainly in docs/DATA.md. Instead, it asks the direct question the
correction raises -- does the "packed bed is cheapest everywhere, PCM is
priced out entirely" finding survive a corrected PCM capex, or was it an
artifact of the wrong citation -- by sweeping PCM's own
`storage_capex_eur_per_mwh` from a value below the corrected literature
range up through the original (now-flagged-wrong) 80,000 EUR/MWh-th
ceiling, at this project's own headline case (300 C, flat load, tau=6h,
matched-duration sizing, C3's own methodology exactly), and comparing
PCM's own resulting total cost against packed bed's and molten salt's --
read directly from the already-committed `outputs/phase_c_full_matrix/
run_manifest.json` at the same (temperature, profile) point, not
re-solved, since neither depends on PCM's own capex at all.
"""

from __future__ import annotations

import dataclasses
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from tes_screen.config import CaseConfig, load_config  # noqa: E402
from tes_screen.discharge_curve import fit_piecewise_curve_from_power_curve  # noqa: E402
from tes_screen.dispatch import solve_dispatch  # noqa: E402
from tes_screen.pcm_dynamics import default_pcm_config  # noqa: E402
from tes_screen.pcm_dynamics import discharge_power_curve as pcm_discharge_power_curve  # noqa: E402
from tes_screen.pcm_dynamics import (  # noqa: E402
    mass_flow_for_target_duration as pcm_mass_flow_for_target_duration,
)
from tes_screen.pcm_dynamics import (  # noqa: E402
    reference_energy_capacity_mwh as pcm_reference_energy_capacity_mwh,
)
from tes_screen.synthetic_profiles import (  # noqa: E402
    build_load_profile,
    synthetic_daily_price_profile,
)
from tes_screen.verification import verify_schedule  # noqa: E402

CONFIG_PATH = Path("configs/pcm_300c_flat.yaml")
HEADLINE_DURATION_HOURS = 6.0  # C3's own headline duration
DELTA_T_MIN_HOT_SIDE_C = 0.0
N_SEGMENTS = 5
PROFILE_SHAPE = "flat"
PROCESS_TEMPERATURE_C = 300.0

REFERENCE_PCM_T_MAX_C = 330.0
REFERENCE_PCM_T_MIN_C = 300.0
REFERENCE_PCM_HTF_RETURN_TEMPERATURE_C = 290.0

# EUR/MWh-th = $/kWh-th at this project's own stated face-value USD/EUR
# convention (docs/DATA.md). Spans below the corrected literature range
# (15-21 $/kWh-th) up through the original, now-flagged-wrong ceiling
# (80,000 EUR/MWh-th, this project's own current committed config value).
CAPEX_SWEEP_EUR_PER_MWH = [
    10_000.0,
    15_000.0,
    18_000.0,
    21_000.0,
    25_000.0,
    30_000.0,
    40_000.0,
    50_000.0,
    60_000.0,
    80_000.0,
]
ORIGINAL_CONFIG_CAPEX_EUR_PER_MWH = 80_000.0

C3_MANIFEST_PATH = Path("outputs") / "phase_c_full_matrix" / "run_manifest.json"


def _reference_costs_from_c3() -> dict[str, float]:
    """Packed bed's and molten salt's own already-committed total costs at
    (300 C, flat, tau=6h) -- read, not re-solved, since neither depends on
    PCM's own capex at all."""
    manifest = json.loads(C3_MANIFEST_PATH.read_text())
    costs = {}
    for case in manifest["cases"]:
        matches_headline_case = (
            case["temperature_c"] == PROCESS_TEMPERATURE_C
            and case["profile_shape"] == PROFILE_SHAPE
        )
        if matches_headline_case and case["technology"] in {"packed_bed", "molten_salt"}:
            costs[case["technology"]] = case["constant_limit"]["kpis"]["total_cost_eur"]
    if set(costs) != {"packed_bed", "molten_salt"}:
        raise RuntimeError(
            f"Expected packed_bed and molten_salt reference costs from {C3_MANIFEST_PATH}, "
            f"got {sorted(costs)}. Re-run run_phase_c_full_matrix_experiment.py first."
        )
    return costs


def _pcm_curve():
    pcm_config = default_pcm_config()
    mass_flow = pcm_mass_flow_for_target_duration(
        pcm_config,
        HEADLINE_DURATION_HOURS,
        REFERENCE_PCM_T_MAX_C,
        REFERENCE_PCM_T_MIN_C,
        REFERENCE_PCM_HTF_RETURN_TEMPERATURE_C,
    )
    power_curve = pcm_discharge_power_curve(
        pcm_config,
        mass_flow,
        REFERENCE_PCM_T_MAX_C,
        REFERENCE_PCM_T_MIN_C,
        REFERENCE_PCM_HTF_RETURN_TEMPERATURE_C,
        PROCESS_TEMPERATURE_C,
        DELTA_T_MIN_HOT_SIDE_C,
        n_points=2000,
    )
    reference_energy_capacity_mwh = pcm_reference_energy_capacity_mwh(
        pcm_config, REFERENCE_PCM_T_MAX_C, REFERENCE_PCM_T_MIN_C
    )
    return fit_piecewise_curve_from_power_curve(
        power_curve, reference_energy_capacity_mwh, n_segments=N_SEGMENTS
    )


def _duration_matched_config(
    base_config: CaseConfig, capex_eur_per_mwh: float, soc_dependent: bool
):
    return dataclasses.replace(
        base_config,
        process=dataclasses.replace(base_config.process, profile_shape=PROFILE_SHAPE),
        storage=dataclasses.replace(
            base_config.storage,
            charge_power_max_mw=None,
            discharge_power_max_mw=None,
            design_duration_hours=HEADLINE_DURATION_HOURS,
            discharge_limit_mode="soc_dependent" if soc_dependent else "constant",
            discharge_capability_reference=("start_of_hour" if soc_dependent else None),
        ),
        economics=dataclasses.replace(
            base_config.economics, storage_capex_eur_per_mwh=capex_eur_per_mwh
        ),
    )


def _solved(config: CaseConfig, load, price, discharge_curve=None):
    result = solve_dispatch(config, load, price, discharge_curve=discharge_curve)
    checks = verify_schedule(result.schedule, config, result.solver["objective_eur"])
    if not all(checks.values()):
        raise RuntimeError(f"{config.case_name} failed independent verification")
    return result


def main() -> None:
    output_dir = Path("outputs") / "pcm_capex_sensitivity"
    output_dir.mkdir(parents=True, exist_ok=True)

    reference_costs = _reference_costs_from_c3()
    cheapest_reference_technology = min(reference_costs, key=reference_costs.get)
    cheapest_reference_cost = reference_costs[cheapest_reference_technology]

    base_config = load_config(CONFIG_PATH)
    horizon = base_config.optimization.horizon_hours
    load = build_load_profile(PROFILE_SHAPE, base_config.process.annual_peak_load_mw, horizon)
    price = synthetic_daily_price_profile(horizon)
    curve = _pcm_curve()

    points = []
    ranking_flip_capex_eur_per_mwh = None
    for capex in CAPEX_SWEEP_EUR_PER_MWH:
        constant_config = _duration_matched_config(base_config, capex, soc_dependent=False)
        constant_result = _solved(constant_config, load, price)
        soc_config = _duration_matched_config(base_config, capex, soc_dependent=True)
        soc_result = _solved(soc_config, load, price, discharge_curve=curve)

        pcm_beats_cheapest = constant_result.kpis["total_cost_eur"] < cheapest_reference_cost
        if pcm_beats_cheapest and ranking_flip_capex_eur_per_mwh is None:
            ranking_flip_capex_eur_per_mwh = capex

        point = {
            "storage_capex_eur_per_mwh": capex,
            "is_within_corrected_literature_range": 15_000.0 <= capex <= 21_000.0,
            "is_original_committed_config_value": capex == ORIGINAL_CONFIG_CAPEX_EUR_PER_MWH,
            "pcm_constant_total_cost_eur": constant_result.kpis["total_cost_eur"],
            "pcm_constant_e_cap_mwh": constant_result.kpis["e_cap_mwh"],
            "pcm_soc_dependent_total_cost_eur": soc_result.kpis["total_cost_eur"],
            "pcm_soc_dependent_e_cap_mwh": soc_result.kpis["e_cap_mwh"],
            "pcm_beats_cheapest_reference_technology": pcm_beats_cheapest,
        }
        points.append(point)
        print(
            f"capex={capex:>9,.0f} EUR/MWh-th  "
            f"pcm_cost(constant)={constant_result.kpis['total_cost_eur']:>12,.0f}  "
            f"pcm_e_cap={constant_result.kpis['e_cap_mwh']:>6.2f} MWh  "
            f"beats {cheapest_reference_technology}={pcm_beats_cheapest}"
        )

    manifest = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "note": (
            "Answers whether Phase C3/D.3's 'PCM priced out entirely' finding "
            "survives a corrected PCM storage-CAPEX citation (docs/DATA.md's "
            "PCM row); does not change any already-committed config or result."
        ),
        "headline_duration_hours": HEADLINE_DURATION_HOURS,
        "process_temperature_c": PROCESS_TEMPERATURE_C,
        "profile_shape": PROFILE_SHAPE,
        "reference_costs_eur_from_phase_c3": reference_costs,
        "reference_source": str(C3_MANIFEST_PATH),
        "cheapest_reference_technology": cheapest_reference_technology,
        "corrected_literature_range_eur_per_mwh": [15_000.0, 21_000.0],
        "original_committed_config_value_eur_per_mwh": ORIGINAL_CONFIG_CAPEX_EUR_PER_MWH,
        "ranking_flip_capex_eur_per_mwh": ranking_flip_capex_eur_per_mwh,
        "points": points,
    }
    (output_dir / "run_manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )

    print()
    print(f"Reference costs (from {C3_MANIFEST_PATH}): {reference_costs}")
    print(f"Cheapest reference technology: {cheapest_reference_technology}")
    if ranking_flip_capex_eur_per_mwh is not None:
        print(
            f"RESULT: PCM becomes cheapest than {cheapest_reference_technology} at "
            f"storage_capex_eur_per_mwh <= {ranking_flip_capex_eur_per_mwh:,.0f} EUR/MWh-th "
            f"-- within the tested range, including the corrected literature range."
        )
    else:
        print(
            "RESULT: PCM does not beat the cheapest reference technology anywhere in the "
            "tested range, including at the bottom of the corrected literature range."
        )
    print(f"Written to {output_dir}")


if __name__ == "__main__":
    main()
