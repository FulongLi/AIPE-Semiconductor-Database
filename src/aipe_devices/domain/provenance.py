from typing import Literal

from pydantic import Field, model_validator

from aipe_devices.schema.enums import DERIVED_ORIGINS, Freshness, Lifecycle, Origin

from .base import Model


class AccessMetadata(Model):
    license: str | None = None
    redistribution_allowed: bool | None = None
    commercial_use_allowed: bool | None = None
    visibility: Literal["public", "partner", "private", "unknown"] = "unknown"
    owner: str | None = None
    category: Literal["manufacturer", "aipe", "partner", "licensed", "customer", "unknown"] = (
        "unknown"
    )


class ArtifactRef(Model):
    id: str = Field(min_length=1)
    uri: str = Field(min_length=1)
    checksum: str = Field(pattern=r"^[0-9a-f]{64}$")
    format: str = Field(min_length=1)
    size: int = Field(ge=0)


class Source(Model):
    id: str = Field(min_length=1)
    kind: Literal[
        "manufacturer",
        "laboratory",
        "test_partner",
        "paper",
        "AIPE",
        "simulation_model",
        "distributor",
    ]
    name: str = Field(min_length=1)
    artifact: ArtifactRef | None = None
    url: str | None = None
    access: AccessMetadata = AccessMetadata()


class Dependency(Model):
    id: str = Field(min_length=1)
    version: str = Field(min_length=1)
    checksum: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")


class Provenance(Model):
    origin: Origin
    source_ids: tuple[str, ...] = Field(min_length=1)
    lifecycle: Lifecycle = Lifecycle.CANONICAL
    dependencies: tuple[Dependency, ...] = ()
    recipe_id: str | None = None
    recipe_version: str | None = None
    freshness: Freshness = Freshness.CURRENT

    @model_validator(mode="after")
    def lineage_required(self):
        if self.origin in DERIVED_ORIGINS:
            if not self.dependencies:
                raise ValueError("Derived/estimated records require upstream dependencies")
            if self.lifecycle not in {Lifecycle.DERIVED, Lifecycle.APPLICATION_VIEW}:
                raise ValueError("Derived/estimated data must remain in the derived lifecycle")
        if (self.recipe_id is None) != (self.recipe_version is None):
            raise ValueError("Recipe ID and version must be supplied together")
        return self
