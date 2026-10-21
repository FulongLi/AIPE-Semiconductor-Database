# AIPE — Semiconductor Database

AIPE Semiconductor Database is the canonical power-semiconductor data infrastructure of **AI for Power
Engineering**. The Python package `aipe-devices` gives manufacturer models, datasheets, laboratory
measurements and derived results one versioned semantic vocabulary with explicit units, operating conditions
and evidence lineage, so that device comparison, converter evaluation and AI-assisted design rest on
traceable data. Its `aipe.yaml` advertises the capabilities to AIPE-Registry; the domain schema is 3.0.0 and
a documented mapping relates device identity and evidence to the AIPE-Core Engineering State 0.1.0.

## Features

- Canonical corpus of 163 Wolfspeed SiC devices (119 discrete, 44 module models) rebuilt from the preserved
  manufacturer XML, which is kept byte-identical under `data/raw/`
- Pydantic domain models for Si MOSFET, IGBT, SiC and GaN identities, packages, sample/lot distinctions,
  reliability records and market observations
- Import adapters (PLECS XML, Excel/CSV/JSON libraries, datasheet transcriptions) with SI normalisation and
  schema plus engineering validation; exporters to PLECS, MATLAB and JSON
- Services: coverage analysis, bounded 1-D and N-D interpolation, Cauer/Foster thermal models,
  dual-active-bridge switch-loss evaluation, evidence-tiered device screening and prioritised measurement
  requests
- Measurement-partner interface (`MeasurementRequest` / `MeasurementPackage`) and a renderer-neutral Device
  Explorer API
- Append-only repository: manufacturer and measured evidence is never overwritten

## Installation

Python 3.10 or newer; Pydantic is the only core runtime dependency. Source datasets stay in the checkout
and are not bundled into the wheel.

```sh
python -m pip install -e '.[dev]'
```

## Usage

```python
from aipe_devices.repository.json_repository import JsonDeviceRepository
from aipe_devices.services.coverage import CoverageAnalyzer

repo = JsonDeviceRepository("data/canonical")
device = repo.get("wolfspeed_c2m0025120d")
print(device.identity.part_number)
print(CoverageAnalyzer().analyze(device))
print([d.device_id for d in repo.search("C2M0025")])
```

```sh
aipe-devices validate-package examples/measurement_package/manifest.json
pytest -q
```

Export, PLECS import, legacy migration, library import, the Device Explorer and the DAB loss-evaluation
commands are described in [docs/usage.md](docs/usage.md).

## Project Information

- Version: 3.1.0 (`pyproject.toml`, package `aipe-devices`; domain schema 3.0.0)
- Status: Alpha (`aipe.yaml`: status `active`, maturity `usable`; no measured evidence backs any loss
  result)
- Developer: Fulong Li
- Organisation: Spirit Connect / AIPE Labs
- License: not declared. No repository licence has been selected (`aipe.yaml`: `NOASSERTION`;
  `pyproject.toml` ships [LICENSING.md](LICENSING.md) instead of an SPDX identifier). Manufacturer data in
  `data/raw/` keeps Wolfspeed's rights; LICENSING.md covers code, data and historical-contribution rights.

## Documentation

- [Usage: query, export, import, migration, measurement packages, Device Explorer, DAB losses](docs/usage.md)
- [Limitations and roadmap](docs/limitations.md)
- [Architecture and invariants](docs/architecture.md) · [Core integration](docs/core-integration.md)
- [DAB loss evaluation and screening](docs/dab-loss-screening.md) ·
  [Phase-2 library import and Explorer](docs/phase2.md) ·
  [Measurement partner interface](docs/measurement.md) · [Migration](docs/migration.md)
- [JSON Schemas](docs/schemas/) · [Candidate records](data/candidates/README.md) · [Audit](docs/audit.md) ·
  [Refactor report](docs/refactor-report.md)
- [CHANGELOG.md](CHANGELOG.md) · [LICENSING.md](LICENSING.md) · [Capability manifest](aipe.yaml)
