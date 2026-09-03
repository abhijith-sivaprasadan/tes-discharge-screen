"""Provenance records for externally fetched or literature-sourced data.

Ported from PyNEXUS's ``data/provenance.py``. Every input series this
repository pulls from an external source (ENTSO-E prices, published material
properties) is accompanied by a committed record answering: what was
requested, from where, when, and did it arrive complete. Refuse to proceed on
incomplete coverage rather than imputing silently; that decision belongs to
the caller, this module only reports what it found.

Records are small JSON files committed to ``data/provenance_records/``. Raw
downloads are not committed (see ``.gitignore``); the record plus its
checksum is what lets someone verify a re-fetch matches.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def sha256_file(path: Path) -> str:
    """SHA-256 of a file's bytes, read in chunks so large files are fine."""
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def check_calendar_completeness(hours: list[int], expected_count: int) -> dict[str, Any]:
    """Check a series of integer hour indices for gaps against an expected count.

    Returns a small record rather than raising, so callers can decide whether
    an incomplete series is fatal for their use case.
    """
    complete = hours == list(range(expected_count))
    missing = sorted(set(range(expected_count)) - set(hours))
    duplicates = sorted({h for h in hours if hours.count(h) > 1})
    return {
        "complete": complete,
        "expected_count": expected_count,
        "actual_count": len(hours),
        "missing_hours": missing,
        "duplicate_hours": duplicates,
    }


@dataclass
class ProvenanceRecord:
    """One committed record for one fetched or literature-sourced dataset."""

    source: str
    variables: list[str]
    request_params: dict[str, Any]
    temporal_range: dict[str, str]
    retrieval_timestamp: str
    file_sha256: str
    row_count: dict[str, int]
    calendar_check: dict[str, Any]
    schema_version: int = 1
    extra: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def build_provenance_record(
    *,
    source: str,
    variables: list[str],
    start: str,
    end: str,
    timezone_name: str,
    request_params: dict[str, Any],
    raw_file: Path,
    expected_row_count: int,
    actual_row_count: int,
    calendar_check: dict[str, Any],
    extra: dict[str, Any] | None = None,
) -> ProvenanceRecord:
    """Assemble a ProvenanceRecord from the pieces a fetch/load step produces."""
    return ProvenanceRecord(
        source=source,
        variables=list(variables),
        request_params=request_params,
        temporal_range={"start": start, "end": end, "timezone": timezone_name},
        retrieval_timestamp=datetime.now(timezone.utc).isoformat(),
        file_sha256=sha256_file(raw_file),
        row_count={"expected": expected_row_count, "actual": actual_row_count},
        calendar_check=calendar_check,
        extra=extra or {},
    )


def write_provenance_record(record: ProvenanceRecord, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(record.to_dict(), indent=2, sort_keys=True) + "\n", encoding="utf-8")


def read_provenance_record(path: Path) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))
