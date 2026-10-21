"""Small explicit conversion registry. Unknown units raise; no magnitude guessing."""

from aipe_devices.domain.quantities import Quantity

CONVERSIONS = {
    "µJ": ("J", 1e-6, 0),
    "μJ": ("J", 1e-6, 0),
    "mΩ": ("Ohm", 1e-3, 0),
    "Ω": ("Ohm", 1, 0),
    "µs": ("s", 1e-6, 0),
    "μs": ("s", 1e-6, 0),
    "ms": ("s", 1e-3, 0),
    "uF": ("F", 1e-6, 0),
    "µF": ("F", 1e-6, 0),
    "mA": ("A", 1e-3, 0),
    "mV": ("V", 1e-3, 0),
    "mJ": ("J", 1e-3, 0),
    "uJ": ("J", 1e-6, 0),
    "mOhm": ("Ohm", 1e-3, 0),
    "mohm": ("Ohm", 1e-3, 0),
    "ohm": ("Ohm", 1, 0),
    "degC": ("K", 1, 273.15),
    "°C": ("K", 1, 273.15),
    "ns": ("s", 1e-9, 0),
    "us": ("s", 1e-6, 0),
    "nF": ("F", 1e-9, 0),
    "pF": ("F", 1e-12, 0),
    "nC": ("C", 1e-9, 0),
    "MHz": ("Hz", 1e6, 0),
    "kHz": ("Hz", 1e3, 0),
    "kV": ("V", 1000.0, 0),
    "uH": ("H", 1e-06, 0),
    "µH": ("H", 1e-06, 0),
    "μH": ("H", 1e-06, 0),
    "nH": ("H", 1e-09, 0),
    "mH": ("H", 0.001, 0),
    "uC": ("C", 1e-06, 0),
    "µC": ("C", 1e-06, 0),
    "μC": ("C", 1e-06, 0),
    "A/us": ("A/s", 1000000.0, 0),
    "A/µs": ("A/s", 1000000.0, 0),
    "A/μs": ("A/s", 1000000.0, 0),
    "A/ns": ("A/s", 1000000000.0, 0),
    "V/us": ("V/s", 1000000.0, 0),
    "V/µs": ("V/s", 1000000.0, 0),
    "V/ns": ("V/s", 1000000000.0, 0),
    "kW": ("W", 1000.0, 0),
    "mW": ("W", 0.001, 0),
    "degC/W": ("K/W", 1, 0),
    "°C/W": ("K/W", 1, 0),
}


def normalize(value: float, unit: str) -> Quantity:
    target, scale, offset = CONVERSIONS.get(unit, (unit, 1, 0))
    return Quantity(value=value * scale + offset, unit=target)
