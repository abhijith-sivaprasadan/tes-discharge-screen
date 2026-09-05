"""OpenModelica FMU build and simulation adapter, ported from OpenSteamOpt's fmu.py.

`find_omc()` keeps the OpenModelica toolchain optional rather than a hard
dependency, exactly as it does there. This working environment has neither
`omc` nor `fmpy` installed, so none of `build_fmu`/`simulate_fmu` has ever
been exercised *here*: every function in this module fails loudly and
specifically when the toolchain is absent, rather than silently skipping.
`modelica/tes_screen/package.mo`'s `PackedBedThermocline` model has since
been compiled outside this environment (OpenModelica/OMEdit, Windows),
producing an FMI 2.0 Co-Simulation FMU with win64 binaries only -- this
sandbox is Linux with no Wine, so it cannot load that FMU either. The
FMU-vs-shadow-twin cross-check that is this project's strongest
verification story (per the build spec's own words) has therefore also
run outside this environment: `scripts/run_fmu_cross_check_experiment.py`,
on the machine holding the working FMU, using `simulate_fmu_staged` below
(plain `simulate_fmu`'s single uniform communication step turned out to be
numerically unusable for this particular model -- see that function's own
docstring). The result (0.184 C max deviation over an 80 C swing, 0.0029%
relative delivered-energy deviation across a full 8h discharge) is
committed under `outputs/fmu_cross_check/`; see the project README for the
full story.
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


def simulate_fmu_staged(fmu: Path, segments: list[tuple[float, float]]) -> pd.DataFrame:
    """Run the FMU's own Co-Simulation solver with a *variable* communication
    step size across explicit time segments, rather than `simulate_fmu`'s one
    uniform step for the whole run.

    `segments` is a list of `(segment_end_time_s, communication_step_s)`
    pairs, each applied from wherever the previous segment left off (or from
    t=0 for the first) up to `segment_end_time_s`.

    This exists because `simulate_fmu`'s single uniform `output_interval`
    genuinely cannot serve `PackedBedThermocline`: a real P4.2 run against
    the compiled FMU, at a uniform 0.05 s step, blew up to ~1e10 C by
    t=6.6s -- fluidCapacityPerVolume (245 J/(m3.K)) is ~4600x below
    solidCapacityPerVolume (1.14e6), so the sudden t=0 step change from a
    uniform 400 C bed to a 320 C inlet drives an extremely fast inlet
    boundary-layer transient -- then recovered and matched the Python
    shadow twin to <1e-3 C for the rest of that 1800 s run once past it.
    That same 0.05 s step is therefore already confirmed safe for the
    quasi-steady remainder of an arbitrarily long discharge (validated
    against 36,000 consecutive steps with no drift); only the initial
    transient itself needs the much finer step the FMU's own
    `modelDescription.xml` already recommends
    (`DefaultExperiment stepSize="0.002"`). Running that fine step for an
    entire multi-hour discharge is impractical (tens of millions of
    `doStep` calls); running it only through the transient, then the
    already-validated coarser step for the rest, is.

    Uses fmpy's low-level `FMU2Slave` interface, not the `simulate_fmu`
    convenience wrapper (which only accepts one uniform step). Requires
    fmpy. Returns a DataFrame with `time_s` and `outlet_temperature_c`
    columns (unlike `simulate_fmu`'s raw `time`/`outletTemperature`).
    """

    import fmpy  # type: ignore[import-untyped]
    from fmpy.fmi2 import FMU2Slave  # type: ignore[import-untyped]

    if not segments:
        raise ValueError("segments must be non-empty")

    model_description = fmpy.read_model_description(str(fmu))
    output_vr = next(
        variable.valueReference
        for variable in model_description.modelVariables
        if variable.name == "outletTemperature"
    )
    stop_time_s = segments[-1][0]

    unzipdir = fmpy.extract(str(fmu))
    try:
        instance = FMU2Slave(
            guid=model_description.guid,
            unzipDirectory=unzipdir,
            modelIdentifier=model_description.coSimulation.modelIdentifier,
            instanceName="tes_screen_cross_check",
        )
        instance.instantiate()
        instance.setupExperiment(startTime=0.0, stopTime=stop_time_s)
        instance.enterInitializationMode()
        instance.exitInitializationMode()

        time_s = [0.0]
        outlet_temperature_c = [instance.getReal([output_vr])[0]]
        current_time = 0.0
        for segment_end_s, step_s in segments:
            if step_s <= 0:
                raise ValueError("every segment step size must be positive")
            while current_time < segment_end_s - 1e-9:
                step = min(step_s, segment_end_s - current_time)
                instance.doStep(currentCommunicationPoint=current_time, communicationStepSize=step)
                current_time += step
                time_s.append(current_time)
                outlet_temperature_c.append(instance.getReal([output_vr])[0])

        instance.terminate()
        instance.freeInstance()
    finally:
        shutil.rmtree(unzipdir, ignore_errors=True)

    frame = pd.DataFrame({"time_s": time_s, "outlet_temperature_c": outlet_temperature_c})
    if frame.empty or not np.isfinite(frame.to_numpy(dtype=float)).all():
        raise ValueError("FMU output is empty or non-finite")
    return frame


def write_build_receipt(receipt: dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
