import json

import pytest
from conftest import ROOT

from aipe_devices.domain.device import PowerSemiconductorDevice
from aipe_devices.importers.datasheet import (
    DatasheetImporter,
    load_candidates,
    load_transcription,
    write_candidates,
)
from aipe_devices.repository.json_repository import JsonDeviceRepository
from aipe_devices.services.validation import validate_device

YAML = ROOT / "data/candidates/sic-dab-shortlist-2026-10-21.yaml"
RECORDS = ROOT / "data/candidates/records"


def transcription(**device_overrides):
    entry = {
        "part_number": "TEST-1",
        "manufacturer": "Synthetic",
        "integration": "discrete",
        "package": "TO-247-4",
        "datasheet": {
            "url": "https://example.com/test.pdf",
            "revision": "Rev. 1",
            "date": "2026-01",
        },
        "ratings": {"vds_max": {"value": 1200, "unit": "V"}},
        "conduction": {
            "rds_on": {
                "value": 40,
                "unit": "mOhm",
                "statistic": "typical",
                "conditions": {
                    "junction_temperature": {"value": 25, "unit": "degC"},
                    "gate_voltage_on": {"value": 15, "unit": "V"},
                },
            }
        },
        "reverse_conduction": {
            "vsd": {
                "value": 4.5,
                "unit": "V",
                "conditions": {"source_current": {"value": 20, "unit": "A"}},
            }
        },
        "absent": ["Eoss"],
    }
    entry.update(device_overrides)
    return {
        "schema": "aipe-datasheet-transcription/0.1",
        "title": "test",
        "collected_on": "2026-10-21",
        "transcribed_from": "unit test",
        "devices": [entry],
    }


def write(tmp_path, data, name="t.json"):
    path = tmp_path / name
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def test_json_transcription_becomes_valid_unreviewed_candidate(tmp_path):
    items = DatasheetImporter().load(write(tmp_path, transcription()))
    assert len(items) == 1
    device = items[0].device
    assert device.device_id == "candidate_synthetic_test-1"
    assert device.quality.review_status == "unreviewed"
    assert {"candidate_not_canonical", "datasheet_transcription", "absent:Eoss"} <= set(
        device.quality.flags
    )
    assert validate_device(device).valid
    rds = device.conduction.scalars[0]
    assert rds.quantity.value == pytest.approx(0.04) and rds.quantity.unit == "Ohm"
    assert rds.condition.junction_temperature.value == pytest.approx(298.15)
    assert rds.provenance.origin == "manufacturer_datasheet"
    assert rds.provenance.source_locators[0].original_unit == "mOhm"
    assert device.provenance[0].url == "https://example.com/test.pdf"
    vsd = device.reverse_conduction.scalars[0]
    assert vsd.name == "voltage_drop"
    assert vsd.quantity.value == -4.5 and vsd.condition.drain_current.value == -20.0
    assert "sign_convention:third_quadrant_negative_voltage_drop" in vsd.quality.flags
    assert items[0].dossier.field_basis["conduction.rds_on"] == "manufacturer_specified"
    assert items[0].dossier.canonical_link is None


@pytest.mark.parametrize(
    "override, message",
    [
        ({"conduction": {"rds_on": {"value": 1, "unit": "V"}}}, "converts to"),
        ({"conduction": {"mystery": {"value": 1, "unit": "Ohm"}}}, "unknown conduction field"),
        ({"datasheet": None, "product_page": None}, "datasheet, product page or citation"),
        (
            {"ratings": {"vds_max": {"value": 1200, "unit": "V", "basis": "product_page"}}},
            "without a source",
        ),
        (
            {
                "conduction": {
                    "rds_on": {
                        "value": 1,
                        "unit": "Ohm",
                        "conditions": {"foo": {"value": 1, "unit": "V"}},
                    }
                }
            },
            "Unknown transcription condition",
        ),
    ],
)
def test_transcription_errors_are_explicit(tmp_path, override, message):
    with pytest.raises(ValueError, match=message):
        DatasheetImporter().load(write(tmp_path, transcription(**override)))


def test_unknown_top_level_keys_rejected(tmp_path):
    data = transcription()
    data["devices"][0]["estimated_rds_on"] = 1
    with pytest.raises(ValueError):
        load_transcription(write(tmp_path, data))


def test_real_shortlist_imports_and_links_canonical_records():
    pytest.importorskip("yaml")
    repo = JsonDeviceRepository(ROOT / "data/canonical")
    items = DatasheetImporter(repo).load(YAML)
    assert len(items) == 19
    by_part = {i.device.identity.part_number: i for i in items}
    assert {
        "C3M0040120K",
        "C4MS047120K",
        "C3M0025065K",
        "CBB021M12FM3",
        "C3M0075120K",
        "C3M0030090K",
    } == {p for p, i in by_part.items() if i.dossier.canonical_link}
    link = by_part["C3M0075120K"].dossier.canonical_link
    assert link.device_id == "wolfspeed_c3m0075120k"
    assert link.uri == "urn:aipe:semiconductor:wolfspeed_c3m0075120k:revision:1"
    assert any("Eoff tensor" in p for p in link.provides)
    device = by_part["C3M0075120K"].device
    assert any(s.kind == "AIPE" and s.url == link.uri for s in device.provenance)
    assert "values_cited_by_third_party" in device.quality.flags
    assert all("basis:third_party_cited" in r.quality.flags for r in device.ratings)
    for item in items:
        assert item.validation.valid
        assert item.device.device_id.startswith("candidate_")
        assert item.device.quality.review_status == "unreviewed"
        assert all(
            r.name != "rds_on" or r.quantity.unit == "Ohm" for r in item.device.conduction.scalars
        )
    c3m = by_part["C3M0040120K"].device
    hot = [r for r in c3m.conduction.scalars if r.condition.junction_temperature.value > 440]
    assert hot[0].quantity.value == pytest.approx(0.068)
    eoss = [r for r in c3m.capacitance.scalars if r.name == "Eoss"]
    assert eoss[0].quantity.value == pytest.approx(60e-6)
    assert by_part["IMZA65R027M1H"].device.switching.scalars == ()
    assert any("Eon/Eoff" in a for a in by_part["IMZA65R027M1H"].dossier.absent)


def test_write_and_load_roundtrip_is_deterministic(tmp_path):
    pytest.importorskip("yaml")
    items = DatasheetImporter(JsonDeviceRepository(ROOT / "data/canonical")).load(YAML)
    report = write_candidates(items, tmp_path)
    assert report["status"].startswith("unreviewed")
    loaded = load_candidates(tmp_path)
    assert [i.device for i in loaded] == sorted(
        (i.device for i in items), key=lambda d: d.device_id
    )
    assert [i.dossier for i in loaded] == sorted(
        (i.dossier for i in items), key=lambda d: d.candidate_id
    )


def test_committed_candidate_records_match_the_transcription():
    pytest.importorskip("yaml")
    committed = load_candidates(RECORDS)
    rebuilt = DatasheetImporter(JsonDeviceRepository(ROOT / "data/canonical")).load(YAML)
    assert {c.device.device_id for c in committed} == {r.device.device_id for r in rebuilt}
    by_id = {r.device.device_id: r for r in rebuilt}
    for item in committed:
        assert item.device == by_id[item.device.device_id].device
        assert item.dossier == by_id[item.device.device_id].dossier
    canonical = JsonDeviceRepository(ROOT / "data/canonical").list()
    assert not any(key.startswith("candidate_") for key in canonical)
    for path in RECORDS.glob("candidate_*.json"):
        if not path.name.endswith(".dossier.json"):
            PowerSemiconductorDevice.model_validate_json(path.read_bytes())
