from typing import Literal

from pydantic import Field

from .base import Model
from .curves import CharacteristicData, ScalarRecord
from .identity import Classification, DeviceIdentity
from .models import ModelReference
from .module import DevicePackage
from .provenance import Source
from .quality import Quality
from .reliability import ReliabilityRecord
from .thermal import ThermalNetwork

CHARACTERISTICS = (
    "conduction",
    "switching",
    "capacitance",
    "gate_charge",
    "reverse_conduction",
    "soa",
)


class PowerSemiconductorDevice(Model):
    schema_version: Literal["3.0.0"] = "3.0.0"
    device_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")
    revision: int = Field(default=1, ge=1)
    identity: DeviceIdentity
    classification: Classification = Classification()
    ratings: tuple[ScalarRecord, ...] = ()
    package: DevicePackage = DevicePackage()
    provenance: tuple[Source, ...] = Field(min_length=1)
    quality: Quality = Quality()
    conduction: CharacteristicData = CharacteristicData()
    switching: CharacteristicData = CharacteristicData()
    capacitance: CharacteristicData = CharacteristicData()
    gate_charge: CharacteristicData = CharacteristicData()
    reverse_conduction: CharacteristicData = CharacteristicData()
    thermal: tuple[ThermalNetwork, ...] = ()
    soa: CharacteristicData = CharacteristicData()
    reliability: tuple[ReliabilityRecord, ...] = ()
    models: tuple[ModelReference, ...] = ()
    measurement_ids: tuple[str, ...] = ()
    market_reference_ids: tuple[str, ...] = ()
