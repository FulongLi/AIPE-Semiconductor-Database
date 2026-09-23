"""Small renderer-neutral Device Explorer API. Fetch one selected device at a time."""

from aipe_devices.domain.device import CHARACTERISTICS
from aipe_devices.services.coverage.gaps import coverage_gaps
from aipe_devices.visualization import VisualizationBuilder


class DeviceExplorer:
    def __init__(self, repository):
        self.repository = repository

    def search(self, query):
        return tuple(
            {
                "device_id": d.device_id,
                "manufacturer": d.identity.manufacturer,
                "part_number": d.identity.part_number,
            }
            for d in self.repository.search(query)
        )

    def summary(self, device_id):
        device = self.repository.get(device_id)
        report = coverage_gaps(device)
        sections = ["overview", "sources"]
        sections.extend(
            n for n in CHARACTERISTICS if getattr(device, n).curves or getattr(device, n).scalars
        )
        sections.extend(n for n in ("thermal", "reliability", "models") if getattr(device, n))
        # Measurement and market references are exposed as links, not populated panels.
        return {
            "device_id": device.device_id,
            "identity": device.identity.model_dump(mode="json"),
            "classification": device.classification.model_dump(mode="json"),
            "coverage": report.model_dump(mode="json"),
            "sections": sections,
            "measurement_ids": device.measurement_ids,
            "market_reference_ids": device.market_reference_ids,
        }

    def characteristics(self, device_id):
        device = self.repository.get(device_id)
        return tuple(
            {
                "group": group,
                "id": c.id,
                "quantity": c.name,
                "axes": [a.name for a in c.axes],
                "unit": c.unit,
            }
            for group in CHARACTERISTICS
            for c in getattr(device, group).curves
        )

    def raw_record(self, device_id, record_id):
        from aipe_devices.services.validation import records

        device = self.repository.get(device_id)
        return next((r.model_dump(mode="json") for r in records(device) if r.id == record_id), None)

    def visualize(self, device_id, record_ids, *, fixed=None, x=None, y=None):
        device = self.repository.get(device_id)
        curves = {c.id: c for group in CHARACTERISTICS for c in getattr(device, group).curves}
        builder = VisualizationBuilder(
            device_id=device_id, device_revision=device.revision, sources=device.provenance
        )
        specs = []
        for record_id in record_ids:
            curve = curves[record_id]
            if x and y:
                specs.append(builder.surface(curve, x=x, y=y, fixed=fixed))
            elif x:
                specs.append(builder.line(curve, x=x, fixed=fixed))
            else:
                specs.append(builder.auto(curve, fixed=fixed))
        if not specs:
            raise ValueError("Select at least one actual curve")
        return builder.overlay(*specs) if len(specs) > 1 else specs[0]
