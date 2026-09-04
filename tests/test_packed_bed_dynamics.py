from __future__ import annotations

import dataclasses

import numpy as np
import pytest

from tes_screen.packed_bed_dynamics import (
    bed_stored_energy_j,
    default_packed_bed_config,
    discharge_power_curve,
    flow_diagnostics,
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
    slow_curve = discharge_power_curve(
        slow, process_temperature_c=350.0, delta_t_min_hot_side_c=0.0
    )
    fast_curve = discharge_power_curve(
        fast, process_temperature_c=350.0, delta_t_min_hot_side_c=0.0
    )
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
    curve = discharge_power_curve(result, process_temperature_c=350.0, delta_t_min_hot_side_c=0.0)
    assert (curve["deliverable_power_mw"] >= 0).all()
    below_process = curve["outlet_temperature_c"] < 350.0
    assert (curve.loc[below_process, "deliverable_power_mw"] == 0).all()


# --- P0.2: temperature semantics and the useful-power definition -------------


def test_fully_depleted_bed_reports_zero_net_storage_heat() -> None:
    # Roadmap P0.2 acceptance test 1: a bed discharged long enough that the
    # outlet has relaxed onto T_return must report exactly zero storage_heat,
    # not a small negative number that happens to get clipped -- the same
    # reference (T_return) the bed's own stored-energy accounting uses.
    config = default_packed_bed_config()
    result = simulate_discharge(
        config,
        mass_flow_kg_per_s=3.0,
        initial_bed_temperature_c=400.0,
        inlet_temperature_c=320.0,
        duration_s=200 * 3600,  # far past breakthrough: outlet relaxes onto T_return
        n_steps=4000,
    )
    curve = discharge_power_curve(result, process_temperature_c=300.0, delta_t_min_hot_side_c=0.0)
    assert np.isclose(curve["outlet_temperature_c"].iloc[-1], 320.0, atol=0.5)
    assert np.isclose(curve["storage_heat_mw"].iloc[-1], 0.0, atol=1e-6)


def test_low_grade_heat_below_required_outlet_is_unusable_but_not_absent() -> None:
    # Roadmap P0.2 acceptance test 2: once the outlet falls below
    # T_required_out = T_process + delta_T_min_hot_side, the process cannot
    # be served directly (deliverable_power_mw == 0) even though the bed
    # still holds recoverable sensible energy above T_return
    # (storage_heat_mw > 0). The two must diverge in exactly this window, or
    # the quality gate isn't doing anything the plain T_return reference
    # didn't already do.
    config = default_packed_bed_config()
    result = simulate_discharge(
        config,
        mass_flow_kg_per_s=3.0,
        initial_bed_temperature_c=400.0,
        inlet_temperature_c=320.0,
        duration_s=30 * 3600,
        n_steps=1500,
    )
    curve = discharge_power_curve(result, process_temperature_c=350.0, delta_t_min_hot_side_c=5.0)
    low_grade = (curve["outlet_temperature_c"] < 355.0) & (curve["outlet_temperature_c"] > 320.0)
    assert low_grade.any(), "test setup should reach the low-grade window"
    assert (curve.loc[low_grade, "deliverable_power_mw"] == 0).all()
    assert (curve.loc[low_grade, "storage_heat_mw"] > 0).all()


def test_integrated_storage_heat_matches_the_beds_own_stored_energy_drop() -> None:
    # Roadmap P0.2 acceptance test 3: energy removed from the dynamic bed
    # and the integrated Q_storage must be consistent, now that both are
    # referenced to T_return. This is a stronger, independent check than
    # simulate_discharge's own energy_conservation_residual_j (which never
    # mentions discharge_power_curve at all): it confirms the *downstream*
    # deliverable-power calculation, not just the simulation's internal
    # bookkeeping, actually agrees with the bed's own energy accounting.
    config = default_packed_bed_config()
    # n_steps=3000, not the usual 800: this test's own numerical error is a
    # trapezoidal integration of storage_heat_mw against time, coarser than
    # simulate_discharge's own per-step energy_conservation_residual_j check,
    # so it needs finer time resolution to converge to the same tolerance.
    result = simulate_discharge(
        config,
        mass_flow_kg_per_s=3.0,
        initial_bed_temperature_c=400.0,
        inlet_temperature_c=320.0,
        duration_s=8 * 3600,
        n_steps=3000,
    )
    curve = discharge_power_curve(result, process_temperature_c=300.0, delta_t_min_hot_side_c=0.0)
    time_s = curve["time_s"].to_numpy()
    storage_heat_w = curve["storage_heat_mw"].to_numpy() * 1e6
    integrated_j = np.trapezoid(storage_heat_w, time_s)
    bed_energy_drop_j = (
        result.trace["bed_stored_energy_j"].iloc[0] - result.trace["bed_stored_energy_j"].iloc[-1]
    )
    assert np.isclose(integrated_j, bed_energy_drop_j, rtol=1e-3)


def test_discharge_power_curve_rejects_negative_hot_side_approach() -> None:
    config = default_packed_bed_config()
    result = simulate_discharge(
        config,
        mass_flow_kg_per_s=3.0,
        initial_bed_temperature_c=400.0,
        inlet_temperature_c=320.0,
        duration_s=3600,
        n_steps=50,
    )
    with pytest.raises(ValueError, match="delta_t_min_hot_side_c"):
        discharge_power_curve(result, process_temperature_c=300.0, delta_t_min_hot_side_c=-1.0)


def test_volumetric_heat_transfer_coefficient_is_zero_at_zero_flow() -> None:
    config = default_packed_bed_config()
    assert volumetric_heat_transfer_coefficient(config, 0.0) == 0.0


def test_volumetric_heat_transfer_coefficient_increases_with_flow() -> None:
    config = default_packed_bed_config()
    low = volumetric_heat_transfer_coefficient(config, 0.1)
    high = volumetric_heat_transfer_coefficient(config, 1.0)
    assert high > low > 0


def test_flow_diagnostics_is_zero_at_zero_flow() -> None:
    config = default_packed_bed_config()
    diagnostics = flow_diagnostics(config, 0.0)
    assert diagnostics.reynolds == 0.0
    assert diagnostics.prandtl == 0.0
    assert diagnostics.nusselt == 0.0
    assert diagnostics.volumetric_heat_transfer_coefficient_w_per_m3k == 0.0


def test_flow_diagnostics_h_v_matches_volumetric_heat_transfer_coefficient() -> None:
    # roadmap P2.1 needs Re/Pr/Nu recorded alongside h_v; flow_diagnostics
    # factors them out of the same correlation volumetric_heat_transfer_
    # coefficient already used, so the two must agree exactly, not just
    # approximately -- one computation, two views of it.
    config = default_packed_bed_config()
    mass_flux = 0.5
    diagnostics = flow_diagnostics(config, mass_flux)
    assert diagnostics.volumetric_heat_transfer_coefficient_w_per_m3k == (
        volumetric_heat_transfer_coefficient(config, mass_flux)
    )


def test_flow_diagnostics_nusselt_matches_wakao_kaguei_correlation() -> None:
    # Nu = 2 + 1.1*Re^0.6*Pr^(1/3); check the reported Re/Pr actually
    # reproduce the reported Nu via the correlation's own formula, not just
    # that some internally-consistent numbers came back.
    config = default_packed_bed_config()
    diagnostics = flow_diagnostics(config, 0.5)
    expected_nusselt = 2 + 1.1 * diagnostics.reynolds**0.6 * diagnostics.prandtl ** (1 / 3)
    assert diagnostics.nusselt == pytest.approx(expected_nusselt, rel=1e-12)


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


# --- P0.3: non-uniform initial temperature fields -----------------------------


def test_simulate_discharge_accepts_a_nonuniform_initial_temperature_field() -> None:
    # A non-uniform field must actually be applied, not silently collapsed to
    # its mean or otherwise ignored: the t=0 outlet reading (node N-1's fluid
    # temperature) must equal exactly what was placed there, and the t=0
    # stored energy must match the field's own energy content, not a
    # uniform-bed approximation of it.
    config = default_packed_bed_config()
    field = np.linspace(320.0, 400.0, config.n_nodes)
    result = simulate_discharge(
        config,
        mass_flow_kg_per_s=2.0,
        initial_bed_temperature_c=field,
        inlet_temperature_c=320.0,
        duration_s=1800,
        n_steps=100,
    )
    assert np.isclose(result.trace["outlet_temperature_c"].iloc[0], field[-1], atol=1e-9)
    expected_energy = bed_stored_energy_j(config, field, field, 320.0)
    assert np.isclose(result.trace["bed_stored_energy_j"].iloc[0], expected_energy, rtol=1e-9)


def test_simulate_discharge_rejects_a_wrongly_shaped_initial_temperature_field() -> None:
    config = default_packed_bed_config()
    field = np.full(config.n_nodes + 1, 350.0)
    with pytest.raises(ValueError, match="initial_bed_temperature_c"):
        simulate_discharge(
            config,
            mass_flow_kg_per_s=2.0,
            initial_bed_temperature_c=field,
            inlet_temperature_c=320.0,
            duration_s=1800,
            n_steps=100,
        )
