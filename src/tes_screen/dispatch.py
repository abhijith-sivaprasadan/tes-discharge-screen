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
from tes_screen.discharge_curve import PiecewiseDischargeCurve
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
    config: CaseConfig,
    process_load: pd.DataFrame,
    electricity_price: pd.DataFrame,
    discharge_curve: PiecewiseDischargeCurve | None = None,
) -> pyo.ConcreteModel:
    """Build but do not solve the annual LP: constant limit (Phase A) or SOC-dependent (Phase C).

    `discharge_curve` is required when `storage.discharge_limit_mode ==
    "soc_dependent"` (Phase C's corrected model: `discharge_curve.py`'s
    piecewise-linear construction, C1) and rejected otherwise, so a config
    and a curve can never silently drift apart. In soc_dependent mode,
    `storage.discharge_power_max_mw` must be null: the curve replaces it
    entirely (C1: "replaces p_dis[t] <= P_dis_max"), so a value there would
    be silently ignored rather than honoured, which this rejects instead.
    """

    soc_dependent = config.storage.discharge_limit_mode == "soc_dependent"
    if soc_dependent and discharge_curve is None:
        raise ValueError(
            "storage.discharge_limit_mode == 'soc_dependent' requires a discharge_curve "
            "(discharge_curve.fit_piecewise_discharge_curve)."
        )
    if not soc_dependent and discharge_curve is not None:
        raise ValueError(
            "discharge_curve was given but storage.discharge_limit_mode == 'constant'; "
            "it would be silently ignored. Set discharge_limit_mode to 'soc_dependent'."
        )
    if soc_dependent and config.storage.discharge_power_max_mw is not None:
        raise ValueError(
            "storage.discharge_power_max_mw must be null when discharge_limit_mode == "
            "'soc_dependent': the piecewise discharge_curve replaces it, so a given value "
            "would be silently ignored."
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

    model = pyo.ConcreteModel(name=f"tes-discharge-screen-{config.case_name}")
    model.T = pyo.RangeSet(0, horizon - 1)

    # Sizing: a config value of null means "let the solver choose"; a given
    # value means "fixed, not a decision variable". Only both-null or
    # both-given power sizing is supported outside duration-matched mode; a
    # mix is rejected rather than guessing which side the modeller meant to
    # fix.
    if storage.energy_capacity_mwh is None:
        # Upper bound is a solver bound for numerical stability (up to ten
        # days of storage at peak load), not a physical or economic
        # assumption about how much storage makes sense.
        model.E_cap = pyo.Var(domain=pyo.NonNegativeReals, bounds=(0, peak * 24 * 10))
        e_cap: Any = model.E_cap
        e_cap_bound_mwh = peak * 24 * 10
    else:
        e_cap = storage.energy_capacity_mwh
        e_cap_bound_mwh = storage.energy_capacity_mwh

    duration_matched = storage.design_duration_hours is not None

    # charge_power_bound_mw/discharge_power_bound_mw shadow p_ch_max/p_dis_max
    # with a genuine numeric constant (never a Pyomo Var or an expression
    # containing one) even when the corresponding power is itself a sizing
    # decision variable: P0.5's MILP cycling-prevention constraints need a
    # literal big-M, and `p_ch_max * z[t]` would be bilinear (Var times Var)
    # whenever p_ch_max depends on E_cap or P_rated, which HiGHS's MILP
    # solver cannot handle. Built from the same numeric bounds already
    # declared for those Vars (e_cap_bound_mwh, peak*5), not an arbitrary
    # big number, per the roadmap's own "use defensible capacity bounds"
    # instruction.
    if duration_matched:
        # C1/C2's matched-sizing fix: tie power to energy at one externally
        # chosen design duration tau, identically in both formulations, so a
        # constant-limit run and a SOC-dependent run compared as a pair have
        # exactly the same sizing degrees of freedom. Without this, each
        # formulation being free to pick its own independent power/energy
        # ratio confounds "the discharge-limit shape changed" with "the two
        # runs were also allowed to build different-duration stores" -- see
        # docs/DATA.md's matched-sizing note for the confound this replaced.
        tau = storage.design_duration_hours
        p_ch_max: Any = e_cap / tau
        charge_power_bound_mw = e_cap_bound_mwh / tau
        if soc_dependent:
            # The discharge curve must itself have been fit at the mass flow
            # that ties its own reference power/energy ratio to this same
            # tau (discharge_curve.mass_flow_for_target_duration); a
            # mismatched curve would silently break the matched comparison.
            if abs(discharge_curve.k_mw_per_mwh - 1.0 / tau) > 1e-6 * (1.0 / tau):
                raise ValueError(
                    "discharge_curve's own power/energy ratio "
                    f"(k={discharge_curve.k_mw_per_mwh:.6g} MW/MWh, implied tau="
                    f"{1 / discharge_curve.k_mw_per_mwh:.4g} h) does not match "
                    f"storage.design_duration_hours ({tau} h); refit the curve at "
                    "discharge_curve.mass_flow_for_target_duration(tau)."
                )
            p_dis_max: Any = None
            discharge_power_bound_mw = discharge_curve.k_mw_per_mwh * e_cap_bound_mwh
        else:
            p_dis_max = e_cap / tau
            discharge_power_bound_mw = e_cap_bound_mwh / tau
        power_rating: Any = p_ch_max
    elif soc_dependent:
        # Not duration-matched: the discharge side is no longer an
        # independent sizing choice regardless (the piecewise curve
        # determines allowed discharge power from (level, E_cap) alone,
        # C1). When charge power is also unfixed, tie it to the same
        # reference power/energy ratio (k) the discharge curve uses, rather
        # than giving it an independent free variable: see the
        # duration_matched branch's docstring for why an extra, unconstrained
        # sizing degree of freedom would confound the comparison. Prefer
        # duration_matched mode for any paired comparison; this path exists
        # for standalone SOC-dependent runs. A fixed charge_power_max_mw is
        # honoured as given.
        if storage.charge_power_max_mw is None:
            p_ch_max = discharge_curve.k_mw_per_mwh * e_cap
            charge_power_bound_mw = discharge_curve.k_mw_per_mwh * e_cap_bound_mwh
        else:
            p_ch_max = storage.charge_power_max_mw
            charge_power_bound_mw = storage.charge_power_max_mw
        p_dis_max = None
        discharge_power_bound_mw = discharge_curve.k_mw_per_mwh * e_cap_bound_mwh
        power_rating = p_ch_max
    else:
        charge_given = storage.charge_power_max_mw is not None
        discharge_given = storage.discharge_power_max_mw is not None
        if charge_given != discharge_given:
            raise ValueError(
                "storage.charge_power_max_mw and storage.discharge_power_max_mw must both "
                "be given or both be null in Phase A; mixed sizing is not supported."
            )
        if charge_given:
            p_ch_max = storage.charge_power_max_mw
            p_dis_max = storage.discharge_power_max_mw
            charge_power_bound_mw = storage.charge_power_max_mw
            discharge_power_bound_mw = storage.discharge_power_max_mw
            power_rating = max(storage.charge_power_max_mw, storage.discharge_power_max_mw)
        else:
            model.P_rated = pyo.Var(domain=pyo.NonNegativeReals, bounds=(0, peak * 5))
            p_ch_max = model.P_rated
            p_dis_max = model.P_rated
            charge_power_bound_mw = peak * 5
            discharge_power_bound_mw = peak * 5
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

    def level_start(m: pyo.ConcreteModel, t: int) -> Any:
        # Pre-dispatch state: what was actually available before this hour's
        # own charge/discharge acted on it, not `m.level[t]` (the post-
        # dispatch state `storage_balance` below defines in terms of this
        # same hour's p_dis[t]/p_ch[t]). Shared by storage_balance's own
        # "previous" term and, when soc_dependent's capability_reference
        # asks for it, by the discharge-capability constraint (P0.4).
        return storage.soc_init_fraction * e_cap if t == 0 else m.level[t - 1]

    if soc_dependent:
        # C1's piecewise-linear replacement for the constant P_dis_max bound:
        # p_dis[t] <= a_i*level_ref[t] + b_i*E_cap, for every segment i,
        # simultaneously. Exact for a concave curve (this one is, checked
        # empirically in discharge_curve.py's own tests, not assumed).
        model.Segments = pyo.RangeSet(0, len(discharge_curve.a_coefficients) - 1)
        # P0.4: which state the capability bound reads is an explicit,
        # required modelling choice (config.py's validation), never a
        # hidden default. "start_of_hour" (level_start[t], the roadmap's own
        # first choice for this screening model) reflects what was actually
        # on hand before this hour's own discharge drew it down;
        # "end_of_hour" uses the post-dispatch m.level[t] instead -- the
        # project's original, more conservative choice, kept as an explicit
        # alternative rather than replaced outright (see
        # test_dispatch.py's P0.4 tests for the quantified difference).
        capability_reference = storage.discharge_capability_reference
        if capability_reference not in {"start_of_hour", "end_of_hour"}:
            # config.py's own validation already rejects this when a config
            # is loaded via load_config, but build_model is public API too
            # (tests and scripts call it directly on hand-built configs) and
            # must not silently fall back to a default state reference for a
            # missing/invalid one -- exactly the hidden-default P0.4 exists
            # to eliminate.
            raise ValueError(
                "storage.discharge_capability_reference must be 'start_of_hour' or "
                "'end_of_hour' when discharge_limit_mode == 'soc_dependent', got "
                f"{capability_reference!r}."
            )

        def discharge_limit_piecewise(m: pyo.ConcreteModel, t: int, seg: int) -> Any:
            a = discharge_curve.a_coefficients[seg]
            b = discharge_curve.b_coefficients[seg]
            reference_level = (
                level_start(m, t) if capability_reference == "start_of_hour" else m.level[t]
            )
            return m.p_dis[t] <= a * reference_level + b * e_cap

        model.c_discharge_limit = pyo.Constraint(
            model.T, model.Segments, rule=discharge_limit_piecewise
        )
    else:

        def discharge_limit(m: pyo.ConcreteModel, t: int) -> Any:
            # This constant bound is the assumption under test: A5/README.
            return m.p_dis[t] <= p_dis_max

        model.c_discharge_limit = pyo.Constraint(model.T, rule=discharge_limit)

    cycling_prevention_mode = storage.cycling_prevention_mode
    if cycling_prevention_mode not in {"none", "milp_binary"}:
        # config.py's own validation already rejects this when a config is
        # loaded via load_config; build_model re-checks defensively for the
        # same reason P0.4's capability_reference check does (public API,
        # called directly on hand-built configs in tests/scripts).
        raise ValueError(
            "storage.cycling_prevention_mode must be 'none' or 'milp_binary', got "
            f"{cycling_prevention_mode!r}."
        )
    if cycling_prevention_mode == "milp_binary":
        # P0.5: independent nonnegative p_ch[t]/p_dis[t] let a pure LP
        # exploit simultaneous charge and discharge in the same hour once
        # electricity prices go negative -- draw heater electricity purely
        # to collect the negative-price payment, discharge the store to
        # make room for it in the same hour's heat balance, then charge the
        # store right back up beyond what c_charge_limit alone would allow.
        # Mathematically feasible, physically meaningless, and it burns real
        # round-trip losses (eta_charge, eta_discharge) for no net storage
        # benefit. z[t] forces at most one direction active per hour.
        # charge_power_bound_mw/discharge_power_bound_mw (defined above) are
        # genuine numeric constants derived from the same bounds already
        # declared for E_cap/P_rated, not an arbitrary big-M, per the
        # roadmap's own "use defensible capacity bounds" instruction --
        # required precisely because p_ch_max/p_dis_max themselves are often
        # Pyomo expressions in a sizing Var here, and `p_ch_max * z[t]` would
        # be a non-linear (Var-times-Var) term MILP cannot solve.
        model.z_charging = pyo.Var(model.T, domain=pyo.Binary)

        def charge_only_while_charging(m: pyo.ConcreteModel, t: int) -> Any:
            return m.p_ch[t] <= charge_power_bound_mw * m.z_charging[t]

        model.c_charge_only_while_charging = pyo.Constraint(
            model.T, rule=charge_only_while_charging
        )

        def discharge_only_while_not_charging(m: pyo.ConcreteModel, t: int) -> Any:
            return m.p_dis[t] <= discharge_power_bound_mw * (1 - m.z_charging[t])

        model.c_discharge_only_while_not_charging = pyo.Constraint(
            model.T, rule=discharge_only_while_not_charging
        )

    def level_cap(m: pyo.ConcreteModel, t: int) -> Any:
        return m.level[t] <= e_cap

    model.c_level_cap = pyo.Constraint(model.T, rule=level_cap)

    def storage_balance(m: pyo.ConcreteModel, t: int) -> Any:
        previous = level_start(m, t)
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
    # True only when model.P_rated actually exists as its own Var: the
    # constant-limit model's "both charge and discharge null" case, and only
    # outside duration-matched mode (there, power is always tied to e_cap/tau,
    # never a free variable). In soc_dependent mode there is no such variable
    # even when charge power is unfixed; power_rating is k*e_cap instead (see
    # extract_schedule).
    model._power_is_var = (
        (not duration_matched) and (not soc_dependent) and storage.charge_power_max_mw is None
    )
    model._soc_dependent = soc_dependent
    model._duration_matched = duration_matched
    model._design_duration_hours = storage.design_duration_hours
    model._discharge_curve_k = discharge_curve.k_mw_per_mwh if soc_dependent else None
    model._cycling_prevention_mode = cycling_prevention_mode
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
    e_cap_mwh = _value(model.E_cap) if model._e_cap_is_var else config.storage.energy_capacity_mwh
    schedule.attrs["e_cap_mwh"] = e_cap_mwh

    if model._duration_matched:
        # C2's matched-sizing tie: power was never a free variable here in
        # either formulation, so both report the same externally chosen
        # duration back out, not a fitted/derived one (build_model).
        power_rating_mw = e_cap_mwh / model._design_duration_hours
    elif model._power_is_var:
        power_rating_mw = _value(model.P_rated)
    elif model._soc_dependent:
        # soc_dependent mode: charge power is either fixed, or tied to the
        # same reference k = P_rated/E_cap ratio the discharge curve uses
        # (build_model); discharge_power_max_mw is required to be null (C1).
        power_rating_mw = (
            config.storage.charge_power_max_mw
            if config.storage.charge_power_max_mw is not None
            else model._discharge_curve_k * e_cap_mwh
        )
    else:
        power_rating_mw = max(
            config.storage.charge_power_max_mw, config.storage.discharge_power_max_mw
        )
    schedule.attrs["power_rating_mw"] = power_rating_mw
    schedule.attrs["capital_recovery_factor"] = crf
    return schedule


def solve_dispatch(
    config: CaseConfig,
    process_load: pd.DataFrame,
    electricity_price: pd.DataFrame,
    discharge_curve: PiecewiseDischargeCurve | None = None,
) -> DispatchResult:
    """Solve the annual LP with HiGHS and return a schedule with recorded solver status.

    `discharge_curve` is required for `storage.discharge_limit_mode ==
    "soc_dependent"`; see `build_model`.
    """

    model = build_model(config, process_load, electricity_price, discharge_curve)
    solver = pyo.SolverFactory("appsi_highs")
    solver.options["time_limit"] = config.optimization.time_limit_seconds
    solver.options["mip_rel_gap"] = config.optimization.mip_gap
    # Every decision variable build_model creates is continuous (no integers
    # anywhere in this model): the interior-point method is a better-suited
    # default than HiGHS's own simplex choice for a large, sparse, purely
    # continuous LP, and resolves a real numerical difficulty observed with
    # P0.4's start_of_hour capability reference in some duration-matched
    # configurations (a piecewise segment's `a` coefficient near zero, close
    # to full charge, made simplex stall at "unknown" with no incumbent even
    # well inside the configured time limit; IPM solves the identical model
    # to the identical objective without issue). Confirmed not to change any
    # already-passing case's objective value, only how it gets there.
    solver.options["solver"] = "ipm"
    start = time.perf_counter()
    try:
        result = solver.solve(model)
    except RuntimeError as exc:
        # Pyomo's appsi/HiGHS interface raises a raw RuntimeError instead of
        # a normal termination condition when no feasible solution could be
        # loaded at all (not even a "maxtimelimit" incumbent); catch and
        # reraise in this function's own consistent failure format rather
        # than letting an internal Pyomo message leak through unexplained.
        raise RuntimeError(f"Dispatch solve failed to find a loadable solution: {exc}") from exc
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
