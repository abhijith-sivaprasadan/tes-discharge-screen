"""P0.3: is a scalar state of charge a sufficient packed-bed state?

Phase C's piecewise discharge-limit curve (`discharge_curve.py`) comes from
one trajectory: a fully-charged, spatially uniform bed, discharged
continuously at one mass flow. Reading deliverable power off that single
trajectory as a function of total stored energy (SOC) alone assumes any two
bed states with the same total energy have the same outlet capability --
but a packed bed is a distributed-temperature system: two beds holding the
same total energy can have that energy arranged very differently along the
bed (a sharp thermocline near one end vs a broad, smeared one), and a sharp
thermocline nearer the outlet leaves less "buffer" before breakthrough than
the same energy spread more evenly. Whether that spatial arrangement
actually changes near-term deliverable power -- whether scalar SOC is a
*sufficient* state for this purpose -- is an empirical question, not
something the single-trajectory curve construction can answer on its own.

This module constructs several temperature fields at a matched total energy
so `scripts/run_state_sufficiency_experiment.py` can discharge each briefly
and compare: uniform, a sharp step with the hot block at the inlet end, the
mirror-image step with the hot block at the outlet end (same total energy,
opposite spatial arrangement), and a broad linear ramp. A fifth family the
roadmap names -- "profiles taken from realistic charge/discharge histories"
-- is not built here: it depends on having a charging dynamic model, which
this project does not have (Phase B is discharge-only), so it is left
undone rather than approximated.

Every constructor returns a length-`config.n_nodes` array of temperatures
(deg C), applied to both the fluid and solid phases identically at t=0 --
generalising `simulate_discharge`'s own "fully-charged, equilibrated bed"
convention to a spatially varying field, not introducing fluid/solid
non-equilibrium as a separate concern. `energy_fraction` is always relative
to the same reference a fully-charged uniform bed at `hot_temperature_c`
would hold (`bed_stored_energy_j`, referenced to `return_temperature_c`),
so 1.0 means "as much total energy as a fully-charged bed," not "every node
at the hot temperature."
"""

from __future__ import annotations

import numpy as np

from tes_screen.packed_bed_dynamics import PackedBedDynamicsConfig, bed_stored_energy_j

_HOT_SIDES = frozenset({"inlet", "outlet"})


def _validate_inputs(
    config: PackedBedDynamicsConfig,
    energy_fraction: float,
    hot_temperature_c: float,
    return_temperature_c: float,
) -> None:
    config.validate()
    if not 0 < energy_fraction < 1:
        raise ValueError("energy_fraction must be in (0, 1)")
    if hot_temperature_c <= return_temperature_c:
        raise ValueError("hot_temperature_c must exceed return_temperature_c")


def reference_energy_j(
    config: PackedBedDynamicsConfig, hot_temperature_c: float, return_temperature_c: float
) -> float:
    """Energy a fully-charged, uniform bed at `hot_temperature_c` holds.

    The denominator every `energy_fraction` in this module is measured
    against; not itself a constructed field.
    """
    full = np.full(config.n_nodes, hot_temperature_c)
    return bed_stored_energy_j(config, full, full, return_temperature_c)


def achieved_energy_fraction(
    config: PackedBedDynamicsConfig,
    field_c: np.ndarray,
    hot_temperature_c: float,
    return_temperature_c: float,
) -> float:
    """The actual energy fraction a constructed field holds, for verification.

    Node-count discretisation means a constructor's requested
    `energy_fraction` and the field it actually returns can differ slightly;
    call this rather than assuming the request was met exactly.
    """
    field_energy = bed_stored_energy_j(config, field_c, field_c, return_temperature_c)
    return field_energy / reference_energy_j(config, hot_temperature_c, return_temperature_c)


def uniform_field(
    config: PackedBedDynamicsConfig,
    energy_fraction: float,
    hot_temperature_c: float,
    return_temperature_c: float,
) -> np.ndarray:
    """Every node at the same intermediate temperature.

    The "no spatial structure at all" baseline: since a uniform field is
    also the well-mixed-tank limit, this is what the other three profiles
    below are compared against.
    """
    _validate_inputs(config, energy_fraction, hot_temperature_c, return_temperature_c)
    t_uniform = return_temperature_c + energy_fraction * (hot_temperature_c - return_temperature_c)
    return np.full(config.n_nodes, t_uniform)


def step_field(
    config: PackedBedDynamicsConfig,
    energy_fraction: float,
    hot_temperature_c: float,
    return_temperature_c: float,
    hot_side: str,
) -> np.ndarray:
    """A sharp two-block step: a hot block and a cold block, same total energy either way.

    `hot_side="inlet"` puts the hot block (`round(energy_fraction * n_nodes)`
    nodes at `hot_temperature_c`) at node 0 and the cold block (the rest, at
    `return_temperature_c`) toward the outlet -- the transition sits at
    position `energy_fraction * bed_length_m` from the inlet.
    `hot_side="outlet"` mirrors it: cold at the inlet, hot at the outlet,
    transition at `(1 - energy_fraction) * bed_length_m` from the inlet.
    For any `energy_fraction != 0.5` these two put the transition at
    different physical locations while holding exactly the same total
    energy (same hot-block length, and total energy for a uniform
    cross-section bed depends only on each block's length, not where along
    the bed it sits) -- the equal-SOC, different-spatial-structure pair
    P0.3's roadmap items 2 and 3 ask for.
    """
    _validate_inputs(config, energy_fraction, hot_temperature_c, return_temperature_c)
    if hot_side not in _HOT_SIDES:
        raise ValueError(f"hot_side must be one of {sorted(_HOT_SIDES)}, got {hot_side!r}")
    n = config.n_nodes
    n_hot = round(energy_fraction * n)
    field = np.full(n, return_temperature_c)
    if hot_side == "inlet":
        field[:n_hot] = hot_temperature_c
    else:
        field[n - n_hot :] = hot_temperature_c
    return field


def smeared_field(
    config: PackedBedDynamicsConfig,
    energy_fraction: float,
    hot_temperature_c: float,
    return_temperature_c: float,
    spread_fraction: float = 0.9,
) -> np.ndarray:
    """A broad linear ramp across the whole bed, same total energy as the uniform field.

    Centred on the same temperature `uniform_field` would use everywhere
    (`t_mean`); a linear ramp's spatial average equals its centre value
    regardless of slope, so centring on `t_mean` matches total energy to
    `uniform_field` exactly, by construction, with no search or fitting
    needed. `spread_fraction` (0, 1) sets how much of the room between
    `t_mean` and each physical bound (`return_temperature_c`,
    `hot_temperature_c`) the ramp actually uses; keeping it below 1 keeps
    the ramp's own endpoints strictly inside those bounds, so nothing
    clips and the exact-energy-match property is never broken by clipping.
    """
    _validate_inputs(config, energy_fraction, hot_temperature_c, return_temperature_c)
    if not 0 < spread_fraction < 1:
        raise ValueError("spread_fraction must be in (0, 1)")
    n = config.n_nodes
    t_mean = return_temperature_c + energy_fraction * (hot_temperature_c - return_temperature_c)
    half_range = spread_fraction * min(t_mean - return_temperature_c, hot_temperature_c - t_mean)
    node_position_fraction = (np.arange(n) + 0.5) / n  # node-centre positions in (0, 1)
    return t_mean + half_range * (2 * node_position_fraction - 1)
