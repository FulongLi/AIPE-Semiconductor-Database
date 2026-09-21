from aipe_devices.services.coverage import CoverageAnalyzer


class DeviceComparator:
    def coverage(self, devices, requirements=None):
        return {d.device_id: CoverageAnalyzer().analyze(d, requirements) for d in devices}
