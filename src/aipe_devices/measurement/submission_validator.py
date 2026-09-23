import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Literal

from pydantic import Field, ValidationError

from aipe_devices.domain.base import Model
from aipe_devices.domain.measurement import TestCampaign, TestRun
from aipe_devices.domain.provenance import ArtifactRef, Dependency, Source
from aipe_devices.schema.enums import DERIVED_ORIGINS, Lifecycle, Origin
from aipe_devices.schema.validation import ValidationIssue, ValidationReport
from aipe_devices.services.validation import EXPECTED_UNITS

from .request_generator import MeasurementRequest


class MeasurementPackage(Model):
    schema_version: Literal["3.0.0"] = "3.0.0"
    id: str = Field(min_length=1)
    request_id: str = Field(min_length=1)
    device_id: str = Field(min_length=1)
    sources: tuple[Source, ...] = Field(min_length=1)
    campaigns: tuple[TestCampaign, ...] = ()
    runs: tuple[TestRun, ...] = Field(min_length=1)
    artifacts: tuple[ArtifactRef, ...] = ()
    external_dependencies: tuple[Dependency, ...] = ()


def validate_submission(
    package: MeasurementPackage,
    *,
    root: Path | None = None,
    request: MeasurementRequest | None = None,
) -> ValidationReport:
    issues = []

    def issue(code, path, message, severity="error"):
        issues.append(ValidationIssue(code=code, path=path, message=message, severity=severity))

    artifacts = {a.id: a for a in package.artifacts}
    source_ids = {s.id for s in package.sources}
    all_ids = [package.id, *(a.id for a in package.artifacts), *(s.id for s in package.sources)]
    run_ids = {r.id for r in package.runs}
    plan_counts = {i.id: Counter() for i in request.test_plan_items} if request else {}
    for campaign in package.campaigns:
        all_ids.append(campaign.id)
        if not set(campaign.test_run_ids) <= run_ids or campaign.source.id not in source_ids:
            issue("campaign_reference", campaign.id, "Unresolved campaign run/source")
    for run in package.runs:
        all_ids.append(run.id)
        if run.device_id != package.device_id:
            issue("device_reference", run.id, "Run device does not match manifest")
        if not run.physical_sample_id:
            issue("sample_missing", run.id, "Physical sample was not identified", "warning")
        waveforms = {w.id: w for w in run.waveform_refs}
        recipes = {(r.id, r.version): r for r in run.processing_recipes}
        all_ids.extend(waveforms)
        if len(waveforms) != len(run.waveform_refs):
            issue("duplicate_id", run.id, "Duplicate waveform IDs")
        if len(recipes) != len(run.processing_recipes):
            issue("duplicate_recipe", run.id, "Duplicate recipe ID/version")
        known_dependencies = (
            {(w.id, w.version): w.artifact.checksum for w in run.waveform_refs}
            | {(r.id, r.version): None for r in run.processing_recipes}
            | {(d.id, d.version): d.checksum for d in package.external_dependencies}
        )

        def check_dependencies(record):
            for dependency in record.provenance.dependencies:
                pair = (dependency.id, dependency.version)
                if pair not in known_dependencies or dependency.id == record.id:
                    issue("dependency_reference", record.id, f"Unresolved/self dependency {pair}")
                elif (
                    dependency.checksum
                    and known_dependencies[pair]
                    and dependency.checksum != known_dependencies[pair]
                ):
                    issue(
                        "dependency_checksum",
                        record.id,
                        "Dependency checksum differs from waveform",
                    )

        for w in run.waveform_refs:
            check_dependencies(w)
            if w.test_run_id != run.id:
                issue("run_reference", w.id, "Waveform belongs to a different run")
            if artifacts.get(w.artifact.id) != w.artifact:
                issue("artifact_reference", w.id, "Waveform artifact absent or inconsistent")
            if not set(w.provenance.source_ids) <= source_ids:
                issue("source_reference", w.id, "Unresolved waveform source")
            if w.stage == "raw":
                permitted = (
                    w.provenance.origin == Origin.MEASURED
                    and w.provenance.lifecycle == Lifecycle.RAW
                ) or (
                    w.provenance.origin == Origin.SYNTHETIC
                    and w.provenance.lifecycle == Lifecycle.DERIVED
                )
                if not permitted:
                    issue(
                        "waveform_stage",
                        w.id,
                        "Unprocessed waveform requires measured/raw or explicit synthetic/derived provenance",
                    )
            if w.stage == "processed":
                if (w.provenance.recipe_id, w.provenance.recipe_version) not in recipes:
                    issue("recipe_reference", w.id, "Processed waveform recipe missing")
                upstream = {d.id for d in w.provenance.dependencies}
                if not upstream & (waveforms.keys() - {w.id}):
                    issue("waveform_lineage", w.id, "Processed waveform needs an upstream waveform")
        for metrics in run.derived_metrics:
            all_ids.append(metrics.id)
            if metrics.test_run_id != run.id or not set(metrics.waveform_ids) <= waveforms.keys():
                issue("metric_reference", metrics.id, "Unresolved metric run/waveform")
            if (metrics.recipe.id, metrics.recipe.version) not in recipes:
                issue("recipe_reference", metrics.id, "Metric recipe/version missing")
            for m in metrics.metrics:
                check_dependencies(m)
                all_ids.append(m.id)
                if m.provenance.origin not in DERIVED_ORIGINS:
                    issue("metric_origin", m.id, "Processed waveform metric must be derived")
                if not set(m.provenance.source_ids) <= source_ids:
                    issue("source_reference", m.id, "Unresolved metric source")
                if m.quantity.unit in {"J", "C", "s", "Hz"} and m.quantity.value < 0:
                    issue("negative_metric", m.id, "Expected nonnegative metric")
        for result in run.results:
            all_ids.append(result.id)
            check_dependencies(result)
            if (
                result.name in EXPECTED_UNITS
                and result.quantity.unit != EXPECTED_UNITS[result.name]
            ):
                issue(
                    "result_unit",
                    result.id,
                    f"{result.name} requires {EXPECTED_UNITS[result.name]}",
                )
            if not set(result.provenance.source_ids) <= source_ids:
                issue("source_reference", result.id, "Unresolved result source")
            if result.condition != run.condition:
                issue("result_condition", result.id, "Result condition differs from run")
            if (
                result.quantity.unit in {"J", "C", "s", "Hz", "F", "Ohm", "K/W"}
                and result.quantity.value < 0
            ):
                issue("negative_metric", result.id, "Expected nonnegative metric")
        if request is not None:
            matches = [
                (item, item.match(run.protocol, run.condition))
                for item in request.test_plan_items
                if run.test_plan_item_id is None or item.id == run.test_plan_item_id
            ]
            matches = [(item, key) for item, key in matches if key is not None]
            if not matches:
                issue("request_mismatch", run.id, "Protocol/condition was not requested")
            elif len(matches) > 1:
                issue("request_ambiguous", run.id, "Set test_plan_item_id for overlapping items")
            else:
                item, key = matches[0]
                plan_counts[item.id][key] += 1
                names = {m.name for g in run.derived_metrics for m in g.metrics}
                names.update(m.name for m in run.results)
                if not set(item.requested_metrics) <= names:
                    issue("request_metrics", run.id, "Requested item metrics missing")
            if request.physical_sample_id and run.physical_sample_id != request.physical_sample_id:
                issue("request_sample", run.id, "Sample differs from measurement request")
    if len(all_ids) != len(set(all_ids)):
        issue("duplicate_id", "manifest", "Submission IDs must be unique")
    if request is not None:
        if package.request_id != request.id or package.device_id != request.device_id:
            issue("request_reference", package.id, "Submission does not match request")
        for item in request.test_plan_items:
            counts = plan_counts[item.id]
            if item.draft:
                issue("request_draft", item.id, "Draft plan requires engineering review")
            if len(counts) != item.point_count or any(
                n < item.repetitions for n in counts.values()
            ):
                issue("request_coverage", item.id, "Requested item points/repetitions missing")
    if root is not None:
        root = Path(root).resolve()
        for artifact in package.artifacts:
            candidate = (root / artifact.uri).resolve()
            if Path(artifact.uri).is_absolute() or not candidate.is_relative_to(root):
                issue("artifact_path", artifact.id, "Artifact URI must stay inside package")
                continue
            try:
                content = candidate.read_bytes()
                if (
                    len(content) != artifact.size
                    or hashlib.sha256(content).hexdigest() != artifact.checksum
                ):
                    issue("artifact_integrity", artifact.id, "Checksum/size mismatch")
            except OSError as exc:
                issue("artifact_missing", artifact.id, str(exc))
    return ValidationReport(issues=tuple(issues))


def validate_package_file(
    path: str | Path, *, request: MeasurementRequest | None = None
) -> ValidationReport:
    path = Path(path)
    try:
        package = MeasurementPackage.model_validate(json.loads(path.read_bytes()))
    except (ValidationError, ValueError, OSError) as exc:
        return ValidationReport(
            issues=(
                ValidationIssue(severity="error", code="schema", path=str(path), message=str(exc)),
            )
        )
    return validate_submission(package, root=path.parent, request=request)
