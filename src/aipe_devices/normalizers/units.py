"""Small explicit conversion registry. Unknown units raise; no magnitude guessing."""

from aipe_devices.domain.quantities import Quantity

CONVERSIONS = {
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
