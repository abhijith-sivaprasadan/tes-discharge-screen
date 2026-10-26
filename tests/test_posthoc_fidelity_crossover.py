"""Post-hoc comparison guards; never infer a winner from an unresolved solve."""

from __future__ import annotations

import copy

import pytest

from scripts.run_posthoc_fidelity_crossover import (
    SALT_CAPEX_FACTORS,
    _winner,
    compare_fidelity_rankings,
    study_grid,
)


def synthetic_result():
    rows = []
    for case in study_grid():
        tech = case["technology"]
        fac = case["molten_salt_capex_factor"]
        form = case["formulation"]
        salt_cost = 100 + 100 * fac + (3 if form == "soc_dependent" else 0)
        packed_cost = 140 + (1 if form == "soc_dependent" else 0)
        rows.append(
            {
                **case,
                "status": "OPTIMAL_VERIFIED",
                "total_cost_eur": packed_cost if tech == "packed_bed" else salt_cost,
            }
        )
    return rows


def test_study_is_fixed_posthoc_grid_and_both_formulations():
    cases = study_grid()
    assert len(cases) == 4 * len(SALT_CAPEX_FACTORS)
    assert len({tuple(sorted(c.items())) for c in cases}) == len(cases)
    assert all({c["formulation"] for c in cases if c["molten_salt_capex_factor"] == f}
               == {"constant", "soc_dependent"} for f in SALT_CAPEX_FACTORS)


def test_winner_changes_by_assumption_not_fabricated_between_factors():
    report = compare_fidelity_rankings(synthetic_result(), "two_shift")
    assert report["registered_after_prior_2026_sensitivity_results"] is True
    assert len(report["pairwise_comparisons"]) == len(SALT_CAPEX_FACTORS)
    by_factor = {p["molten_salt_capex_factor"]: p for p in report["pairwise_comparisons"]}
    assert by_factor[0.35]["formulation_ranking_comparison"] == "AGREEMENT"
    assert _winner(0.5) == "indistinguishable_at_1_eur_tolerance"


def test_missing_solver_proof_withholds_tech_choice():
    rows = synthetic_result()
    rows[0]["status"] = "NO_LOADABLE_SOLUTION_NOT_PROVEN_INFEASIBLE"
    rows[0].pop("total_cost_eur")
    report = compare_fidelity_rankings(rows, "seasonal")
    first = report["pairwise_comparisons"][0]
    assert first["formulation_ranking_comparison"] == "UNDETERMINED_MISSING_RESULT"


def test_duplicate_factors_cannot_be_published():
    rows = synthetic_result()
    rows[-1] = copy.deepcopy(rows[0])
    with pytest.raises(ValueError, match="duplicated"):
        compare_fidelity_rankings(rows, "flat")


def test_missing_factor_cannot_be_published():
    with pytest.raises(ValueError, match="Missing"):
        compare_fidelity_rankings(synthetic_result()[:-1], "flat")


def test_nan_monetary_margin_rejected():
    rows = synthetic_result()
    rows[0]["total_cost_eur"] = float("nan")
    with pytest.raises(ValueError, match="Nonfinite"):
        compare_fidelity_rankings(rows, "flat")
