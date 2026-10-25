"""Independent post-solve checks of archived C3 technology-ranking evidence.

This re-derives comparisons from saved solver results; it does not re-solve the
dispatch MILPs, authenticate upstream costs, or extrapolate to real installations.
"""

from __future__ import annotations

import csv
import io
import math
from collections import defaultdict


def _rows(csv_content: str) -> list[dict[str, str]]:
    reader = csv.DictReader(io.StringIO(csv_content))
    if not reader.fieldnames:
        raise ValueError("Expected a CSV header")
    rows = list(reader)
    if not rows or any(None in row or any(value is None for value in row.values()) for row in rows):
        raise ValueError("Empty, incomplete or malformed CSV")
    return rows


def _number(value: object, label: str) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Non-numeric {label}") from exc
    if not math.isfinite(result):
        raise ValueError(f"Non-finite {label}")
    return result


def _equal(left: float, right: float, label: str, *, abs_tol: float = 1e-5) -> None:
    if not math.isclose(left, right, rel_tol=1e-10, abs_tol=abs_tol):
        raise ValueError(f"Evidence mismatch: {label}: {left} != {right}")


def audit_ranking_evidence(manifest: dict, deltas_csv: str, rankings_csv: str) -> dict:
    """Check every paired solver result, published delta and stated ranking.

    A fixed-output *additive surcharge* margin is calculated for the cheapest
    option versus the runner-up. It is NOT a re-optimised CAPEX sensitivity, a
    technology break-even investment cost or a calibrated uncertainty interval.
    """
    if manifest.get("all_runs_verified") is not True:
        raise ValueError("Archived solver/physics verification was not recorded")
    cases = manifest.get("cases")
    if not isinstance(cases, list) or not cases:
        raise ValueError("Missing archived cases")
    deltas = _rows(deltas_csv)
    rankings = _rows(rankings_csv)
    by_key = {}
    groups: dict[tuple[float, str], list[tuple[str, float, float]]] = defaultdict(list)

    for case in cases:
        technology = case["technology"]
        temperature = _number(case["temperature_c"], "temperature_c")
        profile = case["profile_shape"]
        key = (technology, temperature, profile)
        if key in by_key:
            raise ValueError("Duplicate technology/temperature/profile identity")
        if not isinstance(technology, str) or not technology or not isinstance(profile, str):
            raise ValueError("Invalid case labels")
        legs = []
        for name in ("constant_limit", "soc_dependent"):
            leg = case[name]
            if leg.get("verification_passed") is not True:
                raise ValueError(f"Missing physical verification for {key}/{name}")
            solver = leg["solver"]
            if solver.get("status") != "ok" or solver.get("termination") != "optimal":
                raise ValueError(f"Non-optimal solve for {key}/{name}")
            objective = _number(solver["objective_eur"], "solver objective")
            total = _number(leg["kpis"]["total_cost_eur"], "total cost")
            if total <= 0:
                raise ValueError("Nonpositive total cost")
            _equal(objective, total, "solver objective versus KPI")
            legs.append(total)
        constant, soc = legs
        delta = soc - constant
        derived = (delta, 100.0 * delta / constant)
        declared = case["delta_soc_dependent_minus_constant"]
        _equal(delta, _number(declared["total_cost_eur"], "manifest cost delta"), "manifest delta")
        _equal(
            derived[1],
            _number(declared["total_cost_pct"], "manifest percent delta"),
            "manifest percent delta",
        )
        by_key[key] = (constant, soc, *derived)
        groups[(temperature, profile)].append((technology, constant, soc))

    found = set()
    for row in deltas:
        key = (
            row["technology"],
            _number(row["temperature_c"], "CSV temperature"),
            row["profile_shape"],
        )
        if key not in by_key or key in found:
            raise ValueError("Missing, unexpected or duplicate delta row")
        found.add(key)
        constant, soc, delta, pct = by_key[key]
        for column, expected in (
            ("total_cost_constant_eur", constant),
            ("total_cost_soc_dependent_eur", soc),
            ("delta_total_cost_eur", delta),
            ("delta_total_cost_pct", pct),
        ):
            _equal(_number(row[column], column), expected, f"{key}/{column}")
    if found != set(by_key):
        raise ValueError("Incomplete case-delta table")

    observed_rankings = set()
    output = []
    flips = []
    for row in rankings:
        group = (_number(row["temperature_c"], "ranking temperature"), row["profile_shape"])
        if group not in groups or group in observed_rankings:
            raise ValueError("Duplicate or unregistered ranking group")
        observed_rankings.add(group)
        technologies = groups[group]
        declared = {name.strip() for name in row["technologies_compared"].split(",")}
        actual = {name for name, _, _ in technologies}
        if declared != actual or len(actual) < 2:
            raise ValueError("Ranking excludes or duplicates a technology")
        order_constant = sorted(technologies, key=lambda value: (value[1], value[0]))
        order_soc = sorted(technologies, key=lambda value: (value[2], value[0]))
        winners = (order_constant[0][0], order_soc[0][0])
        flipped = winners[0] != winners[1]
        if winners != (
            row["cheapest_technology_constant"],
            row["cheapest_technology_soc_dependent"],
        ):
            raise ValueError("Published cheapest technology disagrees with archived costs")
        if flipped != (row["ranking_flipped"].strip().lower() == "true"):
            raise ValueError("Published ranking-flip flag disagrees with archived costs")
        flips.append(flipped)
        for formulation, ordered, idx in (
            ("constant_limit", order_constant, 1),
            ("soc_dependent", order_soc, 2),
        ):
            best, runner = ordered[:2]
            margin = runner[idx] - best[idx]
            if margin < 0:
                raise ValueError("Negative ranking margin")
            output.append(
                {
                    "temperature_c": group[0],
                    "profile_shape": group[1],
                    "formulation": formulation,
                    "winner": best[0],
                    "runner_up": runner[0],
                    "winner_total_eur": best[idx],
                    "runner_up_total_eur": runner[idx],
                    "fixed_output_additive_surcharge_margin_eur": margin,
                    "fixed_output_additive_surcharge_margin_pct": 100.0 * margin / best[idx],
                }
            )
    if observed_rankings != set(groups):
        raise ValueError("Missing published ranking groups")
    if any(flips) != manifest.get("any_ranking_flip"):
        raise ValueError("Archived summary flip flag disagrees with raw results")
    return {
        "status": "PASS_ARCHIVED_EVIDENCE_RECONCILIATION",
        "paired_cases_verified": len(by_key),
        "ranking_groups_verified": len(groups),
        "ranking_flips": sum(flips),
        "margins": sorted(
            output, key=lambda row: (row["temperature_c"], row["profile_shape"], row["formulation"])
        ),
        "interpretation": (
            "Fixed solved-output additive surcharge screening ONLY; "
            "no re-optimisation or CAPEX validation."
        ),
    }
