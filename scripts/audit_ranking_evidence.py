"""Reconcile archived C3 solver KPIs, published tables and fixed-output margins."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from tes_screen.ranking_evidence import audit_ranking_evidence


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root", type=Path, default=Path(__file__).resolve().parents[1]
    )
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    root = args.root / "outputs" / "phase_c_full_matrix"
    result = audit_ranking_evidence(
        json.loads((root / "run_manifest.json").read_text(encoding="utf-8")),
        (root / "case_deltas.csv").read_text(encoding="utf-8"),
        (root / "ranking_table.csv").read_text(encoding="utf-8"),
    )
    content = json.dumps(result, indent=2, allow_nan=False) + "\n"
    if args.output is None:
        print(content, end="")
    else:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(content, encoding="utf-8")


if __name__ == "__main__":
    main()
