from datetime import datetime, timezone

import pytest

from aipe_devices.exporters.core import export_core_candidate
from aipe_devices.schema.enums import Technology


def export(device, **kwargs):
    args = {
        "role": "primary-bridge candidate",
        "record_uri": "urn:aipe:semiconductor:wolfspeed_c2m0025120d:revision:1",
        "exported_at": datetime(2026, 10, 7, tzinfo=timezone.utc),
    }
    args.update(kwargs)
    return export_core_candidate(device, **args)


def test_identity_projection_is_deterministic_and_conservative(device):
    original = device.model_dump_json()
    result = export(device)
    assert result == export(device)
    assert device.model_dump_json() == original
    assert result["component"]["technology"] == "SiC"
    assert result["component"]["part_number"] == device.identity.part_number
    assert result["component"]["selection_status"] == "candidate"
    assert result["component"]["evidence_refs"] == [result["evidence"]["id"]]
    assert result["evidence"]["kind"] == "source"
    assert "ratings" not in result["component"]


@pytest.mark.parametrize("technology", [Technology.IGBT, Technology.DIODE])
def test_structure_does_not_invent_material(device, technology):
    classification = device.classification.model_copy(update={"technology": technology})
    result = export(device.model_copy(update={"classification": classification}))
    assert result["component"]["technology"] == "unspecified"


@pytest.mark.parametrize(
    "kwargs",
    [
        {"role": " "},
        {"record_uri": "local.json"},
        {"record_uri": "https://example.com/invalid uri"},
        {"exported_at": datetime(2026, 10, 7)},
    ],
)
def test_invalid_export_context_is_rejected(device, kwargs):
    with pytest.raises(ValueError):
        export(device, **kwargs)


def test_revision_has_distinct_evidence_identity(device):
    revised = device.model_copy(update={"revision": device.revision + 1})
    assert export(revised)["evidence"]["id"] != export(device)["evidence"]["id"]
