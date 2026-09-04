"""Piecewise-linear discharge-limit construction: Phase C's C1.

Converts a Phase B discharge curve (deliverable power vs. state of charge, at
one reference bed size and draw rate) into a small set of fixed linear
coefficients such that, for any storage energy capacity E_cap scaled from the
same reference bed design (same power/energy "duration" ratio
k = P_rated_reference / E_cap_reference), the constraint

    p_dis[t] <= a_i * level[t] + b_i * E_cap      for every segment i

reproduces the reference curve's shape at any scale while staying strictly
linear in the annual dispatch LP's own decision variables (level[t] and
E_cap, when E_cap is itself a decision variable): a_i and b_i are fixed
constants derived once from the fit, and E_cap enters only multiplied by a
constant, never by another variable. Same piecewise construction technique
as the boiler fuel curve in OpenSteamOpt's rto.py, adapted from an
equality-style curve (fuel as a function of load) to an inequality-style
capacity limit (allowed discharge power as a function of level).

This "intersect every segment's own secant line, extended over the whole
domain" construction reconstructs a concave piecewise-linear function
exactly, and only ever under-estimates (never over-estimates) a function
that is concave near each breakpoint but not globally so. It is unsafe
(can over-estimate) for a function with a large convex swing between
breakpoints; `verify_piecewise_curve_is_safe` checks this against the
underlying data before a fitted curve is used, rather than assuming it.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from tes_screen.packed_bed_dynamics import (
    DischargeResult,
    PackedBedDynamicsConfig,
    discharge_power_curve,
)


@dataclass(frozen=True)
class PiecewiseDischargeCurve:
    """p_dis[t] <= a_i*level[t] + b_i*E_cap, for every segment i, simultaneously."""

    a_coefficients: tuple[float, ...]
    b_coefficients: tuple[float, ...]
    soc_breakpoints: tuple[float, ...]
    power_fraction_breakpoints: tuple[float, ...]
    reference_energy_capacity_mwh: float
    reference_rated_power_mw: float
    k_mw_per_mwh: float

    def limit_mw(self, level_mwh: float, e_cap_mwh: float) -> float:
        """The piecewise-linear limit at a given (level, E_cap).

        For tests and plots; the LP itself uses a_coefficients/b_coefficients directly.
        """
        return min(
            a * level_mwh + b * e_cap_mwh
            for a, b in zip(self.a_coefficients, self.b_coefficients, strict=True)
        )


def fit_piecewise_discharge_curve(
    result: DischargeResult, process_temperature_c: float, n_segments: int = 5
) -> PiecewiseDischargeCurve:
    """Fit an n_segments piecewise-linear approximation from one Phase B discharge run."""
    if n_segments < 1:
        raise ValueError("n_segments must be at least 1")
    curve = discharge_power_curve(result, process_temperature_c)
    reference_energy_capacity_mwh = float(result.trace["bed_stored_energy_j"].iloc[0]) / 3.6e9
    reference_rated_power_mw = float(curve["deliverable_power_mw"].iloc[0])
    if reference_energy_capacity_mwh <= 0 or reference_rated_power_mw <= 0:
        raise ValueError(
            "Reference bed has non-positive capacity or rated power; check the discharge run"
        )
    k = reference_rated_power_mw / reference_energy_capacity_mwh

    soc_breakpoints = np.linspace(1.0, 0.0, n_segments + 1)
    # curve['state_of_charge'] declines monotonically with time; np.interp needs
    # ascending x, so reverse both series for interpolation.
    soc_ascending = curve["state_of_charge"].to_numpy()[::-1]
    power_ascending = curve["deliverable_power_mw"].to_numpy()[::-1]
    power_at_breakpoints = np.interp(soc_breakpoints, soc_ascending, power_ascending)
    frac_breakpoints = power_at_breakpoints / reference_rated_power_mw

    a_coefficients = []
    b_coefficients = []
    for i in range(n_segments):
        soc_hi, soc_lo = soc_breakpoints[i], soc_breakpoints[i + 1]
        frac_hi, frac_lo = frac_breakpoints[i], frac_breakpoints[i + 1]
        slope = (frac_hi - frac_lo) / (soc_hi - soc_lo)
        # Secant line through (soc_hi, frac_hi): frac(soc) = frac_hi + slope*(soc - soc_hi).
        # Substituting soc = level/E_cap:
        #   p_dis_limit = k*E_cap*frac(level/E_cap)
        #               = k*slope*level + k*E_cap*(frac_hi - slope*soc_hi)
        a_coefficients.append(k * slope)
        b_coefficients.append(k * (frac_hi - slope * soc_hi))

    return PiecewiseDischargeCurve(
        a_coefficients=tuple(a_coefficients),
        b_coefficients=tuple(b_coefficients),
        soc_breakpoints=tuple(soc_breakpoints),
        power_fraction_breakpoints=tuple(frac_breakpoints),
        reference_energy_capacity_mwh=reference_energy_capacity_mwh,
        reference_rated_power_mw=reference_rated_power_mw,
        k_mw_per_mwh=k,
    )


def verify_piecewise_curve_is_safe(
    curve: PiecewiseDischargeCurve, result: DischargeResult, process_temperature_c: float
) -> dict[str, float]:
    """Check the fit against the underlying discharge data it was fit from.

    Returns the largest observed overestimate (must be ~0 or negative: the
    piecewise limit must never exceed the true deliverable power at the
    reference bed size) and the largest observed underestimate (how
    conservative the approximation is where it is not exact). Call this
    before trusting a fit; do not assume safety from the construction alone.
    """
    power_curve = discharge_power_curve(result, process_temperature_c)
    e_cap = curve.reference_energy_capacity_mwh
    level = power_curve["state_of_charge"].to_numpy() * e_cap
    true_power = power_curve["deliverable_power_mw"].to_numpy()
    fitted = np.array([curve.limit_mw(lv, e_cap) for lv in level])
    difference = fitted - true_power  # positive => unsafe overestimate
    return {
        "max_overestimate_mw": float(max(difference.max(), 0.0)),
        "max_underestimate_mw": float(max(-difference.min(), 0.0)),
        "mean_absolute_error_mw": float(np.abs(difference).mean()),
    }


def mass_flow_for_target_duration(
    config: PackedBedDynamicsConfig,
    target_duration_hours: float,
    initial_bed_temperature_c: float,
    inlet_temperature_c: float,
    process_temperature_c: float,
) -> float:
    """The discharge mass flow whose reference power/energy ratio is 1/target_duration_hours.

    C2's matched-sizing fix (see dispatch.py's `duration_matched` branch)
    needs a discharge curve whose own k = P_reference/E_reference already
    equals 1/tau for the chosen design duration tau, rather than rescaling a
    curve fit at an arbitrary mass flow after the fact. This is possible in
    closed form because, for this bed model, the fully-charged bed's stored
    energy (`simulate_discharge`'s `bed_stored_energy_j` at t=0, referenced
    to `inlet_temperature_c`) depends only on geometry, material properties
    and the two temperatures -- not on mass flow -- while the reference
    deliverable power (`discharge_power_curve`'s value at t=0, referenced to
    `process_temperature_c`) scales linearly with mass flow. So the mass flow
    for any target duration can be solved for directly, then used to
    re-simulate the discharge and fit a curve genuinely specific to that
    duration, rather than reusing one bed's curve across all durations.

    Deliberately reuses `discharge_power_curve`'s existing reference-power
    definition (deliverable enthalpy flow above `process_temperature_c`) as
    the P0.1 fix's own scope: this does not address the separate,
    already-tracked P0.2 issue of that definition mixing the process and
    return temperature references. Fixing P0.1 without also silently
    changing P0.2's behaviour keeps the two roadmap items independent.
    """
    if target_duration_hours <= 0:
        raise ValueError("target_duration_hours must be positive")
    if initial_bed_temperature_c <= process_temperature_c:
        raise ValueError("initial_bed_temperature_c must exceed process_temperature_c")

    fluid_capacity_per_volume = (
        config.porosity * config.air_density_kg_per_m3 * config.air_specific_heat_j_per_kgk
    )
    solid_capacity_per_volume = (
        (1 - config.porosity) * config.rock_density_kg_per_m3 * config.rock_specific_heat_j_per_kgk
    )
    reference_energy_j = (
        config.bed_length_m
        * config.cross_section_area_m2
        * (fluid_capacity_per_volume + solid_capacity_per_volume)
        * (initial_bed_temperature_c - inlet_temperature_c)
    )
    reference_energy_mwh = reference_energy_j / 3.6e9
    target_power_mw = reference_energy_mwh / target_duration_hours
    temperature_drop = initial_bed_temperature_c - process_temperature_c
    return target_power_mw * 1e6 / (config.air_specific_heat_j_per_kgk * temperature_drop)


def piecewise_curve_to_frame(curve: PiecewiseDischargeCurve) -> pd.DataFrame:
    """Tabulate the fitted breakpoints for committing alongside a run's evidence."""
    return pd.DataFrame(
        {
            "state_of_charge": curve.soc_breakpoints,
            "power_fraction_of_rated": curve.power_fraction_breakpoints,
        }
    )
