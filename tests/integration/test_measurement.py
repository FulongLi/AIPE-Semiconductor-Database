import pytest
from conftest import ROOT
from pydantic import ValidationError

from aipe_devices.domain.measurement import InstrumentSetup
from aipe_devices.measurement.request_generator import MeasurementRequest
from aipe_devices.measurement.submission_validator import (
    MeasurementPackage,
    validate_package_file,
    validate_submission,
)

FOLDER = ROOT / "examples/measurement_package"


def test_example_package_and_request():
    request = MeasurementRequest.model_validate_json(
        (ROOT / "examples/measurement_request.json").read_bytes()
    )
    assert validate_package_file(FOLDER / "manifest.json", request=request).valid


@pytest.mark.parametrize(
    "change,expected",
    [
        ("device", "device_reference"),
        ("waveform", "artifact_reference"),
        ("recipe", "recipe_reference"),
        ("checksum", "artifact_integrity"),
        ("traversal", "artifact_path"),
        ("metric_source", "source_reference"),
    ],
)
def test_invalid_submission_references(change, expected):
    package = MeasurementPackage.model_validate_json((FOLDER / "manifest.json").read_bytes())
    data = package.model_dump()
    if change == "device":
        data["runs"][0]["device_id"] = "wrong"
    elif change == "waveform":
        data["runs"][0]["waveform_refs"][0]["artifact"]["id"] = "absent"
    elif change == "recipe":
        data["runs"][0]["processing_recipes"] = []
    elif change == "checksum":
        data["artifacts"][0]["checksum"] = "0" * 64
    elif change == "traversal":
        data["artifacts"][0]["uri"] = "../outside.csv"
    else:
        data["runs"][0]["derived_metrics"][0]["metrics"][0]["provenance"]["source_ids"] = ["absent"]
    report = validate_submission(MeasurementPackage.model_validate(data), root=FOLDER)
    assert not report.valid
    assert expected in {i.code for i in report.issues}


def test_no_giant_waveform_payload_field():
    data = MeasurementPackage.model_validate_json(
        (FOLDER / "manifest.json").read_bytes()
    ).model_dump()
    data["runs"][0]["waveform_refs"][0]["samples"] = [0, 1, 2]
    with pytest.raises(ValidationError):
        MeasurementPackage.model_validate(data)
    with pytest.raises(ValidationError):
        InstrumentSetup(sampling_rate={"value": 1, "unit": "V"})


def test_request_repetition_coverage():
    package = MeasurementPackage.model_validate_json((FOLDER / "manifest.json").read_bytes())
    request = MeasurementRequest.model_validate_json(
        (ROOT / "examples/measurement_request.json").read_bytes()
    )
    request = request.model_copy(update={"repetitions": 2})
    assert not validate_submission(package, request=request).valid


def test_stale_input_version_and_checksum_rejected():
    package = MeasurementPackage.model_validate_json((FOLDER / "manifest.json").read_bytes())
    for field, value, code in [
        ("version", "wrong", "dependency_reference"),
        ("checksum", "0" * 64, "dependency_checksum"),
    ]:
        data = package.model_dump()
        data["runs"][0]["derived_metrics"][0]["metrics"][0]["provenance"]["dependencies"][0][
            field
        ] = value
        report = validate_submission(MeasurementPackage.model_validate(data))
        assert code in {i.code for i in report.issues}
