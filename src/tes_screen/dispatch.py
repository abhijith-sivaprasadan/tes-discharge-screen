"""Annual quasi-steady dispatch: the Phase A baseline model.

One generic storage block (level, charge, discharge, standing loss, terminal
condition) serves a process heat load from an electric heater and a fossil
backup boiler, sized alongside the store by the solver. The storage block's
discharge limit is **constant** here, by construction: this is the baseline
whose bias the project exists to measure. The state-of-charge-dependent
correction is Phase C's model, not this one; `build_model` refuses to run on
a config asking for it, rather than silently ignoring the request.

Pattern carried from PyNEXUS's `optimization/dispatch.py` (storage block with
terminal condition, sizing as decision variables, HiGHS via Pyomo) and from
OpenSteamOpt's `src/opensteamopt/rto.py` (profile validation before model
build, independent schedule extraction, solver status carried through).
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd
import pyomo.environ as pyo

from tes_screen.config import CaseConfig
from tes_screen.profiles import ELECTRICITY_PRICE_COLUMNS, PROCESS_LOAD_COLUMNS, validate_profile

# A numerical safety valve, not a real energy price: it exists so an
# infeasible-looking case (backup boiler undersized for the load) reports a
# large but finite unmet-heat cost instead of the solver failing outright,
# the same soft-constraint pattern OpenSteamOpt's rto.py uses for unmet
# steam/power. A well-sized case should always drive this variable to zero;
# tests check that it does.
UNMET_HEAT_PENALTY_EUR_PER_MWH = 1_000_000.0


@dataclass(frozen=True)
class DispatchResult:
    schedule: pd.DataFrame
    kpis: dict[str, Any]
    solver: dict[str, Any]


def capital_recovery_factor(discount_rate: float, lifetime_years: float) -> float:
    """Annualises a capital cost over ``lifetime_years`` at ``discount_rate``."""
    r = discount_rate
    n = lifetime_years
    return r * (1 + r) ** n / ((1 + r) ** n - 1)


def build_model(
    config: CaseConfig, process_load: pd.DataFrame, electricity_price: pd.DataFrame
) -> pyo.ConcreteModel:
    """Build but do not solve the Phase A annual LP."""

    if config.storage.discharge_limit_mode != "constant":
        raise ValueError(
            "dispatch.build_model only implements storage.discharge_limit_mode == "
            "'constant' (Phase A's baseline). 'soc_dependent' is Phase C's corrected "
            "model and is not implemented here."
        )

    validate_profile(process_load, PROCESS_LOAD_COLUMNS)
    validate_profile(
        electricity_price,
        ELECTRICITY_PRICE_COLUMNS,
        allow_negative=frozenset({"price_eur_per_mwh"}),
    )
    horizon = config.optimization.horizon_hours
    if len(process_load) != horizon or len(electricity_price) != horizon:
        raise ValueError(
            f"process_load ({len(process_load)}h) and electricity_price "
            f"({len(electricity_price)}h) must both match optimization.horizon_hours "
            f"({horizon}h)"
        )

    storage = config.storage
    supply = config.supply
    economics = config.economics

    load = process_load.set_index("hour")["heat_demand_mw"].to_dict()
    price = electricity_price.set_index("hour")["price_eur_per_mwh"].to_dict()
    peak = max(load.values())

    model = pyo.ConcreteModel(name=f"tes-screen-{config.case_name}")
    model.T = pyo.RangeSet(0, horizon - 1)

    # Sizing: a config value of null means "let the solver choose"; a given
    # value means "fixed, not a decision variable". Only both-null or
    # both-given power sizing is supported; a mix is rejected rather than
    # guessing which side the modeller meant to fix.
    if storage.energy_capacity_mwh is None:
        # Upper bound is a solver bound for numerical stability (up to ten
        # days of storage at peak load), not a physical or economic
        # assumption about how much storage makes sense.
        model.E_cap = pyo.Var(domain=pyo.NonNegativeReals, bounds=(0, peak * 24 * 10))
        e_cap: Any = model.E_cap
    else:
        e_cap = storage.energy_capacity_mwh

    charge_given = storage.charge_power_max_mw is not None
    discharge_given = storage.discharge_power_max_mw is not None
    if charge_given != discharge_given:
        raise ValueError(
            "storage.charge_power_max_mw and storage.discharge_power_max_mw must both "
            "be given or both be null in Phase A; mixed sizing is not supported."
        )
    if charge_given:
        p_ch_max: Any = storage.charge_power_max_mw
        p_dis_max: Any = storage.discharge_power_max_mw
        power_rating: Any = max(storage.charge_power_max_mw, storage.discharge_power_max_mw)
    else:
        model.P_rated = pyo.Var(domain=pyo.NonNegativeReals, bounds=(0, peak * 5))
        p_ch_max = model.P_rated
        p_dis_max = model.P_rated
        power_rating = model.P_rated

    model.p_ch = pyo.Var(model.T, domain=pyo.NonNegativeReals)
    model.p_dis = pyo.Var(model.T, domain=pyo.NonNegativeReals)
    model.level = pyo.Var(model.T, domain=pyo.NonNegativeReals)
    model.elec_to_heater = pyo.Var(
        model.T, domain=pyo.NonNegativeReals, bounds=(0, supply.electric_heater.capacity_mw)
    )
    model.boiler_heat = pyo.Var(
        model.T, domain=pyo.NonNegativeReals, bounds=(0, supply.backup_boiler.capacity_mw)
    )
    model.unmet_heat = pyo.Var(model.T, domain=pyo.NonNegativeReals)

    def charge_limit(m: pyo.ConcreteModel, t: int) -> Any:
        return m.p_ch[t] <= p_ch_max

    model.c_charge_limit = pyo.Constraint(model.T, rule=charge_limit)

    def discharge_limit(m: pyo.ConcreteModel, t: int) -> Any:
        # This constant bound is the assumption under test: A5/README.
        return m.p_dis[t] <= p_dis_max

    model.c_discharge_limit = pyo.Constraint(model.T, rule=discharge_limit)

    def level_cap(m: pyo.ConcreteModel, t: int) -> Any:
        return m.level[t] <= e_cap

    model.c_level_cap = pyo.Constraint(model.T, rule=level_cap)

    def storage_balance(m: pyo.ConcreteModel, t: int) -> Any:
        previous = storage.soc_init_fraction * e_cap if t == 0 else m.level[t - 1]
        loss = storage.standing_loss_fraction_per_hour * previous
        return m.level[t] == (
            previous - loss + storage.eta_charge * m.p_ch[t] - m.p_dis[t] / storage.eta_discharge
        )

    model.c_storage_balance = pyo.Constraint(model.T, rule=storage_balance)

    def storage_terminal(m: pyo.ConcreteModel) -> Any:
        # Without this the optimiser drains the store on the final timestep:
        # free energy with no penalty for leaving it depleted. Carried from
        # PyNEXUS's identical terminal condition.
        return m.level[horizon - 1] >= storage.soc_final_min_fraction * e_cap

    model.c_storage_terminal = pyo.Constraint(rule=storage_terminal)

    def heat_balance(m: pyo.ConcreteModel, t: int) -> Any:
        heater_heat = supply.electric_heater.efficiency * m.elec_to_heater[t]
        return heater_heat + m.boiler_heat[t] + m.p_dis[t] + m.unmet_heat[t] == load[t] + m.p_ch[t]

    model.c_heat_balance = pyo.Constraint(model.T, rule=heat_balance)

    def objective(m: pyo.ConcreteModel) -> Any:
        crf = capital_recovery_factor(economics.discount_rate, economics.storage_lifetime_years)
        capex = crf * (
            e_cap * economics.storage_capex_eur_per_mwh
            + power_rating * economics.storage_capex_eur_per_mw
        )
        operating = sum(
            price[t] * m.elec_to_heater[t]
            + supply.backup_boiler.fuel_cost_eur_per_mwh * m.boiler_heat[t]
            + economics.carbon_price_eur_per_tco2
            * (supply.backup_boiler.emission_factor_kg_co2_per_mwh / 1000.0)
            * m.boiler_heat[t]
            + UNMET_HEAT_PENALTY_EUR_PER_MWH * m.unmet_heat[t]
            for t in m.T
        )
        return capex + operating

    model.total_cost = pyo.Objective(rule=objective, sense=pyo.minimize)

    model._config = config
    model._load = load
    model._price = price
    model._e_cap_is_var = storage.energy_capacity_mwh is None
    model._power_is_var = not charge_given
    return model


def _value(variable: Any) -> float:
    value = pyo.value(variable)
    if value is None or not np.isfinite(value):
        raise ValueError("Solver returned an absent/non-finite value")
    return float(value)


def extract_schedule(model: pyo.ConcreteModel) -> pd.DataFrame:
    """Extract a solved model into an hourly DataFrame with independently recomputed costs."""

    config: CaseConfig = model._config
    supply = config.supply
    economics = config.economics
    crf = capital_recovery_factor(economics.discount_rate, economics.storage_lifetime_years)

    rows: list[dict[str, float | int]] = []
    for t in model.T:
        p_ch = _value(model.p_ch[t])
        p_dis = _value(model.p_dis[t])
        level = _value(model.level[t])
        elec_to_heater = _value(model.elec_to_heater[t])
        boiler_heat = _value(model.boiler_heat[t])
        unmet_heat = _value(model.unmet_heat[t])
        heater_heat = supply.electric_heater.efficiency * elec_to_heater

        electricity_cost = model._price[t] * elec_to_heater
        fuel_cost = supply.backup_boiler.fuel_cost_eur_per_mwh * boiler_heat
        emissions_tco2 = boiler_heat * supply.backup_boiler.emission_factor_kg_co2_per_mwh / 1000.0
        carbon_cost = economics.carbon_price_eur_per_tco2 * emissions_tco2
        penalty_cost = 1_000_000.0 * unmet_heat

        rows.append(
            {
                "hour": int(t),
                "heat_demand_mw": model._load[t],
                "price_eur_per_mwh": model._price[t],
                "p_ch_mw": p_ch,
                "p_dis_mw": p_dis,
                "level_mwh": level,
                "elec_to_heater_mw": elec_to_heater,
                "heater_heat_mw": heater_heat,
                "boiler_heat_mw": boiler_heat,
                "unmet_heat_mw": unmet_heat,
                "electricity_cost_eur": electricity_cost,
                "fuel_cost_eur": fuel_cost,
                "carbon_cost_eur": carbon_cost,
                "penalty_cost_eur": penalty_cost,
                "emissions_tco2": emissions_tco2,
                "heat_balance_residual_mw": (
                    heater_heat + boiler_heat + p_dis + unmet_heat - model._load[t] - p_ch
                ),
            }
        )
    schedule = pd.DataFrame(rows)
    schedule.attrs["e_cap_mwh"] = (
        _value(model.E_cap) if model._e_cap_is_var else config.storage.energy_capacity_mwh
    )
    schedule.attrs["power_rating_mw"] = (
        _value(model.P_rated)
        if model._power_is_var
        else max(config.storage.charge_power_max_mw, config.storage.discharge_power_max_mw)
    )
    schedule.attrs["capital_recovery_factor"] = crf
    return schedule


def solve_dispatch(
    config: CaseConfig, process_load: pd.DataFrame, electricity_price: pd.DataFrame
) -> DispatchResult:
    """Solve the Phase A LP with HiGHS and return a schedule with recorded solver status."""

    model = build_model(config, process_load, electricity_price)
    solver = pyo.SolverFactory("appsi_highs")
    solver.options["time_limit"] = config.optimization.time_limit_seconds
    solver.options["mip_rel_gap"] = config.optimization.mip_gap
    start = time.perf_counter()
    result = solver.solve(model)
    wall_time_seconds = time.perf_counter() - start

    termination = str(result.solver.termination_condition).lower()
    status = str(result.solver.status).lower()
    if termination not in {"optimal", "maxtimelimit"}:
        raise RuntimeError(f"Dispatch solve failed with status={status} termination={termination}")

    objective_value = _value(model.total_cost)
    schedule = extract_schedule(model)
    kpis = {
        "total_cost_eur": objective_value,
        "e_cap_mwh": schedule.attrs["e_cap_mwh"],
        "power_rating_mw": schedule.attrs["power_rating_mw"],
        "electricity_cost_eur": float(schedule.electricity_cost_eur.sum()),
        "fuel_cost_eur": float(schedule.fuel_cost_eur.sum()),
        "carbon_cost_eur": float(schedule.carbon_cost_eur.sum()),
        "emissions_tco2": float(schedule.emissions_tco2.sum()),
        "unmet_heat_mwh": float(schedule.unmet_heat_mw.sum()),
        "max_heat_balance_residual_mw": float(schedule.heat_balance_residual_mw.abs().max()),
    }
    solver_info = {
        "name": "HiGHS",
        "status": status,
        "termination": termination,
        "objective_eur": objective_value,
        "wall_time_seconds": wall_time_seconds,
        "time_limit_hit": termination == "maxtimelimit",
    }
    return DispatchResult(schedule=schedule, kpis=kpis, solver=solver_info)
