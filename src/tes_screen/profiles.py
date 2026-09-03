"""Profile contract: explicit required columns, validated on load, no silent coercion.

Mirrors the validation shape used for setpoint profiles in OpenSteamOpt
(``rto.py::_validate_profiles``): an exact required-column set, consecutive
zero-based hours, finite values, and a stated sign contract. A profile that
fails any check is rejected with the contract spelled out in the error, not
silently repaired.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

PROCESS_LOAD_COLUMNS = frozenset({"hour", "heat_demand_mw"})
ELECTRICITY_PRICE_COLUMNS = frozenset({"hour", "price_eur_per_mwh"})


def validate_profile(
    profile: pd.DataFrame,
    required_columns: frozenset[str],
    *,
    allow_negative: frozenset[str] = frozenset(),
) -> None:
    """Validate a profile against an explicit column contract.

    Parameters
    ----------
    profile:
        The loaded profile.
    required_columns:
        The exact set of columns the profile must have; no more, no fewer.
    allow_negative:
        Columns exempt from the nonnegativity check (e.g. a price series that
        can legitimately go negative). Empty by default.
    """

    if set(profile.columns) != set(required_columns):
        raise ValueError(
            "profile columns do not match the contract. "
            f"required: {sorted(required_columns)}, got: {sorted(profile.columns)}"
        )
    if profile.empty or profile["hour"].tolist() != list(range(len(profile))):
        raise ValueError("profile must have consecutive zero-based hourly records")

    numeric = profile.select_dtypes(include="number")
    if numeric.isna().any().any() or not np.isfinite(numeric.to_numpy()).all():
        raise ValueError("profile must be finite everywhere; no NaN or inf")

    checked_columns = [c for c in profile.columns if c != "hour" and c not in allow_negative]
    if checked_columns and (profile[checked_columns] < 0).any().any():
        raise ValueError(f"profile columns must be nonnegative: {checked_columns}")


def load_profile(
    path: str,
    required_columns: frozenset[str],
    *,
    allow_negative: frozenset[str] = frozenset(),
) -> pd.DataFrame:
    """Load a CSV profile and validate it against ``required_columns``."""

    profile = pd.read_csv(path)
    validate_profile(profile, required_columns, allow_negative=allow_negative)
    return profile
