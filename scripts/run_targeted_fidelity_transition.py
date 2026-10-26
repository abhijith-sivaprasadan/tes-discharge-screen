"""A second, outcome-informed study zooming in on the techno-economic crossover.

Factors were picked after seeing the coarse exploratory data. Not a
preregistered confirmatory study or a vendor-cost estimate.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from scripts.run_posthoc_fidelity_crossover import run_experiment

TARGET_FACTORS = {
    "flat": (0.3825, 0.385, 0.3875),
    "two_shift": (0.3925, 0.393, 0.3935),
    "seasonal": (0.3965, 0.398, 0.399),
}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile", choices=tuple(TARGET_FACTORS), required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError("Existing report will not be overwritten")
    source_dir = args.output.parent / f"hourly-{args.profile}"
    result = run_experiment(
        args.profile,
        factors=TARGET_FACTORS[args.profile],
        hourly_output_dir=source_dir,
    )
    result["ex_post_factor_selection"] = (
        "These locations were chosen by inspecting the earlier 0.375/0.400 "
        "synthetic CAPEX-factor results. They are explicitly exploratory."
    )
    result["hourly_source_directory"] = source_dir.name
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, allow_nan=False) + "\n")
    print(json.dumps(result["analysis"], indent=2))


if __name__ == "__main__":
    main()
