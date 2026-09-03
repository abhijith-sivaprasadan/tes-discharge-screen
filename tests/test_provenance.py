from __future__ import annotations

import hashlib
from pathlib import Path

from tes_screen.provenance import (
    ProvenanceRecord,
    build_provenance_record,
    check_calendar_completeness,
    read_provenance_record,
    sha256_file,
    write_provenance_record,
)


def test_sha256_file_matches_hashlib(tmp_path: Path) -> None:
    raw = tmp_path / "data.csv"
    raw.write_text("hour,price_eur_per_mwh\n0,10\n1,20\n", encoding="utf-8")
    expected = hashlib.sha256(raw.read_bytes()).hexdigest()
    assert sha256_file(raw) == expected


def test_calendar_completeness_detects_gaps_and_duplicates() -> None:
    result = check_calendar_completeness([0, 1, 1, 3], expected_count=4)
    assert result["complete"] is False
    assert result["missing_hours"] == [2]
    assert result["duplicate_hours"] == [1]


def test_calendar_completeness_passes_for_full_coverage() -> None:
    result = check_calendar_completeness(list(range(8760)), expected_count=8760)
    assert result["complete"] is True
    assert result["missing_hours"] == []
    assert result["duplicate_hours"] == []


def test_build_provenance_record_records_checksum_and_row_count(tmp_path: Path) -> None:
    raw = tmp_path / "prices.csv"
    raw.write_text("hour,price_eur_per_mwh\n0,10\n1,20\n", encoding="utf-8")
    calendar_check = check_calendar_completeness([0, 1], expected_count=2)

    record = build_provenance_record(
        source="entso_e",
        variables=["price_eur_per_mwh"],
        start="2023-01-01T00:00:00+00:00",
        end="2023-01-01T01:00:00+00:00",
        timezone_name="Europe/Amsterdam",
        request_params={"bidding_zone": "NL"},
        raw_file=raw,
        expected_row_count=2,
        actual_row_count=2,
        calendar_check=calendar_check,
    )

    assert isinstance(record, ProvenanceRecord)
    assert record.file_sha256 == sha256_file(raw)
    assert record.row_count == {"expected": 2, "actual": 2}
    assert record.calendar_check["complete"] is True
    assert record.schema_version == 1


def test_provenance_record_round_trips_through_json(tmp_path: Path) -> None:
    raw = tmp_path / "prices.csv"
    raw.write_text("hour,price_eur_per_mwh\n0,10\n", encoding="utf-8")
    calendar_check = check_calendar_completeness([0], expected_count=1)

    record = build_provenance_record(
        source="entso_e",
        variables=["price_eur_per_mwh"],
        start="2023-01-01T00:00:00+00:00",
        end="2023-01-01T00:00:00+00:00",
        timezone_name="Europe/Amsterdam",
        request_params={"bidding_zone": "NL"},
        raw_file=raw,
        expected_row_count=1,
        actual_row_count=1,
        calendar_check=calendar_check,
    )

    record_path = tmp_path / "provenance_records" / "prices.json"
    write_provenance_record(record, record_path)
    loaded = read_provenance_record(record_path)

    assert loaded["source"] == "entso_e"
    assert loaded["file_sha256"] == record.file_sha256
    assert loaded["row_count"] == {"expected": 1, "actual": 1}
