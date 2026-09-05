"""P0.3: the state-sufficiency experiment -- is scalar SOC enough?

Usage: python scripts/run_state_sufficiency_experiment.py

Phase C's discharge-limit curve reads deliverable power off one trajectory
(a fully-charged, spatially uniform bed, discharged continuously at one
mass flow) as a function of total stored energy alone. That treats total
energy (SOC) as a *sufficient* state for predicting outlet capability --
but a packed bed is a distributed-temperature system, so two bed states
holding the same total energy but arranged differently along the bed (a
sharp thermocline near one end vs a broad, smeared one) could plausibly
deliver different near-term power. This script tests that directly, per
the roadmap's own short-term research test (P0.3), rather than assuming
the single-trajectory curve generalises to states it was never fit from.

For each of several target energy fractions, `state_sufficiency.py`
constructs four temperature fields holding (as close as node-count
discretisation allows) the same total energy but different spatial
structure: uniform, a sharp step with the hot block at the inlet, the
mirror-image step with the hot block at the outlet (same energy, opposite
arrangement), and a broad linear ramp. Each field is discharged briefly
(the same short horizon, same mass flow, same return temperature for every
field) and deliverable power is read off at several short-term checkpoints.

**The t=0 checkpoint is not informative on its own** and is included only
for transparency: at t=0, the recorded outlet temperature is exactly
whatever temperature was assigned to the field's own outlet-end node, so
any two fields that differ there will trivially show different "immediate"
power regardless of the rest of the bed's structure. The real test is at
the later checkpoints, once fluid has actually convected through a
meaningful length of the bed and the outlet reading reflects genuine
upstream structure, not just the prescribed initial condition at one node.

Interpretation follows the roadmap's own instruction: relative scatter
across the profile family at fixed (energy fraction, checkpoint) below
`SCATTER_THRESHOLD` (an explicit [assumption], not a literature figure) is
read as "scalar SOC is an adequate reduction for this screening use";
above it is read as a real, reportable limitation of the scalar-SOC
approximation -- not hidden, per the roadmap's explicit instruction not to
bury a negative result here. Until this test exists project-wide, the
existing single-trajectory relation is documented as a
"trajectory-derived SOC capability curve," not a universal law; see
README/MODEL_CARD.

A fifth profile family the roadmap names -- "profiles taken from realistic
charge/discharge histories" -- needs a charging dynamic model this project
does not have (Phase B is discharge-only), so it is left undone rather
than approximated; see `state_sufficiency.py`'s own module docstring.
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
    default_packed_bed_config,
    discharge_power_curve,
    simulate_discharge,
)
from tes_screen.state_sufficiency import (  # noqa: E402
    achieved_energy_fraction,
    smeared_field,
    step_field,
    uniform_field,
)

HOT_TEMPERATURE_C = 400.0
RETURN_TEMPERATURE_C = 320.0
PROCESS_TEMPERATURE_C = 300.0
DELTA_T_MIN_HOT_SIDE_C = 0.0  # [assumption]; see run_packed_bed_dynamics.py's own note (P0.2)
MASS_FLOW_KG_PER_S = 3.0  # matches the Phase B/C reference bed's own draw rate
ENERGY_FRACTIONS = [0.3, 0.5, 0.7]
SHORT_HORIZON_S = 1800.0  # 30 min: ~1.5-2.5% of a full ~20-30h breakthrough discharge
N_STEPS = 300  # 6s resolution
CHECKPOINTS_S = [0.0, 300.0, 600.0, 1200.0, 1800.0]
# [assumption]: relative scatter (max-min)/mean across the profile family, at
# fixed energy fraction and checkpoint, below this is read as "scalar SOC is
# an adequate screening reduction"; above it, a reportable limitation. Not a
# literature figure -- there isn't a citable standard for this test.
SCATTER_THRESHOLD = 0.05


def _profile_family(energy_fraction: float, bed_config) -> dict[str, np.ndarray]:
    args = (bed_config, energy_fraction, HOT_TEMPERATURE_C, RETURN_TEMPERATURE_C)
    return {
        "uniform": uniform_field(*args),
        "step_hot_at_inlet": step_field(*args, hot_side="inlet"),
        "step_hot_at_outlet": step_field(*args, hot_side="outlet"),
        "smeared": smeared_field(*args),
    }


def _nearest_checkpoint_rows(power_curve: pd.DataFrame, checkpoints_s: list[float]) -> pd.DataFrame:
    indices = [int((power_curve["time_s"] - t).abs().idxmin()) for t in checkpoints_s]
    rows = power_curve.loc[indices].copy()
    rows.insert(0, "checkpoint_s", checkpoints_s)
    return rows


def main() -> None:
    output_dir = Path("outputs") / "state_sufficiency"
    output_dir.mkdir(parents=True, exist_ok=True)
    bed_config = default_packed_bed_config()

    records: list[dict[str, Any]] = []
    for energy_fraction in ENERGY_FRACTIONS:
        profiles = _profile_family(energy_fraction, bed_config)
        for profile_name, field in profiles.items():
            achieved = achieved_energy_fraction(
                bed_config, field, HOT_TEMPERATURE_C, RETURN_TEMPERATURE_C
            )
            result = simulate_discharge(
                bed_config,
                mass_flow_kg_per_s=MASS_FLOW_KG_PER_S,
                initial_bed_temperature_c=field,
                inlet_temperature_c=RETURN_TEMPERATURE_C,
                duration_s=SHORT_HORIZON_S,
                n_steps=N_STEPS,
            )
            power_curve = discharge_power_curve(
                result, PROCESS_TEMPERATURE_C, DELTA_T_MIN_HOT_SIDE_C
            )
            checkpoint_rows = _nearest_checkpoint_rows(power_curve, CHECKPOINTS_S)
            for _, row in checkpoint_rows.iterrows():
                records.append(
                    {
                        "target_energy_fraction": energy_fraction,
                        "achieved_energy_fraction": achieved,
                        "profile": profile_name,
                        "checkpoint_s": row["checkpoint_s"],
                        "outlet_temperature_c": row["outlet_temperature_c"],
                        "storage_heat_mw": row["storage_heat_mw"],
                        "deliverable_power_mw": row["deliverable_power_mw"],
                    }
                )

    table = pd.DataFrame.from_records(records)
    table.to_csv(output_dir / "useful_power_vs_soc.csv", index=False)

    scatter_rows = []
    for (energy_fraction, checkpoint_s), group in table.groupby(
        ["target_energy_fraction", "checkpoint_s"]
    ):
        power = group["deliverable_power_mw"].to_numpy()
        mean_power = float(power.mean())
        relative_scatter = (
            float((power.max() - power.min()) / mean_power) if mean_power > 0 else 0.0
        )
        scatter_rows.append(
            {
                "target_energy_fraction": energy_fraction,
                "checkpoint_s": checkpoint_s,
                "power_min_mw": float(power.min()),
                "power_max_mw": float(power.max()),
                "power_mean_mw": mean_power,
                "relative_scatter": relative_scatter,
                "is_trivial_t0_comparison": bool(checkpoint_s == 0.0),
            }
        )
    scatter = pd.DataFrame.from_records(scatter_rows).sort_values(
        ["target_energy_fraction", "checkpoint_s"]
    )
    scatter.to_csv(output_dir / "scatter_by_soc_and_checkpoint.csv", index=False)

    non_trivial = scatter[~scatter["is_trivial_t0_comparison"]]
    max_relative_scatter = float(non_trivial["relative_scatter"].max())
    scalar_soc_adequate = bool((non_trivial["relative_scatter"] < SCATTER_THRESHOLD).all())

    # step_hot_at_inlet places the hot block where cold fluid enters first,
    # so a real discharge (which always erodes from the inlet) could not
    # reach that arrangement without an external recharge/mixing process --
    # unlike the other three, which are all plausible states along some
    # discharge or partial-discharge trajectory. Reported alongside the
    # full-family number, not instead of it: excluding the least reachable
    # construction is a legitimate operational-relevance caveat, not a way
    # to quietly shrink an inconvenient result.
    restricted = table[(table["profile"] != "step_hot_at_inlet") & (table["checkpoint_s"] > 0)]
    restricted_scatter_rows = []
    for _group_key, group in restricted.groupby(["target_energy_fraction", "checkpoint_s"]):
        power = group["deliverable_power_mw"].to_numpy()
        restricted_scatter_rows.append(float((power.max() - power.min()) / power.mean()))
    max_relative_scatter_excluding_unreachable_profile = float(max(restricted_scatter_rows))

    manifest = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "case": "packed_bed_300c_flat reference bed (default_packed_bed_config)",
        "research_question": (
            "Is total stored energy (scalar SOC) a sufficient state for predicting "
            "near-term deliverable power, or does the spatial arrangement of that "
            "energy along the bed also matter?"
        ),
        "energy_fractions_swept": ENERGY_FRACTIONS,
        "profile_family": ["uniform", "step_hot_at_inlet", "step_hot_at_outlet", "smeared"],
        "profile_family_note": (
            "A fifth family the roadmap names (profiles from realistic charge/"
            "discharge histories) needs a charging dynamic model this project "
            "does not have; left undone rather than approximated."
        ),
        "checkpoints_s": CHECKPOINTS_S,
        "t0_checkpoint_caveat": (
            "The t=0 row is not informative on its own: it exactly reflects the "
            "temperature assigned to the field's own outlet-end node, so it is "
            "expected to scatter regardless of the rest of the bed's structure. "
            "The verdict below excludes it."
        ),
        "scatter_threshold": SCATTER_THRESHOLD,
        "scatter_threshold_note": "[assumption]; not a literature figure.",
        "max_relative_scatter_excluding_t0": max_relative_scatter,
        "max_relative_scatter_excluding_t0_and_step_hot_at_inlet": (
            max_relative_scatter_excluding_unreachable_profile
        ),
        "step_hot_at_inlet_reachability_note": (
            "step_hot_at_inlet places the hot block where cold fluid enters first; "
            "a real discharge always erodes from the inlet, so this arrangement is "
            "not reachable by discharging alone, unlike the other three profiles. "
            "Kept in the headline scatter number, not excluded by default -- the "
            "restricted number above is reported alongside it, not in place of it."
        ),
        "scalar_soc_adequate_for_screening": scalar_soc_adequate,
        "mass_flow_kg_per_s": MASS_FLOW_KG_PER_S,
        "hot_temperature_c": HOT_TEMPERATURE_C,
        "return_temperature_c": RETURN_TEMPERATURE_C,
        "process_temperature_c": PROCESS_TEMPERATURE_C,
        "delta_t_min_hot_side_c": DELTA_T_MIN_HOT_SIDE_C,
        "short_horizon_s": SHORT_HORIZON_S,
    }
    (output_dir / "run_manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )

    print(f"Max relative scatter (excluding trivial t=0): {max_relative_scatter:.4f}")
    print(
        "Max relative scatter (excluding t=0 and step_hot_at_inlet): "
        f"{max_relative_scatter_excluding_unreachable_profile:.4f}"
    )
    print(
        f"Scalar SOC adequate for screening (threshold {SCATTER_THRESHOLD}): {scalar_soc_adequate}"
    )
    print(f"Written to {output_dir}")


if __name__ == "__main__":
    main()
