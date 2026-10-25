"""Independent consistency tests for archived C3 comparison results."""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from tes_screen.ranking_evidence import audit_ranking_evidence

ROOT = Path(__file__).resolve().parents[1] / "outputs" / "phase_c_full_matrix"


def evidence():
    return (
        json.loads((ROOT / "run_manifest.json").read_text(encoding="utf-8")),
        (ROOT / "case_deltas.csv").read_text(encoding="utf-8"),
        (ROOT / "ranking_table.csv").read_text(encoding="utf-8"),
    )


def test_archived_rankings_are_rederived_from_solver_results():
    result = audit_ranking_evidence(*evidence())
    assert result["paired_cases_verified"] == 15
    assert result["ranking_groups_verified"] == 6
    assert result["ranking_flips"] == 0
    assert len(result["margins"]) == 12
    assert all(r["fixed_output_additive_surcharge_margin_eur"] > 0 for r in result["margins"])


def test_tampered_solver_cost_fails():
    manifest, deltas, rankings = evidence()
    manifest = copy.deepcopy(manifest)
    manifest["cases"][0]["constant_limit"]["solver"]["objective_eur"] += 1000
    with pytest.raises(ValueError, match="solver objective"):
        audit_ranking_evidence(manifest, deltas, rankings)


def test_tampered_published_delta_fails():
    manifest, deltas, rankings = evidence()
    deltas = deltas.replace("835.6178239975125", "999.0", 1)
    with pytest.raises(ValueError, match="Evidence mismatch"):
        audit_ranking_evidence(manifest, deltas, rankings)


def test_tampered_ranking_fails():
    manifest, deltas, rankings = evidence()
    rankings = rankings.replace("packed_bed,packed_bed", "pcm,pcm", 1)
    with pytest.raises(ValueError, match="Published cheapest"):
        audit_ranking_evidence(manifest, deltas, rankings)


def test_duplicate_case_fails():
    manifest, deltas, rankings = evidence()
    manifest["cases"].append(copy.deepcopy(manifest["cases"][0]))
    with pytest.raises(ValueError, match="Duplicate"):
        audit_ranking_evidence(manifest, deltas, rankings)
