import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from aipe_devices.domain.provenance import ImportMetadata
from aipe_devices.normalizers.units import normalize
from aipe_devices.schema.enums import Origin
from aipe_devices.services.coverage.gaps import coverage_gaps
from aipe_devices.services.validation import records, validate_device

from .construction import build_device
from .mapping import map_table
from .models import ImportReport, ImportSession, UnitMapping
from .parsers import CanonicalJsonImporter, CsvImporter, ExcelImporter, GenericJsonImporter

IMPORTER_VERSION = "2.0.0"


class LibraryImporter:
    def inspect(
        self, path, *, mappings=None, identity=None, origin=Origin.UNKNOWN
    ) -> ImportSession:
        path = Path(path)
        format = path.suffix.lower().lstrip(".")
        tables, table_mappings, warnings, errors, conversions = [], [], [], [], []
        candidate = metadata = validation = coverage = None
        try:
            if format not in {"xlsx", "csv", "json"}:
                raise ValueError("Supported import formats: .json, .xlsx, .csv")
            content = path.read_bytes()
            metadata = ImportMetadata(
                source_type=format,
                original_filename=path.name,
                source_sha256=hashlib.sha256(content).hexdigest(),
                import_timestamp=datetime.now(timezone.utc),
                importer_version=IMPORTER_VERSION,
            )
            if mappings is not None and not isinstance(mappings, dict):
                raise ValueError("Mappings must be a column-to-semantic object")
            if identity is not None and not isinstance(identity, dict):
                raise ValueError("Identity must be an object")
            canonical = False
            if format == "json":
                payload = json.loads(content)
                # A claimed canonical document must fail loudly instead of silently losing fields.
                canonical = isinstance(payload, dict) and "schema_version" in payload
                if not canonical:
                    try:
                        candidate, validation = CanonicalJsonImporter().load(content)
                        canonical = True
                    except ValueError:
                        pass
            if canonical:
                candidate, validation = CanonicalJsonImporter().load(content)
                if mappings or identity or origin != Origin.UNKNOWN:
                    raise ValueError(
                        "Canonical JSON bypasses remapping; do not supply tabular overrides"
                    )
            else:
                parser = {"csv": CsvImporter, "xlsx": ExcelImporter, "json": GenericJsonImporter}[
                    format
                ]()
                tables = parser.parse(content, mappings)
                for table in tables:
                    mapped = map_table(table.info, mappings)
                    columns = mapped.columns
                    table_mappings.append(mapped)
                    if not table.info.row_count:
                        warnings.append(f"{table.info.name}: empty table")
                    for column in columns:
                        if (
                            column.unit
                            and column.status in {"confirmed", "high_confidence"}
                            and not column.ignored
                        ):
                            conversions.append(
                                UnitMapping(
                                    source=column.unit, target=normalize(1, column.unit).unit
                                )
                            )
                candidate = build_device(
                    tables, table_mappings, metadata, identity, Origin(origin), warnings, errors
                )
                del content  # Transient bytes only; caller's original file is never removed.
                if candidate:
                    validation = validate_device(candidate)
            if candidate:
                coverage = coverage_gaps(candidate)
            if validation:
                warnings.extend(i.message for i in validation.issues if i.severity == "warning")
                errors.extend(i.message for i in validation.issues if i.severity == "error")
        except (ValueError, TypeError, OSError, KeyError) as exc:
            errors.append(str(exc))
        unresolved = tuple(
            c
            for t in table_mappings
            for c in t.columns
            if c.status in {"unresolved", "needs_confirmation"}
        )
        status = "failed" if errors else ("needs_confirmation" if unresolved else "ready_to_import")
        if not candidate and not errors:
            status = "failed"
            errors.append("No canonical device candidate")
        partial = not coverage or any(
            e.status not in {"available", "not_applicable"} for e in coverage.entries
        )
        if status == "ready_to_import" and partial:
            status = "partial"
        conversions = tuple(dict.fromkeys(conversions))
        history = ("parsed",) if metadata else ()
        if validation and validation.valid:
            history += ("validated",)
        history += (status,)
        report = ImportReport(
            input_format=format,
            source_metadata=metadata,
            detected_tables=tuple(t.info for t in tables),
            recognized_columns=tuple(
                c
                for t in table_mappings
                for c in t.columns
                if c.status in {"confirmed", "high_confidence"}
            ),
            unresolved_columns=unresolved,
            unit_conversions=conversions,
            records_created=sum(1 for _ in records(candidate)) if candidate else 0,
            warnings=tuple(dict.fromkeys(warnings)),
            errors=tuple(errors),
            device_identity_status="conflicting"
            if any("Conflicting identity" in e for e in errors)
            else ("available" if candidate else "missing"),
            validation_result=validation,
            coverage_summary=coverage,
            final_status=status,
            dataset_status="partial" if partial else "complete",
        )
        return ImportSession(
            id=str(uuid4()),
            input_format=format,
            source_metadata=metadata,
            detected_tables=report.detected_tables,
            mappings=tuple(table_mappings),
            transformations=conversions,
            warnings=report.warnings,
            unresolved_fields=unresolved,
            canonical_candidate=candidate,
            validation_report=validation,
            coverage_report=coverage,
            status=status,
            history=history,
            report=report,
        )

    def save(self, session: ImportSession, repository) -> ImportSession:
        """Only an acceptable candidate is persisted; conflicts become import reports."""
        if (
            session.status not in {"partial", "ready_to_import"}
            or session.unresolved_fields
            or session.report.errors
        ):
            return session
        try:
            if session.canonical_candidate is None:
                raise ValueError("Missing canonical candidate")
            validate_device(session.canonical_candidate).raise_for_errors()
            repository.save(session.canonical_candidate)
        except (ValueError, OSError, RuntimeError) as exc:
            report = session.report.model_copy(
                update={"final_status": "failed", "errors": (*session.report.errors, str(exc))}
            )
            return session.model_copy(
                update={
                    "status": "failed",
                    "report": report,
                    "history": (*session.history, "failed"),
                }
            )
        output = (
            str(repository.root / f"{session.canonical_candidate.device_id}.json")
            if hasattr(repository, "root")
            else session.canonical_candidate.device_id
        )
        report = session.report.model_copy(
            update={"final_status": "imported", "canonical_output": output}
        )
        return session.model_copy(
            update={
                "status": "imported",
                "report": report,
                "history": (*session.history, "imported"),
            }
        )
