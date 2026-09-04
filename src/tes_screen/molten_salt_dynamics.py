"""Two-tank molten salt discharge model: the project's own control case.

Unlike a packed bed, a two-tank molten salt store develops no thermocline:
the hot and cold inventories are physically separate, well-mixed tanks, not
a moving front within one vessel, so the hot tank's outlet temperature
stays at essentially the hot-tank temperature regardless of how much salt
remains in it -- until it nears empty. This module's own config file
comments (`configs/molten_salt_*.yaml`, written before this module existed)
already state the expected result: "molten salt discharges at a
near-constant temperature, so the SOC-dependent correction should barely
move it. If it does move materially, the implementation is wrong." This
module exists to let that claim actually be tested, not merely asserted.

Discharge capability declining near full depletion is modelled as a flow
limitation, not a temperature one: outlet temperature is exactly the hot
tank's own temperature for as long as any usable salt remains (there is no
mechanism in a two-tank system for it to do anything else), while the
deliverable *flow rate* -- and therefore power -- tapers linearly to zero
across a small "heel" fraction near the bottom of the tank
(`heel_fraction`, an explicit [assumption]: real two-tank systems keep an
unusable residual for pump NPSH, tank geometry, and avoiding cold/mixed
boundary-layer draw near the outlet, not a fabricated mechanism, but not a
literature-sourced number either).
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class MoltenSaltDynamicsConfig:
    """Material properties and reference module size only.

    Hot/cold tank temperatures are supplied per case at call time (like
    `packed_bed_dynamics.simulate_discharge`'s own
    `initial_bed_temperature_c`/`inlet_temperature_c`), not baked in here,
    since the same salt config serves every process temperature case.
    """

    salt_density_kg_per_m3: float
    salt_specific_heat_j_per_kgk: float
    heel_fraction: float
    reference_tank_volume_m3: float

    def validate(self) -> None:
        if self.salt_density_kg_per_m3 <= 0:
            raise ValueError("salt_density_kg_per_m3 must be positive")
        if self.salt_specific_heat_j_per_kgk <= 0:
            raise ValueError("salt_specific_heat_j_per_kgk must be positive")
        if not 0 <= self.heel_fraction < 1:
            raise ValueError("heel_fraction must be in [0, 1)")
        if self.reference_tank_volume_m3 <= 0:
            raise ValueError("reference_tank_volume_m3 must be positive")


def default_molten_salt_config() -> MoltenSaltDynamicsConfig:
    """Solar Salt (NaNO3-KNO3 60:40) properties; see docs/DATA.md for citations.

    Density at the mean of the 290-565 C operating range from docs/DATA.md's
    own correlation (rho = 2091 - 0.641*T[C]); specific heat is that same
    table's cited average. `reference_tank_volume_m3` is illustrative
    (matches the order of magnitude the packed-bed reference config's own
    energy capacity implies), not tied to any specific case's sizing --
    Phase B/B-equivalent modules characterise curve shape, not a specific
    plant, exactly as `packed_bed_dynamics.default_packed_bed_config`'s own
    docstring already states for the packed-bed case.
    """
    mean_temperature_c = (290.0 + 565.0) / 2
    config = MoltenSaltDynamicsConfig(
        salt_density_kg_per_m3=2091 - 0.641 * mean_temperature_c,  # docs/DATA.md
        salt_specific_heat_j_per_kgk=1550.0,  # docs/DATA.md, Solar Salt average
        heel_fraction=0.05,  # [assumption]
        reference_tank_volume_m3=25.0,
    )
    config.validate()
    return config


def reference_energy_capacity_mwh(
    config: MoltenSaltDynamicsConfig, hot_tank_temperature_c: float, cold_tank_temperature_c: float
) -> float:
    """Full-charge stored energy of the reference tank, referenced to the cold-tank
    (return) temperature -- the same convention `packed_bed_dynamics.bed_stored_energy_j`
    uses, generalised to a well-mixed tank rather than a spatial field."""
    if hot_tank_temperature_c <= cold_tank_temperature_c:
        raise ValueError("hot_tank_temperature_c must exceed cold_tank_temperature_c")
    mass_kg = config.salt_density_kg_per_m3 * config.reference_tank_volume_m3
    temperature_drop = hot_tank_temperature_c - cold_tank_temperature_c
    energy_j = mass_kg * config.salt_specific_heat_j_per_kgk * temperature_drop
    return energy_j / 3.6e9


def mass_flow_for_target_duration(
    config: MoltenSaltDynamicsConfig,
    target_duration_hours: float,
    hot_tank_temperature_c: float,
    cold_tank_temperature_c: float,
) -> float:
    """The discharge mass flow whose full-charge power/energy ratio is 1/target_duration_hours.

    Same closed-form approach as `discharge_curve.mass_flow_for_target_duration`:
    reference energy is independent of mass flow (fixed tank size), while
    reference power scales linearly with it, so the mass flow for any
    target duration solves directly.
    """
    if target_duration_hours <= 0:
        raise ValueError("target_duration_hours must be positive")
    reference_energy_mwh = reference_energy_capacity_mwh(
        config, hot_tank_temperature_c, cold_tank_temperature_c
    )
    target_power_mw = reference_energy_mwh / target_duration_hours
    temperature_drop = hot_tank_temperature_c - cold_tank_temperature_c
    return target_power_mw * 1e6 / (config.salt_specific_heat_j_per_kgk * temperature_drop)


def discharge_power_curve(
    config: MoltenSaltDynamicsConfig,
    mass_flow_kg_per_s: float,
    hot_tank_temperature_c: float,
    cold_tank_temperature_c: float,
    process_temperature_c: float,
    delta_t_min_hot_side_c: float,
    n_points: int = 200,
) -> pd.DataFrame:
    """Analytic (state_of_charge, deliverable_power_mw) curve for a two-tank store.

    Same four-column contract `packed_bed_dynamics.discharge_power_curve`
    produces (`state_of_charge`, `outlet_temperature_c`, `storage_heat_mw`,
    `deliverable_power_mw`), built directly rather than by time-stepping a
    PDE, since there is no spatial field here to integrate: outlet
    temperature is `hot_tank_temperature_c`, exactly, for every state of
    charge down to zero (no thermocline to erode it); only the deliverable
    *flow*, and therefore power, tapers across `config.heel_fraction`.
    """
    config.validate()
    if delta_t_min_hot_side_c < 0:
        raise ValueError("delta_t_min_hot_side_c must be nonnegative")
    if mass_flow_kg_per_s <= 0:
        raise ValueError("mass_flow_kg_per_s must be positive")
    t_required_out = process_temperature_c + delta_t_min_hot_side_c
    if hot_tank_temperature_c <= t_required_out:
        raise ValueError(
            "hot_tank_temperature_c must reach process_temperature_c + "
            "delta_t_min_hot_side_c, or the store could never serve the process"
        )

    soc = np.linspace(1.0, 0.0, n_points)
    if config.heel_fraction > 0:
        flow_fraction = np.clip(soc / config.heel_fraction, 0.0, 1.0)
    else:
        flow_fraction = np.ones_like(soc)

    rated_power_mw = (
        mass_flow_kg_per_s
        * config.salt_specific_heat_j_per_kgk
        * (hot_tank_temperature_c - cold_tank_temperature_c)
        / 1e6
    )
    storage_heat_mw = flow_fraction * rated_power_mw
    # Outlet temperature never varies while any flow occurs (it is exactly
    # the hot-tank temperature), so the quality gate is a single pass/fail
    # check made once above, not a per-point comparison the way the packed
    # bed's continuously-declining outlet needs.
    deliverable_power_mw = storage_heat_mw.copy()

    return pd.DataFrame(
        {
            "state_of_charge": soc,
            "outlet_temperature_c": np.full(n_points, hot_tank_temperature_c),
            "storage_heat_mw": storage_heat_mw,
            "deliverable_power_mw": deliverable_power_mw,
        }
    )
