"""P2.1: duration-family capability curves as committed, self-contained evidence.

Usage: python scripts/run_capability_curves_experiment.py

Every prior duration-family run (`run_phase_c2_duration_matched_experiment.py`,
`run_phase_c_full_matrix_experiment.py`) builds a discharge curve at each
design duration internally, uses it to solve a pair of annual dispatch LPs,
and records only the paired-solve KPIs in its own manifest -- the curve
itself, and the flow physics that produced it, are a means to that end, not
committed evidence in their own right (only the headline duration's
breakpoints get written to disk). Roadmap P2.1 asks for the curves
themselves, at every duration in the same grid, as standalone artifacts:
"Generate curves for the same duration grid used in the paired annual
model," each with a manifest recording "geometry; mass flow and mass flux;
Re, Pr, Nu; h_v; temperatures; duration; timestep/node resolution; process
quality threshold; scaling family definition."

Scope: packed bed only, at both its process-temperature cases (300 C and
400 C). The roadmap's own framing of P2 is specific to the packed bed's
mass-flow/thermocline trade-off ("higher flow -> potentially lower outlet
temperature / faster thermocline movement"): two-tank molten salt has no
thermocline to move (`molten_salt_dynamics.py`'s own module docstring), and
PCM's near-isothermal latent plateau does not develop one either, so
neither technology has the design tension this section exists to
characterise. `mass_flow_for_target_duration` already exists for both
(built for Phase C3), so extending this script to them would be
mechanical if ever needed; not done here because the roadmap does not ask
for it here.

P2.2 (a full feasible-mass-flow capability envelope, choosing the highest
*net useful* power after parasitics at each physical state) is explicitly
deferred by the roadmap itself ("Do not jump to this until the simpler
duration-family comparison is correct") and is not attempted here: this
script produces one curve per (case, duration) at the mass flow that
duration's own `mass_flow_for_target_duration` solves for, the "simpler
duration-family comparison," not a swept envelope.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from tes_screen.discharge_curve import (  # noqa: E402
    fit_piecewise_discharge_curve,
    mass_flow_for_target_duration,
    piecewise_curve_to_frame,
    verify_piecewise_curve_is_safe,
)
from tes_screen.packed_bed_dynamics import (  # noqa: E402
    default_packed_bed_config,
    discharge_power_curve,
    flow_diagnostics,
    simulate_discharge,
)

# Same grid run_phase_c2_duration_matched_experiment.py sweeps, per the
# roadmap's own "same duration grid used in the paired annual model"
# instruction.
DESIGN_DURATIONS_HOURS = [2.0, 4.0, 6.0, 8.0, 12.0]
DELTA_T_MIN_HOT_SIDE_C = 0.0  # [assumption]; see run_packed_bed_dynamics.py's own note (P0.2)
REFERENCE_N_STEPS = 1500
PRIMARY_N_SEGMENTS = 5

# (case_name, config_path, initial_bed_temperature_c, inlet_temperature_c
# (T_return), process_temperature_c) -- the same temperature convention
# run_phase_c_full_matrix_experiment.py uses for packed bed.
CASES = [
    ("packed_bed_300c_flat", "configs/packed_bed_300c_flat.yaml", 400.0, 320.0, 300.0),
    ("packed_bed_400c_flat", "configs/packed_bed_400c_flat.yaml", 500.0, 420.0, 400.0),
]


def _curve_for_duration(
    design_duration_hours: float,
    initial_bed_temperature_c: float,
    inlet_temperature_c: float,
    process_temperature_c: float,
):
    bed_config = default_packed_bed_config()
    mass_flow = mass_flow_for_target_duration(
        bed_config,
        target_duration_hours=design_duration_hours,
        initial_bed_temperature_c=initial_bed_temperature_c,
        inlet_temperature_c=inlet_temperature_c,
        process_temperature_c=process_temperature_c,
        delta_t_min_hot_side_c=DELTA_T_MIN_HOT_SIDE_C,
    )
    mass_flux = mass_flow / bed_config.cross_section_area_m2
    diagnostics = flow_diagnostics(bed_config, mass_flux)
    result = simulate_discharge(
        bed_config,
        mass_flow_kg_per_s=mass_flow,
        initial_bed_temperature_c=initial_bed_temperature_c,
        inlet_temperature_c=inlet_temperature_c,
        duration_s=design_duration_hours * 2 * 3600.0,
        n_steps=REFERENCE_N_STEPS,
    )
    curve = fit_piecewise_discharge_curve(
        result, process_temperature_c, DELTA_T_MIN_HOT_SIDE_C, n_segments=PRIMARY_N_SEGMENTS
    )
    safety = verify_piecewise_curve_is_safe(
        curve, result, process_temperature_c, DELTA_T_MIN_HOT_SIDE_C
    )
    power_curve = discharge_power_curve(result, process_temperature_c, DELTA_T_MIN_HOT_SIDE_C)
    return bed_config, mass_flow, mass_flux, diagnostics, result, curve, safety, power_curve


def main() -> None:
    output_root = Path("outputs") / "capability_curves"
    output_root.mkdir(parents=True, exist_ok=True)

    top_level_manifest = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "roadmap_item": "P2.1 (duration-family curve generation)",
        "scope_note": (
            "Packed bed only, both process-temperature cases (300 C and "
            "400 C): the roadmap's own framing of P2 is specific to the "
            "packed bed's mass-flow/thermocline trade-off. Molten salt (no "
            "thermocline) and PCM (near-isothermal latent plateau) are not "
            "covered here; see this script's own module docstring."
        ),
        "design_durations_swept_hours": DESIGN_DURATIONS_HOURS,
        "delta_t_min_hot_side_c": DELTA_T_MIN_HOT_SIDE_C,
        "n_segments": PRIMARY_N_SEGMENTS,
        "scaling_family_definition": (
            "Duration family (roadmap P0.1/P2.1): geometry (bed_length_m, "
            "cross_section_area_m2, particle_diameter_m, porosity, n_nodes) "
            "is held fixed at the default reference bed's own values across "
            "every duration; only mass flow (and therefore mass flux) "
            "varies, solved in closed form so the resulting curve's own "
            "power/energy ratio k equals 1/tau exactly "
            "(discharge_curve.mass_flow_for_target_duration). This is a "
            "different family from P1's modular-area scaling (which varies "
            "cross-sectional area and mass flow together, at fixed mass "
            "flux, to change store size at fixed duration): P0.1/P2.1 "
            "deliberately varies mass flux per duration, changing the "
            "curve's own shape; P1 deliberately holds mass flux fixed, "
            "preserving it."
        ),
        "cases": [],
    }

    for case_name, config_path, initial_temp_c, inlet_temp_c, process_temp_c in CASES:
        case_summary = {"case_name": case_name, "config_path": config_path, "durations": []}
        for tau in DESIGN_DURATIONS_HOURS:
            (
                bed_config,
                mass_flow,
                mass_flux,
                diagnostics,
                result,
                curve,
                safety,
                power_curve,
            ) = _curve_for_duration(tau, initial_temp_c, inlet_temp_c, process_temp_c)

            case_dir = output_root / f"tau_{tau:g}h" / case_name
            case_dir.mkdir(parents=True, exist_ok=True)
            power_curve.to_csv(case_dir / "discharge_power_curve.csv", index=False)
            piecewise_curve_to_frame(curve).to_csv(
                case_dir / "piecewise_curve_breakpoints.csv", index=False
            )

            manifest = {
                "case_name": case_name,
                "config_path": config_path,
                "design_duration_hours": tau,
                "geometry": {
                    "bed_length_m": bed_config.bed_length_m,
                    "cross_section_area_m2": bed_config.cross_section_area_m2,
                    "porosity": bed_config.porosity,
                    "particle_diameter_m": bed_config.particle_diameter_m,
                    "n_nodes": bed_config.n_nodes,
                },
                "mass_flow_kg_per_s": mass_flow,
                "mass_flux_kg_per_m2s": mass_flux,
                "reynolds": diagnostics.reynolds,
                "prandtl": diagnostics.prandtl,
                "nusselt": diagnostics.nusselt,
                "volumetric_heat_transfer_coefficient_w_per_m3k": (
                    diagnostics.volumetric_heat_transfer_coefficient_w_per_m3k
                ),
                "temperatures_c": {
                    "initial_bed_temperature_c": initial_temp_c,
                    "inlet_temperature_c_t_return": inlet_temp_c,
                    "process_temperature_c": process_temp_c,
                },
                "process_quality_threshold_c": process_temp_c + DELTA_T_MIN_HOT_SIDE_C,
                "delta_t_min_hot_side_c": DELTA_T_MIN_HOT_SIDE_C,
                "resolution": {
                    "n_nodes": bed_config.n_nodes,
                    "n_steps": REFERENCE_N_STEPS,
                    "duration_s": tau * 2 * 3600.0,
                },
                "curve_fit_n_segments": PRIMARY_N_SEGMENTS,
                "curve_fit_max_overestimate_mw": safety["max_overestimate_mw"],
                "curve_fit_max_underestimate_mw": safety["max_underestimate_mw"],
                "curve_fit_mean_absolute_error_mw": safety["mean_absolute_error_mw"],
                "reference_rated_power_mw": curve.reference_rated_power_mw,
                "reference_energy_capacity_mwh": curve.reference_energy_capacity_mwh,
                "k_mw_per_mwh": curve.k_mw_per_mwh,
            }
            (case_dir / "manifest.json").write_text(
                json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
            )
            case_summary["durations"].append(manifest)
            print(
                f"{case_name:20s} tau={tau:5.2f}h  mass_flow={mass_flow:6.3f} kg/s  "
                f"mass_flux={mass_flux:6.4f} kg/m2s  Re={diagnostics.reynolds:8.2f}  "
                f"Pr={diagnostics.prandtl:.4f}  Nu={diagnostics.nusselt:7.3f}  "
                f"h_v={diagnostics.volumetric_heat_transfer_coefficient_w_per_m3k:10.2f} W/m3K  "
                f"overestimate={safety['max_overestimate_mw']:.2e} MW"
            )
        top_level_manifest["cases"].append(case_summary)

    (output_root / "run_manifest.json").write_text(
        json.dumps(top_level_manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(f"Written to {output_root}")


if __name__ == "__main__":
    main()
