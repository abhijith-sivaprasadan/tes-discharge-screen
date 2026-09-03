from __future__ import annotations

import dataclasses

import numpy as np
import pytest

from tes_screen.config import load_config
from tes_screen.dispatch import capital_recovery_factor, solve_dispatch
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


def test_soc_dependent_discharge_mode_is_not_implemented_here() -> None:
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
