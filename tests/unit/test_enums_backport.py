import json
import sys

from aipe_devices.domain.provenance import Provenance
from aipe_devices.schema.enums import Origin, StrEnum, Technology


def test_strenum_members_behave_as_strings():
    assert isinstance(Origin.PHYSICS, str)
    assert str(Origin.PHYSICS) == "physics_derived"
    assert format(Technology.SIC_MOSFET) == "SiC_MOSFET"
    assert f"{Origin.INTERPOLATED}" == "interpolated"
    assert Origin.PHYSICS == "physics_derived"
    assert Origin("manufacturer_model") is Origin.MODEL
    assert json.loads(json.dumps({"origin": Origin.DATASHEET})) == {
        "origin": "manufacturer_datasheet"
    }


def test_pydantic_serialisation_uses_values():
    provenance = Provenance(origin=Origin.DATASHEET, source_ids=("s",))
    assert provenance.model_dump(mode="json")["origin"] == "manufacturer_datasheet"
    assert Provenance.model_validate_json(provenance.model_dump_json()) == provenance


def test_backport_only_on_old_interpreters():
    if sys.version_info >= (3, 11):
        from enum import StrEnum as Standard

        assert StrEnum is Standard
    else:
        assert StrEnum.__module__ == "aipe_devices.schema.enums"
