"""Rebuild reviewable candidate records from the datasheet transcriptions in data/candidates.

Candidate records are not canonical evidence. They link to canonical records of the
same manufacturer/part when one exists so that screening can combine datasheet
ratings with manufacturer model tensors without merging the two kinds of evidence.
"""

import sys
from pathlib import Path

from aipe_devices.importers.datasheet import DatasheetImporter, write_candidates
from aipe_devices.repository.json_repository import JsonDeviceRepository

ROOT = Path(__file__).resolve().parents[1]


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    transcriptions = [Path(p) for p in argv] or sorted((ROOT / "data/candidates").glob("*.yaml"))
    importer = DatasheetImporter(JsonDeviceRepository(ROOT / "data/canonical"))
    imports = []
    for path in transcriptions:
        imports.extend(importer.load(path))
    report = write_candidates(imports, ROOT / "data/candidates/records")
    linked = sum(1 for c in report["candidates"] if c["canonical_link"])
    print(
        f"Wrote {len(report['candidates'])} candidate records "
        f"({linked} linked to canonical records) to data/candidates/records"
    )


if __name__ == "__main__":
    main()
