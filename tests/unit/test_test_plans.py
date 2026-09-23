import json

import pytest
from conftest import ROOT
from pydantic import ValidationError

from aipe_devices.domain.conditions import OperatingCondition
from aipe_devices.domain.measurement import MeasurementProtocol
from aipe_devices.domain.measurement import TestRun as Run
from aipe_devices.measurement.plans import SweepAxis, SweepRange
from aipe_devices.measurement.plans import TestPlanItem as Item
from aipe_devices.measurement.request_generator import MeasurementRequest
from aipe_devices.measurement.submission_validator import MeasurementPackage, validate_submission


def protocol(category="dpt"):
    return MeasurementProtocol(id=category, version="1.0", category=category)


def test_compact_sweep_and_no_eager_expansion():
    axis = SweepAxis(
        parameter="drain_current", unit="A", range=SweepRange(start=0, stop=1_000_000, step=1)
    )
    item = Item(id="many", protocol=protocol(), sweep_axes=(axis,))
    assert item.point_count == 1_000_001
    assert len(item.model_dump_json()) < 1000
    assert item.match(protocol(), OperatingCondition(drain_current={"value": 10, "unit": "A"})) == (
        10,
    )
    assert (
        item.match(protocol(), OperatingCondition(drain_current={"value": 0.5, "unit": "A"}))
        is None
    )


@pytest.mark.parametrize(
    "axis",
    [
        {"parameter": "junction_temperature", "unit": "C", "values": [25]},
        {"parameter": "drain_current", "unit": "A", "values": []},
        {"parameter": "drain_current", "unit": "A", "values": [1, 1]},
        {"parameter": "junction_temperature", "unit": "K", "values": [-1]},
        {"parameter": "drain_current", "unit": "A", "range": {"start": 0, "stop": 1, "step": 0.3}},
    ],
)
def test_invalid_sweeps(axis):
    with pytest.raises(ValidationError):
        SweepAxis.model_validate(axis)


def test_no_cross_product_between_protocols():
    package = MeasurementPackage.model_validate_json(
        (ROOT / "examples/measurement_package/manifest.json").read_bytes()
    )
    dpt = package.runs[0]
    cap_condition = OperatingCondition(dc_bus_voltage={"value": 400, "unit": "V"})
    cap = Run(
        id="cap",
        device_id=package.device_id,
        protocol=protocol("capacitance"),
        condition=cap_condition,
    )
    request = MeasurementRequest(
        id=package.request_id,
        device_id=package.device_id,
        test_plan_items=(
            Item(
                id="dpt",
                protocol=dpt.protocol,
                fixed_conditions=dpt.condition,
                requested_metrics=("Eon",),
            ),
            Item(id="cap", protocol=cap.protocol, fixed_conditions=cap_condition),
        ),
    )
    updated = package.model_copy(update={"runs": (*package.runs, cap)})
    assert validate_submission(updated, request=request).valid
    wrong = cap.model_copy(update={"condition": dpt.condition})
    report = validate_submission(updated.model_copy(update={"runs": (dpt, wrong)}), request=request)
    assert {"request_mismatch", "request_coverage"} <= {i.code for i in report.issues}


def test_legacy_migration_serializes_only_items():
    request = MeasurementRequest.model_validate(
        {
            "id": "legacy",
            "device_id": "x",
            "protocols": [protocol().model_dump()],
            "conditions": [{}],
            "repetitions": 3,
        }
    )
    assert request.test_plan_items[0].repetitions == 3
    assert "protocols" not in json.loads(request.model_dump_json())


def test_overlap_and_per_coordinate_repetitions():
    package = MeasurementPackage.model_validate_json(
        (ROOT / "examples/measurement_package/manifest.json").read_bytes()
    )
    run = package.runs[0]
    items = tuple(Item(id=n, protocol=run.protocol) for n in ("a", "b"))
    request = MeasurementRequest(
        id=package.request_id, device_id=package.device_id, test_plan_items=items
    )
    assert "request_ambiguous" in {
        i.code for i in validate_submission(package, request=request).issues
    }
    item = Item(
        id="sweep",
        protocol=run.protocol,
        sweep_axes=(SweepAxis(parameter="dc_bus_voltage", unit="V", values=(800, 600)),),
    )
    request = request.model_copy(update={"test_plan_items": (item,)})
    assert "request_coverage" in {
        i.code for i in validate_submission(package, request=request).issues
    }
