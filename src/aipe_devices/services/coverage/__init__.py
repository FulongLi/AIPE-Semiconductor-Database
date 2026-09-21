from aipe_devices.domain.device import CHARACTERISTICS, PowerSemiconductorDevice
from aipe_devices.schema.enums import Availability, Freshness


class CoverageAnalyzer:
    def analyze(
        self, device: PowerSemiconductorDevice, requirements: dict[str, set[str]] | None = None
    ) -> dict[str, Availability]:
        """Availability is evidence presence, not suitability for an operating envelope."""
        result = {}
        for name in CHARACTERISTICS:
            data = getattr(device, name)
            status = data.availability
            available = {
                r.name
                for r in (*data.scalars, *data.curves)
                if r.provenance.freshness != Freshness.STALE
            }
            required = (requirements or {}).get(name, set())
            if required and not required <= available:
                status = Availability.PARTIAL if available else Availability.MISSING
            if any(
                r.provenance.freshness == Freshness.STALE for r in (*data.scalars, *data.curves)
            ):
                status = Availability.PARTIAL
            result[name] = status
        result["thermal"] = Availability.AVAILABLE if device.thermal else Availability.UNKNOWN
        result["reliability"] = (
            Availability.AVAILABLE if device.reliability else Availability.UNKNOWN
        )
        return result
