# Changelog

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
