# Retired files

Replacement tests passed before removal. Git history remains the archive.

| Deleted path | Reason |
| --- | --- |
| `.cursor/worktrees.json` | Invalid npm setup in a Python repository. |
| `__pycache__/data_router.cpython-39.pyc` | Committed interpreter cache; ignored by V3. |
| `analyze_data_structure.py` | One-off V1 analysis replaced by coverage and reproducible migration reports. |
| `data_preprocess/EVALUATION_REPORT.md` | Stale legacy instructions, missing test references or destructive normalization proposal; superseded by V3 docs. |
| `data_preprocess/__pycache__/data_router.cpython-39.pyc` | Committed interpreter cache; ignored by V3. |
| `data_preprocess/__pycache__/standardise_data.cpython-39.pyc` | Committed interpreter cache; ignored by V3. |
| `data_preprocess/restructure_data.py` | Old competing schema pipeline replaced by explicit import and migration adapters. |
| `data_preprocess/standardise_data.py` | Old competing schema pipeline replaced by explicit import and migration adapters. |
| `data_process/README.md` | Stale legacy instructions, missing test references or destructive normalization proposal; superseded by V3 docs. |
| `data_process/__pycache__/figure_process.cpython-39.pyc` | Committed interpreter cache; ignored by V3. |
| `data_process/figure_process.py` | V1-only plotting/report pipeline retired; no Phase-1 presentation replacement. |
| `data_router.py` | Mixed V1 router replaced by independent PLECS/MAT/JSON adapters; HTML/PDF retired. |
| `transistor.py` | Inherited monolith with unresolved dependencies; replaced by independent AIPE domain/services. |
| `数据特征总结.md` | Stale legacy instructions, missing test references or destructive normalization proposal; superseded by V3 docs. |
| `温度轴统一方案讨论.md` | Stale legacy instructions, missing test references or destructive normalization proposal; superseded by V3 docs. |

## Moves, not deletions

- `DUTs/` → `data/raw/wolfspeed/`: 164 raw files, byte-identical.
- `standard_database/` → `legacy/v1/`: 163 JSON files, byte-identical.
- `standard_database_v2/` → `legacy/v2/`: 163 JSON files, byte-identical.
- `README.md` rewritten; `images/logo.png` retained.
