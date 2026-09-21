from contextlib import contextmanager
from pathlib import Path

from aipe_devices.domain.device import PowerSemiconductorDevice
from aipe_devices.schema.enums import DERIVED_ORIGINS
from aipe_devices.services.validation import records, validate_device
from aipe_devices.storage.artifact_store import atomic_write, safe_identifier


class JsonDeviceRepository:
    """Atomic files, exclusive writer lock, optimistic revisions; no database dependency."""

    def __init__(self, root: str | Path):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, device_id: str) -> Path:
        return self.root / f"{safe_identifier(device_id)}.json"

    @contextmanager
    def _writer(self):
        lock = self.root / ".write-lock"
        try:
            lock.mkdir()
        except FileExistsError as exc:
            raise RuntimeError("Repository writer busy (or stale lock after crash)") from exc
        try:
            yield
        finally:
            lock.rmdir()

    def get(self, device_id: str) -> PowerSemiconductorDevice:
        device = PowerSemiconductorDevice.model_validate_json(self._path(device_id).read_bytes())
        if device.device_id != device_id:
            raise ValueError("Repository filename does not match device ID")
        validate_device(device).raise_for_errors()
        return device

    def list(self) -> tuple[str, ...]:
        return tuple(sorted(p.stem for p in self.root.glob("*.json")))

    def search(self, query: str) -> tuple[PowerSemiconductorDevice, ...]:
        query = query.casefold()
        return tuple(
            d
            for key in self.list()
            if query
            in " ".join(
                [
                    (d := self.get(key)).device_id,
                    d.identity.manufacturer,
                    d.identity.part_number,
                    *d.identity.aliases,
                ]
            ).casefold()
        )

    def _write(self, device):
        # Revalidate even model_copy/update and mutable adapter metadata.
        device = PowerSemiconductorDevice.model_validate(device.model_dump())
        validate_device(device).raise_for_errors()
        atomic_write(
            self._path(device.device_id), (device.model_dump_json(indent=2) + "\n").encode()
        )

    def save(self, device: PowerSemiconductorDevice) -> None:
        with self._writer():
            if self._path(device.device_id).exists():
                raise FileExistsError(device.device_id)
            self._write(device)

    def update(self, device: PowerSemiconductorDevice, *, expected_revision: int) -> None:
        with self._writer():
            old = self.get(device.device_id)
            if old.revision != expected_revision or device.revision != expected_revision + 1:
                raise ValueError("Revision conflict: update must increment expected revision")
            new_records = {r.id: r for r in records(device)}
            for record in records(old):
                if record.provenance.origin not in DERIVED_ORIGINS:
                    replacement = new_records.get(record.id)
                    if replacement is None or replacement != record:
                        raise ValueError(
                            "Source evidence is immutable; append a new record/version"
                        )
            new_sources = {s.id: s for s in device.provenance}
            if any(new_sources.get(s.id) != s for s in old.provenance):
                raise ValueError("Source evidence cannot be removed or replaced")
            self._write(device)
