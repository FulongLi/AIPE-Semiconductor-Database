"""Deterministic evidence rules, separate from human/agent explanations."""

from typing import Literal, Protocol

from aipe_devices.domain.base import Model
from aipe_devices.domain.device import CHARACTERISTICS, PowerSemiconductorDevice
from aipe_devices.schema.enums import Availability, Freshness


class CoverageRule(Model):
    id: str
    group: str
    metrics: tuple[str, ...] = ()
    importance: Literal["required", "recommended", "optional"] = "optional"
    check: Literal["presence", "high_temperature", "gate_resistance"] = "presence"
    temperatures_kelvin: tuple[float, ...] = ()


class CoveragePolicy(Protocol):
    name: str
    rules: tuple[CoverageRule, ...]


class GenericDeviceStoragePolicy:
    name = "generic_device_storage"
    rules = (CoverageRule(id="identity", group="identity", importance="required"),) + tuple(
        CoverageRule(id=g, group=g)
        for g in (*CHARACTERISTICS, "thermal", "reliability", "dynamic_test", "market", "models")
    )


class DABLossEvaluationPolicy:
    name = "dab_loss_foundation"
    rules = (
        CoverageRule(id="identity", group="identity", importance="required"),
        CoverageRule(id="conduction", group="conduction", importance="required"),
        CoverageRule(id="Eon", group="switching", metrics=("Eon",), importance="required"),
        CoverageRule(id="Eoff", group="switching", metrics=("Eoff",), importance="required"),
        CoverageRule(id="thermal", group="thermal", importance="required"),
        CoverageRule(
            id="output_capacitance",
            group="capacitance",
            metrics=("coss", "Eoss"),
            importance="recommended",
        ),
        CoverageRule(id="reverse_conduction", group="reverse_conduction", importance="recommended"),
        CoverageRule(
            id="high_temperature_Eon",
            group="switching",
            metrics=("Eon",),
            importance="recommended",
            check="high_temperature",
            temperatures_kelvin=(398.15, 423.15),
        ),
        CoverageRule(
            id="high_temperature_Eoff",
            group="switching",
            metrics=("Eoff",),
            importance="recommended",
            check="high_temperature",
            temperatures_kelvin=(398.15, 423.15),
        ),
        CoverageRule(
            id="rg_dependence_Eon",
            group="switching",
            metrics=("Eon",),
            importance="recommended",
            check="gate_resistance",
        ),
        CoverageRule(
            id="rg_dependence_Eoff",
            group="switching",
            metrics=("Eoff",),
            importance="recommended",
            check="gate_resistance",
        ),
    )


class CoverageGap(Model):
    rule: CoverageRule
    status: Availability
    evidence_ids: tuple[str, ...] = ()
    message: str


class CoverageGapReport(Model):
    device_id: str
    policy: str
    entries: tuple[CoverageGap, ...]
    acceptable: bool
    scope: str = (
        "Evidence checks only; no operating-envelope, safety, or converter sufficiency claim."
    )


def _coordinates(record, parameter):
    for axis in getattr(record, "axes", ()):
        if axis.name == parameter:
            return set(axis.values)
    q = getattr(getattr(record, "condition", None), parameter, None)
    return {q.value} if q else set()


def assess_rule(device, rule):
    group = rule.group
    if group == "identity":
        return Availability.AVAILABLE, (), "Required device identity is present"
    if group in CHARACTERISTICS:
        data = getattr(device, group)
        if data.availability == Availability.NOT_APPLICABLE:
            return Availability.NOT_APPLICABLE, (), "Explicitly not applicable"
        all_records = (*data.scalars, *data.curves)
        records = [r for r in all_records if r.provenance.freshness != Freshness.STALE]
        if rule.metrics:
            records = [r for r in records if r.name in rule.metrics]
        ids = tuple(r.id for r in records)
        if not records:
            status = data.availability
            if (
                all_records
                or rule.metrics
                or status in {Availability.AVAILABLE, Availability.PARTIAL}
            ):
                status = Availability.MISSING
            return status, (), "No current matching evidence"
        if rule.check == "high_temperature":
            present = set().union(*(_coordinates(r, "junction_temperature") for r in records))
            covered = set(rule.temperatures_kelvin) & present
            status = (
                Availability.AVAILABLE
                if set(rule.temperatures_kelvin) <= present
                else (Availability.PARTIAL if covered else Availability.MISSING)
            )
            return (
                status,
                ids,
                f"Requested temperature points (K): {rule.temperatures_kelvin}; found: {sorted(present)}",
            )
        if rule.check == "gate_resistance":
            parameter = "gate_resistance_on" if rule.metrics == ("Eon",) else "gate_resistance_off"
            # A sweep must occur within one record; unrelated conditions do not form a sweep.
            present = any(len(_coordinates(r, parameter)) >= 2 for r in records)
            return (
                (Availability.AVAILABLE if present else Availability.MISSING),
                ids,
                f"Requires >=2 {parameter} points in one record",
            )
        partial = (
            data.availability == Availability.PARTIAL
            and not rule.metrics
            or len(records) < len(all_records)
            and not rule.metrics
        )
        if (
            group == "switching"
            and not rule.metrics
            and not {"Eon", "Eoff"} <= {r.name for r in records}
        ):
            partial = True
        if any(r.quality.flags for r in records):
            partial = True
        return (
            (Availability.PARTIAL if partial else Availability.AVAILABLE),
            ids,
            "Matching current evidence present",
        )
    attribute = {"dynamic_test": "measurement_ids", "market": "market_reference_ids"}.get(
        group, group
    )
    records = getattr(device, attribute)
    if group in {"dynamic_test", "market"}:
        # IDs indicate linked evidence, not validated payload availability.
        return (
            (Availability.PARTIAL if records else Availability.UNKNOWN),
            tuple(records),
            "External references only; inspect linked records",
        )
    current = [r for r in records if r.provenance.freshness != Freshness.STALE]
    status = (
        Availability.AVAILABLE
        if current
        else (Availability.MISSING if group == "thermal" or records else Availability.UNKNOWN)
    )
    return (
        status,
        tuple(r.id for r in current),
        "Current records present" if current else "No current records",
    )


def coverage_gaps(device: PowerSemiconductorDevice, policy: CoveragePolicy | None = None):
    policy = policy or GenericDeviceStoragePolicy()
    entries = []
    for rule in policy.rules:
        status, ids, message = assess_rule(device, rule)
        entries.append(CoverageGap(rule=rule, status=status, evidence_ids=ids, message=message))
    return CoverageGapReport(
        device_id=device.device_id,
        policy=policy.name,
        entries=tuple(entries),
        acceptable=all(
            e.status == Availability.AVAILABLE for e in entries if e.rule.importance == "required"
        ),
    )


def explanation_input(report: CoverageGapReport) -> dict:
    """Only engine findings are supplied to an optional explanation agent."""
    return {
        "scope": report.scope,
        "policy": report.policy,
        "findings": [
            e.model_dump(mode="json")
            for e in report.entries
            if e.status not in {Availability.AVAILABLE, Availability.NOT_APPLICABLE}
        ],
    }
