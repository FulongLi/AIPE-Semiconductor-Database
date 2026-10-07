"""Conservative identity/source projection to AIPE Core Engineering State 0.1.0."""

from datetime import datetime
from hashlib import sha256
from urllib.parse import urlsplit

from aipe_devices import __version__
from aipe_devices.domain.device import PowerSemiconductorDevice
from aipe_devices.schema.enums import Technology
from aipe_devices.services.validation import validate_device

_TECHNOLOGY = {
    Technology.SI_MOSFET: "Si",
    Technology.SIC_MOSFET: "SiC",
    Technology.GAN: "GaN",
    # IGBT and diode are device structures, not sufficient material evidence.
    Technology.IGBT: "unspecified",
    Technology.DIODE: "unspecified",
    Technology.UNKNOWN: "unspecified",
}


def export_core_candidate(
    device: PowerSemiconductorDevice,
    *,
    role: str,
    record_uri: str,
    exported_at: datetime,
) -> dict:
    """Return component/evidence to append to a reviewed state; never mutate it.

    ``record_uri`` must identify the source revision (a pinned repository URL or
    domain URN). The caller supplies the actual export timestamp. No suitability,
    rated limits, losses or physical validation are inferred by this projection.
    """
    validate_device(device).raise_for_errors()
    if not role.strip():
        raise ValueError("A nonempty engineering role is required")
    if (
        not urlsplit(record_uri).scheme
        or any(char.isspace() for char in record_uri)
        or not record_uri
    ):
        raise ValueError("record_uri must be an absolute URI identifying the record revision")
    if exported_at.tzinfo is None or exported_at.utcoffset() is None:
        raise ValueError("exported_at must include a timezone")
    key = sha256(f"{device.device_id}:{device.revision}".encode()).hexdigest()
    evidence_id = f"evidence.device-{key}"
    return {
        "component": {
            "id": f"device.{key}",
            "role": role,
            "selection_status": "candidate",
            "technology": _TECHNOLOGY[device.classification.technology],
            "manufacturer": device.identity.manufacturer,
            "part_number": device.identity.part_number,
            "database_ref": record_uri,
            "evidence_refs": [evidence_id],
            "extensions": {
                "aipe.semiconductor": {
                    "schema_version": device.schema_version,
                    "device_id": device.device_id,
                    "revision": device.revision,
                }
            },
        },
        "evidence": {
            "id": evidence_id,
            "kind": "source",
            "description": (
                "Candidate identity from a canonical semiconductor record. This export "
                "does not establish ratings, design suitability or measured performance."
            ),
            "source": {
                "type": "repository",
                "reference": record_uri,
                "locator": f"device_id={device.device_id}; revision={device.revision}",
            },
            "provenance": {
                "created_at": exported_at.isoformat(),
                "activity": "Project V3 device identity to Core v0.1 candidate metadata",
                "inputs": [],
                "tool": {"id": "aipe.semiconductor-database", "version": __version__},
            },
            "artifacts": [{"uri": record_uri, "media_type": "application/json"}],
            "review_status": "unreviewed",
        },
    }
