"""Post-hoc exploratory *paired-formulation* technology-selection screening.

The prior registered study found no winner change down to 0.5x molten-salt
CAPEX. These closer factors were selected *after inspecting those results*.
Every grid point re-solves both the constant-power and SOC-dependent
formulations for each technology; no existing objective is relabelled.
"""

from __future__ import annotations

import argparse
import dataclasses
import hashlib
import json
import math
from pathlib import Path

from tes_screen.config import load_config
from tes_screen.dispatch import solve_dispatch
from tes_screen.synthetic_profiles import build_load_profile, synthetic_daily_price_profile
from tes_screen.verification import verify_schedule

SALT_CAPEX_FACTORS = (0.25, 0.35, 0.375, 0.4, 0.425, 0.45, 0.5, 1.0)
FORMULATIONS = ("constant", "soc_dependent")
TECHNOLOGIES = ("packed_bed", "molten_salt")
COMPARISON_TOLERANCE_EUR = 1.0


def study_grid(factors: tuple[float, ...] = SALT_CAPEX_FACTORS) -> list[dict]:
    """Same economic perturbation for molten salt in each physical formulation."""
    if not factors or len(set(factors)) != len(factors) or any(
        not math.isfinite(f) or f <= 0 for f in factors
    ):
        raise ValueError("Unique positive finite CAPEX factors required")
    return [
        {"technology": t, "formulation": form, "molten_salt_capex_factor": fac}
        for fac in factors
        for form in FORMULATIONS
        for t in TECHNOLOGIES
    ]


def _winner(salt_minus_packed_eur: float) -> str:
    if not math.isfinite(salt_minus_packed_eur):
        raise ValueError("Nonfinite relative annual objective")
    if abs(salt_minus_packed_eur) <= COMPARISON_TOLERANCE_EUR:
        return "indistinguishable_at_1_eur_tolerance"
    return "packed_bed" if salt_minus_packed_eur > 0 else "molten_salt"


def compare_fidelity_rankings(
    rows: list[dict], profile: str, *, factors: tuple[float, ...] = SALT_CAPEX_FACTORS
) -> dict:
    """No missing cost may be substituted with a guessed/interpolated value."""
    expected = {
        (r["molten_salt_capex_factor"], r["formulation"], r["technology"]) for r in study_grid(factors)
    }
    by_id = {}
    for row in rows:
        key = (row["molten_salt_capex_factor"], row["formulation"], row["technology"])
        if key not in expected or key in by_id:
            raise ValueError("Unexpected or duplicated grid point")
        by_id[key] = row
    if set(by_id) != expected:
        raise ValueError("Missing registered exploratory grid points")

    pairs = []
    for fac in factors:
        form_out = {}
        for formulation in FORMULATIONS:
            packed = by_id[(fac, formulation, "packed_bed")]
            molten = by_id[(fac, formulation, "molten_salt")]
            statuses = (packed["status"], molten["status"])
            if statuses != ("OPTIMAL_VERIFIED", "OPTIMAL_VERIFIED"):
                form_out[formulation] = {
                    "status": "INDETERMINATE_MISSING_VERIFIED_SOLVE",
                    "failed_or_unverified": [
                        {"technology": row["technology"], "status": row["status"]}
                        for row in (packed, molten)
                        if row["status"] != "OPTIMAL_VERIFIED"
                    ],
                }
                continue
            salt_cost = float(molten["total_cost_eur"])
            packed_cost = float(packed["total_cost_eur"])
            difference = salt_cost - packed_cost
            form_out[formulation] = {
                "status": "BOTH_OPTIMAL_VERIFIED",
                "salt_minus_packed_eur_per_year": difference,
                "winner": _winner(difference),
                "packed_bed_total_eur_per_year": packed_cost,
                "molten_salt_total_eur_per_year": salt_cost,
            }
        constant, soc = form_out["constant"], form_out["soc_dependent"]
        if constant["status"] == soc["status"] == "BOTH_OPTIMAL_VERIFIED":
            if "indistinguishable" in constant["winner"] or "indistinguishable" in soc["winner"]:
                flag = "UNDETERMINED_NEAR_TIE"
            else:
                flag = "DISAGREEMENT" if constant["winner"] != soc["winner"] else "AGREEMENT"
            delta_margin = (
                soc["salt_minus_packed_eur_per_year"] - constant["salt_minus_packed_eur_per_year"]
            )
        else:
            flag, delta_margin = "UNDETERMINED_MISSING_RESULT", None
        pairs.append(
            {
                "molten_salt_capex_factor": fac,
                "by_formulation": form_out,
                "formulation_ranking_comparison": flag,
                "soc_minus_constant_change_in_salt_cost_advantage_eur": delta_margin,
            }
        )
    return {
        "status": "EXPLORATORY_POSTHOC_RESOLVED_FORMULATION_COMPARISON",
        "profile_shape": profile,
        "registered_after_prior_2026_sensitivity_results": True,
        "cost_grid": list(factors),
        "pairwise_comparisons": pairs,
        "confirmed_disagreements": sum(
            row["formulation_ranking_comparison"] == "DISAGREEMENT" for row in pairs
        ),
        "unresolved_factors": [
            row["molten_salt_capex_factor"]
            for row in pairs
            if row["formulation_ranking_comparison"].startswith("UNDETERMINED")
        ],
        "limits": [
            "Not prospectively registered: factors selected after previous 0.5x finding.",
            "Both formulations use original model curves, prices, demand and 6h duration.",
            "The salt CAPEX coefficients are illustrative and unverified by procurement data.",
            "Packed-bed blower is modelled; molten-salt pump parasitic is omitted.",
            "A 1 EUR annual objective tie tolerance is an interpretive filter, not solver precision.",
            "No threshold interpolation, field validation, confidence interval or LCOH claim.",
        ],
    }


def run_experiment(
    profile: str,
    *,
    factors: tuple[float, ...] = SALT_CAPEX_FACTORS,
    hourly_output_dir: Path | None = None,
) -> dict:
    from scripts import run_phase_c_full_matrix_experiment as full_matrix
    from scripts.run_technology_reoptimisation import CONFIGS, modify_config

    if hourly_output_dir is not None:
        if hourly_output_dir.exists():
            raise FileExistsError("Never overwrite hourly source evidence")
        hourly_output_dir.mkdir(parents=True)
    curves = {}
    for technology in TECHNOLOGIES:
        curve, _source, mass_flow = full_matrix.CURVE_BUILDERS[technology](300.0)
        blower = full_matrix._blower_ratio(technology, curve, mass_flow)
        curves[technology] = (curve, blower)
    results = []
    # Reuse only the *solve results of the same physical and CAPEX config*
    # for packed-bed across salt multipliers: the packed-bed problem is
    # mathematically identical at each factor. We still record the exact
    # originating solve identifier, rather than presenting eight new solves.
    verified_packed = {}
    for case in study_grid(factors):
        technology = case["technology"]
        formulation = case["formulation"]
        factor = case["molten_salt_capex_factor"]
        if technology == "packed_bed" and formulation in verified_packed:
            source = verified_packed[formulation]
            results.append(
                {
                    **case,
                    **{k: v for k, v in source.items() if k not in case},
                    "solve_reused_from_factor": factors[0],
                }
            )
            continue
        config_path = CONFIGS[technology]
        base = load_config(config_path)
        changed = (
            modify_config(base, "storage_capex", factor) if technology == "molten_salt" else base
        )
        cfg = full_matrix._duration_matched_config(
            changed, profile, soc_dependent=(formulation == "soc_dependent")
        )
        n = cfg.optimization.horizon_hours
        demand = build_load_profile(profile, cfg.process.annual_peak_load_mw, n)
        prices = synthetic_daily_price_profile(n)
        curve, blower = curves[technology]
        config_digest = hashlib.sha256(
            json.dumps(dataclasses.asdict(cfg), sort_keys=True).encode()
        ).hexdigest()
        try:
            solved = solve_dispatch(
                cfg,
                demand,
                prices,
                discharge_curve=curve if formulation == "soc_dependent" else None,
                blower_specific_power_mw_per_mw=blower,
            )
        except RuntimeError as error:
            item = {
                **case,
                "status": "NO_LOADABLE_SOLUTION_NOT_PROVEN_INFEASIBLE",
                "solver_exception_type": type(error).__name__,
                "derived_config_sha256": config_digest,
            }
            results.append(item)
            print(f"{profile} {case} NOT SOLVED", flush=True)
            continue
        checks = verify_schedule(solved.schedule, cfg, solved.solver["objective_eur"])
        if (
            solved.solver["status"] != "ok"
            or solved.solver["termination"] != "optimal"
            or not checks
            or not all(checks.values())
        ):
            raise RuntimeError(f"Unverified solution: {case}")
        item = {
            **case,
            "status": "OPTIMAL_VERIFIED",
            "total_cost_eur": solved.kpis["total_cost_eur"],
            "solver_objective_eur": solved.solver["objective_eur"],
            "solver_status": solved.solver,
            "e_cap_mwh": solved.kpis["e_cap_mwh"],
            "power_rating_mw": solved.kpis["power_rating_mw"],
            "unmet_heat_mwh": solved.kpis["unmet_heat_mwh"],
            "verification": checks,
            "derived_config_sha256": config_digest,
        }
        if hourly_output_dir is not None:
            prefix = f"{formulation}_{technology}_factor_{factor:.4f}"
            schedule_path = hourly_output_dir / f"{prefix}.csv"
            config_path_json = hourly_output_dir / f"{prefix}.json"
            solved.schedule.to_csv(schedule_path, index=False)
            config_path_json.write_text(
                json.dumps(dataclasses.asdict(cfg), sort_keys=True, indent=2) + "\n",
                encoding="utf-8",
            )
            item["hourly_csv"] = schedule_path.name
            item["hourly_csv_sha256"] = hashlib.sha256(schedule_path.read_bytes()).hexdigest()
            item["config_json"] = config_path_json.name
            item["config_json_sha256"] = hashlib.sha256(
                config_path_json.read_bytes()
            ).hexdigest()
        results.append(item)
        if technology == "packed_bed":
            verified_packed[formulation] = item
        print(f"{profile} {case}: {item['total_cost_eur']:.3f} EUR", flush=True)
    return {
        "study_design": study_grid(factors),
        "number_distinct_solves": len([r for r in results if "solve_reused_from_factor" not in r]),
        "records": results,
        "analysis": compare_fidelity_rankings(results, profile, factors=factors),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile", choices=("flat", "two_shift", "seasonal"), required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError("Never overwrite previously recorded scientific results")
    result = run_experiment(args.profile)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, allow_nan=False) + "\n")
    print(json.dumps(result["analysis"], indent=2))


if __name__ == "__main__":
    main()
