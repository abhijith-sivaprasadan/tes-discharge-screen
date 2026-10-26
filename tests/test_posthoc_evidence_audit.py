"""Independent saved-hour objective checks; no solver/network required."""

from __future__ import annotations

import copy
import hashlib
import json

import pytest

from scripts.audit_posthoc_fidelity_evidence import check_record


def authored_fixture():
    config = {
        "optimization": {"horizon_hours": 2},
        "economics": {
            "discount_rate": 0.06,
            "storage_lifetime_years": 25,
            "storage_capex_eur_per_mwh": 7000,
            "storage_capex_eur_per_mw": 20000,
        },
    }
    content = json.dumps(config).encode()
    csv_bytes = (
        b"hour,electricity_cost_eur,fuel_cost_eur,carbon_cost_eur,"
        b"penalty_cost_eur,blower_cost_eur,heat_balance_residual_mw\n"
        b"0,2,3,0,0,1,0\n1,4,5,0,0,2,0\n"
    )
    crf = 0.06 * (1.06**25) / (1.06**25 - 1)
    total = crf * (2 * 7000 + 3 * 20000) + 17
    record = {
        "status": "OPTIMAL_VERIFIED",
        "config_json_sha256": hashlib.sha256(content).hexdigest(),
        "hourly_csv_sha256": hashlib.sha256(csv_bytes).hexdigest(),
        "verification": {"heat_balance_closure": True, "objective_reconstruction": True},
        "solver_status": {"status": "ok", "termination": "optimal"},
        "e_cap_mwh": 2,
        "power_rating_mw": 3,
        "total_cost_eur": total,
        "solver_objective_eur": total,
    }
    return record, content, csv_bytes


def test_independently_reconstructs_annualised_capex_and_hourly_operating_cost():
    record, cfg, rows = authored_fixture()
    assert check_record(record, cfg, rows, hours=2) == pytest.approx(0)


def test_tampered_schedule_hash_rejected():
    record, cfg, rows = authored_fixture()
    with pytest.raises(ValueError, match="SHA-256"):
        check_record(record, cfg, rows.replace(b"0,2,3", b"0,8,3"), hours=2)


def test_provenance_valid_but_objective_false_rejected():
    record, cfg, rows = authored_fixture()
    modified = copy.deepcopy(record)
    modified["total_cost_eur"] += 30
    modified["solver_objective_eur"] += 30
    with pytest.raises(ValueError, match="Archived total cost"):
        check_record(modified, cfg, rows, hours=2)


def test_invalid_json_source_is_not_accepted():
    record, cfg, rows = authored_fixture()
    invalid = cfg + b"\\n"
    record["config_json_sha256"] = hashlib.sha256(invalid).hexdigest()
    with pytest.raises(json.JSONDecodeError):
        check_record(record, invalid, rows, hours=2)


def test_missing_hour_rejected_even_if_hashes_match():
    record, cfg, rows = authored_fixture()
    changed = rows.replace(b"1,4,5", b"2,4,5")
    record["hourly_csv_sha256"] = hashlib.sha256(changed).hexdigest()
    with pytest.raises(ValueError, match="misordered hourly"):
        check_record(record, cfg, changed, hours=2)


def test_nonoptimal_solver_not_passed():
    record, cfg, rows = authored_fixture()
    record["solver_status"]["termination"] = "infeasible"
    with pytest.raises(ValueError, match="optimal"):
        check_record(record, cfg, rows, hours=2)
