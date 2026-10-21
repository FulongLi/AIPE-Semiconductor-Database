# Changelog

## 3.1.0 — DAB loss evaluation, screening and measurement requests

- Python 3.10 support: `StrEnum` backport in `schema/enums.py`, `requires-python >= 3.10`,
  CI matrix 3.10/3.11/3.12. Package version 3.1.0; domain schema stays 3.0.0.
- `services/interpolation`: `NDInterpolator`/`PreparedTensor` multilinear evaluation of
  N-D curves with `EnvelopePolicy` (guard rows >= 773.15 K dropped, extrapolation only
  with `allow_extrapolation=True`, flagged and recorded as `extrapolated` origin).
- `services/loss/dab.py`: `DABLossEvaluator` implementing `LossEvaluator` for a DAB
  switch position from summary metrics or sampled waveforms (HDF5 loader), with
  conduction (forward/reverse, gate-aware third-quadrant policy), turn-off, ZVS-aware
  turn-on, PLECS gate-resistance formula scaling through a restricted grammar
  (`plecs_formula.py`), `physics_derived` records with tensor lineage and a `coverage` list.
- `services/thermal`: Zth(t) step response, exact Cauer -> Foster conversion, junction
  temperature with user-supplied case-to-sink resistance, electro-thermal fixed point.
- `importers/datasheet`: transcription importer (`aipe-datasheet-transcription/0.1`) that
  builds unreviewed candidate records with datasheet URL evidence, `absent` flags and
  canonical-record links; `data/candidates/` with the 2026-10-21 SiC DAB shortlist
  (17 devices + 2 TI reference-design parts) and generated records.
- `services/selection/dab.py`: evidence-tiered DAB screening (derating, current margin,
  losses at Tj, junction-temperature headroom, confidence score; tiers never interleave).
- `services/measurement_requests.py`: prioritised draft `MeasurementRequest`s from
  coverage gaps (static I-V, Rds(on) vs Tj, DPT, reverse conduction, Coss/Eoss, Zth,
  package thermal) with questions, uncertainty targets and benefit x uncertainty scores.
- CLI: `dab-losses`, `dab-screen`, `measurement-requests`, `import-candidates`;
  `examples/dab/` holds outputs generated from the nominal run summary.
- Unit registry: uH/nH/mH, uC, A/us, A/ns, V/us, V/ns, kV, kW/mW, degC/W.
- `aipe.yaml`: capabilities `semiconductor-loss-evaluation`, `semiconductor-dab-screening`,
  `semiconductor-measurement-requests`, `candidate-device-import`.

## 3.0.0 — Foundation refactor

- Added versioned canonical models, SI units, conditions, provenance, lineage and quality.
- Added JSON repository, artifact storage, PLECS importer/exporter, JSON/MATLAB exports,
  and explicit V1/V2 migrations.
- Preserved 164 raw files and 326 legacy JSON files. Rebuilt 163 devices, including
  90 four-dimensional switching tables lost by old converters.
- Added DPT campaign/run/instrument/protocol/recipe/metric metadata, measurement
  schemas, examples and validation; module, reliability and market extensions.
- Added coverage, invalidation, bounded interpolation, thermal resistance, tests and CI.

### Breaking changes

Old root scripts and the monolithic `Transistor` API are retired. V3 does not import
`transistordatabase`. `DUTs/` moved to `data/raw/wolfspeed/`; `standard_database*`
moved to `legacy/v1/` and `legacy/v2/`. `data/canonical/` is the sole official corpus.
The V3 CLI replaces preprocessing/router scripts. PDF/HTML reports and legacy plots
are retired without a V3 replacement in this phase. New services do not implement
all historical working-point, fitting or lifetime methods.

Energy is J, resistance Ohm, absolute temperature K; `C` means electrical charge.
No source temperature/voltage points are removed and no unknown ratings/gate voltages
are synthesized. V2 rating/static assumptions remain derived/inferred records.
