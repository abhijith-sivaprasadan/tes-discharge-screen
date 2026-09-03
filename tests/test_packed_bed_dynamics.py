from __future__ import annotations

import dataclasses

import numpy as np
import pytest

from tes_screen.packed_bed_dynamics import (
    default_packed_bed_config,
    discharge_power_curve,
    simulate_discharge,
    volumetric_heat_transfer_coefficient,
)


def test_zero_draw_rate_and_zero_loss_keeps_outlet_at_initial_temperature() -> None:
    # B4 analytic check 1: with no flow, there is nothing to drive the bed
    # away from its (already-equilibrated) initial state, and this model has
    # no ambient loss term, so the outlet must sit exactly at T_max for the
    # whole duration.
    config = default_packed_bed_config()
    result = simulate_discharge(
        config,
        mass_flow_kg_per_s=0.0,
        initial_bed_temperature_c=400.0,
        inlet_temperature_c=320.0,
        duration_s=4 * 3600,
        n_steps=200,
    )
    assert np.allclose(result.trace["outlet_temperature_c"], 400.0, atol=1e-9)


def test_infinite_heat_transfer_coefficient_matches_well_mixed_tank_analytic_response() -> None:
    # B4 analytic check 2: a single-node bed (N=1) with h_v -> infinity
    # collapses fluid and solid into one lumped capacity, giving the
    # well-known well-mixed-tank exponential response
    #   T(t) = T_in + (T0 - T_in) * exp(-t / tau)
    #   tau = (eps*rho_f*cp_f + (1-eps)*rho_s*cp_s) * V / (mdot * cp_f)
    # Derived by hand from the same discrete balance the model solves (see
    # packed_bed_dynamics.py's module docstring); independent of the
    # implementation's own bookkeeping.
    config = dataclasses.replace(default_packed_bed_config(), n_nodes=1)
    config.validate()
    mass_flow = 2.0
    t0, t_in = 400.0, 320.0
    duration = 3 * 3600.0

    result = simulate_discharge(
        config,
        mass_flow_kg_per_s=mass_flow,
        initial_bed_temperature_c=t0,
        inlet_temperature_c=t_in,
        duration_s=duration,
        heat_transfer_coefficient_override_w_per_m3k=1e12,
        n_steps=4000,
    )

    volume = config.bed_length_m * config.cross_section_area_m2
    c_f = config.porosity * config.air_density_kg_per_m3 * config.air_specific_heat_j_per_kgk
    c_s = (
        (1 - config.porosity) * config.rock_density_kg_per_m3 * config.rock_specific_heat_j_per_kgk
    )
    tau = (c_f + c_s) * volume / (mass_flow * config.air_specific_heat_j_per_kgk)

    time_s = result.trace["time_s"].to_numpy()
    analytic = t_in + (t0 - t_in) * np.exp(-time_s / tau)
    numeric = result.trace["outlet_temperature_c"].to_numpy()
    assert np.allclose(numeric, analytic, rtol=1e-3, atol=1e-2)


def test_energy_conservation_holds_to_near_machine_precision() -> None:
    # B4 analytic check 3: total energy discharged (outlet enthalpy flow,
    # integrated) must equal the bed's own stored-energy loss exactly, since
    # this is an adiabatic model with no other sink. Checked at every
    # recorded timestep, not only at the end.
    config = default_packed_bed_config()
    result = simulate_discharge(
        config,
        mass_flow_kg_per_s=3.0,
        initial_bed_temperature_c=400.0,
        inlet_temperature_c=320.0,
        duration_s=8 * 3600,
        n_steps=800,
    )
    residual = result.trace["energy_conservation_residual_j"].abs()
    initial_energy = result.trace["bed_stored_energy_j"].iloc[0]
    assert (residual / initial_energy < 1e-9).all()


def test_outlet_temperature_declines_monotonically_during_discharge() -> None:
    # Physics a reader would expect: discharging a hotter-than-inlet bed can
    # only cool the outlet over time, never reheat it, since there is no
    # recharging and no source hotter than the initial state.
    config = default_packed_bed_config()
    result = simulate_discharge(
        config,
        mass_flow_kg_per_s=2.5,
        initial_bed_temperature_c=400.0,
        inlet_temperature_c=320.0,
        duration_s=10 * 3600,
        n_steps=500,
    )
    outlet = result.trace["outlet_temperature_c"].to_numpy()
    assert np.all(np.diff(outlet) <= 1e-9)


def test_higher_draw_rate_breaks_through_sooner() -> None:
    # Monotonicity: a faster draw should reach any given outlet temperature
    # at an earlier state of charge than a slower draw, since more fluid mass
    # has moved through the bed for the same stored-energy depletion.
    config = default_packed_bed_config()
    slow = simulate_discharge(
        config,
        1.0,
        initial_bed_temperature_c=400.0,
        inlet_temperature_c=320.0,
        duration_s=20 * 3600,
        n_steps=1000,
    )
    fast = simulate_discharge(
        config,
        5.0,
        initial_bed_temperature_c=400.0,
        inlet_temperature_c=320.0,
        duration_s=4 * 3600,
        n_steps=1000,
    )
    # process_temperature_c must sit strictly between inlet (320) and
    # initial (400) or the outlet asymptotes above it and never actually
    # reaches zero deliverable power.
    slow_curve = discharge_power_curve(slow, process_temperature_c=350.0)
    fast_curve = discharge_power_curve(fast, process_temperature_c=350.0)
    # SOC at which the outlet first drops below the process temperature.
    slow_breakthrough_soc = slow_curve.loc[
        slow_curve["deliverable_power_mw"] <= 1e-9, "state_of_charge"
    ]
    fast_breakthrough_soc = fast_curve.loc[
        fast_curve["deliverable_power_mw"] <= 1e-9, "state_of_charge"
    ]
    assert fast_breakthrough_soc.max() >= slow_breakthrough_soc.max() - 1e-6


def test_deliverable_power_never_negative_and_clips_below_process_temperature() -> None:
    config = default_packed_bed_config()
    result = simulate_discharge(
        config,
        3.0,
        initial_bed_temperature_c=400.0,
        inlet_temperature_c=320.0,
        duration_s=8 * 3600,
        n_steps=800,
    )
    curve = discharge_power_curve(result, process_temperature_c=350.0)
    assert (curve["deliverable_power_mw"] >= 0).all()
    below_process = curve["outlet_temperature_c"] < 350.0
    assert (curve.loc[below_process, "deliverable_power_mw"] == 0).all()


def test_volumetric_heat_transfer_coefficient_is_zero_at_zero_flow() -> None:
    config = default_packed_bed_config()
    assert volumetric_heat_transfer_coefficient(config, 0.0) == 0.0


def test_volumetric_heat_transfer_coefficient_increases_with_flow() -> None:
    config = default_packed_bed_config()
    low = volumetric_heat_transfer_coefficient(config, 0.1)
    high = volumetric_heat_transfer_coefficient(config, 1.0)
    assert high > low > 0


def test_negative_mass_flow_is_rejected() -> None:
    config = default_packed_bed_config()
    with pytest.raises(ValueError, match="nonnegative"):
        simulate_discharge(
            config,
            -1.0,
            initial_bed_temperature_c=400.0,
            inlet_temperature_c=320.0,
            duration_s=3600,
        )


def test_invalid_porosity_is_rejected() -> None:
    config = dataclasses.replace(default_packed_bed_config(), porosity=1.5)
    with pytest.raises(ValueError, match="porosity"):
        config.validate()
