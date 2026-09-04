"""Phase C: the paired constant-vs-SOC-dependent experiment (MVP scope, C2).

Usage: python scripts/run_phase_c_experiment.py

Solves configs/packed_bed_300c_flat.yaml twice: once with the constant
discharge limit (Phase A's baseline) and once with the SOC-dependent limit
derived from the Phase B packed-bed shadow twin (discharge_curve.py's
piecewise-linear construction, C1). Verifies both, reports the deltas C2
asks for, and checks that the answer does not materially change with more
piecewise segments (C1's own instruction).

This is the minimum viable version the build spec's own section 10 and 8
describe: one technology (packed bed), one process temperature (300 C), one
load profile (flat), both formulations. It is not the full 18-run matrix
(3 technologies x 2 temperatures x 3 profiles): only packed bed has a Phase B
dynamic sub-model, so a technology-ranking comparison is not answerable yet.
See the run manifest and the project README for what this result does and
does not show.

**Archived (README/MODEL_CARD): its committed output is superseded by
run_phase_c2_duration_matched_experiment.py, kept unmodified rather than
re-run.** Its calls are still updated to match discharge_power_curve's
current signature (P0.2), so re-running this script does not error, but it
now uses the corrected physics and will not reproduce the committed
`outputs/phase_c_packed_bed_300c_flat/` numbers if actually run again.
"""

from __future__ import annotations

import dataclasses
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from tes_screen.config import load_config  # noqa: E402
from tes_screen.discharge_curve import (  # noqa: E402
    fit_piecewise_discharge_curve,
    piecewise_curve_to_frame,
    verify_piecewise_curve_is_safe,
)
from tes_screen.dispatch import solve_dispatch  # noqa: E402
from tes_screen.packed_bed_dynamics import (  # noqa: E402
    default_packed_bed_config,
    simulate_discharge,
)
from tes_screen.synthetic_profiles import (  # noqa: E402
    build_load_profile,
    synthetic_daily_price_profile,
)
from tes_screen.verification import verify_schedule  # noqa: E402

CONFIG_PATH = Path("configs/packed_bed_300c_flat.yaml")
REFERENCE_DRAW_RATE_KG_PER_S = 3.0
REFERENCE_INITIAL_BED_TEMPERATURE_C = 400.0
REFERENCE_INLET_TEMPERATURE_C = 320.0
REFERENCE_DURATION_S = 30 * 3600.0
REFERENCE_N_STEPS = 1500
DELTA_T_MIN_HOT_SIDE_C = 0.0  # [assumption]; see run_packed_bed_dynamics.py's own note (P0.2)
PRIMARY_N_SEGMENTS = 5
ROBUSTNESS_N_SEGMENTS = [3, 5, 8, 12]


def _solved(config, load, price, discharge_curve=None):
    result = solve_dispatch(config, load, price, discharge_curve=discharge_curve)
    checks = verify_schedule(result.schedule, config, result.solver["objective_eur"])
    return result, checks


def main() -> None:
    output_dir = Path("outputs") / "phase_c_packed_bed_300c_flat"
    output_dir.mkdir(parents=True, exist_ok=True)

    config = load_config(CONFIG_PATH)
    horizon = config.optimization.horizon_hours
    load = build_load_profile(
        config.process.profile_shape, config.process.annual_peak_load_mw, horizon
    )
    price = synthetic_daily_price_profile(horizon)

    bed_config = default_packed_bed_config()
    discharge_result = simulate_discharge(
        bed_config,
        REFERENCE_DRAW_RATE_KG_PER_S,
        REFERENCE_INITIAL_BED_TEMPERATURE_C,
        REFERENCE_INLET_TEMPERATURE_C,
        REFERENCE_DURATION_S,
        n_steps=REFERENCE_N_STEPS,
    )

    # Robustness check across segment counts (C1): solve the SOC-dependent
    # case at each count, not just fit the curve, since what matters is
    # whether the *answer* changes, not just the curve's own fit error
    # (already checked in discharge_curve.py's own tests).
    robustness = []
    for n_segments in ROBUSTNESS_N_SEGMENTS:
        curve = fit_piecewise_discharge_curve(
            discharge_result,
            config.process.delivery_temperature_c,
            DELTA_T_MIN_HOT_SIDE_C,
            n_segments=n_segments,
        )
        safety = verify_piecewise_curve_is_safe(
            curve, discharge_result, config.process.delivery_temperature_c, DELTA_T_MIN_HOT_SIDE_C
        )
        soc_config = dataclasses.replace(
            config,
            storage=dataclasses.replace(
                config.storage, discharge_limit_mode="soc_dependent", discharge_power_max_mw=None
            ),
        )
        result, checks = _solved(soc_config, load, price, discharge_curve=curve)
        robustness.append(
            {
                "n_segments": n_segments,
                "max_overestimate_mw": safety["max_overestimate_mw"],
                "mean_absolute_error_mw": safety["mean_absolute_error_mw"],
                "total_cost_eur": result.kpis["total_cost_eur"],
                "e_cap_mwh": result.kpis["e_cap_mwh"],
                "power_rating_mw": result.kpis["power_rating_mw"],
                "verification_passed": all(checks.values()),
            }
        )
        if n_segments == PRIMARY_N_SEGMENTS:
            primary_curve = curve
            primary_result = result
            primary_checks = checks

    # Constant-limit baseline, same config, same profiles.
    constant_result, constant_checks = _solved(config, load, price)

    constant_result.schedule.to_csv(output_dir / "constant_schedule.csv", index=False)
    primary_result.schedule.to_csv(output_dir / "soc_dependent_schedule.csv", index=False)
    piecewise_curve_to_frame(primary_curve).to_csv(
        output_dir / "discharge_curve_breakpoints.csv", index=False
    )

    delta = {
        "total_cost_eur": primary_result.kpis["total_cost_eur"]
        - constant_result.kpis["total_cost_eur"],
        "total_cost_pct": 100
        * (primary_result.kpis["total_cost_eur"] - constant_result.kpis["total_cost_eur"])
        / constant_result.kpis["total_cost_eur"],
        "e_cap_mwh": primary_result.kpis["e_cap_mwh"] - constant_result.kpis["e_cap_mwh"],
        "power_rating_mw": primary_result.kpis["power_rating_mw"]
        - constant_result.kpis["power_rating_mw"],
        "fuel_cost_eur": primary_result.kpis["fuel_cost_eur"]
        - constant_result.kpis["fuel_cost_eur"],
        "emissions_tco2": primary_result.kpis["emissions_tco2"]
        - constant_result.kpis["emissions_tco2"],
        "electricity_cost_eur": (
            primary_result.kpis["electricity_cost_eur"]
            - constant_result.kpis["electricity_cost_eur"]
        ),
        "wall_time_seconds_constant": constant_result.solver["wall_time_seconds"],
        "wall_time_seconds_soc_dependent": primary_result.solver["wall_time_seconds"],
    }

    manifest = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "case": "packed_bed_300c_flat",
        "note": (
            "MVP scope per the build spec's own section 10/8: one technology "
            "(packed bed), one process temperature (300 C), one load profile "
            "(flat), both discharge-limit formulations. Not the full 18-run "
            "matrix; only packed bed has a Phase B dynamic sub-model, so a "
            "technology-ranking comparison is not answerable from this run."
        ),
        "reference_discharge": {
            "mass_flow_kg_per_s": REFERENCE_DRAW_RATE_KG_PER_S,
            "initial_bed_temperature_c": REFERENCE_INITIAL_BED_TEMPERATURE_C,
            "inlet_temperature_c": REFERENCE_INLET_TEMPERATURE_C,
        },
        "constant_limit": {
            "solver": constant_result.solver,
            "kpis": constant_result.kpis,
            "verification_checks": constant_checks,
            "verification_passed": all(constant_checks.values()),
        },
        "soc_dependent": {
            "n_segments": PRIMARY_N_SEGMENTS,
            "solver": primary_result.solver,
            "kpis": primary_result.kpis,
            "verification_checks": primary_checks,
            "verification_passed": all(primary_checks.values()),
        },
        "delta_soc_dependent_minus_constant": delta,
        "segment_count_robustness_check": robustness,
    }
    (output_dir / "run_manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )

    print(
        f"Constant-limit:    {constant_result.solver['termination']}, "
        f"cost={constant_result.kpis['total_cost_eur']:,.2f} EUR/yr, "
        f"E_cap={constant_result.kpis['e_cap_mwh']:.2f} MWh, "
        f"P={constant_result.kpis['power_rating_mw']:.2f} MW"
    )
    print(
        f"SOC-dependent:     {primary_result.solver['termination']}, "
        f"cost={primary_result.kpis['total_cost_eur']:,.2f} EUR/yr, "
        f"E_cap={primary_result.kpis['e_cap_mwh']:.2f} MWh, "
        f"P={primary_result.kpis['power_rating_mw']:.2f} MW"
    )
    print(
        f"Delta: cost {delta['total_cost_pct']:+.3f}%, "
        f"E_cap {delta['e_cap_mwh']:+.2f} MWh, "
        f"power {delta['power_rating_mw']:+.2f} MW"
    )
    print(f"Written to {output_dir}")

    if not (all(constant_checks.values()) and all(primary_checks.values())):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
