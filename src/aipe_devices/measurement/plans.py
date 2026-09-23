"""Compact, protocol-local test plans. No Cartesian product is materialized."""

from math import isclose, prod

from pydantic import Field, model_validator

from aipe_devices.domain.base import Model
from aipe_devices.domain.conditions import CONDITION_UNITS, OperatingCondition
from aipe_devices.domain.measurement import MeasurementProtocol
from aipe_devices.domain.quantities import Unit

PARAMETER_UNITS = {**CONDITION_UNITS, "drain_source_voltage": "V"}


class SweepRange(Model):
    start: float
    stop: float
    step: float = Field(gt=0)

    @model_validator(mode="after")
    def valid_range(self):
        steps = (self.stop - self.start) / self.step
        if steps < 0 or not isclose(steps, round(steps), abs_tol=1e-9, rel_tol=1e-12):
            raise ValueError("Sweep stop must be on the ascending inclusive step grid")
        return self

    @property
    def count(self):
        return round((self.stop - self.start) / self.step) + 1


class SweepAxis(Model):
    parameter: str
    unit: Unit
    values: tuple[float, ...] | None = None
    range: SweepRange | None = None

    @model_validator(mode="after")
    def valid_axis(self):
        if self.unit != PARAMETER_UNITS.get(self.parameter):
            raise ValueError(f"Unknown sweep parameter or incorrect SI unit: {self.parameter}")
        if (self.values is None) == (self.range is None):
            raise ValueError("Specify either explicit values or a compact range")
        if self.values is not None and (
            not self.values or len(set(self.values)) != len(self.values)
        ):
            raise ValueError("Sweep values must be nonempty and unique")
        lower = min(self.values) if self.values else self.range.start
        upper = max(self.values) if self.values else self.range.stop
        if self.unit == "K" and lower < 0:
            raise ValueError("Negative absolute temperature")
        if self.parameter == "duty_cycle" and not 0 <= lower <= upper <= 1:
            raise ValueError("Duty cycle must be in [0, 1]")
        return self

    @property
    def count(self):
        return len(self.values) if self.values is not None else self.range.count

    def index(self, value: float) -> int | None:
        if self.values is not None:
            return next((i for i, v in enumerate(self.values) if v == value), None)
        i = round((value - self.range.start) / self.range.step)
        expected = self.range.start + i * self.range.step
        if 0 <= i < self.count and isclose(value, expected, abs_tol=1e-10, rel_tol=1e-12):
            return i
        return None


def condition_values(condition):
    result = {n: getattr(condition, n) for n in CONDITION_UNITS if getattr(condition, n)}
    result.update({p.name: p.quantity for p in condition.extensions})
    return result


class TestPlanItem(Model):
    __test__ = False
    id: str = Field(min_length=1)
    protocol: MeasurementProtocol
    fixed_conditions: OperatingCondition = OperatingCondition()
    sweep_axes: tuple[SweepAxis, ...] = ()
    requested_metrics: tuple[str, ...] = ()
    repetitions: int = Field(default=1, ge=1)
    notes: str | None = None
    requirements: tuple[str, ...] = ()
    draft: bool = False

    @model_validator(mode="after")
    def unique_parameters(self):
        names = [a.parameter for a in self.sweep_axes]
        if (
            len(names) != len(set(names))
            or set(names) & condition_values(self.fixed_conditions).keys()
        ):
            raise ValueError("Sweep parameters must be unique and not shadow fixed conditions")
        if len(set(self.requested_metrics)) != len(self.requested_metrics):
            raise ValueError("Requested metrics must be unique")
        return self

    @property
    def point_count(self):
        return prod(a.count for a in self.sweep_axes)

    def match(self, protocol, condition):
        """Return a coordinate key, allowing additional recorded run conditions."""
        if protocol != self.protocol:
            return None
        actual = condition_values(condition)
        if any(actual.get(k) != v for k, v in condition_values(self.fixed_conditions).items()):
            return None
        if (
            self.fixed_conditions.gate_state != "unknown"
            and condition.gate_state != self.fixed_conditions.gate_state
        ):
            return None
        coordinates = []
        for axis in self.sweep_axes:
            q = actual.get(axis.parameter)
            index = axis.index(q.value) if q and q.unit == axis.unit else None
            if index is None:
                return None
            coordinates.append(index)
        return tuple(coordinates)
