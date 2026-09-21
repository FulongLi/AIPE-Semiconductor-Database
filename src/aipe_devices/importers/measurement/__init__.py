from pathlib import Path

from aipe_devices.measurement.submission_validator import MeasurementPackage, validate_package_file


class MeasurementPackageImporter:
    def load(self, path: str | Path) -> MeasurementPackage:
        path = Path(path)
        validate_package_file(path).raise_for_errors()
        return MeasurementPackage.model_validate_json(path.read_bytes())
