from pathlib import Path

from aipe_devices.services.validation import validate_device


class MatlabExporter:
    def export(self, device, path: str | Path) -> Path:
        """MAT structure mirrors V3. Missing optional values become empty MATLAB arrays."""
        try:
            from scipy.io import savemat
        except ImportError as exc:
            raise ImportError("Install aipe-devices[matlab] for MAT export") from exc
        validate_device(device).raise_for_errors()

        def clean(value):
            if value is None:
                return []
            if isinstance(value, dict):
                return {key: clean(item) for key, item in value.items()}
            if isinstance(value, list):
                return [clean(item) for item in value]
            return value

        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        # JSON copy preserves null/empty distinctions and arbitrary adapter metadata keys.
        savemat(
            path,
            {
                "device": clean(device.model_dump(mode="json")),
                "canonical_json": device.model_dump_json(),
            },
            long_field_names=True,
        )
        return path
