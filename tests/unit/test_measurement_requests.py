import json

import pytest
from conftest import ROOT

from aipe_devices.measurement.request_generator import MeasurementRequest
from aipe_devices.repository.json_repository import JsonDeviceRepository
from aipe_devices.services.loss.dab import DABLossEvaluator, operating_point
from aipe_devices.services.loss.stress import stress_from_summary
from aipe_devices.services.measurement_requests import (
    PrioritisedMeasurementRequest,
    generate_dab_measurement_requests,
)

SUMMARY = json.loads((ROOT / "tests/fixtures/dab-l1-nominal-ic.summary.json").read_text())


@pytest.fixture(scope="module")
def generated():
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
    result = DABLossEvaluator(stress_from_summary(SUMMARY, "S1")).evaluate_detailed(
        device=device, operating_point=op
    )
    return device, result, generate_dab_measurement_requests(device, result, thermal_headroom=58.0)


def test_request_follows_partner_shape_and_is_draft(generated):
    _, _, prioritised = generated
    data = json.loads(prioritised.model_dump_json(by_alias=True))
    assert data["schema"] == "aipe-prioritised-measurement-request/0.1"
    request = MeasurementRequest.model_validate(data["request"])
    assert request.device_id == "wolfspeed_c3m0075120k"
    ids = [i.id for i in request.test_plan_items]
    assert len(ids) == len(set(ids)) == 8
    assert all(i.draft and i.requirements for i in request.test_plan_items)
    categories = {i.protocol.category for i in request.test_plan_items}
    assert categories == {
        "static_conduction",
        "dpt",
        "reverse_conduction",
        "capacitance",
        "thermal",
    }
    example = json.loads((ROOT / "examples/measurement_request.json").read_text())
    assert set(data["request"]) == set(example)
    assert set(data["request"]["test_plan_items"][0]) == set(example["test_plan_items"][0])
    assert (
        PrioritisedMeasurementRequest.model_validate_json(
            prioritised.model_dump_json(by_alias=True)
        )
        == prioritised
    )


def test_sweeps_follow_the_actual_operating_point(generated):
    _, result, prioritised = generated
    items = {i.id: i for i in prioritised.request.test_plan_items}
    dpt = items["dpt-eoff-eon"]
    axes = {a.parameter: a for a in dpt.sweep_axes}
    assert 800.0 in axes["dc_bus_voltage"].values and 880.0 in axes["dc_bus_voltage"].values
    assert 14.0 in axes["drain_current"].values  # turn-off current 14.26 A rounded to the grid
    assert 2.0 in axes["gate_resistance_off"].values and 2.0 in axes["gate_resistance_on"].values
    assert 398.15 in axes["junction_temperature"].values
    assert {"Eon", "Eoff", "dv_dt", "di_dt", "Vds_peak"} <= set(dpt.requested_metrics)
    assert dpt.repetitions == 5 and dpt.fixed_conditions.gate_voltage_on.value == 15.0
    reverse = items["reverse-conduction-body-diode"]
    assert all(v < 0 for v in reverse.sweep_axes[0].values)
    assert reverse.fixed_conditions.gate_state == "off"
    assert items["reverse-conduction-synchronous"].fixed_conditions.gate_state == "on"
    rds = items["rds-on-vs-tj"]
    assert rds.fixed_conditions.drain_current.value == pytest.approx(10.0)
    assert rds.requested_metrics == ("rds_on",)
    zth = items["zth-junction-case"]
    assert zth.sweep_axes[0].parameter == "pulse_width" and zth.point_count == 11
    cap = items["coss-eoss"]
    assert cap.sweep_axes[0].parameter == "drain_source_voltage"
    assert max(cap.sweep_axes[0].values) == pytest.approx(880.0)


def test_priorities_are_benefit_times_uncertainty_and_sorted(generated):
    _, result, prioritised = generated
    scores = [p.score for p in prioritised.priorities]
    assert scores == sorted(scores, reverse=True)
    assert [p.rank for p in prioritised.priorities] == list(range(1, len(scores) + 1))
    for p in prioritised.priorities:
        assert p.score == pytest.approx(p.expected_design_benefit * p.current_uncertainty, abs=1e-4)
        assert p.engineering_question.endswith("?")
        assert "%" in p.uncertainty_target
    by_id = {p.item_id: p for p in prioritised.priorities}
    # Coss is absent (uncertainty 1.0); the channel I-V is backed by a model tensor (0.45).
    assert by_id["coss-eoss"].current_uncertainty == 1.0
    assert by_id["static-iv-channel"].current_uncertainty < by_id["coss-eoss"].current_uncertainty
    conduction_share = result.breakdown()["conduction_loss"] / result.total_loss
    assert by_id["static-iv-channel"].expected_design_benefit == pytest.approx(
        conduction_share, abs=1e-3
    )
    assert prioritised.context["loss_breakdown_W"]["turn_off_loss"] == pytest.approx(5.95, abs=0.05)
    assert (
        prioritised.safety and "No measurement is executed automatically" in prioritised.safety[0]
    )
