from itertools import product

import pytest
from conftest import ROOT

from aipe_devices.domain.conditions import OperatingCondition
from aipe_devices.domain.curves import Axis, Curve
from aipe_devices.measurement.submission_validator import MeasurementPackage
from aipe_devices.visualization import VisualizationBuilder, VisualizationSpec
from aipe_devices.visualization.spec import EventAnnotation


@pytest.fixture
def builder():
    return VisualizationBuilder()


@pytest.fixture
def tensor(device):
    axes = (
        Axis(name="dc_bus_voltage", unit="V", values=(600, 800)),
        Axis(name="current", unit="A", values=(10, 20, 40)),
        Axis(name="gate_resistance_on", unit="Ohm", values=(2, 5)),
        Axis(name="junction_temperature", unit="K", values=(298.15, 398.15)),
    )
    values = tuple(
        v / 1000 + i / 100 + r / 10 + (t - 273.15) / 1000
        for v, i, r, t in product(*(a.values for a in axes))
    )
    return Curve(
        id="tensor",
        name="Eon",
        unit="J",
        axes=axes,
        values=values,
        provenance=device.switching.curves[0].provenance,
    )


def test_nd_slicing_reorders_axes_exactly(builder, tensor):
    spec = builder.surface(
        tensor,
        x="current",
        y="junction_temperature",
        fixed={"dc_bus_voltage": 800, "gate_resistance_on": 5},
    )
    assert spec.kind == "surface_3d"
    assert spec.series[0].data.values == pytest.approx((1.425, 1.525, 1.525, 1.625, 1.725, 1.825))
    assert len(spec.parameter_controls) == 2
    assert VisualizationSpec.model_validate_json(spec.model_dump_json()) == spec
    with pytest.raises(ValueError, match="exact"):
        builder.surface(
            tensor,
            x="current",
            y="junction_temperature",
            fixed={"dc_bus_voltage": 700, "gate_resistance_on": 5},
        )
    with pytest.raises(ValueError, match="remaining"):
        builder.surface(tensor, x="current", y="junction_temperature")


def test_auto_selection_and_linked_slice_point(builder, tensor):
    spec = builder.auto(tensor)
    assert spec.kind == "surface_3d"
    assert [a.name for a in spec.series[0].data.axes] == ["current", "junction_temperature"]
    assert spec.warnings
    spec = builder.select_slice(
        spec, series_id=tensor.id, parameter="junction_temperature", value=398.15
    )
    assert spec.selected_slice.line.values == pytest.approx((1.025, 1.125, 1.325))
    spec = builder.select_point(
        spec, series_id=tensor.id, coordinates={"current": 20, "junction_temperature": 398.15}
    )
    point = spec.selected_point
    assert point.value.value == pytest.approx(1.125)
    assert point.operating_condition.dc_bus_voltage.value == 600
    assert point.operating_condition.drain_current.value == 20
    assert point.provenance == tensor.provenance
    assert point.quality == tensor.quality


def test_line_multi_line_and_multi_surface(builder, tensor):
    off = tensor.model_copy(update={"id": "off", "name": "Eoff"})
    spec = builder.overlay(builder.auto(tensor), builder.auto(off))
    assert spec.kind == "multi_surface_3d"
    assert [s.label for s in spec.series] == ["Eon", "Eoff"]
    hidden = spec.series[1].model_copy(update={"visible_by_default": False})
    spec = spec.model_copy(update={"series": (spec.series[0], hidden)})
    assert spec.series[0].visible_by_default and not spec.series[1].visible_by_default
    fixed = {"dc_bus_voltage": 800, "gate_resistance_on": 5, "junction_temperature": 398.15}
    line = builder.line(tensor, x="current", fixed=fixed)
    assert line.kind == "line"
    assert builder.overlay(line, builder.line(off, x="current", fixed=fixed)).kind == "multi_line"


def test_overlay_condition_slice_and_unit_guards(builder, tensor):
    off = tensor.model_copy(update={"id": "off", "name": "Eoff"})
    on_spec = builder.auto(tensor)
    off_spec = builder.auto(off, fixed={"dc_bus_voltage": 800})
    with pytest.raises(ValueError, match="mismatch"):
        builder.overlay(on_spec, off_spec)
    warning = builder.overlay(on_spec, off_spec, allow_mismatch=True)
    assert any("not directly comparable" in w for w in warning.warnings)
    off = off.model_copy(
        update={"condition": OperatingCondition(gate_voltage_on={"value": 15, "unit": "V"})}
    )
    with pytest.raises(ValueError, match="mismatch"):
        builder.overlay(on_spec, builder.auto(off))
    with pytest.raises(ValueError, match="units"):
        builder.overlay(on_spec, builder.auto(off.model_copy(update={"unit": "V"})))


def test_duplicate_coordinate_is_not_arbitrarily_selected(builder, tensor):
    axis = tensor.axes[0].model_copy(update={"values": (600, 600)})
    duplicate = tensor.model_copy(update={"axes": (axis, *tensor.axes[1:])})
    with pytest.raises(ValueError, match="Duplicate"):
        builder.auto(duplicate)


def test_waveform_uses_artifact_refs_and_sync(builder):
    package = MeasurementPackage.model_validate_json(
        (ROOT / "examples/measurement_package/manifest.json").read_bytes()
    )
    run = package.runs[0]
    window = EventAnnotation(
        id="integration", kind="integration_window", start_seconds=1e-9, end_seconds=2e-8
    )
    spec = builder.waveform(run.waveform_refs[0], run=run, integration_windows=(window,))
    assert spec.kind == "waveform"
    assert spec.synchronized_axis == "time_s"
    assert len(spec.annotations) == 2
    assert all(s.data is None and s.data_reference.artifact for s in spec.series)
    assert len(spec.model_dump_json()) < 10000
