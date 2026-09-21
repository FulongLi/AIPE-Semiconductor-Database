from typing import Literal

from .base import Model
from .curves import ScalarRecord
from .provenance import Provenance


class ReliabilityRecord(Model):
    id: str
    category: Literal[
        "power_cycling",
        "thermal_cycling",
        "HTRB",
        "HTGB",
        "short_circuit",
        "avalanche",
        "aging_drift",
        "failure_rate",
        "mission_profile_lifetime",
    ]
    provenance: Provenance
    protocol_id: str | None = None
    metrics: tuple[ScalarRecord, ...] = ()
    test_run_ids: tuple[str, ...] = ()
