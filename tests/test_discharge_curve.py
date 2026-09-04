from __future__ import annotations

import numpy as np
import pytest

from tes_screen.discharge_curve import (
    fit_piecewise_discharge_curve,
    mass_flow_for_target_duration,
    piecewise_curve_to_frame,
    verify_piecewise_curve_is_safe,
)
from tes_screen.packed_bed_dynamics import default_packed_bed_config, simulate_discharge


@pytest.fixture(scope="module")
def reference_discharge():
    config = default_packed_bed_config()
    return simulate_discharge(
        config,
        mass_flow_kg_per_s=3.0,
        initial_bed_temperature_c=400.0,
        inlet_temperature_c=320.0,
        duration_s=30 * 3600,
        n_steps=1500,
    )


@pytest.mark.parametrize("n_segments", [3, 5, 8, 12])
def test_piecewise_fit_never_overestimates_the_true_curve(
    reference_discharge, n_segments: int
) -> None:
    # Safety property, not assumed from the construction: verified against
    # the underlying data for a range of segment counts. The construction is
    # exact for concave functions and this curve is empirically concave
    # (flat near full charge, steepening toward depletion); this test is
    # what actually establishes that, not a theoretical argument alone.
    curve = fit_piecewise_discharge_curve(
        reference_discharge, process_temperature_c=300.0, n_segments=n_segments
    )
    safety = verify_piecewise_curve_is_safe(curve, reference_discharge, process_temperature_c=300.0)
    assert safety["max_overestimate_mw"] < 1e-9


def test_more_segments_reduces_the_approximation_error(reference_discharge) -> None:
    # Spec C1: "check whether more [segments] changes the answer and record
    # that check." More segments should track the true curve more closely,
    # not less.
    errors = []
    for n in (3, 5, 8, 12):
        curve = fit_piecewise_discharge_curve(
            reference_discharge, process_temperature_c=300.0, n_segments=n
        )
        safety = verify_piecewise_curve_is_safe(
            curve, reference_discharge, process_temperature_c=300.0
        )
        errors.append(safety["mean_absolute_error_mw"])
    assert all(later <= earlier + 1e-9 for earlier, later in zip(errors, errors[1:], strict=False))


def test_fitted_curve_matches_breakpoints_exactly(reference_discharge) -> None:
    curve = fit_piecewise_discharge_curve(
        reference_discharge, process_temperature_c=300.0, n_segments=5
    )
    e_cap = curve.reference_energy_capacity_mwh
    for soc, frac in zip(curve.soc_breakpoints, curve.power_fraction_breakpoints, strict=True):
        expected = frac * curve.reference_rated_power_mw
        actual = curve.limit_mw(soc * e_cap, e_cap)
        assert np.isclose(actual, expected, atol=1e-6, rtol=1e-6)


def test_limit_scales_linearly_with_e_cap_at_fixed_soc(reference_discharge) -> None:
    # This is the property that keeps the LP linear: at a fixed
    # state-of-charge fraction, doubling E_cap must exactly double the
    # allowed discharge power (same duration ratio, twice the scale).
    curve = fit_piecewise_discharge_curve(
        reference_discharge, process_temperature_c=300.0, n_segments=5
    )
    e_cap = curve.reference_energy_capacity_mwh
    soc = 0.4
    base = curve.limit_mw(soc * e_cap, e_cap)
    doubled = curve.limit_mw(soc * (2 * e_cap), 2 * e_cap)
    assert np.isclose(doubled, 2 * base, rtol=1e-9)


def test_rejects_non_positive_segment_count(reference_discharge) -> None:
    with pytest.raises(ValueError, match="n_segments"):
        fit_piecewise_discharge_curve(
            reference_discharge, process_temperature_c=300.0, n_segments=0
        )


def test_piecewise_curve_to_frame_round_trips_breakpoints(reference_discharge) -> None:
    curve = fit_piecewise_discharge_curve(
        reference_discharge, process_temperature_c=300.0, n_segments=5
    )
    frame = piecewise_curve_to_frame(curve)
    assert len(frame) == 6
    assert list(frame["state_of_charge"]) == list(curve.soc_breakpoints)


@pytest.mark.parametrize("target_duration_hours", [2.0, 4.0, 8.0])
def test_mass_flow_for_target_duration_yields_a_curve_matching_the_requested_tau(
    target_duration_hours: float,
) -> None:
    # C2's matched-sizing fix (roadmap P0.1): re-simulating and refitting at
    # the solved-for mass flow must produce a curve whose own k =
    # P_reference/E_reference equals 1/tau to solver tolerance, since
    # dispatch.py's duration_matched branch enforces exactly this equality
    # before accepting a curve.
    bed_config = default_packed_bed_config()
    mass_flow = mass_flow_for_target_duration(
        bed_config,
        target_duration_hours=target_duration_hours,
        initial_bed_temperature_c=400.0,
        inlet_temperature_c=320.0,
        process_temperature_c=300.0,
    )
    result = simulate_discharge(
        bed_config,
        mass_flow_kg_per_s=mass_flow,
        initial_bed_temperature_c=400.0,
        inlet_temperature_c=320.0,
        duration_s=target_duration_hours * 2 * 3600,
        n_steps=1500,
    )
    curve = fit_piecewise_discharge_curve(result, process_temperature_c=300.0, n_segments=5)
    assert np.isclose(curve.k_mw_per_mwh, 1.0 / target_duration_hours, rtol=1e-6)


def test_mass_flow_for_target_duration_scales_inversely_with_duration() -> None:
    # E_reference is independent of mass flow for this bed model (only
    # geometry/material/temperatures); P_reference = k*E_reference scales
    # linearly with mass flow, so the solved mass flow must scale as 1/tau.
    bed_config = default_packed_bed_config()
    flow_2h = mass_flow_for_target_duration(
        bed_config,
        target_duration_hours=2.0,
        initial_bed_temperature_c=400.0,
        inlet_temperature_c=320.0,
        process_temperature_c=300.0,
    )
    flow_4h = mass_flow_for_target_duration(
        bed_config,
        target_duration_hours=4.0,
        initial_bed_temperature_c=400.0,
        inlet_temperature_c=320.0,
        process_temperature_c=300.0,
    )
    assert np.isclose(flow_2h, 2 * flow_4h, rtol=1e-9)


def test_mass_flow_for_target_duration_rejects_non_positive_duration() -> None:
    bed_config = default_packed_bed_config()
    with pytest.raises(ValueError, match="target_duration_hours"):
        mass_flow_for_target_duration(
            bed_config,
            target_duration_hours=0.0,
            initial_bed_temperature_c=400.0,
            inlet_temperature_c=320.0,
            process_temperature_c=300.0,
        )


def test_mass_flow_for_target_duration_rejects_process_temperature_at_or_above_bed() -> None:
    bed_config = default_packed_bed_config()
    with pytest.raises(ValueError, match="initial_bed_temperature_c"):
        mass_flow_for_target_duration(
            bed_config,
            target_duration_hours=4.0,
            initial_bed_temperature_c=400.0,
            inlet_temperature_c=320.0,
            process_temperature_c=400.0,
        )
