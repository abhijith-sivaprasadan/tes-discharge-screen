"""Electricity price source: real ENTSO-E day-ahead prices, gated by credential.

Ported from PyNEXUS's `data/entsoe.py`. That module is itself built and
unit-tested but has never been run against a live ENTSO-E credential in
PyNEXUS; its own docstring records that deferral explicitly and falls back to
synthetic prices until `ENTSOE_API_KEY` is actually available to test
against. This module follows the identical pattern for the identical reason:
no `ENTSOE_API_KEY` is configured in this working environment either.

`supply.electricity_price_source` in a case config selects which path is
used: "entso_e" attempts the real fetch and raises if no key is configured
(fail loud, no silent fallback to synthetic data behind a real-looking
label); "synthetic" explicitly asks for the declared-synthetic series.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import pandas as pd

from tes_screen.profiles import ELECTRICITY_PRICE_COLUMNS, validate_profile
from tes_screen.provenance import (
    ProvenanceRecord,
    build_provenance_record,
    check_calendar_completeness,
    write_provenance_record,
)
from tes_screen.synthetic_profiles import synthetic_daily_price_profile

ENTSOE_SOURCE = "ENTSO-E Transparency Platform (day-ahead prices, A44)"


def _get_api_key() -> str:
    key = os.environ.get("ENTSOE_API_KEY", "").strip()
    if not key:
        raise RuntimeError(
            "ENTSOE_API_KEY environment variable is not set. Register at "
            "https://transparency.entsoe.eu and request a Web API security token "
            "from your account settings. Until then, use "
            "supply.electricity_price_source: synthetic in the case config."
        )
    return key


def fetch_entsoe_prices(
    bidding_zone: str, start_date: str, end_date: str, timezone_name: str
) -> tuple[pd.Series, dict[str, Any]]:
    """Fetch real day-ahead prices for one bidding zone and date range.

    Not exercised by this repository's tests or committed results: no
    ENTSOE_API_KEY is configured here. Kept as a ready interface for when one
    is, mirroring PyNEXUS's identical deferral of its own ENTSO-E module.
    """
    try:
        from entsoe import EntsoePandasClient
    except ImportError as exc:
        raise ImportError(
            "fetch_entsoe_prices requires the 'entsoe-py' package: pip install entsoe-py"
        ) from exc

    api_key = _get_api_key()
    try:
        client = EntsoePandasClient(api_key=api_key)
    except Exception as exc:
        raise RuntimeError(f"ENTSO-E client could not be created: {exc}") from exc

    start = pd.Timestamp(start_date, tz=timezone_name)
    end = pd.Timestamp(end_date, tz=timezone_name) + pd.Timedelta(days=1)
    try:
        prices = client.query_day_ahead_prices(bidding_zone, start=start, end=end)
    except Exception as exc:
        raise RuntimeError(
            f"ENTSO-E query failed for {bidding_zone} {start_date}..{end_date}: {exc}"
        ) from exc

    request_metadata = {
        "bidding_zone": bidding_zone,
        "document_type": "A44",
        "start": start.isoformat(),
        "end": end.isoformat(),
    }
    return prices, request_metadata


def fetch_and_record_entsoe(
    bidding_zone: str,
    start_date: str,
    end_date: str,
    timezone_name: str,
    cache_dir: Path = Path("data/raw"),
    provenance_dir: Path = Path("data/provenance_records"),
) -> tuple[pd.DataFrame, ProvenanceRecord]:
    """Full pipeline: fetch, cache raw, check coverage, write provenance record."""
    prices, request_metadata = fetch_entsoe_prices(
        bidding_zone, start_date, end_date, timezone_name
    )

    df = pd.DataFrame({"hour": range(len(prices)), "price_eur_per_mwh": prices.to_numpy()})
    validate_profile(df, ELECTRICITY_PRICE_COLUMNS, allow_negative=frozenset({"price_eur_per_mwh"}))

    cache_dir.mkdir(parents=True, exist_ok=True)
    raw_file = cache_dir / f"entsoe_{bidding_zone}_{start_date}_{end_date}.csv"
    df.to_csv(raw_file, index=False)

    calendar_check = check_calendar_completeness(df["hour"].tolist(), expected_count=len(df))
    if not calendar_check["complete"]:
        raise ValueError(f"Incomplete ENTSO-E coverage: {calendar_check}")

    record = build_provenance_record(
        source=ENTSOE_SOURCE,
        variables=["day_ahead_price"],
        start=start_date,
        end=end_date,
        timezone_name=timezone_name,
        request_params=request_metadata,
        raw_file=raw_file,
        expected_row_count=len(df),
        actual_row_count=len(df),
        calendar_check=calendar_check,
        extra={"bidding_zone": bidding_zone},
    )
    provenance_path = provenance_dir / f"entsoe_{bidding_zone}_{start_date}_{end_date}.json"
    write_provenance_record(record, provenance_path)
    return df, record


def load_electricity_price(
    source: str, horizon_hours: int, **synthetic_kwargs: Any
) -> pd.DataFrame:
    """Resolve `supply.electricity_price_source` to an hourly price DataFrame.

    "synthetic" always succeeds (see `synthetic_profiles.synthetic_daily_price_profile`).
    "entso_e" raises RuntimeError naming the missing credential rather than
    silently substituting synthetic data under a real-sounding label.
    """
    if source == "synthetic":
        return synthetic_daily_price_profile(horizon_hours, **synthetic_kwargs)
    if source == "entso_e":
        _get_api_key()
        raise NotImplementedError(
            "ENTSOE_API_KEY is set, but the live-fetch call path (bidding zone, "
            "date range) is not wired into load_electricity_price yet; call "
            "fetch_and_record_entsoe directly with those parameters."
        )
    raise ValueError(f"unknown electricity_price_source {source!r}")


__all__ = [
    "ENTSOE_SOURCE",
    "fetch_and_record_entsoe",
    "fetch_entsoe_prices",
    "load_electricity_price",
]
