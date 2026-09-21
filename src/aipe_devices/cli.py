import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path

from aipe_devices.importers.plecs import PlecsImporter
from aipe_devices.measurement.submission_validator import validate_package_file
from aipe_devices.repository.json_repository import JsonDeviceRepository
from aipe_devices.schema.enums import Technology
from aipe_devices.services.validation import validate_device
from aipe_devices.storage.artifact_store import atomic_write


def import_wolfspeed(raw_root, repository_root):
    """Explicit source-catalogue classification; XML itself does not identify SiC or module topology."""
    raw_root = Path(raw_root)
    repository = JsonDeviceRepository(repository_root)
    entries = []
    for path in sorted(raw_root.rglob("*.xml")):
        relative = path.relative_to(raw_root)
        integration = "module" if "Modules" in path.parts else "discrete"
        device = PlecsImporter().load(
            path,
            technology=Technology.SIC_MOSFET,
            integration=integration,
            source_uri=f"raw:wolfspeed/{relative.as_posix()}",
        )
        report = validate_device(device)
        report.raise_for_errors()
        if device.device_id in repository.list():
            if repository.get(device.device_id) != device:
                raise ValueError(f"Existing canonical record differs: {device.device_id}")
        else:
            repository.save(device)
        entries.append(
            {
                "device_id": device.device_id,
                "raw_path": relative.as_posix(),
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                "integration": integration,
                "curves": sum(
                    len(getattr(device, n).curves)
                    for n in ["switching", "conduction", "reverse_conduction"]
                ),
                "custom_tables": len(device.models[0].adapter_metadata["custom_tables"]),
                "issues": [i.model_dump() for i in report.issues],
            }
        )
    return {
        "schema_version": "3.0.0",
        "devices": len(entries),
        "integration": dict(Counter(e["integration"] for e in entries)),
        "custom_tables": sum(e["custom_tables"] for e in entries),
        "warning_counts": dict(Counter(i["code"] for e in entries for i in e["issues"])),
        "entries": entries,
    }


def main():
    parser = argparse.ArgumentParser(description="AIPE V3 data tools")
    commands = parser.add_subparsers(dest="command", required=True)
    importer = commands.add_parser(
        "import-wolfspeed", help="Import preserved Wolfspeed source catalogue"
    )
    importer.add_argument("raw_root", type=Path)
    importer.add_argument("repository", type=Path)
    importer.add_argument("--report", type=Path, required=True)
    validator = commands.add_parser("validate-package")
    validator.add_argument("manifest", type=Path)
    migration = commands.add_parser("migrate-legacy")
    migration.add_argument("version", choices=["v1", "v2"])
    migration.add_argument("source", type=Path)
    migration.add_argument("repository", type=Path)
    args = parser.parse_args()
    if args.command == "import-wolfspeed":
        report = import_wolfspeed(args.raw_root, args.repository)
        atomic_write(args.report, (json.dumps(report, indent=2) + "\n").encode())
        print(f"Imported/verified {report['devices']} devices; report: {args.report}")
    elif args.command == "validate-package":
        report = validate_package_file(args.manifest)
        print(report.model_dump_json(indent=2))
        raise SystemExit(0 if report.valid else 1)
    elif args.command == "migrate-legacy":
        from aipe_devices.migration.v1_to_v3 import load as load_v1
        from aipe_devices.migration.v2_to_v3 import load as load_v2

        loader = load_v1 if args.version == "v1" else load_v2
        repository = JsonDeviceRepository(args.repository)
        for path in sorted(args.source.glob("*.json")):
            repository.save(loader(path))


if __name__ == "__main__":
    main()
