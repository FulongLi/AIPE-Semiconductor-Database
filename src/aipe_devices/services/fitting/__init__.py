from typing import Protocol

from aipe_devices.domain.curves import Curve
from aipe_devices.domain.models import ModelReference


class ModelFitter(Protocol):
    def fit(self, curve: Curve, *, input_version: str) -> ModelReference: ...
