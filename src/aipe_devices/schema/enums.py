"""Controlled vocabularies. ``StrEnum`` is backported so the package runs on Python 3.10."""

import sys

if sys.version_info >= (3, 11):
    from enum import StrEnum
else:  # pragma: no cover - exercised only by the Python 3.10 interpreter
    from enum import Enum

    class StrEnum(str, Enum):
        """Minimal ``enum.StrEnum`` backport: members are strings and ``str()`` is the value."""

        def __new__(cls, value, *args, **kwargs):
            if not isinstance(value, str):
                raise TypeError(f"{value!r} is not a string")
            return super().__new__(cls, value, *args, **kwargs)

        def __str__(self):
            return str(self.value)

        def _generate_next_value_(name, start, count, last_values):
            return name.lower()


class Technology(StrEnum):
    SI_MOSFET = "Si_MOSFET"
    SIC_MOSFET = "SiC_MOSFET"
    IGBT = "IGBT"
    GAN = "GaN"
    DIODE = "diode"
    UNKNOWN = "unknown"


class Lifecycle(StrEnum):
    RAW = "raw"
    NORMALIZED = "normalized"
    VALIDATED = "validated"
    CANONICAL = "canonical"
    DERIVED = "derived"
    APPLICATION_VIEW = "application_view"


class Origin(StrEnum):
    UNKNOWN = "unknown"
    MEASURED = "measured"
    DATASHEET = "manufacturer_datasheet"
    MODEL = "manufacturer_model"
    DIGITIZED = "digitized"
    INTERPOLATED = "interpolated"
    EXTRAPOLATED = "extrapolated"
    FITTED = "fitted"
    PHYSICS = "physics_derived"
    INFERRED = "inferred"
    SYNTHETIC = "synthetic"


DERIVED_ORIGINS = frozenset(
    {
        Origin.INTERPOLATED,
        Origin.EXTRAPOLATED,
        Origin.FITTED,
        Origin.PHYSICS,
        Origin.INFERRED,
        Origin.SYNTHETIC,
    }
)


class Availability(StrEnum):
    AVAILABLE = "available"
    PARTIAL = "partial"
    MISSING = "missing"
    NOT_APPLICABLE = "not_applicable"
    UNKNOWN = "unknown"


class Statistic(StrEnum):
    UNSPECIFIED = "unspecified"
    TYPICAL = "typical"
    MINIMUM = "minimum"
    MAXIMUM = "maximum"
    MEAN = "measured_mean"
    MEDIAN = "median"
    STD = "standard_deviation"


class Freshness(StrEnum):
    CURRENT = "current"
    STALE = "stale"
