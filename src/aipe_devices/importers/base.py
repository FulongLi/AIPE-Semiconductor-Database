from pathlib import Path
from typing import Protocol

from aipe_devices.domain.device import PowerSemiconductorDevice


class DeviceImporter(Protocol):
    def load(self, path: str | Path) -> PowerSemiconductorDevice: ...


class UnsupportedFormatError(ValueError):
    pass
