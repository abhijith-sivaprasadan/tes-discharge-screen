"""Explicit targeted factor selection and archival controls."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tes_screen.config import load_config

from scripts.run_posthoc_fidelity_crossover import (
    compare_fidelity_rankings,
    study_grid,
    write_derived_config,
)
from scripts.run_targeted_fidelity_transition import TARGET_FACTORS


def test_three_separate_posthoc_followups_are_labelled():
    assert set(TARGET_FACTORS) == {"flat", "two_shift", "seasonal"}
    assert all(len(v) == 3 for v in TARGET_FACTORS.values())
    assert all(all(0.25 < f < 0.5 for f in v) for v in TARGET_FACTORS.values())
    assert len({tuple(x) for x in TARGET_FACTORS.values()}) == 3


def test_targeted_grid_has_four_records_per_factor_and_two_formulations():
    for factors in TARGET_FACTORS.values():
        cases = study_grid(factors)
        assert len(cases) == 12
        assert {
            (case["technology"], case["formulation"]) for case in cases
        } == {
            ("packed_bed", "constant"),
            ("packed_bed", "soc_dependent"),
            ("molten_salt", "constant"),
            ("molten_salt", "soc_dependent"),
        }


def test_nonfinite_or_duplicate_factors_rejected():
    with pytest.raises(ValueError, match="Unique"):
        study_grid((0.398, 0.398))
    with pytest.raises(ValueError, match="Unique"):
        study_grid((float("nan"),))


def test_do_not_treat_missing_optimisations_as_winners():
    factors = TARGET_FACTORS["flat"]
    rows = [
        {
            **case,
            "status": "NO_LOADABLE_SOLUTION_NOT_PROVEN_INFEASIBLE",
        }
        for case in study_grid(factors)
    ]
    report = compare_fidelity_rankings(rows, "flat", factors=factors)
    assert report["unresolved_factors"] == list(factors)
    assert report["confirmed_disagreements"] == 0


def test_archived_derived_config_is_valid_json_and_has_stable_hash(tmp_path):
    cfg = load_config(Path("configs/molten_salt_300c_flat.yaml"))
    target = tmp_path / "config.json"
    sha = write_derived_config(target, cfg)
    assert json.loads(target.read_text())["economics"]["storage_capex_eur_per_mwh"] == 26000
    assert len(sha) == 64
    with pytest.raises(FileExistsError):
        write_derived_config(target, cfg)
