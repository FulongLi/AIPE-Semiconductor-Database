import hashlib
import json
import xml.etree.ElementTree as ET

import pytest
from conftest import RAW, ROOT

from aipe_devices.domain.device import PowerSemiconductorDevice
from aipe_devices.exporters.json import JsonExporter
from aipe_devices.exporters.plecs import PlecsExporter
from aipe_devices.importers.plecs import PlecsImporter
from aipe_devices.services.thermal import ThermalEvaluator
from aipe_devices.services.validation import validate_device

FILES = sorted(RAW.rglob("*.xml"))


@pytest.mark.parametrize("path", FILES, ids=lambda p: p.stem)
def test_all_source_points_and_export_roundtrip(path):
    device = PlecsImporter().load(path)
    assert validate_device(device).valid
    xml = ET.parse(path).getroot()
    for n in xml.iter():
        n.tag = n.tag.split("}")[-1]
    # Independently check source tensor point counts, scale and axis order.
    for tag, group, name in [
        ("TurnOnLoss", "switching", "Eon"),
        ("TurnOffLoss", "switching", "Eoff"),
    ]:
        section = xml.find(f".//{tag}")
        curve = next(c for c in getattr(device, group).curves if c.name == name)
        raw = tuple(
            float(v)
            for row in section.findall("Energy/Temperature/Voltage")
            for v in row.text.split()
        )
        assert curve.values == tuple(v * float(section.find("Energy").get("scale")) for v in raw)
        assert curve.axes[0].values == tuple(
            float(v) + 273.15 for v in section.findtext("TemperatureAxis").split()
        )
    for tag in xml.findall(".//ConductionLoss"):
        group = device.reverse_conduction if tag.get("gate") == "off" else device.conduction
        raw = tuple(
            float(v) for row in tag.findall("VoltageDrop/Temperature") for v in row.text.split()
        )
        assert group.curves[0].values == tuple(
            v * float(tag.find("VoltageDrop").get("scale")) for v in raw
        )
    for table in xml.findall(".//CustomTables/Table"):
        curve = next(
            c
            for c in device.switching.curves
            if c.id.endswith(f"{table.findtext('Name')}:gate_resistance")
        )
        raw = tuple(
            float(v)
            for leaf in table.find("FunctionValues").iter()
            if len(leaf) == 0
            for v in leaf.text.split()
        )
        assert curve.values == tuple(
            v * float(table.find("FunctionValues").get("scale")) * 1e-3 for v in raw
        )
    exported = PlecsExporter().export(device)
    restored = PlecsImporter().loads(exported.encode())
    for group in ["switching", "conduction", "reverse_conduction"]:
        assert len(getattr(restored, group).curves) == len(getattr(device, group).curves)
        for before, after in zip(getattr(device, group).curves, getattr(restored, group).curves):
            assert before.axes == after.axes
            assert before.values == after.values
            assert before.condition == after.condition
    assert [t.elements for t in restored.thermal] == [t.elements for t in device.thermal]
    assert restored.models[0].adapter_metadata == device.models[0].adapter_metadata
    assert PowerSemiconductorDevice.model_validate_json(JsonExporter().export(device)) == device


def test_known_physical_values(device):
    eon = device.switching.curves[0]
    # 25 C, 800 V, 12.56 A => 0.371 mJ; manufacturer table, not assumed gate voltage.
    assert eon.values[2 * 6 + 2] == pytest.approx(0.000371)
    assert device.switching.curves[1].values[2 * 6 + 2] == pytest.approx(0.00007008)
    assert eon.axes[0].values == (298.15, 398.15, 1173.15, 1273.15)
    assert device.conduction.curves[0].values[11 + 6] == 0.1024
    assert ThermalEvaluator().steady_state_resistance(device.thermal[0]).value == pytest.approx(
        0.2688
    )
    assert device.ratings == ()
    assert eon.condition.gate_voltage_on is None


def test_raw_manifest_is_byte_identical():
    manifest = json.loads((ROOT / "data/raw/manifest.json").read_text())
    assert len(FILES) == 163
    assert len(manifest["files"]) == 164
    for entry in manifest["files"]:
        raw = (ROOT / entry["path"]).read_bytes()
        assert hashlib.sha256(raw).hexdigest() == entry["sha256"]
        assert len(raw) == entry["size"]


def test_synthetic_technologies():
    for path in (ROOT / "tests/golden/fixtures").glob("*.json"):
        device = PowerSemiconductorDevice.model_validate_json(path.read_bytes())
        assert validate_device(device).valid
        assert device.provenance[0].name.startswith("Synthetic")
        if device.classification.integration == "module":
            assert len(device.package.components) == 2
