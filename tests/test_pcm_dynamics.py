from __future__ import annotations

import numpy as np
import pytest

from tes_screen.discharge_curve import fit_piecewise_curve_from_power_curve
from tes_screen.pcm_dynamics import (
    PcmDynamicsConfig,
    default_pcm_config,
    discharge_power_curve,
    mass_flow_for_target_duration,
    reference_energy_capacity_mwh,
)

T_MAX_C = 330.0
T_MIN_C = 300.0
HTF_RETURN_C = 290.0
PROCESS_C = 300.0


@pytest.fixture(scope="module")
def config():
    return default_pcm_config()


def test_default_config_validates(config) -> None:
    config.validate()


def test_outlet_temperature_holds_at_the_melting_point_during_the_latent_regime(config) -> None:
    curve = discharge_power_curve(
        config, mass_flow_kg_per_s=5.0, t_max_c=T_MAX_C, t_min_c=T_MIN_C,
        htf_return_temperature_c=HTF_RETURN_C, process_temperature_c=PROCESS_C,
        delta_t_min_hot_side_c=0.0, n_points=2000,
    )
    near_melt = curve[np.isclose(curve["outlet_temperature_c"], config.melting_point_c, atol=1e-6)]
    assert len(near_melt) > 100  # a genuine plateau, not a single sample


def test_outlet_temperature_declines_monotonically_with_soc(config) -> None:
    curve = discharge_power_curve(
        config, mass_flow_kg_per_s=5.0, t_max_c=T_MAX_C, t_min_c=T_MIN_C,
        htf_return_temperature_c=HTF_RETURN_C, process_temperature_c=PROCESS_C,
        delta_t_min_hot_side_c=0.0,
    )
    outlet = curve["outlet_temperature_c"].to_numpy()
    assert np.all(np.diff(outlet) <= 1e-9)  # SOC descending -> outlet nonincreasing
    assert np.isclose(outlet[0], T_MAX_C)
    assert np.isclose(outlet[-1], T_MIN_C)


def test_deliverable_power_is_gated_below_the_process_requirement(config) -> None:
    # process_temperature_c == T_min_c here, so the quality gate should bind
    # somewhere in the subcooled tail, leaving storage_heat positive there
    # while deliverable_power is zero -- the same P0.2 distinction the
    # packed-bed model draws.
    curve = discharge_power_curve(
        config, mass_flow_kg_per_s=5.0, t_max_c=T_MAX_C, t_min_c=T_MIN_C,
        htf_return_temperature_c=HTF_RETURN_C, process_temperature_c=305.0,
        delta_t_min_hot_side_c=0.0,
    )
    gated_out = curve[curve["outlet_temperature_c"] < 305.0]
    assert len(gated_out) > 0
    assert (gated_out["deliverable_power_mw"] == 0).all()
    assert (gated_out["storage_heat_mw"] > 0).all()


def test_reference_energy_capacity_scales_with_reference_module_volume() -> None:
    small = PcmDynamicsConfig(
        melting_point_c=306.0, latent_heat_j_per_kg=177_000.0,
        solid_density_kg_per_m3=2257.0, solid_specific_heat_j_per_kgk=1095.0,
        liquid_specific_heat_j_per_kgk=1550.0, htf_specific_heat_j_per_kgk=1085.0,
        reference_module_volume_m3=10.0,
    )
    big = PcmDynamicsConfig(
        melting_point_c=306.0, latent_heat_j_per_kg=177_000.0,
        solid_density_kg_per_m3=2257.0, solid_specific_heat_j_per_kgk=1095.0,
        liquid_specific_heat_j_per_kgk=1550.0, htf_specific_heat_j_per_kgk=1085.0,
        reference_module_volume_m3=20.0,
    )
    e_small = reference_energy_capacity_mwh(small, T_MAX_C, T_MIN_C)
    e_big = reference_energy_capacity_mwh(big, T_MAX_C, T_MIN_C)
    assert np.isclose(e_big, 2 * e_small, rtol=1e-12)


@pytest.mark.parametrize("target_duration_hours", [2.0, 6.0, 12.0])
def test_mass_flow_for_target_duration_yields_the_requested_duration(
    config, target_duration_hours: float
) -> None:
    mass_flow = mass_flow_for_target_duration(
        config, target_duration_hours, T_MAX_C, T_MIN_C, HTF_RETURN_C
    )
    curve = discharge_power_curve(
        config, mass_flow_kg_per_s=mass_flow, t_max_c=T_MAX_C, t_min_c=T_MIN_C,
        htf_return_temperature_c=HTF_RETURN_C, process_temperature_c=PROCESS_C,
        delta_t_min_hot_side_c=0.0,
    )
    reference_energy = reference_energy_capacity_mwh(config, T_MAX_C, T_MIN_C)
    reference_power = curve["deliverable_power_mw"].iloc[0]
    assert np.isclose(reference_energy / reference_power, target_duration_hours, rtol=1e-9)


@pytest.mark.parametrize("n_segments", [3, 5, 8, 12, 20, 30])
def test_piecewise_fit_safety_is_checked_not_assumed(config, n_segments: int) -> None:
    # Unlike the packed bed and molten-salt curves, PCM's three-regime shape
    # is not globally concave: going from the flat latent plateau into the
    # rising superheat ramp as SOC increases past soc_a, the slope jumps
    # from 0 up to positive -- a convex corner, where a naive single-segment
    # chord could overestimate. But `limit_mw` takes the *minimum* over
    # every segment's own secant line extended across the whole domain, not
    # just the nominally-containing segment's: whenever a neighbouring
    # segment's breakpoints both land in the flat latent plateau (as they do
    # here whenever a segment doesn't itself straddle a regime boundary),
    # that segment's line is exactly the flat, correct plateau value
    # everywhere, and it wins the minimum wherever it is tighter. Verified
    # empirically at every segment count actually swept, not assumed from
    # concavity (which does not hold here) or from a single segment count.
    curve = discharge_power_curve(
        config, mass_flow_kg_per_s=5.0, t_max_c=T_MAX_C, t_min_c=T_MIN_C,
        htf_return_temperature_c=HTF_RETURN_C, process_temperature_c=PROCESS_C,
        delta_t_min_hot_side_c=0.0, n_points=2000,
    )
    reference_energy = reference_energy_capacity_mwh(config, T_MAX_C, T_MIN_C)
    fitted = fit_piecewise_curve_from_power_curve(curve, reference_energy, n_segments=n_segments)
    e_cap = fitted.reference_energy_capacity_mwh
    level = curve["state_of_charge"].to_numpy() * e_cap
    true_power = curve["deliverable_power_mw"].to_numpy()
    limits = np.array([fitted.limit_mw(lv, e_cap) for lv in level])
    overestimate = float(max((limits - true_power).max(), 0.0))
    assert overestimate < 1e-9, f"n_segments={n_segments}: overestimate {overestimate} MW"


def test_rejects_melting_point_outside_the_temperature_band() -> None:
    config = default_pcm_config()
    with pytest.raises(ValueError, match="melting_point_c"):
        discharge_power_curve(
            config, mass_flow_kg_per_s=5.0, t_max_c=305.0, t_min_c=300.0,
            htf_return_temperature_c=290.0, process_temperature_c=300.0,
            delta_t_min_hot_side_c=0.0,
        )
