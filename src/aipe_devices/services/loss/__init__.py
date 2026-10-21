from typing import Protocol, runtime_checkable

from aipe_devices.domain.conditions import OperatingCondition
from aipe_devices.domain.curves import ScalarRecord
from aipe_devices.domain.device import PowerSemiconductorDevice


@runtime_checkable
class LossEvaluator(Protocol):
    """Loss contract; converter topology and switching policy must be explicit.

    ``aipe_devices.services.loss.dab.DABLossEvaluator`` implements it for a DAB switch position.
    """

    def evaluate(
        self, *, device: PowerSemiconductorDevice, operating_point: OperatingCondition
    ) -> tuple[ScalarRecord, ...]: ...
