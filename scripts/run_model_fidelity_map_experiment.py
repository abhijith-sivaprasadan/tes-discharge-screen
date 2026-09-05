"""P6: the model-fidelity decision map.

Usage: python scripts/run_model_fidelity_map_experiment.py

Every paired comparison so far in this repository (C2, C3, P5) answers "is
the SOC-dependent correction material at *this* case's own process
temperature and design duration?" Roadmap P6 asks the more general
question this project's own build spec calls the actual PhD-application
deliverable: **under what conditions does the detailed discharge
representation materially change the system-level decision, at all?**

Axes (P6.1):

- y-axis: `theta_req = (T_required_out - T_return) / (T_hot - T_return)`,
  a dimensionless temperature-quality requirement rather than a raw
  process temperature -- transferable across cases, not tied to one
  case's own absolute temperatures. `theta_req` near 0 means the process
  only needs the store to clear a temperature barely above its own return
  temperature (almost all stored sensible heat is useful); `theta_req`
  near 1 means the process needs nearly the store's own fully-charged
  temperature (only the hottest sliver of stored heat is useful, and
  outlet-temperature degradation should matter strongly). This project's
  own actual packed-bed configs (`packed_bed_300c_flat.yaml`,
  `packed_bed_400c_flat.yaml`) both sit at `theta_req = -0.25`: *negative*,
  because both hold `inlet_temperature_c` (T_return) a deliberate 20 C
  *above* their own `process_temperature_c` -- exactly the parameter
  choice `run_convergence_experiment.py`'s own docstring already found
  means the quality gate can never bind for either config, no matter the
  duration. This map deliberately sweeps `theta_req` past that point (up
  to 0.9) to explore the regime those two configs do not reach.
- x-axis: design duration tau (hours), the same duration-matched sizing
  grid every other paired comparison in this repository uses.
- panels: one per load profile (flat, two_shift, seasonal), per the
  roadmap's own explicit instruction.
- colour/reported value: power-sizing bias and annual-cost bias (%,
  SOC-dependent vs. constant-limit, matched duration), reported together
  rather than choosing one -- P6.1 suggests either.

Classification (P6.2's own screening thresholds, explicitly labelled as
screening thresholds, not universal truths, per the roadmap's own
instruction): a grid point is `additional_fidelity_materially_changes_design`
if the power-sizing or energy-capacity bias exceeds 5%, or if which
formulation is even worth building differs (a `storage_priced_out_zero_
capacity`-style feasibility flip, checked directly rather than assumed
never to happen); `additional_fidelity_potentially_useful` if not that but
the annual-cost bias exceeds 1%; otherwise `constant_model_adequate`.

Grid: `theta_req` in {-0.25, 0.25, 0.5, 0.75, 0.9} x tau in {2, 6, 12}
hours x 3 profiles = 45 grid points, 90 solves. The `theta_req=-0.25,
tau=6, flat` point is this repository's own already-published Phase C2/C3
headline case -- reproduced here as an explicit internal consistency
check, not just assumed to line up, since this script builds its curves
independently (parameterised by `theta_req` rather than a case's own
`process_temperature_c` directly).

Scope: packed bed only (theta_req is defined from `T_hot`/`T_return`, both
packed-bed-specific concepts from the thermocline model; molten salt has
no thermocline to degrade in the first place, per Phase C3's own finding,
so this map's whole premise does not apply to it the same way).
"""

from __future__ import annotations

import dataclasses
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import matplotlib  # noqa: E402

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from tes_screen.config import CaseConfig, load_config  # noqa: E402
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
T_HOT_C = 400.0  # reference bed's own fully-charged temperature
T_RETURN_C = 320.0  # reference bed's own inlet/return temperature
DELTA_T_MIN_HOT_SIDE_C = 0.0
PRIMARY_N_SEGMENTS = 5
REFERENCE_N_STEPS = 1500

THETA_REQ_GRID = [-0.25, 0.25, 0.5, 0.75, 0.9]
TAU_GRID_HOURS = [2.0, 6.0, 12.0]
PROFILES = ["flat", "two_shift", "seasonal"]

POWER_SIZING_BIAS_THRESHOLD_PCT = 5.0  # [assumption] P6.2's own suggested screening value
ENERGY_CAPACITY_BIAS_THRESHOLD_PCT = 5.0  # [assumption] P6.2's own suggested screening value
ANNUAL_COST_BIAS_THRESHOLD_PCT = 1.0  # [assumption] P6.2's own suggested screening value
ZERO_CAPACITY_THRESHOLD_MWH = 0.05  # matches run_economics_sensitivity_experiment.py's own choice


def _process_temperature_for_theta_req(theta_req: float) -> float:
    return T_RETURN_C + theta_req * (T_HOT_C - T_RETURN_C)


def _curve_for_grid_point(theta_req: float, tau: float):
    process_temperature_c = _process_temperature_for_theta_req(theta_req)
    bed_config = default_packed_bed_config()
    mass_flow = mass_flow_for_target_duration(
        bed_config,
        target_duration_hours=tau,
        initial_bed_temperature_c=T_HOT_C,
        inlet_temperature_c=T_RETURN_C,
        process_temperature_c=process_temperature_c,
        delta_t_min_hot_side_c=DELTA_T_MIN_HOT_SIDE_C,
    )
    result = simulate_discharge(
        bed_config,
        mass_flow_kg_per_s=mass_flow,
        initial_bed_temperature_c=T_HOT_C,
        inlet_temperature_c=T_RETURN_C,
        duration_s=tau * 2 * 3600.0,
        n_steps=REFERENCE_N_STEPS,
    )
    curve = fit_piecewise_discharge_curve(
        result, process_temperature_c, DELTA_T_MIN_HOT_SIDE_C, n_segments=PRIMARY_N_SEGMENTS
    )
    return curve, process_temperature_c


def _duration_matched_config(
    base_config: CaseConfig, tau: float, profile_shape: str, soc_dependent: bool
) -> CaseConfig:
    return dataclasses.replace(
        base_config,
        process=dataclasses.replace(base_config.process, profile_shape=profile_shape),
        storage=dataclasses.replace(
            base_config.storage,
            charge_power_max_mw=None,
            discharge_power_max_mw=None,
            design_duration_hours=tau,
            discharge_limit_mode="soc_dependent" if soc_dependent else "constant",
            discharge_capability_reference=("start_of_hour" if soc_dependent else None),
        ),
    )


def _solved(config: CaseConfig, load, price, discharge_curve=None):
    result = solve_dispatch(config, load, price, discharge_curve=discharge_curve)
    checks = verify_schedule(result.schedule, config, result.solver["objective_eur"])
    if not all(checks.values()):
        raise RuntimeError(f"{config.case_name} failed independent verification")
    return result


def _classify(
    power_bias_pct: float,
    e_cap_bias_pct: float,
    cost_bias_pct: float,
    constant_e_cap_mwh: float,
    soc_e_cap_mwh: float,
) -> str:
    feasibility_flip = (constant_e_cap_mwh < ZERO_CAPACITY_THRESHOLD_MWH) != (
        soc_e_cap_mwh < ZERO_CAPACITY_THRESHOLD_MWH
    )
    if (
        abs(power_bias_pct) > POWER_SIZING_BIAS_THRESHOLD_PCT
        or abs(e_cap_bias_pct) > ENERGY_CAPACITY_BIAS_THRESHOLD_PCT
        or feasibility_flip
    ):
        return "additional_fidelity_materially_changes_design"
    if abs(cost_bias_pct) > ANNUAL_COST_BIAS_THRESHOLD_PCT:
        return "additional_fidelity_potentially_useful"
    return "constant_model_adequate"


def main() -> None:
    output_dir = Path("outputs") / "model_fidelity_map"
    output_dir.mkdir(parents=True, exist_ok=True)

    base_config = load_config(CONFIG_PATH)
    horizon = base_config.optimization.horizon_hours
    price = synthetic_daily_price_profile(horizon)
    loads = {
        profile_shape: build_load_profile(
            profile_shape, base_config.process.annual_peak_load_mw, horizon
        )
        for profile_shape in PROFILES
    }

    grid_points = []
    consistency_check = None
    for theta_req in THETA_REQ_GRID:
        for tau in TAU_GRID_HOURS:
            curve, process_temperature_c = _curve_for_grid_point(theta_req, tau)
            for profile_shape in PROFILES:
                load = loads[profile_shape]
                constant_config = _duration_matched_config(
                    base_config, tau, profile_shape, soc_dependent=False
                )
                constant_result = _solved(constant_config, load, price)
                soc_config = _duration_matched_config(
                    base_config, tau, profile_shape, soc_dependent=True
                )
                soc_result = _solved(soc_config, load, price, discharge_curve=curve)

                constant_e_cap = constant_result.kpis["e_cap_mwh"]
                soc_e_cap = soc_result.kpis["e_cap_mwh"]
                constant_power = constant_result.kpis["power_rating_mw"]
                soc_power = soc_result.kpis["power_rating_mw"]
                constant_cost = constant_result.kpis["total_cost_eur"]
                soc_cost = soc_result.kpis["total_cost_eur"]

                power_bias_pct = (
                    100 * (soc_power - constant_power) / constant_power
                    if abs(constant_power) > 1e-9
                    else 0.0
                )
                e_cap_bias_pct = (
                    100 * (soc_e_cap - constant_e_cap) / constant_e_cap
                    if abs(constant_e_cap) > 1e-9
                    else 0.0
                )
                cost_bias_pct = 100 * (soc_cost - constant_cost) / constant_cost
                region = _classify(
                    power_bias_pct, e_cap_bias_pct, cost_bias_pct, constant_e_cap, soc_e_cap
                )

                point = {
                    "theta_req": theta_req,
                    "tau_hours": tau,
                    "profile_shape": profile_shape,
                    "process_temperature_c": process_temperature_c,
                    "constant_e_cap_mwh": constant_e_cap,
                    "soc_e_cap_mwh": soc_e_cap,
                    "constant_power_rating_mw": constant_power,
                    "soc_power_rating_mw": soc_power,
                    "constant_total_cost_eur": constant_cost,
                    "soc_total_cost_eur": soc_cost,
                    "power_sizing_bias_pct": power_bias_pct,
                    "energy_capacity_bias_pct": e_cap_bias_pct,
                    "annual_cost_bias_pct": cost_bias_pct,
                    "region": region,
                }
                grid_points.append(point)
                print(
                    f"theta_req={theta_req:+.2f} tau={tau:5.1f}h {profile_shape:10s}  "
                    f"power_bias={power_bias_pct:+7.3f}%  e_cap_bias={e_cap_bias_pct:+7.3f}%  "
                    f"cost_bias={cost_bias_pct:+7.4f}%  region={region}"
                )

                if theta_req == -0.25 and tau == 6.0 and profile_shape == "flat":
                    consistency_check = point

    if consistency_check is None:
        raise RuntimeError("consistency-check grid point was not evaluated")
    # Internal consistency check: this grid point's own parameters
    # (theta_req=-0.25 -> process_temperature_c=300, tau=6h, flat) should
    # reproduce Phase C2/C3's own already-published headline numbers
    # (docs/RESULTS.md's Phase C3 table: 54.99/55.20 MWh, +0.020% cost), even though
    # this script builds its curve independently, parameterised by
    # theta_req rather than reading process_temperature_c off the case
    # config directly.
    expected_constant_e_cap = 54.99
    expected_soc_e_cap = 55.20
    expected_cost_bias_pct = 0.020
    consistency_ok = (
        abs(consistency_check["constant_e_cap_mwh"] - expected_constant_e_cap) < 0.01
        and abs(consistency_check["soc_e_cap_mwh"] - expected_soc_e_cap) < 0.01
        and abs(consistency_check["annual_cost_bias_pct"] - expected_cost_bias_pct) < 0.001
    )
    print()
    print(
        f"Consistency check (theta_req=-0.25, tau=6h, flat) vs. Phase C2/C3's own "
        f"published headline: {'PASS' if consistency_ok else 'FAIL'} -- "
        f"E_cap {consistency_check['constant_e_cap_mwh']:.2f}/"
        f"{consistency_check['soc_e_cap_mwh']:.2f} MWh, cost bias "
        f"{consistency_check['annual_cost_bias_pct']:.4f}%"
    )

    region_counts: dict[str, int] = {}
    for point in grid_points:
        region_counts[point["region"]] = region_counts.get(point["region"], 0) + 1

    manifest = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "roadmap_item": "P6 (model-fidelity decision map)",
        "scope_note": (
            "Packed bed only: theta_req is defined from T_hot/T_return, "
            "packed-bed-specific thermocline concepts; molten salt has no "
            "thermocline to degrade (Phase C3's own finding), so this "
            "map's premise does not transfer to it directly."
        ),
        "theta_req_grid": THETA_REQ_GRID,
        "tau_grid_hours": TAU_GRID_HOURS,
        "profiles": PROFILES,
        "thresholds_pct": {
            "power_sizing_bias": POWER_SIZING_BIAS_THRESHOLD_PCT,
            "energy_capacity_bias": ENERGY_CAPACITY_BIAS_THRESHOLD_PCT,
            "annual_cost_bias": ANNUAL_COST_BIAS_THRESHOLD_PCT,
        },
        "thresholds_note": (
            "[assumption] screening thresholds per the roadmap's own P6.2 "
            "suggested values, not universal truths -- labelled as such."
        ),
        "consistency_check": {
            "grid_point": consistency_check,
            "expected_constant_e_cap_mwh": expected_constant_e_cap,
            "expected_soc_e_cap_mwh": expected_soc_e_cap,
            "expected_cost_bias_pct": expected_cost_bias_pct,
            "passed": consistency_ok,
        },
        "region_counts": region_counts,
        "grid_points": grid_points,
    }
    (output_dir / "run_manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )

    # One heatmap panel per profile (P6.1's own explicit instruction),
    # coloured by annual-cost bias %, with a hatch overlay marking grid
    # points classified as materially design-changing (P6.2).
    figures_dir = output_dir / "figures"
    figures_dir.mkdir(exist_ok=True)
    for profile_shape in PROFILES:
        profile_points = [p for p in grid_points if p["profile_shape"] == profile_shape]
        cost_bias_grid = np.array(
            [
                [
                    next(
                        p["annual_cost_bias_pct"]
                        for p in profile_points
                        if p["theta_req"] == theta_req and p["tau_hours"] == tau
                    )
                    for tau in TAU_GRID_HOURS
                ]
                for theta_req in THETA_REQ_GRID
            ]
        )
        materially_changes = np.array(
            [
                [
                    next(
                        p["region"] == "additional_fidelity_materially_changes_design"
                        for p in profile_points
                        if p["theta_req"] == theta_req and p["tau_hours"] == tau
                    )
                    for tau in TAU_GRID_HOURS
                ]
                for theta_req in THETA_REQ_GRID
            ]
        )

        fig, ax = plt.subplots(figsize=(6, 5))
        vmax = max(0.01, np.abs(cost_bias_grid).max())
        mesh = ax.pcolormesh(
            range(len(TAU_GRID_HOURS) + 1),
            range(len(THETA_REQ_GRID) + 1),
            cost_bias_grid,
            cmap="RdYlGn_r",
            vmin=0,
            vmax=vmax,
        )
        for i in range(len(THETA_REQ_GRID)):
            for j in range(len(TAU_GRID_HOURS)):
                marker = "materially\nchanges design" if materially_changes[i, j] else ""
                ax.text(
                    j + 0.5,
                    i + 0.5,
                    f"{cost_bias_grid[i, j]:.3f}%\n{marker}",
                    ha="center",
                    va="center",
                    fontsize=7,
                )
        ax.set_xticks([t + 0.5 for t in range(len(TAU_GRID_HOURS))])
        ax.set_xticklabels([f"{tau:g}h" for tau in TAU_GRID_HOURS])
        ax.set_yticks([t + 0.5 for t in range(len(THETA_REQ_GRID))])
        ax.set_yticklabels([f"{theta:+.2f}" for theta in THETA_REQ_GRID])
        ax.set_xlabel("Design duration (tau)")
        ax.set_ylabel("theta_req (dimensionless temperature-quality requirement)")
        ax.set_title(
            f"Model-fidelity decision map: {profile_shape}\n"
            "annual-cost bias, SOC-dependent vs. constant"
        )
        fig.colorbar(mesh, ax=ax, label="Annual-cost bias (%)")
        fig.tight_layout()
        fig.savefig(figures_dir / f"{profile_shape}.png", dpi=150)
        plt.close(fig)

    print()
    print("Region counts:", region_counts)
    print(f"Written to {output_dir}")


if __name__ == "__main__":
    main()
