"""Rebuild synthetic partner examples, golden schema fixtures, and JSON Schemas."""

import hashlib
import json
from pathlib import Path

from aipe_devices.domain.conditions import OperatingCondition
from aipe_devices.domain.curves import ScalarRecord
from aipe_devices.domain.device import PowerSemiconductorDevice
from aipe_devices.domain.identity import Classification, DeviceIdentity
from aipe_devices.domain.measurement import (
    DynamicMetrics,
    DynamicWaveformRef,
    MeasurementProtocol,
    ProcessingRecipe,
    TestCampaign,
    TestRun,
    WaveformChannel,
    WaveformEvent,
)
from aipe_devices.domain.module import DevicePackage, ModuleComponent
from aipe_devices.domain.provenance import (
    AccessMetadata,
    ArtifactRef,
    Dependency,
    Provenance,
    Source,
)
from aipe_devices.measurement.plans import TestPlanItem
from aipe_devices.measurement.request_generator import MeasurementRequest
from aipe_devices.measurement.submission_validator import MeasurementPackage

ROOT = Path(__file__).resolve().parents[1]


def write(path, model):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(model.model_dump_json(indent=2) + "\n")


def main():
    for technology, integration in [
        ("IGBT", "discrete"),
        ("Si_MOSFET", "module"),
        ("GaN", "discrete"),
    ]:
        components = (
            ()
            if integration == "discrete"
            else (
                ModuleComponent(id="high", role="switch", die_count=2),
                ModuleComponent(id="low", role="switch", die_count=2),
            )
        )
        source = Source(
            id="synthetic-fixture", kind="AIPE", name="Synthetic schema example; no measured claims"
        )
        device = PowerSemiconductorDevice(
            device_id=f"synthetic_{technology.lower()}",
            identity=DeviceIdentity(manufacturer="Example only", part_number=technology),
            classification=Classification(technology=technology, integration=integration),
            package=DevicePackage(components=components),
            provenance=(source,),
        )
        write(ROOT / f"tests/golden/fixtures/{technology.lower()}.json", device)

    folder = ROOT / "examples/measurement_package"
    folder.mkdir(parents=True, exist_ok=True)
    waveform = b"time_s,vds_V,id_A\n0,800,0\n1e-8,400,5\n2e-8,10,10\n3e-8,1,10\n"
    (folder / "waveforms").mkdir(exist_ok=True)
    (folder / "waveforms/synthetic.csv").write_bytes(waveform)
    digest = hashlib.sha256(waveform).hexdigest()
    artifact = ArtifactRef(
        id="artifact:synthetic",
        uri="waveforms/synthetic.csv",
        checksum=digest,
        size=len(waveform),
        format="text/csv",
    )
    source = Source(
        id="source:example",
        kind="AIPE",
        name="Synthetic demonstration; not Wolfspeed measurements",
        access=AccessMetadata(owner="AIPE example", category="aipe", visibility="public"),
    )
    condition = OperatingCondition(
        junction_temperature={"value": 298.15, "unit": "K"},
        dc_bus_voltage={"value": 800, "unit": "V"},
    )
    protocol = MeasurementProtocol(id="AIPE-DPT", version="1.0", category="dpt")
    recipe = ProcessingRecipe(
        id="illustrative-integration",
        version="1.0",
        algorithm="Synthetic demonstration only; metric is not a validated DPT result",
        integration_start_rule="first sample",
        integration_end_rule="last sample",
    )
    recipe_ref = Dependency(id=recipe.id, version=recipe.version)
    waveform_ref = DynamicWaveformRef(
        id="waveform:synthetic",
        test_run_id="run:example",
        artifact=artifact,
        stage="raw",
        channels=(
            WaveformChannel(name="time_s", unit="s", role="time"),
            WaveformChannel(name="vds_V", unit="V", role="voltage"),
            WaveformChannel(name="id_A", unit="A", role="current"),
        ),
        provenance=Provenance(
            origin="synthetic",
            source_ids=(source.id,),
            lifecycle="derived",
            dependencies=(Dependency(id="example-generator", version="1.0"),),
        ),
        events=(
            WaveformEvent(id="event:turn-on", kind="turn_on", start_seconds=0, end_seconds=3e-8),
        ),
    )
    metric_provenance = Provenance(
        origin="synthetic",
        source_ids=(source.id,),
        lifecycle="derived",
        dependencies=(Dependency(id=waveform_ref.id, version="1", checksum=digest), recipe_ref),
        recipe_id=recipe.id,
        recipe_version=recipe.version,
    )
    metrics = DynamicMetrics(
        id="metrics:example",
        test_run_id="run:example",
        waveform_ids=(waveform_ref.id,),
        recipe=recipe_ref,
        metrics=(
            ScalarRecord(
                id="metric:eon",
                name="Eon",
                quantity={"value": 0.00002105, "unit": "J"},
                provenance=metric_provenance,
                condition=condition,
            ),
        ),
    )
    request = MeasurementRequest(
        id="request:example",
        device_id="synthetic_dpt_device",
        physical_sample_id="synthetic_sample_1",
        test_plan_items=(
            TestPlanItem(
                id="dpt-example",
                protocol=protocol,
                fixed_conditions=condition,
                requested_metrics=("Eon",),
            ),
        ),
    )
    run = TestRun(
        id="run:example",
        device_id=request.device_id,
        physical_sample_id=request.physical_sample_id,
        condition=condition,
        protocol=protocol,
        waveform_refs=(waveform_ref,),
        processing_recipes=(recipe,),
        derived_metrics=(metrics,),
    )
    package = MeasurementPackage(
        id="package:example",
        request_id=request.id,
        device_id=request.device_id,
        sources=(source,),
        campaigns=(
            TestCampaign(
                id="campaign:example",
                name="Synthetic DPT example",
                source=source,
                test_run_ids=(run.id,),
            ),
        ),
        runs=(run,),
        artifacts=(artifact,),
        external_dependencies=(Dependency(id="example-generator", version="1.0"),),
    )
    write(ROOT / "examples/measurement_request.json", request)
    write(folder / "manifest.json", package)
    for name, model in [
        ("device", PowerSemiconductorDevice),
        ("measurement-request", MeasurementRequest),
        ("measurement-package", MeasurementPackage),
    ]:
        path = ROOT / f"docs/schemas/{name}.schema.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        schema = model.model_json_schema()
        schema["$schema"] = "https://json-schema.org/draft/2020-12/schema"
        path.write_text(json.dumps(schema, indent=2) + "\n")


if __name__ == "__main__":
    main()
