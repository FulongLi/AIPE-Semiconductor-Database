from typing import Literal

from .base import Model

# Absolute temperature is K, electrical charge is C, thermal capacitance is J/K.
Unit = Literal[
    "1", "V", "A", "Ohm", "F", "C", "K", "J", "s", "W", "Hz", "H", "K/W", "J/K", "V/s", "A/s", "1/s"
]


class Quantity(Model):
    value: float
    unit: Unit
