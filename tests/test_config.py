from __future__ import annotations

from pathlib import Path

import pytest

from tes_screen.config import (
    BackupBoilerConfig,
    CaseConfig,
    EconomicsConfig,
    ElectricHeaterConfig,
    OptimizationConfig,
    ProcessConfig,
    StorageConfig,
    SupplyConfig,
    load_config,
)

FIXTURES = Path(__file__).parent / "fixtures"


def _valid_storage(**overrides: object) -> StorageConfig:
    fields = dict(
        technology="packed_bed",
        energy_capacity_mwh=None,
        charge_power_max_mw=None,
        discharge_power_max_mw=None,
        eta_charge=0.95,
        eta_discharge=0.95,
        standing_loss_fraction_per_hour=0.002,
        temperature_max_c=400.0,
        temperature_min_c=320.0,
        soc_init_fraction=0.5,
        soc_final_min_fraction=0.5,
        discharge_limit_mode="constant",
        design_duration_hours=None,
        discharge_capability_reference=None,
        cycling_prevention_mode="none",
    )
    fields.update(overrides)
    return StorageConfig(**fields)


def test_valid_config_loads_and_validates() -> None:
    config = load_config(FIXTURES / "valid_config.yaml")
    assert isinstance(config, CaseConfig)
    assert config.storage.technology == "packed_bed"
    assert config.process.delivery_temperature_c == 300.0
    assert config.optimization.horizon_hours == 8760


def test_broken_config_fails_loudly_and_names_the_contract() -> None:
    with pytest.raises(ValueError) as excinfo:
        load_config(FIXTURES / "broken_config.yaml")
    message = str(excinfo.value)
    assert "process" in message
    assert "annual_peak_load_mw" in message
    assert "notes" in message


def test_example_config_in_repo_loads() -> None:
    example = Path(__file__).parents[1] / "configs" / "packed_bed_300c_flat.yaml"
    config = load_config(example)
    config.validate()


@pytest.mark.parametrize(
    "overrides",
    [
        {"eta_charge": 1.5},
        {"eta_discharge": 0.0},
        {"standing_loss_fraction_per_hour": -0.01},
        {"standing_loss_fraction_per_hour": 1.0},
        {"temperature_min_c": 400.0, "temperature_max_c": 400.0},
        {"soc_init_fraction": 1.5},
        {"technology": "diesel_generator"},
        {"discharge_limit_mode": "sometimes"},
    ],
)
def test_storage_config_rejects_out_of_range_values(overrides: dict[str, object]) -> None:
    storage = _valid_storage(**overrides)
    with pytest.raises(ValueError):
        storage.validate()


def test_storage_config_rejects_design_duration_with_a_given_charge_power() -> None:
    # C2's matched-sizing fix: design_duration_hours ties power to E_cap, so
    # a config that also gives an explicit charge_power_max_mw would have one
    # value silently overridden by the other; reject instead.
    storage = _valid_storage(design_duration_hours=4.0, charge_power_max_mw=5.0)
    with pytest.raises(ValueError, match="design_duration_hours"):
        storage.validate()


def test_storage_config_rejects_design_duration_with_a_given_discharge_power() -> None:
    storage = _valid_storage(design_duration_hours=4.0, discharge_power_max_mw=5.0)
    with pytest.raises(ValueError, match="design_duration_hours"):
        storage.validate()


def test_storage_config_accepts_design_duration_with_both_powers_null() -> None:
    storage = _valid_storage(design_duration_hours=4.0)
    storage.validate()


def test_storage_config_rejects_soc_dependent_without_a_capability_reference() -> None:
    # P0.4: whether the discharge-capability constraint reads the pre- or
    # post-dispatch level is a modelling choice, never a hidden default.
    storage = _valid_storage(discharge_limit_mode="soc_dependent")
    with pytest.raises(ValueError, match="discharge_capability_reference"):
        storage.validate()


@pytest.mark.parametrize("reference", ["start_of_hour", "end_of_hour"])
def test_storage_config_accepts_soc_dependent_with_a_valid_capability_reference(reference) -> None:
    storage = _valid_storage(
        discharge_limit_mode="soc_dependent", discharge_capability_reference=reference
    )
    storage.validate()


def test_storage_config_rejects_soc_dependent_with_an_unknown_capability_reference() -> None:
    storage = _valid_storage(
        discharge_limit_mode="soc_dependent", discharge_capability_reference="mid_hour"
    )
    with pytest.raises(ValueError, match="discharge_capability_reference"):
        storage.validate()


def test_storage_config_rejects_a_capability_reference_given_under_constant_mode() -> None:
    # Would otherwise be silently ignored: the constant limit doesn't depend
    # on level at all, so a given value here can't mean anything.
    storage = _valid_storage(discharge_capability_reference="start_of_hour")
    with pytest.raises(ValueError, match="discharge_capability_reference"):
        storage.validate()


@pytest.mark.parametrize("mode", ["none", "milp_binary"])
def test_storage_config_accepts_valid_cycling_prevention_modes(mode) -> None:
    storage = _valid_storage(cycling_prevention_mode=mode)
    storage.validate()


def test_storage_config_rejects_an_unknown_cycling_prevention_mode() -> None:
    storage = _valid_storage(cycling_prevention_mode="throughput_penalty")
    with pytest.raises(ValueError, match="cycling_prevention_mode"):
        storage.validate()


def test_process_config_rejects_bad_medium() -> None:
    process = ProcessConfig(
        delivery_temperature_c=300.0,
        medium="lava",
        profile_shape="flat",
        profile_path="x.csv",
        annual_peak_load_mw=1.0,
    )
    with pytest.raises(ValueError):
        process.validate()


def test_economics_config_rejects_discount_rate_out_of_range() -> None:
    economics = EconomicsConfig(
        currency="EUR",
        discount_rate=1.2,
        storage_lifetime_years=25.0,
        storage_capex_eur_per_mwh=1.0,
        storage_capex_eur_per_mw=1.0,
        carbon_price_eur_per_tco2=0.0,
    )
    with pytest.raises(ValueError):
        economics.validate()


def test_optimization_config_rejects_zero_horizon() -> None:
    optimization = OptimizationConfig(
        solver="highs", horizon_hours=0, time_limit_seconds=60.0, mip_gap=0.01
    )
    with pytest.raises(ValueError):
        optimization.validate()


def test_supply_config_validates_nested_sections() -> None:
    supply = SupplyConfig(
        electric_heater=ElectricHeaterConfig(efficiency=1.5, capacity_mw=1.0),
        backup_boiler=BackupBoilerConfig(
            fuel="natural_gas",
            fuel_cost_eur_per_mwh=1.0,
            emission_factor_kg_co2_per_mwh=1.0,
            capacity_mw=1.0,
        ),
        electricity_price_source="entso_e",
    )
    with pytest.raises(ValueError):
        supply.validate()
