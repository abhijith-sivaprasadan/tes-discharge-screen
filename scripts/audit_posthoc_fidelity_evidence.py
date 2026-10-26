"""Independent standard-library audit of annual TES fidelity crossover artifacts.

Checks original per-hour CSV and JSON bytes against the saved study hashes,
recalculates all yearly cost objectives, and rejects fake ranking evidence.
Does not solve the model or validate actual equipment costs.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import math
from pathlib import Path
from zipfile import ZipFile

COST_FIELDS = (
    "electricity_cost_eur",
    "fuel_cost_eur",
    "carbon_cost_eur",
    "penalty_cost_eur",
    "blower_cost_eur",
)


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def check_record(
    record: dict, config_bytes: bytes, hourly_csv: bytes, *, hours: int = 8760
) -> float:
    """Return objective reconstruction error, fail on any tampered record."""
    if record.get("status") != "OPTIMAL_VERIFIED":
        raise ValueError("Only verified solved records can be audited")
    if sha256(config_bytes) != record["config_json_sha256"]:
        raise ValueError("Configuration SHA-256 differs")
    if sha256(hourly_csv) != record["hourly_csv_sha256"]:
        raise ValueError("Hourly CSV SHA-256 differs")
    config = json.loads(config_bytes)
    if not isinstance(config, dict):
        raise ValueError("Configuration JSON is not an object")
    if config["optimization"]["horizon_hours"] != hours:
        raise ValueError("Wrong annual model horizon")
    if not all(record["verification"].values()) or not record["verification"]:
        raise ValueError("A post-solve physical verification check failed")
    solver = record.get("solver_status", {})
    if solver.get("status") != "ok" or solver.get("termination") != "optimal":
        raise ValueError("Solver did not certify an optimal loaded solution")
    rows = csv.DictReader(io.StringIO(hourly_csv.decode("utf-8")))
    summed = {field: 0.0 for field in COST_FIELDS}
    count = 0
    for idx, row in enumerate(rows):
        if idx >= hours or int(row["hour"]) != idx:
            raise ValueError("Repeated, missing or misordered hourly timestep")
        for field in COST_FIELDS:
            value = float(row[field])
            if not math.isfinite(value):
                raise ValueError(f"Nonfinite hourly {field}")
            summed[field] += value
        residual = float(row["heat_balance_residual_mw"])
        if not math.isfinite(residual) or abs(residual) > 1e-5:
            raise ValueError("Unverified annual hourly heat balance")
        count += 1
    if count != hours:
        raise ValueError(f"Expected {hours} hourly rows, got {count}")
    ec = config["economics"]
    r, n = float(ec["discount_rate"]), float(ec["storage_lifetime_years"])
    if not (0 < r < 1 and n > 0):
        raise ValueError("Invalid annualisation inputs")
    crf = r * (1 + r) ** n / ((1 + r) ** n - 1)
    capex = crf * (
        record["e_cap_mwh"] * ec["storage_capex_eur_per_mwh"]
        + record["power_rating_mw"] * ec["storage_capex_eur_per_mw"]
    )
    independently_reconstructed = capex + sum(summed.values())
    expected = float(record["total_cost_eur"])
    solver_objective = float(record["solver_objective_eur"])
    if not all(math.isfinite(v) for v in (independently_reconstructed, expected, solver_objective)):
        raise ValueError("Nonfinite annual objective")
    if abs(independently_reconstructed - expected) > 1e-4:
        raise ValueError("Archived total cost differs from original hourly accounting")
    if abs(solver_objective - expected) > 1e-4:
        raise ValueError("Solver objective differs from archived total cost")
    return independently_reconstructed - expected


def audit_archive(path: Path) -> dict:
    """Check exact archive contents; missing cases are not filled in."""
    with ZipFile(path) as z:
        manifest_paths = [
            p for p in z.namelist() if p.startswith("targeted-") and p.endswith(".json")
        ]
        if len(manifest_paths) != 1:
            raise ValueError("Expected one targeted-<profile>.json study manifest")
        name = manifest_paths[0]
        profile = name[len("targeted-") : -len(".json")]
        if profile not in {"flat", "seasonal", "two_shift"}:
            raise ValueError("Unexpected load profile")
        report = json.loads(z.read(name))
        cases = report["records"]
        distinct = {}
        reused = []
        unresolved = []
        max_objective_err = 0.0
        for rec in cases:
            key = (
                rec["molten_salt_capex_factor"],
                rec["formulation"],
                rec["technology"],
            )
            if rec.get("solve_reused_from_factor") is not None:
                reused.append(rec)
                continue
            if rec["status"] != "OPTIMAL_VERIFIED":
                if "total_cost_eur" in rec or "hourly_csv" in rec:
                    raise ValueError("Failed/unresolved case has fabricated numeric results")
                unresolved.append(key)
                continue
            directory = f"hourly-{profile}/"
            config_file = directory + rec["config_json"]
            hourly_file = directory + rec["hourly_csv"]
            err = check_record(rec, z.read(config_file), z.read(hourly_file))
            distinct[key] = rec
            max_objective_err = max(max_objective_err, abs(err))
        for rec in reused:
            key = (
                rec["solve_reused_from_factor"],
                rec["formulation"],
                rec["technology"],
            )
            original = distinct.get(key)
            if original is None or any(
                rec[k] != original[k]
                for k in ("total_cost_eur", "derived_config_sha256", "hourly_csv_sha256")
            ):
                raise ValueError("Reused packed-bed solve is not an unchanged solved source")
            if rec["technology"] != "packed_bed":
                raise ValueError("Only unperturbed packed-bed results may be reused")
        if report["number_distinct_solves"] != len(distinct) + len(unresolved):
            raise ValueError("Attempted solve count conflicts with archived cases")
        factors = report["analysis"]["cost_grid"]
        actual = {(r["molten_salt_capex_factor"], r["formulation"], r["technology"]) for r in cases}
        expected = {
            (f, form, tech)
            for f in factors
            for form in ("constant", "soc_dependent")
            for tech in ("packed_bed", "molten_salt")
        }
        if actual != expected or len(actual) != len(cases):
            raise ValueError("Unregistered, missing or duplicated study cases")
        return {
            "status": "PASS_INDEPENDENT_HOURLY_COST_AND_PROVENANCE_CHECKS",
            "profile": profile,
            "archive_sha256": sha256(path.read_bytes()),
            "distinct_solver_attempts": report["number_distinct_solves"],
            "independently_audited_8760h_solutions": len(distinct),
            "reused_reference_rows": len(reused),
            "unresolved_solver_cells": unresolved,
            "max_objective_discrepancy_eur": max_objective_err,
            "reported_formulation_disagreements": report["analysis"]["confirmed_disagreements"],
            "limits": "Numeric/accounting audit only. No physical plant or cost calibration.",
        }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", type=Path)
    args = parser.parse_args()
    print(json.dumps(audit_archive(args.archive), indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
