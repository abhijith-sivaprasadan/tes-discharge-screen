"""Re-solve matched-duration thermal stores under registered isolated perturbations.

This is a synthetic assumption-sensitivity experiment, not uncertainty
quantification or empirical technology selection. It preserves source models
and ensures independent solver/physical checks for every new optimisation.
"""

from __future__ import annotations

import argparse
import dataclasses
import hashlib
import json
from pathlib import Path

from scripts.run_phase_c_full_matrix_experiment import (
    CURVE_BUILDERS,
    _blower_ratio,
    _duration_matched_config,
)
from tes_screen.config import load_config
from tes_screen.dispatch import solve_dispatch
from tes_screen.synthetic_profiles import build_load_profile, synthetic_daily_price_profile
from tes_screen.verification import verify_schedule


FACTORS = (0.5, 1.0, 1.5, 2.0)
PHYSICAL_FACTORS = (0.5, 2.0)
TECHNOLOGIES = ("packed_bed", "molten_salt")
CONFIGS = {
    "packed_bed": Path("configs/packed_bed_300c_flat.yaml"),
    "molten_salt": Path("configs/molten_salt_300c_flat.yaml"),
}


def registered_design() -> list[dict]:
    """No adaptive search or tuned-to-flip endpoints."""
    cases = []
    for technology in TECHNOLOGIES:
        cases.append({"technology": technology, "axis": "control", "factor": 1.0})
        for factor in FACTORS:
            if factor != 1.0:
                cases.append({"technology": technology, "axis": "storage_capex", "factor": factor})
        for factor in PHYSICAL_FACTORS:
            cases.append({"technology": technology, "axis": "standing_loss", "factor": factor})
    return cases


def modify_config(config, axis: str, factor: float):
    """Apply one parameter family at a time, with equal sizing degrees of freedom."""
    if axis == "control":
        return config
    if axis == "storage_capex":
        return dataclasses.replace(
            config,
            economics=dataclasses.replace(
                config.economics,
                storage_capex_eur_per_mwh=config.economics.storage_capex_eur_per_mwh * factor,
                storage_capex_eur_per_mw=config.economics.storage_capex_eur_per_mw * factor,
            ),
        )
    if axis == "standing_loss":
        return dataclasses.replace(
            config,
            storage=dataclasses.replace(
                config.storage,
                standing_loss_fraction_per_hour=(
                    config.storage.standing_loss_fraction_per_hour * factor
                ),
            ),
        )
    raise ValueError(f"Unsupported perturbation axis: {axis}")


def analyse(records: list[dict], profile: str) -> dict:
    controls = {r["technology"]: r for r in records if r["axis"] == "control" and r.get("status") == "OPTIMAL_VERIFIED"}
    if set(controls) != set(TECHNOLOGIES):
        raise ValueError("Incomplete controls")
    original_winner = min(controls, key=lambda k: controls[k]["total_cost_eur"])
    comparisons = []
    # The other technology is held exactly at its original unperturbed solve.
    for row in records:
        opponent = next(t for t in TECHNOLOGIES if t != row["technology"])
        winner = min(
            ((row["technology"], row["total_cost_eur"]),
             (opponent, controls[opponent]["total_cost_eur"])),
            key=lambda x: x[1],
        )[0]
        comparisons.append({
            "technology_perturbed": row["technology"],
            "axis": row["axis"],
            "factor": row["factor"],
            "chosen_technology_after_full_resolve": winner,
            "ranking_flipped_from_original_controls": winner != original_winner,
            "cost_difference_perturbed_minus_opponent_eur": (
                row["total_cost_eur"] - controls[opponent]["total_cost_eur"]
            ),
        })
    return {
        "profile_shape": profile,
        "control_winner": original_winner,
        "comparisons": comparisons,
        "status": "SCREENING_REOPTIMISED_SYNTHETIC_ASSUMPTIONS",
        "caveats": [
            "Matched duration is 6 h in both technologies and formulations.",
            "Only SOC-dependent models were re-optimised under each perturbation.",
            "Packed bed prices a quantified blower; molten salt pump parasitic is unmodelled.",
            "No confidence intervals, observed prices, plant validation or external cost certification.",
            "No interpolation between factors is presented as a solved break-even threshold.",
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile", choices=("flat", "seasonal", "two_shift"), required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    spec = registered_design()
    # Build all physical curves once and reuse for all strictly registered scenarios.
    curves = {}
    for technology in TECHNOLOGIES:
        curve, _raw, mass_flow = CURVE_BUILDERS[technology](300.0)
        curves[technology] = (curve, _blower_ratio(technology, curve, mass_flow))
    results = []
    for case in spec:
        technology = case["technology"]
        config_path = CONFIGS[technology]
        base = load_config(config_path)
        perturbed = modify_config(base, case["axis"], case["factor"])
        config = _duration_matched_config(perturbed, args.profile, soc_dependent=True)
        horizon = config.optimization.horizon_hours
        load = build_load_profile(args.profile, config.process.annual_peak_load_mw, horizon)
        price = synthetic_daily_price_profile(horizon)
        curve, blower = curves[technology]
        result = solve_dispatch(
            config,
            load,
            price,
            discharge_curve=curve,
            blower_specific_power_mw_per_mw=blower,
        )
        checks = verify_schedule(result.schedule, config, result.solver["objective_eur"])
        if result.solver["status"] != "ok" or result.solver["termination"] != "optimal":
            raise RuntimeError(f"Non-optimal: {case}")
        if not checks or not all(checks.values()):
            raise RuntimeError(f"Physical verification failed: {case}")
        results.append({
            **case,
            "config_sha256": hashlib.sha256(config_path.read_bytes()).hexdigest(),
            "objective_eur": result.solver["objective_eur"],
            "total_cost_eur": result.kpis["total_cost_eur"],
            "e_cap_mwh": result.kpis["e_cap_mwh"],
            "power_rating_mw": result.kpis["power_rating_mw"],
            "unmet_heat_mwh": result.kpis["unmet_heat_mwh"],
            "verification": checks,
        })
        print(f"{args.profile} {case} => {result.kpis['total_cost_eur']:.2f}", flush=True)
    report = {
        "design": spec,
        "analysis": analyse(results, args.profile),
        "solved_records": results,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, allow_nan=False) + "\n")
    print(json.dumps(report["analysis"], indent=2))


if __name__ == "__main__":
    main()
