from __future__ import annotations

import numpy as np
import pytest

from tes_screen.discharge_curve import fit_piecewise_curve_from_power_curve
from tes_screen.molten_salt_dynamics import (
    MoltenSaltDynamicsConfig,
    default_molten_salt_config,
    discharge_power_curve,
    mass_flow_for_target_duration,
    reference_energy_capacity_mwh,
)

HOT_C = 565.0
COLD_C = 290.0
PROCESS_C = 300.0


@pytest.fixture(scope="module")
def config():
    return default_molten_salt_config()


def test_default_config_validates(config) -> None:
    config.validate()


def test_outlet_temperature_is_constant_at_the_hot_tank_temperature(config) -> None:
    # The whole physical premise of a two-tank store: no thermocline, so no
    # temperature degradation with state of charge, at any state of charge.
    curve = discharge_power_curve(
        config, mass_flow_kg_per_s=5.0,
        hot_tank_temperature_c=HOT_C, cold_tank_temperature_c=COLD_C,
        process_temperature_c=PROCESS_C, delta_t_min_hot_side_c=0.0,
    )
    assert (curve["outlet_temperature_c"] == HOT_C).all()


def test_power_is_rated_above_the_heel_and_tapers_to_zero_below_it(config) -> None:
    curve = discharge_power_curve(
        config, mass_flow_kg_per_s=5.0,
        hot_tank_temperature_c=HOT_C, cold_tank_temperature_c=COLD_C,
        process_temperature_c=PROCESS_C, delta_t_min_hot_side_c=0.0,
    )
    above_heel = curve[curve["state_of_charge"] >= config.heel_fraction]
    rated = curve["deliverable_power_mw"].max()
    assert np.allclose(above_heel["deliverable_power_mw"], rated, rtol=1e-9)
    assert curve["deliverable_power_mw"].iloc[-1] == 0.0
    # Monotonically nonincreasing as SOC falls, never negative.
    assert (np.diff(curve["deliverable_power_mw"].to_numpy()) <= 1e-12).all()
    assert (curve["deliverable_power_mw"] >= 0).all()


def test_rejects_hot_tank_temperature_at_or_below_required_outlet(config) -> None:
    with pytest.raises(ValueError, match="hot_tank_temperature_c"):
        discharge_power_curve(
            config, mass_flow_kg_per_s=5.0,
            hot_tank_temperature_c=300.0, cold_tank_temperature_c=COLD_C,
            process_temperature_c=300.0, delta_t_min_hot_side_c=0.0,
        )


def test_reference_energy_capacity_scales_with_reference_tank_volume() -> None:
    small = MoltenSaltDynamicsConfig(
        salt_density_kg_per_m3=1900.0, salt_specific_heat_j_per_kgk=1550.0,
        heel_fraction=0.05, reference_tank_volume_m3=10.0,
    )
    big = MoltenSaltDynamicsConfig(
        salt_density_kg_per_m3=1900.0, salt_specific_heat_j_per_kgk=1550.0,
        heel_fraction=0.05, reference_tank_volume_m3=20.0,
    )
    e_small = reference_energy_capacity_mwh(small, HOT_C, COLD_C)
    e_big = reference_energy_capacity_mwh(big, HOT_C, COLD_C)
    assert np.isclose(e_big, 2 * e_small, rtol=1e-12)


@pytest.mark.parametrize("target_duration_hours", [2.0, 6.0, 12.0])
def test_mass_flow_for_target_duration_yields_the_requested_duration(
    config, target_duration_hours: float
) -> None:
    mass_flow = mass_flow_for_target_duration(config, target_duration_hours, HOT_C, COLD_C)
    curve = discharge_power_curve(
        config, mass_flow_kg_per_s=mass_flow,
        hot_tank_temperature_c=HOT_C, cold_tank_temperature_c=COLD_C,
        process_temperature_c=PROCESS_C, delta_t_min_hot_side_c=0.0,
    )
    reference_energy = reference_energy_capacity_mwh(config, HOT_C, COLD_C)
    reference_power = curve["deliverable_power_mw"].iloc[0]
    assert np.isclose(reference_energy / reference_power, target_duration_hours, rtol=1e-9)


def test_fitted_curve_is_safe_against_the_analytic_data(config) -> None:
    curve = discharge_power_curve(
        config, mass_flow_kg_per_s=5.0,
        hot_tank_temperature_c=HOT_C, cold_tank_temperature_c=COLD_C,
        process_temperature_c=PROCESS_C, delta_t_min_hot_side_c=0.0,
    )
    reference_energy = reference_energy_capacity_mwh(config, HOT_C, COLD_C)
    fitted = fit_piecewise_curve_from_power_curve(curve, reference_energy, n_segments=5)
    e_cap = fitted.reference_energy_capacity_mwh
    level = curve["state_of_charge"].to_numpy() * e_cap
    true_power = curve["deliverable_power_mw"].to_numpy()
    limits = np.array([fitted.limit_mw(lv, e_cap) for lv in level])
    # Never overestimates (the LP must never be told it can discharge more
    # than the store can actually deliver at that level).
    assert (limits <= true_power + 1e-6).all()


def test_mass_flow_for_target_duration_rejects_non_positive_duration(config) -> None:
    with pytest.raises(ValueError, match="target_duration_hours"):
        mass_flow_for_target_duration(config, 0.0, HOT_C, COLD_C)
