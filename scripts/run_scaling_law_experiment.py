"""P1: test the modular-area-scaling exit criterion (roadmap P1.1/P1.2).

Usage: python scripts/run_scaling_law_experiment.py

The dispatch LP's piecewise discharge-limit constraint,
`p_dis[t] <= a_i*level[t] + b_i*E_cap`, rescales one reference bed's fitted
curve linearly to whatever storage energy capacity a case actually sizes --
implicitly assuming the *normalized* curve (state of charge vs. fraction of
full-charge power) is the same shape regardless of how big the physical bed
actually is. That assumption previously rested on an abstract "same
duration ratio" argument, not a stated physical mechanism.

`packed_bed_dynamics.scale_parallel_bed` gives it one: hold bed length,
particle diameter, porosity, material properties and node count fixed;
scale cross-sectional area and mass flow together by the same factor. Under
this specific family, mass flux (and therefore Reynolds number, the
Wakao-Kaguei Nusselt number, the volumetric heat transfer coefficient, and
every coefficient in the governing PDE, none of which reference area
directly) stays exactly fixed, so the simulated temperature field is
identical at every scale -- only the *totals* built from it scale with
area, and a normalized curve (a ratio of two same-scaling quantities)
should collapse onto the reference exactly.

This script runs that check at five scale factors (0.25x, 0.5x, 1x, 2x,
4x) and reports the maximum normalized-curve deviation, per P1.2's own
exit criterion: "small enough to support the scaling approximation, or
the approximation is rejected." An explicit threshold decides which,
stated here rather than left to eyeball judgement.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from tes_screen.discharge_curve import fit_piecewise_discharge_curve  # noqa: E402
from tes_screen.packed_bed_dynamics import (  # noqa: E402
    default_packed_bed_config,
    discharge_power_curve,
    scale_parallel_bed,
    simulate_discharge,
)

REFERENCE_MASS_FLOW_KG_PER_S = 3.0  # matches Phase B/C's own reference draw rate
INITIAL_BED_TEMPERATURE_C = 400.0
INLET_TEMPERATURE_C = 320.0
PROCESS_TEMPERATURE_C = 300.0
DELTA_T_MIN_HOT_SIDE_C = 0.0  # [assumption]; see run_packed_bed_dynamics.py's own note (P0.2)
DURATION_S = 20 * 3600.0
N_STEPS = 1000
SCALE_FACTORS = [0.25, 0.5, 1.0, 2.0, 4.0]
# [assumption]: not a literature figure -- there is no citable standard for
# this check. Set well above float64 noise (~1e-12 for this arithmetic) and
# well below anything that would matter for the annual LP's own MW-scale
# rounding, so it cannot pass by accident and would catch a real physical
# breakdown of the scaling family, not just numerical roundoff.
DEVIATION_THRESHOLD = 1e-6


def _normalized_curve(config, mass_flow_kg_per_s: float) -> pd.DataFrame:
    result = simulate_discharge(
        config,
        mass_flow_kg_per_s=mass_flow_kg_per_s,
        initial_bed_temperature_c=INITIAL_BED_TEMPERATURE_C,
        inlet_temperature_c=INLET_TEMPERATURE_C,
        duration_s=DURATION_S,
        n_steps=N_STEPS,
    )
    curve = discharge_power_curve(result, PROCESS_TEMPERATURE_C, DELTA_T_MIN_HOT_SIDE_C)
    power_fraction = curve["deliverable_power_mw"] / curve["deliverable_power_mw"].iloc[0]
    return pd.DataFrame(
        {
            "time_s": curve["time_s"],
            "state_of_charge": curve["state_of_charge"],
            "power_fraction_of_rated": power_fraction,
        }
    ), result, curve


def main() -> None:
    output_dir = Path("outputs") / "scaling_law"
    output_dir.mkdir(parents=True, exist_ok=True)
    reference_config = default_packed_bed_config()

    reference_normalized, reference_result, _reference_curve = _normalized_curve(
        reference_config, REFERENCE_MASS_FLOW_KG_PER_S
    )
    reference_soc = reference_normalized["state_of_charge"].to_numpy()
    reference_fraction = reference_normalized["power_fraction_of_rated"].to_numpy()
    reference_k = fit_piecewise_discharge_curve(
        reference_result, PROCESS_TEMPERATURE_C, DELTA_T_MIN_HOT_SIDE_C, n_segments=5
    ).k_mw_per_mwh

    all_rows = []
    per_scale_results = []
    for scale_factor in SCALE_FACTORS:
        scaled_config, scaled_mass_flow = scale_parallel_bed(
            reference_config, REFERENCE_MASS_FLOW_KG_PER_S, scale_factor
        )
        normalized, result, curve = _normalized_curve(scaled_config, scaled_mass_flow)
        soc = normalized["state_of_charge"].to_numpy()
        fraction = normalized["power_fraction_of_rated"].to_numpy()

        soc_deviation = float(np.abs(soc - reference_soc).max())
        fraction_deviation = float(np.abs(fraction - reference_fraction).max())

        fitted_curve = fit_piecewise_discharge_curve(
            result, PROCESS_TEMPERATURE_C, DELTA_T_MIN_HOT_SIDE_C, n_segments=5
        )
        k_deviation = float(abs(fitted_curve.k_mw_per_mwh - reference_k))

        normalized_with_scale = normalized.copy()
        normalized_with_scale.insert(0, "scale_factor", scale_factor)
        all_rows.append(normalized_with_scale)

        per_scale_results.append(
            {
                "scale_factor": scale_factor,
                "cross_section_area_m2": scaled_config.cross_section_area_m2,
                "mass_flow_kg_per_s": scaled_mass_flow,
                "reference_energy_capacity_mwh": fitted_curve.reference_energy_capacity_mwh,
                "reference_rated_power_mw": fitted_curve.reference_rated_power_mw,
                "k_mw_per_mwh": fitted_curve.k_mw_per_mwh,
                "k_deviation_from_reference": k_deviation,
                "max_state_of_charge_deviation": soc_deviation,
                "max_power_fraction_deviation": fraction_deviation,
            }
        )
        print(
            f"scale={scale_factor:5.2f}x  A={scaled_config.cross_section_area_m2:6.2f} m2  "
            f"m_dot={scaled_mass_flow:5.2f} kg/s  k={fitted_curve.k_mw_per_mwh:.6f} MW/MWh  "
            f"max SOC dev={soc_deviation:.3e}  max power-fraction dev={fraction_deviation:.3e}"
        )

    table = pd.concat(all_rows, ignore_index=True)
    table.to_csv(output_dir / "normalized_curves_by_scale.csv", index=False)

    max_deviation = max(
        max(r["max_state_of_charge_deviation"], r["max_power_fraction_deviation"])
        for r in per_scale_results
    )
    scaling_approximation_supported = max_deviation < DEVIATION_THRESHOLD

    manifest = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "case": "packed_bed default config, modular area scaling (roadmap P1.1)",
        "note": (
            "Tests whether the dispatch LP's linear b_i*E_cap rescaling of one "
            "reference bed's fitted discharge curve to an arbitrary storage "
            "capacity is physically defensible under a specific, stated "
            "scaling family: cross-sectional area and mass flow scale "
            "together, holding bed length, particle diameter, porosity, "
            "material properties, and mass flux (and therefore Reynolds "
            "number, the Wakao-Kaguei Nusselt number, and the volumetric "
            "heat transfer coefficient) fixed. A normalized curve (state of "
            "charge; power as a fraction of that run's own full-charge "
            "power) should collapse onto the reference (1x) run's own "
            "normalized curve at every scale factor if the family is valid."
        ),
        "reference_mass_flow_kg_per_s": REFERENCE_MASS_FLOW_KG_PER_S,
        "scale_factors": SCALE_FACTORS,
        "duration_s": DURATION_S,
        "n_steps": N_STEPS,
        "deviation_threshold": DEVIATION_THRESHOLD,
        "deviation_threshold_note": "[assumption]; not a literature figure.",
        "per_scale_results": per_scale_results,
        "max_deviation_across_all_scale_factors": max_deviation,
        "exit_criterion": {
            "text": (
                "Maximum normalized curve deviation is reported and small "
                "enough to support the scaling approximation, or the "
                "approximation is rejected."
            ),
            "scaling_approximation_supported": scaling_approximation_supported,
        },
    }
    (output_dir / "run_manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )

    print(f"Max deviation across all scale factors: {max_deviation:.3e}")
    print(f"Scaling approximation supported (threshold {DEVIATION_THRESHOLD:.0e}): "
          f"{scaling_approximation_supported}")
    print(f"Written to {output_dir}")

    if not scaling_approximation_supported:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
