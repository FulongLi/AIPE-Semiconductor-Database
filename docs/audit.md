# Pre-refactor audit

The starting checkout contained 507 files (including four tracked bytecode caches),
no Python project metadata, no executable tests, and a one-line `PEDeviceLib` README.
All files were inventoried before edits. All 163 XML, 326 JSON, and six Python files
were structurally inspected; XML tags/attributes and JSON schemas were scanned across
the complete corpus. The source PDF is retained as evidence, not used to infer ratings.

| Area | Finding | V3 disposition |
| --- | --- | --- |
| `DUTs/` | 163 Wolfspeed SiC models: 119 discrete, 44 modules; one manufacturer guide | Move byte-for-byte to `data/raw/wolfspeed/`, record SHA-256 manifest |
| `standard_database/` | 163 V1 JSON mirrors of PLECS; namespace and custom tables lost | Retain under `legacy/v1/` as migration inputs |
| `standard_database_v2/` | 163 alternative JSON objects; source points filtered and assumptions added | Retain under `legacy/v2/`; migration labels assumptions and losses |
| `standardise_data.py` | Useful axis/scale/RC parsing concepts, but drops CustomTables | Replace with independent PLECS importer |
| `restructure_data.py` | Drops >=500 C and <=0 V points, invents 15 V gate drive and 175 C rating; guesses ratings/packages | Replace with explicit, conservative V1/V2 migrations |
| `data_router.py` | 930 lines mixing XML, MAT, HTML/PDF, plotting and CLI; coupled to V1 | Replace XML/MAT/JSON adapters and CLI; retire presentation exporters |
| `transistor.py` | 2,719-line mutable God class, unresolved `transistordatabase.*` imports, plotting/database dependencies | Remove after V3 replacement tests; no inherited code copied |
| `figure_process.py` | V1-only plotting; Cauer network handling mixed with presentation | Retire legacy plotting; independent physics extension interfaces |
| `analyze_data_structure.py` | One-off V1 report generator | Replace coverage service and reproducible migration report |
| Documentation | References missing tests/output, Windows-era paths; temperature proposal recommends destructive extrapolation | Replace README, architecture, migration and partner docs |
| `.cursor/worktrees.json` | Runs `npm install` in Python-only repo | Remove invalid setup |
| `__pycache__/`, `*.pyc` | Four committed CPython 3.9 build artifacts | Remove and ignore |

## Important data findings

All XML files use the PLECS namespace. Versions are 1.1, 1.4 and 1.6. Every device
has switching tables, two conduction tables and a Cauer network. **45 devices have
90 four-dimensional custom tables** referenced by formula-only switching models;
neither previous JSON architecture retained these. Exporting the old JSON can leave
unresolved `lookup()` expressions. V3 imports these tables without evaluating source code.

900/1000 C points and negative/zero voltage points are manufacturer model evidence,
not verified operating ratings. They must survive migration and exports. V3 flags
unusual temperatures and leaves engineering filtering to application policy.

V2 static values and identity/package assumptions are not promoted to verified
manufacturer facts. V2 migration is explicitly lossy relative to original XML;
the official corpus is rebuilt from XML, never reconstructed from V2.

## Licensing

The legacy monolith imports UPB-LEA `transistordatabase` extensively and appears
inherited, as identified in the refactor request. This checkout had no top-level
license or usable third-party attribution bundle. V3 does not copy that implementation,
assign a new blanket license to historic contributions, or change manufacturer rights.
See `LICENSING.md`. Git history remains the archive for retired code.
