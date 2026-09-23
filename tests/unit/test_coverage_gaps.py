from aipe_devices.domain.curves import CharacteristicData
from aipe_devices.domain.device import PowerSemiconductorDevice
from aipe_devices.domain.identity import DeviceIdentity
from aipe_devices.domain.provenance import Source
from aipe_devices.measurement.gap_planner import draft_measurement_request
from aipe_devices.services.coverage import CoverageAnalyzer
from aipe_devices.services.coverage.gaps import DABLossEvaluationPolicy, explanation_input


def test_storage_acceptable_dab_insufficient():
    device = PowerSemiconductorDevice(
        device_id="synthetic",
        identity=DeviceIdentity(manufacturer="Example", part_number="Synthetic"),
        provenance=(Source(id="s", kind="AIPE", name="Synthetic identity only"),),
        capacitance=CharacteristicData(availability="not_applicable"),
    )
    generic = CoverageAnalyzer().gaps(device)
    assert generic.acceptable
    states = {e.rule.id: e.status for e in generic.entries}
    assert states["capacitance"] == "not_applicable"
    assert states["conduction"] == "unknown"
    assert states["thermal"] == "missing"
    dab = CoverageAnalyzer().gaps(device, DABLossEvaluationPolicy())
    assert not dab.acceptable
    assert "operating-envelope" in dab.scope
    plan = draft_measurement_request(dab)
    assert plan.device_id == device.device_id
    assert all(i.draft and i.requirements for i in plan.test_plan_items)
    hot = next(i for i in plan.test_plan_items if i.id == "gap-high_temperature_Eoff")
    assert hot.sweep_axes[0].values == (398.15, 423.15)
    assert all(i.fixed_conditions.dc_bus_voltage is None for i in plan.test_plan_items)
    assert len(explanation_input(dab)["findings"]) <= len(dab.entries)


def test_stale_evidence_cannot_satisfy_rule(device):
    analyzer = CoverageAnalyzer()
    original = analyzer.gaps(device, DABLossEvaluationPolicy())
    by_rule = {e.rule.id: e for e in original.entries}
    assert by_rule["Eon"].evidence_ids
    stale = tuple(
        c.model_copy(update={"provenance": c.provenance.model_copy(update={"freshness": "stale"})})
        for c in device.switching.curves
    )
    updated = device.model_copy(
        update={"switching": device.switching.model_copy(update={"curves": stale})}
    )
    report = analyzer.gaps(updated, DABLossEvaluationPolicy())
    assert next(e for e in report.entries if e.rule.id == "Eon").status == "missing"


def test_partial_and_available_statuses(device):
    analyzer = CoverageAnalyzer()
    assert (
        next(e for e in analyzer.gaps(device).entries if e.rule.id == "conduction").status
        == "available"
    )
    partial = device.model_copy(
        update={"conduction": device.conduction.model_copy(update={"availability": "partial"})}
    )
    assert (
        next(e for e in analyzer.gaps(partial).entries if e.rule.id == "conduction").status
        == "partial"
    )


def test_dab_required_rules_can_be_satisfied_without_claiming_complete_physics():
    from aipe_devices.domain.curves import ScalarRecord
    from aipe_devices.domain.provenance import Dependency, Provenance
    from aipe_devices.domain.thermal import ThermalElement, ThermalNetwork

    provenance = Provenance(
        origin="synthetic",
        lifecycle="derived",
        source_ids=("s",),
        dependencies=(Dependency(id="fixture", version="1"),),
    )

    def scalar(name, unit):
        return ScalarRecord(
            id=name, name=name, quantity={"value": 1, "unit": unit}, provenance=provenance
        )

    device = PowerSemiconductorDevice(
        device_id="complete_rules",
        identity=DeviceIdentity(manufacturer="Example", part_number="Synthetic"),
        provenance=(Source(id="s", kind="AIPE", name="Synthetic test"),),
        conduction=CharacteristicData(
            availability="available", scalars=(scalar("voltage_drop", "V"),)
        ),
        switching=CharacteristicData(
            availability="available", scalars=(scalar("Eon", "J"), scalar("Eoff", "J"))
        ),
        thermal=(
            ThermalNetwork(
                id="thermal",
                topology="Foster",
                provenance=provenance,
                elements=(
                    ThermalElement(
                        resistance={"value": 1, "unit": "K/W"},
                        capacitance={"value": 1, "unit": "J/K"},
                    ),
                ),
            ),
        ),
    )
    report = CoverageAnalyzer().gaps(device, DABLossEvaluationPolicy())
    assert report.acceptable
    assert all(e.status == "available" for e in report.entries if e.rule.importance == "required")
    assert any(
        e.status != "available" for e in report.entries if e.rule.importance == "recommended"
    )
