from typing import Literal

from pydantic import Field, model_validator

from .base import Model
from .provenance import Provenance
from .quantities import Quantity


class ThermalElement(Model):
    resistance: Quantity
    capacitance: Quantity

    @model_validator(mode="after")
    def physical_units(self):
        if self.resistance.unit != "K/W" or self.capacitance.unit != "J/K":
            raise ValueError("Thermal R and C require K/W and J/K")
        if self.resistance.value < 0 or self.capacitance.value <= 0:
            raise ValueError("Thermal R must be nonnegative and C positive")
        return self


class ThermalNetwork(Model):
    id: str = Field(min_length=1)
    topology: Literal["Cauer", "Foster"]
    elements: tuple[ThermalElement, ...] = Field(min_length=1)
    provenance: Provenance
    from_node: str = "junction"
    to_node: str = "case"
