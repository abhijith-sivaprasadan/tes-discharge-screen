from __future__ import annotations

from pathlib import Path

import pytest

from tes_screen.fmu import build_fmu, find_omc


def test_find_omc_returns_none_when_toolchain_is_absent(monkeypatch: pytest.MonkeyPatch) -> None:
    # True in this working environment: no omc on PATH, no TES_SCREEN_OMC set.
    monkeypatch.delenv("TES_SCREEN_OMC", raising=False)
    monkeypatch.setattr("shutil.which", lambda _name: None)
    assert find_omc() is None


def test_build_fmu_fails_loud_without_the_toolchain(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("TES_SCREEN_OMC", raising=False)
    monkeypatch.setattr("shutil.which", lambda _name: None)
    with pytest.raises(FileNotFoundError, match="TES_SCREEN_OMC"):
        build_fmu(Path("."), tmp_path)
