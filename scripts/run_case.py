"""Annual run harness: solve one case config end to end and commit its evidence.

Usage: python scripts/run_case.py configs/packed_bed_300c_flat.yaml

Generates the case's synthetic load and price profiles from its config,
solves the Phase A dispatch LP, runs every independent verification check
(raising if any fails rather than writing an unverified result), and writes
`outputs/<case_name>/{config.yaml, schedule.csv, run_manifest.json}`. The
manifest carries the solver status, KPIs, and which checks passed, so every
number in the schedule traces back to a config and a solver run, per the
project's governing rules.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from tes_screen.config import load_config  # noqa: E402
from tes_screen.dispatch import solve_dispatch  # noqa: E402
from tes_screen.synthetic_profiles import (  # noqa: E402
    build_load_profile,
    synthetic_daily_price_profile,
)
from tes_screen.verification import verify_schedule  # noqa: E402


def run_case(config_path: Path, output_root: Path) -> Path:
    config = load_config(config_path)

    if config.supply.electricity_price_source != "synthetic":
        raise NotImplementedError(
            f"{config_path}: electricity_price_source={config.supply.electricity_price_source!r} "
            "is not runnable in this environment (no ENTSOE_API_KEY); use 'synthetic'."
        )

    horizon = config.optimization.horizon_hours
    load = build_load_profile(
        config.process.profile_shape, config.process.annual_peak_load_mw, horizon
    )
    price = synthetic_daily_price_profile(horizon)

    result = solve_dispatch(config, load, price)
    checks = verify_schedule(result.schedule, config, result.solver["objective_eur"])
    failed = [name for name, passed in checks.items() if not passed]

    output_dir = output_root / config.case_name
    output_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy(config_path, output_dir / "config.yaml")
    result.schedule.to_csv(output_dir / "schedule.csv", index=False)

    manifest = {
        "case_name": config.case_name,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "profile_shape": config.process.profile_shape,
        "load_profile_synthetic": True,
        "electricity_price_synthetic": True,
        "solver": result.solver,
        "kpis": result.kpis,
        "verification_checks": checks,
        "verification_passed": not failed,
        "verification_failed_checks": failed,
    }
    (output_dir / "run_manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )

    if failed:
        raise ValueError(f"{config_path}: verification failed, checks: {failed}. See {output_dir}")

    return output_dir


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("config", type=Path)
    parser.add_argument("--output-root", type=Path, default=Path("outputs"))
    args = parser.parse_args()

    output_dir = run_case(args.config, args.output_root)
    manifest = json.loads((output_dir / "run_manifest.json").read_text(encoding="utf-8"))
    print(
        f"Solved {manifest['case_name']}: {manifest['solver']['termination']}, "
        f"objective={manifest['solver']['objective_eur']:,.2f} EUR, "
        f"verification_passed={manifest['verification_passed']}"
    )
    print(f"Written to {output_dir}")


if __name__ == "__main__":
    main()
