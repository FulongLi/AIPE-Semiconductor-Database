from pydantic import JsonValue

from .base import Model
from .provenance import ArtifactRef, Provenance


class ModelReference(Model):
    """Opaque adapter metadata belongs here, never in physical characteristics."""

    id: str
    format: str
    provenance: Provenance
    artifact: ArtifactRef | None = None
    adapter_metadata: dict[str, JsonValue] = {}
