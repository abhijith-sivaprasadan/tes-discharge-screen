from pathlib import Path

from scripts.run_technology_reoptimisation import (
    FACTORS,
    PHYSICAL_FACTORS,
    analyse,
    modify_config,
    registered_design,
)
from tes_screen.config import load_config


def test_registered_design_and_single_axis():
    cases = registered_design()
    assert len(cases) == 2 * (1 + len(FACTORS) - 1 + len(PHYSICAL_FACTORS))
    assert len({(c["technology"], c["axis"], c["factor"]) for c in cases}) == len(cases)


def test_cost_perturbation_does_not_change_physics():
    original = load_config(Path("configs/packed_bed_300c_flat.yaml"))
    changed = modify_config(original, "storage_capex", 1.5)
    assert changed.storage == original.storage
    assert changed.economics.storage_capex_eur_per_mwh == 1.5 * (
        original.economics.storage_capex_eur_per_mwh
    )


def test_physical_perturbation_does_not_change_economics():
    original = load_config(Path("configs/packed_bed_300c_flat.yaml"))
    changed = modify_config(original, "standing_loss", 2.0)
    assert changed.economics == original.economics
    assert changed.storage.standing_loss_fraction_per_hour == 0.002


def test_flip_check_uses_full_resolved_objectives_without_interpolation():
    rows = [
        {"technology": "packed_bed", "status": "OPTIMAL_VERIFIED", "axis": "control", "factor": 1.0, "total_cost_eur": 100},
        {"technology": "molten_salt", "status": "OPTIMAL_VERIFIED", "axis": "control", "factor": 1.0, "total_cost_eur": 110},
        {"technology": "packed_bed", "status": "OPTIMAL_VERIFIED", "axis": "storage_capex", "factor": 2.0, "total_cost_eur": 120},
    ]
    result = analyse(rows, "flat")
    assert result["control_winner"] == "packed_bed"
    assert result["comparisons"][-1]["ranking_flipped_from_original_controls"] is True
