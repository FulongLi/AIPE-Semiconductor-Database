from math import exp

import pytest

from aipe_devices.domain.provenance import Provenance
from aipe_devices.domain.thermal import ThermalElement, ThermalNetwork
from aipe_devices.services.thermal import (
    ThermalEvaluator,
    cauer_to_foster_terms,
    electro_thermal_fixed_point,
)

PROVENANCE = Provenance(origin="manufacturer_model", source_ids=("s",))


def network(topology, pairs, **kwargs):
    return ThermalNetwork(
        id="net",
        topology=topology,
        provenance=PROVENANCE,
        elements=tuple(
            ThermalElement(
                resistance={"value": r, "unit": "K/W"}, capacitance={"value": c, "unit": "J/K"}
            )
            for r, c in pairs
        ),
        **kwargs,
    )


def test_foster_step_response_is_analytic():
    foster = network("Foster", ((1.0, 1.0), (0.5, 4.0)))
    evaluator = ThermalEvaluator()
    times = (0.0, 0.5, 2.0, 50.0)
    expected = tuple(1.0 * (1 - exp(-t / 1.0)) + 0.5 * (1 - exp(-t / 2.0)) for t in times)
    assert evaluator.step_response(foster, times) == pytest.approx(expected)
    assert evaluator.steady_state_resistance(foster).value == 1.5


def test_single_stage_cauer_equals_foster():
    cauer = network("Cauer", ((0.5, 0.01),))
    terms = cauer_to_foster_terms(cauer.elements)
    assert len(terms) == 1
    assert terms[0] == pytest.approx((0.5, 0.005))


def test_cauer_to_foster_preserves_dc_resistance_and_matches_state_space(device):
    cauer = device.thermal[0]
    evaluator = ThermalEvaluator()
    foster = evaluator.foster_equivalent(cauer)
    assert foster.topology == "Foster"
    assert foster.provenance.origin == "physics_derived"
    assert foster.provenance.dependencies[0].id == cauer.id
    assert sum(e.resistance.value for e in foster.elements) == pytest.approx(
        evaluator.steady_state_resistance(cauer).value
    )
    times = (1e-5, 1e-4, 1e-3, 1e-2, 1e-1, 1.0)
    zth = evaluator.step_response(cauer, times)
    assert zth == pytest.approx(evaluator.step_response(foster, times))
    assert all(a < b for a, b in zip(zth, zth[1:]))
    np = pytest.importorskip("numpy")
    linalg = pytest.importorskip("scipy.linalg")
    r = [e.resistance.value for e in cauer.elements]
    c = [e.capacitance.value for e in cauer.elements]
    n = len(r)
    g = np.zeros((n, n))
    for i in range(n):
        g[i, i] += 1 / r[i]
        if i:
            g[i, i] += 1 / r[i - 1]
            g[i, i - 1] -= 1 / r[i - 1]
            g[i - 1, i] -= 1 / r[i - 1]
    a = -np.diag(1 / np.array(c)) @ g
    b = np.zeros(n)
    b[0] = 1 / c[0]
    reference = [float(np.linalg.solve(a, (linalg.expm(a * t) - np.eye(n)) @ b)[0]) for t in times]
    assert zth == pytest.approx(reference, rel=1e-9, abs=1e-12)


def test_zero_resistance_stages_are_merged():
    cauer = network("Cauer", ((0.0, 0.5), (1.0, 1.0)))
    terms = cauer_to_foster_terms(cauer.elements)
    assert len(terms) == 1
    assert terms[0] == pytest.approx((1.0, 1.5))


def test_junction_temperature_record_uses_user_supplied_interface():
    cauer = network("Cauer", ((0.5, 0.01), (0.5, 0.1)))
    record = ThermalEvaluator().junction_temperature(
        cauer, 20.0, rth_case_to_sink=0.3, sink_temperature=330.0
    )
    assert record.quantity.value == pytest.approx(330.0 + 20.0 * 1.3)
    assert record.quantity.unit == "K"
    assert record.condition.case_temperature.value == pytest.approx(336.0)
    assert "user_supplied_case_to_sink_resistance" in record.quality.flags
    assert record.provenance.origin == "physics_derived"
    transient = ThermalEvaluator().junction_temperature(
        cauer, 20.0, rth_case_to_sink=0.3, sink_temperature=330.0, time=1e-4
    )
    assert transient.quantity.value < record.quantity.value
    with pytest.raises(ValueError):
        ThermalEvaluator().junction_temperature(
            cauer, -1.0, rth_case_to_sink=0.3, sink_temperature=330.0
        )


def test_fixed_point_converges_to_analytic_solution_and_records_iterations():
    a, b, rth, sink = 10.0, 0.05, 1.0, 313.15

    def loss_at(tj):
        return a + b * tj

    result = electro_thermal_fixed_point(
        loss_at, rth_junction_to_sink=rth, sink_temperature=sink, tj_initial=398.15, tolerance=1e-6
    )
    expected = (sink + rth * a) / (1 - rth * b)
    assert result.converged
    assert result.junction_temperature == pytest.approx(expected, abs=1e-5)
    assert result.loss == pytest.approx(a + b * expected, abs=1e-4)
    assert result.iterations[0].tj_in == 398.15
    assert all(
        later.change <= earlier.change or abs(later.change) < abs(earlier.change)
        for earlier, later in zip(result.iterations, result.iterations[1:])
    )
    assert result.criterion.startswith("|Tj_out - Tj_in|")


def test_fixed_point_reports_runaway_and_evidence_failures():
    runaway = electro_thermal_fixed_point(
        lambda tj: 10.0 + 0.5 * tj,
        rth_junction_to_sink=4.0,
        sink_temperature=313.15,
        tj_initial=350.0,
        tj_limit=500.0,
    )
    assert not runaway.converged and "runaway" in runaway.reason

    def envelope(tj):
        if tj > 420:
            raise ValueError("outside the source envelope")
        return 100.0

    failed = electro_thermal_fixed_point(
        envelope, rth_junction_to_sink=2.0, sink_temperature=313.15, tj_initial=398.15
    )
    assert not failed.converged and "outside the source envelope" in failed.reason
    exhausted = electro_thermal_fixed_point(
        lambda tj: 10.0,
        rth_junction_to_sink=1.0,
        sink_temperature=313.15,
        tj_initial=398.15,
        max_iterations=1,
        relaxation=0.01,
    )
    assert not exhausted.converged and "no convergence" in exhausted.reason
