"""Content-addressed local storage; callers depend only on ArtifactStore."""

import hashlib
import os
import re
import tempfile
from pathlib import Path
from typing import Protocol

from aipe_devices.domain.provenance import ArtifactRef


class ArtifactStore(Protocol):
    def put(self, data: bytes, *, format: str) -> ArtifactRef: ...
    def get(self, artifact: ArtifactRef) -> bytes: ...
    def exists(self, artifact: ArtifactRef) -> bool: ...
    def metadata(self, artifact: ArtifactRef) -> ArtifactRef: ...
    def checksum(self, artifact: ArtifactRef) -> str: ...


def atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(dir=path.parent, prefix=".aipe-")
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


class LocalArtifactStore:
    def __init__(self, root: str | Path):
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, artifact: ArtifactRef) -> Path:
        if artifact.uri != f"sha256:{artifact.checksum}":
            raise ValueError("Local store expects a sha256 URI")
        return self.root / artifact.checksum[:2] / artifact.checksum

    def put(self, data: bytes, *, format: str) -> ArtifactRef:
        digest = hashlib.sha256(data).hexdigest()
        ref = ArtifactRef(
            id=digest, uri=f"sha256:{digest}", checksum=digest, format=format, size=len(data)
        )
        path = self._path(ref)
        if path.exists():
            self.get(ref)
        else:
            atomic_write(path, data)
        return ref

    def get(self, artifact: ArtifactRef) -> bytes:
        data = self._path(artifact).read_bytes()
        if len(data) != artifact.size or hashlib.sha256(data).hexdigest() != artifact.checksum:
            raise ValueError("Artifact integrity check failed")
        return data

    def exists(self, artifact: ArtifactRef) -> bool:
        return self._path(artifact).is_file()

    def metadata(self, artifact: ArtifactRef) -> ArtifactRef:
        self.get(artifact)
        return artifact

    def checksum(self, artifact: ArtifactRef) -> str:
        return hashlib.sha256(self.get(artifact)).hexdigest()


def safe_identifier(value: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", value):
        raise ValueError("Unsafe identifier")
    return value
