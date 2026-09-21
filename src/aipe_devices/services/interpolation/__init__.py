from bisect import bisect_left

from aipe_devices.domain.curves import Curve, ScalarRecord
from aipe_devices.domain.provenance import Dependency, Provenance
from aipe_devices.domain.quantities import Quantity
from aipe_devices.schema.enums import Freshness, Lifecycle, Origin


class Interpolator:
    def evaluate(
        self, curve: Curve, coordinate: Quantity, *, result_id: str, input_version: str
    ) -> ScalarRecord:
        """Linear 1D interpolation only; explicit bounds, units, and input version."""
        if len(curve.axes) != 1:
            raise ValueError("Phase 1 interpolation requires a one-dimensional curve")
        axis = curve.axes[0]
        if coordinate.unit != axis.unit:
            raise ValueError("Coordinate unit does not match axis")
        if curve.provenance.freshness == Freshness.STALE:
            raise ValueError("Cannot interpolate stale evidence")
        if any(b <= a for a, b in zip(axis.values, axis.values[1:])):
            raise ValueError("Interpolation requires strictly increasing unique coordinates")
        x = coordinate.value
        if not axis.values[0] <= x <= axis.values[-1]:
            raise ValueError("Extrapolation requires a separate explicit policy")
        index = bisect_left(axis.values, x)
        if axis.values[index] == x:
            value = curve.values[index]
        else:
            fraction = (x - axis.values[index - 1]) / (axis.values[index] - axis.values[index - 1])
            value = curve.values[index - 1] + fraction * (
                curve.values[index] - curve.values[index - 1]
            )
        from aipe_devices.domain.conditions import ConditionParameter

        condition = curve.condition.model_copy(
            update={
                "extensions": (
                    *curve.condition.extensions,
                    ConditionParameter(name=f"axis:{axis.name}", quantity=coordinate),
                )
            }
        )
        return ScalarRecord(
            id=result_id,
            name=curve.name,
            quantity=Quantity(value=value, unit=curve.unit),
            condition=condition,
            provenance=Provenance(
                origin=Origin.INTERPOLATED,
                source_ids=curve.provenance.source_ids,
                lifecycle=Lifecycle.DERIVED,
                recipe_id="linear-1d",
                recipe_version="1.0",
                dependencies=(
                    Dependency(id=curve.id, version=input_version),
                    Dependency(id="linear-1d", version="1.0"),
                ),
            ),
        )
