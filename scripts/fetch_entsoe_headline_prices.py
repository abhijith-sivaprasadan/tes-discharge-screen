"""Fetch one year of real ENTSO-E day-ahead prices for the headline comparison.

Usage: python scripts/fetch_entsoe_headline_prices.py [bidding_zone] [year]
Defaults: bidding_zone=SE_3 (Stockholm price area -- this project's own KTH
context), year=2024 (the most recent full calendar year at the time this
script was written).

Requires ENTSOE_API_KEY (register at https://transparency.entsoe.eu, Web API
security token in account settings) and the 'entsoe-py' package (`uv sync
--extra entsoe`). Writes the fetched series to data/raw/ (cached CSV) and
data/provenance_records/ (a ProvenanceRecord -- source, request params,
calendar-completeness check), via `electricity_price.fetch_and_record_entsoe`,
then copies the result into data/profiles/ in this project's own
`{hour, price_eur_per_mwh}` schema so it is a drop-in replacement for
`synthetic_profiles.synthetic_daily_price_profile` at any script's `price =`
call site.

As of 2026-09-07, this script has been written but not actually run: this
working environment's own outbound network egress policy blocks
web-api.tp.entsoe.eu at the proxy level (confirmed via
`curl $HTTPS_PROXY/__agentproxy/status`'s `recentRelayFailures`, a 403 on the
CONNECT, independent of the credential or this project's code). Run this from
an environment whose egress policy allows that host once one is available.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from tes_screen.electricity_price import fetch_and_record_entsoe  # noqa: E402

DEFAULT_BIDDING_ZONE = "SE_3"
DEFAULT_YEAR = 2024
TIMEZONE_NAME = "Europe/Stockholm"


def main() -> None:
    bidding_zone = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_BIDDING_ZONE
    year = int(sys.argv[2]) if len(sys.argv) > 2 else DEFAULT_YEAR
    start_date = f"{year}-01-01"
    end_date = f"{year}-12-31"

    print(f"Fetching {bidding_zone} day-ahead prices, {start_date}..{end_date} ...")
    df, record = fetch_and_record_entsoe(bidding_zone, start_date, end_date, TIMEZONE_NAME)
    print(f"Fetched {len(df)} hourly rows. Calendar check: {record.calendar_check}")

    profiles_dir = Path("data/profiles")
    profiles_dir.mkdir(parents=True, exist_ok=True)
    out_path = profiles_dir / f"entsoe_{bidding_zone}_{year}.csv"
    df.to_csv(out_path, index=False)
    print(f"Written to {out_path} (drop-in replacement for synthetic_daily_price_profile).")
    print(
        f"Price range: {df['price_eur_per_mwh'].min():.2f} to "
        f"{df['price_eur_per_mwh'].max():.2f} EUR/MWh, "
        f"mean {df['price_eur_per_mwh'].mean():.2f} EUR/MWh."
    )


if __name__ == "__main__":
    main()
