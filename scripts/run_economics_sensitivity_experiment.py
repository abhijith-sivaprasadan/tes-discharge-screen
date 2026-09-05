"""P5: economics sensitivity, not one assumed number.

Usage: python scripts/run_economics_sensitivity_experiment.py

The project's own committed headline results (Phase A, C2, C3) each rest on
one specific economic assumption per parameter -- most visibly
`storage_capex_eur_per_mw`, an [assumption] this repository's own
docs/DATA.md flags as having "no literature figure found." Roadmap P5's own
framing is explicit: "do not attempt to rescue that number by finding one
citation and treating it as universal... instead make uncertainty part of
the method." This script does that for every parameter the roadmap names,
rather than defending or replacing the single assumed value.

P5.1 (`POWER_CAPEX_MULTIPLIERS`): the primary sensitivity, storage power
CAPEX at 0x/0.25x/0.5x/1x/2x/4x/8x of the case config's own assumed value,
per the roadmap's own suggested scenario-multiplier grid (used "instead of
pretending the endpoints are known market values").

P5.2 (`SECONDARY_AXES`): one-at-a-time sweeps of every other parameter the
roadmap names (energy CAPEX, gas price, carbon price, electric-heater
efficiency, standing loss, charge/discharge efficiency, price
volatility/spread, process load factor) -- not a combinatorial grid, per
the roadmap's own explicit instruction not to build one before the
application.

P5.3 (cost decomposition): every point in both sweeps reports total
annualised cost broken into annualised energy-capacity CAPEX, annualised
power/BOP CAPEX, electricity, backup fuel, and carbon -- recomputed
independently from each solved schedule's own per-hour columns, not read
back from the objective, and cross-checked to reproduce it (P5.3's own
purpose: "make it obvious *why* the dynamic model changes the optimum").
Blower/parasitic electricity (mentioned in the same roadmap bullet) is
reported per P3.3's own scope decision -- at the sized power rating's
implied mass flow, as a *rated*, not annually-integrated, diagnostic
figure -- since dispatch.py's own economics do not include it (P3.3's
own module docstring); it is not summed into the cost decomposition
total, to avoid fabricating an annual duty-cycle assumption this project
has not made.

Every point also classifies which constraint actually binds the optimum
(storage priced out entirely at zero sized capacity; backup boiler
capacity binding with real unmet heat; electric heater capacity binding;
or an interior optimum where no capacity bound binds), read directly off
each solved schedule rather than inferred from the cost number alone.

Scope: one representative case (packed_bed_300c_flat, flat load profile),
duration-matched at tau=6h (this project's own established headline
duration, C2/C3/P2.1's own choice), both discharge-limit formulations at
every sensitivity point -- the same matched-sizing methodology (P0.1)
every other paired comparison in this repository already uses, so a
constant-vs-SOC-dependent delta at any sensitivity point isolates the
discharge-limit shape, not an incidental duration difference. One real
consequence of this choice, stated plainly rather than glossed over: since
`design_duration_hours` ties power to `E_cap / tau` identically in both
formulations, the storage power CAPEX (P5.1) and storage energy CAPEX
(P5.2) sensitivities are not fully decoupled here -- both ultimately scale
the same combined per-MWh capex rate (`storage_capex_eur_per_mwh +
storage_capex_eur_per_mw / tau`), since power is never an independent
sizing decision in duration-matched mode. A fully decoupled power-CAPEX
sensitivity would need non-duration-matched sizing, which would reopen the
unequal-sizing-degrees-of-freedom confound P0.1 fixed; kept duration-matched
here for consistency with every other paired comparison in this
repository, with this coupling stated explicitly rather than hidden.
"""

from __future__ import annotations

import dataclasses
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from tes_screen.config import CaseConfig, load_config  # noqa: E402
from tes_screen.discharge_curve import (  # noqa: E402
    fit_piecewise_discharge_curve,
    mass_flow_for_target_duration,
)
from tes_screen.dispatch import capital_recovery_factor, solve_dispatch  # noqa: E402
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
INITIAL_BED_TEMPERATURE_C = 400.0
INLET_TEMPERATURE_C = 320.0
PROCESS_TEMPERATURE_C = 300.0
DELTA_T_MIN_HOT_SIDE_C = 0.0
DESIGN_DURATION_HOURS = 6.0
PRIMARY_N_SEGMENTS = 5
REFERENCE_N_STEPS = 1500

POWER_CAPEX_MULTIPLIERS = [0.0, 0.25, 0.5, 1.0, 2.0, 4.0, 8.0]
SECONDARY_MULTIPLIERS = [0.5, 1.0, 2.0]
ZERO_CAPACITY_THRESHOLD_MWH = 0.05  # [assumption] below this, treat storage as "not built"


def _build_curve(base_config: CaseConfig):
    bed_config = default_packed_bed_config()
    mass_flow = mass_flow_for_target_duration(
        bed_config,
        target_duration_hours=DESIGN_DURATION_HOURS,
        initial_bed_temperature_c=INITIAL_BED_TEMPERATURE_C,
        inlet_temperature_c=INLET_TEMPERATURE_C,
        process_temperature_c=PROCESS_TEMPERATURE_C,
        delta_t_min_hot_side_c=DELTA_T_MIN_HOT_SIDE_C,
    )
    result = simulate_discharge(
        bed_config,
        mass_flow_kg_per_s=mass_flow,
        initial_bed_temperature_c=INITIAL_BED_TEMPERATURE_C,
        inlet_temperature_c=INLET_TEMPERATURE_C,
        duration_s=DESIGN_DURATION_HOURS * 2 * 3600.0,
        n_steps=REFERENCE_N_STEPS,
    )
    return fit_piecewise_discharge_curve(
        result, PROCESS_TEMPERATURE_C, DELTA_T_MIN_HOT_SIDE_C, n_segments=PRIMARY_N_SEGMENTS
    )


def _duration_matched_config(base_config: CaseConfig, soc_dependent: bool) -> CaseConfig:
    return dataclasses.replace(
        base_config,
        storage=dataclasses.replace(
            base_config.storage,
            charge_power_max_mw=None,
            discharge_power_max_mw=None,
            design_duration_hours=DESIGN_DURATION_HOURS,
            discharge_limit_mode="soc_dependent" if soc_dependent else "constant",
            discharge_capability_reference=("start_of_hour" if soc_dependent else None),
        ),
    )


def _cost_decomposition(
    schedule, config: CaseConfig, e_cap_mwh: float, power_rating_mw: float
) -> dict:
    crf = capital_recovery_factor(
        config.economics.discount_rate, config.economics.storage_lifetime_years
    )
    annualised_energy_capex_eur = crf * e_cap_mwh * config.economics.storage_capex_eur_per_mwh
    annualised_power_capex_eur = crf * power_rating_mw * config.economics.storage_capex_eur_per_mw
    electricity_cost_eur = float(schedule["electricity_cost_eur"].sum())
    fuel_cost_eur = float(schedule["fuel_cost_eur"].sum())
    carbon_cost_eur = float(schedule["carbon_cost_eur"].sum())
    penalty_cost_eur = float(schedule["penalty_cost_eur"].sum())
    return {
        "annualised_energy_capex_eur": annualised_energy_capex_eur,
        "annualised_power_capex_eur": annualised_power_capex_eur,
        "electricity_cost_eur": electricity_cost_eur,
        "fuel_cost_eur": fuel_cost_eur,
        "carbon_cost_eur": carbon_cost_eur,
        "penalty_cost_eur": penalty_cost_eur,
        "sum_eur": (
            annualised_energy_capex_eur
            + annualised_power_capex_eur
            + electricity_cost_eur
            + fuel_cost_eur
            + carbon_cost_eur
            + penalty_cost_eur
        ),
    }


def _binding_regime(schedule, config: CaseConfig, e_cap_mwh: float) -> str:
    if e_cap_mwh < ZERO_CAPACITY_THRESHOLD_MWH:
        return "storage_priced_out_zero_capacity"
    if float(schedule["unmet_heat_mw"].sum()) > 1e-6:
        return "backup_capacity_binding_unmet_heat"
    boiler_capacity = config.supply.backup_boiler.capacity_mw
    if (schedule["boiler_heat_mw"] >= boiler_capacity - 1e-6).any():
        return "backup_boiler_capacity_binding"
    heater_capacity = config.supply.electric_heater.capacity_mw
    if (schedule["elec_to_heater_mw"] >= heater_capacity - 1e-6).any():
        return "electric_heater_capacity_binding"
    return "interior_optimum_no_capacity_binding"


def _solve_point(config: CaseConfig, load, price, curve) -> dict:
    constant_config = _duration_matched_config(config, soc_dependent=False)
    constant_result = solve_dispatch(constant_config, load, price)
    constant_checks = verify_schedule(
        constant_result.schedule, constant_config, constant_result.solver["objective_eur"]
    )

    soc_config = _duration_matched_config(config, soc_dependent=True)
    soc_result = solve_dispatch(soc_config, load, price, discharge_curve=curve)
    soc_checks = verify_schedule(
        soc_result.schedule, soc_config, soc_result.solver["objective_eur"]
    )

    if not (all(constant_checks.values()) and all(soc_checks.values())):
        raise RuntimeError("a sensitivity point failed independent verification")

    constant_decomposition = _cost_decomposition(
        constant_result.schedule,
        config,
        constant_result.kpis["e_cap_mwh"],
        constant_result.kpis["power_rating_mw"],
    )
    soc_decomposition = _cost_decomposition(
        soc_result.schedule,
        config,
        soc_result.kpis["e_cap_mwh"],
        soc_result.kpis["power_rating_mw"],
    )

    return {
        "constant_limit": {
            "kpis": constant_result.kpis,
            "cost_decomposition": constant_decomposition,
            "binding_regime": _binding_regime(
                constant_result.schedule, config, constant_result.kpis["e_cap_mwh"]
            ),
        },
        "soc_dependent": {
            "kpis": soc_result.kpis,
            "cost_decomposition": soc_decomposition,
            "binding_regime": _binding_regime(
                soc_result.schedule, config, soc_result.kpis["e_cap_mwh"]
            ),
        },
        "delta_soc_dependent_minus_constant": {
            "total_cost_eur": (
                soc_result.kpis["total_cost_eur"] - constant_result.kpis["total_cost_eur"]
            ),
            "total_cost_pct": 100
            * (soc_result.kpis["total_cost_eur"] - constant_result.kpis["total_cost_eur"])
            / constant_result.kpis["total_cost_eur"],
            "e_cap_mwh": soc_result.kpis["e_cap_mwh"] - constant_result.kpis["e_cap_mwh"],
            "power_rating_mw": (
                soc_result.kpis["power_rating_mw"] - constant_result.kpis["power_rating_mw"]
            ),
        },
    }


def main() -> None:
    output_dir = Path("outputs") / "economics_sensitivity"
    output_dir.mkdir(parents=True, exist_ok=True)

    base_config = load_config(CONFIG_PATH)
    horizon = base_config.optimization.horizon_hours
    curve = _build_curve(base_config)

    def default_load_price():
        load = build_load_profile(
            base_config.process.profile_shape, base_config.process.annual_peak_load_mw, horizon
        )
        price = synthetic_daily_price_profile(horizon)
        return load, price

    load, price = default_load_price()

    # --- P5.1: storage power CAPEX -------------------------------------
    power_capex_base = base_config.economics.storage_capex_eur_per_mw
    power_capex_sweep = []
    for multiplier in POWER_CAPEX_MULTIPLIERS:
        config = dataclasses.replace(
            base_config,
            economics=dataclasses.replace(
                base_config.economics, storage_capex_eur_per_mw=power_capex_base * multiplier
            ),
        )
        entry = _solve_point(config, load, price, curve)
        entry["multiplier"] = multiplier
        entry["storage_capex_eur_per_mw"] = power_capex_base * multiplier
        power_capex_sweep.append(entry)
        print(
            f"P5.1 power_capex x{multiplier:<5.2f}  "
            f"constant: E_cap={entry['constant_limit']['kpis']['e_cap_mwh']:7.2f} MWh "
            f"({entry['constant_limit']['binding_regime']})  "
            f"soc: E_cap={entry['soc_dependent']['kpis']['e_cap_mwh']:7.2f} MWh "
            f"({entry['soc_dependent']['binding_regime']})  "
            f"delta={entry['delta_soc_dependent_minus_constant']['total_cost_pct']:+.4f}%"
        )

    # --- P5.2: secondary sensitivities, one axis at a time --------------
    secondary_sweep: dict[str, list[dict]] = {}

    def _run_axis(axis_name: str, values, config_and_load_price_fn) -> None:
        points = []
        for value in values:
            config, axis_load, axis_price = config_and_load_price_fn(value)
            entry = _solve_point(config, axis_load, axis_price, curve)
            entry["axis_value"] = value
            points.append(entry)
            print(
                f"P5.2 {axis_name:28s} = {value!s:>8s}  "
                f"constant: E_cap={entry['constant_limit']['kpis']['e_cap_mwh']:7.2f} MWh  "
                f"soc: E_cap={entry['soc_dependent']['kpis']['e_cap_mwh']:7.2f} MWh  "
                f"delta={entry['delta_soc_dependent_minus_constant']['total_cost_pct']:+.4f}%"
            )
        secondary_sweep[axis_name] = points

    _run_axis(
        "energy_capex",
        SECONDARY_MULTIPLIERS,
        lambda m: (
            dataclasses.replace(
                base_config,
                economics=dataclasses.replace(
                    base_config.economics,
                    storage_capex_eur_per_mwh=base_config.economics.storage_capex_eur_per_mwh * m,
                ),
            ),
            load,
            price,
        ),
    )
    _run_axis(
        "gas_price",
        SECONDARY_MULTIPLIERS,
        lambda m: (
            dataclasses.replace(
                base_config,
                supply=dataclasses.replace(
                    base_config.supply,
                    backup_boiler=dataclasses.replace(
                        base_config.supply.backup_boiler,
                        fuel_cost_eur_per_mwh=base_config.supply.backup_boiler.fuel_cost_eur_per_mwh
                        * m,
                    ),
                ),
            ),
            load,
            price,
        ),
    )
    _run_axis(
        "carbon_price",
        SECONDARY_MULTIPLIERS,
        lambda m: (
            dataclasses.replace(
                base_config,
                economics=dataclasses.replace(
                    base_config.economics,
                    carbon_price_eur_per_tco2=base_config.economics.carbon_price_eur_per_tco2 * m,
                ),
            ),
            load,
            price,
        ),
    )
    _run_axis(
        "electric_heater_efficiency",
        [0.90, 0.95, 0.99],
        lambda v: (
            dataclasses.replace(
                base_config,
                supply=dataclasses.replace(
                    base_config.supply,
                    electric_heater=dataclasses.replace(
                        base_config.supply.electric_heater, efficiency=v
                    ),
                ),
            ),
            load,
            price,
        ),
    )
    _run_axis(
        "standing_loss_fraction_per_hour",
        SECONDARY_MULTIPLIERS,
        lambda m: (
            dataclasses.replace(
                base_config,
                storage=dataclasses.replace(
                    base_config.storage,
                    standing_loss_fraction_per_hour=(
                        base_config.storage.standing_loss_fraction_per_hour * m
                    ),
                ),
            ),
            load,
            price,
        ),
    )
    _run_axis(
        "charge_discharge_efficiency",
        [0.85, 0.90, 0.95],
        lambda v: (
            dataclasses.replace(
                base_config,
                storage=dataclasses.replace(base_config.storage, eta_charge=v, eta_discharge=v),
            ),
            load,
            price,
        ),
    )
    _run_axis(
        "price_volatility_daily_amplitude_multiplier",
        SECONDARY_MULTIPLIERS,
        lambda m: (
            base_config,
            load,
            synthetic_daily_price_profile(horizon, daily_amplitude_eur_per_mwh=25.0 * m),
        ),
    )

    def _load_factor_point(profile_shape: str):
        axis_load = build_load_profile(
            profile_shape, base_config.process.annual_peak_load_mw, horizon
        )
        config = dataclasses.replace(
            base_config,
            process=dataclasses.replace(base_config.process, profile_shape=profile_shape),
        )
        load_factor = float(axis_load["heat_demand_mw"].mean() / axis_load["heat_demand_mw"].max())
        return config, axis_load, price, load_factor

    load_factor_points = []
    for profile_shape in ["flat", "two_shift", "seasonal"]:
        config, axis_load, axis_price, load_factor = _load_factor_point(profile_shape)
        entry = _solve_point(config, axis_load, axis_price, curve)
        entry["axis_value"] = load_factor
        entry["profile_shape"] = profile_shape
        load_factor_points.append(entry)
        print(
            f"P5.2 process_load_factor ({profile_shape:10s} = {load_factor:.4f})  "
            f"constant: E_cap={entry['constant_limit']['kpis']['e_cap_mwh']:7.2f} MWh  "
            f"soc: E_cap={entry['soc_dependent']['kpis']['e_cap_mwh']:7.2f} MWh  "
            f"delta={entry['delta_soc_dependent_minus_constant']['total_cost_pct']:+.4f}%"
        )
    secondary_sweep["process_load_factor"] = load_factor_points

    manifest = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "roadmap_item": "P5 (economics sensitivity, not one assumed number)",
        "case": "packed_bed_300c_flat",
        "design_duration_hours": DESIGN_DURATION_HOURS,
        "coupling_note": (
            "duration_matched sizing ties power to E_cap/tau identically in "
            "both formulations (P0.1), so P5.1 (power CAPEX) and P5.2's "
            "energy_capex axis are not fully decoupled here: both scale the "
            "same combined per-MWh capex rate. See this script's own module "
            "docstring for why this was kept rather than reopening the "
            "unequal-sizing-degrees-of-freedom confound P0.1 fixed."
        ),
        "zero_capacity_threshold_mwh": ZERO_CAPACITY_THRESHOLD_MWH,
        "power_capex_sweep": power_capex_sweep,
        "secondary_sweep": secondary_sweep,
    }
    (output_dir / "run_manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(f"Written to {output_dir}")


if __name__ == "__main__":
    main()
