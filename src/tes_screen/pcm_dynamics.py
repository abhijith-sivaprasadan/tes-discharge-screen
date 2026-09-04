"""High-temperature PCM discharge model: a three-regime, not two-regime, curve.

A latent-heat store built with realistic (non-zero) sensible superheat and
subcooling bands -- as this project's own configs already assume
(`temperature_max_c`/`temperature_min_c` straddling the melting point, not
equal to it) -- discharges through three distinct regimes, not the "flat
plateau then done" idealisation a pure latent-only treatment would suggest:

1. **Superheat (sensible, liquid)**: outlet temperature declines from
   `T_max` down to the melting point as the liquid's superheat is removed.
2. **Latent**: outlet temperature holds at the melting point while the PCM
   freezes -- the "near-constant discharge temperature" idealisation this
   project's own `configs/pcm_300c_flat.yaml` comment names explicitly, and
   only while genuinely discharging across the phase change.
3. **Subcooled (sensible, solid)**: once fully frozen, outlet temperature
   declines further from the melting point down to `T_min` as the solid
   itself cools.

Each regime is modelled as a simple, closed-form, spatially-uniform
(lumped) sensible or latent energy balance -- a real simplification of a
genuinely more complex coupled conduction/convection problem, stated
plainly rather than disguised as a full dynamic model, but not a
fabricated mechanism: all three regimes are physically real for any PCM
store sized with sensible headroom either side of its melting point.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class PcmDynamicsConfig:
    melting_point_c: float
    latent_heat_j_per_kg: float
    solid_density_kg_per_m3: float
    solid_specific_heat_j_per_kgk: float
    liquid_specific_heat_j_per_kgk: float
    htf_specific_heat_j_per_kgk: float
    reference_module_volume_m3: float

    def validate(self) -> None:
        positive = (
            self.latent_heat_j_per_kg,
            self.solid_density_kg_per_m3,
            self.solid_specific_heat_j_per_kgk,
            self.liquid_specific_heat_j_per_kgk,
            self.htf_specific_heat_j_per_kgk,
            self.reference_module_volume_m3,
        )
        if not all(value > 0 for value in positive):
            raise ValueError("all PCM material properties and reference volume must be positive")


def default_pcm_config() -> PcmDynamicsConfig:
    """Single-salt NaNO3; see docs/DATA.md for citations, including this
    session's own density/specific-heat searches and their explicitly-flagged
    same-family proxies where a pure-NaNO3 liquid figure was not found.

    `htf_specific_heat_j_per_kgk` reuses the packed-bed reference config's
    own air property (`default_packed_bed_config`, docs/DATA.md) rather than
    inventing a new unsourced heat-transfer-fluid figure: a PCM module's
    heat exchanger fluid is a genuinely separate stream from the PCM medium
    itself (unlike molten salt, which is pumped directly), and air/steam HTF
    specific heats are broadly comparable in this range.
    """
    config = PcmDynamicsConfig(
        melting_point_c=306.0,
        latent_heat_j_per_kg=177_000.0,
        solid_density_kg_per_m3=2257.0,
        solid_specific_heat_j_per_kgk=1095.0,
        liquid_specific_heat_j_per_kgk=1550.0,
        htf_specific_heat_j_per_kgk=1085.0,
        reference_module_volume_m3=15.0,
    )
    config.validate()
    return config


def _pcm_mass_kg(config: PcmDynamicsConfig) -> float:
    return config.solid_density_kg_per_m3 * config.reference_module_volume_m3


def _energy_bands_j(
    config: PcmDynamicsConfig, t_max_c: float, t_min_c: float
) -> tuple[float, float, float]:
    """(subcooled sensible, latent, superheat sensible) energy, in that
    discharge order (subcooled is what remains *last*, at SOC near 0)."""
    if not t_min_c < config.melting_point_c < t_max_c:
        raise ValueError("t_min_c < melting_point_c < t_max_c is required")
    mass_kg = _pcm_mass_kg(config)
    subcooled_span_c = config.melting_point_c - t_min_c
    superheat_span_c = t_max_c - config.melting_point_c
    e_subcooled = mass_kg * config.solid_specific_heat_j_per_kgk * subcooled_span_c
    e_latent = mass_kg * config.latent_heat_j_per_kg
    e_superheat = mass_kg * config.liquid_specific_heat_j_per_kgk * superheat_span_c
    return e_subcooled, e_latent, e_superheat


def reference_energy_capacity_mwh(
    config: PcmDynamicsConfig, t_max_c: float, t_min_c: float
) -> float:
    """Full-charge (T_max) to fully-discharged (T_min) stored energy of the
    reference module, referenced to T_min the same way
    `packed_bed_dynamics.bed_stored_energy_j` references T_return."""
    e_subcooled, e_latent, e_superheat = _energy_bands_j(config, t_max_c, t_min_c)
    return (e_subcooled + e_latent + e_superheat) / 3.6e9


def _pcm_temperature_at_soc(
    soc: np.ndarray, config: PcmDynamicsConfig, t_max_c: float, t_min_c: float
) -> np.ndarray:
    e_subcooled, e_latent, e_superheat = _energy_bands_j(config, t_max_c, t_min_c)
    e_total = e_subcooled + e_latent + e_superheat
    soc_b = e_subcooled / e_total  # boundary: subcooled <-> latent
    soc_a = (e_subcooled + e_latent) / e_total  # boundary: latent <-> superheat

    temperature = np.empty_like(soc)
    in_superheat = soc >= soc_a
    in_latent = (soc < soc_a) & (soc >= soc_b)
    in_subcooled = soc < soc_b

    span_a = max(1.0 - soc_a, 1e-15)
    temperature[in_superheat] = config.melting_point_c + (t_max_c - config.melting_point_c) * (
        soc[in_superheat] - soc_a
    ) / span_a
    temperature[in_latent] = config.melting_point_c
    span_b = max(soc_b, 1e-15)
    temperature[in_subcooled] = t_min_c + (config.melting_point_c - t_min_c) * (
        soc[in_subcooled] / span_b
    )
    return temperature


def mass_flow_for_target_duration(
    config: PcmDynamicsConfig,
    target_duration_hours: float,
    t_max_c: float,
    t_min_c: float,
    htf_return_temperature_c: float,
) -> float:
    """The discharge HTF mass flow whose full-charge power/energy ratio is
    1/target_duration_hours. Same closed-form approach as the packed-bed and
    molten-salt equivalents: reference energy is independent of mass flow,
    reference power (at SOC=1, the superheat plateau's own top) scales
    linearly with it."""
    if target_duration_hours <= 0:
        raise ValueError("target_duration_hours must be positive")
    if t_max_c <= htf_return_temperature_c:
        raise ValueError("t_max_c must exceed htf_return_temperature_c")
    reference_energy_mwh = reference_energy_capacity_mwh(config, t_max_c, t_min_c)
    target_power_mw = reference_energy_mwh / target_duration_hours
    temperature_drop = t_max_c - htf_return_temperature_c
    return target_power_mw * 1e6 / (config.htf_specific_heat_j_per_kgk * temperature_drop)


def discharge_power_curve(
    config: PcmDynamicsConfig,
    mass_flow_kg_per_s: float,
    t_max_c: float,
    t_min_c: float,
    htf_return_temperature_c: float,
    process_temperature_c: float,
    delta_t_min_hot_side_c: float,
    n_points: int = 200,
) -> pd.DataFrame:
    """Analytic (state_of_charge, deliverable_power_mw) curve across all
    three discharge regimes. Same four-column contract
    `packed_bed_dynamics.discharge_power_curve` and
    `molten_salt_dynamics.discharge_power_curve` produce.
    """
    config.validate()
    if delta_t_min_hot_side_c < 0:
        raise ValueError("delta_t_min_hot_side_c must be nonnegative")
    if mass_flow_kg_per_s <= 0:
        raise ValueError("mass_flow_kg_per_s must be positive")
    if t_max_c <= htf_return_temperature_c:
        raise ValueError("t_max_c must exceed htf_return_temperature_c")
    t_required_out = process_temperature_c + delta_t_min_hot_side_c
    if t_max_c <= t_required_out:
        raise ValueError(
            "t_max_c must reach process_temperature_c + delta_t_min_hot_side_c, or the "
            "store could never serve the process even fully charged"
        )

    soc = np.linspace(1.0, 0.0, n_points)
    outlet_temperature_c = _pcm_temperature_at_soc(soc, config, t_max_c, t_min_c)
    storage_heat_w = (
        mass_flow_kg_per_s
        * config.htf_specific_heat_j_per_kgk
        * (outlet_temperature_c - htf_return_temperature_c)
    )
    storage_heat_mw = np.clip(storage_heat_w, 0.0, None) / 1e6
    meets_quality = outlet_temperature_c >= t_required_out
    deliverable_power_mw = np.where(meets_quality, storage_heat_mw, 0.0)

    return pd.DataFrame(
        {
            "state_of_charge": soc,
            "outlet_temperature_c": outlet_temperature_c,
            "storage_heat_mw": storage_heat_mw,
            "deliverable_power_mw": deliverable_power_mw,
        }
    )
