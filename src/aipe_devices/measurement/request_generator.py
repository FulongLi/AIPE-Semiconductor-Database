from typing import Literal
from uuid import uuid4

from pydantic import Field

from aipe_devices.domain.base import Model
from aipe_devices.domain.conditions import OperatingCondition
from aipe_devices.domain.measurement import MeasurementProtocol
from aipe_devices.domain.provenance import AccessMetadata


class MeasurementRequest(Model):
    schema_version: Literal["3.0.0"] = "3.0.0"
    id: str = Field(min_length=1)
    device_id: str = Field(min_length=1)
    physical_sample_id: str | None = None
    protocols: tuple[MeasurementProtocol, ...] = Field(min_length=1)
    conditions: tuple[OperatingCondition, ...] = Field(min_length=1)
    requested_metrics: tuple[str, ...] = ()
    repetitions: int = Field(default=1, ge=1)
    access: AccessMetadata = AccessMetadata()


def generate_request(*, device_id, protocols, conditions, requested_metrics=(), **kwargs):
    return MeasurementRequest(
        id=str(uuid4()),
        device_id=device_id,
        protocols=tuple(protocols),
        conditions=tuple(conditions),
        requested_metrics=tuple(requested_metrics),
        **kwargs,
    )
