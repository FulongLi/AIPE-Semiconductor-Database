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
}


def normalize(value: float, unit: str) -> Quantity:
    target, scale, offset = CONVERSIONS.get(unit, (unit, 1, 0))
    return Quantity(value=value * scale + offset, unit=target)
