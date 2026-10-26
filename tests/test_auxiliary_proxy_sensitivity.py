"""Controls for an explicitly hypothetical molten-salt parasitic screen."""

from scripts.run_auxiliary_proxy_sensitivity import (
    FORMULATIONS,
    PROXY_PARASITIC_FACTORS,
    TARGET_SALT_CAPEX_FACTORS,
    grid,
)


def test_preregistered_after_finding_fidelity_crossovers():
    assert len(grid()) == 8
    assert len(PROXY_PARASITIC_FACTORS) == 4
    assert PROXY_PARASITIC_FACTORS[0] == 0
    assert PROXY_PARASITIC_FACTORS == tuple(sorted(set(PROXY_PARASITIC_FACTORS)))
    assert set(FORMULATIONS) == {"constant", "soc_dependent"}
    assert TARGET_SALT_CAPEX_FACTORS == {
        "flat": 0.385,
        "two_shift": 0.393,
        "seasonal": 0.3965,
    }
