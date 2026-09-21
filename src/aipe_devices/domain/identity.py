from typing import Literal

from pydantic import Field

from aipe_devices.schema.enums import Technology

from .base import Model


class DeviceIdentity(Model):
    """device_id is assigned, not computed from the optional hierarchy."""

    manufacturer: str = Field(min_length=1)
    part_number: str = Field(min_length=1)
    family_id: str | None = None
    part_id: str | None = None
    revision_id: str | None = None
    production_lot_id: str | None = None
    physical_sample_id: str | None = None
    aliases: tuple[str, ...] = ()


class Classification(Model):
    technology: Technology = Technology.UNKNOWN
    integration: Literal["discrete", "module", "unknown"] = "unknown"
    polarity: Literal["N", "P", "unknown"] = "unknown"
