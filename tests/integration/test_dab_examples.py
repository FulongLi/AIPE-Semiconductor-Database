import json

import pytest
from conftest import ROOT

from aipe_devices.measurement.request_generator import MeasurementRequest
from aipe_devices.services.loss.dab import DABLossResult
from aipe_devices.services.measurement_requests import PrioritisedMeasurementRequest
from aipe_devices.services.selection import ScreeningReport
from aipe_devices.services.thermal import FixedPointResult

EXAMPLES = ROOT / "examples/dab"


@pytest.mark.parametrize("part, switch", [("C3M0075120K", "S1"), ("C3M0030090K", "S5")])
def test_generated_loss_examples_validate_and_match_the_fixture_run(part, switch):
    data = json.loads((EXAMPLES / f"dab_losses_{part}_{switch}.json").read_text(encoding="utf-8"))
    assert data["schema"] == "aipe-dab-loss-evaluation/0.1"
    result = DABLossResult.model_validate(data["result"])
    assert result.switch_id == switch and result.complete
    fixture = json.loads(
        (ROOT / "tests/fixtures/dab-l1-nominal-ic.summary.json").read_text(encoding="utf-8")
    )
    assert result.stress.dataset_sha256 == fixture["dataset_sha256"]
    fixed = FixedPointResult.model_validate(data["thermal"]["electro_thermal_fixed_point"])
    assert (
        fixed.converged
        and fixed.junction_temperature < result.operating_point.junction_temperature.value
    )
    request = PrioritisedMeasurementRequest.model_validate_json(
        (EXAMPLES / f"measurement_request_{part}_{switch}.json").read_text(encoding="utf-8")
    )
    assert isinstance(request.request, MeasurementRequest)
    assert request.request.device_id == result.device_id


def test_generated_screening_example_validates():
    report = ScreeningReport.model_validate_json(
        (EXAMPLES / "dab_screening.json").read_text(encoding="utf-8")
    )
    assert [b.bridge for b in report.bridges] == ["primary", "secondary"]
    for bridge in report.bridges:
        tiers = [a.confidence.tier for a in bridge.ranked]
        assert tiers == sorted(tiers) and bridge.ranked
