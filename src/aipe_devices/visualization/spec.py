"""Renderer-neutral application views; never stored as canonical device data."""

from typing import Literal

from pydantic import Field, model_validator

from aipe_devices.domain.base import Model
from aipe_devices.domain.conditions import OperatingCondition
from aipe_devices.domain.curves import Axis
from aipe_devices.domain.measurement import DynamicMetrics
from aipe_devices.domain.provenance import ArtifactRef, Provenance, Source
from aipe_devices.domain.quality import Quality, Uncertainty
from aipe_devices.domain.quantities import Quantity, Unit


class DataReference(Model):
    record_id: str
    device_id: str | None = None
    device_revision: int | None = None
    artifact: ArtifactRef | None = None
    channel: str | None = None


class TensorView(Model):
    axes: tuple[Axis, ...]
    values: tuple[float, ...]
    layout: Literal["last_axis_fastest"] = "last_axis_fastest"

    @model_validator(mode="after")
    def shape(self):
        from math import prod

        if len(self.values) != prod(len(a.values) for a in self.axes):
            raise ValueError("View dimensions do not match")
        return self


class SeriesSpec(Model):
    id: str
    label: str
    quantity: str
    unit: Unit
    visible_by_default: bool = True
    provenance: Provenance
    quality: Quality = Quality()
    uncertainty: Uncertainty | None = None
    condition: OperatingCondition = OperatingCondition()
    data_reference: DataReference
    data: TensorView | None = None
    selected_parameters: dict[str, Quantity] = Field(default_factory=dict)
    sources: tuple[Source, ...] = ()


class ParameterControl(Model):
    parameter: str
    unit: Unit
    values: tuple[float, ...]
    selected: float


class SelectedSlice(Model):
    parameter: str
    coordinate: Quantity
    line: TensorView
    series_id: str


class SelectedPoint(Model):
    series_id: str
    coordinates: dict[str, Quantity]
    value: Quantity
    operating_condition: OperatingCondition
    provenance: Provenance
    sources: tuple[Source, ...] = ()
    quality: Quality
    uncertainty: Uncertainty | None = None


class EventAnnotation(Model):
    id: str
    kind: Literal["turn_on", "turn_off", "reverse_recovery", "integration_window"]
    start_seconds: float
    end_seconds: float

    @model_validator(mode="after")
    def ordered(self):
        if self.end_seconds <= self.start_seconds:
            raise ValueError("Annotation end must follow start")
        return self


class VisualizationSpec(Model):
    schema_version: Literal["1.0"] = "1.0"
    kind: Literal["line", "multi_line", "surface_3d", "multi_surface_3d", "waveform"]
    series: tuple[SeriesSpec, ...] = Field(min_length=1)
    parameter_controls: tuple[ParameterControl, ...] = ()
    selected_slice: SelectedSlice | None = None
    selected_point: SelectedPoint | None = None
    annotations: tuple[EventAnnotation, ...] = ()
    dynamic_metrics: tuple[DynamicMetrics, ...] = ()
    synchronized_axis: str | None = None
    warnings: tuple[str, ...] = ()

    @model_validator(mode="after")
    def unique_series(self):
        if len({s.id for s in self.series}) != len(self.series):
            raise ValueError("Series IDs must be unique")
        return self
