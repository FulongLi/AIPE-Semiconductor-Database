from pydantic import Field

from .base import Model
from .curves import ScalarRecord


class ModuleComponent(Model):
    id: str
    role: str
    device_id: str | None = None
    die_count: int | None = Field(default=None, ge=1)
    terminals: tuple[str, ...] = ()


class ThermalCoupling(Model):
    from_component: str
    to_component: str
    thermal_model_id: str


class DevicePackage(Model):
    name: str | None = None
    components: tuple[ModuleComponent, ...] = ()
    parasitics: tuple[ScalarRecord, ...] = ()
    thermal_coupling: tuple[ThermalCoupling, ...] = ()
