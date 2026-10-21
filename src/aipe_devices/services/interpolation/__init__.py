"""Bounded linear interpolation over canonical tensors with an explicit operating envelope.

``Interpolator`` is the original one-dimensional Phase-1 service. ``NDInterpolator``
adds multilinear evaluation of N-dimensional ``Curve`` tensors. Both return new
derived records and never modify source evidence. Manufacturer PLECS tables carry
extrapolation guard rows at 900/1000 degC; ``EnvelopePolicy`` drops those rows and
rejects coordinates outside the remaining source envelope unless extrapolation is
explicitly permitted, in which case the result is flagged and its origin becomes
``extrapolated``.
"""

from bisect import bisect_left
from itertools import product
from typing import Literal

from pydantic import Field

from aipe_devices.domain.base import Model
from aipe_devices.domain.conditions import ConditionParameter
from aipe_devices.domain.curves import Curve, ScalarRecord
from aipe_devices.domain.provenance import Dependency, Provenance
from aipe_devices.domain.quality import Quality
from aipe_devices.domain.quantities import Quantity
from aipe_devices.schema.enums import Freshness, Lifecycle, Origin

GUARD_TEMPERATURE_K = 773.15
"""Junction-temperature source points at or above 500 degC are model guard rows."""

RECIPE_ND = ("linear-nd", "1.0")


class EnvelopePolicy(Model):
    """Which source coordinates count as evidence and whether leaving them is permitted."""

    max_junction_temperature: float = Field(default=GUARD_TEMPERATURE_K, gt=0)
    drop_guard_rows: bool = True
    allow_extrapolation: bool = False
    extrapolation: Literal["linear", "hold_nearest"] = "linear"


class AxisEvaluation(Model):
    axis: str
    unit: str
    coordinate: float
    lower: float
    upper: float
    exact: bool
    extrapolated: bool
    bracket: tuple[float, float]
    dropped_points: tuple[float, ...] = ()


class TensorValue(Model):
    value: float
    axes: tuple[AxisEvaluation, ...]
    extrapolated: bool
    flags: tuple[str, ...]


class PreparedTensor:
    """Guard-row-filtered view of one curve that can be evaluated repeatedly."""

    def __init__(self, curve: Curve, policy: EnvelopePolicy | None = None):
        self.curve = curve
        self.policy = policy or EnvelopePolicy()
        if curve.provenance.freshness == Freshness.STALE:
            raise ValueError("Cannot interpolate stale evidence")
        keep = []
        self.dropped = {}
        for axis in curve.axes:
            indices = tuple(
                i
                for i, v in enumerate(axis.values)
                if not (
                    self.policy.drop_guard_rows
                    and axis.name == "junction_temperature"
                    and v >= self.policy.max_junction_temperature
                )
            )
            if not indices:
                raise ValueError(f"Envelope policy removes every {axis.name} source point")
            kept = set(indices)
            self.dropped[axis.name] = tuple(v for i, v in enumerate(axis.values) if i not in kept)
            grid = tuple(axis.values[i] for i in indices)
            if any(b <= a for a, b in zip(grid, grid[1:])):
                raise ValueError(
                    f"Interpolation requires strictly increasing unique {axis.name} coordinates"
                )
            keep.append(indices)
        self.grids = {a.name: tuple(a.values[i] for i in k) for a, k in zip(curve.axes, keep)}
        self.units = {a.name: a.unit for a in curve.axes}
        self.names = tuple(a.name for a in curve.axes)
        self.strides = _strides([len(a.values) for a in curve.axes])
        self.shape = tuple(len(k) for k in keep)
        # Reindex the filtered tensor once; last axis varies fastest.
        self.values = tuple(
            curve.values[sum(o * s for o, s in zip(original, self.strides))]
            for original in product(*keep)
        )
        self.filtered_strides = _strides(self.shape)

    def envelope(self, axis: str) -> tuple[float, float]:
        grid = self.grids[axis]
        return grid[0], grid[-1]

    def _locate(self, axis: str, x: float) -> tuple[int, int, float, AxisEvaluation]:
        grid = self.grids[axis]
        lower, upper = grid[0], grid[-1]
        extrapolated = not lower <= x <= upper
        if extrapolated and not self.policy.allow_extrapolation:
            raise ValueError(
                f"{axis} coordinate {x} {self.units[axis]} is outside the source envelope "
                f"[{lower}, {upper}] of {self.curve.id}; extrapolation requires "
                "allow_extrapolation=True in the envelope policy"
            )
        if len(grid) == 1:
            if x != grid[0]:
                raise ValueError(
                    f"{axis} has a single source point {grid[0]}; cannot evaluate at {x}"
                )
            i0 = i1 = 0
            fraction = 0.0
            exact = True
            extrapolated = False
        elif extrapolated:
            if self.policy.extrapolation == "hold_nearest":
                i0 = i1 = 0 if x < lower else len(grid) - 1
                fraction = 0.0
            elif x < lower:
                i0, i1 = 0, 1
                fraction = (x - grid[0]) / (grid[1] - grid[0])
            else:
                i0, i1 = len(grid) - 2, len(grid) - 1
                fraction = (x - grid[i0]) / (grid[i1] - grid[i0])
            exact = False
        else:
            index = bisect_left(grid, x)
            if grid[index] == x:
                i0 = i1 = index
                fraction = 0.0
                exact = True
            else:
                i0, i1 = index - 1, index
                fraction = (x - grid[i0]) / (grid[i1] - grid[i0])
                exact = False
        evaluation = AxisEvaluation(
            axis=axis,
            unit=self.units[axis],
            coordinate=x,
            lower=lower,
            upper=upper,
            exact=exact,
            extrapolated=extrapolated,
            bracket=(grid[i0], grid[i1]),
            dropped_points=self.dropped[axis],
        )
        return i0, i1, fraction, evaluation

    def value(self, coordinates: dict[str, float]) -> TensorValue:
        missing = set(self.names) - set(coordinates)
        unknown = set(coordinates) - set(self.names)
        if missing or unknown:
            raise ValueError(
                f"Coordinates must name every tensor axis exactly once; missing={sorted(missing)}"
                f" unknown={sorted(unknown)}"
            )
        corners = []
        evaluations = []
        for name in self.names:
            i0, i1, fraction, evaluation = self._locate(name, coordinates[name])
            corners.append(((i0, 1.0 - fraction), (i1, fraction)) if i0 != i1 else ((i0, 1.0),))
            evaluations.append(evaluation)
        total = 0.0
        for corner in product(*corners):
            weight = 1.0
            offset = 0
            for (index, w), stride in zip(corner, self.filtered_strides):
                weight *= w
                offset += index * stride
            if weight:
                total += weight * self.values[offset]
        flags = []
        for evaluation in evaluations:
            if evaluation.dropped_points:
                flags.append(f"guard_rows_dropped:{evaluation.axis}")
            if evaluation.extrapolated:
                flags.append(f"extrapolated:{evaluation.axis}")
            elif not evaluation.exact:
                flags.append(f"interpolated:{evaluation.axis}")
        return TensorValue(
            value=total,
            axes=tuple(evaluations),
            extrapolated=any(e.extrapolated for e in evaluations),
            flags=tuple(flags),
        )


def _strides(shape):
    strides = []
    stride = 1
    for n in reversed(list(shape)):
        strides.append(stride)
        stride *= n
    return tuple(reversed(strides))


class NDInterpolator:
    def prepare(self, curve: Curve, policy: EnvelopePolicy | None = None) -> PreparedTensor:
        return PreparedTensor(curve, policy)

    def evaluate(
        self,
        curve: Curve,
        coordinates: dict[str, Quantity],
        *,
        result_id: str,
        input_version: str,
        policy: EnvelopePolicy | None = None,
    ) -> ScalarRecord:
        """Multilinear evaluation returning a derived record with explicit lineage and flags."""
        prepared = self.prepare(curve, policy)
        for name, quantity in coordinates.items():
            if name in prepared.units and quantity.unit != prepared.units[name]:
                raise ValueError(f"Coordinate unit {quantity.unit} does not match axis {name}")
        result = prepared.value({k: q.value for k, q in coordinates.items()})
        condition = curve.condition.model_copy(
            update={
                "extensions": (
                    *curve.condition.extensions,
                    *(
                        ConditionParameter(name=f"axis:{name}", quantity=coordinates[name])
                        for name in prepared.names
                    ),
                )
            }
        )
        return ScalarRecord(
            id=result_id,
            name=curve.name,
            quantity=Quantity(value=result.value, unit=curve.unit),
            condition=condition,
            quality=Quality(flags=result.flags),
            provenance=Provenance(
                origin=Origin.EXTRAPOLATED if result.extrapolated else Origin.INTERPOLATED,
                source_ids=curve.provenance.source_ids,
                lifecycle=Lifecycle.DERIVED,
                recipe_id=RECIPE_ND[0],
                recipe_version=RECIPE_ND[1],
                dependencies=(
                    Dependency(id=curve.id, version=input_version),
                    Dependency(id=RECIPE_ND[0], version=RECIPE_ND[1]),
                ),
            ),
        )


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
