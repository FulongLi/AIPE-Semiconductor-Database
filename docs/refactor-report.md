# V3 foundation refactor — delivery report

## 1. Old architecture audit

The starting repository contained 507 files, two competing 163-device JSON corpora,
163 source XML models and a manufacturer PDF. Six Python scripts mixed XML parsing,
schema conversion, plotting, export, working points and database concerns. There was
no project metadata or executable test suite. The 2,719-line inherited monolith had
unresolved `transistordatabase.*` dependencies; the 930-line router depended on V1.

The audit found substantive data loss: V1/V2 omitted 90 four-axis custom tables in
45 models. V2 also removed high-temperature/nonpositive-voltage points and injected
gate-voltage, rating, package and identity assumptions. [Full audit](audit.md).

## 2. Deleted files

**15 obsolete files removed after replacement tests passed:** six old Python scripts,
four bytecode caches, four stale documents and an invalid npm worktree setup.
[Exact file-by-file list and reasons](deletions.md).

No raw or legacy device data was deleted. The 164 raw files and 326 legacy JSON files
were moved and verified byte-for-byte. README was rewritten; the logo was retained.
Git history remains the archive for retired functionality.

## 3. Preserved and migrated functionality

| Capability | V3 result |
| --- | --- |
| PLECS parsing | Independent importer; SI tensors, provenance and full source points |
| Four-axis custom tables | Newly recovered into 90 canonical curves, with adapter bindings |
| PLECS export | Canonical tensors → XML, preserving variables/formulas/comments/thermal elements |
| MATLAB export | Canonical struct plus lossless V3 JSON string; optional SciPy dependency |
| JSON conversion | Versioned canonical roundtrip, explicit V1/V2 migrations |
| Working-point concepts | Independent service contracts, no mutable Device.wp |
| Thermal models | Typed Cauer/Foster networks; initial DC resistance evaluator |
| Data reporting | Coverage service and reproducible per-device migration report |
| Legacy plots / HTML / PDF | Retired, intentionally not a Phase-1 replacement feature |

No code from the old monolithic class was copied into the new foundation.
[Licensing notes](../LICENSING.md) record the unresolved historical/code-license status.

## 4. New directory tree

```text
AIPE-Transistor-Database/
├── pyproject.toml, README.md, CHANGELOG.md, LICENSING.md, .gitignore
├── .github/workflows/tests.yml
├── src/aipe_devices/
│   ├── cli.py
│   ├── domain/
│   │   ├── base.py, device.py, identity.py, conditions.py, quantities.py
│   │   ├── curves.py, provenance.py, quality.py, models.py
│   │   └── thermal.py, module.py, measurement.py, reliability.py, market.py
│   ├── schema/                  # enums, versions, validation reports
│   ├── importers/               # PLECS, legacy, measurement; datasheet/SPICE interfaces
│   ├── normalizers/units.py
│   ├── repository/              # protocol + JSON filesystem implementation
│   ├── storage/artifact_store.py
│   ├── services/                # validation, coverage, lineage, interpolation, thermal,
│   │                            # comparison and loss/fitting contracts
│   ├── measurement/             # requests, submissions, processing interface
│   ├── exporters/               # PLECS, MATLAB, JSON
│   └── migration/               # v1_to_v3.py, v2_to_v3.py
├── data/
│   ├── raw/wolfspeed/           # 163 XML + original PDF, original subdirectories
│   ├── raw/manifest.json        # pre-refactor source checksums
│   ├── canonical/               # 163 official V3 device JSONs
│   └── derived/README.md
├── legacy/                      # README, unchanged v1/ and v2/ corpora
├── tests/                       # unit/, integration/, golden/fixtures/
├── examples/                    # measurement request, manifest, synthetic waveform
├── scripts/generate_examples.py
├── docs/                        # architecture, audit, migration, partner interface,
│                                # deletion/delivery reports and JSON schemas
└── images/logo.png
```

## 5. Canonical model

PowerSemiconductorDevice composes identity/classification, ratings, package components,
source catalogue, quality, characteristic groups, thermal/reliability data and
model/measurement/market references. Identity can distinguish family, part, revision,
lot and sample. Generic curves are flattened tensors with ordered named axes; scalars
carry condition, unit, statistic, uncertainty and provenance. Internal units are SI,
including Kelvin for absolute temperature. Unknown historical fields remain unknown.
Market observations are separate time-varying records, not fixed device properties.

## 6. Evidence flow

Raw bytes → explicit normalization → shape/engineering/provenance validation →
canonical repository → independent services → derived records → application views.
Source references retain checksums and rights metadata. Derived data uses input
IDs/versions, recipes and stale status; source records are append-only at the
repository boundary. Large waveforms are artifacts referenced by TestRun metadata.
The initial invalidation service marks transitive dependencies stale on explicit
input/recipe changes. [Architecture and invariants](architecture.md).

## 7. Migration status

- **163/163 source devices migrated:** 119 discrete, 44 module models.
- **742 characteristic curves**, including **90 four-dimensional custom tables**.
- **164/164 raw files unchanged**, including the manufacturer PDF.
- **326/326 historical JSON files preserved and migration-tested**.
- **Zero engineering/schema errors** in the official corpus.
- **742 high-temperature warnings** and **24 duplicate-axis warnings in six devices**
  are retained and explicitly reported. No source points were deduplicated/filtered.
- V2 inferred ratings/static values stay derived/inferred. Missing custom data and
  injected defaults are not represented as verified manufacturer evidence.

See [per-device report](migration-report.json) and [migration guide](migration.md).

## 8. Verification

Local verification on Python 3.12 completed:

- **521 pytest cases passed**, including all source XML roundtrips, all legacy
  migrations, golden physical values, synthetic IGBT/MOSFET-module/GaN schemas,
  storage integrity, evidence protection, coverage, invalidation, units and measurement
  package/reference/version/checksum failure cases.
- Ruff lint and formatting checks passed; `git diff --check` passed.
- Source distribution and wheel built successfully; wheel includes licensing notes.
- Installed-wheel repository/query/coverage/PLECS workflow and package-validation CLI passed.
- SHA-256 comparison verified all raw and legacy files against the initial inventory.
- CI is configured for Python 3.11 and 3.12; remote CI has not been run in this task.

The local managed macOS runtime marked editable-install `.pth` files hidden, so a
normal wheel installation was used for the installed-package smoke test. Source tests
use pytest's explicit `src` path. In environments with this behavior, use a regular
installation or `PYTHONPATH=src` for source-based commands.

## 9. Known limitations

PLECS compatibility is tested by semantic XML roundtrip, not simulator execution or
external XSD validation. Export requires explicit adapter bindings; unsupported
custom-table semantics and unresolved legacy lookups raise. Formula execution is absent.
Duplicate source coordinates require reviewed resolution before interpolation.

Loss/fitting, DPT processing, datasheet/SPICE ingestion and market repositories are
extension contracts. Only bounded 1D interpolation and thermal DC resistance are
implemented physics services. No complete module transient model, ratings review,
waveform processing, reliability prediction, lab automation, pricing APIs, cloud
storage or production authorization is included. License metadata does not settle
historical rights or grant source-data reuse permissions.

## 10. Recommended Phase 2

1. Review six duplicate-axis models and define engineering envelopes without changing raw evidence.
2. Validate representative exported models in PLECS, including custom gate-resistance tables.
3. Implement unit/condition-aware multidimensional interpolation and converter loss evaluation
   with provenance, extrapolation policy and engineering regression cases.
4. Define reviewed DPT protocols and processors, uncertainty/repeatability rules and
   real partner submission acceptance criteria.
5. Add HDF5/Zarr artifact adapters and streaming/object storage as actual workloads require.
6. Curate ratings, capacitance/gate-charge/SOA data and real IGBT/GaN/module datasets;
   retain source-specific licensing and sample identity.
7. Resolve code licensing/attribution and data redistribution terms before distribution.

All work remains in the local working tree; no commit, push or remote pull request
was created as part of this refactor.
