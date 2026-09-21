import pytest

from aipe_devices.domain.curves import Axis, Curve
from aipe_devices.domain.provenance import Dependency
from aipe_devices.domain.quantities import Quantity
from aipe_devices.schema.enums import Availability, Freshness
from aipe_devices.services.coverage import CoverageAnalyzer
from aipe_devices.services.interpolation import Interpolator
from aipe_devices.services.lineage import DerivedNode, invalidate


def test_coverage_explicit_requirements(device):
    analyzer = CoverageAnalyzer()
    assert analyzer.analyze(device)["switching"] == Availability.AVAILABLE
    assert analyzer.analyze(device)["capacitance"] == Availability.UNKNOWN
    assert (
        analyzer.analyze(device, {"switching": {"Eon", "Eoff", "Err"}})["switching"]
        == Availability.PARTIAL
    )


def test_invalidation_transitive():
    nodes = (
        DerivedNode(id="processed", version="1", dependencies=(Dependency(id="raw", version="1"),)),
        DerivedNode(
            id="metrics", version="1", dependencies=(Dependency(id="processed", version="1"),)
        ),
        DerivedNode(id="unrelated", version="1", dependencies=()),
    )
    result = invalidate(nodes, {"raw"})
    assert [n.freshness for n in result] == [Freshness.STALE, Freshness.STALE, Freshness.CURRENT]
    assert all(n.freshness == Freshness.CURRENT for n in nodes)


def test_interpolation_is_derived_and_bounded(device):
    curve = Curve(
        id="source-curve",
        name="Eon",
        axes=(Axis(name="current", unit="A", values=(0, 10)),),
        unit="J",
        values=(0, 0.002),
        provenance=device.switching.curves[0].provenance,
    )
    result = Interpolator().evaluate(
        curve, Quantity(value=5, unit="A"), result_id="result", input_version="1"
    )
    assert result.quantity.value == 0.001
    assert result.provenance.origin == "interpolated"
    assert result.provenance.dependencies[0].id == curve.id
    for value, unit in [(11, "A"), (5, "V")]:
        with pytest.raises(ValueError):
            Interpolator().evaluate(
                curve, Quantity(value=value, unit=unit), result_id="bad", input_version="1"
            )


def test_duplicate_coordinates_block_interpolation(device):
    curve = Curve(
        id="duplicate",
        name="Eon",
        axes=(Axis(name="current", unit="A", values=(1, 1)),),
        unit="J",
        values=(0.001, 0.002),
        provenance=device.switching.curves[0].provenance,
    )
    with pytest.raises(ValueError, match="unique"):
        Interpolator().evaluate(
            curve, Quantity(value=1, unit="A"), result_id="bad", input_version="1"
        )
