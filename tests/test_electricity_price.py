from __future__ import annotations

import pytest

from tes_screen.electricity_price import load_electricity_price


def test_synthetic_source_returns_valid_profile() -> None:
    profile = load_electricity_price("synthetic", 168)
    assert len(profile) == 168
    assert "price_eur_per_mwh" in profile.columns


def test_entso_e_source_fails_loud_without_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ENTSOE_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="ENTSOE_API_KEY"):
        load_electricity_price("entso_e", 168)


def test_unknown_source_is_rejected() -> None:
    with pytest.raises(ValueError, match="unknown electricity_price_source"):
        load_electricity_price("made_up_source", 168)
