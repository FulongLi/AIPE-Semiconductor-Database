from typing import Literal

from pydantic import model_validator

from .base import Model
from .quantities import Quantity

CONDITION_UNITS = {
    "junction_temperature": "K",
    "case_temperature": "K",
    "ambient_temperature": "K",
    "dc_bus_voltage": "V",
    "drain_current": "A",
    "collector_current": "A",
    "gate_voltage_on": "V",
    "gate_voltage_off": "V",
    "gate_resistance_on": "Ohm",
    "gate_resistance_off": "Ohm",
    "switching_frequency": "Hz",
    "pulse_width": "s",
    "duty_cycle": "1",
}


class ConditionParameter(Model):
    name: str
    quantity: Quantity


class OperatingCondition(Model):
    junction_temperature: Quantity | None = None
    case_temperature: Quantity | None = None
    ambient_temperature: Quantity | None = None
    dc_bus_voltage: Quantity | None = None
    drain_current: Quantity | None = None
    collector_current: Quantity | None = None
    gate_voltage_on: Quantity | None = None
    gate_voltage_off: Quantity | None = None
    gate_resistance_on: Quantity | None = None
    gate_resistance_off: Quantity | None = None
    switching_frequency: Quantity | None = None
    pulse_width: Quantity | None = None
    duty_cycle: Quantity | None = None
    gate_state: Literal["on", "off", "unknown"] = "unknown"
    extensions: tuple[ConditionParameter, ...] = ()

    @model_validator(mode="after")
    def validate_units(self):
        for name, unit in CONDITION_UNITS.items():
            q = getattr(self, name)
            if q is not None:
                if q.unit != unit:
                    raise ValueError(f"{name} requires {unit}")
                if unit == "K" and q.value < 0:
                    raise ValueError("Absolute temperature must be non-negative")
                if name == "duty_cycle" and not 0 <= q.value <= 1:
                    raise ValueError("Duty cycle must be in [0, 1]")
        names = [x.name for x in self.extensions]
        if len(names) != len(set(names)) or set(names) & CONDITION_UNITS.keys():
            raise ValueError("Duplicate/shadowed condition parameter")
        return self
