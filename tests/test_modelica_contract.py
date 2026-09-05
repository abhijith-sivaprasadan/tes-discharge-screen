from __future__ import annotations

from pathlib import Path

MODELICA_SOURCE = Path("modelica/tes_screen/package.mo").read_text(encoding="utf-8")


def test_modelica_model_declares_the_expected_parameters_and_states() -> None:
    for name in (
        "bedLength",
        "crossSectionArea",
        "porosity",
        "particleDiameter",
        "rockDensity",
        "rockSpecificHeat",
        "airDensity",
        "airSpecificHeat",
        "massFlow",
        "inletTemperature",
        "initialBedTemperature",
        "volumetricHeatTransferCoefficient",
        "outletTemperature",
    ):
        assert name in MODELICA_SOURCE


def test_modelica_model_has_dynamic_states_for_both_phases() -> None:
    assert "der(Tf[" in MODELICA_SOURCE
    assert "der(Ts[" in MODELICA_SOURCE


def test_modelica_outlet_is_the_last_node() -> None:
    assert "outletTemperature = Tf[n];" in MODELICA_SOURCE


def test_build_script_requests_fmi2_cosimulation() -> None:
    script = Path("scripts/build_packed_bed_fmu.mos").read_text(encoding="utf-8")
    assert 'version="2.0"' in script
    assert 'fmuType="cs"' in script
    assert 'fileNamePrefix="PackedBedThermocline"' in script
    assert "tes_screen.PackedBedThermocline" in script
