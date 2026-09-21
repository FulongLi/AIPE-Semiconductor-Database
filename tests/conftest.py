from pathlib import Path

import pytest

from aipe_devices.importers.plecs import PlecsImporter
from aipe_devices.schema.enums import Technology

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data/raw/wolfspeed"


@pytest.fixture
def device():
    path = next(RAW.rglob("C2M0025120D.xml"))
    return PlecsImporter().load(path, technology=Technology.SIC_MOSFET, integration="discrete")
