"""Synthetic hourly profile generators for process heat load and electricity price.

Every profile this module produces is synthetic: a declared shape, not a
measurement of any real site or market. See docs/DATA.md. Every profile is run
through the same contract validation used for any other profile
(`tes_screen.profiles.validate_profile`) before being returned.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from tes_screen.profiles import ELECTRICITY_PRICE_COLUMNS, PROCESS_LOAD_COLUMNS, validate_profile


def flat_load_profile(peak_mw: float, horizon_hours: int) -> pd.DataFrame:
    """Constant demand at ``peak_mw`` for every hour. Synthetic."""
    profile = pd.DataFrame(
        {"hour": range(horizon_hours), "heat_demand_mw": [peak_mw] * horizon_hours}
    )
    validate_profile(profile, PROCESS_LOAD_COLUMNS)
    return profile


def two_shift_load_profile(
    peak_mw: float,
    horizon_hours: int,
    *,
    shift_start_hour: int = 6,
    shift_end_hour: int = 22,
    off_shift_fraction: float = 0.2,
) -> pd.DataFrame:
    """Two daily 8-hour-class shifts at ``peak_mw``, a low base load outside them.

    ``shift_start_hour``/``shift_end_hour`` are hour-of-day boundaries (0-23);
    ``off_shift_fraction`` is the demand fraction retained outside shift hours
    (equipment idling, space heating, standby losses). Synthetic.
    """
    if not 0 <= shift_start_hour < shift_end_hour <= 24:
        raise ValueError("shift_start_hour must be before shift_end_hour, both in [0, 24]")
    if not 0 <= off_shift_fraction <= 1:
        raise ValueError("off_shift_fraction must be in [0, 1]")
    hour_of_day = np.arange(horizon_hours) % 24
    on_shift = (hour_of_day >= shift_start_hour) & (hour_of_day < shift_end_hour)
    demand = np.where(on_shift, peak_mw, peak_mw * off_shift_fraction)
    profile = pd.DataFrame({"hour": range(horizon_hours), "heat_demand_mw": demand})
    validate_profile(profile, PROCESS_LOAD_COLUMNS)
    return profile


def seasonal_load_profile(
    peak_mw: float,
    horizon_hours: int,
    *,
    trough_fraction: float = 0.5,
    peak_day_of_year: int = 15,
) -> pd.DataFrame:
    """A winter-heavy annual sinusoid between ``trough_fraction * peak_mw`` and ``peak_mw``.

    ``peak_day_of_year`` sets the phase (day 15 = mid-January, a heating-season
    peak). Synthetic; intended for a full 8,760-hour horizon, but works for any
    length.
    """
    if not 0 <= trough_fraction <= 1:
        raise ValueError("trough_fraction must be in [0, 1]")
    hour = np.arange(horizon_hours)
    day_of_year = (hour / 24.0) % 365.25
    phase = 2 * np.pi * (day_of_year - peak_day_of_year) / 365.25
    midpoint = peak_mw * (1 + trough_fraction) / 2
    amplitude = peak_mw * (1 - trough_fraction) / 2
    demand = midpoint + amplitude * np.cos(phase)
    profile = pd.DataFrame({"hour": range(horizon_hours), "heat_demand_mw": demand})
    validate_profile(profile, PROCESS_LOAD_COLUMNS)
    return profile


LOAD_PROFILE_GENERATORS = {
    "flat": flat_load_profile,
    "two_shift": two_shift_load_profile,
    "seasonal": seasonal_load_profile,
}


def build_load_profile(shape: str, peak_mw: float, horizon_hours: int) -> pd.DataFrame:
    """Dispatch to the named shape's generator with its documented defaults."""
    try:
        generator = LOAD_PROFILE_GENERATORS[shape]
    except KeyError as exc:
        raise ValueError(
            f"unknown profile_shape {shape!r}; known: {sorted(LOAD_PROFILE_GENERATORS)}"
        ) from exc
    return generator(peak_mw, horizon_hours)


def synthetic_daily_price_profile(
    horizon_hours: int,
    *,
    mean_price_eur_per_mwh: float = 60.0,
    daily_amplitude_eur_per_mwh: float = 25.0,
    weekend_discount_fraction: float = 0.3,
    noise_seed: int = 0,
    noise_std_eur_per_mwh: float = 5.0,
) -> pd.DataFrame:
    """A declared-synthetic hourly electricity price series with a daily cycle.

    Cheaper overnight, a morning/evening peak, a discount on weekend days
    (day-of-week 5, 6 in an hour-indexed series starting at an assumed Monday
    hour 0), plus bounded random noise from a fixed seed for reproducibility.
    This exists only because no ENTSOE_API_KEY is configured in this working
    environment; see docs/DATA.md and `tes_screen.electricity_price`. Every
    caller must label results built from it as synthetic.
    """
    hour_of_day = np.arange(horizon_hours) % 24
    day_of_week = (np.arange(horizon_hours) // 24) % 7
    daily_shape = -np.cos(2 * np.pi * (hour_of_day - 7) / 24)
    weekend = day_of_week >= 5
    rng = np.random.default_rng(noise_seed)
    noise = rng.normal(0.0, noise_std_eur_per_mwh, size=horizon_hours)
    price = mean_price_eur_per_mwh + daily_amplitude_eur_per_mwh * daily_shape + noise
    price = np.where(weekend, price * (1 - weekend_discount_fraction), price)
    profile = pd.DataFrame({"hour": range(horizon_hours), "price_eur_per_mwh": price})
    validate_profile(
        profile, ELECTRICITY_PRICE_COLUMNS, allow_negative=frozenset({"price_eur_per_mwh"})
    )
    return profile
