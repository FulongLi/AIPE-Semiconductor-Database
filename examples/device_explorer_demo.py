"""Run from a checkout: python examples/device_explorer_demo.py. No web server needed."""

from pathlib import Path
from tempfile import TemporaryDirectory

from aipe_devices.explorer import DeviceExplorer
from aipe_devices.importers.library import LibraryImporter
from aipe_devices.repository.json_repository import JsonDeviceRepository
from aipe_devices.visualization import VisualizationBuilder

ROOT = Path(__file__).resolve().parents[1]


def main():
    with TemporaryDirectory() as directory:
        importer = LibraryImporter()
        session = importer.inspect(
            ROOT / "examples/import/device_switching.xlsx", origin="synthetic"
        )
        repo = JsonDeviceRepository(directory)
        session = importer.save(session, repo)
        if session.status != "imported":
            raise ValueError(session.report.model_dump_json())
        explorer = DeviceExplorer(repo)
        result = explorer.search("DEMO-001")[0]
        device_id = result["device_id"]
        switching = [
            c["id"] for c in explorer.characteristics(device_id) if c["group"] == "switching"
        ]
        spec = explorer.visualize(
            device_id,
            switching,
            x="current",
            y="junction_temperature",
            fixed={"dc_bus_voltage": 800, "gate_resistance_on": 5},
        )
        builder = VisualizationBuilder()
        spec = builder.select_slice(
            spec, series_id=switching[0], parameter="junction_temperature", value=398.15
        )
        spec = builder.select_point(
            spec,
            series_id=switching[0],
            coordinates={"current": 40, "junction_temperature": 398.15},
        )
        print(f"Selected: {device_id}; {spec.kind}")
        print(f"Series: {[s.label for s in spec.series]}")
        print(f"Selected Eon: {spec.selected_point.value.value} J (synthetic)")
        print(f"Source: {spec.selected_point.sources[0].name}")
        print(
            "Coverage:",
            {
                e["rule"]["id"]: e["status"]
                for e in explorer.summary(device_id)["coverage"]["entries"]
            },
        )


if __name__ == "__main__":
    main()
