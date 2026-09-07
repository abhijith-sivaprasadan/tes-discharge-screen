"""Delta-T-min heat-exchanger sensitivity: how the P6 decision boundary moves
with a cruder-vs-better hot-side approach temperature.

Usage: python scripts/run_delta_t_min_sensitivity_experiment.py

Every result in this repository so far, including P6's own model-fidelity
decision map, holds `delta_t_min_hot_side_c = 0.0` throughout: a zero
minimum hot-side approach temperature, i.e. a perfect, infinitely-effective
heat exchanger between the store and the process. There is no explicit heat-
exchanger model anywhere in this project (`docs/DATA.md` states this
plainly), which matters specifically because the project's own central
question -- whether stored heat is at high enough temperature to still
serve the process as the store discharges -- is a temperature-quality
question a real, imperfect heat exchanger would only make harder, not
easier. This experiment does not add a heat-exchanger design model; it asks
a narrower, answerable question instead: **holding the required *process*
delivery temperature fixed, how much does the theta_req threshold at which
the SOC-dependent correction starts to matter move as the assumed minimum
hot-side approach temperature grows from a perfect 0 C up to a genuinely
poor 30 C?**

`theta_req = (T_required_out - T_return) / (T_hot - T_return)` (P6.1) is
computed exactly as P6 computes it -- `process_temperature_c` fixed first
from `theta_req` via P6's own formula, `T_return + theta_req*(T_hot -
T_return)` -- and `delta_t_min_hot_side_c` then varies *on top of* that
fixed process temperature, exactly as it would for a real process with a
fixed delivery-temperature requirement served through heat exchangers of
different quality. This makes `T_required_out = process_temperature_c +
delta_t_min_hot_side_c` (the quantity the discharge curve's own quality
gate actually reads, `discharge_power_curve`) increase as the heat
exchanger gets worse, which is the real physical effect being tested: a
worse heat exchanger demands a hotter store outlet to still deliver the
same *process* temperature. (An earlier version of this script instead
held `T_required_out` itself fixed while backing out `process_temperature_c`
from it -- mathematically elegant, but wrong for this question: since the
discharge curve's quality gate depends on `T_required_out` alone, holding
it fixed while delta_t_min varies is exactly the manipulation that makes
delta_t_min's real effect disappear by construction, and a first, discarded
run of that version confirmed it: bit-identical results at every
delta_t_min.)

Grid: theta_req in {-0.25, 0.25, 0.5, 0.75, 0.9} (P6's own grid, for direct
comparability) x delta_t_min_hot_side_c in {0, 5, 10, 20, 30} C (the
critique's own suggested range) = 25 grid points, at this project's own
headline design duration (tau=6h) and load profile (flat) -- a single
representative case, not the full (tau, profile) grid P6 already covers,
since the question here is specifically about the theta_req x delta_t_min
interaction, not re-litigating duration/profile sensitivity P6 and the
technology-selection map already answered. Four of the 25 grid points
(theta_req=0.75 at delta_t_min=30 C; theta_req=0.9 at delta_t_min=10/20/30
C) push `T_required_out` at or past `T_hot` itself (400 C): a bed that
never gets hotter than 400 C cannot serve a process that needs 400 C or
more delivered through *any* heat exchanger, an outright infeasibility
this script reports as such (`region="infeasible_t_required_out_exceeds_
t_hot"`) rather than solving around or silently skipping.

delta_t_min_hot_side_c=0 at theta_req=-0.25 is exactly P6's own published
consistency-check point (which is itself this project's own C2/C3 headline
case); reproduced here too as the same internal consistency check, since
this script also builds its own curves independently.
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
T_HOT_C = 400.0  # matches P6's own reference bed
T_RETURN_C = 320.0
PRIMARY_N_SEGMENTS = 5
REFERENCE_N_STEPS = 1500
TAU_HOURS = 6.0  # this project's own headline design duration (C2/C3)
PROFILE_SHAPE = "flat"  # this project's own headline load profile

THETA_REQ_GRID = [-0.25, 0.25, 0.5, 0.75, 0.9]  # P6's own grid, for comparability
DELTA_T_MIN_GRID_C = [0.0, 5.0, 10.0, 20.0, 30.0]  # the critique's own suggested range

# P6.2's own screening thresholds, reused unchanged for direct comparability.
POWER_SIZING_BIAS_THRESHOLD_PCT = 5.0
ENERGY_CAPACITY_BIAS_THRESHOLD_PCT = 5.0
ANNUAL_COST_BIAS_THRESHOLD_PCT = 1.0
ZERO_CAPACITY_THRESHOLD_MWH = 0.05


def _process_temperature_c(theta_req: float) -> float:
    """P6's own formula, unchanged: theta_req anchors process_temperature_c
    directly (not T_required_out), so delta_t_min_hot_side_c is free to
    move T_required_out = process_temperature_c + delta_t_min_hot_side_c
    on top of a fixed process requirement -- see this module's own
    docstring for why the reverse (holding T_required_out fixed) would
    make delta_t_min's effect vanish by construction."""
    return T_RETURN_C + theta_req * (T_HOT_C - T_RETURN_C)


class Infeasible(Exception):
    """T_required_out = process_temperature_c + delta_t_min_hot_side_c has
    reached or passed T_hot: no heat-exchanger quality can serve this
    process from this bed at all, not a curve-fitting or solver failure."""


def _curve_for_grid_point(theta_req: float, delta_t_min_hot_side_c: float):
    process_temperature_c = _process_temperature_c(theta_req)
    if process_temperature_c + delta_t_min_hot_side_c >= T_HOT_C:
        raise Infeasible(
            f"T_required_out={process_temperature_c + delta_t_min_hot_side_c:.1f}C "
            f">= T_hot={T_HOT_C:.1f}C"
        )
    bed_config = default_packed_bed_config()
    mass_flow = mass_flow_for_target_duration(
        bed_config,
        target_duration_hours=TAU_HOURS,
        initial_bed_temperature_c=T_HOT_C,
        inlet_temperature_c=T_RETURN_C,
        process_temperature_c=process_temperature_c,
        delta_t_min_hot_side_c=delta_t_min_hot_side_c,
    )
    result = simulate_discharge(
        bed_config,
        mass_flow_kg_per_s=mass_flow,
        initial_bed_temperature_c=T_HOT_C,
        inlet_temperature_c=T_RETURN_C,
        duration_s=TAU_HOURS * 2 * 3600.0,
        n_steps=REFERENCE_N_STEPS,
    )
    curve = fit_piecewise_discharge_curve(
        result, process_temperature_c, delta_t_min_hot_side_c, n_segments=PRIMARY_N_SEGMENTS
    )
    return curve, process_temperature_c


def _duration_matched_config(base_config: CaseConfig, soc_dependent: bool) -> CaseConfig:
    return dataclasses.replace(
        base_config,
        process=dataclasses.replace(base_config.process, profile_shape=PROFILE_SHAPE),
        storage=dataclasses.replace(
            base_config.storage,
            charge_power_max_mw=None,
            discharge_power_max_mw=None,
            design_duration_hours=TAU_HOURS,
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
    output_dir = Path("outputs") / "delta_t_min_sensitivity"
    output_dir.mkdir(parents=True, exist_ok=True)

    base_config = load_config(CONFIG_PATH)
    horizon = base_config.optimization.horizon_hours
    load = build_load_profile(PROFILE_SHAPE, base_config.process.annual_peak_load_mw, horizon)
    price = synthetic_daily_price_profile(horizon)

    # constant_config/constant_result never depend on theta_req or
    # delta_t_min (the constant-limit baseline reads no curve and no
    # temperature at all -- P0.2's own already-documented Phase A
    # limitation), and tau/profile are both fixed constants here, unlike
    # P6's own sweep over them -- so this solves exactly once, not once per
    # grid point.
    constant_config = _duration_matched_config(base_config, soc_dependent=False)
    constant_result = _solved(constant_config, load, price)

    grid_points = []
    consistency_check = None
    for theta_req in THETA_REQ_GRID:
        for delta_t_min in DELTA_T_MIN_GRID_C:
            try:
                curve, process_temperature_c = _curve_for_grid_point(theta_req, delta_t_min)
            except Infeasible as exc:
                point = {
                    "theta_req": theta_req,
                    "delta_t_min_hot_side_c": delta_t_min,
                    "process_temperature_c": _process_temperature_c(theta_req),
                    "region": "infeasible_t_required_out_exceeds_t_hot",
                    "infeasibility_reason": str(exc),
                }
                grid_points.append(point)
                print(
                    f"theta_req={theta_req:+.2f} delta_t_min={delta_t_min:5.1f}C  "
                    f"INFEASIBLE ({exc})"
                )
                continue

            soc_config = _duration_matched_config(base_config, soc_dependent=True)
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
                "delta_t_min_hot_side_c": delta_t_min,
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
                f"theta_req={theta_req:+.2f} delta_t_min={delta_t_min:5.1f}C  "
                f"process_T={process_temperature_c:6.2f}C  "
                f"power_bias={power_bias_pct:+7.3f}%  e_cap_bias={e_cap_bias_pct:+7.3f}%  "
                f"cost_bias={cost_bias_pct:+7.4f}%  region={region}"
            )

            if theta_req == -0.25 and delta_t_min == 0.0:
                consistency_check = point

    if consistency_check is None:
        raise RuntimeError("consistency-check grid point was not evaluated")
    # Same internal consistency check P6 runs at its own theta_req=-0.25,
    # tau=6h, flat point (this project's own published C2/C3 headline case):
    # this script builds its curve independently too, parameterised by
    # theta_req/delta_t_min rather than reading process_temperature_c off
    # the case config directly.
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
        f"Consistency check (theta_req=-0.25, delta_t_min=0C) vs. Phase C2/C3's own "
        f"published headline: {'PASS' if consistency_ok else 'FAIL'} -- "
        f"E_cap {consistency_check['constant_e_cap_mwh']:.2f}/"
        f"{consistency_check['soc_e_cap_mwh']:.2f} MWh, cost bias "
        f"{consistency_check['annual_cost_bias_pct']:.4f}%"
    )

    # The boundary itself: for each delta_t_min column, the lowest theta_req
    # in this grid classified as at least "additional_fidelity_potentially_
    # useful" (the region P6.2 itself uses to mean "the correction starts to
    # matter") -- None if no *feasible* grid point in this theta_req range
    # crosses it at that delta_t_min. Infeasible points are excluded here,
    # not counted as "crossing": infeasibility means no design exists at
    # all, not that the correction matters for one that does.
    boundary_by_delta_t_min: dict[float, float | None] = {}
    for delta_t_min in DELTA_T_MIN_GRID_C:
        column = [
            p
            for p in grid_points
            if p["delta_t_min_hot_side_c"] == delta_t_min and "annual_cost_bias_pct" in p
        ]
        column.sort(key=lambda p: p["theta_req"])
        crossing = next(
            (p["theta_req"] for p in column if p["region"] != "constant_model_adequate"), None
        )
        boundary_by_delta_t_min[delta_t_min] = crossing

    region_counts: dict[str, int] = {}
    for point in grid_points:
        region_counts[point["region"]] = region_counts.get(point["region"], 0) + 1

    manifest = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "note": (
            "Extends P6's model-fidelity decision map with a second axis "
            "P6 held fixed at 0: delta_t_min_hot_side_c, the minimum "
            "hot-side heat-exchanger approach temperature. No explicit "
            "heat-exchanger model is added; theta_req anchors "
            "process_temperature_c exactly as in P6 (a fixed process "
            "delivery-temperature requirement), and delta_t_min_hot_side_c "
            "varies on top of it, raising T_required_out = "
            "process_temperature_c + delta_t_min_hot_side_c as the "
            "assumed heat exchanger gets worse -- the real physical "
            "effect being tested. Four grid points push T_required_out to "
            "or past T_hot itself and are reported as infeasible, not "
            "solved around."
        ),
        "tau_hours": TAU_HOURS,
        "profile_shape": PROFILE_SHAPE,
        "theta_req_grid": THETA_REQ_GRID,
        "delta_t_min_hot_side_c_grid": DELTA_T_MIN_GRID_C,
        "thresholds_pct": {
            "power_sizing_bias": POWER_SIZING_BIAS_THRESHOLD_PCT,
            "energy_capacity_bias": ENERGY_CAPACITY_BIAS_THRESHOLD_PCT,
            "annual_cost_bias": ANNUAL_COST_BIAS_THRESHOLD_PCT,
        },
        "consistency_check": {
            "grid_point": consistency_check,
            "expected_constant_e_cap_mwh": expected_constant_e_cap,
            "expected_soc_e_cap_mwh": expected_soc_e_cap,
            "expected_cost_bias_pct": expected_cost_bias_pct,
            "passed": consistency_ok,
        },
        "region_counts": region_counts,
        "boundary_theta_req_by_delta_t_min_hot_side_c": boundary_by_delta_t_min,
        "grid_points": grid_points,
    }
    (output_dir / "run_manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )

    # Heatmap: theta_req x delta_t_min, coloured by annual-cost bias %, with
    # a hatch label marking grid points classified as materially
    # design-changing -- same visual language as P6's own figures.
    figures_dir = output_dir / "figures"
    figures_dir.mkdir(exist_ok=True)

    def _point_at(theta_req: float, delta_t_min: float) -> dict:
        return next(
            p
            for p in grid_points
            if p["theta_req"] == theta_req and p["delta_t_min_hot_side_c"] == delta_t_min
        )

    cost_bias_grid = np.array(
        [
            [
                _point_at(theta_req, delta_t_min).get("annual_cost_bias_pct", np.nan)
                for delta_t_min in DELTA_T_MIN_GRID_C
            ]
            for theta_req in THETA_REQ_GRID
        ]
    )
    materially_changes = np.array(
        [
            [
                _point_at(theta_req, delta_t_min)["region"]
                == "additional_fidelity_materially_changes_design"
                for delta_t_min in DELTA_T_MIN_GRID_C
            ]
            for theta_req in THETA_REQ_GRID
        ]
    )
    infeasible_mask = np.array(
        [
            [
                _point_at(theta_req, delta_t_min)["region"]
                == "infeasible_t_required_out_exceeds_t_hot"
                for delta_t_min in DELTA_T_MIN_GRID_C
            ]
            for theta_req in THETA_REQ_GRID
        ]
    )

    fig, ax = plt.subplots(figsize=(6.5, 5))
    vmax = max(0.01, np.nanmax(np.abs(cost_bias_grid)))
    mesh = ax.pcolormesh(
        range(len(DELTA_T_MIN_GRID_C) + 1),
        range(len(THETA_REQ_GRID) + 1),
        cost_bias_grid,
        cmap="RdYlGn_r",
        vmin=0,
        vmax=vmax,
    )
    for i in range(len(THETA_REQ_GRID)):
        for j in range(len(DELTA_T_MIN_GRID_C)):
            if infeasible_mask[i, j]:
                ax.text(
                    j + 0.5,
                    i + 0.5,
                    "infeasible\n(T_req >= T_hot)",
                    ha="center",
                    va="center",
                    fontsize=7,
                )
                continue
            marker = "materially\nchanges design" if materially_changes[i, j] else ""
            ax.text(
                j + 0.5,
                i + 0.5,
                f"{cost_bias_grid[i, j]:.3f}%\n{marker}",
                ha="center",
                va="center",
                fontsize=7,
            )
    ax.set_xticks([t + 0.5 for t in range(len(DELTA_T_MIN_GRID_C))])
    ax.set_xticklabels([f"{d:g}C" for d in DELTA_T_MIN_GRID_C])
    ax.set_yticks([t + 0.5 for t in range(len(THETA_REQ_GRID))])
    ax.set_yticklabels([f"{theta:+.2f}" for theta in THETA_REQ_GRID])
    ax.set_xlabel("delta_t_min_hot_side_c (minimum HX approach temperature)")
    ax.set_ylabel("theta_req (dimensionless temperature-quality requirement)")
    ax.set_title(
        f"Heat-exchanger-quality sensitivity (tau={TAU_HOURS:g}h, {PROFILE_SHAPE})\n"
        "annual-cost bias, SOC-dependent vs. constant"
    )
    fig.colorbar(mesh, ax=ax, label="Annual-cost bias (%)")
    fig.tight_layout()
    fig.savefig(figures_dir / "delta_t_min_sensitivity.png", dpi=150)
    plt.close(fig)

    print()
    print("Region counts:", region_counts)
    print("Boundary theta_req (first point past constant_model_adequate) by delta_t_min:")
    for delta_t_min, boundary in boundary_by_delta_t_min.items():
        print(f"  delta_t_min={delta_t_min:5.1f}C  boundary_theta_req={boundary}")
    print(f"Written to {output_dir}")


if __name__ == "__main__":
    main()
