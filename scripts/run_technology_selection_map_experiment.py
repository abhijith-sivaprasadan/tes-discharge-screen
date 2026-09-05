"""Phase D: the technology-selection map.

Usage: python scripts/run_technology_selection_map_experiment.py

TES_SCREEN_SPEC.md section 7's own third Phase D deliverable: "Two-
dimensional: process temperature against storage duration, coloured by
which technology wins. Explicitly labelled as conditional on the stated
boundaries, which is the whole point."

Phase C3 already established the technology ranking at one design
duration (tau=6h) across every valid technology/temperature/profile
combination and found it never flips. This script extends that into the
duration dimension C3 held fixed: for each (process temperature, design
duration) grid point, builds every valid technology's own discharge curve
at that duration (reusing each technology's own `mass_flow_for_target_
duration`, exactly as C3 does), solves both discharge-limit formulations
duration-matched, and records which technology is cheapest under each --
extending C3's single-duration ranking-flip finding into a genuine 2D map,
not just restating it.

Grid: process temperature in {300 C, 400 C} (the only two this project's
case configs actually support) x design duration in {2, 4, 6, 8, 12} hours
(the same grid C2 sweeps) = 10 (temperature, duration) points. PCM has no
400 C case (no suitable high-temperature nitrate-salt PCM composition
found; unchanged from every prior phase), so the 400 C column compares
only packed bed and molten salt, exactly as C3 already does at its own
single duration. Flat load profile only (C3 already showed profile shape
does not change the ranking-never-flips finding at tau=6h; re-sweeping
duration across all three profiles as well would triple this script's
already-substantial solve count for a dimension C3 has already answered).

This is explicitly a conditional map, not an absolute one, per the
spec's own instruction: it is conditional on every boundary tabulated in
README's Phase D boundary-harmonisation table (which cost figures are
[assumption] vs literature-cited, what is and is not inside each
technology's own storage capex, and -- flagged there directly -- that
only packed bed has any computed parasitic-load estimate at all, not
wired into any technology's actual cost here).
"""

from __future__ import annotations

import dataclasses
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from tes_screen.config import CaseConfig, load_config  # noqa: E402
from tes_screen.discharge_curve import (  # noqa: E402
    fit_piecewise_curve_from_power_curve,
)
from tes_screen.discharge_curve import (
    mass_flow_for_target_duration as packed_bed_mass_flow_for_target_duration,
)
from tes_screen.dispatch import solve_dispatch  # noqa: E402
from tes_screen.molten_salt_dynamics import default_molten_salt_config  # noqa: E402
from tes_screen.molten_salt_dynamics import (  # noqa: E402
    discharge_power_curve as molten_salt_discharge_power_curve,
)
from tes_screen.molten_salt_dynamics import (  # noqa: E402
    mass_flow_for_target_duration as molten_salt_mass_flow_for_target_duration,
)
from tes_screen.molten_salt_dynamics import (  # noqa: E402
    reference_energy_capacity_mwh as molten_salt_reference_energy_capacity_mwh,
)
from tes_screen.packed_bed_dynamics import (  # noqa: E402
    default_packed_bed_config,
    simulate_discharge,
)
from tes_screen.packed_bed_dynamics import (  # noqa: E402
    discharge_power_curve as packed_bed_discharge_power_curve,
)
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

DELTA_T_MIN_HOT_SIDE_C = 0.0
N_SEGMENTS = 5
DURATIONS_HOURS = [2.0, 4.0, 6.0, 8.0, 12.0]
PROFILE_SHAPE = "flat"

REFERENCE_PACKED_BED_N_STEPS = 1500
REFERENCE_PACKED_BED_TEMPERATURES_C = {300.0: (400.0, 320.0), 400.0: (500.0, 420.0)}
REFERENCE_MOLTEN_SALT_HOT_TANK_TEMPERATURE_C = 565.0
REFERENCE_MOLTEN_SALT_COLD_TANK_TEMPERATURE_C = 290.0
REFERENCE_PCM_T_MAX_C = 330.0
REFERENCE_PCM_T_MIN_C = 300.0
REFERENCE_PCM_HTF_RETURN_TEMPERATURE_C = 290.0

# (technology, process_temperature_c, config_path) -- same 5 valid
# combinations Phase C3 established; PCM has no 400 C case.
TECHNOLOGY_TEMPERATURE_CASES = [
    ("packed_bed", 300.0, "configs/packed_bed_300c_flat.yaml"),
    ("packed_bed", 400.0, "configs/packed_bed_400c_flat.yaml"),
    ("molten_salt", 300.0, "configs/molten_salt_300c_flat.yaml"),
    ("molten_salt", 400.0, "configs/molten_salt_400c_flat.yaml"),
    ("pcm", 300.0, "configs/pcm_300c_flat.yaml"),
]


def _packed_bed_curve(process_temperature_c: float, tau: float):
    bed_config = default_packed_bed_config()
    initial_temperature_c, inlet_temperature_c = REFERENCE_PACKED_BED_TEMPERATURES_C[
        process_temperature_c
    ]
    mass_flow = packed_bed_mass_flow_for_target_duration(
        bed_config,
        target_duration_hours=tau,
        initial_bed_temperature_c=initial_temperature_c,
        inlet_temperature_c=inlet_temperature_c,
        process_temperature_c=process_temperature_c,
        delta_t_min_hot_side_c=DELTA_T_MIN_HOT_SIDE_C,
    )
    result = simulate_discharge(
        bed_config,
        mass_flow_kg_per_s=mass_flow,
        initial_bed_temperature_c=initial_temperature_c,
        inlet_temperature_c=inlet_temperature_c,
        duration_s=tau * 2 * 3600.0,
        n_steps=REFERENCE_PACKED_BED_N_STEPS,
    )
    power_curve = packed_bed_discharge_power_curve(
        result, process_temperature_c, DELTA_T_MIN_HOT_SIDE_C
    )
    reference_energy_capacity_mwh = float(result.trace["bed_stored_energy_j"].iloc[0]) / 3.6e9
    return fit_piecewise_curve_from_power_curve(
        power_curve, reference_energy_capacity_mwh, n_segments=N_SEGMENTS
    )


def _molten_salt_curve(process_temperature_c: float, tau: float):
    salt_config = default_molten_salt_config()
    mass_flow = molten_salt_mass_flow_for_target_duration(
        salt_config,
        tau,
        REFERENCE_MOLTEN_SALT_HOT_TANK_TEMPERATURE_C,
        REFERENCE_MOLTEN_SALT_COLD_TANK_TEMPERATURE_C,
    )
    power_curve = molten_salt_discharge_power_curve(
        salt_config,
        mass_flow,
        REFERENCE_MOLTEN_SALT_HOT_TANK_TEMPERATURE_C,
        REFERENCE_MOLTEN_SALT_COLD_TANK_TEMPERATURE_C,
        process_temperature_c,
        DELTA_T_MIN_HOT_SIDE_C,
        n_points=2000,
    )
    reference_energy_capacity_mwh = molten_salt_reference_energy_capacity_mwh(
        salt_config,
        REFERENCE_MOLTEN_SALT_HOT_TANK_TEMPERATURE_C,
        REFERENCE_MOLTEN_SALT_COLD_TANK_TEMPERATURE_C,
    )
    return fit_piecewise_curve_from_power_curve(
        power_curve, reference_energy_capacity_mwh, n_segments=N_SEGMENTS
    )


def _pcm_curve(process_temperature_c: float, tau: float):
    if process_temperature_c != 300.0:
        raise ValueError("PCM only has a discharge model for the 300 C case")
    pcm_config = default_pcm_config()
    mass_flow = pcm_mass_flow_for_target_duration(
        pcm_config,
        tau,
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
        process_temperature_c,
        DELTA_T_MIN_HOT_SIDE_C,
        n_points=2000,
    )
    reference_energy_capacity_mwh = pcm_reference_energy_capacity_mwh(
        pcm_config, REFERENCE_PCM_T_MAX_C, REFERENCE_PCM_T_MIN_C
    )
    return fit_piecewise_curve_from_power_curve(
        power_curve, reference_energy_capacity_mwh, n_segments=N_SEGMENTS
    )


CURVE_BUILDERS = {
    "packed_bed": _packed_bed_curve,
    "molten_salt": _molten_salt_curve,
    "pcm": _pcm_curve,
}


def _duration_matched_config(
    base_config: CaseConfig, tau: float, soc_dependent: bool
) -> CaseConfig:
    return dataclasses.replace(
        base_config,
        process=dataclasses.replace(base_config.process, profile_shape=PROFILE_SHAPE),
        storage=dataclasses.replace(
            base_config.storage,
            charge_power_max_mw=None,
            discharge_power_max_mw=None,
            design_duration_hours=tau,
            discharge_limit_mode="soc_dependent" if soc_dependent else "constant",
            discharge_capability_reference=("start_of_hour" if soc_dependent else None),
        ),
    )


def _solved(config: CaseConfig, load, price, discharge_curve=None):
    result = solve_dispatch(config, load, price, discharge_curve=discharge_curve)
    checks = verify_schedule(result.schedule, config, result.solver["objective_eur"])
    if not all(checks.values()):
        raise RuntimeError(f"{config.case_name} failed independent verification")
    return result


def main() -> None:
    output_dir = Path("outputs") / "technology_selection_map"
    output_dir.mkdir(parents=True, exist_ok=True)

    cases = []
    for technology, temperature_c, config_path in TECHNOLOGY_TEMPERATURE_CASES:
        base_config = load_config(Path(config_path))
        horizon = base_config.optimization.horizon_hours
        load = build_load_profile(PROFILE_SHAPE, base_config.process.annual_peak_load_mw, horizon)
        price = synthetic_daily_price_profile(horizon)

        for tau in DURATIONS_HOURS:
            curve = CURVE_BUILDERS[technology](temperature_c, tau)

            constant_config = _duration_matched_config(base_config, tau, soc_dependent=False)
            constant_result = _solved(constant_config, load, price)

            soc_config = _duration_matched_config(base_config, tau, soc_dependent=True)
            soc_result = _solved(soc_config, load, price, discharge_curve=curve)

            entry = {
                "technology": technology,
                "temperature_c": temperature_c,
                "tau_hours": tau,
                "constant_total_cost_eur": constant_result.kpis["total_cost_eur"],
                "soc_total_cost_eur": soc_result.kpis["total_cost_eur"],
            }
            cases.append(entry)
            print(
                f"{technology:12s} {temperature_c:5.0f}C tau={tau:5.1f}h  "
                f"constant={constant_result.kpis['total_cost_eur']:>12,.0f}  "
                f"soc={soc_result.kpis['total_cost_eur']:>12,.0f}"
            )

    ranking_rows = []
    for temperature_c in [300.0, 400.0]:
        for tau in DURATIONS_HOURS:
            group = [
                c for c in cases if c["temperature_c"] == temperature_c and c["tau_hours"] == tau
            ]
            cheapest_constant = min(group, key=lambda c: c["constant_total_cost_eur"])["technology"]
            cheapest_soc = min(group, key=lambda c: c["soc_total_cost_eur"])["technology"]
            ranking_rows.append(
                {
                    "temperature_c": temperature_c,
                    "tau_hours": tau,
                    "technologies_compared": sorted(c["technology"] for c in group),
                    "cheapest_technology_constant": cheapest_constant,
                    "cheapest_technology_soc_dependent": cheapest_soc,
                    "ranking_flipped": cheapest_constant != cheapest_soc,
                }
            )
            print(
                f"{temperature_c:.0f}C tau={tau:5.1f}h  "
                f"cheapest(constant)={cheapest_constant:12s}  "
                f"cheapest(soc)={cheapest_soc:12s}  flipped={cheapest_constant != cheapest_soc}"
            )

    any_flip = any(row["ranking_flipped"] for row in ranking_rows)

    manifest = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "roadmap_item": "Phase D.3 (technology-selection map, TES_SCREEN_SPEC.md section 7)",
        "conditional_on_note": (
            "This map is conditional on the boundaries tabulated in "
            "README's Phase D boundary-harmonisation table, not an "
            "absolute technology ranking -- per the spec's own explicit "
            "instruction. In particular: cost figures mix literature-cited "
            "and [assumption] values with different confidence levels "
            "across technologies, and only packed bed has any computed "
            "parasitic-load estimate (P3.3's blower power) at all, not "
            "wired into any technology's cost here."
        ),
        "temperatures_c": [300.0, 400.0],
        "durations_hours": DURATIONS_HOURS,
        "profile_shape": PROFILE_SHAPE,
        "cases": cases,
        "ranking_table": ranking_rows,
        "any_ranking_flip": any_flip,
    }
    (output_dir / "run_manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print()
    if any_flip:
        print(
            "RESULT: the technology ranking DOES flip somewhere in this duration x temperature map."
        )
    else:
        print(
            "RESULT: the technology ranking does not flip anywhere across the full duration x "
            "temperature grid, under either discharge-limit formulation."
        )
    print(f"Written to {output_dir}")


if __name__ == "__main__":
    main()
