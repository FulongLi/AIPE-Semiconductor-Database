"""Common serialization rules; domain objects reject unknown fields and nonfinite numbers."""

from pydantic import BaseModel, ConfigDict


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)
