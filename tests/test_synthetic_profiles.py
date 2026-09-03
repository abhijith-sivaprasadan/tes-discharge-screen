from __future__ import annotations

import numpy as np
import pytest

from tes_screen.synthetic_profiles import (
    build_load_profile,
    flat_load_profile,
    seasonal_load_profile,
    synthetic_daily_price_profile,
    two_shift_load_profile,
)

HORIZON = 8760


def test_flat_profile_is_constant_at_peak() -> None:
    profile = flat_load_profile(10.0, 168)
    assert (profile["heat_demand_mw"] == 10.0).all()


def test_two_shift_profile_matches_peak_and_off_shift_bounds() -> None:
    profile = two_shift_load_profile(10.0, 48, off_shift_fraction=0.25)
    values = set(np.round(profile["heat_demand_mw"], 6))
    assert values == {10.0, 2.5}


def test_two_shift_profile_rejects_bad_bounds() -> None:
    with pytest.raises(ValueError):
        two_shift_load_profile(10.0, 48, shift_start_hour=22, shift_end_hour=6)


def test_seasonal_profile_stays_within_declared_bounds() -> None:
    profile = seasonal_load_profile(10.0, HORIZON, trough_fraction=0.4)
    assert profile["heat_demand_mw"].max() <= 10.0 + 1e-9
    assert profile["heat_demand_mw"].min() >= 4.0 - 1e-9


def test_seasonal_profile_peaks_near_january() -> None:
    profile = seasonal_load_profile(10.0, HORIZON, trough_fraction=0.0, peak_day_of_year=15)
    peak_hour = int(profile["heat_demand_mw"].idxmax())
    peak_day = peak_hour // 24
    assert abs(peak_day - 15) <= 2 or abs(peak_day - 15 - 365) <= 2


def test_build_load_profile_dispatches_to_named_shape() -> None:
    flat = build_load_profile("flat", 5.0, 24)
    assert (flat["heat_demand_mw"] == 5.0).all()


def test_build_load_profile_rejects_unknown_shape() -> None:
    with pytest.raises(ValueError, match="unknown profile_shape"):
        build_load_profile("bogus", 5.0, 24)


def test_synthetic_price_profile_is_reproducible_given_seed() -> None:
    first = synthetic_daily_price_profile(HORIZON, noise_seed=42)
    second = synthetic_daily_price_profile(HORIZON, noise_seed=42)
    assert np.allclose(first["price_eur_per_mwh"], second["price_eur_per_mwh"])


def test_synthetic_price_profile_has_a_daily_cycle() -> None:
    profile = synthetic_daily_price_profile(
        168,
        mean_price_eur_per_mwh=60.0,
        daily_amplitude_eur_per_mwh=30.0,
        noise_std_eur_per_mwh=0.0,
    )
    by_hour = profile.groupby(profile["hour"] % 24)["price_eur_per_mwh"].mean()
    assert by_hour.max() - by_hour.min() > 20.0


def test_synthetic_price_profile_is_finite_and_contract_valid() -> None:
    profile = synthetic_daily_price_profile(HORIZON)
    assert profile["hour"].tolist() == list(range(HORIZON))
    assert np.isfinite(profile["price_eur_per_mwh"]).all()
