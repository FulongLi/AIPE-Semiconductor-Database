from datetime import datetime
from decimal import Decimal
from typing import Protocol

from pydantic import Field, field_validator

from .base import Model
from .provenance import Source


class MarketObservation(Model):
    id: str
    device_id: str
    distributor: str
    region: str
    currency: str = Field(pattern=r"^[A-Z]{3}$")
    quantity_break: int = Field(ge=1)
    unit_price: Decimal = Field(ge=0)
    stock: int | None = Field(default=None, ge=0)
    lead_time_seconds: float | None = Field(default=None, ge=0)
    timestamp: datetime
    source: Source

    @field_validator("timestamp")
    @classmethod
    def timezone_required(cls, value):
        if value.tzinfo is None:
            raise ValueError("Market observation timestamp needs a timezone")
        return value


class MarketRepository(Protocol):
    def observations(self, device_id: str) -> tuple[MarketObservation, ...]: ...
    def append(self, observation: MarketObservation) -> None: ...
