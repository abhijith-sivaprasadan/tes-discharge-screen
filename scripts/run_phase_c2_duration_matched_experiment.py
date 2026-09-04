"""Phase C2: the matched-duration-family paired experiment (roadmap fixes P0.1/P0.2).

Usage: python scripts/run_phase_c2_duration_matched_experiment.py

`run_phase_c_experiment.py`'s constant-vs-SOC-dependent comparison left each
formulation free to pick its own power rating: the constant-limit baseline
solves its own P_rated as an independent decision variable, while the
SOC-dependent case ties charge power to the discharge curve's own k=P/E
ratio. The two runs it produced are not a like-for-like comparison of the
discharge-limit shape alone -- they also differ in duration (that run's
manifest: constant tau=7.41h vs soc_dependent tau=3.88h) -- so a chunk of the
"SOC-dependent needs more power" result could be duration, not shape.

This script instead sweeps a design-duration family (`DESIGN_DURATIONS_HOURS`):
for each tau, both formulations are solved with `storage.design_duration_hours
= tau` (dispatch.py's `duration_matched` branch), which ties power to
E_cap/tau identically in both, removing that degree of freedom entirely. The
SOC-dependent curve at each tau is refit from a bed re-simulated at the mass
flow `discharge_curve.mass_flow_for_target_duration` solves for, so its own
k also equals 1/tau exactly (dispatch.py enforces this at build time).

Also applies P0.2's temperature-reference fix: `discharge_power_curve`
(and, through it, `mass_flow_for_target_duration` and the piecewise fit)
now reference deliverable power to T_return (the bed's own HTF return
temperature, `REFERENCE_INLET_TEMPERATURE_C`), the same reference the
bed's own stored-energy accounting uses, rather than mixing it with
T_process; a quality gate on top of that (`T_required_out = T_process +
delta_T_min_hot_side`) still zeroes deliverable power once the outlet can
no longer serve the process, matching the earlier behaviour when
`delta_t_min_hot_side_c = 0`. This script's own output supersedes its own
earlier (P0.1-only) run; it does not overwrite Phase C's original
(confounded) result at outputs/phase_c_packed_bed_300c_flat/, kept as an
archived, diagnostic-only baseline per the roadmap's own instruction.
"""

from __future__ import annotations

import dataclasses
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from tes_screen.config import load_config  # noqa: E402
from tes_screen.discharge_curve import (  # noqa: E402
    fit_piecewise_discharge_curve,
    mass_flow_for_target_duration,
    piecewise_curve_to_frame,
    verify_piecewise_curve_is_safe,
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
REFERENCE_INITIAL_BED_TEMPERATURE_C = 400.0
REFERENCE_INLET_TEMPERATURE_C = 320.0  # T_return: explicit, not derived from T_process (P0.2)
# [assumption] no heat-exchanger approach modelled explicitly yet; see
# run_packed_bed_dynamics.py's own note.
DELTA_T_MIN_HOT_SIDE_C = 0.0
REFERENCE_N_STEPS = 1500
PRIMARY_N_SEGMENTS = 5
DESIGN_DURATIONS_HOURS = [2.0, 4.0, 6.0, 8.0, 12.0]
# The sweep point whose full 8760h schedules are written to disk; the rest
# are recorded as KPIs/checks only in the manifest, the same "primary +
# robustness table" pattern run_phase_c_experiment.py uses for segment count.
HEADLINE_DURATION_HOURS = 6.0


def _duration_matched_config(base_config, design_duration_hours: float, soc_dependent: bool):
    return dataclasses.replace(
        base_config,
        storage=dataclasses.replace(
            base_config.storage,
            charge_power_max_mw=None,
            discharge_power_max_mw=None,
            design_duration_hours=design_duration_hours,
            discharge_limit_mode="soc_dependent" if soc_dependent else "constant",
        ),
    )


def _curve_for_duration(design_duration_hours: float, process_temperature_c: float):
    bed_config = default_packed_bed_config()
    mass_flow = mass_flow_for_target_duration(
        bed_config,
        target_duration_hours=design_duration_hours,
        initial_bed_temperature_c=REFERENCE_INITIAL_BED_TEMPERATURE_C,
        inlet_temperature_c=REFERENCE_INLET_TEMPERATURE_C,
        process_temperature_c=process_temperature_c,
        delta_t_min_hot_side_c=DELTA_T_MIN_HOT_SIDE_C,
    )
    result = simulate_discharge(
        bed_config,
        mass_flow_kg_per_s=mass_flow,
        initial_bed_temperature_c=REFERENCE_INITIAL_BED_TEMPERATURE_C,
        inlet_temperature_c=REFERENCE_INLET_TEMPERATURE_C,
        duration_s=design_duration_hours * 2 * 3600.0,
        n_steps=REFERENCE_N_STEPS,
    )
    curve = fit_piecewise_discharge_curve(
        result, process_temperature_c, DELTA_T_MIN_HOT_SIDE_C, n_segments=PRIMARY_N_SEGMENTS
    )
    safety = verify_piecewise_curve_is_safe(
        curve, result, process_temperature_c, DELTA_T_MIN_HOT_SIDE_C
    )
    return curve, mass_flow, safety


def _solved(config, load, price, discharge_curve=None):
    result = solve_dispatch(config, load, price, discharge_curve=discharge_curve)
    checks = verify_schedule(result.schedule, config, result.solver["objective_eur"])
    return result, checks


def main() -> None:
    output_dir = Path("outputs") / "phase_c2_duration_matched"
    output_dir.mkdir(parents=True, exist_ok=True)

    base_config = load_config(CONFIG_PATH)
    horizon = base_config.optimization.horizon_hours
    load = build_load_profile(
        base_config.process.profile_shape, base_config.process.annual_peak_load_mw, horizon
    )
    price = synthetic_daily_price_profile(horizon)
    process_temperature_c = base_config.process.delivery_temperature_c

    sweep = []
    headline = None
    for tau in DESIGN_DURATIONS_HOURS:
        curve, mass_flow, safety = _curve_for_duration(tau, process_temperature_c)

        constant_config = _duration_matched_config(base_config, tau, soc_dependent=False)
        constant_result, constant_checks = _solved(constant_config, load, price)

        soc_config = _duration_matched_config(base_config, tau, soc_dependent=True)
        soc_result, soc_checks = _solved(soc_config, load, price, discharge_curve=curve)

        entry = {
            "design_duration_hours": tau,
            "mass_flow_kg_per_s": mass_flow,
            "curve_fit_max_overestimate_mw": safety["max_overestimate_mw"],
            "curve_fit_mean_absolute_error_mw": safety["mean_absolute_error_mw"],
            "constant_limit": {
                "solver": constant_result.solver,
                "kpis": constant_result.kpis,
                "verification_passed": all(constant_checks.values()),
            },
            "soc_dependent": {
                "solver": soc_result.solver,
                "kpis": soc_result.kpis,
                "verification_passed": all(soc_checks.values()),
            },
            "delta_soc_dependent_minus_constant": {
                "total_cost_eur": soc_result.kpis["total_cost_eur"]
                - constant_result.kpis["total_cost_eur"],
                "total_cost_pct": 100
                * (soc_result.kpis["total_cost_eur"] - constant_result.kpis["total_cost_eur"])
                / constant_result.kpis["total_cost_eur"],
                "e_cap_mwh": soc_result.kpis["e_cap_mwh"] - constant_result.kpis["e_cap_mwh"],
            },
        }
        sweep.append(entry)
        print(
            f"tau={tau:5.2f}h  constant: cost={constant_result.kpis['total_cost_eur']:>14,.2f} "
            f"E_cap={constant_result.kpis['e_cap_mwh']:>8.2f} MWh  |  "
            f"soc_dependent: cost={soc_result.kpis['total_cost_eur']:>14,.2f} "
            f"E_cap={soc_result.kpis['e_cap_mwh']:>8.2f} MWh  |  "
            f"delta {entry['delta_soc_dependent_minus_constant']['total_cost_pct']:+.3f}%"
        )

        if tau == HEADLINE_DURATION_HOURS:
            headline = {
                "tau": tau,
                "curve": curve,
                "constant_result": constant_result,
                "soc_result": soc_result,
            }
            constant_result.schedule.to_csv(output_dir / "constant_schedule.csv", index=False)
            soc_result.schedule.to_csv(output_dir / "soc_dependent_schedule.csv", index=False)
            piecewise_curve_to_frame(curve).to_csv(
                output_dir / "discharge_curve_breakpoints.csv", index=False
            )

    if headline is None:
        raise ValueError(
            f"HEADLINE_DURATION_HOURS={HEADLINE_DURATION_HOURS} is not in DESIGN_DURATIONS_HOURS"
        )

    all_verified = all(
        entry["constant_limit"]["verification_passed"]
        and entry["soc_dependent"]["verification_passed"]
        for entry in sweep
    )

    manifest = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "case": "packed_bed_300c_flat",
        "fix": "roadmap P0.1 (matched-duration-family sizing) + P0.2 (temperature-reference fix)",
        "note": (
            "Supersedes outputs/phase_c_packed_bed_300c_flat/ as the paired "
            "comparison of discharge-limit shape: that run left the two "
            "formulations with unequal sizing degrees of freedom (constant "
            "tau=7.41h vs soc_dependent tau=3.88h from its own manifest), so "
            "part of its 'soc_dependent needs more power' result could be "
            "duration, not shape (P0.1). It also computed deliverable power "
            "against T_process while the bed's own stored-energy accounting "
            "used T_return, counting enthalpy already present in the return "
            "stream as if storage supplied it (P0.2). Here "
            "storage.design_duration_hours ties power to E_cap/tau "
            "identically in both formulations at each swept tau (dispatch.py's "
            "duration_matched branch, P0.1), the soc_dependent curve at each "
            "tau is refit at the matched mass flow "
            "(discharge_curve.mass_flow_for_target_duration) so its own k=P/E "
            "ratio equals 1/tau exactly, and discharge_power_curve references "
            "deliverable power to T_return with an explicit quality gate at "
            "T_process + delta_T_min_hot_side (P0.2, packed_bed_dynamics.py). "
            "The original phase_c_packed_bed_300c_flat run is kept in place, "
            "unmodified, as an archived/diagnostic result, not deleted or "
            "overwritten -- see its own directory."
        ),
        "delta_t_min_hot_side_c": DELTA_T_MIN_HOT_SIDE_C,
        "design_durations_swept_hours": DESIGN_DURATIONS_HOURS,
        "headline_duration_hours": HEADLINE_DURATION_HOURS,
        "sweep": sweep,
        "all_runs_verified": all_verified,
    }
    (output_dir / "run_manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(f"Written to {output_dir}")

    if not all_verified:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
