# Phase 2: import, understand, visualize, request missing data

The existing V3 composition, repository, artifact, PLECS and measurement boundaries
remain in place. Frontend libraries are not dependencies of domain models. The
optional `library` extra adds openpyxl; core JSON/CSV/visualization needs only Pydantic.

## Import flow and storage

`LibraryImporter.inspect(path)` returns an immutable `ImportSession` with detected
tables, `TableMapping`/`ColumnMapping`, `UnitMapping` transformations, source metadata,
warnings, unresolved fields, candidate, engineering validation, coverage and report.
The file adapters are `CanonicalJsonImporter`, `ExcelImporter`, `CsvImporter` and
`GenericJsonImporter`. Construction and semantic mapping are separate modules.

Session history records `parsed`, `validated` when applicable, then `partial`,
`ready_to_import`, `needs_confirmation`, or `failed`. A successful explicit `save`
adds `imported`; the report retains `dataset_status=partial` for incomplete evidence.
Only `partial` or `ready_to_import` sessions without unresolved mappings/errors can
be saved. Filename/device conflicts are reported and never overwrite old evidence.

For a source with declared V3 `schema_version`, schema errors are fatal: it cannot
silently fall back to generic remapping. Valid canonical JSON is not modified.
Its upload metadata lives in the session/report context; existing canonical source
provenance remains unchanged. Tabular/generic imports attach lightweight metadata
to `Source.import_metadata` and observed conversion locators to record provenance.

Excel/CSV bytes, workbook handles and temporary tables live in memory only. Excel
handles are closed after parsing; byte buffers/tables are released after inspection.
No upload is copied to data, docs, legacy, or ArtifactStore. The importer **does not
delete the caller's source file**. Persisted output is canonical JSON only. Explicit
`--report` writes a JSON report to the caller-selected location. Existing raw
manufacturer evidence and large waveform artifacts retain their original policies.

## Mapping and normalization

Aliases are controlled, case-insensitive, and tolerate spaces/underscores. Examples:
`Tj`, `T_j`, `Junction Temp`, `Temperature` map to `junction_temperature`; `Id`, `I_D`,
`Drain Current` map to `drain_current` (canonical curve axis `current`).
`Eon`/`turn_on_energy` and `Eoff`/`turn_off_energy` map to canonical `Eon`/`Eoff`.
Headers accept parentheses or brackets containing engineering units.
When Ciss/Coss/Crss/Eoss columns identify a capacitance table, Vds is treated as
the drain-source-voltage sweep coordinate. Explicit overrides always take precedence.

```text
Tj(C), Vdc(V), Id(A), Eon(mJ), Eoff(mJ)
125,   800,    40,    1.275,   0.6375
```

This becomes `398.15 K`, `800 V`, `40 A`, `0.001275 J`, `0.0006375 J`.
`C` is interpreted as Celsius only for a recognized temperature column; charge
still uses coulombs. Supported conversions include mJ/uJ/µJ, mOhm/mΩ, degC/°C,
nF/pF, ns/us/µs, and the shared explicit conversion registry.

Workbook headers are detected among the first 25 rows using recognized aliases
or explicit overrides; each worksheet represents one table. Flat JSON row arrays,
single row objects, and objects of named row tables use the same pipeline.
Identity must explicitly provide manufacturer and part number, in a worksheet,
row columns or CLI arguments. No identity or physical values are inferred from
filenames. Technology and origin default to unknown. Uploaded data stays unreviewed.

Unrecognized columns such as Loss1, Loss2, and LossAux are unresolved. Unknown,
missing or dimensionally wrong units require confirmation. An accepted mapping:

```json
{
  "Loss1": {"semantic": "Eon", "unit": "mJ"},
  "Loss2": {"semantic": "Eoff", "unit": "mJ"},
  "Notes": {"ignore": true}
}
```

Keys may be column names or `sheet.column` for sheet-specific overrides. A string
alias such as `{"Loss1(mJ)": "Eon"}` is also accepted when the header supplies units.
Explicit overrides are recorded as confirmed; deterministic recognized aliases as
high_confidence. `MappingAssistant` returns separate `MappingSuggestion` objects;
they cannot become accepted columns without a caller-provided mapping override.

Identical rows/points are deduplicated with warnings. Conflicting values at the same
conditions fail; repeats are not silently averaged. Complete Cartesian grids become
dense last-axis-fastest tensors. Sparse grids become exact 1D traces at other fixed
conditions (or scalar records); no point is interpolated or invented. Missing
conditions remain missing with quality flags. Formula cells must be replaced by
reviewed values before import; neither formula execution nor cached results are used.

```bash
aipe-devices inspect-import examples/import/device_ambiguous.csv
aipe-devices import-library examples/import/device_ambiguous.csv --mapping examples/import/mapping_override.json --origin synthetic --output data/derived/demo-library
aipe-devices import-library examples/import/device_canonical.json --output data/derived/canonical-demo
```

CLI exit codes: 0 accepted/inspected/imported, 1 failed, 2 needs confirmation.
Inspect never persists the candidate. Save never persists a rejected candidate.

## Coverage and measurement plans

`CoverageAnalyzer.analyze()` retains its original API. `gaps(device, policy)` adds
`CoverageGapReport` with available/partial/missing/unknown/not_applicable states,
required/recommended/optional priorities, evidence IDs and deterministic findings.
`GenericDeviceStoragePolicy` requires identity only. Missing optional fields do not
invalidate storage. `DABLossEvaluationPolicy` requires conduction, Eon, Eoff and
thermal evidence; it recommends coss/Eoss, reverse conduction, Eon/Eoff at 398.15
and 423.15 K, and gate-resistance sweeps. These are limited evidence-presence rules,
not a converter loss model or a claim of physical sufficiency. Stale records do not
satisfy a requirement. External measurement/market IDs are references, not verified
data payloads.

`explanation_input(report)` exposes engine findings for human/agent explanation.
`draft_measurement_request(report)` maps supported missing groups to reviewable
protocol-local `TestPlanItem` objects. Temperature recommendations come only from
the policy; unspecified current, voltage, gate-resistance and repetition decisions
remain engineering review requirements. Drafts have no lab execution behavior.
See [measurement details](measurement.md).

## Visualization and Explorer

`VisualizationSpec` describes line, multi_line, surface_3d, multi_surface_3d and
waveform views. Series hold labels, units, independent legend visibility, provenance,
quality, uncertainty, source references and selected data. It is an application
view, not canonical stored data. Tensor slices preserve last-axis-fastest layout;
renderers must reshape using the named axis lengths.

```python
from pathlib import Path
from aipe_devices.domain.device import PowerSemiconductorDevice
from aipe_devices.visualization import VisualizationBuilder

device = PowerSemiconductorDevice.model_validate_json(
    Path("examples/import/device_canonical.json").read_bytes()
)
builder = VisualizationBuilder(device_id=device.device_id,
    device_revision=device.revision, sources=device.provenance)
on, off = device.switching.curves
fixed = {"dc_bus_voltage": 800, "gate_resistance_on": 5}
on_view = builder.surface(on, x="current", y="junction_temperature", fixed=fixed)
off_view = builder.surface(off, x="current", y="junction_temperature", fixed=fixed)
spec = builder.overlay(on_view, off_view)
spec = builder.select_slice(spec, series_id=on.id,
    parameter="junction_temperature", value=398.15)
spec = builder.select_point(spec, series_id=on.id,
    coordinates={"current": 40, "junction_temperature": 398.15})
print(spec.kind)                        # multi_surface_3d
print(spec.selected_point.value.value) # approximately 0.001275 J, synthetic
```

`auto()` prefers current/temperature among varying axes. One varying axis gives a
line; two give a surface; other dimensions become controls. Initial automatic
slices select first source coordinates with an explicit warning. Manual surface/
line calls require values for every remaining varying axis. Exact source points
are required; non-source coordinates, duplicate axes and implicit interpolation
are rejected. Changing a control rebuilds the view through the builder.

Overlay requires equal axes, coordinate grids, units, fixed conditions and selected
slices. Condition mismatch raises by default. `allow_mismatch=True` permits a view
with an explicit noncomparability warning; axes/unit mismatch always raises.
Legend visibility is `SeriesSpec.visible_by_default` for each series independently.
Selected point values, conditions, origin, sources, quality and uncertainty all
come from canonical records. A linked 2D slice and selected point can coexist.

Waveform views reference artifacts/channels and synchronize on the time channel;
samples are never embedded. Existing `WaveformEvent` annotations and
`DynamicMetrics` can be exposed. Integration windows must be explicitly supplied
as `EventAnnotation`; no waveform processing or inferred windows are performed.

`DeviceExplorer` implements search → summary/coverage → available characteristics
→ visualization → raw record inspection. It fetches only the selected device when
constructing a view. Summary sections appear only for actual data; measurement and
market references are links, not empty functional panels. Search scans the small
JSON catalogue; no extra index/cache or web infrastructure is required.

```bash
python examples/device_explorer_demo.py
aipe-devices explore --search C3M0016120K
aipe-devices explore --device wolfspeed_c3m0016120k --curves
```

The returned curve IDs can be passed to `explore --device ID --series CURVE_ID...`.
Use `--raw RECORD_ID` for raw canonical values, axes, units, conditions and provenance.
There is no browser renderer in this iteration; the API/CLI and generated specs
are the requested Device Explorer foundation.

## Limits and next iteration

One device per import; one rectangular table per worksheet. Nested generic JSON,
merged multirow headers, multiple devices in a sheet, locale-specific numeric strings,
unit inference, formula evaluation, mixed-unit columns and all thermal/reliability
tabular schemas are not implemented. Unsupported/ambiguous fields remain unresolved.
Production spreadsheets are never fixtures. Current source-axis ambiguities in the
Wolfspeed corpus remain visible and are rejected by exact visualization slicing.

No MAT/TDMS/PDF/image extraction, tensor interpolation, full DPT processing, device
selection, lifetime solver, live market API, lab hardware control or production web
frontend is included. Recommended next work: a review UI for mapping overrides and
coverage, a thin plot adapter for specs, more explicitly specified tabular schemas,
and reviewed operating envelopes before application-level suitability claims.
