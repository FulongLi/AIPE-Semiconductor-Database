from typing import Literal, Protocol

from aipe_devices.domain.base import Model
from aipe_devices.domain.device import PowerSemiconductorDevice
from aipe_devices.domain.provenance import ImportMetadata
from aipe_devices.schema.validation import ValidationReport
from aipe_devices.services.coverage.gaps import CoverageGapReport

MappingStatus = Literal["confirmed", "high_confidence", "needs_confirmation", "unresolved"]
ImportStatus = Literal[
    "parsed", "needs_confirmation", "validated", "partial", "ready_to_import", "imported", "failed"
]


class UnitMapping(Model):
    source: str
    target: str


class ColumnMapping(Model):
    table: str
    column: str
    semantic: str | None = None
    unit: str | None = None
    status: MappingStatus = "unresolved"
    ignored: bool = False
    reason: str | None = None


class TableMapping(Model):
    table: str
    columns: tuple[ColumnMapping, ...]


class DetectedTable(Model):
    name: str
    header_row: int
    columns: tuple[str, ...]
    row_count: int


class ImportReport(Model):
    input_format: str
    source_metadata: ImportMetadata | None = None
    detected_tables: tuple[DetectedTable, ...] = ()
    recognized_columns: tuple[ColumnMapping, ...] = ()
    unresolved_columns: tuple[ColumnMapping, ...] = ()
    unit_conversions: tuple[UnitMapping, ...] = ()
    records_created: int = 0
    warnings: tuple[str, ...] = ()
    errors: tuple[str, ...] = ()
    device_identity_status: Literal["available", "missing", "conflicting"] = "missing"
    validation_result: ValidationReport | None = None
    coverage_summary: CoverageGapReport | None = None
    final_status: ImportStatus
    dataset_status: Literal["complete", "partial"] = "partial"
    canonical_output: str | None = None


class ImportSession(Model):
    id: str
    input_format: str
    source_metadata: ImportMetadata | None = None
    detected_tables: tuple[DetectedTable, ...] = ()
    mappings: tuple[TableMapping, ...] = ()
    transformations: tuple[UnitMapping, ...] = ()
    warnings: tuple[str, ...] = ()
    unresolved_fields: tuple[ColumnMapping, ...] = ()
    canonical_candidate: PowerSemiconductorDevice | None = None
    validation_report: ValidationReport | None = None
    coverage_report: CoverageGapReport | None = None
    status: ImportStatus
    history: tuple[ImportStatus, ...] = ()
    report: ImportReport


class MappingSuggestion(Model):
    """Suggestions cannot be passed as accepted ColumnMappings implicitly."""

    table: str
    column: str
    suggested_semantic: str
    rationale: str


class MappingAssistant(Protocol):
    def suggest(self, tables: tuple[DetectedTable, ...]) -> tuple[MappingSuggestion, ...]: ...
