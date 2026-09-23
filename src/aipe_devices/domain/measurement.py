from typing import Literal

from pydantic import Field, model_validator

from .base import Model
from .conditions import ConditionParameter, OperatingCondition
from .curves import ScalarRecord
from .provenance import ArtifactRef, Dependency, Provenance, Source
from .quantities import Quantity, Unit


class MeasurementProtocol(Model):
    id: str = Field(min_length=1)
    version: str = Field(min_length=1)
    category: Literal[
        "static_conduction",
        "dpt",
        "capacitance",
        "gate_charge",
        "reverse_conduction",
        "thermal",
        "soa",
        "reliability",
    ]
    definition: ArtifactRef | None = None


class Instrument(Model):
    id: str
    role: str
    manufacturer: str | None = None
    model: str | None = None
    serial_number: str | None = None
    calibration_reference: str | None = None
    settings: tuple[ConditionParameter, ...] = ()


class InstrumentSetup(Model):
    instruments: tuple[Instrument, ...] = ()
    sampling_rate: Quantity | None = None
    bandwidth: Quantity | None = None
    record_length: int | None = Field(default=None, ge=1)
    voltage_probe: Instrument | None = None
    current_probe: Instrument | None = None
    gate_probe: Instrument | None = None
    deskew: Quantity | None = None
    dc_bus_capacitance: Quantity | None = None
    load_inductance: Quantity | None = None
    gate_driver: str | None = None
    corrections: tuple[ConditionParameter, ...] = ()

    @model_validator(mode="after")
    def units(self):
        for name, unit in {
            "sampling_rate": "Hz",
            "bandwidth": "Hz",
            "deskew": "s",
            "dc_bus_capacitance": "F",
            "load_inductance": "H",
        }.items():
            q = getattr(self, name)
            if q is not None and (q.unit != unit or (name != "deskew" and q.value <= 0)):
                raise ValueError(f"Invalid {name}: expected {unit} and positive magnitude")
        return self


class ProcessingRecipe(Model):
    id: str = Field(min_length=1)
    version: str = Field(min_length=1)
    algorithm: str = Field(min_length=1)
    parameters: tuple[ConditionParameter, ...] = ()
    integration_start_rule: str | None = None
    integration_end_rule: str | None = None
    code_artifact: ArtifactRef | None = None


class WaveformChannel(Model):
    name: str
    unit: Unit
    role: Literal["time", "voltage", "current", "gate_voltage", "gate_current", "other"]


class WaveformEvent(Model):
    id: str
    kind: Literal["turn_on", "turn_off", "reverse_recovery"]
    start_seconds: float
    end_seconds: float

    @model_validator(mode="after")
    def ordered(self):
        if self.end_seconds <= self.start_seconds:
            raise ValueError("Event end must follow start")
        return self


class DynamicWaveformRef(Model):
    id: str
    version: str = "1"
    test_run_id: str
    artifact: ArtifactRef
    stage: Literal["raw", "normalized", "processed"]
    channels: tuple[WaveformChannel, ...] = Field(min_length=1)
    provenance: Provenance
    events: tuple[WaveformEvent, ...] = ()


METRIC_UNITS = {
    "Eon": "J",
    "Eoff": "J",
    "Err": "J",
    "Qrr": "C",
    "td_on": "s",
    "td_off": "s",
    "tr": "s",
    "tf": "s",
    "dv_dt": "V/s",
    "di_dt": "A/s",
    "Vds_peak": "V",
    "Id_peak": "A",
    "ringing_frequency": "Hz",
}


class DynamicMetrics(Model):
    id: str
    test_run_id: str
    waveform_ids: tuple[str, ...] = Field(min_length=1)
    recipe: Dependency
    metrics: tuple[ScalarRecord, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def metric_lineage(self):
        for m in self.metrics:
            if m.name not in METRIC_UNITS or m.quantity.unit != METRIC_UNITS[m.name]:
                raise ValueError(f"Unsupported metric or incorrect unit: {m.name}")
            p = m.provenance
            if p.recipe_id != self.recipe.id or p.recipe_version != self.recipe.version:
                raise ValueError("Metric must reference its processing recipe/version")
            ids = {d.id for d in p.dependencies}
            if not set(self.waveform_ids) <= ids or self.recipe.id not in ids:
                raise ValueError("Metric dependencies must include waveforms and recipe")
            if self.recipe not in p.dependencies:
                raise ValueError("Metric recipe dependency version/checksum must match")
        return self


class TestRun(Model):
    id: str = Field(min_length=1)
    device_id: str = Field(min_length=1)
    physical_sample_id: str | None = None
    production_lot_id: str | None = None
    condition: OperatingCondition
    protocol: MeasurementProtocol
    test_plan_item_id: str | None = None
    results: tuple[ScalarRecord, ...] = ()
    instrument_setup: InstrumentSetup = InstrumentSetup()
    waveform_refs: tuple[DynamicWaveformRef, ...] = ()
    processing_recipes: tuple[ProcessingRecipe, ...] = ()
    derived_metrics: tuple[DynamicMetrics, ...] = ()


class TestCampaign(Model):
    id: str
    name: str
    source: Source
    test_run_ids: tuple[str, ...] = ()
