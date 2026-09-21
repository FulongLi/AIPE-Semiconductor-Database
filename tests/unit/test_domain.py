import pytest
from pydantic import ValidationError

from aipe_devices.domain.conditions import OperatingCondition
from aipe_devices.domain.curves import Axis, Curve
from aipe_devices.domain.device import PowerSemiconductorDevice
from aipe_devices.domain.identity import DeviceIdentity
from aipe_devices.domain.provenance import Provenance
from aipe_devices.domain.quantities import Quantity
from aipe_devices.normalizers.units import normalize
from aipe_devices.services.validation import validate_device


@pytest.mark.parametrize(
    "value,unit", [(float("nan"), "V"), (float("inf"), "J"), (2, "guessed_mJ")]
)
def test_invalid_quantity(value, unit):
    with pytest.raises(ValidationError):
        Quantity(value=value, unit=unit)


def test_conditions_units_and_missing():
    assert OperatingCondition().junction_temperature is None
    with pytest.raises(ValidationError):
        OperatingCondition(junction_temperature=Quantity(value=25, unit="C"))
    assert normalize(25, "degC").value == 298.15
    assert normalize(1.42, "mJ").value == pytest.approx(0.00142)
    assert normalize(23, "mOhm").value == 0.023


def test_identity_hierarchy():
    identity = DeviceIdentity(
        manufacturer="Example",
        part_number="X",
        family_id="family",
        part_id="part",
        revision_id="revA",
        production_lot_id="lot1",
        physical_sample_id="sample7",
    )
    assert identity.production_lot_id == "lot1"


def test_derived_requires_lineage():
    with pytest.raises(ValidationError):
        Provenance(origin="inferred", source_ids=("s",))
    with pytest.raises(ValidationError):
        Provenance(origin="measured", source_ids=())


def test_shape_and_reference_validation(device):
    with pytest.raises(ValidationError):
        Curve(
            id="bad",
            name="Eon",
            unit="J",
            axes=(Axis(name="current", unit="A", values=(1, 2)),),
            values=(1,),
            provenance=device.switching.curves[0].provenance,
        )
    bad = device.model_dump(mode="json")
    bad["switching"]["curves"][0]["provenance"]["source_ids"] = ["missing"]
    assert not validate_device(PowerSemiconductorDevice.model_validate(bad)).valid
    bad = device.model_dump(mode="json")
    bad["switching"]["curves"][0]["values"][0] = -1
    assert not validate_device(PowerSemiconductorDevice.model_validate(bad)).valid


def test_unknown_schema_fields_rejected(device):
    data = device.model_dump()
    data["schema_version"] = "4.0"
    with pytest.raises(ValidationError):
        PowerSemiconductorDevice.model_validate(data)
    with pytest.raises(ValidationError):
        OperatingCondition(magic_temperature=25)
