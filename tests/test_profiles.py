from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from tes_screen.profiles import (
    ELECTRICITY_PRICE_COLUMNS,
    PROCESS_LOAD_COLUMNS,
    validate_profile,
)


def _valid_load_profile(hours: int = 24) -> pd.DataFrame:
    return pd.DataFrame({"hour": range(hours), "heat_demand_mw": [5.0] * hours})


def test_valid_profile_passes() -> None:
    validate_profile(_valid_load_profile(), PROCESS_LOAD_COLUMNS)


def test_missing_column_is_rejected() -> None:
    profile = _valid_load_profile().drop(columns="heat_demand_mw")
    with pytest.raises(ValueError, match="contract"):
        validate_profile(profile, PROCESS_LOAD_COLUMNS)


def test_unexpected_column_is_rejected() -> None:
    profile = _valid_load_profile()
    profile["extra_column"] = 1.0
    with pytest.raises(ValueError, match="contract"):
        validate_profile(profile, PROCESS_LOAD_COLUMNS)


def test_non_consecutive_hours_are_rejected() -> None:
    profile = _valid_load_profile()
    profile.loc[3, "hour"] = 99
    with pytest.raises(ValueError, match="consecutive zero-based"):
        validate_profile(profile, PROCESS_LOAD_COLUMNS)


def test_empty_profile_is_rejected() -> None:
    profile = pd.DataFrame({"hour": [], "heat_demand_mw": []})
    with pytest.raises(ValueError, match="consecutive zero-based"):
        validate_profile(profile, PROCESS_LOAD_COLUMNS)


def test_nan_is_rejected() -> None:
    profile = _valid_load_profile()
    profile.loc[2, "heat_demand_mw"] = np.nan
    with pytest.raises(ValueError, match="finite"):
        validate_profile(profile, PROCESS_LOAD_COLUMNS)


def test_infinite_value_is_rejected() -> None:
    profile = _valid_load_profile()
    profile.loc[2, "heat_demand_mw"] = np.inf
    with pytest.raises(ValueError, match="finite"):
        validate_profile(profile, PROCESS_LOAD_COLUMNS)


def test_negative_value_is_rejected_by_default() -> None:
    profile = _valid_load_profile()
    profile.loc[0, "heat_demand_mw"] = -1.0
    with pytest.raises(ValueError, match="nonnegative"):
        validate_profile(profile, PROCESS_LOAD_COLUMNS)


def test_allow_negative_exempts_named_column() -> None:
    profile = pd.DataFrame({"hour": range(3), "price_eur_per_mwh": [-5.0, 10.0, 3.0]})
    validate_profile(
        profile, ELECTRICITY_PRICE_COLUMNS, allow_negative=frozenset({"price_eur_per_mwh"})
    )


def test_no_silent_coercion_of_string_hours() -> None:
    profile = pd.DataFrame({"hour": ["0", "1", "2"], "heat_demand_mw": [1.0, 2.0, 3.0]})
    with pytest.raises(ValueError, match="consecutive zero-based"):
        validate_profile(profile, PROCESS_LOAD_COLUMNS)
