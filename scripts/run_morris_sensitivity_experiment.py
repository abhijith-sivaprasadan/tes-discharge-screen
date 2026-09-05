"""Phase D: Morris global sensitivity screening.

Usage: python scripts/run_morris_sensitivity_experiment.py

TES_SCREEN_SPEC.md section 7's second Phase D deliverable: "Sobol or
Morris on the parameters most likely to move the ranking: material cost,
heat transfer coefficient, discount rate, electricity price volatility,
process temperature."

Every prior sensitivity experiment in this repository (P5) is one-at-a-
time: every parameter but one held at its base value, per the roadmap's
own explicit instruction not to build a full multi-dimensional study
before the application. Morris elementary-effects screening (Morris,
M.D., 1991, "Factorial sampling plans for preliminary computational
experiments," Technometrics 33(2), 161-174; implemented here via SALib,
the standard library for this) is the next step up: it perturbs every
factor along randomized trajectories through the whole 5-dimensional
space at once, and reports each factor's own elementary effect (mu_star,
the mean absolute effect -- how much that factor alone moves the output on
average) and its interaction/nonlinearity indicator (sigma, the standard
deviation of that factor's effects across trajectories) -- something a
one-at-a-time sweep cannot show, since it never perturbs two factors
together.

The five factors, mapped directly onto this repository's own existing
mechanisms rather than invented ones:

- **material cost**: `economics.storage_capex_eur_per_mwh` multiplier,
  the same axis P5.2 already swept one-at-a-time.
- **heat transfer coefficient**: a multiplier on the Wakao-Kaguei
  correlation's own `h_v` output (`flow_diagnostics`), applied via
  `simulate_discharge`'s existing `heat_transfer_coefficient_override_w_per_m3k`
  parameter (already built for the B4 infinite-h_v analytic-limit test,
  reused here for its intended purpose: substituting an arbitrary h_v).
- **discount rate**: `economics.discount_rate`, direct value (not a
  multiplier -- the base 0.06 is not the centre of a physically
  meaningful multiplicative range the way a cost figure is).
- **electricity price volatility**: `synthetic_daily_price_profile`'s own
  `daily_amplitude_eur_per_mwh` multiplier, the same axis P5.2 swept.
- **process temperature**: `theta_req`, the dimensionless temperature-
  quality requirement P6 defines and already demonstrated a genuine
  cliff in packed-bed sizing across -- reused directly here rather than
  a second, redundant temperature parameterisation.

Response variable: the SOC-dependent-vs-constant annual-cost bias %, this
repository's own headline quantity of interest, at a fixed design
duration (tau=6h, the project's own established headline) and the flat
load profile. Scope: packed bed only, for the same reason P6 and P2.1
scope to it -- `h_v` and `theta_req` are both thermocline-specific
concepts that do not transfer to molten salt (no thermocline) or PCM
(a different, three-regime degradation shape) without their own separate
parameterisation, which this screening does not attempt. This is
therefore a screening of what drives the *size* of the fidelity correction
for the one technology this project's whole dynamic-modelling apparatus
was built around, not a "does the technology ranking change" Sobol study
across all three technologies -- a substantially larger undertaking the
spec's own wording ("Sobol *or* Morris") does not require choosing.

Design: N=8 Morris trajectories x 6 (5 factors + 1 baseline) = 48 sample
points, one solve pair (constant + SOC-dependent) each = 96 solves.
"""

from __future__ import annotations

import dataclasses
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
from SALib.analyze import morris as morris_analyze
from SALib.sample import morris as morris_sample

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from tes_screen.config import CaseConfig, load_config  # noqa: E402
from tes_screen.discharge_curve import fit_piecewise_discharge_curve  # noqa: E402
from tes_screen.dispatch import solve_dispatch  # noqa: E402
from tes_screen.packed_bed_dynamics import (  # noqa: E402
    bed_stored_energy_j,
    default_packed_bed_config,
    flow_diagnostics,
    simulate_discharge,
)
from tes_screen.synthetic_profiles import (  # noqa: E402
    build_load_profile,
    synthetic_daily_price_profile,
)
from tes_screen.verification import verify_schedule  # noqa: E402

CONFIG_PATH = Path("configs/packed_bed_300c_flat.yaml")
T_HOT_C = 400.0
T_RETURN_C = 320.0
DELTA_T_MIN_HOT_SIDE_C = 0.0
TAU_HOURS = 6.0
PRIMARY_N_SEGMENTS = 5
REFERENCE_N_STEPS = 1500
PROFILE_SHAPE = "flat"

N_TRAJECTORIES = 8

PROBLEM = {
    "num_vars": 5,
    "names": [
        "energy_capex_multiplier",
        "h_v_multiplier",
        "discount_rate",
        "price_volatility_multiplier",
        "theta_req",
    ],
    "bounds": [
        [0.5, 2.0],
        [0.5, 2.0],
        [0.03, 0.10],
        [0.5, 2.0],
        [-0.25, 0.9],
    ],
}


def _process_temperature_for_theta_req(theta_req: float) -> float:
    return T_RETURN_C + theta_req * (T_HOT_C - T_RETURN_C)


def _mass_flow_for_target_duration(process_temperature_c: float) -> float:
    # Closed-form, independent of h_v (a heat-transfer-rate parameter, not
    # an energy-balance one): the reference full-charge power/energy ratio
    # this solves for depends only on geometry and the two temperatures.
    bed_config = default_packed_bed_config()
    t_required_out = process_temperature_c + DELTA_T_MIN_HOT_SIDE_C
    if t_required_out >= T_HOT_C:
        raise ValueError("T_HOT_C must clear the process quality threshold")
    uniform_field = np.full(bed_config.n_nodes, T_HOT_C)
    reference_energy_j = bed_stored_energy_j(bed_config, uniform_field, uniform_field, T_RETURN_C)
    reference_energy_mwh = reference_energy_j / 3.6e9
    target_power_mw = reference_energy_mwh / TAU_HOURS
    return target_power_mw * 1e6 / (bed_config.air_specific_heat_j_per_kgk * (T_HOT_C - T_RETURN_C))


def _curve_for_sample(h_v_multiplier: float, theta_req: float):
    process_temperature_c = _process_temperature_for_theta_req(theta_req)
    bed_config = default_packed_bed_config()
    mass_flow = _mass_flow_for_target_duration(process_temperature_c)
    mass_flux = mass_flow / bed_config.cross_section_area_m2
    nominal_h_v = flow_diagnostics(
        bed_config, mass_flux
    ).volumetric_heat_transfer_coefficient_w_per_m3k
    result = simulate_discharge(
        bed_config,
        mass_flow_kg_per_s=mass_flow,
        initial_bed_temperature_c=T_HOT_C,
        inlet_temperature_c=T_RETURN_C,
        duration_s=TAU_HOURS * 2 * 3600.0,
        heat_transfer_coefficient_override_w_per_m3k=nominal_h_v * h_v_multiplier,
        n_steps=REFERENCE_N_STEPS,
    )
    curve = fit_piecewise_discharge_curve(
        result, process_temperature_c, DELTA_T_MIN_HOT_SIDE_C, n_segments=PRIMARY_N_SEGMENTS
    )
    return curve


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


def _cost_bias_pct(sample: np.ndarray, base_config: CaseConfig, horizon: int, load) -> float:
    (
        energy_capex_multiplier,
        h_v_multiplier,
        discount_rate,
        price_volatility_multiplier,
        theta_req,
    ) = sample
    curve = _curve_for_sample(h_v_multiplier, theta_req)
    config = dataclasses.replace(
        base_config,
        economics=dataclasses.replace(
            base_config.economics,
            storage_capex_eur_per_mwh=(
                base_config.economics.storage_capex_eur_per_mwh * energy_capex_multiplier
            ),
            discount_rate=discount_rate,
        ),
    )
    price = synthetic_daily_price_profile(
        horizon, daily_amplitude_eur_per_mwh=25.0 * price_volatility_multiplier
    )

    constant_config = _duration_matched_config(config, soc_dependent=False)
    constant_result = _solved(constant_config, load, price)
    soc_config = _duration_matched_config(config, soc_dependent=True)
    soc_result = _solved(soc_config, load, price, discharge_curve=curve)

    return (
        100
        * (soc_result.kpis["total_cost_eur"] - constant_result.kpis["total_cost_eur"])
        / constant_result.kpis["total_cost_eur"]
    )


def main() -> None:
    output_dir = Path("outputs") / "morris_sensitivity"
    output_dir.mkdir(parents=True, exist_ok=True)

    base_config = load_config(CONFIG_PATH)
    horizon = base_config.optimization.horizon_hours
    load = build_load_profile(PROFILE_SHAPE, base_config.process.annual_peak_load_mw, horizon)

    samples = morris_sample.sample(PROBLEM, N=N_TRAJECTORIES, num_levels=4, seed=0)
    print(f"Evaluating {len(samples)} Morris sample points ({N_TRAJECTORIES} trajectories)...")

    responses = []
    for i, sample in enumerate(samples):
        cost_bias_pct = _cost_bias_pct(sample, base_config, horizon, load)
        responses.append(cost_bias_pct)
        print(
            f"[{i + 1:3d}/{len(samples)}] energy_capex_x={sample[0]:.3f} "
            f"h_v_x={sample[1]:.3f} discount_rate={sample[2]:.4f} "
            f"price_vol_x={sample[3]:.3f} theta_req={sample[4]:+.3f}  "
            f"-> cost_bias={cost_bias_pct:+.4f}%"
        )

    responses_array = np.array(responses)
    morris_result = morris_analyze.analyze(
        PROBLEM, samples, responses_array, num_levels=4, seed=0, print_to_console=False
    )

    ranked = sorted(
        zip(PROBLEM["names"], morris_result["mu_star"], morris_result["sigma"], strict=True),
        key=lambda row: row[1],
        reverse=True,
    )
    print()
    print("Morris elementary-effects ranking (by mu_star, mean absolute effect):")
    for name, mu_star, sigma in ranked:
        print(f"  {name:32s} mu_star={mu_star:10.4f}  sigma={sigma:10.4f}")

    manifest = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "roadmap_item": "Phase D (Morris global sensitivity, TES_SCREEN_SPEC.md section 7)",
        "scope_note": (
            "Packed bed only, tau=6h, flat profile: h_v and theta_req are "
            "both thermocline-specific concepts that do not transfer to "
            "molten salt or PCM without their own separate "
            "parameterisation. Screens what drives the size of the "
            "SOC-dependent-vs-constant cost bias for this technology, not "
            "a cross-technology ranking-change Sobol study."
        ),
        "problem": PROBLEM,
        "n_trajectories": N_TRAJECTORIES,
        "response_variable": "soc_dependent_minus_constant_total_cost_pct",
        "samples": samples.tolist(),
        "responses": responses,
        "mu_star": dict(zip(PROBLEM["names"], morris_result["mu_star"].tolist(), strict=True)),
        "mu_star_conf": dict(
            zip(PROBLEM["names"], morris_result["mu_star_conf"], strict=True)
        ),
        "sigma": dict(zip(PROBLEM["names"], morris_result["sigma"].tolist(), strict=True)),
        "mu": dict(zip(PROBLEM["names"], morris_result["mu"].tolist(), strict=True)),
        "ranked_by_mu_star": [name for name, _, _ in ranked],
    }
    (output_dir / "run_manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(f"Written to {output_dir}")


if __name__ == "__main__":
    main()
