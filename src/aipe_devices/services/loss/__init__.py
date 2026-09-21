from typing import Protocol

from aipe_devices.domain.conditions import OperatingCondition
from aipe_devices.domain.curves import ScalarRecord
from aipe_devices.domain.device import PowerSemiconductorDevice


class LossEvaluator(Protocol):
    """Extension contract; converter topology and switching policy must be explicit."""

    def evaluate(
        self, *, device: PowerSemiconductorDevice, operating_point: OperatingCondition
    ) -> tuple[ScalarRecord, ...]: ...
