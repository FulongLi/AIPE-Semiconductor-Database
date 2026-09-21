from pathlib import Path

from aipe_devices.domain.device import PowerSemiconductorDevice
from aipe_devices.services.validation import validate_device
from aipe_devices.storage.artifact_store import atomic_write


class JsonExporter:
    def export(self, device: PowerSemiconductorDevice, path: str | Path | None = None) -> str:
        validate_device(device).raise_for_errors()
        result = device.model_dump_json(indent=2) + "\n"
        if path is not None:
            atomic_write(Path(path), result.encode())
        return result
