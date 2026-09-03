"""Packed-bed thermocline dynamic sub-model: the Phase B shadow twin.

A one-dimensional, two-phase (solid and fluid) transient model of a packed-bed
sensible store's discharge, discretised along the flow direction. Textbook
formulation, not a contribution in itself (see docs/DATA.md and the project
README): the governing equations are Schumann's two-phase packed-bed model
(Schumann, T.E.W., 1929, "Heat transfer: A liquid flowing through a porous
prism," Journal of the Franklin Institute 208(3), 405-416), the same
structure Zanganeh et al. (2012) and the wider packed-bed TES literature use:
a fluid energy equation and a solid energy equation coupled by a volumetric
heat transfer coefficient, axial conduction neglected.

    eps * rho_f * cp_f * dT_f/dt + G * cp_f * dT_f/dx = h_v * (T_s - T_f)
    (1-eps) * rho_s * cp_s * dT_s/dt = h_v * (T_f - T_s)

This module is a "shadow twin" in OpenSteamOpt's sense: a transparent Python
reimplementation meant to cross-check a compiled Modelica/FMU model
(`modelica/tes_screen/PackedBedThermocline.mo`, `fmu.py`). No OpenModelica
toolchain is available in this working environment (no `omc`, no `fmpy`), so
that cross-check has not been run; see fmu.py and the project README. This
module's own correctness instead rests on the three analytic limits in
`tests/test_packed_bed_dynamics.py` (zero draw rate, infinite heat transfer
coefficient reducing to a well-mixed tank, and exact energy conservation).
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class PackedBedDynamicsConfig:
    """Bed geometry, rock properties, and air (HTF) properties for the discharge model.

    Every field is either a literature-cited material property (docs/DATA.md's
    packed-bed table) or an explicitly labelled [assumption]/[textbook-standard]
    value; none are hardcoded in this module's logic.
    """

    bed_length_m: float
    cross_section_area_m2: float
    porosity: float
    particle_diameter_m: float
    rock_density_kg_per_m3: float
    rock_specific_heat_j_per_kgk: float
    air_density_kg_per_m3: float
    air_specific_heat_j_per_kgk: float
    air_viscosity_pa_s: float
    air_thermal_conductivity_w_per_mk: float
    n_nodes: int = 40

    def validate(self) -> None:
        positive = (
            self.bed_length_m,
            self.cross_section_area_m2,
            self.particle_diameter_m,
            self.rock_density_kg_per_m3,
            self.rock_specific_heat_j_per_kgk,
            self.air_density_kg_per_m3,
            self.air_specific_heat_j_per_kgk,
            self.air_viscosity_pa_s,
            self.air_thermal_conductivity_w_per_mk,
        )
        if not all(value > 0 for value in positive):
            raise ValueError("all geometry, rock, and air properties must be positive")
        if not 0 < self.porosity < 1:
            raise ValueError("porosity must be in (0, 1)")
        if self.n_nodes < 1:
            raise ValueError("n_nodes must be at least 1")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def default_packed_bed_config() -> PackedBedDynamicsConfig:
    """A reviewed, documented default bed. See docs/DATA.md for every source.

    Bed geometry (length, cross-section, node count) is illustrative, sized to
    produce a discharge duration of a few hours at the reference draw rates
    used in scripts/run_packed_bed_dynamics.py; it is not tied to any Phase A
    case's sizing decision, since Phase B's job is to characterise the shape
    of the discharge curve, not to match a specific plant. Rock properties
    (granite, docs/DATA.md) and air properties (standard property-table
    values at a representative bed temperature, not independently
    re-verified this session; see docs/DATA.md) are cited there.
    """
    config = PackedBedDynamicsConfig(
        bed_length_m=5.0,
        cross_section_area_m2=10.0,
        porosity=0.4,  # [assumption] typical crushed-rock packing void fraction
        particle_diameter_m=0.03,  # [assumption] typical crushed-rock/gravel size; docs/DATA.md
        rock_density_kg_per_m3=2400.0,
        rock_specific_heat_j_per_kgk=790.0,
        air_density_kg_per_m3=0.565,
        air_specific_heat_j_per_kgk=1085.0,
        air_viscosity_pa_s=3.1e-5,
        air_thermal_conductivity_w_per_mk=0.0454,
        n_nodes=40,
    )
    config.validate()
    return config


def volumetric_heat_transfer_coefficient(
    config: PackedBedDynamicsConfig, mass_flux_kg_per_m2s: float
) -> float:
    """Volumetric fluid-solid heat transfer coefficient h_v [W/m3/K].

    Wakao-Kaguei correlation for particle Nusselt number (Wakao, N., Kaguei,
    S., 1982, "Heat and Mass Transfer in Packed Beds," Gordon and Breach;
    widely reproduced in packed-bed thermal storage literature):

        Nu = 2 + 1.1 * Re^0.6 * Pr^(1/3),   valid 15 < Re < 8500

    scaled to a volumetric coefficient by the packing's specific surface area
    per unit bed volume, a_v = 6(1-eps)/d_p for spherical particles.
    """
    if mass_flux_kg_per_m2s <= 0:
        return 0.0
    reynolds = mass_flux_kg_per_m2s * config.particle_diameter_m / config.air_viscosity_pa_s
    prandtl = (
        config.air_viscosity_pa_s
        * config.air_specific_heat_j_per_kgk
        / config.air_thermal_conductivity_w_per_mk
    )
    nusselt = 2 + 1.1 * reynolds**0.6 * prandtl ** (1 / 3)
    h_particle = nusselt * config.air_thermal_conductivity_w_per_mk / config.particle_diameter_m
    specific_surface_area = 6 * (1 - config.porosity) / config.particle_diameter_m
    return h_particle * specific_surface_area


@dataclass(frozen=True)
class DischargeResult:
    trace: pd.DataFrame
    config: PackedBedDynamicsConfig
    mass_flow_kg_per_s: float
    inlet_temperature_c: float
    initial_bed_temperature_c: float


def simulate_discharge(
    config: PackedBedDynamicsConfig,
    mass_flow_kg_per_s: float,
    initial_bed_temperature_c: float,
    inlet_temperature_c: float,
    duration_s: float,
    *,
    heat_transfer_coefficient_override_w_per_m3k: float | None = None,
    n_steps: int = 500,
) -> DischargeResult:
    """Discharge a fully-charged bed at a constant mass flow; the shadow twin.

    Cold fluid at `inlet_temperature_c` enters node 0 and flows toward node
    N-1, whose fluid temperature is the delivered outlet temperature. Both
    phases start at `initial_bed_temperature_c` everywhere (a fully-charged
    bed). No ambient heat loss term: this is an adiabatic bed model, matching
    Phase A's separate accounting of standing loss at the annual scale and
    keeping the energy-conservation analytic check (test_packed_bed_dynamics.py)
    exact rather than approximate.

    Time-stepped with backward Euler (implicit), not forward Euler: air's
    volumetric heat capacity is orders of magnitude below rock's, which makes
    the explicit CFL/relaxation stability limits punishingly small (tens of
    milliseconds for an hours-long discharge). Backward Euler is
    unconditionally stable here, and because the solid-phase equation at each
    node depends only on that node's own fluid temperature, its update
    substitutes in closed form, leaving a lower-bidiagonal system in the
    fluid temperatures alone, solved by a single forward sweep per step, no
    matrix inversion, still fully auditable by hand. `n_steps` sets time
    resolution directly (accuracy, not stability), so the whole discharge
    solves in well under a second at the default resolution.

    `heat_transfer_coefficient_override_w_per_m3k` bypasses the Wakao-Kaguei
    correlation with a fixed h_v; used by the infinite-h_v analytic limit
    test, not by normal discharge-curve generation.
    """
    config.validate()
    if mass_flow_kg_per_s < 0:
        raise ValueError("mass_flow_kg_per_s must be nonnegative (zero is a valid, static case)")
    if duration_s <= 0:
        raise ValueError("duration_s must be positive")
    if n_steps < 1:
        raise ValueError("n_steps must be at least 1")

    n = config.n_nodes
    dx = config.bed_length_m / n
    mass_flux = mass_flow_kg_per_s / config.cross_section_area_m2
    h_v = (
        heat_transfer_coefficient_override_w_per_m3k
        if heat_transfer_coefficient_override_w_per_m3k is not None
        else volumetric_heat_transfer_coefficient(config, mass_flux)
    )

    fluid_capacity_per_volume = (
        config.porosity * config.air_density_kg_per_m3 * config.air_specific_heat_j_per_kgk
    )
    solid_capacity_per_volume = (
        (1 - config.porosity) * config.rock_density_kg_per_m3 * config.rock_specific_heat_j_per_kgk
    )
    advective_rate_per_volume = mass_flux * config.air_specific_heat_j_per_kgk

    dt_s = duration_s / n_steps
    # Solid-phase implicit weight: T_s_new[i] = w_s*T_s_old[i] + (1-w_s)*T_f_new[i].
    # Substituting into the fluid equation gives h_v*(T_s_new-T_f_new) =
    # h_v*w_s*(T_s_old - T_f_new): the coefficient on T_f_new (into a_coeff)
    # and on T_s_old (into rhs) is h_v*w_s, not h_v*(1-w_s).
    w_s = (
        (solid_capacity_per_volume / dt_s) / (solid_capacity_per_volume / dt_s + h_v)
        if h_v > 0
        else 1.0
    )
    a_coeff = fluid_capacity_per_volume / dt_s + advective_rate_per_volume / dx + h_v * w_s
    b_coeff = advective_rate_per_volume / dx

    t_f = np.full(n, initial_bed_temperature_c, dtype=float)
    t_s = np.full(n, initial_bed_temperature_c, dtype=float)

    rows: list[dict[str, float]] = []
    initial_energy_j = (
        config.cross_section_area_m2
        * dx
        * np.sum(
            fluid_capacity_per_volume * (t_f - inlet_temperature_c)
            + solid_capacity_per_volume * (t_s - inlet_temperature_c)
        )
    )
    cumulative_outlet_energy_j = 0.0

    def record(time_s: float, outlet_energy_j: float) -> None:
        bed_energy_j = (
            config.cross_section_area_m2
            * dx
            * np.sum(
                fluid_capacity_per_volume * (t_f - inlet_temperature_c)
                + solid_capacity_per_volume * (t_s - inlet_temperature_c)
            )
        )
        rows.append(
            {
                "time_s": time_s,
                "outlet_temperature_c": t_f[-1],
                "bed_stored_energy_j": bed_energy_j,
                "cumulative_outlet_energy_j": outlet_energy_j,
                "energy_conservation_residual_j": (initial_energy_j - bed_energy_j)
                - outlet_energy_j,
            }
        )

    record(0.0, 0.0)
    for step in range(n_steps):
        rhs = fluid_capacity_per_volume * t_f / dt_s + h_v * w_s * t_s
        t_f_new = np.empty(n)
        t_f_new[0] = (rhs[0] + b_coeff * inlet_temperature_c) / a_coeff
        for i in range(1, n):
            t_f_new[i] = (rhs[i] + b_coeff * t_f_new[i - 1]) / a_coeff
        t_s_new = w_s * t_s + (1 - w_s) * t_f_new

        outlet_flux_w = (
            mass_flow_kg_per_s
            * config.air_specific_heat_j_per_kgk
            * (t_f_new[-1] - inlet_temperature_c)
        )
        cumulative_outlet_energy_j += outlet_flux_w * dt_s
        t_f, t_s = t_f_new, t_s_new
        record((step + 1) * dt_s, cumulative_outlet_energy_j)

    trace = pd.DataFrame(rows)
    if not np.isfinite(trace.select_dtypes(include="number")).all().all():
        raise ValueError("Discharge simulation produced non-finite output; reduce dt_s")
    return DischargeResult(
        trace=trace,
        config=config,
        mass_flow_kg_per_s=mass_flow_kg_per_s,
        inlet_temperature_c=inlet_temperature_c,
        initial_bed_temperature_c=initial_bed_temperature_c,
    )


def discharge_power_curve(result: DischargeResult, process_temperature_c: float) -> pd.DataFrame:
    """Convert a discharge trace into a state-of-charge vs deliverable-power curve.

    State of charge is the bed's remaining stored energy (relative to the
    inlet/return temperature) as a fraction of its initial value. Deliverable
    power is the outlet enthalpy flow above `process_temperature_c`; zero once
    the outlet falls below the process requirement, per this project's core
    hypothesis, not `p_dis_max` regardless of temperature. This is the curve
    Phase C's piecewise-linear construction (rto.py's technique) will turn
    into `p_dis[t] <= f_pw(level[t])`.
    """
    trace = result.trace
    initial_energy = trace["bed_stored_energy_j"].iloc[0]
    soc = trace["bed_stored_energy_j"] / initial_energy
    mass_flow = result.mass_flow_kg_per_s
    cp = result.config.air_specific_heat_j_per_kgk
    deliverable_w = mass_flow * cp * (trace["outlet_temperature_c"] - process_temperature_c)
    deliverable_w = deliverable_w.clip(lower=0.0)
    return pd.DataFrame(
        {
            "time_s": trace["time_s"],
            "state_of_charge": soc,
            "outlet_temperature_c": trace["outlet_temperature_c"],
            "deliverable_power_mw": deliverable_w / 1e6,
        }
    )
