"""Case configuration schema: one YAML file per case, five required sections.

No physical, economic or solver parameter may live in source. Every value a case
needs comes from the YAML file loaded here. The loader fails loudly, naming the
missing or unexpected keys, rather than filling gaps with defaults.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import yaml

_TOP_LEVEL_SECTIONS = {"case_name", "process", "storage", "supply", "economics", "optimization"}

_TECHNOLOGIES = {"molten_salt", "packed_bed", "pcm"}
_PROFILE_SHAPES = {"flat", "two_shift", "seasonal"}
_DISCHARGE_LIMIT_MODES = {"constant", "soc_dependent"}
_DISCHARGE_CAPABILITY_REFERENCES = {"start_of_hour", "end_of_hour"}
_ELECTRICITY_PRICE_SOURCES = {"entso_e", "synthetic"}


def _require_keys(section_name: str, data: dict[str, Any], required: set[str]) -> None:
    present = set(data)
    missing = required - present
    unexpected = present - required
    if missing or unexpected:
        parts = [f"config section '{section_name}' does not match its contract."]
        if missing:
            parts.append(f"missing: {sorted(missing)}")
        if unexpected:
            parts.append(f"unexpected: {sorted(unexpected)}")
        parts.append(f"required keys are: {sorted(required)}")
        raise ValueError(" ".join(parts))


@dataclass(frozen=True)
class ProcessConfig:
    """The industrial heat load this case serves."""

    delivery_temperature_c: float
    medium: str
    profile_shape: str
    profile_path: str
    annual_peak_load_mw: float

    _REQUIRED = frozenset(
        {"delivery_temperature_c", "medium", "profile_shape", "profile_path", "annual_peak_load_mw"}
    )

    def validate(self) -> None:
        if self.delivery_temperature_c <= 0:
            raise ValueError("process.delivery_temperature_c must be positive")
        if self.medium not in {"steam", "air"}:
            raise ValueError(f"process.medium must be 'steam' or 'air', got {self.medium!r}")
        if self.profile_shape not in _PROFILE_SHAPES:
            raise ValueError(f"process.profile_shape must be one of {sorted(_PROFILE_SHAPES)}")
        if self.annual_peak_load_mw <= 0:
            raise ValueError("process.annual_peak_load_mw must be positive")
        if not self.profile_path:
            raise ValueError("process.profile_path must not be empty")


@dataclass(frozen=True)
class StorageConfig:
    """Generic storage block, parameterised by technology.

    ``discharge_limit_mode`` is the assumption this project exists to test: the
    baseline model (Phase A) uses 'constant'; the corrected model (Phase C) uses
    'soc_dependent'. Both are valid config states, never chosen in source.
    """

    technology: str
    energy_capacity_mwh: float | None
    charge_power_max_mw: float | None
    discharge_power_max_mw: float | None
    eta_charge: float
    eta_discharge: float
    standing_loss_fraction_per_hour: float
    temperature_max_c: float
    temperature_min_c: float
    soc_init_fraction: float
    soc_final_min_fraction: float
    discharge_limit_mode: str
    design_duration_hours: float | None
    discharge_capability_reference: str | None

    _REQUIRED = frozenset(
        {
            "technology",
            "energy_capacity_mwh",
            "charge_power_max_mw",
            "discharge_power_max_mw",
            "eta_charge",
            "eta_discharge",
            "standing_loss_fraction_per_hour",
            "temperature_max_c",
            "temperature_min_c",
            "soc_init_fraction",
            "soc_final_min_fraction",
            "discharge_limit_mode",
            "design_duration_hours",
            "discharge_capability_reference",
        }
    )

    def validate(self) -> None:
        if self.technology not in _TECHNOLOGIES:
            raise ValueError(f"storage.technology must be one of {sorted(_TECHNOLOGIES)}")
        for name, value in (
            ("energy_capacity_mwh", self.energy_capacity_mwh),
            ("charge_power_max_mw", self.charge_power_max_mw),
            ("discharge_power_max_mw", self.discharge_power_max_mw),
            ("design_duration_hours", self.design_duration_hours),
        ):
            if value is not None and value <= 0:
                raise ValueError(f"storage.{name} must be positive when given, or null")
        for name, value in (("eta_charge", self.eta_charge), ("eta_discharge", self.eta_discharge)):
            if not 0 < value <= 1:
                raise ValueError(f"storage.{name} must be in (0, 1]")
        if not 0 <= self.standing_loss_fraction_per_hour < 1:
            raise ValueError("storage.standing_loss_fraction_per_hour must be in [0, 1)")
        if self.temperature_min_c >= self.temperature_max_c:
            raise ValueError("storage.temperature_min_c must be below storage.temperature_max_c")
        for name, value in (
            ("soc_init_fraction", self.soc_init_fraction),
            ("soc_final_min_fraction", self.soc_final_min_fraction),
        ):
            if not 0 <= value <= 1:
                raise ValueError(f"storage.{name} must be in [0, 1]")
        if self.discharge_limit_mode not in _DISCHARGE_LIMIT_MODES:
            raise ValueError(
                f"storage.discharge_limit_mode must be one of {sorted(_DISCHARGE_LIMIT_MODES)}"
            )
        if self.design_duration_hours is not None and (
            self.charge_power_max_mw is not None or self.discharge_power_max_mw is not None
        ):
            raise ValueError(
                "storage.design_duration_hours ties charge/discharge power to E_cap; "
                "charge_power_max_mw and discharge_power_max_mw must both be null when it is set, "
                "not silently overridden."
            )
        if self.discharge_limit_mode == "soc_dependent":
            if self.discharge_capability_reference not in _DISCHARGE_CAPABILITY_REFERENCES:
                raise ValueError(
                    "storage.discharge_capability_reference must be one of "
                    f"{sorted(_DISCHARGE_CAPABILITY_REFERENCES)} when discharge_limit_mode == "
                    "'soc_dependent': whether the piecewise discharge limit reads the pre- or "
                    "post-dispatch level is a modelling choice (roadmap P0.4), never a hidden "
                    "default."
                )
        elif self.discharge_capability_reference is not None:
            raise ValueError(
                "storage.discharge_capability_reference only means something when "
                "discharge_limit_mode == 'soc_dependent' (the constant limit does not depend on "
                "level at all); it must be null here, not silently ignored."
            )


@dataclass(frozen=True)
class BackupBoilerConfig:
    fuel: str
    fuel_cost_eur_per_mwh: float
    emission_factor_kg_co2_per_mwh: float
    capacity_mw: float

    _REQUIRED = frozenset(
        {"fuel", "fuel_cost_eur_per_mwh", "emission_factor_kg_co2_per_mwh", "capacity_mw"}
    )

    def validate(self) -> None:
        if not self.fuel:
            raise ValueError("supply.backup_boiler.fuel must not be empty")
        if self.fuel_cost_eur_per_mwh < 0:
            raise ValueError("supply.backup_boiler.fuel_cost_eur_per_mwh must be nonnegative")
        if self.emission_factor_kg_co2_per_mwh < 0:
            raise ValueError(
                "supply.backup_boiler.emission_factor_kg_co2_per_mwh must be nonnegative"
            )
        if self.capacity_mw <= 0:
            raise ValueError("supply.backup_boiler.capacity_mw must be positive")


@dataclass(frozen=True)
class ElectricHeaterConfig:
    efficiency: float
    capacity_mw: float

    _REQUIRED = frozenset({"efficiency", "capacity_mw"})

    def validate(self) -> None:
        if not 0 < self.efficiency <= 1:
            raise ValueError("supply.electric_heater.efficiency must be in (0, 1]")
        if self.capacity_mw <= 0:
            raise ValueError("supply.electric_heater.capacity_mw must be positive")


@dataclass(frozen=True)
class SupplyConfig:
    """Deliberately thin: the project is about the store, not the source."""

    electric_heater: ElectricHeaterConfig
    backup_boiler: BackupBoilerConfig
    electricity_price_source: str

    _REQUIRED = frozenset({"electric_heater", "backup_boiler", "electricity_price_source"})

    def validate(self) -> None:
        self.electric_heater.validate()
        self.backup_boiler.validate()
        if self.electricity_price_source not in _ELECTRICITY_PRICE_SOURCES:
            raise ValueError(
                "supply.electricity_price_source must be one of "
                f"{sorted(_ELECTRICITY_PRICE_SOURCES)}"
            )


@dataclass(frozen=True)
class EconomicsConfig:
    currency: str
    discount_rate: float
    storage_lifetime_years: float
    storage_capex_eur_per_mwh: float
    storage_capex_eur_per_mw: float
    carbon_price_eur_per_tco2: float

    _REQUIRED = frozenset(
        {
            "currency",
            "discount_rate",
            "storage_lifetime_years",
            "storage_capex_eur_per_mwh",
            "storage_capex_eur_per_mw",
            "carbon_price_eur_per_tco2",
        }
    )

    def validate(self) -> None:
        if not self.currency:
            raise ValueError("economics.currency must not be empty")
        if not 0 < self.discount_rate < 1:
            raise ValueError("economics.discount_rate must be in (0, 1)")
        if self.storage_lifetime_years <= 0:
            raise ValueError("economics.storage_lifetime_years must be positive")
        for name in ("storage_capex_eur_per_mwh", "storage_capex_eur_per_mw"):
            if getattr(self, name) < 0:
                raise ValueError(f"economics.{name} must be nonnegative")
        if self.carbon_price_eur_per_tco2 < 0:
            raise ValueError("economics.carbon_price_eur_per_tco2 must be nonnegative")


@dataclass(frozen=True)
class OptimizationConfig:
    solver: str
    horizon_hours: int
    time_limit_seconds: float
    mip_gap: float

    _REQUIRED = frozenset({"solver", "horizon_hours", "time_limit_seconds", "mip_gap"})

    def validate(self) -> None:
        if not self.solver:
            raise ValueError("optimization.solver must not be empty")
        if self.horizon_hours <= 0:
            raise ValueError("optimization.horizon_hours must be positive")
        if self.time_limit_seconds <= 0:
            raise ValueError("optimization.time_limit_seconds must be positive")
        if not 0 <= self.mip_gap < 1:
            raise ValueError("optimization.mip_gap must be in [0, 1)")


@dataclass(frozen=True)
class CaseConfig:
    """A fully validated, self-contained case: everything needed for one run."""

    case_name: str
    process: ProcessConfig
    storage: StorageConfig
    supply: SupplyConfig
    economics: EconomicsConfig
    optimization: OptimizationConfig

    def validate(self) -> None:
        if not self.case_name:
            raise ValueError("case_name must not be empty")
        self.process.validate()
        self.storage.validate()
        self.supply.validate()
        self.economics.validate()
        self.optimization.validate()

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def load_config(path: str | Path) -> CaseConfig:
    """Load and validate one case config. Raises ValueError naming the contract violation."""

    path = Path(path)
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError(f"{path}: config must be a YAML mapping at the top level")

    _require_keys("top level", raw, _TOP_LEVEL_SECTIONS)

    _require_keys(
        "supply.electric_heater",
        raw["supply"]["electric_heater"],
        ElectricHeaterConfig._REQUIRED,
    )
    _require_keys(
        "supply.backup_boiler", raw["supply"]["backup_boiler"], BackupBoilerConfig._REQUIRED
    )
    _require_keys("supply", raw["supply"], SupplyConfig._REQUIRED)

    _require_keys("process", raw["process"], ProcessConfig._REQUIRED)
    _require_keys("storage", raw["storage"], StorageConfig._REQUIRED)
    _require_keys("economics", raw["economics"], EconomicsConfig._REQUIRED)
    _require_keys("optimization", raw["optimization"], OptimizationConfig._REQUIRED)

    try:
        config = CaseConfig(
            case_name=raw["case_name"],
            process=ProcessConfig(**raw["process"]),
            storage=StorageConfig(**raw["storage"]),
            supply=SupplyConfig(
                electric_heater=ElectricHeaterConfig(**raw["supply"]["electric_heater"]),
                backup_boiler=BackupBoilerConfig(**raw["supply"]["backup_boiler"]),
                electricity_price_source=raw["supply"]["electricity_price_source"],
            ),
            economics=EconomicsConfig(**raw["economics"]),
            optimization=OptimizationConfig(**raw["optimization"]),
        )
    except TypeError as exc:
        raise ValueError(f"{path}: config field has the wrong shape: {exc}") from exc

    config.validate()
    return config
