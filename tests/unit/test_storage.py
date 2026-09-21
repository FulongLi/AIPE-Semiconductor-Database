import pytest

from aipe_devices.repository.json_repository import JsonDeviceRepository
from aipe_devices.storage.artifact_store import LocalArtifactStore


def test_repository_crud_and_evidence_protection(tmp_path, device):
    repo = JsonDeviceRepository(tmp_path / "devices")
    repo.save(device)
    assert repo.get(device.device_id) == device
    assert repo.list() == (device.device_id,)
    assert repo.search("C2M0025") == (device,)
    with pytest.raises(FileExistsError):
        repo.save(device)
    newer = device.model_copy(update={"revision": 2, "measurement_ids": ("run:1",)})
    repo.update(newer, expected_revision=1)
    assert repo.get(device.device_id).revision == 2
    with pytest.raises(ValueError, match="Revision"):
        repo.update(newer, expected_revision=1)
    changed = newer.model_dump(mode="json")
    changed["revision"] = 3
    changed["switching"]["curves"][0]["values"][0] = 99
    with pytest.raises(ValueError, match="immutable"):
        repo.update(type(device).model_validate(changed), expected_revision=2)
    assert repo.get(device.device_id) == newer
    with pytest.raises(ValueError):
        repo.get("../escape")


def test_artifact_checksum_and_deduplication(tmp_path):
    store = LocalArtifactStore(tmp_path)
    ref = store.put(b"raw waveform bytes", format="application/octet-stream")
    assert store.put(b"raw waveform bytes", format=ref.format) == ref
    assert store.exists(ref)
    assert store.get(ref) == b"raw waveform bytes"
    assert store.checksum(ref) == ref.checksum
    assert store.metadata(ref) == ref
    (tmp_path / ref.checksum[:2] / ref.checksum).write_bytes(b"corrupted")
    with pytest.raises(ValueError, match="integrity"):
        store.get(ref)
