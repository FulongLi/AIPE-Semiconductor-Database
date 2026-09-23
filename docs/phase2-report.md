# Phase-2 implementation report

Implemented on `codex/phase2-library-explorer`, starting from upstream `406379f`.
This is an incremental extension of V3. Manufacturer data and the JSON repository
remain the source of truth; no replacement architecture or production web stack
was introduced.

## 1. Changes

Protocol-local compact test plans, a four-format Library Importer, deterministic
mapping and normalization, structured import/coverage reports, a rule-driven draft
measurement planner, renderer-neutral visualizations and a Device Explorer API/CLI
now form a working end-to-end flow. Original tests remain; new tests cover the
Phase-2 behavior and its failure cases.

## 2. Updated directory tree

```text
src/aipe_devices/
  domain/                     existing V3 models; additive traceability/results
  importers/library/
    models.py                 sessions, reports, mappings and suggestion contract
    parsers.py                canonical/generic JSON, Excel and CSV adapters
    mapping.py                aliases, accepted overrides and unit checks
    construction.py           exact canonical curves, scalars and provenance
    service.py                inspect/save lifecycle
  measurement/
    plans.py                  TestPlanItem, SweepAxis, SweepRange
    request_generator.py      new requests and legacy migration
    submission_validator.py   per-item point/repetition validation
    gap_planner.py            reviewable draft requests
  services/coverage/gaps.py    policies, engine report, explanation input
  visualization/
    spec.py                   renderer-neutral models
    selection.py              automatic axis/type choice
    slicing.py                exact named tensor slices
    builder.py                line/surface/overlay/point/waveform APIs
  explorer.py                 search, summaries, raw records, visualization
  cli.py                      inspect-import, import-library, explore
examples/
  import/                     tiny explicitly synthetic inputs
  phase2/                     actual report/spec/request JSON outputs
  device_explorer_demo.py     executable API demonstration
scripts/generate_phase2_examples.py
tests/unit/test_{test_plans,library_importer,coverage_gaps,visualization}.py
tests/integration/test_phase2_workflow.py
docs/phase2.md                 usage and limitations
docs/schemas/                 refreshed and new public JSON schemas
```

## 3. New models

Measurement: `TestPlanItem`, `SweepAxis`, `SweepRange`.
Ingestion: `ImportMetadata`, `SourceLocator`, `DetectedTable`, `ColumnMapping`,
`TableMapping`, `UnitMapping`, `MappingSuggestion`, `ImportSession`, `ImportReport`.
Coverage: `CoverageRule`, `CoverageGap`, `CoverageGapReport`, `CoveragePolicy`.
Views: `VisualizationSpec`, `SeriesSpec`, `TensorView`, `DataReference`,
`ParameterControl`, `SelectedSlice`, `SelectedPoint`, `EventAnnotation`.
`Source` accepts user-upload context and optional import metadata; `Origin.UNKNOWN`
represents genuinely unspecified origin. Uploaded data remains unreviewed.

## 4. MeasurementRequest

`test_plan_items[]` replaces global protocol and condition lists. Each item owns
its protocol, fixed conditions, sweeps, metrics, repetitions, requirements and draft
flag. An inclusive range remains compact rather than allocating all points.
Submitted runs are counted by matching coordinate keys per item; the validator
does not create a cross-product across different protocols. Overlapping items
require explicit `test_plan_item_id`. `TestRun.results` supports static/capacitance
scalars alongside existing DynamicMetrics.

Legacy requests are migrated on read and serialize back to the new form.
The [compact example](../examples/phase2/compact_measurement_request.json) describes
324 DPT points × 3 repetitions, and 162 capacitance points, in two independent items.
The old `model_copy(repetitions=...)`-style update compatibility is implemented as
`model_copy(update={"repetitions": n})`; new code edits repetitions per item.

## 5. Importer architecture

Canonical JSON → schema/engineering checks → report → repository save.
Excel/CSV/generic JSON → transient tables → semantic mappings → SI normalization
→ canonical candidate → validation/coverage → explicit save.
Format adapters, mappings, construction and lifecycle are independent modules.
An optional mapping assistant can suggest; only explicit accepted mappings enter
the deterministic pipeline. No LLM invocation is required.

## 6. Excel/CSV behavior

The workbook example has identity, switching and conduction sheets, recognized
headers after a descriptive row, and a four-dimensional switching grid. Aliases
and units are explicit. For example, `Tj(C)=125` becomes `398.15 K`, and
`Eon(mJ)=1.275` becomes `0.001275 J`. Capacitance table Vds becomes its sweep axis.

Loss1/Loss2 remain unresolved, producing `needs_confirmation` and CLI exit 2.
[Mapping overrides](../examples/import/mapping_override.json) confirm quantities
and units; rerunning then saves a partial device successfully. Missing identity,
nonfinite values, wrong canonical units and conflicting repeated points fail.
Sparse grids are split into exact traces without filling data or averaging repeats.

## 7. Upload disposal and traceability

No upload is copied into the repository. Workbook handles close after parsing;
temporary bytes and table objects are released. The user's original file is left
intact. Source JSON preserves filename, SHA-256, timestamp, importer version and
row/column/unit-conversion locators. Existing raw manufacturer evidence is retained;
scientific artifacts continue to use ArtifactStore references. Committed CSV/XLSX
files added by this change are tiny, labelled synthetic fixtures only.

## 8. Canonical JSON example

[Full valid canonical example](../examples/import/device_canonical.json) contains
48 observed points per switching quantity and six conduction points, with source
lineage. Selected fields from its Eon record:

```json
{
  "name": "Eon",
  "unit": "J",
  "quality": {"flags": [], "review_status": "unreviewed"},
  "condition": {"gate_resistance_off": {"value": 5.0, "unit": "Ohm"}}
}
```

This is a field excerpt, not a standalone device document. The axes in the full
record are current, junction_temperature, dc_bus_voltage, gate_resistance_on.
All example quantities are synthetic, not manufacturer claims.

## 9. ImportReport example

[Actual report](../examples/phase2/import_report.json) from the workbook:

```text
input_format: xlsx
detected_tables: identity, switching, conduction
records_created: 3
device_identity_status: available
validation_result: no errors
final_status: partial
dataset_status: partial
```

The imported characteristics are usable; missing thermal/capacitance/etc. remain
explicit. Calling `save` changes final_status to imported while dataset_status
stays partial. [Ambiguous report](../examples/phase2/ambiguous_report.json) identifies
Loss1 and Loss2 and blocks saving until accepted mappings are supplied.

## 10. CoverageGapReport example

Generic library storage accepts the example identity. The [DAB report](../examples/phase2/coverage_gap_report.json)
has acceptable=false:

| Rule | Result | Priority |
| --- | --- | --- |
| Conduction | available | required |
| Eon / Eoff | available | required |
| Thermal | missing | required |
| Coss / Eoss | missing | recommended |
| 125/150 °C Eon / Eoff | partial (125 °C present) | recommended |
| Rgon dependence for Eon | available | recommended |
| Rgoff dependence for Eoff | missing | recommended |

These are implemented evidence rules only. They do not assert safe operating
limits or converter-level physical sufficiency. Only reported engine findings
reach `explanation_input` and the [draft measurement request](../examples/phase2/draft_measurement_request.json).

## 11. VisualizationSpec examples

Generated [line](../examples/phase2/line.json), [surface](../examples/phase2/surface.json),
[conduction](../examples/phase2/conduction_surface.json), and
[waveform](../examples/phase2/waveform.json) views validate against the public models.
They carry source/quality metadata, series visibility and exact selected data.
Waveforms have synchronized channels, artifact references, event annotations and
existing DynamicMetrics; no samples or processing algorithms are embedded.

## 12. Eon/Eoff multi-surface example

[Full spec](../examples/phase2/multi_surface.json):

```text
kind: multi_surface_3d
series: Eon (visible), Eoff (visible)
X: current = [10, 20, 40] A
Y: junction_temperature = [298.15, 398.15] K
controls: dc_bus_voltage=800 V, gate_resistance_on=5 Ohm
fixed condition: gate_resistance_off=5 Ohm
selected_slice: junction_temperature=398.15 K
selected_point: current=40 A, temperature=398.15 K
selected Eon: approximately 0.001275 J = 1.275 mJ (synthetic)
```

Each series has its own visible_by_default. Overlay verifies axes, units, conditions
and slices. Eon at 800 V versus Eoff at 600 V raises unless a mismatch warning is
explicitly requested. Incompatible axes or units always raise.

## 13. High-dimensional slicing example

```python
surface = builder.surface(on, x="current", y="junction_temperature",
    fixed={"dc_bus_voltage": 800, "gate_resistance_on": 5})
```

The returned two-axis view contains six values, with the last axis varying fastest.
Remaining source dimensions become controls. Selecting an absent coordinate such
as 700 V fails rather than interpolating. A linked 125 °C line and source-aware
point are demonstrated by `python examples/device_explorer_demo.py`.

## 14. Validation

The original 521 tests remain and pass; 50 new test cases bring the suite to
**571 passing tests** on both Python 3.11 and 3.12. Tests cover the 163-device
catalogue, byte-identical raw manifest, PLECS roundtrips and migrations, importer
failure paths, SI conversion, partial/sparse construction, policies, request
migration/repetitions, exact slicing, overlay guards, waveform references and the
CLI-to-Explorer workflow. Ruff lint/format and package builds also pass.
The built wheel was installed into a separate environment and tested outside the
checkout: Excel → canonical JSON repository → Eon/Eoff multi-surface succeeded.

Windows checkout initially converted evidence line endings; `.gitattributes` now
preserves raw evidence and waveform/synthetic CSV bytes. No manufacturer canonical
or raw evidence files are changed. GitHub Actions retains Python 3.11/3.12 coverage
and additionally executes the Explorer demo. Equivalent checks were run locally;
hosted GitHub Actions has not been triggered in this session.

## 15. Known limitations

The Explorer is a renderer-neutral API/CLI foundation, without a browser GUI.
Import currently handles one device per file and one table per sheet; nested JSON,
formula evaluation, multirow/merged headers, locale numbers and broad thermal/
reliability spreadsheet schemas need explicit future adapters. Unsupported columns
stay unresolved. No interpolation, prediction, OCR, TDMS/MAT import, full waveform
processing, lab control, cloud database, auth or live pricing is implemented.
New readers load the old V3 corpus; older strict clients may need upgrading to
understand the new optional metadata fields. Source-axis ambiguities are preserved
and can prevent an exact plot rather than being silently repaired.

## 16. Recommended next iteration

Build a small mapping-review and plotting adapter on these APIs, add fixture-backed
tabular schemas requested by real contributors, and introduce reviewed operating
envelopes before making application-suitability claims. Keep waveform processing,
large artifact storage and device-selection optimization as separate extensions.
