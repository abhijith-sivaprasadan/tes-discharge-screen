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
reimplementation cross-checked against a compiled Modelica/FMU model
(`modelica/tes_screen/package.mo`, `fmu.py`). No OpenModelica toolchain is
available in this working environment (no `omc`, no `fmpy`), so that
cross-check ran outside it instead (Windows/OMEdit compiled the model;
`scripts/run_fmu_cross_check_experiment.py` ran the comparison), agreeing
to within 0.184 C (of an 80 C swing) and 0.0029% relative delivered energy
over a full 8h discharge -- see fmu.py and the project README for the full
story. This module's own correctness also rests on the three analytic
limits in `tests/test_packed_bed_dynamics.py` (zero draw rate, infinite
heat transfer coefficient reducing to a well-mixed tank, and
exact energy conservation).
"""

from __future__ import annotations

import warnings
from dataclasses import asdict, dataclass, replace
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
    # Blower/fan efficiency for the Ergun pressure-drop parasitic-power
    # calculation (roadmap P3.3). Carries a dataclass default the same way
    # n_nodes does (both are algorithm/equipment choices, not literature
    # material properties), but per this project's own rule ("assumptions
    # live in config, never in source") `default_packed_bed_config` still
    # sets it explicitly with its own citation tier below, rather than
    # relying on this default silently: [assumption] until a sourced
    # figure replaces it.
    blower_efficiency: float = 0.65

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
        if not 0 < self.blower_efficiency <= 1:
            raise ValueError("blower_efficiency must be in (0, 1]")

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
        blower_efficiency=0.65,  # [assumption] typical industrial centrifugal blower, 0.55-0.75
    )
    config.validate()
    return config


def scale_parallel_bed(
    reference_config: PackedBedDynamicsConfig,
    reference_mass_flow_kg_per_s: float,
    scale_factor: float,
) -> tuple[PackedBedDynamicsConfig, float]:
    """Modular area scaling (roadmap P1.1): a specific, defensible geometric
    family for rescaling one reference bed's discharge curve to an
    arbitrary storage capacity, replacing the vaguer "same duration ratio"
    assumption the dispatch LP's linear `b_i*E_cap` scaling used to rest on
    without a stated mechanism.

    Bed length, particle diameter, porosity, material properties and node
    count all stay fixed; only cross-sectional area `A` and mass flow
    `m_dot` scale, together, by `scale_factor`, holding the mass flux
    `G = m_dot/A` -- and therefore Reynolds number, the Wakao-Kaguei
    Nusselt number, the volumetric heat transfer coefficient, and every
    coefficient in `simulate_discharge`'s governing PDE, none of which
    reference `A` directly -- exactly fixed, not merely approximately.
    Since none of `simulate_discharge`'s physics depends on `A`, the
    resulting fluid/solid temperature fields `T_f(x,t)`, `T_s(x,t)` are
    identical to the reference run's at every scale factor; only the
    *totals* built from them (`bed_stored_energy_j`, `cumulative_outlet_energy_j`,
    `discharge_power_curve`'s `storage_heat_mw`) scale with `A`. A
    *normalized* curve (state of charge, a ratio of two `A`-proportional
    energies; power as a fraction of the reference rated power, a ratio of
    two `A`-proportional powers) should therefore collapse onto the
    reference curve exactly, up to floating-point roundoff -- checked, not
    assumed, in `tests/test_scaling_law.py` and
    `scripts/run_scaling_law_experiment.py`.

    Returns `(scaled_config, scaled_mass_flow_kg_per_s)` together, not the
    config alone: scaling area without scaling mass flow by the same factor
    would silently break the fixed-mass-flux invariant this family depends
    on, so there is no way to call this and forget the second half.
    """
    if scale_factor <= 0:
        raise ValueError("scale_factor must be positive")
    scaled_config = replace(
        reference_config,
        cross_section_area_m2=reference_config.cross_section_area_m2 * scale_factor,
    )
    return scaled_config, reference_mass_flow_kg_per_s * scale_factor


# Wakao-Kaguei's own stated validity domain (Wakao & Kaguei, 1982): the
# correlation was fit to data over this Reynolds range, and roadmap P3.2
# asks that every run record this range alongside Re/Pr/Nu and warn loudly
# when a scenario falls outside it, rather than silently extrapolating.
WAKAO_KAGUEI_REYNOLDS_VALIDITY_RANGE = (15.0, 8500.0)


@dataclass(frozen=True)
class FlowDiagnostics:
    """The Wakao-Kaguei correlation's own intermediate dimensionless groups,
    alongside the volumetric coefficient they produce -- roadmap P2.1's own
    required manifest fields (Re, Pr, Nu, h_v), factored out as a named
    result so a capability-curve run can record them directly rather than
    recomputing the correlation a second time from scratch. `reynolds_
    within_correlation_validity_range` is P3.2's own required field: whether
    this run's Re actually falls inside `WAKAO_KAGUEI_REYNOLDS_VALIDITY_RANGE`."""

    reynolds: float
    prandtl: float
    nusselt: float
    volumetric_heat_transfer_coefficient_w_per_m3k: float
    reynolds_within_correlation_validity_range: bool


def flow_diagnostics(
    config: PackedBedDynamicsConfig, mass_flux_kg_per_m2s: float
) -> FlowDiagnostics:
    """Reynolds, Prandtl, and Nusselt numbers and the volumetric fluid-solid
    heat transfer coefficient h_v [W/m3/K] at a given mass flux.

    Wakao-Kaguei correlation for particle Nusselt number (Wakao, N., Kaguei,
    S., 1982, "Heat and Mass Transfer in Packed Beds," Gordon and Breach;
    widely reproduced in packed-bed thermal storage literature):

        Nu = 2 + 1.1 * Re^0.6 * Pr^(1/3),   valid 15 < Re < 8500

    scaled to a volumetric coefficient by the packing's specific surface area
    per unit bed volume, a_v = 6(1-eps)/d_p for spherical particles.

    Roadmap P3.2: whenever Re falls outside `WAKAO_KAGUEI_REYNOLDS_VALIDITY_RANGE`,
    this warns loudly (`RuntimeWarning`) rather than silently extrapolating
    the correlation beyond where it was actually fit, and always records the
    in/out-of-range verdict on the returned `FlowDiagnostics` so a caller can
    check it without parsing warnings. Zero flow (`mass_flux_kg_per_m2s <= 0`)
    is a deliberate, already-tested static case, not a correlation
    evaluation, so it is reported as trivially "within range" rather than
    a violation.
    """
    if mass_flux_kg_per_m2s <= 0:
        return FlowDiagnostics(0.0, 0.0, 0.0, 0.0, True)
    reynolds = mass_flux_kg_per_m2s * config.particle_diameter_m / config.air_viscosity_pa_s
    prandtl = (
        config.air_viscosity_pa_s
        * config.air_specific_heat_j_per_kgk
        / config.air_thermal_conductivity_w_per_mk
    )
    nusselt = 2 + 1.1 * reynolds**0.6 * prandtl ** (1 / 3)
    h_particle = nusselt * config.air_thermal_conductivity_w_per_mk / config.particle_diameter_m
    specific_surface_area = 6 * (1 - config.porosity) / config.particle_diameter_m
    h_v = h_particle * specific_surface_area

    reynolds_lo, reynolds_hi = WAKAO_KAGUEI_REYNOLDS_VALIDITY_RANGE
    within_range = reynolds_lo <= reynolds <= reynolds_hi
    if not within_range:
        warnings.warn(
            f"Reynolds number {reynolds:.2f} is outside the Wakao-Kaguei "
            f"correlation's stated validity range [{reynolds_lo:.0f}, "
            f"{reynolds_hi:.0f}] (roadmap P3.2); h_v is being extrapolated "
            "beyond where the correlation was actually fit.",
            RuntimeWarning,
            stacklevel=2,
        )
    return FlowDiagnostics(reynolds, prandtl, nusselt, h_v, within_range)


def volumetric_heat_transfer_coefficient(
    config: PackedBedDynamicsConfig, mass_flux_kg_per_m2s: float
) -> float:
    """Volumetric fluid-solid heat transfer coefficient h_v [W/m3/K].

    Thin wrapper over `flow_diagnostics` kept for existing call sites that
    only need h_v itself (`simulate_discharge`'s own default correlation
    path); see `flow_diagnostics` for the full Re/Pr/Nu breakdown.
    """
    return flow_diagnostics(
        config, mass_flux_kg_per_m2s
    ).volumetric_heat_transfer_coefficient_w_per_m3k


@dataclass(frozen=True)
class PressureDropDiagnostics:
    """Ergun pressure drop and the blower electric power it implies
    (roadmap P3.3) -- an optional, documented extension, not wired into
    the annual dispatch LP's own economics: `dispatch.py`'s objective
    still uses `economics.storage_capex_eur_per_mw` as its blower/ducting/
    HX capital-cost proxy exactly as before, unchanged, so every already-
    committed result in this repository is unaffected by this addition.
    This makes that proxy's *operating*-cost counterpart computable and
    reportable alongside a discharge curve, not a silent replacement for it."""

    superficial_velocity_m_per_s: float
    pressure_drop_pa_per_m: float
    pressure_drop_pa: float
    volumetric_flow_m3_per_s: float
    blower_power_w: float


def ergun_pressure_drop_and_blower_power(
    config: PackedBedDynamicsConfig, mass_flow_kg_per_s: float
) -> PressureDropDiagnostics:
    """Ergun equation pressure drop across the bed length, and the blower
    electric power it implies at `config.blower_efficiency`.

    Ergun, S., 1952, "Fluid flow through packed columns," Chemical
    Engineering Progress 48(2), 89-94 -- textbook-standard, widely used for
    packed-bed pressure drop, combining laminar (Blake-Kozeny) and
    turbulent (Burke-Plummer) terms:

        dP/L = 150 * mu * (1-eps)^2 / (eps^3 * dp^2) * v_s
             + 1.75 * rho * (1-eps) / (eps^3 * dp) * v_s^2

    where `v_s` is the *superficial* velocity (volumetric flow divided by
    the empty cross-section, not the interstitial pore velocity) --
    `mass_flux_kg_per_m2s / air_density_kg_per_m3`, the same mass flux
    `flow_diagnostics` already uses for Re/Nu, so this stays exactly
    consistent with the heat-transfer side of the model rather than a
    second, independently-derived flow quantity.

    Blower electric power approximates the pressure drop as a simple
    isentropic-free hydraulic power divided by a blower efficiency
    (`P_blower = dP * volumetric_flow / eta_blower`, roadmap P3.3's own
    formula) -- a first-order approximation (no compressibility, no fan
    curve), adequate for the air-density, low-pressure-drop regime this
    project's own reference bed operates in, not a detailed blower design.
    """
    config.validate()
    if mass_flow_kg_per_s < 0:
        raise ValueError("mass_flow_kg_per_s must be nonnegative")
    mass_flux = mass_flow_kg_per_s / config.cross_section_area_m2
    superficial_velocity = mass_flux / config.air_density_kg_per_m3
    eps = config.porosity
    dp = config.particle_diameter_m
    laminar_term = (
        150 * config.air_viscosity_pa_s * (1 - eps) ** 2 / (eps**3 * dp**2) * superficial_velocity
    )
    turbulent_term = (
        1.75 * config.air_density_kg_per_m3 * (1 - eps) / (eps**3 * dp) * superficial_velocity**2
    )
    pressure_drop_per_length = laminar_term + turbulent_term
    pressure_drop_pa = pressure_drop_per_length * config.bed_length_m
    volumetric_flow = mass_flow_kg_per_s / config.air_density_kg_per_m3
    blower_power_w = pressure_drop_pa * volumetric_flow / config.blower_efficiency
    return PressureDropDiagnostics(
        superficial_velocity_m_per_s=superficial_velocity,
        pressure_drop_pa_per_m=pressure_drop_per_length,
        pressure_drop_pa=pressure_drop_pa,
        volumetric_flow_m3_per_s=volumetric_flow,
        blower_power_w=blower_power_w,
    )


@dataclass(frozen=True)
class DischargeResult:
    trace: pd.DataFrame
    config: PackedBedDynamicsConfig
    mass_flow_kg_per_s: float
    inlet_temperature_c: float
    initial_bed_temperature_c: float | np.ndarray


def bed_stored_energy_j(
    config: PackedBedDynamicsConfig,
    fluid_temperature_c: np.ndarray,
    solid_temperature_c: np.ndarray,
    reference_temperature_c: float,
) -> float:
    """Total sensible energy stored in the bed, referenced to `reference_temperature_c`.

    The same accounting `simulate_discharge`'s own `bed_stored_energy_j`
    trace column uses (there, always referenced to `inlet_temperature_c`),
    factored out here as a standalone primitive so a constructed
    (non-uniform) temperature field can be checked against exactly the same
    physics rather than a second, potentially drifting, implementation --
    used by `state_sufficiency.py`'s P0.3 field constructors, and by
    `discharge_curve.mass_flow_for_target_duration`'s reference-energy
    calculation.
    """
    fluid_capacity_per_volume = (
        config.porosity * config.air_density_kg_per_m3 * config.air_specific_heat_j_per_kgk
    )
    solid_capacity_per_volume = (
        (1 - config.porosity) * config.rock_density_kg_per_m3 * config.rock_specific_heat_j_per_kgk
    )
    dx = config.bed_length_m / config.n_nodes
    fluid_temperature_c = np.asarray(fluid_temperature_c)
    solid_temperature_c = np.asarray(solid_temperature_c)
    return float(
        config.cross_section_area_m2
        * dx
        * np.sum(
            fluid_capacity_per_volume * (fluid_temperature_c - reference_temperature_c)
            + solid_capacity_per_volume * (solid_temperature_c - reference_temperature_c)
        )
    )


def simulate_discharge(
    config: PackedBedDynamicsConfig,
    mass_flow_kg_per_s: float,
    initial_bed_temperature_c: float | np.ndarray,
    inlet_temperature_c: float,
    duration_s: float,
    *,
    heat_transfer_coefficient_override_w_per_m3k: float | None = None,
    n_steps: int = 500,
) -> DischargeResult:
    """Discharge a bed at a constant mass flow; the shadow twin.

    Cold fluid at `inlet_temperature_c` enters node 0 and flows toward node
    N-1, whose fluid temperature is the delivered outlet temperature. Both
    phases start at `initial_bed_temperature_c`: a single number for a
    uniform, fully-charged bed (every normal call site in this repository),
    or a length-`config.n_nodes` array for a non-uniform initial temperature
    field (P0.3's state-sufficiency experiment, `state_sufficiency.py`) --
    fluid and solid phases start equilibrated to the same field either way,
    generalising the uniform case rather than replacing it. No ambient heat
    loss term: this is an adiabatic bed model, matching Phase A's separate
    accounting of standing loss at the annual scale and keeping the
    energy-conservation analytic check (test_packed_bed_dynamics.py) exact
    rather than approximate.

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

    t_f = np.array(initial_bed_temperature_c, dtype=float)
    if t_f.shape == ():
        t_f = np.full(n, float(t_f))
    elif t_f.shape != (n,):
        raise ValueError(
            f"initial_bed_temperature_c array must have shape ({n},) to match "
            f"config.n_nodes, got {t_f.shape}"
        )
    t_s = t_f.copy()

    rows: list[dict[str, float]] = []
    initial_energy_j = bed_stored_energy_j(config, t_f, t_s, inlet_temperature_c)
    cumulative_outlet_energy_j = 0.0

    def record(time_s: float, outlet_energy_j: float) -> None:
        bed_energy_j = bed_stored_energy_j(config, t_f, t_s, inlet_temperature_c)
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


def discharge_power_curve(
    result: DischargeResult,
    process_temperature_c: float,
    delta_t_min_hot_side_c: float,
) -> pd.DataFrame:
    """Convert a discharge trace into a state-of-charge vs deliverable-power curve.

    Three separate temperatures, not one ambiguous "process temperature"
    (roadmap P0.2, fixing an enthalpy-reference mismatch): `T_process`
    (`process_temperature_c`, the process's own service temperature),
    `delta_T_min_hot_side` (`delta_t_min_hot_side_c`, the minimum
    heat-exchanger approach/headroom above it a delivered stream must clear),
    and `T_return` (`result.inlet_temperature_c`, the HTF temperature
    entering the bed -- an explicit simulation input, never derived from
    `T_process`; see `simulate_discharge`).

    State of charge and `storage_heat_mw` are both referenced to `T_return`:
    the same temperature the bed's own `bed_stored_energy_j` accounting
    uses (`simulate_discharge`). Before this fix, deliverable power was
    computed against `T_process` while stored energy was computed against
    `T_return`, so enthalpy already present in the return stream (whenever
    `T_return != T_process`) was counted as if storage had supplied it,
    inflating deliverable power and, through it, every SOC-dependent sizing
    result derived from this curve. `storage_heat_mw` and the bed's own
    stored-energy drop are now on the same reference, so integrating one
    against time reproduces the other (checked in
    test_packed_bed_dynamics.py's energy-consistency test), and a fully
    depleted bed (`T_out == T_return`) reports exactly zero, not a negative
    number that happened to get clipped away.

    `deliverable_power_mw` then applies a quality gate on top of
    `storage_heat_mw`: zero whenever the outlet cannot clear
    `T_required_out = T_process + delta_T_min_hot_side`, even though the bed
    still holds recoverable (`storage_heat_mw > 0`) sensible energy at that
    point -- lower-grade heat the process cannot use directly. This is the
    curve Phase C's piecewise-linear construction (rto.py's technique) turns
    into `p_dis[t] <= f_pw(level[t])`; the LP sees `deliverable_power_mw`,
    the quality-gated stream, never the ungated `storage_heat_mw`.
    """
    if delta_t_min_hot_side_c < 0:
        raise ValueError("delta_t_min_hot_side_c must be nonnegative")
    trace = result.trace
    initial_energy = trace["bed_stored_energy_j"].iloc[0]
    soc = trace["bed_stored_energy_j"] / initial_energy
    mass_flow = result.mass_flow_kg_per_s
    cp = result.config.air_specific_heat_j_per_kgk
    t_return = result.inlet_temperature_c
    storage_heat_w = (mass_flow * cp * (trace["outlet_temperature_c"] - t_return)).clip(lower=0.0)
    t_required_out = process_temperature_c + delta_t_min_hot_side_c
    meets_quality = trace["outlet_temperature_c"] >= t_required_out
    deliverable_w = storage_heat_w.where(meets_quality, 0.0)
    return pd.DataFrame(
        {
            "time_s": trace["time_s"],
            "state_of_charge": soc,
            "outlet_temperature_c": trace["outlet_temperature_c"],
            "storage_heat_mw": storage_heat_w / 1e6,
            "deliverable_power_mw": deliverable_w / 1e6,
        }
    )
