from enum import StrEnum


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
