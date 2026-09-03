"""Independent numerical checks on an extracted dispatch schedule, not solver expressions.

Every check here recomputes something from the raw solved values `dispatch.py`
extracted, and compares it to what the solver reported. It never re-evaluates
a Pyomo expression. This is what "verified" means for this project: checked
against the model's own physics and identities, not against measured data.
Carried from the same pattern in PyNEXUS's `optimization/verification.py` and
OpenSteamOpt's `rto.py::summarize`.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from tes_screen.config import CaseConfig
from tes_screen.dispatch import capital_recovery_factor

TOLERANCE = 1e-6


def reconstruct_objective(schedule: pd.DataFrame, config: CaseConfig) -> float:
    """Recompute total annualised cost from the extracted schedule, independent of Pyomo."""
    crf = capital_recovery_factor(
        config.economics.discount_rate, config.economics.storage_lifetime_years
    )
    capex = crf * (
        schedule.attrs["e_cap_mwh"] * config.economics.storage_capex_eur_per_mwh
        + schedule.attrs["power_rating_mw"] * config.economics.storage_capex_eur_per_mw
    )
    operating = float(
        schedule["electricity_cost_eur"].sum()
        + schedule["fuel_cost_eur"].sum()
        + schedule["carbon_cost_eur"].sum()
        + schedule["penalty_cost_eur"].sum()
    )
    return capex + operating


def verify_schedule(
    schedule: pd.DataFrame, config: CaseConfig, solver_objective_eur: float
) -> dict[str, bool]:
    """Run every independent check and return a name -> passed dict. Never raises."""

    checks: dict[str, bool] = {}
    numeric = schedule.select_dtypes(include="number")
    checks["finite_results"] = bool(np.isfinite(numeric.to_numpy()).all())

    nonnegative_columns = [
        "p_ch_mw",
        "p_dis_mw",
        "level_mwh",
        "elec_to_heater_mw",
        "heater_heat_mw",
        "boiler_heat_mw",
        "unmet_heat_mw",
    ]
    checks["nonnegativity"] = bool((schedule[nonnegative_columns] >= -TOLERANCE).all().all())

    e_cap = float(schedule.attrs["e_cap_mwh"])
    checks["storage_level_bounds"] = bool((schedule["level_mwh"] <= e_cap + TOLERANCE).all())

    storage = config.storage
    level = schedule["level_mwh"].to_numpy()
    p_ch = schedule["p_ch_mw"].to_numpy()
    p_dis = schedule["p_dis_mw"].to_numpy()
    previous = np.empty_like(level)
    previous[0] = storage.soc_init_fraction * e_cap
    previous[1:] = level[:-1]
    loss = storage.standing_loss_fraction_per_hour * previous
    recomputed_level = previous - loss + storage.eta_charge * p_ch - p_dis / storage.eta_discharge
    checks["storage_balance_identity"] = bool(
        np.allclose(level, recomputed_level, atol=1e-6, rtol=1e-8)
    )

    checks["storage_terminal_condition"] = bool(
        level[-1] >= storage.soc_final_min_fraction * e_cap - TOLERANCE
    )

    checks["heat_balance_closure"] = bool(
        (schedule["heat_balance_residual_mw"].abs() <= TOLERANCE).all()
    )

    reconstructed = reconstruct_objective(schedule, config)
    checks["objective_reconstruction"] = bool(
        np.isclose(reconstructed, solver_objective_eur, rtol=1e-6, atol=1e-3)
    )

    checks["unmet_heat_negligible"] = bool(schedule["unmet_heat_mw"].sum() <= TOLERANCE)

    return checks


def assert_verified(
    schedule: pd.DataFrame, config: CaseConfig, solver_objective_eur: float
) -> dict[str, bool]:
    """Run every check; raise ValueError naming which failed rather than returning silently."""
    checks = verify_schedule(schedule, config, solver_objective_eur)
    failed = [name for name, passed in checks.items() if not passed]
    if failed:
        raise ValueError(f"Verification failed: {failed}")
    return checks
