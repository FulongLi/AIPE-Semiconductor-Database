"""Validate corpus identity projections using a supplied local Core checkout."""

import argparse
import importlib.util
import json
from datetime import datetime, timezone
from pathlib import Path

from aipe_devices.domain.device import PowerSemiconductorDevice
from aipe_devices.exporters.core import export_core_candidate


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("core", type=Path, help="Trusted local AIPE-Core checkout")
    args = parser.parse_args()
    validator_path = args.core.resolve() / "scripts/validate.py"
    spec = importlib.util.spec_from_file_location("aipe_core_validator", validator_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    state = json.loads(
        (args.core / "examples/dab-10kw/engineering-state.json").read_text(encoding="utf-8")
    )
    paths = sorted((Path(__file__).resolve().parents[1] / "data/canonical").glob("*.json"))
    for path in paths:
        device = PowerSemiconductorDevice.model_validate_json(path.read_text(encoding="utf-8"))
        proposal = export_core_candidate(
            device,
            role="Interchange validation candidate; no suitability assessment",
            record_uri=f"urn:aipe:semiconductor:{device.device_id}:revision:{device.revision}",
            exported_at=datetime.now(timezone.utc),
        )
        state["semiconductors"].append(proposal["component"])
        state["evidence"].append(proposal["evidence"])
    errors = module.validate_state(state)
    if errors:
        raise SystemExit("\n".join(errors))
    print(f"PASS: {len(paths)} candidate projections against local Core; no files written")


if __name__ == "__main__":
    main()
