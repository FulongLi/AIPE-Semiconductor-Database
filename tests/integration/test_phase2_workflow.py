import json
import subprocess
import sys

import pytest
from conftest import ROOT

from aipe_devices.explorer import DeviceExplorer
from aipe_devices.importers.library import LibraryImporter
from aipe_devices.measurement.gap_planner import draft_measurement_request
from aipe_devices.repository.json_repository import JsonDeviceRepository
from aipe_devices.services.coverage import CoverageAnalyzer
from aipe_devices.services.coverage.gaps import DABLossEvaluationPolicy
from aipe_devices.visualization import VisualizationBuilder, VisualizationSpec


def cli(*args):
    return subprocess.run(
        [sys.executable, "-m", "aipe_devices.cli", *map(str, args)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )


def test_cli_end_to_end_excel_to_explorer_and_draft(tmp_path):
    result = cli(
        "import-library",
        ROOT / "examples/import/device_switching.xlsx",
        "--origin",
        "synthetic",
        "--output",
        tmp_path / "canonical",
    )
    assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout)
    assert report["final_status"] == "imported"
    assert report["dataset_status"] == "partial"
    assert report["records_created"] == 3
    repo = JsonDeviceRepository(tmp_path / "canonical")
    explorer = DeviceExplorer(repo)
    device_id = repo.list()[0]
    device = repo.get(device_id)
    assert explorer.search("DEMO-001")[0]["device_id"] == device_id
    summary = explorer.summary(device_id)
    assert "switching" in summary["sections"] and "thermal" not in summary["sections"]
    ids = [c.id for c in device.switching.curves]
    spec = explorer.visualize(
        device_id,
        ids,
        x="current",
        y="junction_temperature",
        fixed={"dc_bus_voltage": 800, "gate_resistance_on": 5},
    )
    assert spec.kind == "multi_surface_3d"
    selected = VisualizationBuilder().select_point(
        spec, series_id=ids[0], coordinates={"current": 40, "junction_temperature": 398.15}
    )
    assert selected.selected_point.value.value == pytest.approx(0.001275)
    assert (
        selected.selected_point.sources[0].import_metadata.original_filename
        == "device_switching.xlsx"
    )
    assert explorer.raw_record(device_id, ids[0])["values"] == list(
        device.switching.curves[0].values
    )
    gaps = CoverageAnalyzer().gaps(device, DABLossEvaluationPolicy())
    assert not gaps.acceptable
    draft = draft_measurement_request(gaps)
    assert any(i.protocol.category == "thermal" for i in draft.test_plan_items)
    assert all(p.suffix == ".json" for p in repo.root.iterdir())


def test_cli_confirmation_exit_code_then_explicit_mapping(tmp_path):
    path = ROOT / "examples/import/device_ambiguous.csv"
    inspected = cli("inspect-import", path)
    assert inspected.returncode == 2
    assert {c["column"] for c in json.loads(inspected.stdout)["unresolved_columns"]} == {
        "Loss1",
        "Loss2",
    }
    blocked = cli("import-library", path, "--output", tmp_path / "blocked")
    assert blocked.returncode == 2
    assert not (tmp_path / "blocked").exists()
    mapped = cli(
        "import-library",
        path,
        "--mapping",
        ROOT / "examples/import/mapping_override.json",
        "--origin",
        "synthetic",
        "--output",
        tmp_path / "mapped",
    )
    assert mapped.returncode == 0, mapped.stderr
    assert json.loads(mapped.stdout)["final_status"] == "imported"


@pytest.mark.parametrize(
    "filename", ["device_canonical.json", "device_generic.json", "device_partial.csv"]
)
def test_other_import_formats(tmp_path, filename):
    result = cli(
        "import-library", ROOT / "examples/import" / filename, "--output", tmp_path / "repo"
    )
    assert result.returncode == 0, result.stderr
    assert len(list((tmp_path / "repo").glob("*.json"))) == 1


def test_examples_validate_and_never_pollute_manufacturer_corpus():
    for name in ("line", "surface", "conduction_surface", "multi_surface", "waveform"):
        VisualizationSpec.model_validate_json((ROOT / f"examples/phase2/{name}.json").read_bytes())
    repo = JsonDeviceRepository(ROOT / "data/canonical")
    assert len(repo.list()) == 163
    assert all(key.startswith("wolfspeed_") for key in repo.list())


def test_selected_device_does_not_load_entire_repository(device):
    class SingleReadRepository:
        reads = 0

        def get(self, key):
            self.reads += 1
            assert key == device.device_id
            return device

        def list(self):
            raise AssertionError("Unexpected catalogue scan")

    repo = SingleReadRepository()
    DeviceExplorer(repo).visualize(device.device_id, [device.switching.curves[0].id])
    assert repo.reads == 1


def test_malformed_workbook_and_formula_report(tmp_path):
    from openpyxl import Workbook

    path = tmp_path / "bad.xlsx"
    path.write_bytes(b"not a ZIP workbook")
    assert LibraryImporter().inspect(path).status == "failed"
    book = Workbook()
    book.active.append(["manufacturer", "part_number", "Id(A)", "Eon(mJ)"])
    book.active.append(["Synthetic", "Formula", 10, "=1+1"])
    book.save(path)
    session = LibraryImporter().inspect(path)
    assert session.status == "failed"
    assert any("row 2" in e for e in session.report.errors)
