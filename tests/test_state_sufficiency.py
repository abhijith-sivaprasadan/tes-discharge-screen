from __future__ import annotations

import numpy as np
import pytest

from tes_screen.packed_bed_dynamics import default_packed_bed_config
from tes_screen.state_sufficiency import (
    achieved_energy_fraction,
    smeared_field,
    step_field,
    uniform_field,
)

HOT_C = 400.0
RETURN_C = 320.0


@pytest.fixture(scope="module")
def config():
    return default_packed_bed_config()


@pytest.mark.parametrize("energy_fraction", [0.2, 0.5, 0.8])
def test_uniform_field_achieves_target_energy_fraction(config, energy_fraction: float) -> None:
    field = uniform_field(config, energy_fraction, HOT_C, RETURN_C)
    achieved = achieved_energy_fraction(config, field, HOT_C, RETURN_C)
    assert np.isclose(achieved, energy_fraction, rtol=1e-9)


@pytest.mark.parametrize("energy_fraction", [0.2, 0.5, 0.8])
@pytest.mark.parametrize("hot_side", ["inlet", "outlet"])
def test_step_field_achieves_target_energy_fraction(
    config, energy_fraction: float, hot_side: str
) -> None:
    field = step_field(config, energy_fraction, HOT_C, RETURN_C, hot_side=hot_side)
    achieved = achieved_energy_fraction(config, field, HOT_C, RETURN_C)
    # Discretisation (round(energy_fraction * n_nodes)) is the only source of
    # error here; loose enough tolerance to absorb it without hiding a real bug.
    assert np.isclose(achieved, energy_fraction, atol=1.0 / config.n_nodes)


@pytest.mark.parametrize("energy_fraction", [0.2, 0.5, 0.8])
def test_smeared_field_achieves_target_energy_fraction(config, energy_fraction: float) -> None:
    field = smeared_field(config, energy_fraction, HOT_C, RETURN_C)
    achieved = achieved_energy_fraction(config, field, HOT_C, RETURN_C)
    assert np.isclose(achieved, energy_fraction, rtol=1e-9)


def test_step_field_orientations_have_matching_energy_but_different_shape(config) -> None:
    # The core P0.3 construction: same total energy, genuinely different
    # spatial arrangement (mirror images of each other), for energy
    # fractions away from the symmetric midpoint.
    inlet_hot = step_field(config, 0.3, HOT_C, RETURN_C, hot_side="inlet")
    outlet_hot = step_field(config, 0.3, HOT_C, RETURN_C, hot_side="outlet")
    assert np.isclose(
        achieved_energy_fraction(config, inlet_hot, HOT_C, RETURN_C),
        achieved_energy_fraction(config, outlet_hot, HOT_C, RETURN_C),
        atol=1e-9,
    )
    assert not np.allclose(inlet_hot, outlet_hot)
    # Mirror images of each other along the bed.
    assert np.allclose(inlet_hot, outlet_hot[::-1])


def test_smeared_field_stays_strictly_within_the_two_physical_bounds(config) -> None:
    field = smeared_field(config, 0.5, HOT_C, RETURN_C, spread_fraction=0.9)
    assert field.min() > RETURN_C
    assert field.max() < HOT_C


@pytest.mark.parametrize(
    "constructor_kwargs",
    [
        {"energy_fraction": 0.0},
        {"energy_fraction": 1.0},
        {"energy_fraction": -0.1},
        {"energy_fraction": 1.1},
    ],
)
def test_uniform_field_rejects_out_of_range_energy_fraction(config, constructor_kwargs) -> None:
    with pytest.raises(ValueError, match="energy_fraction"):
        uniform_field(
            config, hot_temperature_c=HOT_C, return_temperature_c=RETURN_C, **constructor_kwargs
        )


def test_step_field_rejects_invalid_hot_side(config) -> None:
    with pytest.raises(ValueError, match="hot_side"):
        step_field(config, 0.5, HOT_C, RETURN_C, hot_side="middle")


def test_field_constructors_reject_hot_temperature_at_or_below_return(config) -> None:
    with pytest.raises(ValueError, match="hot_temperature_c"):
        uniform_field(config, 0.5, hot_temperature_c=300.0, return_temperature_c=320.0)


def test_smeared_field_rejects_out_of_range_spread_fraction(config) -> None:
    with pytest.raises(ValueError, match="spread_fraction"):
        smeared_field(config, 0.5, HOT_C, RETURN_C, spread_fraction=1.5)
