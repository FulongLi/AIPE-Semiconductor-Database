"""Thermal network services: DC resistance, Zth(t), Cauer-Foster conversion, Tj, fixed point.

Cauer ladders are converted through the exact eigen-decomposition of the symmetric
ladder matrix (pure Python Jacobi rotations; networks have a handful of stages), so
``step_response`` is the analytic response of the linear network, not a time-stepped
approximation. Case-to-sink and sink-to-ambient paths are user-supplied resistances;
the services never guess mounting conditions. The electro-thermal helper iterates
loss(Tj) -> Tj -> loss(Tj) with an explicit convergence criterion and keeps every
iteration for review.
"""

from math import exp, isfinite, sqrt
from typing import Callable

from pydantic import Field

from aipe_devices.domain.base import Model
from aipe_devices.domain.conditions import OperatingCondition
from aipe_devices.domain.curves import ScalarRecord
from aipe_devices.domain.provenance import Dependency, Provenance
from aipe_devices.domain.quality import Quality
from aipe_devices.domain.quantities import Quantity
from aipe_devices.domain.thermal import ThermalElement, ThermalNetwork
from aipe_devices.schema.enums import Lifecycle, Origin

RECIPE_FOSTER = ("cauer-to-foster-eigen", "1.0")
RECIPE_TJ = ("steady-state-junction-temperature", "1.0")


def _jacobi_eigen(matrix):
    """Eigenvalues/eigenvectors (columns) of a small symmetric matrix by cyclic Jacobi."""
    n = len(matrix)
    a = [row[:] for row in matrix]
    v = [[1.0 if i == j else 0.0 for j in range(n)] for i in range(n)]
    scale = max(1e-300, sqrt(sum(a[i][j] ** 2 for i in range(n) for j in range(n))))
    for _ in range(100):
        off = sqrt(sum(a[i][j] ** 2 for i in range(n) for j in range(n) if i != j))
        if off <= 1e-15 * scale:
            break
        for p in range(n - 1):
            for q in range(p + 1, n):
                if abs(a[p][q]) <= 1e-300:
                    continue
                theta = (a[q][q] - a[p][p]) / (2 * a[p][q])
                t = (1.0 if theta >= 0 else -1.0) / (abs(theta) + sqrt(theta * theta + 1))
                c = 1 / sqrt(t * t + 1)
                s = t * c
                for k in range(n):
                    akp, akq = a[k][p], a[k][q]
                    a[k][p] = c * akp - s * akq
                    a[k][q] = s * akp + c * akq
                for k in range(n):
                    apk, aqk = a[p][k], a[q][k]
                    a[p][k] = c * apk - s * aqk
                    a[q][k] = s * apk + c * aqk
                for k in range(n):
                    vkp, vkq = v[k][p], v[k][q]
                    v[k][p] = c * vkp - s * vkq
                    v[k][q] = s * vkp + c * vkq
    return [a[i][i] for i in range(n)], v


def _merge_zero_resistances(elements):
    """Zero Cauer resistances short two nodes together; combine their capacitances."""
    merged = []
    pending_capacitance = 0.0
    for element in elements:
        capacitance = element.capacitance.value + pending_capacitance
        if element.resistance.value == 0:
            pending_capacitance = capacitance
            continue
        merged.append((element.resistance.value, capacitance))
        pending_capacitance = 0.0
    # A trailing shorted stage sits at the reference node and carries no dynamics.
    return merged


def cauer_to_foster_terms(elements: tuple[ThermalElement, ...]) -> tuple[tuple[float, float], ...]:
    """Return Foster (R_k, tau_k) pairs equivalent to a Cauer ladder driven at node 1."""
    stages = _merge_zero_resistances(elements)
    if not stages:
        return ()
    n = len(stages)
    resistances = [r for r, _ in stages]
    capacitances = [c for _, c in stages]
    g = [[0.0] * n for _ in range(n)]
    for i in range(n):
        g[i][i] += 1.0 / resistances[i]
        if i > 0:
            g[i][i] += 1.0 / resistances[i - 1]
            g[i][i - 1] -= 1.0 / resistances[i - 1]
            g[i - 1][i] -= 1.0 / resistances[i - 1]
    s = [[-g[i][j] / sqrt(capacitances[i] * capacitances[j]) for j in range(n)] for i in range(n)]
    eigenvalues, vectors = _jacobi_eigen(s)
    terms = []
    for k, value in enumerate(eigenvalues):
        if value >= 0:
            raise ValueError("Cauer ladder produced a non-negative eigenvalue; check R/C signs")
        weight = vectors[0][k] ** 2 / capacitances[0]
        resistance = weight / (-value)
        if resistance > 1e-15 * sum(resistances):
            terms.append((resistance, -1.0 / value))
    terms.sort(key=lambda term: term[1])
    return tuple(terms)


class ThermalEvaluator:
    def steady_state_resistance(self, network: ThermalNetwork) -> Quantity:
        """Series Cauer/Foster DC resistance. Does not treat Cauer stages as Foster time constants."""
        return Quantity(value=sum(e.resistance.value for e in network.elements), unit="K/W")

    def foster_terms(self, network: ThermalNetwork) -> tuple[tuple[float, float], ...]:
        if network.topology == "Foster":
            return tuple(
                (e.resistance.value, e.resistance.value * e.capacitance.value)
                for e in network.elements
                if e.resistance.value > 0
            )
        return cauer_to_foster_terms(network.elements)

    def foster_equivalent(
        self, network: ThermalNetwork, *, result_id: str | None = None
    ) -> ThermalNetwork:
        """Exact Foster equivalent of a Cauer network as a derived record with lineage."""
        terms = self.foster_terms(network)
        if not terms:
            raise ValueError("Network has no dynamic stages")
        elements = tuple(
            ThermalElement(
                resistance=Quantity(value=r, unit="K/W"),
                capacitance=Quantity(value=tau / r, unit="J/K"),
            )
            for r, tau in terms
        )
        return ThermalNetwork(
            id=result_id or f"{network.id}:foster",
            topology="Foster",
            elements=elements,
            from_node=network.from_node,
            to_node=network.to_node,
            provenance=Provenance(
                origin=Origin.PHYSICS,
                source_ids=network.provenance.source_ids,
                lifecycle=Lifecycle.DERIVED,
                recipe_id=RECIPE_FOSTER[0],
                recipe_version=RECIPE_FOSTER[1],
                dependencies=(
                    Dependency(id=network.id, version="1"),
                    Dependency(id=RECIPE_FOSTER[0], version=RECIPE_FOSTER[1]),
                ),
            ),
        )

    def step_response(self, network: ThermalNetwork, times) -> tuple[float, ...]:
        """Zth(t) in K/W for a unit power step applied at ``from_node``."""
        terms = self.foster_terms(network)
        if any(t < 0 for t in times):
            raise ValueError("Step response needs non-negative times")
        return tuple(sum(r * (1.0 - exp(-t / tau)) for r, tau in terms) for t in times)

    def junction_temperature(
        self,
        network: ThermalNetwork,
        loss: float,
        *,
        rth_case_to_sink: float,
        sink_temperature: float,
        result_id: str = "junction-temperature",
        time: float | None = None,
    ) -> ScalarRecord:
        """Tj = T_sink + P * (Zth_jc(t) + Rth_cs); steady state when ``time`` is None."""
        if loss < 0:
            raise ValueError("Loss must be non-negative")
        if rth_case_to_sink < 0:
            raise ValueError("Case-to-sink resistance must be non-negative")
        if sink_temperature < 0:
            raise ValueError("Absolute sink temperature must be non-negative")
        if time is None:
            zth = self.steady_state_resistance(network).value
            flags = ("steady_state",)
        else:
            zth = self.step_response(network, (time,))[0]
            flags = (f"transient_step:{time:g}s",)
        value = sink_temperature + loss * (zth + rth_case_to_sink)
        condition = OperatingCondition(
            case_temperature=Quantity(value=sink_temperature + loss * rth_case_to_sink, unit="K")
        )
        return ScalarRecord(
            id=result_id,
            name="junction_temperature",
            quantity=Quantity(value=value, unit="K"),
            condition=condition,
            quality=Quality(flags=flags + ("user_supplied_case_to_sink_resistance",)),
            provenance=Provenance(
                origin=Origin.PHYSICS,
                source_ids=network.provenance.source_ids,
                lifecycle=Lifecycle.DERIVED,
                recipe_id=RECIPE_TJ[0],
                recipe_version=RECIPE_TJ[1],
                dependencies=(
                    Dependency(id=network.id, version="1"),
                    Dependency(id=RECIPE_TJ[0], version=RECIPE_TJ[1]),
                ),
            ),
        )


class IterationRecord(Model):
    iteration: int
    tj_in: float
    loss: float
    tj_out: float
    change: float


class FixedPointResult(Model):
    converged: bool
    junction_temperature: float | None
    loss: float | None
    iterations: tuple[IterationRecord, ...]
    criterion: str
    relaxation: float = Field(gt=0, le=1)
    reason: str | None = None


def electro_thermal_fixed_point(
    loss_at: Callable[[float], float],
    *,
    rth_junction_to_sink: float,
    sink_temperature: float,
    tj_initial: float,
    tolerance: float = 0.05,
    max_iterations: int = 100,
    relaxation: float = 1.0,
    tj_limit: float | None = None,
) -> FixedPointResult:
    """Damped fixed-point iteration Tj -> loss(Tj) -> T_sink + loss * Rth -> Tj.

    ``loss_at`` returns the total loss in W at a junction temperature in K; it may raise
    ValueError when the temperature leaves the evidence envelope, which ends the
    iteration with ``converged=False`` instead of extrapolating silently.
    """
    if rth_junction_to_sink < 0 or tolerance <= 0 or not 0 < relaxation <= 1:
        raise ValueError("Invalid fixed-point parameters")
    criterion = f"|Tj_out - Tj_in| < {tolerance:g} K"
    records = []
    tj = tj_initial
    for iteration in range(1, max_iterations + 1):
        try:
            loss = float(loss_at(tj))
        except ValueError as exc:
            return FixedPointResult(
                converged=False,
                junction_temperature=None,
                loss=None,
                iterations=tuple(records),
                criterion=criterion,
                relaxation=relaxation,
                reason=f"loss evaluation failed at {tj:.2f} K: {exc}",
            )
        if loss < 0 or not isfinite(loss):
            return FixedPointResult(
                converged=False,
                junction_temperature=None,
                loss=None,
                iterations=tuple(records),
                criterion=criterion,
                relaxation=relaxation,
                reason=f"non-physical loss {loss} W at {tj:.2f} K",
            )
        tj_out = sink_temperature + loss * rth_junction_to_sink
        change = tj_out - tj
        records.append(
            IterationRecord(iteration=iteration, tj_in=tj, loss=loss, tj_out=tj_out, change=change)
        )
        if abs(change) < tolerance:
            return FixedPointResult(
                converged=True,
                junction_temperature=tj_out,
                loss=loss,
                iterations=tuple(records),
                criterion=criterion,
                relaxation=relaxation,
            )
        tj = tj + relaxation * change
        if tj_limit is not None and tj > tj_limit:
            return FixedPointResult(
                converged=False,
                junction_temperature=None,
                loss=None,
                iterations=tuple(records),
                criterion=criterion,
                relaxation=relaxation,
                reason=f"junction temperature exceeded the limit {tj_limit:g} K (thermal runaway)",
            )
    return FixedPointResult(
        converged=False,
        junction_temperature=None,
        loss=None,
        iterations=tuple(records),
        criterion=criterion,
        relaxation=relaxation,
        reason=f"no convergence within {max_iterations} iterations",
    )
