import pytest

from aipe_devices.domain.curves import Axis, Curve
from aipe_devices.domain.provenance import Provenance
from aipe_devices.domain.quantities import Quantity
from aipe_devices.services.interpolation import EnvelopePolicy, NDInterpolator, PreparedTensor

PROVENANCE = Provenance(origin="manufacturer_model", source_ids=("s",))


def energy_curve():
    """E = 1e-6 * V * I with a PLECS-style guard row at 1173.15 K holding zeros."""
    temperatures = (298.15, 398.15, 1173.15)
    voltages = (0.0, 400.0, 800.0)
    currents = (0.0, 10.0, 20.0, 40.0)
    values = []
    for t in temperatures:
        for v in voltages:
            for i in currents:
                values.append(0.0 if t > 1000 else 1e-6 * v * i)
    return Curve(
        id="eoff",
        name="Eoff",
        unit="J",
        axes=(
            Axis(name="junction_temperature", unit="K", values=temperatures),
            Axis(name="dc_bus_voltage", unit="V", values=voltages),
            Axis(name="current", unit="A", values=currents),
        ),
        values=tuple(values),
        provenance=PROVENANCE,
    )


def test_multilinear_evaluation_drops_guard_rows():
    tensor = PreparedTensor(energy_curve())
    assert tensor.grids["junction_temperature"] == (298.15, 398.15)
    assert tensor.dropped["junction_temperature"] == (1173.15,)
    result = tensor.value(
        {"junction_temperature": 348.15, "dc_bus_voltage": 600.0, "current": 15.0}
    )
    assert result.value == pytest.approx(1e-6 * 600 * 15)
    assert "guard_rows_dropped:junction_temperature" in result.flags
    assert {"interpolated:dc_bus_voltage", "interpolated:current"} <= set(result.flags)
    assert not result.extrapolated


def test_guard_rows_would_corrupt_interpolation_if_kept():
    policy = EnvelopePolicy(drop_guard_rows=False)
    kept = PreparedTensor(energy_curve(), policy)
    value = kept.value({"junction_temperature": 700.0, "dc_bus_voltage": 800.0, "current": 20.0})
    assert value.value < 1e-6 * 800 * 20  # the zero guard row pulls the value down
    with pytest.raises(ValueError, match="outside the source envelope"):
        PreparedTensor(energy_curve()).value(
            {"junction_temperature": 700.0, "dc_bus_voltage": 800.0, "current": 20.0}
        )


def test_extrapolation_requires_explicit_policy_and_is_flagged():
    coordinates = {"junction_temperature": 398.15, "dc_bus_voltage": 800.0, "current": 50.0}
    with pytest.raises(ValueError, match="allow_extrapolation"):
        PreparedTensor(energy_curve()).value(coordinates)
    linear = PreparedTensor(energy_curve(), EnvelopePolicy(allow_extrapolation=True))
    result = linear.value(coordinates)
    assert result.extrapolated and "extrapolated:current" in result.flags
    assert result.value == pytest.approx(1e-6 * 800 * 50)
    held = PreparedTensor(
        energy_curve(), EnvelopePolicy(allow_extrapolation=True, extrapolation="hold_nearest")
    )
    assert held.value(coordinates).value == pytest.approx(1e-6 * 800 * 40)


def test_records_carry_origin_units_and_lineage():
    curve = energy_curve()
    record = NDInterpolator().evaluate(
        curve,
        {
            "junction_temperature": Quantity(value=398.15, unit="K"),
            "dc_bus_voltage": Quantity(value=800, unit="V"),
            "current": Quantity(value=20, unit="A"),
        },
        result_id="r",
        input_version="1",
    )
    assert record.quantity.value == pytest.approx(0.016)
    assert record.provenance.origin == "interpolated"
    assert record.provenance.dependencies[0].id == curve.id
    assert {e.name for e in record.condition.extensions} == {
        "axis:junction_temperature",
        "axis:dc_bus_voltage",
        "axis:current",
    }
    extrapolated = NDInterpolator().evaluate(
        curve,
        {
            "junction_temperature": Quantity(value=398.15, unit="K"),
            "dc_bus_voltage": Quantity(value=800, unit="V"),
            "current": Quantity(value=45, unit="A"),
        },
        result_id="x",
        input_version="1",
        policy=EnvelopePolicy(allow_extrapolation=True),
    )
    assert extrapolated.provenance.origin == "extrapolated"
    with pytest.raises(ValueError, match="unit"):
        NDInterpolator().evaluate(
            curve,
            {
                "junction_temperature": Quantity(value=125, unit="V"),
                "dc_bus_voltage": Quantity(value=800, unit="V"),
                "current": Quantity(value=20, unit="A"),
            },
            result_id="bad",
            input_version="1",
        )


def test_missing_axis_duplicate_axis_and_stale_rejected():
    curve = energy_curve()
    with pytest.raises(ValueError, match="every tensor axis"):
        PreparedTensor(curve).value({"junction_temperature": 398.15, "dc_bus_voltage": 800.0})
    duplicate = curve.model_copy(
        update={
            "axes": (
                curve.axes[0],
                curve.axes[1],
                Axis(name="current", unit="A", values=(0.0, 10.0, 10.0, 40.0)),
            )
        }
    )
    with pytest.raises(ValueError, match="unique"):
        PreparedTensor(duplicate)
    stale = curve.model_copy(
        update={"provenance": curve.provenance.model_copy(update={"freshness": "stale"})}
    )
    with pytest.raises(ValueError, match="stale"):
        PreparedTensor(stale)


def test_real_corpus_eoff_point_matches_source_table(device):
    eoff = device.switching.curves[1]
    tensor = PreparedTensor(eoff)
    # Golden test: 25 C, 800 V, 12.56 A is a source grid point of C2M0025120D.
    exact = tensor.value(
        {"junction_temperature": 298.15, "dc_bus_voltage": 800.0, "current": 12.56}
    )
    assert exact.value == pytest.approx(0.00007008)
    assert all(a.exact for a in exact.axes)
    assert tensor.dropped["junction_temperature"] == (1173.15, 1273.15)
