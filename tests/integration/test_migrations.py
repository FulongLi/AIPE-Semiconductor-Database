import pytest
from conftest import ROOT

from aipe_devices.exporters.plecs import PlecsExporter
from aipe_devices.importers.base import UnsupportedFormatError
from aipe_devices.migration.v1_to_v3 import load as v1
from aipe_devices.migration.v2_to_v3 import load as v2
from aipe_devices.services.validation import validate_device


@pytest.mark.parametrize("path", sorted((ROOT / "legacy/v1").glob("*.json")), ids=lambda p: p.stem)
def test_v1_migration(path):
    device = v1(path)
    assert validate_device(device).valid
    assert device.quality.flags[0] == "legacy_v1"
    if device.models[0].adapter_metadata["unresolved_tables"]:
        with pytest.raises(UnsupportedFormatError):
            PlecsExporter().export(device)


@pytest.mark.parametrize("path", sorted((ROOT / "legacy/v2").glob("*.json")), ids=lambda p: p.stem)
def test_v2_migration(path):
    device = v2(path)
    assert validate_device(device).valid
    assert "legacy_v2_lossy" in device.quality.flags
    assert all(r.provenance.origin == "inferred" for r in device.ratings)
    assert all(c.condition.gate_voltage_on is None for c in device.switching.curves)
