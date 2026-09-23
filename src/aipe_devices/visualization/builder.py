from aipe_devices.domain.conditions import CONDITION_UNITS, ConditionParameter, OperatingCondition
from aipe_devices.domain.curves import Curve
from aipe_devices.domain.quantities import Quantity

from .selection import select_axes
from .slicing import slice_tensor
from .spec import (
    DataReference,
    EventAnnotation,
    ParameterControl,
    SelectedPoint,
    SelectedSlice,
    SeriesSpec,
    VisualizationSpec,
)


class VisualizationBuilder:
    def __init__(self, *, device_id=None, device_revision=None, sources=()):
        self.device_id = device_id
        self.device_revision = device_revision
        self.sources = tuple(sources)

    def _view(self, curve, axes, fixed=None):
        fixed = dict(fixed or {})
        names = {a.name for a in curve.axes}
        if set(fixed) - names:
            raise ValueError("Unknown fixed axis")
        for a in curve.axes:
            if a.name not in axes and len(a.values) == 1:
                fixed.setdefault(a.name, a.values[0])
        view = slice_tensor(curve, tuple(axes), fixed)
        selected = {
            a.name: Quantity(value=fixed[a.name], unit=a.unit)
            for a in curve.axes
            if a.name in fixed
        }
        controls = tuple(
            ParameterControl(parameter=a.name, unit=a.unit, values=a.values, selected=fixed[a.name])
            for a in curve.axes
            if a.name in fixed
        )
        series = SeriesSpec(
            id=curve.id,
            label=curve.name,
            quantity=curve.name,
            unit=curve.unit,
            provenance=curve.provenance,
            quality=curve.quality,
            uncertainty=curve.uncertainty,
            condition=curve.condition,
            data_reference=DataReference(
                record_id=curve.id, device_id=self.device_id, device_revision=self.device_revision
            ),
            data=view,
            selected_parameters=selected,
            sources=tuple(s for s in self.sources if s.id in curve.provenance.source_ids),
        )
        return VisualizationSpec(
            kind="line" if len(axes) == 1 else "surface_3d",
            series=(series,),
            parameter_controls=controls,
        )

    def line(self, curve, *, x, fixed=None):
        return self._view(curve, (x,), fixed)

    def surface(self, curve, *, x, y, fixed=None):
        return self._view(curve, (x, y), fixed)

    def auto(self, curve, *, fixed=None):
        axes = select_axes(curve)
        chosen = {a.name: a.values[0] for a in curve.axes if a.name not in axes}
        supplied = dict(fixed or {})
        chosen.update(supplied)
        result = self._view(curve, axes, chosen)
        defaults = [
            a.name
            for a in curve.axes
            if a.name not in axes and len(a.values) > 1 and a.name not in supplied
        ]
        if defaults:
            result = result.model_copy(
                update={
                    "warnings": (
                        f"Initial exact slice uses first coordinates for: {', '.join(defaults)}",
                    )
                }
            )
        return result

    def overlay(self, *specs, allow_mismatch=False):
        if len(specs) < 2 or any(
            s.kind not in {"line", "surface_3d", "multi_line", "multi_surface_3d"} for s in specs
        ):
            raise ValueError("Overlay requires at least two curve views")
        series = tuple(s for spec in specs for s in spec.series)
        reference = series[0]
        warnings = [w for spec in specs for w in spec.warnings]
        for other in series[1:]:
            if other.unit != reference.unit or other.data.axes != reference.data.axes:
                raise ValueError("Overlay requires identical axes, coordinates, and units")
            if (
                other.condition != reference.condition
                or other.selected_parameters != reference.selected_parameters
            ):
                if not allow_mismatch:
                    raise ValueError("Overlay condition/slice mismatch")
                warnings.append(
                    f"Condition/slice mismatch: {reference.id} vs {other.id}; not directly comparable"
                )
        controls = tuple(dict.fromkeys(c for spec in specs for c in spec.parameter_controls))
        return VisualizationSpec(
            kind="multi_line" if len(reference.data.axes) == 1 else "multi_surface_3d",
            series=series,
            parameter_controls=controls,
            warnings=tuple(warnings),
        )

    def select_point(self, spec, *, series_id, coordinates):
        series = next((s for s in spec.series if s.id == series_id), None)
        if series is None or series.data is None:
            raise ValueError("Point selection requires a curve series")
        if set(coordinates) != {a.name for a in series.data.axes}:
            raise ValueError("Supply exactly the displayed axis coordinates in SI units")
        index = 0
        qcoords = dict(series.selected_parameters)
        for axis in series.data.axes:
            value = coordinates[axis.name]
            if value not in axis.values:
                raise ValueError("Point must be an exact displayed source coordinate")
            index = index * len(axis.values) + axis.values.index(value)
            qcoords[axis.name] = Quantity(value=value, unit=axis.unit)
        cond = series.condition.model_dump()
        extensions = {x.name: x for x in series.condition.extensions}
        for name, q in qcoords.items():
            name = "drain_current" if name == "current" else name
            if name in CONDITION_UNITS:
                if cond[name] is not None and cond[name] != q.model_dump():
                    raise ValueError("Curve axis contradicts fixed operating condition")
                cond[name] = q
            else:
                extensions[name] = ConditionParameter(name=name, quantity=q)
        cond["extensions"] = tuple(extensions.values())
        point = SelectedPoint(
            series_id=series.id,
            coordinates=qcoords,
            value=Quantity(value=series.data.values[index], unit=series.unit),
            operating_condition=OperatingCondition.model_validate(cond),
            provenance=series.provenance,
            sources=series.sources,
            quality=series.quality,
            uncertainty=series.uncertainty,
        )
        return spec.model_copy(update={"selected_point": point})

    def select_slice(self, spec, *, series_id, parameter, value):
        series = next((s for s in spec.series if s.id == series_id), None)
        if series is None or series.data is None or len(series.data.axes) != 2:
            raise ValueError("Linked slice requires a displayed surface")
        axis = next((a for a in series.data.axes if a.name == parameter), None)
        if axis is None:
            raise ValueError("Slice parameter is not a displayed surface axis")
        curve = Curve(
            id=series.id,
            name=series.quantity,
            axes=series.data.axes,
            values=series.data.values,
            unit=series.unit,
            provenance=series.provenance,
        )
        view = slice_tensor(
            curve, tuple(a.name for a in curve.axes if a.name != parameter), {parameter: value}
        )
        return spec.model_copy(
            update={
                "selected_slice": SelectedSlice(
                    parameter=parameter,
                    coordinate=Quantity(value=value, unit=axis.unit),
                    line=view,
                    series_id=series_id,
                )
            }
        )

    def waveform(self, waveform, *, run=None, integration_windows=()):
        times = [c for c in waveform.channels if c.role == "time"]
        if len(times) != 1 or times[0].unit != "s":
            raise ValueError("Synchronized waveform requires one time channel in seconds")
        if run and waveform.test_run_id != run.id:
            raise ValueError("Waveform and run do not match")
        series = tuple(
            SeriesSpec(
                id=f"{waveform.id}:{c.name}",
                label=c.name,
                quantity=c.role,
                unit=c.unit,
                provenance=waveform.provenance,
                condition=run.condition if run else OperatingCondition(),
                sources=tuple(s for s in self.sources if s.id in waveform.provenance.source_ids),
                data_reference=DataReference(
                    record_id=waveform.id,
                    device_id=self.device_id,
                    artifact=waveform.artifact,
                    channel=c.name,
                ),
            )
            for c in waveform.channels
            if c.role != "time"
        )
        annotations = tuple(EventAnnotation(**e.model_dump()) for e in waveform.events) + tuple(
            integration_windows
        )
        return VisualizationSpec(
            kind="waveform",
            series=series,
            synchronized_axis=times[0].name,
            annotations=annotations,
            dynamic_metrics=tuple(m for m in run.derived_metrics if waveform.id in m.waveform_ids)
            if run
            else (),
        )
