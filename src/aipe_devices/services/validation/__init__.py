"""Non-mutating engineering and reference checks, separate from shape validation."""

from aipe_devices.domain.device import CHARACTERISTICS, PowerSemiconductorDevice
from aipe_devices.schema.enums import Origin
from aipe_devices.schema.validation import ValidationIssue, ValidationReport

EXPECTED_UNITS = {
    "td_on": "s",
    "td_off": "s",
    "tr": "s",
    "tf": "s",
    "dv_dt": "V/s",
    "di_dt": "A/s",
    "Eon": "J",
    "Eoff": "J",
    "Err": "J",
    "voltage_drop": "V",
    "rds_on": "Ohm",
    "vds_max": "V",
    "id_max": "A",
    "tj_max": "K",
    "pd_max": "W",
    "qg_total": "C",
    "ciss": "F",
    "coss": "F",
    "crss": "F",
    "Eoss": "J",
}
AXIS_UNITS = {
    "junction_temperature": "K",
    "current": "A",
    "dc_bus_voltage": "V",
    "gate_resistance_on": "Ohm",
    "gate_resistance_off": "Ohm",
    "time": "s",
    "drain_source_voltage": "V",
}


def records(device):
    yield from device.ratings
    yield from device.package.parasitics
    for name in CHARACTERISTICS:
        data = getattr(device, name)
        yield from data.scalars
        yield from data.curves
    yield from device.thermal
    yield from device.models
    for item in device.reliability:
        yield item
        yield from item.metrics


def validate_device(device: PowerSemiconductorDevice) -> ValidationReport:
    issues = []

    def issue(code, path, message, severity="error"):
        issues.append(ValidationIssue(severity=severity, code=code, path=path, message=message))

    source_ids = [s.id for s in device.provenance]
    if len(set(source_ids)) != len(source_ids):
        issue("duplicate_source", "provenance", "Source IDs must be unique")
    ids = set()
    for record in records(device):
        if record.id in ids:
            issue("duplicate_id", record.id, "Record IDs must be unique within device")
        ids.add(record.id)
        for source_id in record.provenance.source_ids:
            if source_id not in source_ids:
                issue("missing_source", record.id, f"Unresolved source {source_id}")
        if record.provenance.origin == Origin.MEASURED and not device.measurement_ids:
            issue(
                "measurement_context", record.id, "Measured data lacks a test reference", "warning"
            )
        if hasattr(record, "name"):
            unit = record.unit if hasattr(record, "unit") else record.quantity.unit
            if record.name in EXPECTED_UNITS and unit != EXPECTED_UNITS[record.name]:
                issue("unit", record.id, f"{record.name} requires {EXPECTED_UNITS[record.name]}")
            if (
                hasattr(record, "quantity")
                and unit in {"J", "F", "Ohm"}
                and record.quantity.value < 0
            ):
                issue(
                    "negative_characteristic", record.id, "Negative energy/capacitance/resistance"
                )
        if hasattr(record, "axes"):
            for axis in record.axes:
                if any(b < a for a, b in zip(axis.values, axis.values[1:])):
                    issue("axis_monotonic", record.id, f"{axis.name} is not strictly increasing")
                if len(set(axis.values)) != len(axis.values):
                    severity = "warning" if record.provenance.origin == Origin.MODEL else "error"
                    issue(
                        "duplicate_axis",
                        record.id,
                        f"{axis.name} contains duplicate source coordinates; ambiguous for interpolation",
                        severity,
                    )
                if axis.name in AXIS_UNITS and axis.unit != AXIS_UNITS[axis.name]:
                    issue("axis_unit", record.id, f"Invalid unit for {axis.name}")
                if axis.unit == "K" and min(axis.values) < 0:
                    issue("temperature", record.id, "Negative absolute temperature")
                if axis.name == "junction_temperature" and max(axis.values) > 773.15:
                    issue(
                        "source_temperature",
                        record.id,
                        "Source includes >500 C model points; retained, not operating ratings",
                        "warning",
                    )
            if record.unit in {"J", "F", "Ohm"} and min(record.values) < 0:
                issue(
                    "negative_characteristic", record.id, "Negative energy/capacitance/resistance"
                )
        if record in device.ratings and record.quantity.value <= 0:
            issue("rating", record.id, "Maximum device ratings must be positive")
    component_ids = {c.id for c in device.package.components}
    if len(component_ids) != len(device.package.components):
        issue("duplicate_component", "package", "Component IDs must be unique")
    for c in device.package.thermal_coupling:
        if c.from_component not in component_ids or c.to_component not in component_ids:
            issue("component_reference", "package", "Unresolved thermal coupling component")
        if c.thermal_model_id not in {t.id for t in device.thermal}:
            issue("thermal_reference", "package", "Unresolved thermal model")
    return ValidationReport(issues=tuple(issues))
