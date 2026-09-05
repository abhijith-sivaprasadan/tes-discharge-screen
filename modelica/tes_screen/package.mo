within ;
package tes_screen
  "Techno-economic screening of thermal storage for industrial process heat: Phase B dynamic sub-models"

  model PackedBedThermocline
    "One-dimensional two-phase packed-bed thermocline discharge model (Schumann 1929); see annotation for full documentation"
    parameter Integer n(min=1) = 40 "Number of axial control volumes";
    parameter Real bedLength(unit="m") = 5.0;
    parameter Real crossSectionArea(unit="m2") = 10.0;
    parameter Real porosity(min=0, max=1) = 0.4;
    parameter Real particleDiameter(unit="m") = 0.03;
    parameter Real rockDensity(unit="kg/m3") = 2400;
    parameter Real rockSpecificHeat(unit="J/(kg.K)") = 790;
    parameter Real airDensity(unit="kg/m3") = 0.565;
    parameter Real airSpecificHeat(unit="J/(kg.K)") = 1085;
    parameter Real massFlow(unit="kg/s") = 3.0 "Constant discharge draw rate";
    parameter Real inletTemperature(unit="degC") = 320
      "Fixed cold-return temperature entering node 1";
    parameter Real initialBedTemperature(unit="degC") = 400
      "Uniform initial temperature: a fully-charged bed";
    parameter Real volumetricHeatTransferCoefficient(unit="W/(m3.K)") = 5800
      "Fixed h_v (from the Python twin's Wakao-Kaguei correlation, not recomputed here); see annotation";

    Modelica.Blocks.Interfaces.RealOutput outletTemperature(unit="degC")
      "Delivered discharge temperature: node n's fluid temperature";

  protected
    Real Tf[n](each unit="degC", each start=initialBedTemperature);
    Real Ts[n](each unit="degC", each start=initialBedTemperature);
    parameter Real dx(unit="m") = bedLength / n;
    parameter Real massFlux(unit="kg/(m2.s)") = massFlow / crossSectionArea;
    parameter Real fluidCapacityPerVolume(unit="J/(m3.K)") =
      porosity * airDensity * airSpecificHeat;
    parameter Real solidCapacityPerVolume(unit="J/(m3.K)") =
      (1 - porosity) * rockDensity * rockSpecificHeat;
    parameter Real advectiveRatePerVolume(unit="W/(m3.K)") =
      massFlux * airSpecificHeat;

  initial equation
    for i in 1:n loop
      Tf[i] = initialBedTemperature;
      Ts[i] = initialBedTemperature;
    end for;

  equation
    fluidCapacityPerVolume * der(Tf[1]) =
      advectiveRatePerVolume * (inletTemperature - Tf[1]) / dx
      + volumetricHeatTransferCoefficient * (Ts[1] - Tf[1]);
    solidCapacityPerVolume * der(Ts[1]) =
      volumetricHeatTransferCoefficient * (Tf[1] - Ts[1]);

    for i in 2:n loop
      fluidCapacityPerVolume * der(Tf[i]) =
        advectiveRatePerVolume * (Tf[i - 1] - Tf[i]) / dx
        + volumetricHeatTransferCoefficient * (Ts[i] - Tf[i]);
      solidCapacityPerVolume * der(Ts[i]) =
        volumetricHeatTransferCoefficient * (Tf[i] - Ts[i]);
    end for;

    outletTemperature = Tf[n];

    annotation(Documentation(info="<html>
    <p>One-dimensional two-phase (solid/fluid) packed-bed thermocline discharge
    model. Textbook formulation, not a contribution in itself: Schumann's
    two-phase packed-bed model (Schumann, T.E.W., 1929, Journal of the
    Franklin Institute 208(3), 405-416), axial conduction neglected, the
    fluid and solid energy equations coupled by a volumetric heat transfer
    coefficient. Discretised into n axial control volumes; node 1 sees the
    fixed cold inlet, node n's fluid temperature is the delivered discharge
    temperature.</p>
    <p>This is the Modelica half of the pair with
    src/tes_screen/packed_bed_dynamics.py's pure-Python shadow twin, which
    solves the identical governing equations with a hand-derived implicit
    time-stepping scheme rather than Modelica's own variable-step
    integrator. Cross-checking the two (OpenSteamOpt's verification
    pattern) requires exporting this model as an FMU via OpenModelica
    (scripts/build_packed_bed_fmu.mos, src/tes_screen/fmu.py); no
    OpenModelica toolchain is available in this working environment, so
    neither compiling this model nor running that cross-check happens
    here. Both have been done outside this environment (OpenModelica/
    OMEdit, Windows; scripts/run_fmu_cross_check_experiment.py), and the
    result is committed under outputs/fmu_cross_check/: over a full 8h
    discharge, the two independent implementations agree to within 0.184 C
    max deviation (an 80 C swing) and 0.0029% relative delivered energy.
    See the project README and fmu.py's module docstring for the full
    story, and docs/DATA.md for every cited material property.</p>
    </html>"));
  end PackedBedThermocline;
end tes_screen;
