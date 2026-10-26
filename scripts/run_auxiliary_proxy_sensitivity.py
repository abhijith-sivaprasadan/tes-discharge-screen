"""Post-hoc auxiliary-electricity proxy sensitivity around the verified TES crossover.

Applies a dimensionless per-MW thermal discharge parasitic power charge to
molten salt through the existing generic dispatch auxiliary input.  It is
NOT a molten-salt hydraulic/pumping model nor an empirically calibrated
auxiliary load. Re-solves dispatch for each rate and discharge formulation.
"""

from __future__ import annotations

import argparse
import dataclasses
import hashlib
import json
from pathlib import Path

from tes_screen.config import load_config
from tes_screen.dispatch import solve_dispatch
from tes_screen.synthetic_profiles import build_load_profile, synthetic_daily_price_profile
from tes_screen.verification import verify_schedule

TARGET_SALT_CAPEX_FACTORS = {
    "flat": 0.3850,
    "two_shift": 0.3930,
    "seasonal": 0.3965,
}
PROXY_PARASITIC_FACTORS = (0.0, 0.0001, 0.0005, 0.001)
FORMULATIONS = ("constant", "soc_dependent")


def grid():
    return [
        {"formulation": mode, "salt_capex_factor": factor, "proxy_parasitic_factor": aux}
        for mode in FORMULATIONS
        for factor in (1.0,)
        for aux in PROXY_PARASITIC_FACTORS
    ]


def main() -> None:
    from scripts import run_phase_c_full_matrix_experiment as fm
    from scripts.run_technology_reoptimisation import CONFIGS, modify_config

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", choices=tuple(TARGET_SALT_CAPEX_FACTORS), required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError("Do not overwrite registered solver output")
    profile = args.profile
    factor = TARGET_SALT_CAPEX_FACTORS[profile]
    curve, _, _ = fm.CURVE_BUILDERS["molten_salt"](300.0)
    records = []
    for formulation in FORMULATIONS:
        for auxiliary in PROXY_PARASITIC_FACTORS:
            config = modify_config(load_config(CONFIGS["molten_salt"]), "storage_capex", factor)
            cfg = fm._duration_matched_config(
                config, profile, soc_dependent=(formulation == "soc_dependent")
            )
            n = cfg.optimization.horizon_hours
            demand = build_load_profile(profile, cfg.process.annual_peak_load_mw, n)
            prices = synthetic_daily_price_profile(n)
            identity = {
                "formulation": formulation,
                "profile_shape": profile,
                "molten_salt_capex_factor": factor,
                "auxiliary_discharge_power_ratio": auxiliary,
            }
            try:
                result = solve_dispatch(
                    cfg,
                    demand,
                    prices,
                    discharge_curve=curve if formulation == "soc_dependent" else None,
                    blower_specific_power_mw_per_mw=auxiliary,
                )
            except RuntimeError as exc:
                records.append(
                    {**identity, "status": "NO_LOADABLE_SOLUTION", "exception": type(exc).__name__}
                )
                print(f"{identity}: no loadable solution", flush=True)
                continue
            checks = verify_schedule(result.schedule, cfg, result.solver["objective_eur"])
            if (
                result.solver["status"] != "ok"
                or result.solver["termination"] != "optimal"
                or not checks
                or not all(checks.values())
            ):
                raise RuntimeError(f"Unverified physical solution: {identity}")
            records.append(
                {
                    **identity,
                    "status": "OPTIMAL_VERIFIED",
                    "objective_eur": result.kpis["total_cost_eur"],
                    "size_mwh": result.kpis["e_cap_mwh"],
                    "rated_mw": result.kpis["power_rating_mw"],
                    "checks": checks,
                    "derived_config_sha256": hashlib.sha256(
                        json.dumps(dataclasses.asdict(cfg), sort_keys=True).encode()
                    ).hexdigest(),
                }
            )
            print(f"{identity}: {result.kpis['total_cost_eur']:.6f}", flush=True)
    result = {
        "status": "EXPLORATORY_REOPTIMIZED_UNCALIBRATED_AUXILIARY_PROXY",
        "posthoc": True,
        "profile": profile,
        "salt_capex_factor": factor,
        "proxy_parasitic_factors": list(PROXY_PARASITIC_FACTORS),
        "records": records,
        "interpretation_limit": (
            "An auxiliary electricity price proxy, not a validated hydraulic pump. "
            "Packed-bed reference is separately present in original fine-grid audit. "
            "No actual technology recommendation, measured pumping, or break-even certainty."
        ),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, allow_nan=False) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
