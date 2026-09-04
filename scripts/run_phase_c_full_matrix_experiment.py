"""Phase C3: the full technology x temperature x profile matrix.

Usage: python scripts/run_phase_c_full_matrix_experiment.py

`run_phase_c2_duration_matched_experiment.py` answered C1/C2 for one
technology (packed bed) at one process temperature (300 C) and one load
profile (flat): does the SOC-dependent discharge-limit correction change the
answer for that single case, once sizing is matched across formulations
(P0.1), the temperature reference is fixed (P0.2), and the discharge
capability constraint reads the correct pre-dispatch state (P0.4)? This
script answers C3, the question the build spec's own section 8 actually
asks: does the SOC-dependent correction change *which technology wins*,
across every technology that has a Phase B-equivalent dynamic sub-model
(packed bed, molten salt, PCM -- `molten_salt_dynamics.py` and
`pcm_dynamics.py`, both new this session), every process temperature each
technology is configured for (300 C and 400 C for packed bed and molten
salt; PCM only at 300 C -- no common nitrate-salt PCM melts high enough for
a useful 400 C case, `configs/pcm_300c_flat.yaml`'s own comment), and every
synthetic load profile (`flat`, `two_shift`, `seasonal`,
`synthetic_profiles.py`). That is 5 technology/temperature combinations x 3
profiles = 15 paired cases (30 solves), not the naive "3 x 2 x 3 = 18" the
roadmap's shorthand name for this task suggested: PCM's missing 400 C case
is a prior, already-documented modelling decision (no suitable
high-temperature nitrate-salt PCM composition found), not silently dropped
here.

Every case uses `storage.design_duration_hours = HEADLINE_DURATION_HOURS`
(C2's own headline duration), tying charge/discharge power to E_cap/tau
identically in both formulations (P0.1's matched-sizing fix,
`dispatch.py`'s `duration_matched` branch) so a technology's ranking change
reflects the discharge-limit *shape* difference the SOC-dependent model
adds, not an incidental difference in how much power each formulation would
otherwise have chosen to build. One paired solve per case (not a duration
sweep): this follows the original build spec's literal C2 instruction
("solve the annual problem twice") applied across the full matrix, not
`run_phase_c2_duration_matched_experiment.py`'s own duration-sweep
methodology, which answered a different, narrower question (how sensitive
is the *single* packed-bed-300C-flat result to the chosen design duration).

Each technology's discharge curve is built once per (technology,
temperature) combination, at the mass flow that ties its own k = P/E ratio
to 1/HEADLINE_DURATION_HOURS exactly
(`{packed_bed,molten_salt,pcm}_dynamics`' own `mass_flow_for_target_duration`,
mirroring `discharge_curve.mass_flow_for_target_duration`'s closed-form
approach), and reused across all three load profiles for that combination:
the curve depends on the storage technology's own physics and the process
temperature, not on how the demand happens to vary over the year.

Two-tank molten salt's hot/cold tank temperatures (565 C / 290 C) are held
fixed across both of its process-temperature cases, not read from each
case's own `temperature_max_c`/`temperature_min_c`: those two YAML configs
use `temperature_min_c` for two different concepts (the 300 C case's true
cold-tank temperature vs. the 400 C case's process-specific "usable floor"),
and only `process_temperature_c` should vary between them --
`molten_salt_dynamics.py`'s own module docstring explains why no thermocline
mechanism exists for a two-tank system in the first place.

Outputs: `outputs/phase_c_full_matrix/run_manifest.json` (every case's full
KPIs and deltas), `case_deltas.csv` (15 rows, one per case, the per-case
constant-vs-SOC-dependent deltas), `ranking_table.csv` (5 rows, one per
temperature/profile group, C3's required cheapest-technology-under-each-
formulation comparison with an explicit ranking-flip column), and
`figures/{packed_bed,molten_salt,pcm}.png` (one figure per technology, C3's
other required output).
"""

from __future__ import annotations

import dataclasses
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import matplotlib  # noqa: E402

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import pandas as pd  # noqa: E402

from tes_screen.config import CaseConfig, load_config  # noqa: E402
from tes_screen.discharge_curve import (  # noqa: E402
    PiecewiseDischargeCurve,
    fit_piecewise_curve_from_power_curve,
    verify_piecewise_curve_against_power_curve,
)
from tes_screen.discharge_curve import (
    mass_flow_for_target_duration as packed_bed_mass_flow_for_target_duration,
)
from tes_screen.dispatch import solve_dispatch  # noqa: E402
from tes_screen.molten_salt_dynamics import default_molten_salt_config  # noqa: E402
from tes_screen.molten_salt_dynamics import (  # noqa: E402
    discharge_power_curve as molten_salt_discharge_power_curve,
)
from tes_screen.molten_salt_dynamics import (  # noqa: E402
    mass_flow_for_target_duration as molten_salt_mass_flow_for_target_duration,
)
from tes_screen.molten_salt_dynamics import (  # noqa: E402
    reference_energy_capacity_mwh as molten_salt_reference_energy_capacity_mwh,
)
from tes_screen.packed_bed_dynamics import (  # noqa: E402
    default_packed_bed_config,
    simulate_discharge,
)
from tes_screen.packed_bed_dynamics import (  # noqa: E402
    discharge_power_curve as packed_bed_discharge_power_curve,
)
from tes_screen.pcm_dynamics import default_pcm_config  # noqa: E402
from tes_screen.pcm_dynamics import discharge_power_curve as pcm_discharge_power_curve  # noqa: E402
from tes_screen.pcm_dynamics import (  # noqa: E402
    mass_flow_for_target_duration as pcm_mass_flow_for_target_duration,
)
from tes_screen.pcm_dynamics import (  # noqa: E402
    reference_energy_capacity_mwh as pcm_reference_energy_capacity_mwh,
)
from tes_screen.synthetic_profiles import (  # noqa: E402
    build_load_profile,
    synthetic_daily_price_profile,
)
from tes_screen.verification import verify_schedule  # noqa: E402

HEADLINE_DURATION_HOURS = 6.0  # matches phase_c2_duration_matched's own headline point
DELTA_T_MIN_HOT_SIDE_C = 0.0  # [assumption]; see run_packed_bed_dynamics.py's own note (P0.2)
N_SEGMENTS = 5
LOAD_PROFILES = ["flat", "two_shift", "seasonal"]

REFERENCE_PACKED_BED_N_STEPS = 1500
# initial_bed_temperature_c/inlet_temperature_c (T_return) per process
# temperature, matching each config's own temperature_max_c/temperature_min_c.
REFERENCE_PACKED_BED_TEMPERATURES_C = {300.0: (400.0, 320.0), 400.0: (500.0, 420.0)}

REFERENCE_MOLTEN_SALT_HOT_TANK_TEMPERATURE_C = 565.0
REFERENCE_MOLTEN_SALT_COLD_TANK_TEMPERATURE_C = 290.0

REFERENCE_PCM_T_MAX_C = 330.0
REFERENCE_PCM_T_MIN_C = 300.0
# [assumption] the HTF loop's own return temperature, distinct from the PCM's
# own temperature band; matches tests/test_pcm_dynamics.py's own choice.
REFERENCE_PCM_HTF_RETURN_TEMPERATURE_C = 290.0

# (technology, process_temperature_c, config_path). PCM has no 400 C case:
# see this module's own docstring and configs/pcm_300c_flat.yaml's comment.
TECHNOLOGY_TEMPERATURE_CASES = [
    ("packed_bed", 300.0, "configs/packed_bed_300c_flat.yaml"),
    ("packed_bed", 400.0, "configs/packed_bed_400c_flat.yaml"),
    ("molten_salt", 300.0, "configs/molten_salt_300c_flat.yaml"),
    ("molten_salt", 400.0, "configs/molten_salt_400c_flat.yaml"),
    ("pcm", 300.0, "configs/pcm_300c_flat.yaml"),
]


def _packed_bed_curve(process_temperature_c: float):
    bed_config = default_packed_bed_config()
    initial_temperature_c, inlet_temperature_c = REFERENCE_PACKED_BED_TEMPERATURES_C[
        process_temperature_c
    ]
    mass_flow = packed_bed_mass_flow_for_target_duration(
        bed_config,
        target_duration_hours=HEADLINE_DURATION_HOURS,
        initial_bed_temperature_c=initial_temperature_c,
        inlet_temperature_c=inlet_temperature_c,
        process_temperature_c=process_temperature_c,
        delta_t_min_hot_side_c=DELTA_T_MIN_HOT_SIDE_C,
    )
    result = simulate_discharge(
        bed_config,
        mass_flow_kg_per_s=mass_flow,
        initial_bed_temperature_c=initial_temperature_c,
        inlet_temperature_c=inlet_temperature_c,
        duration_s=HEADLINE_DURATION_HOURS * 2 * 3600.0,
        n_steps=REFERENCE_PACKED_BED_N_STEPS,
    )
    power_curve = packed_bed_discharge_power_curve(
        result, process_temperature_c, DELTA_T_MIN_HOT_SIDE_C
    )
    reference_energy_capacity_mwh = float(result.trace["bed_stored_energy_j"].iloc[0]) / 3.6e9
    curve = fit_piecewise_curve_from_power_curve(
        power_curve, reference_energy_capacity_mwh, n_segments=N_SEGMENTS
    )
    return curve, power_curve, mass_flow


def _molten_salt_curve(process_temperature_c: float):
    salt_config = default_molten_salt_config()
    mass_flow = molten_salt_mass_flow_for_target_duration(
        salt_config,
        HEADLINE_DURATION_HOURS,
        REFERENCE_MOLTEN_SALT_HOT_TANK_TEMPERATURE_C,
        REFERENCE_MOLTEN_SALT_COLD_TANK_TEMPERATURE_C,
    )
    power_curve = molten_salt_discharge_power_curve(
        salt_config,
        mass_flow,
        REFERENCE_MOLTEN_SALT_HOT_TANK_TEMPERATURE_C,
        REFERENCE_MOLTEN_SALT_COLD_TANK_TEMPERATURE_C,
        process_temperature_c,
        DELTA_T_MIN_HOT_SIDE_C,
        n_points=2000,
    )
    reference_energy_capacity_mwh = molten_salt_reference_energy_capacity_mwh(
        salt_config,
        REFERENCE_MOLTEN_SALT_HOT_TANK_TEMPERATURE_C,
        REFERENCE_MOLTEN_SALT_COLD_TANK_TEMPERATURE_C,
    )
    curve = fit_piecewise_curve_from_power_curve(
        power_curve, reference_energy_capacity_mwh, n_segments=N_SEGMENTS
    )
    return curve, power_curve, mass_flow


def _pcm_curve(process_temperature_c: float):
    if process_temperature_c != 300.0:
        raise ValueError("PCM only has a discharge model for the 300 C case")
    pcm_config = default_pcm_config()
    mass_flow = pcm_mass_flow_for_target_duration(
        pcm_config,
        HEADLINE_DURATION_HOURS,
        REFERENCE_PCM_T_MAX_C,
        REFERENCE_PCM_T_MIN_C,
        REFERENCE_PCM_HTF_RETURN_TEMPERATURE_C,
    )
    power_curve = pcm_discharge_power_curve(
        pcm_config,
        mass_flow,
        REFERENCE_PCM_T_MAX_C,
        REFERENCE_PCM_T_MIN_C,
        REFERENCE_PCM_HTF_RETURN_TEMPERATURE_C,
        process_temperature_c,
        DELTA_T_MIN_HOT_SIDE_C,
        n_points=2000,
    )
    reference_energy_capacity_mwh = pcm_reference_energy_capacity_mwh(
        pcm_config, REFERENCE_PCM_T_MAX_C, REFERENCE_PCM_T_MIN_C
    )
    curve = fit_piecewise_curve_from_power_curve(
        power_curve, reference_energy_capacity_mwh, n_segments=N_SEGMENTS
    )
    return curve, power_curve, mass_flow


CURVE_BUILDERS = {
    "packed_bed": _packed_bed_curve,
    "molten_salt": _molten_salt_curve,
    "pcm": _pcm_curve,
}


def _duration_matched_config(
    base_config: CaseConfig, profile_shape: str, soc_dependent: bool
) -> CaseConfig:
    return dataclasses.replace(
        base_config,
        process=dataclasses.replace(base_config.process, profile_shape=profile_shape),
        storage=dataclasses.replace(
            base_config.storage,
            charge_power_max_mw=None,
            discharge_power_max_mw=None,
            design_duration_hours=HEADLINE_DURATION_HOURS,
            discharge_limit_mode="soc_dependent" if soc_dependent else "constant",
            discharge_capability_reference=("start_of_hour" if soc_dependent else None),
        ),
    )


def _solved(
    config: CaseConfig, load, price, discharge_curve: PiecewiseDischargeCurve | None = None
):
    result = solve_dispatch(config, load, price, discharge_curve=discharge_curve)
    checks = verify_schedule(result.schedule, config, result.solver["objective_eur"])
    return result, checks


def _plot_technology_figure(
    technology: str, curves_by_temperature: dict, output_path: Path
) -> None:
    fig, ax = plt.subplots(figsize=(7, 5))
    colors = {300.0: "tab:orange", 400.0: "tab:blue"}
    for temperature_c in sorted(curves_by_temperature):
        curve, power_curve, mass_flow, safety = curves_by_temperature[temperature_c]
        color = colors.get(temperature_c, "tab:green")
        ax.plot(
            power_curve["state_of_charge"],
            power_curve["deliverable_power_mw"],
            color=color,
            linewidth=1.5,
            label=f"{temperature_c:.0f} C process: analytic deliverable power",
        )
        e_cap = curve.reference_energy_capacity_mwh
        fitted = [
            curve.limit_mw(soc * e_cap, e_cap) for soc in power_curve["state_of_charge"]
        ]
        ax.plot(
            power_curve["state_of_charge"],
            fitted,
            color=color,
            linestyle="--",
            linewidth=1.2,
            label=f"{temperature_c:.0f} C process: piecewise fit ({N_SEGMENTS} segments)",
        )
        ax.axhline(
            curve.reference_rated_power_mw,
            color=color,
            linestyle=":",
            linewidth=1.0,
            alpha=0.6,
            label=f"{temperature_c:.0f} C process: constant-limit reference power",
        )
    ax.set_xlabel("State of charge (1 = full, 0 = empty)")
    ax.set_ylabel(f"Deliverable power at the {HEADLINE_DURATION_HOURS:.0f} h design mass flow (MW)")
    ax.set_title(f"{technology}: SOC-dependent discharge capability vs. constant baseline")
    ax.invert_xaxis()
    ax.legend(fontsize=8, loc="best")
    fig.tight_layout()
    fig.savefig(output_path, dpi=150)
    plt.close(fig)


def main() -> None:
    output_dir = Path("outputs") / "phase_c_full_matrix"
    output_dir.mkdir(parents=True, exist_ok=True)
    figures_dir = output_dir / "figures"
    figures_dir.mkdir(exist_ok=True)

    curves_by_case: dict[tuple[str, float], tuple] = {}
    case_entries = []

    for technology, temperature_c, config_path in TECHNOLOGY_TEMPERATURE_CASES:
        base_config = load_config(Path(config_path))
        curve, power_curve, mass_flow = CURVE_BUILDERS[technology](temperature_c)
        safety = verify_piecewise_curve_against_power_curve(curve, power_curve)
        curves_by_case[(technology, temperature_c)] = (curve, power_curve, mass_flow, safety)

        horizon = base_config.optimization.horizon_hours
        for profile_shape in LOAD_PROFILES:
            load = build_load_profile(
                profile_shape, base_config.process.annual_peak_load_mw, horizon
            )
            price = synthetic_daily_price_profile(horizon)

            constant_config = _duration_matched_config(
                base_config, profile_shape, soc_dependent=False
            )
            constant_result, constant_checks = _solved(constant_config, load, price)

            soc_config = _duration_matched_config(base_config, profile_shape, soc_dependent=True)
            soc_result, soc_checks = _solved(soc_config, load, price, discharge_curve=curve)

            delta_cost_eur = (
                soc_result.kpis["total_cost_eur"] - constant_result.kpis["total_cost_eur"]
            )
            delta_cost_pct = 100 * delta_cost_eur / constant_result.kpis["total_cost_eur"]

            entry = {
                "technology": technology,
                "temperature_c": temperature_c,
                "profile_shape": profile_shape,
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
                    "total_cost_eur": delta_cost_eur,
                    "total_cost_pct": delta_cost_pct,
                    "e_cap_mwh": soc_result.kpis["e_cap_mwh"] - constant_result.kpis["e_cap_mwh"],
                    "power_rating_mw": (
                        soc_result.kpis["power_rating_mw"] - constant_result.kpis["power_rating_mw"]
                    ),
                },
            }
            case_entries.append(entry)
            print(
                f"{technology:12s} {temperature_c:5.0f}C {profile_shape:10s}  "
                f"constant={constant_result.kpis['total_cost_eur']:>14,.0f} EUR/yr  "
                f"soc_dependent={soc_result.kpis['total_cost_eur']:>14,.0f} EUR/yr  "
                f"delta={delta_cost_pct:+.3f}%"
            )

    all_verified = all(
        entry["constant_limit"]["verification_passed"]
        and entry["soc_dependent"]["verification_passed"]
        for entry in case_entries
    )

    # Per-case delta table (C3): 15 rows, one per (technology, temperature, profile).
    case_deltas = pd.DataFrame(
        [
            {
                "technology": e["technology"],
                "temperature_c": e["temperature_c"],
                "profile_shape": e["profile_shape"],
                "total_cost_constant_eur": e["constant_limit"]["kpis"]["total_cost_eur"],
                "total_cost_soc_dependent_eur": e["soc_dependent"]["kpis"]["total_cost_eur"],
                "delta_total_cost_eur": e["delta_soc_dependent_minus_constant"]["total_cost_eur"],
                "delta_total_cost_pct": e["delta_soc_dependent_minus_constant"]["total_cost_pct"],
                "delta_e_cap_mwh": e["delta_soc_dependent_minus_constant"]["e_cap_mwh"],
                "delta_power_rating_mw": e["delta_soc_dependent_minus_constant"]["power_rating_mw"],
            }
            for e in case_entries
        ]
    )
    case_deltas.to_csv(output_dir / "case_deltas.csv", index=False)

    # Ranking table (C3): for each (temperature, profile) group, which
    # technology is cheapest under each formulation, and whether that
    # changes. Groups where only one technology exists (none here, since
    # every temperature has at least two) would have ranking_flipped=False
    # by construction; not currently reached but handled defensively.
    ranking_rows = []
    for (temperature_c, profile_shape), group in case_deltas.groupby(
        ["temperature_c", "profile_shape"]
    ):
        cheapest_constant = group.loc[group["total_cost_constant_eur"].idxmin(), "technology"]
        cheapest_soc_dependent = group.loc[
            group["total_cost_soc_dependent_eur"].idxmin(), "technology"
        ]
        ranking_rows.append(
            {
                "temperature_c": temperature_c,
                "profile_shape": profile_shape,
                "technologies_compared": ", ".join(sorted(group["technology"])),
                "cheapest_technology_constant": cheapest_constant,
                "cheapest_technology_soc_dependent": cheapest_soc_dependent,
                "ranking_flipped": cheapest_constant != cheapest_soc_dependent,
            }
        )
    ranking_table = pd.DataFrame(ranking_rows).sort_values(["temperature_c", "profile_shape"])
    ranking_table.to_csv(output_dir / "ranking_table.csv", index=False)

    any_ranking_flip = bool(ranking_table["ranking_flipped"].any())

    for technology in CURVE_BUILDERS:
        curves_for_technology = {
            temperature_c: curves_by_case[(tech, temperature_c)]
            for tech, temperature_c in curves_by_case
            if tech == technology
        }
        _plot_technology_figure(
            technology, curves_for_technology, figures_dir / f"{technology}.png"
        )

    manifest = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "fix": (
            "roadmap P0.1 (matched-duration-family sizing) + P0.2 "
            "(temperature-reference fix) + P0.4 (start-of-hour discharge "
            "capability reference), applied uniformly across packed bed, "
            "two-tank molten salt, and PCM"
        ),
        "note": (
            "Full C3 technology-ranking matrix: 5 technology/temperature "
            "combinations (packed bed and molten salt at 300 C and 400 C; "
            "PCM only at 300 C, no suitable high-temperature nitrate-salt "
            "PCM composition found -- configs/pcm_300c_flat.yaml's own "
            "comment) x 3 synthetic load profiles (flat, two_shift, "
            "seasonal) = 15 paired cases, 30 solves. Every case uses "
            "storage.design_duration_hours = "
            f"{HEADLINE_DURATION_HOURS} h (matching phase_c2_duration_matched's "
            "own headline point), tying charge/discharge power to E_cap/tau "
            "identically in both formulations so the comparison isolates the "
            "discharge-limit shape, not an incidental sizing difference "
            "(P0.1). molten_salt_dynamics.py and pcm_dynamics.py are new "
            "this session: real closed-form/analytic sub-models (near-"
            "isothermal two-tank discharge with a flow-taper heel for salt; "
            "a three-regime superheat/latent/subcooled discharge for PCM), "
            "not fabricated curves, fit through the same technology-agnostic "
            "piecewise construction (discharge_curve.fit_piecewise_curve_"
            "from_power_curve) the packed bed already used."
        ),
        "headline_duration_hours": HEADLINE_DURATION_HOURS,
        "delta_t_min_hot_side_c": DELTA_T_MIN_HOT_SIDE_C,
        "n_segments": N_SEGMENTS,
        "load_profiles": LOAD_PROFILES,
        "cases": case_entries,
        "ranking_table": ranking_rows,
        "any_ranking_flip": any_ranking_flip,
        "all_runs_verified": all_verified,
    }
    (output_dir / "run_manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )

    print()
    print(ranking_table.to_string(index=False))
    print()
    if any_ranking_flip:
        print("RESULT: the SOC-dependent discharge-limit correction DOES change the cheapest "
              "technology in at least one (temperature, profile) case; see ranking_table.csv.")
    else:
        print("RESULT: the SOC-dependent discharge-limit correction does NOT change the cheapest "
              "technology in any (temperature, profile) case; the ranking is identical under both "
              "formulations across the full matrix.")
    print(f"Written to {output_dir}")

    if not all_verified:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
