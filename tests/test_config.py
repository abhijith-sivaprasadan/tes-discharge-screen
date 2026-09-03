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
