# AIPE Core integration v0.1

AIPE means **AI for Power Engineering**. This database owns semiconductor records;
AIPE-Core owns portable Engineering State and contracts. Domain schema **3.0.0**
and Engineering State **0.1.0** are independent versions. Registry discovers the
repository through `aipe.yaml`; it never becomes the device database itself.

## Conservative implemented adapter

`aipe_devices.exporters.core.export_core_candidate` projects a validated device
identity to a Core semiconductor candidate plus one source evidence record. It
returns a proposal for the caller to append to `semiconductors` and `evidence`.
It never mutates the input or picks a component for a design automatically.

```python
from datetime import datetime, timezone
from aipe_devices.exporters.core import export_core_candidate

proposal = export_core_candidate(
    device,
    role="primary bridge candidate",
    record_uri=f"urn:aipe:semiconductor:{device.device_id}:revision:{device.revision}",
    exported_at=datetime.now(timezone.utc),
)
```

Resolve a domain URN with `JsonDeviceRepository` and check revision before use;
it is not an HTTP endpoint. For external interchange a commit-pinned repository
URL is preferable. Identical inputs including timestamp produce identical output.
Explicit caller timestamps describe the export, not acquisition of manufacturer
data. The output identifies candidate status, not suitability or validation.

| Database V3 | Core v0.1 projection |
| --- | --- |
| device_id + revision | Stable component/evidence IDs plus namespaced original identity |
| identity.manufacturer / part_number | semiconductor manufacturer / part_number |
| classification.technology | Si / SiC / GaN only where material is explicit |
| IGBT / diode / unknown | unspecified material; no material inferred from structure |
| canonical revision URI | database_ref and source evidence/artifact reference |
| ratings, curves, thermal networks | Retained in V3 record, not reduced automatically |
| provenance and source rights | Retained in referenced V3 record and original raw files |

Core schema base:
`https://raw.githubusercontent.com/FulongLi/AIPE-Core/v0.1.0/schemas/`.
The tag is a logical version identifier until published. To validate an assembled
state, use the complete local AIPE-Core checkout's `scripts/validate.py` offline.
No schema fetch or Core package dependency is added to the database runtime.
Do not append a proposal twice; Core entity IDs must remain unique.

For a cross-repository check of every canonical record, install the trusted Core
checkout's `requirements-dev.txt` into the test environment, then run
`python scripts/check_core_integration.py ../AIPE-Core`. This imports that local
validator, validates all projections together, and writes no device/design data.

## Evidence and rights

`source` evidence says which canonical record supplied identity. It does not
convert manufacturer models to measurement evidence. Detailed curve origin,
operating conditions, source locators, raw artifact checksums, interpolation and
derived recipe lineage remain in V3. A later quantitative adapter must preserve
these conditions explicitly and reject ambiguous rating names/units.

See [LICENSING](../LICENSING.md): existing code has unresolved blanket rights and
manufacturer data retains its own notices. `license: NOASSERTION` is intentional.
Public data availability alone does not authorize redistribution. Historical
`transistordatabase` and `PowerElectronicsDeviceLibrary` remain migration/reference
sources; this integration neither deletes them nor reimports their data.

The essential query/import/validation/JSON workflow uses Python. PLECS and MATLAB
exports remain available optional professional integrations requiring the relevant
external licence for tool execution. Exporting a file does not require those tools
to be installed and is not evidence that either simulator executed it.
