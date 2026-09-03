"""OpenModelica FMU build and simulation adapter, ported from OpenSteamOpt's fmu.py.

`find_omc()` keeps the OpenModelica toolchain optional rather than a hard
dependency, exactly as it does there. This working environment has neither
`omc` nor `fmpy` installed, so nothing in this module has been exercised:
`modelica/tes_screen/package.mo`'s `PackedBedThermocline` model has been
authored but not compiled, and the FMU-vs-shadow-twin cross-check that would
be this project's strongest verification story (per the build spec's own
words) has not been run. Every function here fails loudly and specifically
when the toolchain is absent, rather than silently skipping.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


def find_omc() -> Path | None:
    explicit = os.environ.get("TES_SCREEN_OMC")
    candidates = [
        Path(explicit) if explicit else None,
        Path(r"C:\Program Files\OpenModelica1.27.0-64bit\bin\omc.exe"),
        Path(r"C:\Program Files\OpenModelica1.26.3-64bit\bin\omc.exe"),
    ]
    command = shutil.which("omc")
    if command:
        candidates.insert(0, Path(command))
    return next((path for path in candidates if path and path.is_file()), None)


def build_fmu(project_root: Path, output_dir: Path) -> dict[str, Any]:
    """Export PackedBedThermocline as FMI 2.0 Co-Simulation. Requires OpenModelica."""

    omc = find_omc()
    if omc is None:
        raise FileNotFoundError(
            "OpenModelica omc was not found; set TES_SCREEN_OMC. Not available in this "
            "working environment; see fmu.py's module docstring."
        )
    output_dir.mkdir(parents=True, exist_ok=True)
    script = project_root / "scripts" / "build_packed_bed_fmu.mos"
    completed = subprocess.run(
        [str(omc), str(script)],
        cwd=output_dir,
        text=True,
        capture_output=True,
        check=False,
        timeout=180,
    )
    log = output_dir / "openmodelica-build.log"
    log.write_text(completed.stdout + completed.stderr, encoding="utf-8")
    fmu = output_dir / "PackedBedThermocline.fmu"
    if completed.returncode != 0 or not fmu.is_file():
        raise RuntimeError(f"OpenModelica FMU export failed; inspect {log}")
    return {
        "omc": str(omc),
        "returncode": completed.returncode,
        "fmu": str(fmu),
        "bytes": fmu.stat().st_size,
        "log": str(log),
    }


def simulate_fmu(fmu: Path, stop_time_s: float, output_interval: float = 60.0) -> pd.DataFrame:
    """Run the exported FMU at its default (constant-input) parameters. Requires fmpy."""

    from fmpy import simulate_fmu as _simulate_fmu  # type: ignore[import-untyped]

    output = ["outletTemperature"]
    result = _simulate_fmu(
        str(fmu),
        start_time=0.0,
        stop_time=stop_time_s,
        output=output,
        output_interval=output_interval,
        fmi_type="CoSimulation",
    )
    frame = pd.DataFrame({name: result[name] for name in result.dtype.names or ()})
    if set(frame.columns) != {"time", *output}:
        raise ValueError("FMU output contract changed")
    if frame.empty or not np.isfinite(frame.to_numpy(dtype=float)).all():
        raise ValueError("FMU output is empty or non-finite")
    return frame


def write_build_receipt(receipt: dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
