from __future__ import annotations

import numpy as np
import pytest

from tes_screen.discharge_curve import fit_piecewise_discharge_curve
from tes_screen.packed_bed_dynamics import (
    default_packed_bed_config,
    discharge_power_curve,
    scale_parallel_bed,
    simulate_discharge,
    volumetric_heat_transfer_coefficient,
)

HOT_C = 400.0
RETURN_C = 320.0
PROCESS_C = 300.0
REFERENCE_MASS_FLOW_KG_PER_S = 3.0
DURATION_S = 20 * 3600.0
N_STEPS = 1000
SCALE_FACTORS = [0.25, 0.5, 1.0, 2.0, 4.0]


@pytest.fixture(scope="module")
def reference_config():
    return default_packed_bed_config()


def test_scale_parallel_bed_rejects_non_positive_factor(reference_config) -> None:
    with pytest.raises(ValueError, match="scale_factor"):
        scale_parallel_bed(reference_config, REFERENCE_MASS_FLOW_KG_PER_S, 0.0)
    with pytest.raises(ValueError, match="scale_factor"):
        scale_parallel_bed(reference_config, REFERENCE_MASS_FLOW_KG_PER_S, -1.0)


@pytest.mark.parametrize("scale_factor", SCALE_FACTORS)
def test_scale_parallel_bed_holds_everything_but_area_and_mass_flow_fixed(
    reference_config, scale_factor: float
) -> None:
    scaled_config, scaled_mass_flow = scale_parallel_bed(
        reference_config, REFERENCE_MASS_FLOW_KG_PER_S, scale_factor
    )
    assert scaled_config.bed_length_m == reference_config.bed_length_m
    assert scaled_config.porosity == reference_config.porosity
    assert scaled_config.particle_diameter_m == reference_config.particle_diameter_m
    assert scaled_config.n_nodes == reference_config.n_nodes
    assert scaled_config.rock_density_kg_per_m3 == reference_config.rock_density_kg_per_m3
    assert np.isclose(
        scaled_config.cross_section_area_m2,
        reference_config.cross_section_area_m2 * scale_factor,
    )
    assert np.isclose(scaled_mass_flow, REFERENCE_MASS_FLOW_KG_PER_S * scale_factor)


@pytest.mark.parametrize("scale_factor", SCALE_FACTORS)
def test_scale_parallel_bed_preserves_mass_flux_exactly(
    reference_config, scale_factor: float
) -> None:
    reference_flux = REFERENCE_MASS_FLOW_KG_PER_S / reference_config.cross_section_area_m2
    scaled_config, scaled_mass_flow = scale_parallel_bed(
        reference_config, REFERENCE_MASS_FLOW_KG_PER_S, scale_factor
    )
    scaled_flux = scaled_mass_flow / scaled_config.cross_section_area_m2
    assert np.isclose(scaled_flux, reference_flux, rtol=1e-12)


@pytest.mark.parametrize("scale_factor", SCALE_FACTORS)
def test_scale_parallel_bed_preserves_the_heat_transfer_coefficient(
    reference_config, scale_factor: float
) -> None:
    # h_v depends only on mass flux and fixed bed/material properties
    # (volumetric_heat_transfer_coefficient never reads cross_section_area_m2
    # directly); since mass flux is exactly preserved, h_v must be too.
    reference_flux = REFERENCE_MASS_FLOW_KG_PER_S / reference_config.cross_section_area_m2
    reference_h_v = volumetric_heat_transfer_coefficient(reference_config, reference_flux)
    scaled_config, scaled_mass_flow = scale_parallel_bed(
        reference_config, REFERENCE_MASS_FLOW_KG_PER_S, scale_factor
    )
    scaled_flux = scaled_mass_flow / scaled_config.cross_section_area_m2
    scaled_h_v = volumetric_heat_transfer_coefficient(scaled_config, scaled_flux)
    assert np.isclose(scaled_h_v, reference_h_v, rtol=1e-12)


@pytest.fixture(scope="module")
def reference_power_curve(reference_config):
    result = simulate_discharge(
        reference_config,
        mass_flow_kg_per_s=REFERENCE_MASS_FLOW_KG_PER_S,
        initial_bed_temperature_c=HOT_C,
        inlet_temperature_c=RETURN_C,
        duration_s=DURATION_S,
        n_steps=N_STEPS,
    )
    return discharge_power_curve(result, PROCESS_C, delta_t_min_hot_side_c=0.0)


@pytest.mark.parametrize("scale_factor", SCALE_FACTORS)
def test_normalized_discharge_curve_collapses_across_scale_factors(
    reference_config, reference_power_curve, scale_factor: float
) -> None:
    # P1.2's exit criterion: the *normalized* curve (state of charge; power
    # as a fraction of that run's own full-charge reference power) should
    # match the reference run's, to floating-point precision, at every
    # scale factor -- not merely approximately. Same duration_s/n_steps for
    # every run means the same time grid, so state_of_charge(t) should also
    # match row for row (no interpolation needed, or hidden behind one).
    scaled_config, scaled_mass_flow = scale_parallel_bed(
        reference_config, REFERENCE_MASS_FLOW_KG_PER_S, scale_factor
    )
    result = simulate_discharge(
        scaled_config,
        mass_flow_kg_per_s=scaled_mass_flow,
        initial_bed_temperature_c=HOT_C,
        inlet_temperature_c=RETURN_C,
        duration_s=DURATION_S,
        n_steps=N_STEPS,
    )
    curve = discharge_power_curve(result, PROCESS_C, delta_t_min_hot_side_c=0.0)

    reference_soc = reference_power_curve["state_of_charge"].to_numpy()
    scaled_soc = curve["state_of_charge"].to_numpy()
    assert np.allclose(scaled_soc, reference_soc, atol=1e-9)

    reference_power = reference_power_curve["deliverable_power_mw"]
    reference_fraction = (reference_power / reference_power.iloc[0]).to_numpy()
    scaled_power = curve["deliverable_power_mw"]
    scaled_fraction = (scaled_power / scaled_power.iloc[0]).to_numpy()
    max_deviation = float(np.abs(scaled_fraction - reference_fraction).max())
    assert max_deviation < 1e-6, f"scale_factor={scale_factor}: max deviation {max_deviation}"


def test_fitted_curve_k_scales_with_area_at_fixed_mass_flux(reference_config) -> None:
    # A direct check on the quantity dispatch.py's LP actually uses: k =
    # P_reference/E_reference (the piecewise curve's own scale-independent
    # "duration" ratio) should be identical at every scale factor, since
    # both P_reference and E_reference are individually proportional to A.
    ks = []
    for scale_factor in SCALE_FACTORS:
        scaled_config, scaled_mass_flow = scale_parallel_bed(
            reference_config, REFERENCE_MASS_FLOW_KG_PER_S, scale_factor
        )
        result = simulate_discharge(
            scaled_config,
            mass_flow_kg_per_s=scaled_mass_flow,
            initial_bed_temperature_c=HOT_C,
            inlet_temperature_c=RETURN_C,
            duration_s=DURATION_S,
            n_steps=N_STEPS,
        )
        curve = fit_piecewise_discharge_curve(
            result, PROCESS_C, delta_t_min_hot_side_c=0.0, n_segments=5
        )
        ks.append(curve.k_mw_per_mwh)
    assert np.allclose(ks, ks[0], rtol=1e-9)
