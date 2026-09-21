from math import prod

from pydantic import Field, model_validator

from aipe_devices.schema.enums import Availability, Statistic

from .base import Model
from .conditions import OperatingCondition
from .provenance import Provenance
from .quality import Quality, Uncertainty
from .quantities import Quantity, Unit


class ScalarRecord(Model):
    id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    quantity: Quantity
    provenance: Provenance
    condition: OperatingCondition = OperatingCondition()
    statistic: Statistic = Statistic.UNSPECIFIED
    uncertainty: Uncertainty | None = None
    quality: Quality = Quality()


class Axis(Model):
    name: str = Field(min_length=1)
    unit: Unit
    values: tuple[float, ...] = Field(min_length=1)


class Curve(Model):
    """Dense tensor; last axis varies fastest. No simulator-specific fields."""

    id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    axes: tuple[Axis, ...] = Field(min_length=1)
    values: tuple[float, ...] = Field(min_length=1)
    unit: Unit
    provenance: Provenance
    condition: OperatingCondition = OperatingCondition()
    statistic: Statistic = Statistic.UNSPECIFIED
    uncertainty: Uncertainty | None = None
    quality: Quality = Quality()

    @model_validator(mode="after")
    def dimensions(self):
        if len(self.values) != prod(len(a.values) for a in self.axes):
            raise ValueError("Curve dimensions do not match value count")
        if len({a.name for a in self.axes}) != len(self.axes):
            raise ValueError("Curve axis names must be unique")
        return self


class CharacteristicData(Model):
    availability: Availability = Availability.UNKNOWN
    scalars: tuple[ScalarRecord, ...] = ()
    curves: tuple[Curve, ...] = ()

    @model_validator(mode="after")
    def availability_matches_data(self):
        has_data = bool(self.scalars or self.curves)
        if has_data and self.availability not in {Availability.AVAILABLE, Availability.PARTIAL}:
            raise ValueError("Populated characteristic must be available or partial")
        if not has_data and self.availability in {Availability.AVAILABLE, Availability.PARTIAL}:
            raise ValueError("Available characteristic requires data")
        return self
