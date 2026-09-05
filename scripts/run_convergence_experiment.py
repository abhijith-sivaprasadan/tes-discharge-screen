"""P3.1: spatial and temporal discretisation convergence for the packed-bed twin.

Usage: python scripts/run_convergence_experiment.py

The three existing analytic-limit checks (zero draw rate, infinite h_v,
energy conservation; `tests/test_packed_bed_dynamics.py`) are valuable but
answer a different question from this one: they check the *governing
equations* are implemented correctly, not that a fixed discretisation
(`n_nodes=40`, `n_steps` ranging 500-2000 across this project's own
scripts) is fine enough to trust. This experiment answers that second
question directly, sweeping node count and timestep count independently
against a finer reference solution, and -- per the roadmap's own
instruction that this is "the strongest metric" -- checking not just state
error but whether finer resolution would have changed the annual dispatch
LP's own sizing/cost decision.

Design:

- Reference ("truth") resolution: n_nodes=160, n_steps=4000, the finest
  point in both sweeps.
- Spatial sweep: n_nodes in {20, 40, 80, 160} at a fixed, already-fine
  n_steps=4000, isolating spatial discretisation error from temporal error.
- Temporal sweep: n_steps in {500, 1000, 2000, 4000} at a fixed, already-fine
  n_nodes=160, isolating temporal error from spatial error.
- Project-default point: n_nodes=40, n_steps=1500 -- what
  `run_phase_c2_duration_matched_experiment.py`,
  `run_phase_c_full_matrix_experiment.py`, and
  `run_capability_curves_experiment.py` all actually use
  (`REFERENCE_N_STEPS`) -- solved and compared explicitly, since "was
  every prior committed result already converged" is the practically
  important question this experiment can actually answer, not just "does
  convergence exist in the abstract."

At every grid point: the bed is discharged at the same mass flow (duration-
matched to 6h, the project's own established headline duration --
`discharge_curve.mass_flow_for_target_duration` is a closed-form function
of bed geometry/material properties alone, not of n_nodes/n_steps, so one
mass flow value serves every resolution), then compared against the
reference run on: the outlet-temperature trajectory (interpolated onto the
reference's own time grid), thermocline breakthrough time (first instant
the outlet drops below the process quality threshold), the useful-energy
fraction (energy actually delivered above quality, as a fraction of total
initial stored energy), the fitted 5-segment piecewise discharge curve's
own power-fraction breakpoints, and -- the headline metric -- the
SOC-dependent duration-matched annual dispatch LP's own sized E_cap, power
rating, and total cost, solved at every grid point exactly as C2/C3
already do, and compared against the same LP solved at the reference
resolution's own curve.
"""

from __future__ import annotations

import dataclasses
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from tes_screen.config import load_config  # noqa: E402
from tes_screen.discharge_curve import (  # noqa: E402
    fit_piecewise_discharge_curve,
    mass_flow_for_target_duration,
)
from tes_screen.dispatch import solve_dispatch  # noqa: E402
from tes_screen.packed_bed_dynamics import (  # noqa: E402
    default_packed_bed_config,
    simulate_discharge,
)
from tes_screen.synthetic_profiles import (  # noqa: E402
    build_load_profile,
    synthetic_daily_price_profile,
)
from tes_screen.verification import verify_schedule  # noqa: E402

CONFIG_PATH = Path("configs/packed_bed_300c_flat.yaml")
INITIAL_BED_TEMPERATURE_C = 400.0
INLET_TEMPERATURE_C = 320.0  # T_return
PROCESS_TEMPERATURE_C = 300.0
DELTA_T_MIN_HOT_SIDE_C = 0.0
DESIGN_DURATION_HOURS = 6.0  # matches C2/C3/P2.1's own headline duration
PRIMARY_N_SEGMENTS = 5

REFERENCE_N_NODES = 160
REFERENCE_N_STEPS = 4000

SPATIAL_GRID = [20, 40, 80, 160]  # at n_steps = REFERENCE_N_STEPS
TEMPORAL_GRID = [500, 1000, 2000, 4000]  # at n_nodes = REFERENCE_N_NODES
PROJECT_DEFAULT_N_NODES = 40
PROJECT_DEFAULT_N_STEPS = 1500  # C2/C3/P2.1's own REFERENCE_N_STEPS


def _duration_matched_config(base_config, soc_dependent: bool):
    return dataclasses.replace(
        base_config,
        storage=dataclasses.replace(
            base_config.storage,
            charge_power_max_mw=None,
            discharge_power_max_mw=None,
            design_duration_hours=DESIGN_DURATION_HOURS,
            discharge_limit_mode="soc_dependent" if soc_dependent else "constant",
            discharge_capability_reference=("start_of_hour" if soc_dependent else None),
        ),
    )


def _solved(config, load, price, discharge_curve=None):
    result = solve_dispatch(config, load, price, discharge_curve=discharge_curve)
    checks = verify_schedule(result.schedule, config, result.solver["objective_eur"])
    return result, checks


def _thermocline_breakthrough_time_s(
    trace, initial_bed_temperature_c: float, inlet_temperature_c: float
) -> float:
    """Standard packed-bed-literature breakthrough definition: the first
    time the dimensionless outlet temperature
    (T_out - T_inlet)/(T_initial - T_inlet) drops below 0.5, i.e. the
    outlet has cooled halfway from the fully-charged temperature toward
    the inlet temperature. Deliberately *not* tied to this project's own
    process quality threshold (`T_process + delta_T_min_hot_side`): every
    packed-bed config in this repository holds `inlet_temperature_c`
    (T_return) a fixed 20 C above its own `process_temperature_c` by
    design (the "usable floor" concept in configs/packed_bed_*.yaml), so
    outlet temperature -- which only ever approaches T_return from above,
    never below it -- can never actually cross that quality threshold in
    any finite discharge; a threshold tied to it would report "never
    breaks through" at every resolution and say nothing about
    discretisation error. The midpoint definition is a genuine property of
    the thermocline's own propagation speed, and is resolution-sensitive."""
    span = initial_bed_temperature_c - inlet_temperature_c
    dimensionless = (trace["outlet_temperature_c"] - inlet_temperature_c) / span
    below_midpoint = dimensionless < 0.5
    if not below_midpoint.any():
        return float(trace["time_s"].iloc[-1])
    return float(trace.loc[below_midpoint.idxmax(), "time_s"])


def _useful_energy_fraction(trace, threshold_c: float, initial_energy_j: float) -> float:
    """Fraction of total initial stored energy actually delivered while
    outlet temperature still clears the process quality threshold --
    trapezoidal integral of net outlet power over the meets-quality mask,
    divided by the bed's own total initial stored energy."""
    meets_quality = trace["outlet_temperature_c"] >= threshold_c
    outlet_energy = trace["cumulative_outlet_energy_j"].to_numpy()
    time_s = trace["time_s"].to_numpy()
    outlet_power_w = np.gradient(outlet_energy, time_s)
    outlet_power_w = np.where(outlet_power_w > 0, outlet_power_w, 0.0)
    gated_power_w = np.where(meets_quality.to_numpy(), outlet_power_w, 0.0)
    useful_energy_j = np.trapezoid(gated_power_w, time_s)
    return float(useful_energy_j / initial_energy_j)


def _run_point(mass_flow: float, n_nodes: int, n_steps: int):
    bed_config = dataclasses.replace(default_packed_bed_config(), n_nodes=n_nodes)
    result = simulate_discharge(
        bed_config,
        mass_flow_kg_per_s=mass_flow,
        initial_bed_temperature_c=INITIAL_BED_TEMPERATURE_C,
        inlet_temperature_c=INLET_TEMPERATURE_C,
        duration_s=DESIGN_DURATION_HOURS * 2 * 3600.0,
        n_steps=n_steps,
    )
    curve = fit_piecewise_discharge_curve(
        result, PROCESS_TEMPERATURE_C, DELTA_T_MIN_HOT_SIDE_C, n_segments=PRIMARY_N_SEGMENTS
    )
    threshold_c = PROCESS_TEMPERATURE_C + DELTA_T_MIN_HOT_SIDE_C
    initial_energy_j = float(result.trace["bed_stored_energy_j"].iloc[0])
    breakthrough_s = _thermocline_breakthrough_time_s(
        result.trace, INITIAL_BED_TEMPERATURE_C, INLET_TEMPERATURE_C
    )
    useful_fraction = _useful_energy_fraction(result.trace, threshold_c, initial_energy_j)
    return result, curve, breakthrough_s, useful_fraction


def _compare_to_reference(result, reference_result, curve, reference_curve):
    reference_time = reference_result.trace["time_s"].to_numpy()
    reference_outlet = reference_result.trace["outlet_temperature_c"].to_numpy()
    this_time = result.trace["time_s"].to_numpy()
    this_outlet = result.trace["outlet_temperature_c"].to_numpy()
    interpolated = np.interp(reference_time, this_time, this_outlet)
    max_outlet_temperature_deviation_c = float(np.max(np.abs(interpolated - reference_outlet)))
    max_power_fraction_breakpoint_deviation = float(
        np.max(
            np.abs(
                np.array(curve.power_fraction_breakpoints)
                - np.array(reference_curve.power_fraction_breakpoints)
            )
        )
    )
    return max_outlet_temperature_deviation_c, max_power_fraction_breakpoint_deviation


def main() -> None:
    output_dir = Path("outputs") / "convergence"
    output_dir.mkdir(parents=True, exist_ok=True)

    base_config = load_config(CONFIG_PATH)
    horizon = base_config.optimization.horizon_hours
    load = build_load_profile(
        base_config.process.profile_shape, base_config.process.annual_peak_load_mw, horizon
    )
    price = synthetic_daily_price_profile(horizon)

    bed_config_for_mass_flow = default_packed_bed_config()
    mass_flow = mass_flow_for_target_duration(
        bed_config_for_mass_flow,
        target_duration_hours=DESIGN_DURATION_HOURS,
        initial_bed_temperature_c=INITIAL_BED_TEMPERATURE_C,
        inlet_temperature_c=INLET_TEMPERATURE_C,
        process_temperature_c=PROCESS_TEMPERATURE_C,
        delta_t_min_hot_side_c=DELTA_T_MIN_HOT_SIDE_C,
    )

    constant_config = _duration_matched_config(base_config, soc_dependent=False)
    constant_result, constant_checks = _solved(constant_config, load, price)
    assert all(constant_checks.values()), "constant-limit baseline failed verification"

    reference_result, reference_curve, reference_breakthrough_s, reference_useful_fraction = (
        _run_point(mass_flow, REFERENCE_N_NODES, REFERENCE_N_STEPS)
    )
    soc_config = _duration_matched_config(base_config, soc_dependent=True)
    reference_soc_result, reference_soc_checks = _solved(
        soc_config, load, price, discharge_curve=reference_curve
    )
    assert all(reference_soc_checks.values()), "reference-resolution SOC-dependent solve failed"

    def build_entry(label: str, n_nodes: int, n_steps: int) -> dict:
        if (n_nodes, n_steps) == (REFERENCE_N_NODES, REFERENCE_N_STEPS):
            result, curve = reference_result, reference_curve
            breakthrough_s, useful_fraction = reference_breakthrough_s, reference_useful_fraction
            soc_result, soc_checks = reference_soc_result, reference_soc_checks
        else:
            result, curve, breakthrough_s, useful_fraction = _run_point(mass_flow, n_nodes, n_steps)
            soc_result, soc_checks = _solved(soc_config, load, price, discharge_curve=curve)
            assert all(soc_checks.values()), f"{label} SOC-dependent solve failed verification"

        max_outlet_dev_c, max_breakpoint_dev = _compare_to_reference(
            result, reference_result, curve, reference_curve
        )
        entry = {
            "label": label,
            "n_nodes": n_nodes,
            "n_steps": n_steps,
            "breakthrough_time_s": breakthrough_s,
            "breakthrough_time_deviation_s": breakthrough_s - reference_breakthrough_s,
            "useful_energy_fraction": useful_fraction,
            "useful_energy_fraction_deviation": useful_fraction - reference_useful_fraction,
            "max_outlet_temperature_deviation_c": max_outlet_dev_c,
            "max_power_fraction_breakpoint_deviation": max_breakpoint_dev,
            "soc_dependent": {
                "e_cap_mwh": soc_result.kpis["e_cap_mwh"],
                "power_rating_mw": soc_result.kpis["power_rating_mw"],
                "total_cost_eur": soc_result.kpis["total_cost_eur"],
            },
            "soc_dependent_deviation_from_reference": {
                "e_cap_mwh": soc_result.kpis["e_cap_mwh"] - reference_soc_result.kpis["e_cap_mwh"],
                "power_rating_mw": (
                    soc_result.kpis["power_rating_mw"]
                    - reference_soc_result.kpis["power_rating_mw"]
                ),
                "total_cost_eur": (
                    soc_result.kpis["total_cost_eur"] - reference_soc_result.kpis["total_cost_eur"]
                ),
                "total_cost_pct": 100
                * (soc_result.kpis["total_cost_eur"] - reference_soc_result.kpis["total_cost_eur"])
                / reference_soc_result.kpis["total_cost_eur"],
            },
        }
        print(
            f"{label:22s} N={n_nodes:3d} steps={n_steps:5d}  "
            f"max_outlet_dev={max_outlet_dev_c:8.4f} C  "
            f"breakthrough_dev={entry['breakthrough_time_deviation_s'] / 3600:7.4f} h  "
            f"E_cap_dev={entry['soc_dependent_deviation_from_reference']['e_cap_mwh']:+8.4f} MWh  "
            f"cost_dev={entry['soc_dependent_deviation_from_reference']['total_cost_pct']:+7.4f}%"
        )
        return entry

    spatial_sweep = [build_entry(f"spatial_N{n}", n, REFERENCE_N_STEPS) for n in SPATIAL_GRID]
    temporal_sweep = [
        build_entry(f"temporal_steps{n}", REFERENCE_N_NODES, n) for n in TEMPORAL_GRID
    ]
    project_default = build_entry(
        "project_default", PROJECT_DEFAULT_N_NODES, PROJECT_DEFAULT_N_STEPS
    )

    project_default_cost_pct = abs(
        project_default["soc_dependent_deviation_from_reference"]["total_cost_pct"]
    )
    decision_converged_at_project_default = project_default_cost_pct < 1.0  # [assumption] threshold

    manifest = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "roadmap_item": "P3.1 (spatial and temporal convergence)",
        "case": "packed_bed_300c_flat",
        "design_duration_hours": DESIGN_DURATION_HOURS,
        "mass_flow_kg_per_s": mass_flow,
        "reference_resolution": {"n_nodes": REFERENCE_N_NODES, "n_steps": REFERENCE_N_STEPS},
        "reference_breakthrough_time_s": reference_breakthrough_s,
        "reference_useful_energy_fraction": reference_useful_fraction,
        "reference_soc_dependent_kpis": {
            "e_cap_mwh": reference_soc_result.kpis["e_cap_mwh"],
            "power_rating_mw": reference_soc_result.kpis["power_rating_mw"],
            "total_cost_eur": reference_soc_result.kpis["total_cost_eur"],
        },
        "constant_limit_baseline_kpis": {
            "e_cap_mwh": constant_result.kpis["e_cap_mwh"],
            "power_rating_mw": constant_result.kpis["power_rating_mw"],
            "total_cost_eur": constant_result.kpis["total_cost_eur"],
        },
        "spatial_sweep": spatial_sweep,
        "temporal_sweep": temporal_sweep,
        "project_default": project_default,
        "decision_convergence_threshold_pct": 1.0,
        "decision_converged_at_project_default": decision_converged_at_project_default,
    }
    (output_dir / "run_manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )

    print()
    verdict = "CONVERGED" if decision_converged_at_project_default else "NOT CONVERGED"
    print(
        f"RESULT: project-default resolution (N={PROJECT_DEFAULT_N_NODES}, "
        f"n_steps={PROJECT_DEFAULT_N_STEPS}) vs. reference (N={REFERENCE_N_NODES}, "
        f"n_steps={REFERENCE_N_STEPS}) -- {verdict}: total-cost deviation "
        f"{project_default['soc_dependent_deviation_from_reference']['total_cost_pct']:+.4f}% "
        f"against a {1.0:.1f}% threshold."
    )
    print(f"Written to {output_dir}")


if __name__ == "__main__":
    main()
