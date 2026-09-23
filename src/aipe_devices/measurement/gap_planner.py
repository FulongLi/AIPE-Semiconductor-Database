"""Reviewable drafts only. No inferred voltages, currents, or laboratory commands."""

from aipe_devices.domain.measurement import MeasurementProtocol
from aipe_devices.schema.enums import Availability
from aipe_devices.services.coverage.gaps import CoverageGapReport

from .plans import SweepAxis, TestPlanItem
from .request_generator import generate_request

PROTOCOLS = {
    "conduction": ("AIPE-STATIC", "static_conduction", ("voltage_drop",)),
    "switching": ("AIPE-DPT", "dpt", ("Eon", "Eoff")),
    "capacitance": ("AIPE-CAP", "capacitance", ("coss",)),
    "reverse_conduction": ("AIPE-REVERSE", "reverse_conduction", ("voltage_drop",)),
    "thermal": ("AIPE-THERMAL", "thermal", ("thermal_impedance",)),
    "gate_charge": ("AIPE-GATE", "gate_charge", ("qg_total",)),
}


def draft_measurement_request(report: CoverageGapReport):
    items = []
    for gap in report.entries:
        rule = gap.rule
        if (
            gap.status in {Availability.AVAILABLE, Availability.NOT_APPLICABLE}
            or rule.group not in PROTOCOLS
        ):
            continue
        protocol, category, metrics = PROTOCOLS[rule.group]
        axes = ()
        if rule.check == "high_temperature":
            axes = (
                SweepAxis(
                    parameter="junction_temperature", unit="K", values=rule.temperatures_kelvin
                ),
            )
        items.append(
            TestPlanItem(
                id=f"gap-{rule.id}",
                protocol=MeasurementProtocol(id=protocol, version="1.0", category=category),
                sweep_axes=axes,
                requested_metrics=rule.metrics if len(rule.metrics) == 1 else metrics,
                notes=f"Policy {report.policy}, rule {rule.id}: {gap.message}",
                draft=True,
                requirements=(
                    "Review protocol definition, safe operating conditions, sample, and repetitions before testing.",
                )
                + (
                    ("Specify gate-resistance sweep values.",)
                    if rule.check == "gate_resistance"
                    else ()
                ),
            )
        )
    return generate_request(device_id=report.device_id, test_plan_items=items) if items else None
