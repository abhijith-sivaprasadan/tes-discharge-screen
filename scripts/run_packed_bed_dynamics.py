"""Generate and commit packed-bed discharge curves, with their generating config.

Usage: python scripts/run_packed_bed_dynamics.py

Runs the Phase B shadow twin (`tes_screen.packed_bed_dynamics`) at several
constant draw rates, verifies the three analytic limits and the energy
conservation identity at runtime (not just in pytest), and writes
`outputs/packed_bed_dynamics/{bed_config.json, discharge_<rate>.csv,
run_manifest.json}` per the Phase B exit criterion: "discharge curves are
produced and committed with their generating configs."
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import numpy as np  # noqa: E402

from tes_screen.packed_bed_dynamics import (  # noqa: E402
    default_packed_bed_config,
    discharge_power_curve,
    simulate_discharge,
)

PROCESS_TEMPERATURE_C = 300.0
INITIAL_BED_TEMPERATURE_C = 400.0
INLET_TEMPERATURE_C = 320.0
DRAW_RATES_KG_PER_S = [1.5, 3.0, 6.0]
DURATION_S = 30 * 3600.0
N_STEPS = 1500


def run_analytic_checks(config) -> dict[str, bool]:
    """Re-run the three B4 analytic checks here, not only in pytest, so the
    committed manifest carries its own evidence that the twin was verified
    on the same code path that produced these curves."""
    checks: dict[str, bool] = {}

    zero_flow = simulate_discharge(
        config, 0.0, INITIAL_BED_TEMPERATURE_C, INLET_TEMPERATURE_C, 4 * 3600, n_steps=200
    )
    checks["zero_draw_rate_holds_at_initial_temperature"] = bool(
        np.allclose(zero_flow.trace["outlet_temperature_c"], INITIAL_BED_TEMPERATURE_C, atol=1e-9)
    )

    import dataclasses

    single_node = dataclasses.replace(config, n_nodes=1)
    single_node.validate()
    mass_flow = 2.0
    infinite_h = simulate_discharge(
        single_node,
        mass_flow,
        INITIAL_BED_TEMPERATURE_C,
        INLET_TEMPERATURE_C,
        3 * 3600,
        heat_transfer_coefficient_override_w_per_m3k=1e12,
        n_steps=4000,
    )
    volume = single_node.bed_length_m * single_node.cross_section_area_m2
    c_f = (
        single_node.porosity
        * single_node.air_density_kg_per_m3
        * single_node.air_specific_heat_j_per_kgk
    )
    c_s = (
        (1 - single_node.porosity)
        * single_node.rock_density_kg_per_m3
        * single_node.rock_specific_heat_j_per_kgk
    )
    tau = (c_f + c_s) * volume / (mass_flow * single_node.air_specific_heat_j_per_kgk)
    time_s = infinite_h.trace["time_s"].to_numpy()
    analytic = INLET_TEMPERATURE_C + (INITIAL_BED_TEMPERATURE_C - INLET_TEMPERATURE_C) * np.exp(
        -time_s / tau
    )
    checks["infinite_h_v_matches_well_mixed_tank"] = bool(
        np.allclose(
            infinite_h.trace["outlet_temperature_c"].to_numpy(), analytic, rtol=1e-3, atol=1e-2
        )
    )

    reference = simulate_discharge(
        config, 3.0, INITIAL_BED_TEMPERATURE_C, INLET_TEMPERATURE_C, DURATION_S, n_steps=N_STEPS
    )
    residual = reference.trace["energy_conservation_residual_j"].abs()
    initial_energy = reference.trace["bed_stored_energy_j"].iloc[0]
    checks["energy_conservation_holds"] = bool((residual / initial_energy < 1e-9).all())

    return checks


def main() -> None:
    config = default_packed_bed_config()
    output_dir = Path("outputs") / "packed_bed_dynamics"
    output_dir.mkdir(parents=True, exist_ok=True)

    (output_dir / "bed_config.json").write_text(
        json.dumps(config.to_dict(), indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )

    checks = run_analytic_checks(config)
    curves_written = []
    for rate in DRAW_RATES_KG_PER_S:
        result = simulate_discharge(
            config,
            rate,
            INITIAL_BED_TEMPERATURE_C,
            INLET_TEMPERATURE_C,
            DURATION_S,
            n_steps=N_STEPS,
        )
        curve = discharge_power_curve(result, PROCESS_TEMPERATURE_C)
        filename = f"discharge_curve_{rate:g}kgps.csv"
        curve.to_csv(output_dir / filename, index=False)
        curves_written.append(
            {
                "mass_flow_kg_per_s": rate,
                "file": filename,
                "final_state_of_charge": float(curve["state_of_charge"].iloc[-1]),
                "breakthrough_soc": (
                    float(curve.loc[curve["deliverable_power_mw"] <= 1e-9, "state_of_charge"].max())
                    if (curve["deliverable_power_mw"] <= 1e-9).any()
                    else None
                ),
            }
        )

    manifest = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "technology": "packed_bed",
        "process_temperature_c": PROCESS_TEMPERATURE_C,
        "initial_bed_temperature_c": INITIAL_BED_TEMPERATURE_C,
        "inlet_temperature_c": INLET_TEMPERATURE_C,
        "duration_s": DURATION_S,
        "n_steps": N_STEPS,
        "analytic_checks": checks,
        "analytic_checks_passed": all(checks.values()),
        "curves": curves_written,
        "note": (
            "Shadow twin only (src/tes_screen/packed_bed_dynamics.py). No FMU "
            "cross-check: no OpenModelica toolchain in this working environment. "
            "See modelica/tes_screen/package.mo and src/tes_screen/fmu.py."
        ),
    }
    (output_dir / "run_manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )

    print(f"Analytic checks passed: {manifest['analytic_checks_passed']} ({checks})")
    print(f"Written to {output_dir}")
    if not manifest["analytic_checks_passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
