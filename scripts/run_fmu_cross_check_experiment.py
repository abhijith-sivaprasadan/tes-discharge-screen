"""P4.2: FMU-vs-shadow-twin cross-check -- the roadmap's own "single
strongest verification story" for the packed-bed model.

Usage: python scripts/run_fmu_cross_check_experiment.py path/to/PackedBedThermocline.fmu

This script cannot run to completion in this working environment: `fmpy`
needs a compiled FMU binary matching the host platform, and the only FMU
this project has ever had compiled (by the user, via OMEdit on Windows,
after this repository fixed the package-name/directory mismatch that had
been silently blocking every earlier load attempt) contains only a
`binaries/win64/` folder, not `binaries/linux64/`, and this sandbox has no
Wine. It is meant to be run on whatever machine holds a working FMU plus a
Python environment with this project installed (`pip install -e .` or
`uv sync`) -- Windows, in the case that produced the FMU checked into this
repository's history. `tes_screen.fmu.simulate_fmu` already fails loudly,
not silently, when `fmpy` or a matching binary is unavailable; this script
adds nothing to change that.

Both halves of the comparison use the exact same physical scenario, chosen
to match `modelica/tes_screen/package.mo`'s own default parameters exactly
(which were themselves set to match `packed_bed_dynamics.default_packed_bed_config()`
-- see that file's parameter list against this project's own default bed):
mass_flow=3.0 kg/s, inlet (T_return)=320 C, initial bed temperature=400 C,
and critically a *fixed* volumetric heat transfer coefficient of
5800 W/(m3.K) on both sides (`heat_transfer_coefficient_override_w_per_m3k`
on the Python side; `volumetricHeatTransferCoefficient` is a fixed Modelica
parameter, "not recomputed" per its own comment) -- removing any risk of
comparing two different physics models on the pretence of comparing solver
implementations. A short probe of the shadow twin alone
(reported in the accompanying write-up) showed the outlet crosses the
thermocline breakthrough midpoint between 6h and 8h at these parameters, so
an 8-hour window gives full breakthrough with margin.

The FMU exposes only `outletTemperature`; it does not expose stored energy
or cumulative delivered heat directly. This script reconstructs delivered
energy from the FMU's own outlet-temperature trace using the identical
formula `simulate_discharge` uses internally
(`mass_flow * air_specific_heat_j_per_kgk * (T_out - T_inlet)`, integrated
over time) rather than comparing a quantity the FMU never actually output,
so "relative energy deviation" stays an apples-to-apples check on both
sides.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from tes_screen.fmu import simulate_fmu  # noqa: E402
from tes_screen.packed_bed_dynamics import (  # noqa: E402
    default_packed_bed_config,
    simulate_discharge,
)

MASS_FLOW_KG_PER_S = 3.0  # package.mo's massFlow
INLET_TEMPERATURE_C = 320.0  # package.mo's inletTemperature (T_return)
INITIAL_BED_TEMPERATURE_C = 400.0  # package.mo's initialBedTemperature
FIXED_H_V_W_PER_M3K = 5800.0  # package.mo's volumetricHeatTransferCoefficient
STOP_TIME_HOURS = 8.0
# For a Co-Simulation FMU, fmpy's `output_interval` *is* the communication
# step size handed to the FMU's own doStep() -- there is no separate finer
# internal integration happening underneath in this code path. This model
# is numerically stiff (fluid thermal capacity ~4600x below the rock's:
# fluidCapacityPerVolume=245 vs solidCapacityPerVolume=1.14e6 J/(m3.K)),
# and a first attempt at 60s blew up (`fmi2GetReal failed`, `a=inf`) well
# before the 8h window finished. The FMU's own modelDescription.xml
# publishes `DefaultExperiment stepSize="0.002"` -- 30,000x smaller than
# that first attempt -- as its author-recommended stable step; this default
# is a pragmatic middle ground, not that exact value (which would take
# millions of doStep calls), meant to be tuned down further via
# --output-interval-s if it still diverges.
OUTPUT_INTERVAL_S = 0.05
TWIN_DT_S = 14.4  # dt at the original 8h/2000-step design point, held fixed as stop-time changes


def _breakthrough_time_s(time_s: np.ndarray, outlet_temperature_c: np.ndarray) -> float:
    """Identical definition to run_convergence_experiment.py's own
    `_thermocline_breakthrough_time_s`: the first instant the dimensionless
    outlet temperature (T_out - T_inlet)/(T_initial - T_inlet) drops below
    0.5. Duplicated rather than imported -- this project's experiment
    scripts are each standalone -- but must stay identical if that one ever
    changes."""
    span = INITIAL_BED_TEMPERATURE_C - INLET_TEMPERATURE_C
    dimensionless = (outlet_temperature_c - INLET_TEMPERATURE_C) / span
    below_midpoint = dimensionless < 0.5
    if not below_midpoint.any():
        return float(time_s[-1])
    return float(time_s[np.argmax(below_midpoint)])


def _delivered_energy_j(time_s: np.ndarray, outlet_temperature_c: np.ndarray) -> float:
    """Same accounting `simulate_discharge` integrates internally
    (`mass_flow * air_specific_heat * (T_out - T_inlet)`), applied here to
    an arbitrary outlet-temperature trace -- the FMU's included -- so
    delivered-energy deviation compares two independent integrations of the
    same physical quantity, not two different quantities."""
    cp_air = default_packed_bed_config().air_specific_heat_j_per_kgk
    outlet_power_w = MASS_FLOW_KG_PER_S * cp_air * (outlet_temperature_c - INLET_TEMPERATURE_C)
    return float(np.trapezoid(outlet_power_w, time_s))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("fmu", type=Path, help="Path to the compiled PackedBedThermocline.fmu")
    parser.add_argument("--output-root", type=Path, default=Path("outputs"))
    parser.add_argument(
        "--stop-time-hours",
        type=float,
        default=STOP_TIME_HOURS,
        help="Discharge duration to simulate. Use a short window (e.g. 0.5) to "
        "quickly check that a given --output-interval-s is numerically stable "
        "before committing to the full run.",
    )
    parser.add_argument(
        "--output-interval-s",
        type=float,
        default=OUTPUT_INTERVAL_S,
        help="Communication step size handed to the FMU's doStep() -- for this "
        "Co-Simulation FMU there is no separate finer internal step, so this "
        "IS the integration step. Shrink it if fmpy raises "
        "'fmi2GetReal failed'/'division leads to inf or nan'.",
    )
    parser.add_argument(
        "--csv-max-rows",
        type=int,
        default=3000,
        help="Decimate the written comparison_trace.csv/plot to at most this many "
        "rows (metrics below are still computed on the full-resolution trace); "
        "a small --output-interval-s over a multi-hour window can otherwise "
        "produce a CSV with hundreds of thousands of rows.",
    )
    args = parser.parse_args()

    if not args.fmu.is_file():
        raise FileNotFoundError(f"FMU not found: {args.fmu}")

    stop_time_s = args.stop_time_hours * 3600.0
    fmu_frame = simulate_fmu(
        args.fmu, stop_time_s=stop_time_s, output_interval=args.output_interval_s
    )
    fmu_frame = fmu_frame.rename(
        columns={"time": "time_s", "outletTemperature": "outlet_temperature_c"}
    )

    twin_result = simulate_discharge(
        default_packed_bed_config(),
        mass_flow_kg_per_s=MASS_FLOW_KG_PER_S,
        initial_bed_temperature_c=INITIAL_BED_TEMPERATURE_C,
        inlet_temperature_c=INLET_TEMPERATURE_C,
        duration_s=stop_time_s,
        heat_transfer_coefficient_override_w_per_m3k=FIXED_H_V_W_PER_M3K,
        n_steps=max(1, round(stop_time_s / TWIN_DT_S)),
    )
    twin_trace = twin_result.trace

    fmu_time = fmu_frame["time_s"].to_numpy(dtype=float)
    fmu_outlet = fmu_frame["outlet_temperature_c"].to_numpy(dtype=float)
    twin_outlet_on_fmu_grid = np.interp(
        fmu_time,
        twin_trace["time_s"].to_numpy(dtype=float),
        twin_trace["outlet_temperature_c"].to_numpy(dtype=float),
    )

    deviation_c = fmu_outlet - twin_outlet_on_fmu_grid
    max_abs_deviation_c = float(np.max(np.abs(deviation_c)))
    rmse_c = float(np.sqrt(np.mean(deviation_c**2)))

    fmu_breakthrough_s = _breakthrough_time_s(fmu_time, fmu_outlet)
    twin_breakthrough_s = _breakthrough_time_s(
        twin_trace["time_s"].to_numpy(dtype=float),
        twin_trace["outlet_temperature_c"].to_numpy(dtype=float),
    )
    breakthrough_deviation_s = fmu_breakthrough_s - twin_breakthrough_s

    fmu_delivered_energy_j = _delivered_energy_j(fmu_time, fmu_outlet)
    twin_delivered_energy_j = float(twin_trace["cumulative_outlet_energy_j"].iloc[-1])
    relative_energy_deviation = (
        fmu_delivered_energy_j - twin_delivered_energy_j
    ) / twin_delivered_energy_j

    output_dir = args.output_root / "fmu_cross_check"
    output_dir.mkdir(parents=True, exist_ok=True)

    # Metrics above are computed on the full-resolution trace; only the
    # written CSV/plot are decimated, so a small --output-interval-s over a
    # multi-hour window doesn't produce an unwieldy file.
    stride = max(1, len(fmu_time) // args.csv_max_rows)
    comparison = pd.DataFrame(
        {
            "time_s": fmu_time[::stride],
            "fmu_outlet_temperature_c": fmu_outlet[::stride],
            "twin_outlet_temperature_c": twin_outlet_on_fmu_grid[::stride],
            "deviation_c": deviation_c[::stride],
        }
    )
    comparison.to_csv(output_dir / "comparison_trace.csv", index=False)

    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        fig, (ax_temp, ax_dev) = plt.subplots(2, 1, figsize=(8, 6), sharex=True)
        ax_temp.plot(
            comparison["time_s"] / 3600,
            comparison["fmu_outlet_temperature_c"],
            label="FMU (OpenModelica)",
            linewidth=2,
        )
        ax_temp.plot(
            comparison["time_s"] / 3600,
            comparison["twin_outlet_temperature_c"],
            label="Python shadow twin",
            linestyle="--",
        )
        ax_temp.set_ylabel("Outlet temperature (C)")
        ax_temp.legend()
        ax_temp.set_title("FMU vs. shadow-twin packed-bed discharge (P4.2 cross-check)")
        ax_dev.plot(comparison["time_s"] / 3600, comparison["deviation_c"], color="tab:red")
        ax_dev.axhline(0.0, color="black", linewidth=0.5)
        ax_dev.set_xlabel("Time (h)")
        ax_dev.set_ylabel("FMU - twin (C)")
        fig.tight_layout()
        fig.savefig(output_dir / "fmu_vs_twin.png", dpi=150)
        plt.close(fig)
    except ImportError:
        pass

    manifest = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "roadmap_item": "P4.2 (FMU-vs-shadow-twin cross-check)",
        "fmu_path": str(args.fmu),
        "scenario": {
            "mass_flow_kg_per_s": MASS_FLOW_KG_PER_S,
            "inlet_temperature_c": INLET_TEMPERATURE_C,
            "initial_bed_temperature_c": INITIAL_BED_TEMPERATURE_C,
            "fixed_h_v_w_per_m3k": FIXED_H_V_W_PER_M3K,
            "stop_time_hours": args.stop_time_hours,
            "output_interval_s": args.output_interval_s,
            "twin_n_steps": max(1, round(stop_time_s / TWIN_DT_S)),
        },
        "max_absolute_outlet_temperature_deviation_c": max_abs_deviation_c,
        "rmse_outlet_temperature_c": rmse_c,
        "fmu_breakthrough_time_s": fmu_breakthrough_s,
        "twin_breakthrough_time_s": twin_breakthrough_s,
        "breakthrough_time_deviation_s": breakthrough_deviation_s,
        "fmu_delivered_energy_j": fmu_delivered_energy_j,
        "twin_delivered_energy_j": twin_delivered_energy_j,
        "relative_energy_deviation": relative_energy_deviation,
    }
    (output_dir / "run_manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")

    print(f"max |FMU - twin| outlet temperature deviation: {max_abs_deviation_c:.4f} C")
    print(f"RMSE: {rmse_c:.4f} C")
    print(f"breakthrough time deviation: {breakthrough_deviation_s:.1f} s")
    print(f"relative delivered-energy deviation: {100 * relative_energy_deviation:+.4f} %")
    print(f"wrote {output_dir}/run_manifest.json, comparison_trace.csv, fmu_vs_twin.png")


if __name__ == "__main__":
    main()
