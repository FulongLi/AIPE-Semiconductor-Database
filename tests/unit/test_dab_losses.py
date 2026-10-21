import json

import pytest
from conftest import ROOT

from aipe_devices.domain.conditions import ConditionParameter, OperatingCondition
from aipe_devices.domain.curves import Axis, CharacteristicData, Curve
from aipe_devices.domain.device import PowerSemiconductorDevice
from aipe_devices.domain.identity import DeviceIdentity
from aipe_devices.domain.models import ModelReference
from aipe_devices.domain.provenance import Provenance, Source
from aipe_devices.domain.quantities import Quantity
from aipe_devices.domain.thermal import ThermalElement, ThermalNetwork
from aipe_devices.services.interpolation import EnvelopePolicy
from aipe_devices.services.loss import LossEvaluator
from aipe_devices.services.loss.dab import DABLossEvaluator, operating_point
from aipe_devices.services.loss.plecs_formula import (
    FormulaError,
    evaluate_formula,
    formula_variables,
    gate_resistance_factor,
)
from aipe_devices.services.loss.stress import (
    SwitchStress,
    SwitchWaveform,
    stress_from_summary,
    stress_from_waveform,
)
from aipe_devices.services.validation import validate_device

SOURCE = Source(id="s", kind="simulation_model", name="Synthetic loss fixture")
PROVENANCE = Provenance(origin="manufacturer_model", source_ids=("s",))
R_COLD, R_HOT = 0.05, 0.08  # Ohm at 298.15 K and 423.15 K; linear in between
K_EOFF = 5e-8  # J per (V*A)
FORMULA = "E/(1)*(1+0.1*Rgoff)"


def resistance(tj):
    return R_COLD + (R_HOT - R_COLD) * (tj - 298.15) / 125.0


def synthetic_device(with_formula=True, with_reverse=True):
    temperatures = (298.15, 423.15, 1173.15)
    currents = (-20.0, -10.0, 0.0, 10.0, 20.0, 40.0)
    forward_values = tuple(
        (0.0 if t > 1000 else resistance(t) * i) for t in temperatures for i in currents
    )
    forward = Curve(
        id="syn:voltage_drop:fwd",
        name="voltage_drop",
        unit="V",
        axes=(
            Axis(name="junction_temperature", unit="K", values=temperatures),
            Axis(name="current", unit="A", values=currents),
        ),
        values=forward_values,
        provenance=PROVENANCE,
        condition=OperatingCondition(gate_state="on"),
    )
    reverse_currents = (-20.0, -10.0, -1.0, 0.0)
    reverse = Curve(
        id="syn:voltage_drop:rev",
        name="voltage_drop",
        unit="V",
        axes=(
            Axis(name="junction_temperature", unit="K", values=temperatures),
            Axis(name="current", unit="A", values=reverse_currents),
        ),
        values=tuple(
            (0.0 if t > 1000 or i == 0 else -3.0 - 0.05 * abs(i))
            for t in temperatures
            for i in reverse_currents
        ),
        provenance=PROVENANCE,
        condition=OperatingCondition(gate_state="off"),
    )
    energy_axes = (
        Axis(name="junction_temperature", unit="K", values=(298.15, 398.15, 1173.15)),
        Axis(name="dc_bus_voltage", unit="V", values=(0.0, 400.0, 800.0)),
        Axis(name="current", unit="A", values=(0.0, 10.0, 20.0, 40.0)),
    )
    energies = tuple(
        (0.0 if t > 1000 else K_EOFF * v * i)
        for t in (298.15, 398.15, 1173.15)
        for v in (0.0, 400.0, 800.0)
        for i in (0.0, 10.0, 20.0, 40.0)
    )
    eoff = Curve(
        id="syn:Eoff",
        name="Eoff",
        unit="J",
        axes=energy_axes,
        values=energies,
        provenance=PROVENANCE,
    )
    eon = Curve(
        id="syn:Eon",
        name="Eon",
        unit="J",
        axes=energy_axes,
        values=tuple(2 * e for e in energies),
        provenance=PROVENANCE,
    )
    model = ModelReference(
        id="syn:plecs",
        format="plecs",
        provenance=PROVENANCE,
        adapter_metadata={
            "variables": [
                {"Name": "Rgoff", "MinValue": "0", "MaxValue": "10", "DefaultValue": "0"},
            ],
            "bindings": [
                {"curve_id": "syn:Eoff", "formula": FORMULA if with_formula else None},
            ],
        },
    )
    return PowerSemiconductorDevice(
        device_id="synthetic_dab",
        identity=DeviceIdentity(manufacturer="Synthetic", part_number="DAB-1"),
        provenance=(SOURCE,),
        conduction=CharacteristicData(availability="available", curves=(forward,)),
        reverse_conduction=CharacteristicData(availability="available", curves=(reverse,))
        if with_reverse
        else CharacteristicData(),
        switching=CharacteristicData(availability="available", curves=(eon, eoff)),
        thermal=(
            ThermalNetwork(
                id="syn:thermal",
                topology="Cauer",
                provenance=PROVENANCE,
                elements=(
                    ThermalElement(
                        resistance={"value": 0.5, "unit": "K/W"},
                        capacitance={"value": 0.01, "unit": "J/K"},
                    ),
                ),
            ),
        ),
        models=(model,),
    )


def metrics_stress(**overrides):
    values = dict(
        switch_id="S1",
        bridge="primary",
        source="summary_metrics",
        periods=1.0,
        switching_frequency=100e3,
        current_rms=10.0,
        current_avg=4.0,
        current_peak_forward=14.0,
        current_peak_reverse=-5.0,
        conduction_fraction=0.5,
        turn_off_currents=(14.0,),
        turn_on_currents=(-14.0,),
        zvs_turn_on=(True,),
        blocking_voltages=(800.0,),
        v_ds_max=800.0,
    )
    values.update(overrides)
    return SwitchStress(**values)


def test_protocol_and_metrics_path_numbers():
    device = synthetic_device()
    assert validate_device(device).valid
    evaluator = DABLossEvaluator(metrics_stress())
    assert isinstance(evaluator, LossEvaluator)
    op = operating_point(
        junction_temperature=398.15,
        dc_bus_voltage=800,
        switching_frequency=100e3,
        gate_resistance_on=2,
        gate_resistance_off=2,
        gate_voltage_on=15,
        gate_voltage_off=-4,
    )
    result = evaluator.evaluate_detailed(device=device, operating_point=op)
    breakdown = result.breakdown()
    assert breakdown["conduction_loss"] == pytest.approx(resistance(398.15) * 100.0)
    assert breakdown["turn_off_loss"] == pytest.approx(100e3 * K_EOFF * 800 * 14 * 1.2)
    assert breakdown["turn_on_loss"] == 0.0
    assert result.total_loss == pytest.approx(
        breakdown["conduction_loss"] + breakdown["turn_off_loss"]
    )
    records = evaluator.evaluate(device=device, operating_point=op)
    by_name = {r.name: r for r in records}
    assert by_name["total_loss"].quantity.unit == "W"
    assert by_name["turn_off_energy_per_period"].quantity.value == pytest.approx(
        K_EOFF * 800 * 14 * 1.2
    )
    provenance = by_name["total_loss"].provenance
    assert provenance.origin == "physics_derived"
    assert provenance.lifecycle == "derived"
    assert {d.id for d in provenance.dependencies} >= {
        "syn:voltage_drop:fwd",
        "syn:Eoff",
        "dab-switch-loss",
    }
    assert "syn:Eon" not in {d.id for d in provenance.dependencies}  # ZVS: Eon unused
    quantities = {n.quantity: n.status for n in result.coverage}
    assert quantities["coss"] == "unavailable"
    assert quantities["vds_max"] == "unavailable"
    assert quantities["rds_on_vs_tj"] == "approximated"
    assert quantities["rg_dependence_Eoff"] == "approximated"
    assert quantities["gate_voltage_dependence"] == "unavailable"
    assert quantities["turn_on_loss_under_zvs"] == "approximated"
    assert quantities["conduction_waveform_integral"] == "approximated"
    assert result.evidence_origins["syn:Eoff"] == "manufacturer_model"


def test_hard_turn_on_uses_eon_and_zvs_flag_sources():
    device = synthetic_device()
    op = operating_point(junction_temperature=398.15, dc_bus_voltage=800, switching_frequency=100e3)
    hard = DABLossEvaluator(metrics_stress(turn_on_currents=(10.0,), zvs_turn_on=(False,)))
    result = hard.evaluate_detailed(device=device, operating_point=op)
    assert result.breakdown()["turn_on_loss"] == pytest.approx(100e3 * 2 * K_EOFF * 800 * 10)
    assert "syn:Eon" in result.evidence_origins
    # Operating-point extension carries the ZVS statement when the stress has no flags.
    op_zvs = op.model_copy(
        update={
            "extensions": (
                ConditionParameter(name="zvs_turn_on", quantity=Quantity(value=1, unit="1")),
            )
        }
    )
    stated = DABLossEvaluator(metrics_stress(turn_on_currents=(10.0,), zvs_turn_on=()))
    assert (
        stated.evaluate_detailed(device=device, operating_point=op_zvs).breakdown()["turn_on_loss"]
        == 0.0
    )
    override = DABLossEvaluator(
        metrics_stress(turn_on_currents=(10.0,), zvs_turn_on=(False,)), zvs_turn_on=True
    )
    assert (
        override.evaluate_detailed(device=device, operating_point=op).breakdown()["turn_on_loss"]
        == 0.0
    )


def test_gate_resistance_policy_and_formula_fallbacks():
    device = synthetic_device()
    stress = metrics_stress()
    outside = operating_point(
        junction_temperature=398.15,
        dc_bus_voltage=800,
        switching_frequency=100e3,
        gate_resistance_off=12,
    )
    with pytest.raises(ValueError, match="PLECS model range"):
        DABLossEvaluator(stress).evaluate_detailed(device=device, operating_point=outside)
    allowed = DABLossEvaluator(stress, policy=EnvelopePolicy(allow_extrapolation=True))
    result = allowed.evaluate_detailed(device=device, operating_point=outside)
    component = next(c for c in result.components if c.name == "turn_off_loss")
    assert "extrapolated:gate_resistance_off" in component.flags
    assert component.value == pytest.approx(100e3 * K_EOFF * 800 * 14 * 2.2)
    no_rg = operating_point(
        junction_temperature=398.15, dc_bus_voltage=800, switching_frequency=100e3
    )
    result = DABLossEvaluator(stress).evaluate_detailed(device=device, operating_point=no_rg)
    assert {n.status for n in result.coverage if n.quantity == "rg_dependence_Eoff"} == {
        "not_evaluated"
    }
    without_formula = synthetic_device(with_formula=False)
    result = DABLossEvaluator(stress).evaluate_detailed(
        device=without_formula,
        operating_point=operating_point(
            junction_temperature=398.15,
            dc_bus_voltage=800,
            switching_frequency=100e3,
            gate_resistance_off=2,
        ),
    )
    assert {n.status for n in result.coverage if n.quantity == "rg_dependence_Eoff"} == {
        "unavailable"
    }
    assert result.breakdown()["turn_off_loss"] == pytest.approx(100e3 * K_EOFF * 800 * 14)


def test_envelope_violations_and_missing_operating_point_are_errors():
    device = synthetic_device()
    with pytest.raises(ValueError, match="requires switching_frequency"):
        DABLossEvaluator(metrics_stress()).evaluate_detailed(
            device=device,
            operating_point=OperatingCondition(
                junction_temperature=Quantity(value=398.15, unit="K"),
                dc_bus_voltage=Quantity(value=800, unit="V"),
            ),
        )
    with pytest.raises(ValueError, match="outside the source envelope"):
        DABLossEvaluator(metrics_stress()).evaluate_detailed(
            device=device,
            operating_point=operating_point(
                junction_temperature=398.15, dc_bus_voltage=1000, switching_frequency=100e3
            ),
        )


def square_waveform(samples=4000, period=1e-5):
    time = tuple(k * period / samples for k in range(samples + 1))
    current = []
    gate = []
    for t in time:
        phase = (t / period) % 1.0
        on = 0.1 <= phase < 0.6
        gate.append(15.0 if on else 0.0)
        if 0.1 <= phase < 0.2:
            current.append(-5.0)
        elif 0.2 <= phase < 0.6:
            current.append(10.0)
        else:
            current.append(0.0)
    v_ds = tuple(0.0 if g else 800.0 for g in gate)
    return SwitchWaveform(
        time=time, current=tuple(current), gate=tuple(gate), drain_source_voltage=v_ds
    )


def test_waveform_path_integrates_forward_and_reverse_conduction():
    device = synthetic_device()
    stress = stress_from_waveform(square_waveform(), switch_id="S1", switching_frequency=100e3)
    assert stress.periods == 1.0
    assert stress.turn_off_currents == (10.0,)
    assert stress.turn_on_currents == (-5.0,)
    assert stress.zvs_turn_on == (True,)
    assert stress.blocking_voltages == (800.0,)
    assert stress.current_rms == pytest.approx((0.1 * 25 + 0.4 * 100) ** 0.5, rel=1e-3)
    assert stress.reverse_charge_fraction == pytest.approx(0.5 / 4.5, rel=1e-2)
    op = operating_point(
        junction_temperature=398.15,
        dc_bus_voltage=800,
        switching_frequency=100e3,
        gate_resistance_off=2,
    )
    r = resistance(398.15)
    channel = DABLossEvaluator(stress).evaluate_detailed(device=device, operating_point=op)
    b = channel.breakdown()
    assert b["conduction_loss_forward"] == pytest.approx(0.4 * r * 100, rel=2e-3)
    assert b["conduction_loss_reverse"] == pytest.approx(0.1 * r * 25, rel=2e-3)
    assert b["turn_off_loss"] == pytest.approx(100e3 * K_EOFF * 800 * 10 * 1.2)
    assert b["turn_on_loss"] == 0.0
    body = DABLossEvaluator(stress, reverse_conduction="body_diode").evaluate_detailed(
        device=device, operating_point=op
    )
    assert body.breakdown()["conduction_loss_reverse"] == pytest.approx(0.1 * 3.25 * 5, rel=2e-3)
    assert body.breakdown()["conduction_loss_forward"] == pytest.approx(
        b["conduction_loss_forward"]
    )
    assert any(f == "method:waveform_integral" for c in channel.components for f in c.flags)
    with pytest.raises(ValueError, match="sampled waveform"):
        DABLossEvaluator(metrics_stress(), reverse_conduction="body_diode").evaluate_detailed(
            device=device, operating_point=op
        )


def test_waveform_without_gate_infers_events_and_notes_dead_time_gap():
    waveform = square_waveform()
    bare = waveform.model_copy(update={"gate": None, "drain_source_voltage": None})
    stress = stress_from_waveform(bare, switch_id="S1", switching_frequency=100e3)
    assert stress.turn_off_currents == (10.0,)
    assert stress.turn_on_currents == (-5.0,)
    assert any("inferred from current steps" in note for note in stress.notes)
    result = DABLossEvaluator(stress).evaluate_detailed(
        device=synthetic_device(),
        operating_point=operating_point(
            junction_temperature=398.15, dc_bus_voltage=800, switching_frequency=100e3
        ),
    )
    assert {
        n.status for n in result.coverage if n.quantity == "dead_time_body_diode_conduction"
    } == {"not_evaluated"}
    with pytest.raises(ValueError, match="integer number"):
        stress_from_waveform(bare, switch_id="S1", switching_frequency=133e3)


def test_summary_reader_rejects_invalid_runs_and_reads_real_metrics():
    summary = json.loads((ROOT / "tests/fixtures/dab-l1-nominal-ic.summary.json").read_text())
    stress = stress_from_summary(summary, "S1")
    assert stress.periods == 4.0
    assert stress.switching_frequency == pytest.approx(100e3)
    assert stress.current_rms == pytest.approx(9.669, abs=1e-3)
    assert len(stress.turn_off_currents) == 4 and stress.zvs_turn_on == (True,) * 4
    assert stress.dataset_sha256 == summary["dataset_sha256"]
    assert stress.reverse_charge_fraction == pytest.approx(0.0333, abs=2e-3)
    with pytest.raises(ValueError, match="not in the summary"):
        stress_from_summary(summary, "S9")
    invalid = dict(summary, valid=False)
    with pytest.raises(ValueError, match="invalid"):
        stress_from_summary(invalid, "S1")


def test_real_c3m0075120k_losses_from_actual_run():
    from aipe_devices.repository.json_repository import JsonDeviceRepository

    summary = json.loads((ROOT / "tests/fixtures/dab-l1-nominal-ic.summary.json").read_text())
    device = JsonDeviceRepository(ROOT / "data/canonical").get("wolfspeed_c3m0075120k")
    op = operating_point(
        junction_temperature=398.15,
        dc_bus_voltage=800,
        switching_frequency=100e3,
        gate_resistance_on=2,
        gate_resistance_off=2,
        gate_voltage_on=15,
        gate_voltage_off=-4,
    )
    result = DABLossEvaluator(stress_from_summary(summary, "S1")).evaluate_detailed(
        device=device, operating_point=op
    )
    b = result.breakdown()
    assert b["conduction_loss"] == pytest.approx(10.40, abs=0.05)
    assert b["turn_off_loss"] == pytest.approx(5.95, abs=0.05)
    assert b["turn_on_loss"] == 0.0
    assert result.complete and result.total_loss == pytest.approx(16.35, abs=0.1)
    turn_off = next(c for c in result.components if c.name == "turn_off_loss")
    assert "rg_scaling:plecs_formula" in turn_off.flags
    assert result.records[0].provenance.dependencies[-1].checksum == summary["dataset_sha256"]


def test_formula_evaluator_is_restricted():
    assert (
        evaluate_formula("E/(0.2707)*(90e-6*(Rgon^2)+0.0126*Rgon+0.2707)", {"E": 1, "Rgon": 0}) == 1
    )
    assert formula_variables("E/(-8e-8*2.5^2+0.0238e-3*2.5)*(-8e-8*Rgoff^2)") == {"E", "Rgoff"}
    assert gate_resistance_factor(FORMULA, "Rgoff", 2.0) == pytest.approx(1.2)
    for bad in ("lookup('Eon',i,v,T,Rgon)*1e-3", "__import__('os')", "E+Rgoff", "E*", ""):
        with pytest.raises(FormulaError):
            gate_resistance_factor(bad, "Rgoff", 2.0)
