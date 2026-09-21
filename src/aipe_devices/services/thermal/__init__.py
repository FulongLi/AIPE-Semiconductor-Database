from aipe_devices.domain.quantities import Quantity
from aipe_devices.domain.thermal import ThermalNetwork


class ThermalEvaluator:
    def steady_state_resistance(self, network: ThermalNetwork) -> Quantity:
        """Series Cauer/Foster DC resistance. Does not treat Cauer stages as Foster time constants."""
        return Quantity(value=sum(e.resistance.value for e in network.elements), unit="K/W")
