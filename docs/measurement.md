# Measurement partner interface

MeasurementRequest describes device/sample, independent `TestPlanItem` entries,
and intended rights. Each item owns its protocol, fixed conditions, compact sweep
axes, requested metrics, repetitions, notes and requirements. This package does not contact
laboratories or operate equipment. MeasurementPackage contains source catalogue,
campaigns, runs, artifact inventory and declared external lineage dependencies.

```text
examples/
  measurement_request.json
  measurement_package/
    manifest.json
    waveforms/synthetic.csv
```

The example is explicitly synthetic/derived, not actual device characterization.
A synthetic raw-stage waveform is an unprocessed generated artifact, never labelled
measured. Real acquisition uses measured/raw provenance. CSV is only an example format;
HDF5, Zarr, Parquet and object storage remain possible without changing domain types.

TestRun includes device/sample/lot IDs, OperatingCondition, versioned protocol,
instruments/probes, sampling/bandwidth, deskew, corrections, bus capacitance, load
inductance, driver, waveform references, event windows, recipes and derived metrics.
Recipes identify algorithm version, parameters and integration-window rules.

Supported metric names: Eon, Eoff, Err, Qrr, td_on, td_off, tr, tf, dv_dt, di_dt,
Vds_peak, Id_peak and ringing_frequency. Scalars carry units, uncertainty, statistic,
condition, source and dependencies. WaveformProcessor is an interface; no deskew,
filtering or energy-integration algorithm is supplied yet.

```python
from pathlib import Path
from aipe_devices.measurement.request_generator import MeasurementRequest
from aipe_devices.measurement.submission_validator import validate_package_file

request = MeasurementRequest.model_validate_json(
    Path("examples/measurement_request.json").read_bytes()
)
report = validate_package_file("examples/measurement_package/manifest.json", request=request)
report.raise_for_errors()
```

Validation checks schema, IDs, run/device/sample references, sources, waveform inventory,
metric units/signs, recipe and input versions/checksums, request coverage and artifact
paths/hash/size. Paths must remain within the package. Missing samples warn for historical
data. Declared external dependencies are explicit references, not fetched or verified remotely.

Each item requires its own points and repetitions; unrelated protocols never share
a condition grid. `SweepAxis` accepts explicit SI values or an inclusive
`SweepRange(start, stop, step)`. Validation counts observed coordinate keys rather
than expanding all requested points. Runs may include additional measured conditions.
Overlapping items require `TestRun.test_plan_item_id` to avoid double counting.
Static/capacitance results can use `TestRun.results`; DPT results retain DynamicMetrics.
This is completeness validation, not calibration or physical acceptance testing.

Legacy Phase-1 requests using `protocols[]` and `conditions[]` are migrated at load
time, preserving their old Cartesian meaning in explicit items. New serialization
only emits `test_plan_items`. A compatibility `model_copy(update={"repetitions": n})`
updates all item repetitions. New code should edit each item independently.
Coverage-generated requests have `draft=True`; set safe conditions, protocol
definitions and repetitions and review them before clearing the draft flag.
Submission validation rejects unreviewed draft plans. No lab commands are sent.

See [compact two-protocol example](../examples/phase2/compact_measurement_request.json)
and [gap-derived draft](../examples/phase2/draft_measurement_request.json).

JSON Schemas in `docs/schemas/` cover structure. Python adds cross-reference and physical
checks. `scripts/generate_examples.py` rebuilds examples/schemas. Example protocol IDs
are illustrative versioned identifiers, not a published laboratory standard.
