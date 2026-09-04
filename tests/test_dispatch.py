from __future__ import annotations

import dataclasses
import functools

import numpy as np
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


def _solve_short_soc_dependent(**economics_overrides: float):
    config = _short_case(**economics_overrides)
    config = dataclasses.replace(
        config,
        storage=dataclasses.replace(
            config.storage, discharge_limit_mode="soc_dependent", discharge_power_max_mw=None
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


def test_soc_dependent_discharge_never_exceeds_the_fitted_curve() -> None:
    config, load, price, result = _solve_short_soc_dependent()
    curve = _reference_discharge_curve()
    e_cap = result.schedule.attrs["e_cap_mwh"]
    limits = result.schedule["level_mwh"].apply(lambda level: curve.limit_mw(level, e_cap))
    assert (result.schedule["p_dis_mw"] <= limits + 1e-6).all()


def test_soc_dependent_requires_more_power_capacity_than_constant_limit_for_the_same_case() -> None:
    # The headline physical expectation: a store whose discharge power falls
    # away with state of charge needs more full-charge power capability to
    # deliver the same load profile than the constant-limit baseline assumes
    # it can. This is what makes the constant-limit simplification an
    # understatement of what a real sensible-heat store needs, not the other
    # way around. Nearly-free storage CAPEX forces both formulations to
    # actually build storage at this short horizon, so the comparison isn't
    # degenerate at E_cap=0 (see the full-horizon Phase C experiment for the
    # result under real economics).
    overrides = {"storage_capex_eur_per_mwh": 1.0, "storage_capex_eur_per_mw": 1.0}
    _config_a, _load_a, _price_a, result_constant = _solve_short(**overrides)
    _config_c, _load_c, _price_c, result_soc = _solve_short_soc_dependent(**overrides)
    assert (
        result_soc.schedule.attrs["power_rating_mw"]
        > result_constant.schedule.attrs["power_rating_mw"]
    )


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
        config, storage=dataclasses.replace(config.storage, discharge_limit_mode="soc_dependent")
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
        config, storage=dataclasses.replace(config.storage, discharge_limit_mode="soc_dependent")
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
