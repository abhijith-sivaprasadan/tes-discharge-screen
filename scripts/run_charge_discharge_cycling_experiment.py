"""Charge/discharge cycling: does the discharge-only Pmax(SOC) curve survive
realistic cyclic operation? The fifth P0.3 profile family, previously left
undone for lack of a charging model.

Usage: python scripts/run_charge_discharge_cycling_experiment.py

P0.3 (`state_sufficiency.py`, `run_state_sufficiency_experiment.py`) found
that scalar state of charge is *not* a sufficient state for predicting a
packed bed's near-term deliverable power: several *hand-constructed*
temperature fields holding the same total energy but different spatial
structure showed up to ~220% scatter in near-term power at matched SOC.
Its own module docstring names a fifth profile family the roadmap also
asks for -- "profiles taken from realistic charge/discharge histories" --
and states plainly why it was left undone: "it depends on having a
charging dynamic model, which this project does not have (Phase B is
discharge-only)."

That is no longer quite true. `simulate_discharge` solves Schumann's two-
phase equations for a fluid stream flowing from node 0 toward node N-1,
warming or cooling the bed however the boundary condition dictates -- the
equations do not know or care whether the entering fluid is colder or
hotter than the bed. A "charge" is not a different model, just a different
boundary condition: hot fluid entering from the bed's *other* end (the
standard opposite-end thermocline convention, keeping the thermocline's own
orientation intact rather than eroding it back the way it formed), which
this script implements by reversing the spatial field before calling
`simulate_discharge` and reversing the result back afterward -- no change
to the governing equations or the solver, only to which physical end is
"node 0" for that one call. `DischargeResult.final_fluid_temperature_c`/
`final_solid_temperature_c` (added for this) let successive calls chain
from the *real*, generally-non-equilibrated state a previous segment left
the bed in, rather than re-equilibrating fluid and solid at every segment
boundary.

This script builds several multi-segment charge/discharge histories from a
fully-charged bed, ending at whatever state of charge each history actually
reaches (not a hand-picked target), probes near-term deliverable power
there exactly as P0.3 does (a short 1800s discharge, five checkpoints), and
compares it against what the single monotonic discharge-only trajectory --
the one this project's own discharge curve, and therefore the annual
dispatch LP's own `p_dis[t]` constraint, is actually built from -- predicts
at that same achieved state of charge. Two of the five histories are pure
single discharges with no charging step at all: these do not test anything
new (they reproduce the reference trajectory's own state by construction)
and are included as a methodology control, not a finding -- if they do not
show ~0% deviation, the comparison machinery itself is broken, not the
physics.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from tes_screen.packed_bed_dynamics import (  # noqa: E402
    DischargeResult,
    PackedBedDynamicsConfig,
    bed_stored_energy_j,
    default_packed_bed_config,
    discharge_power_curve,
    simulate_discharge,
)
from tes_screen.state_sufficiency import reference_energy_j  # noqa: E402

HOT_TEMPERATURE_C = 400.0
RETURN_TEMPERATURE_C = 320.0
PROCESS_TEMPERATURE_C = 300.0
DELTA_T_MIN_HOT_SIDE_C = 0.0  # [assumption]; matches P0.3/every other reference-bed script
MASS_FLOW_KG_PER_S = 3.0  # matches P0.3's own reference bed draw rate; used for charge legs too
REFERENCE_DURATION_S = 10 * 3600.0  # comfortably past full depletion at this mass flow (~8h)
REFERENCE_N_STEPS = 2000
SEGMENT_N_STEPS_PER_HOUR = 200  # resolution for each cycling leg
SHORT_HORIZON_S = 1800.0  # 30 min: identical probe to P0.3, for direct comparability
PROBE_N_STEPS = 300
CHECKPOINTS_S = [0.0, 300.0, 600.0, 1200.0, 1800.0]  # identical to P0.3
SCATTER_THRESHOLD = 0.05  # [assumption]; P0.3's own threshold, reused for comparability

# Each recipe: an ordered list of (direction, duration_hours) legs starting
# from a fully-charged, uniform bed. "monotonic_*" recipes have exactly one
# discharge leg and no charge leg: pure controls, not realistic cycles.
RECIPES: dict[str, list[tuple[str, float]]] = {
    "monotonic_2.0h": [("discharge", 2.0)],
    "monotonic_3.5h": [("discharge", 3.5)],
    "shallow_cycle": [("discharge", 3.0), ("charge", 0.5), ("discharge", 0.7)],
    "deep_cycle": [("discharge", 5.0), ("charge", 2.0), ("discharge", 1.0)],
    "double_cycle": [
        ("discharge", 2.5),
        ("charge", 1.0),
        ("discharge", 0.8),
        ("charge", 0.4),
        ("discharge", 0.6),
    ],
}


def _simulate_segment(
    config: PackedBedDynamicsConfig,
    direction: str,
    duration_hours: float,
    initial_fluid_c: np.ndarray,
    initial_solid_c: np.ndarray,
) -> DischargeResult:
    """One leg of a cycle. "discharge": cold return fluid enters node 0,
    exactly as every other script in this repository. "charge": hot fluid
    enters from the *opposite* physical end -- implemented by reversing the
    spatial field before the call (so the reversed array's node 0 is the
    bed's real far end) and reversing the result back after, not by adding
    a flow-direction parameter to `simulate_discharge` itself, since the
    governing equations already treat "node 0" as a generic label, not a
    physical direction."""
    duration_s = duration_hours * 3600.0
    n_steps = max(10, round(duration_hours * SEGMENT_N_STEPS_PER_HOUR))
    if direction == "discharge":
        return simulate_discharge(
            config,
            mass_flow_kg_per_s=MASS_FLOW_KG_PER_S,
            initial_bed_temperature_c=initial_fluid_c,
            initial_solid_temperature_c=initial_solid_c,
            inlet_temperature_c=RETURN_TEMPERATURE_C,
            duration_s=duration_s,
            n_steps=n_steps,
        )
    if direction == "charge":
        result = simulate_discharge(
            config,
            mass_flow_kg_per_s=MASS_FLOW_KG_PER_S,
            initial_bed_temperature_c=initial_fluid_c[::-1],
            initial_solid_temperature_c=initial_solid_c[::-1],
            inlet_temperature_c=HOT_TEMPERATURE_C,
            duration_s=duration_s,
            n_steps=n_steps,
        )
        # Reverse the spatial fields back to the bed's real physical
        # orientation before handing them to the next leg (which expects
        # "node 0 = the discharge inlet end", not the reversed frame this
        # call ran in).
        return DischargeResult(
            trace=result.trace,
            config=result.config,
            mass_flow_kg_per_s=result.mass_flow_kg_per_s,
            inlet_temperature_c=result.inlet_temperature_c,
            initial_bed_temperature_c=result.initial_bed_temperature_c,
            final_fluid_temperature_c=result.final_fluid_temperature_c[::-1],
            final_solid_temperature_c=result.final_solid_temperature_c[::-1],
        )
    raise ValueError(f"direction must be 'discharge' or 'charge', got {direction!r}")


def _run_recipe(
    config: PackedBedDynamicsConfig, legs: list[tuple[str, float]]
) -> tuple[np.ndarray, np.ndarray, list[dict[str, Any]]]:
    fluid = np.full(config.n_nodes, HOT_TEMPERATURE_C)
    solid = np.full(config.n_nodes, HOT_TEMPERATURE_C)
    leg_log = []
    ref_energy = reference_energy_j(config, HOT_TEMPERATURE_C, RETURN_TEMPERATURE_C)
    for direction, duration_hours in legs:
        result = _simulate_segment(config, direction, duration_hours, fluid, solid)
        fluid = result.final_fluid_temperature_c
        solid = result.final_solid_temperature_c
        soc = bed_stored_energy_j(config, fluid, solid, RETURN_TEMPERATURE_C) / ref_energy
        leg_log.append(
            {"direction": direction, "duration_hours": duration_hours, "soc_after_leg": soc}
        )
    return fluid, solid, leg_log


def main() -> None:
    output_dir = Path("outputs") / "charge_discharge_cycling"
    output_dir.mkdir(parents=True, exist_ok=True)
    config = default_packed_bed_config()
    ref_energy = reference_energy_j(config, HOT_TEMPERATURE_C, RETURN_TEMPERATURE_C)

    # The single monotonic reference trajectory this project's own discharge
    # curve -- and therefore the annual dispatch LP's own p_dis[t] limit --
    # is actually built from.
    reference_result = simulate_discharge(
        config,
        mass_flow_kg_per_s=MASS_FLOW_KG_PER_S,
        initial_bed_temperature_c=HOT_TEMPERATURE_C,
        inlet_temperature_c=RETURN_TEMPERATURE_C,
        duration_s=REFERENCE_DURATION_S,
        n_steps=REFERENCE_N_STEPS,
    )
    reference_curve = discharge_power_curve(
        reference_result, PROCESS_TEMPERATURE_C, DELTA_T_MIN_HOT_SIDE_C
    )
    # Both ascending for np.interp: SOC declines as time increases, so
    # reverse both series the same way discharge_curve.py's own fitting
    # routine does for exactly this reason.
    ref_time_ascending = reference_curve["time_s"].to_numpy()
    ref_soc_ascending = reference_curve["state_of_charge"].to_numpy()[::-1]
    ref_time_for_soc = reference_curve["time_s"].to_numpy()[::-1]
    ref_power_ascending = reference_curve["deliverable_power_mw"].to_numpy()

    def _reference_power_at_soc_and_offset(matched_soc: float, offset_s: float) -> float:
        t_ref_start = float(np.interp(matched_soc, ref_soc_ascending, ref_time_for_soc))
        t_ref = min(t_ref_start + offset_s, ref_time_ascending[-1])
        return float(np.interp(t_ref, ref_time_ascending, ref_power_ascending))

    records: list[dict[str, Any]] = []
    recipe_summaries: list[dict[str, Any]] = []
    for recipe_name, legs in RECIPES.items():
        fluid, solid, leg_log = _run_recipe(config, legs)
        achieved_soc = bed_stored_energy_j(config, fluid, solid, RETURN_TEMPERATURE_C) / ref_energy

        probe = simulate_discharge(
            config,
            mass_flow_kg_per_s=MASS_FLOW_KG_PER_S,
            initial_bed_temperature_c=fluid,
            initial_solid_temperature_c=solid,
            inlet_temperature_c=RETURN_TEMPERATURE_C,
            duration_s=SHORT_HORIZON_S,
            n_steps=PROBE_N_STEPS,
        )
        # discharge_power_curve's own "state_of_charge" column self-
        # normalises against *this probe's own* t=0 energy, meaningless
        # here (every segment before it already spent real energy); only
        # its time_s/deliverable_power_mw/outlet_temperature_c columns are
        # used, against the achieved_soc computed above instead.
        probe_curve = discharge_power_curve(probe, PROCESS_TEMPERATURE_C, DELTA_T_MIN_HOT_SIDE_C)

        is_control = recipe_name.startswith("monotonic_")
        for checkpoint_s in CHECKPOINTS_S:
            idx = int((probe_curve["time_s"] - checkpoint_s).abs().idxmin())
            row = probe_curve.loc[idx]
            reference_power = _reference_power_at_soc_and_offset(achieved_soc, checkpoint_s)
            deviation_mw = float(row["deliverable_power_mw"]) - reference_power
            relative_deviation_pct = (
                100.0 * deviation_mw / reference_power if reference_power > 1e-6 else None
            )
            records.append(
                {
                    "recipe": recipe_name,
                    "is_control": is_control,
                    "achieved_soc": achieved_soc,
                    "checkpoint_s": checkpoint_s,
                    "probe_deliverable_power_mw": float(row["deliverable_power_mw"]),
                    "reference_deliverable_power_mw": reference_power,
                    "deviation_mw": deviation_mw,
                    "relative_deviation_pct": relative_deviation_pct,
                }
            )
        recipe_summaries.append(
            {"recipe": recipe_name, "legs": leg_log, "achieved_soc": achieved_soc}
        )
        print(
            f"{recipe_name:16s}  achieved_soc={achieved_soc:.4f}  "
            f"{'[CONTROL]' if is_control else ''}"
        )

    table = pd.DataFrame.from_records(records)
    table.to_csv(output_dir / "cycled_state_vs_reference_curve.csv", index=False)

    # Verdict: non-trivial (checkpoint > 0), non-control rows only, exactly
    # mirroring P0.3's own exclusion of the trivial t=0 checkpoint.
    non_trivial = table[(table["checkpoint_s"] > 0) & (~table["is_control"])]
    non_trivial_with_signal = non_trivial[non_trivial["relative_deviation_pct"].notna()]
    max_relative_deviation_pct = (
        float(non_trivial_with_signal["relative_deviation_pct"].abs().max())
        if len(non_trivial_with_signal)
        else None
    )

    control_rows = table[table["is_control"] & (table["checkpoint_s"] > 0)]
    control_rows_with_signal = control_rows[control_rows["relative_deviation_pct"].notna()]
    max_control_deviation_pct = (
        float(control_rows_with_signal["relative_deviation_pct"].abs().max())
        if len(control_rows_with_signal)
        else 0.0
    )
    methodology_control_passed = max_control_deviation_pct < 0.5  # [assumption]; near-0 expected

    scalar_soc_survives_cycling = (
        max_relative_deviation_pct is not None
        and max_relative_deviation_pct < SCATTER_THRESHOLD * 100
    )

    manifest = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "case": "packed_bed_300c_flat reference bed (default_packed_bed_config)",
        "research_question": (
            "P0.3 found scalar SOC insufficient for hand-constructed fields. Does the "
            "single discharge-only trajectory's own Pmax(SOC) curve -- the one this "
            "project's dispatch LP actually uses -- still predict near-term deliverable "
            "power correctly for a bed reaching that same SOC via a realistic "
            "charge/discharge history, rather than by hand construction?"
        ),
        "mass_flow_kg_per_s": MASS_FLOW_KG_PER_S,
        "hot_temperature_c": HOT_TEMPERATURE_C,
        "return_temperature_c": RETURN_TEMPERATURE_C,
        "process_temperature_c": PROCESS_TEMPERATURE_C,
        "delta_t_min_hot_side_c": DELTA_T_MIN_HOT_SIDE_C,
        "short_horizon_s": SHORT_HORIZON_S,
        "checkpoints_s": CHECKPOINTS_S,
        "recipes": {name: legs for name, legs in RECIPES.items()},
        "recipe_summaries": recipe_summaries,
        "methodology_control_note": (
            "monotonic_2.0h and monotonic_3.5h have no charging leg: they reproduce the "
            "reference trajectory's own state by construction, so their own deviation "
            "should be ~0%. This is a check on the comparison methodology itself, not a "
            "finding about cycling."
        ),
        "max_control_deviation_pct": max_control_deviation_pct,
        "methodology_control_passed": methodology_control_passed,
        "scatter_threshold_pct": SCATTER_THRESHOLD * 100,
        "scatter_threshold_note": (
            "[assumption]; reused from P0.3's own threshold, not a literature figure."
        ),
        "max_relative_deviation_pct_excluding_controls_and_t0": max_relative_deviation_pct,
        "scalar_soc_survives_realistic_cycling": scalar_soc_survives_cycling,
    }
    (output_dir / "run_manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )

    print()
    print(
        f"Methodology control (monotonic recipes) max deviation: {max_control_deviation_pct:.4f}%"
    )
    print(f"Methodology control passed (<0.5%): {methodology_control_passed}")
    print(
        "Max relative deviation, realistic cycles, excluding t=0 "
        f"(threshold {SCATTER_THRESHOLD * 100:.1f}%): {max_relative_deviation_pct}"
    )
    print(f"Scalar SOC survives realistic cycling: {scalar_soc_survives_cycling}")
    print(f"Written to {output_dir}")


if __name__ == "__main__":
    main()
