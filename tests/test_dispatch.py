from __future__ import annotations

import dataclasses
import functools

import numpy as np
import pandas as pd
import pytest

from tes_screen.config import load_config
from tes_screen.discharge_curve import (
    PiecewiseDischargeCurve,
    fit_piecewise_discharge_curve,
    mass_flow_for_target_duration,
)
from tes_screen.dispatch import build_model, capital_recovery_factor, solve_dispatch
from tes_screen.packed_bed_dynamics import default_packed_bed_config, simulate_discharge
from tes_screen.synthetic_profiles import build_load_profile, synthetic_daily_price_profile
from tes_screen.verification import reconstruct_objective, verify_schedule

CONFIG_PATH = "configs/packed_bed_300c_flat.yaml"
SHORT_HORIZON = 72


def _short_case(**economics_overrides: float):
    config = load_config(CONFIG_PATH)
    config = dataclasses.replace(
        config, optimization=dataclasses.replace(config.optimization, horizon_hours=SHORT_HORIZON)
    )
    if economics_overrides:
        config = dataclasses.replace(
            config, economics=dataclasses.replace(config.economics, **economics_overrides)
        )
    return config


def _solve_short(**economics_overrides: float):
    config = _short_case(**economics_overrides)
    load = build_load_profile(
        config.process.profile_shape, config.process.annual_peak_load_mw, SHORT_HORIZON
    )
    price = synthetic_daily_price_profile(SHORT_HORIZON)
    return config, load, price, solve_dispatch(config, load, price)


@functools.lru_cache(maxsize=1)
def _reference_discharge_curve() -> PiecewiseDischargeCurve:
    bed_config = default_packed_bed_config()
    result = simulate_discharge(
        bed_config,
        mass_flow_kg_per_s=3.0,
        initial_bed_temperature_c=400.0,
        inlet_temperature_c=320.0,
        duration_s=30 * 3600,
        n_steps=1500,
    )
    return fit_piecewise_discharge_curve(
        result, process_temperature_c=300.0, delta_t_min_hot_side_c=0.0, n_segments=5
    )


def _duration_matched_curve(design_duration_hours: float) -> PiecewiseDischargeCurve:
    # Refits the reference bed at the mass flow whose own reference
    # power/energy ratio equals 1/design_duration_hours, so the curve ties
    # exactly to the same tau the config's design_duration_hours requests
    # (C2's matched-sizing fix; see discharge_curve.mass_flow_for_target_duration).
    bed_config = default_packed_bed_config()
    mass_flow = mass_flow_for_target_duration(
        bed_config,
        target_duration_hours=design_duration_hours,
        initial_bed_temperature_c=400.0,
        inlet_temperature_c=320.0,
        process_temperature_c=300.0,
        delta_t_min_hot_side_c=0.0,
    )
    result = simulate_discharge(
        bed_config,
        mass_flow_kg_per_s=mass_flow,
        initial_bed_temperature_c=400.0,
        inlet_temperature_c=320.0,
        duration_s=design_duration_hours * 2 * 3600,
        n_steps=1500,
    )
    return fit_piecewise_discharge_curve(
        result, process_temperature_c=300.0, delta_t_min_hot_side_c=0.0, n_segments=5
    )


def _short_case_duration_matched(design_duration_hours: float, **economics_overrides: float):
    config = _short_case(**economics_overrides)
    return dataclasses.replace(
        config,
        storage=dataclasses.replace(
            config.storage,
            charge_power_max_mw=None,
            discharge_power_max_mw=None,
            design_duration_hours=design_duration_hours,
        ),
    )


def _solve_short_soc_dependent(
    discharge_capability_reference: str = "start_of_hour", **economics_overrides: float
):
    config = _short_case(**economics_overrides)
    config = dataclasses.replace(
        config,
        storage=dataclasses.replace(
            config.storage,
            discharge_limit_mode="soc_dependent",
            discharge_power_max_mw=None,
            discharge_capability_reference=discharge_capability_reference,
        ),
    )
    load = build_load_profile(
        config.process.profile_shape, config.process.annual_peak_load_mw, SHORT_HORIZON
    )
    price = synthetic_daily_price_profile(SHORT_HORIZON)
    curve = _reference_discharge_curve()
    return config, load, price, solve_dispatch(config, load, price, discharge_curve=curve)


def test_solve_reaches_optimal_and_verifies() -> None:
    config, _load, _price, result = _solve_short()
    assert result.solver["termination"] == "optimal"
    checks = verify_schedule(result.schedule, config, result.solver["objective_eur"])
    assert all(checks.values()), checks


def test_energy_balance_closes_every_hour() -> None:
    _config, _load, _price, result = _solve_short()
    residual = result.schedule["heat_balance_residual_mw"].abs()
    assert (residual < 1e-6).all()


def test_storage_level_stays_within_capacity() -> None:
    _config, _load, _price, result = _solve_short()
    e_cap = result.schedule.attrs["e_cap_mwh"]
    assert (result.schedule["level_mwh"] <= e_cap + 1e-6).all()
    assert (result.schedule["level_mwh"] >= -1e-6).all()


def test_terminal_condition_binds_when_forced_high() -> None:
    # Force soc_final_min_fraction high enough, with soc_init below it, that the
    # terminal constraint must actually bind rather than being slack by
    # construction; otherwise this test would pass even with a broken
    # constraint.
    config = _short_case()
    config = dataclasses.replace(
        config,
        storage=dataclasses.replace(
            config.storage, soc_init_fraction=0.1, soc_final_min_fraction=0.95
        ),
    )
    load = build_load_profile(
        config.process.profile_shape, config.process.annual_peak_load_mw, SHORT_HORIZON
    )
    price = synthetic_daily_price_profile(SHORT_HORIZON)
    result = solve_dispatch(config, load, price)
    e_cap = result.schedule.attrs["e_cap_mwh"]
    final_level = result.schedule["level_mwh"].iloc[-1]
    assert final_level >= 0.95 * e_cap - 1e-6


def test_objective_reconstruction_matches_solver_to_tolerance() -> None:
    config, _load, _price, result = _solve_short()
    reconstructed = reconstruct_objective(result.schedule, config)
    assert np.isclose(reconstructed, result.solver["objective_eur"], rtol=1e-6, atol=1e-3)


def test_unmet_heat_is_zero_when_boiler_is_sized_above_peak() -> None:
    _config, _load, _price, result = _solve_short()
    assert result.schedule["unmet_heat_mw"].sum() < 1e-6


def test_soc_dependent_mode_without_a_curve_is_rejected() -> None:
    config = _short_case()
    config = dataclasses.replace(
        config, storage=dataclasses.replace(config.storage, discharge_limit_mode="soc_dependent")
    )
    load = build_load_profile(
        config.process.profile_shape, config.process.annual_peak_load_mw, SHORT_HORIZON
    )
    price = synthetic_daily_price_profile(SHORT_HORIZON)
    with pytest.raises(ValueError, match="soc_dependent"):
        solve_dispatch(config, load, price)


def test_constant_mode_with_a_curve_is_rejected() -> None:
    # A curve given for a constant-limit config would be silently ignored;
    # reject instead of accepting it and pretending it did nothing.
    config, load, price, _ = _solve_short()
    curve = _reference_discharge_curve()
    with pytest.raises(ValueError, match="discharge_limit_mode == 'constant'"):
        solve_dispatch(config, load, price, discharge_curve=curve)


def test_soc_dependent_mode_rejects_a_given_discharge_power_max() -> None:
    config = _short_case()
    config = dataclasses.replace(
        config,
        storage=dataclasses.replace(
            config.storage, discharge_limit_mode="soc_dependent", discharge_power_max_mw=5.0
        ),
    )
    load = build_load_profile(
        config.process.profile_shape, config.process.annual_peak_load_mw, SHORT_HORIZON
    )
    price = synthetic_daily_price_profile(SHORT_HORIZON)
    curve = _reference_discharge_curve()
    with pytest.raises(ValueError, match="discharge_power_max_mw must be null"):
        solve_dispatch(config, load, price, discharge_curve=curve)


def test_soc_dependent_solve_reaches_optimal_and_verifies() -> None:
    config, load, price, result = _solve_short_soc_dependent()
    assert result.solver["termination"] == "optimal"
    checks = verify_schedule(result.schedule, config, result.solver["objective_eur"])
    assert all(checks.values()), checks


def _level_start_mwh(schedule, e_cap: float, soc_init_fraction: float) -> np.ndarray:
    # Independent reconstruction of the pre-dispatch state, the same
    # "previous" array verification.py's own storage-balance check builds:
    # soc_init_fraction*e_cap at t=0, the prior hour's post-dispatch level
    # otherwise.
    level = schedule["level_mwh"].to_numpy()
    previous = np.empty_like(level)
    previous[0] = soc_init_fraction * e_cap
    previous[1:] = level[:-1]
    return previous


def test_soc_dependent_discharge_never_exceeds_the_fitted_curve() -> None:
    # Default (start_of_hour, P0.4): the model's own constraint bounds
    # p_dis[t] using level_start[t] (pre-dispatch), not the schedule's
    # level_mwh column (post-dispatch) -- check against the same reference
    # the model actually used, not the other one, or this check would be
    # verifying a bound the solve was never actually held to.
    config, load, price, result = _solve_short_soc_dependent()
    curve = _reference_discharge_curve()
    e_cap = result.schedule.attrs["e_cap_mwh"]
    level_start = _level_start_mwh(result.schedule, e_cap, config.storage.soc_init_fraction)
    limits = np.array([curve.limit_mw(level, e_cap) for level in level_start])
    assert (result.schedule["p_dis_mw"].to_numpy() <= limits + 1e-6).all()


def test_soc_dependent_discharge_never_exceeds_curve_under_end_of_hour_reference() -> None:
    # The pre-P0.4 reference, kept as an explicit alternative (config.py):
    # here the constraint does use the post-dispatch level_mwh column
    # directly, so checking against it is correct for this mode specifically.
    _config, _load, _price, result = _solve_short_soc_dependent(
        discharge_capability_reference="end_of_hour"
    )
    curve = _reference_discharge_curve()
    e_cap = result.schedule.attrs["e_cap_mwh"]
    limits = result.schedule["level_mwh"].apply(lambda level: curve.limit_mw(level, e_cap))
    assert (result.schedule["p_dis_mw"] <= limits + 1e-6).all()


# --- P0.4: start-of-hour vs. end-of-hour discharge capability ----------------
#
# `dispatch.py`'s piecewise discharge-limit constraint used to bound p_dis[t]
# using level[t], the *post*-dispatch state storage_balance defines in terms
# of that same hour's own p_dis[t] -- backwards: capability at the start of
# an hour should depend on what was on hand before that hour's own discharge
# drew it down, not what's left after. The fix ties the bound to level_start
# (soc_init*E_cap at t=0, level[t-1] otherwise) instead, as an explicit,
# required config choice (storage.discharge_capability_reference), not a
# silent replacement of the old behaviour -- both remain available.


def test_discharge_capability_reference_is_a_required_explicit_choice() -> None:
    config = _short_case()
    config = dataclasses.replace(
        config, storage=dataclasses.replace(config.storage, discharge_limit_mode="soc_dependent")
    )
    assert config.storage.discharge_capability_reference is None
    load = build_load_profile(
        config.process.profile_shape, config.process.annual_peak_load_mw, SHORT_HORIZON
    )
    price = synthetic_daily_price_profile(SHORT_HORIZON)
    curve = _reference_discharge_curve()
    with pytest.raises(ValueError, match="discharge_capability_reference"):
        build_model(config, load, price, discharge_curve=curve)


@pytest.mark.parametrize("reference", ["start_of_hour", "end_of_hour"])
def test_both_discharge_capability_references_solve_and_verify(reference: str) -> None:
    # Roadmap acceptance criterion: demonstrate start-vs-end is an explicit,
    # working modelling option, not that only one of them actually runs.
    _config, _load, _price, result = _solve_short_soc_dependent(
        discharge_capability_reference=reference
    )
    assert result.solver["termination"] == "optimal"
    checks = verify_schedule(result.schedule, _config, result.solver["objective_eur"])
    assert all(checks.values()), checks


def test_discharge_capability_reference_changes_the_annual_result() -> None:
    # Roadmap acceptance criterion: quantify whether it changes the annual
    # result. It does, and by enough to flip which formulation needs more
    # power at this short-horizon, nearly-free-storage case: end_of_hour (the
    # project's old, more conservative choice) understates what the store
    # can actually deliver at the start of an hour, since it evaluates the
    # curve at the *already-discharged* level, so it reports needing *more*
    # power than the constant-limit baseline; start_of_hour (the corrected
    # reference) needs less, undercutting Phase C's original "SOC-dependent
    # always needs more power" framing as itself partly an artifact of this
    # bug, not a robust physical result (see docs/RESULTS.md's P0.4 section
    # for the full-horizon numbers).
    overrides = {"storage_capex_eur_per_mwh": 1.0, "storage_capex_eur_per_mw": 1.0}
    _config_a, _load_a, _price_a, result_constant = _solve_short(**overrides)
    _config_end, _load_end, _price_end, result_end_of_hour = _solve_short_soc_dependent(
        discharge_capability_reference="end_of_hour", **overrides
    )
    _config_start, _load_start, _price_start, result_start_of_hour = _solve_short_soc_dependent(
        discharge_capability_reference="start_of_hour", **overrides
    )
    constant_power = result_constant.schedule.attrs["power_rating_mw"]
    end_of_hour_power = result_end_of_hour.schedule.attrs["power_rating_mw"]
    start_of_hour_power = result_start_of_hour.schedule.attrs["power_rating_mw"]

    assert not np.isclose(end_of_hour_power, start_of_hour_power, rtol=1e-6)
    assert start_of_hour_power < end_of_hour_power
    assert end_of_hour_power > constant_power
    assert start_of_hour_power < constant_power


def test_mismatched_profile_length_is_rejected() -> None:
    config = _short_case()
    load = build_load_profile(config.process.profile_shape, config.process.annual_peak_load_mw, 24)
    price = synthetic_daily_price_profile(SHORT_HORIZON)
    with pytest.raises(ValueError, match="horizon_hours"):
        solve_dispatch(config, load, price)


def test_mixed_power_sizing_is_rejected() -> None:
    config = _short_case()
    config = dataclasses.replace(
        config, storage=dataclasses.replace(config.storage, charge_power_max_mw=5.0)
    )
    load = build_load_profile(
        config.process.profile_shape, config.process.annual_peak_load_mw, SHORT_HORIZON
    )
    price = synthetic_daily_price_profile(SHORT_HORIZON)
    with pytest.raises(ValueError, match="mixed sizing"):
        solve_dispatch(config, load, price)


def test_lossless_full_efficiency_charge_discharge_conserves_energy() -> None:
    # Analytic limit: with zero standing loss and unity round-trip
    # efficiency, whatever energy goes into the store must come back out,
    # exactly (to solver tolerance). This isolates the storage balance
    # identity from the economics that decide *whether* to use storage.
    config = _short_case(storage_capex_eur_per_mwh=1.0, storage_capex_eur_per_mw=1.0)
    config = dataclasses.replace(
        config,
        storage=dataclasses.replace(
            config.storage,
            eta_charge=1.0,
            eta_discharge=1.0,
            standing_loss_fraction_per_hour=0.0,
            soc_init_fraction=0.5,
            soc_final_min_fraction=0.5,
        ),
    )
    load = build_load_profile(
        config.process.profile_shape, config.process.annual_peak_load_mw, SHORT_HORIZON
    )
    price = synthetic_daily_price_profile(SHORT_HORIZON, daily_amplitude_eur_per_mwh=40.0)
    result = solve_dispatch(config, load, price)
    total_charged = result.schedule["p_ch_mw"].sum()
    total_discharged = result.schedule["p_dis_mw"].sum()
    e_cap = result.schedule.attrs["e_cap_mwh"]
    start_level = 0.5 * e_cap
    end_level = result.schedule["level_mwh"].iloc[-1]
    # level[-1] - level[0]  ==  total_charged - total_discharged, exactly, when
    # eta=1 and loss=0: the storage balance identity with nothing lost or
    # gained in translation.
    assert np.isclose(end_level - start_level, total_charged - total_discharged, atol=1e-6)


def test_capital_recovery_factor_matches_equivalent_closed_form() -> None:
    # Independent hand-derivation: CRF = r / (1 - (1+r)^-n) is algebraically
    # identical to r(1+r)^n / ((1+r)^n - 1); check the implementation against
    # this second form rather than a single hardcoded magic number.
    r, n = 0.06, 25.0
    expected = r / (1 - (1 + r) ** (-n))
    assert np.isclose(capital_recovery_factor(r, n), expected, rtol=1e-12)


def test_higher_discount_rate_lowers_optimal_storage_capacity() -> None:
    # Monotonicity a reader would expect: a more expensive cost of capital
    # should never make the model want *more* storage, all else equal.
    _config_low, _load, _price, result_low = _solve_short(discount_rate=0.03)
    _config_high, _load2, _price2, result_high = _solve_short(discount_rate=0.20)
    assert result_high.schedule.attrs["e_cap_mwh"] <= result_low.schedule.attrs["e_cap_mwh"] + 1e-6


def test_process_temperature_has_no_effect_on_phase_a_result() -> None:
    # Documents a real, deliberate limitation rather than letting it be a
    # silent surprise: Phase A's storage block is a temperature-agnostic MWh
    # reservoir (dispatch.py never reads delivery_temperature_c, medium, or
    # storage.temperature_max_c/min_c). Two configs that differ only in the
    # process temperature/medium must therefore solve to the identical
    # objective. That is exactly the simplification this project exists to
    # test; Phase C's SOC-dependent limit is what is supposed to break this
    # invariance. If this test starts failing without Phase C's discharge
    # curve being wired in, something changed by accident.
    config_300 = _short_case()
    config_400 = dataclasses.replace(
        config_300,
        process=dataclasses.replace(config_300.process, delivery_temperature_c=400.0, medium="air"),
    )
    load = build_load_profile(
        config_300.process.profile_shape, config_300.process.annual_peak_load_mw, SHORT_HORIZON
    )
    price = synthetic_daily_price_profile(SHORT_HORIZON)
    result_300 = solve_dispatch(config_300, load, price)
    result_400 = solve_dispatch(config_400, load, price)
    assert np.isclose(
        result_300.solver["objective_eur"], result_400.solver["objective_eur"], rtol=1e-9
    )


# --- C2: matched-duration-family sizing (roadmap P0.1) -----------------------
#
# The unmatched soc_dependent path (build_model's elif soc_dependent branch,
# exercised above) ties charge power to the discharge curve's own k=P/E
# ratio but leaves the constant-limit baseline free to pick its own
# independent P_rated: comparing the two paired confounds "the discharge
# limit shape changed" with "the two runs were also allowed different
# durations" (Phase C's committed result: constant tau=7.41h vs soc_dependent
# tau=3.88h). duration_matched mode removes that confound by tying power to
# E_cap/tau identically in both formulations, so a paired comparison isolates
# the discharge-limit shape alone.


def test_duration_matched_neither_formulation_gets_an_extra_free_power_variable() -> None:
    # P0.1 acceptance criterion: equal sizing degrees of freedom. Neither
    # formulation may create its own model.P_rated Var under
    # duration_matched mode; the only sizing DOF either has left is E_cap.
    tau = 4.0
    config = _short_case_duration_matched(tau)
    load = build_load_profile(
        config.process.profile_shape, config.process.annual_peak_load_mw, SHORT_HORIZON
    )
    price = synthetic_daily_price_profile(SHORT_HORIZON)

    model_constant = build_model(config, load, price)
    assert not hasattr(model_constant, "P_rated")
    assert not model_constant._power_is_var

    curve = _duration_matched_curve(tau)
    config_soc = dataclasses.replace(
        config,
        storage=dataclasses.replace(
            config.storage,
            discharge_limit_mode="soc_dependent",
            discharge_capability_reference="start_of_hour",
        ),
    )
    model_soc = build_model(config_soc, load, price, discharge_curve=curve)
    assert not hasattr(model_soc, "P_rated")
    assert not model_soc._power_is_var


def test_duration_matched_both_formulations_report_exactly_the_configured_duration() -> None:
    # P0.1 acceptance criterion: both report the configured E/P duration back
    # out, not a fitted or drifted one.
    tau = 6.0
    overrides = {"storage_capex_eur_per_mwh": 1.0, "storage_capex_eur_per_mw": 1.0}
    config = _short_case_duration_matched(tau, **overrides)
    load = build_load_profile(
        config.process.profile_shape, config.process.annual_peak_load_mw, SHORT_HORIZON
    )
    price = synthetic_daily_price_profile(SHORT_HORIZON)
    result_constant = solve_dispatch(config, load, price)

    curve = _duration_matched_curve(tau)
    config_soc = dataclasses.replace(
        config,
        storage=dataclasses.replace(
            config.storage,
            discharge_limit_mode="soc_dependent",
            discharge_capability_reference="start_of_hour",
        ),
    )
    result_soc = solve_dispatch(config_soc, load, price, discharge_curve=curve)

    for result in (result_constant, result_soc):
        e_cap = result.schedule.attrs["e_cap_mwh"]
        power = result.schedule.attrs["power_rating_mw"]
        assert e_cap > 1e-6, "degenerate at E_cap=0; nearly-free storage economics needed"
        assert np.isclose(power / e_cap, 1.0 / tau, rtol=1e-9)


def test_duration_matched_rejects_a_curve_fit_at_the_wrong_mass_flow() -> None:
    # A curve fit for a different tau than storage.design_duration_hours
    # would silently break the matched comparison (its own k != 1/tau);
    # build_model must reject it rather than accept a mismatched pairing.
    tau = 4.0
    config = _short_case_duration_matched(tau)
    config_soc = dataclasses.replace(
        config, storage=dataclasses.replace(config.storage, discharge_limit_mode="soc_dependent")
    )
    load = build_load_profile(
        config.process.profile_shape, config.process.annual_peak_load_mw, SHORT_HORIZON
    )
    price = synthetic_daily_price_profile(SHORT_HORIZON)
    wrong_curve = _reference_discharge_curve()  # fit at mass_flow=3.0, not tau=4h's matched flow
    with pytest.raises(ValueError, match="does not match storage.design_duration_hours"):
        build_model(config_soc, load, price, discharge_curve=wrong_curve)


def test_duration_matched_and_free_sizing_baseline_both_remain_available() -> None:
    # P0.1 acceptance criterion: the pre-existing free-sizing path (Phase
    # C's, confounded) must still work unchanged as a diagnostic baseline,
    # not be replaced outright by duration_matched mode.
    config_free = _short_case()
    assert config_free.storage.design_duration_hours is None
    load = build_load_profile(
        config_free.process.profile_shape, config_free.process.annual_peak_load_mw, SHORT_HORIZON
    )
    price = synthetic_daily_price_profile(SHORT_HORIZON)
    model_free = build_model(config_free, load, price)
    assert hasattr(model_free, "P_rated")

    config_matched = _short_case_duration_matched(4.0)
    model_matched = build_model(config_matched, load, price)
    assert not hasattr(model_matched, "P_rated")


# --- P0.5: prevent pathological simultaneous cycling under negative prices ---
#
# A pure LP with independent nonnegative p_ch[t]/p_dis[t] can exploit
# negative electricity prices by drawing heater electricity purely to
# collect the negative-price payment, discharging the store to make room
# for it in the same hour's heat balance, then charging the store right
# back up beyond what c_charge_limit alone would allow -- mathematically
# feasible, physically meaningless, and it burns real round-trip losses for
# no net storage benefit. storage.cycling_prevention_mode == "milp_binary"
# adds a per-hour binary forcing at most one direction active; "none" keeps
# the original LP available for nonnegative-price diagnostics.


def _negative_price_case():
    # Deliberately generous headroom (large heater capacity, sizeable given
    # charge/discharge power, moderate round-trip efficiency) so the
    # pathology actually has room to manifest, not a case so tightly sized
    # the LP has no slack to exploit regardless of mode.
    config = _short_case()
    config = dataclasses.replace(
        config,
        storage=dataclasses.replace(
            config.storage,
            energy_capacity_mwh=100.0,
            charge_power_max_mw=20.0,
            discharge_power_max_mw=20.0,
            eta_charge=0.95,
            eta_discharge=0.95,
        ),
        supply=dataclasses.replace(
            config.supply,
            electric_heater=dataclasses.replace(config.supply.electric_heater, capacity_mw=50.0),
        ),
    )
    load = build_load_profile(
        config.process.profile_shape, config.process.annual_peak_load_mw, SHORT_HORIZON
    )
    rng = np.random.default_rng(0)
    price_values = rng.normal(60.0, 20.0, SHORT_HORIZON)
    price_values[10:20] = -200.0  # a deep negative-price window
    price = pd.DataFrame({"hour": range(SHORT_HORIZON), "price_eur_per_mwh": price_values})
    return config, load, price


def _simultaneous_cycling_hours(schedule) -> int:
    return int(((schedule["p_ch_mw"] > 1e-6) & (schedule["p_dis_mw"] > 1e-6)).sum())


def test_lp_mode_exploits_negative_prices_with_simultaneous_cycling() -> None:
    # Establishes the problem actually reproduces in this codebase, not just
    # in theory: without a doubt, the model should be tested against a real
    # failure it exhibits, not an assumed one.
    config, load, price = _negative_price_case()
    config = dataclasses.replace(
        config, storage=dataclasses.replace(config.storage, cycling_prevention_mode="none")
    )
    result = solve_dispatch(config, load, price)
    assert result.solver["termination"] == "optimal"
    assert _simultaneous_cycling_hours(result.schedule) > 0


def test_milp_binary_mode_prevents_simultaneous_cycling_under_negative_prices() -> None:
    # Roadmap acceptance criterion 1: no hour has material simultaneous
    # charge and discharge when the MILP mode is enabled. Same case the LP
    # test above shows exploiting, so this is a direct before/after fix.
    config, load, price = _negative_price_case()
    config = dataclasses.replace(
        config, storage=dataclasses.replace(config.storage, cycling_prevention_mode="milp_binary")
    )
    result = solve_dispatch(config, load, price)
    assert result.solver["termination"] == "optimal"
    assert _simultaneous_cycling_hours(result.schedule) == 0


def test_milp_binary_mode_solves_and_verifies_under_negative_prices() -> None:
    # Roadmap acceptance criterion 2: negative price tests behave sensibly
    # -- optimal termination and every independent verification check
    # (energy balance, storage identity, terminal condition, objective
    # reconstruction) still passes with a negative-price profile and the
    # cycling-prevention binaries active.
    config, load, price = _negative_price_case()
    config = dataclasses.replace(
        config, storage=dataclasses.replace(config.storage, cycling_prevention_mode="milp_binary")
    )
    result = solve_dispatch(config, load, price)
    assert result.solver["termination"] == "optimal"
    checks = verify_schedule(result.schedule, config, result.solver["objective_eur"])
    assert all(checks.values()), checks
    reconstructed = reconstruct_objective(result.schedule, config)
    assert np.isclose(reconstructed, result.solver["objective_eur"], rtol=1e-6, atol=1e-3)


def test_milp_binary_objective_is_never_cheaper_than_the_lp_relaxation() -> None:
    # The MILP constraints are a strict restriction of the LP's own feasible
    # region (same model, plus c_charge_only_while_charging /
    # c_discharge_only_while_not_charging), so its optimal cost can only be
    # equal to or higher than the unconstrained LP's -- never lower. Confirms
    # the LP's lower cost in the test above is exactly the exploited
    # pathology's "value," not a genuinely better answer MILP is leaving on
    # the table.
    config, load, price = _negative_price_case()
    config_lp = dataclasses.replace(
        config, storage=dataclasses.replace(config.storage, cycling_prevention_mode="none")
    )
    config_milp = dataclasses.replace(
        config, storage=dataclasses.replace(config.storage, cycling_prevention_mode="milp_binary")
    )
    result_lp = solve_dispatch(config_lp, load, price)
    result_milp = solve_dispatch(config_milp, load, price)
    assert result_milp.kpis["total_cost_eur"] >= result_lp.kpis["total_cost_eur"] - 1e-6


def test_lp_mode_remains_available_for_nonnegative_price_diagnostics() -> None:
    # Roadmap acceptance criterion 3: the original LP mode remains available.
    # Ordinary nonnegative synthetic prices, cycling_prevention_mode="none"
    # (this project's default everywhere else): must still solve and verify
    # exactly as every other test in this file already relies on.
    config, _load, _price, result = _solve_short()
    assert config.storage.cycling_prevention_mode == "none"
    assert result.solver["termination"] == "optimal"
    assert _simultaneous_cycling_hours(result.schedule) == 0


def test_build_model_rejects_an_unknown_cycling_prevention_mode() -> None:
    config, load, price = _negative_price_case()
    config = dataclasses.replace(
        config,
        storage=dataclasses.replace(config.storage, cycling_prevention_mode="throughput_penalty"),
    )
    with pytest.raises(ValueError, match="cycling_prevention_mode"):
        build_model(config, load, price)


def test_blower_specific_power_defaults_to_zero_parasitic_cost() -> None:
    # No blower_specific_power_mw_per_mw given: every already-committed
    # result in this repository must stay exactly reproducible.
    _config, _load, _price, result = _solve_short()
    assert (result.schedule["blower_power_mw"] == 0.0).all()
    assert (result.schedule["blower_cost_eur"] == 0.0).all()
    assert result.kpis["blower_cost_eur"] == 0.0
    assert result.kpis["blower_energy_mwh"] == 0.0


def test_blower_specific_power_prices_a_parasitic_load_proportional_to_discharge() -> None:
    config = _short_case()
    load = build_load_profile(
        config.process.profile_shape, config.process.annual_peak_load_mw, SHORT_HORIZON
    )
    price = synthetic_daily_price_profile(SHORT_HORIZON)
    blower_ratio = 0.086  # P3.3/P5's own reported ~8.6% figure at a 2h design duration
    result = solve_dispatch(config, load, price, blower_specific_power_mw_per_mw=blower_ratio)
    expected_blower_power = blower_ratio * result.schedule["p_dis_mw"]
    assert np.allclose(result.schedule["blower_power_mw"], expected_blower_power, atol=1e-9)
    expected_blower_cost = result.schedule["price_eur_per_mwh"] * expected_blower_power
    assert np.allclose(result.schedule["blower_cost_eur"], expected_blower_cost, atol=1e-6)
    assert result.kpis["blower_cost_eur"] == pytest.approx(
        result.schedule["blower_cost_eur"].sum(), rel=1e-9
    )
    checks = verify_schedule(result.schedule, config, result.solver["objective_eur"])
    assert all(checks.values()), checks


def test_blower_specific_power_increases_total_cost_whenever_storage_discharges() -> None:
    # _negative_price_case's fixed-size storage and volatile price profile
    # guarantee real cycling (unlike the free-sizing default config over a
    # short 72h horizon, which finds no arbitrage case for building any
    # storage at all).
    config, load, price = _negative_price_case()
    without_blower = solve_dispatch(config, load, price)
    with_blower = solve_dispatch(config, load, price, blower_specific_power_mw_per_mw=0.086)
    assert without_blower.schedule["p_dis_mw"].sum() > 0, "test needs a case that discharges"
    assert with_blower.kpis["total_cost_eur"] > without_blower.kpis["total_cost_eur"]


def test_blower_specific_power_rejects_a_negative_ratio() -> None:
    config, load, price = _negative_price_case()
    with pytest.raises(ValueError, match="blower_specific_power_mw_per_mw"):
        build_model(config, load, price, blower_specific_power_mw_per_mw=-0.01)


def test_blower_specific_power_applies_identically_in_soc_dependent_mode() -> None:
    config, load, price, result = _solve_short_soc_dependent()
    result_with_blower = solve_dispatch(
        config,
        load,
        price,
        discharge_curve=_reference_discharge_curve(),
        blower_specific_power_mw_per_mw=0.086,
    )
    expected_blower_power = 0.086 * result_with_blower.schedule["p_dis_mw"]
    assert np.allclose(
        result_with_blower.schedule["blower_power_mw"], expected_blower_power, atol=1e-9
    )
    checks = verify_schedule(
        result_with_blower.schedule, config, result_with_blower.solver["objective_eur"]
    )
    assert all(checks.values()), checks
