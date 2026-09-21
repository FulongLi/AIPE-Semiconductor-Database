from typing import Protocol

from aipe_devices.domain.measurement import DynamicMetrics, ProcessingRecipe, TestRun
from aipe_devices.storage.artifact_store import ArtifactStore


class WaveformProcessor(Protocol):
    """Future implementation reads artifact bytes and returns small traceable metrics."""

    def process(
        self, run: TestRun, recipe: ProcessingRecipe, store: ArtifactStore
    ) -> DynamicMetrics: ...
