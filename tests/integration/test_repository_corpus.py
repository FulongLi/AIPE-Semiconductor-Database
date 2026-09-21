import pytest
from conftest import RAW, ROOT

from aipe_devices.cli import import_wolfspeed
from aipe_devices.exporters.matlab import MatlabExporter
from aipe_devices.repository.json_repository import JsonDeviceRepository


def test_committed_corpus_rebuild_is_deterministic():
    report = import_wolfspeed(RAW, ROOT / "data/canonical")
    assert report["devices"] == 163
    assert report["custom_tables"] == 90
    assert report["integration"] == {"discrete": 119, "module": 44}
    assert len(JsonDeviceRepository(ROOT / "data/canonical").list()) == 163


def test_matlab_export_uses_canonical_model(tmp_path, device):
    scipy = pytest.importorskip("scipy.io")
    path = MatlabExporter().export(device, tmp_path / "device.mat")
    loaded = scipy.loadmat(path, simplify_cells=True)
    assert loaded["device"]["identity"]["part_number"] == "C2M0025120D"
    assert type(device).model_validate_json(loaded["canonical_json"]) == device
