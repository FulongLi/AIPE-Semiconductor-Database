"""Structured laboratory measurement requests derived from DAB loss-evaluation coverage gaps.

Each request item is a reviewable ``TestPlanItem`` (the existing partner interface) with
test conditions, compact sweeps, repetitions and requirements, wrapped with the
engineering question, an uncertainty target and a prioritisation score. The score is
``expected_design_benefit * current_uncertainty`` where the benefit follows the share of
the loss term in the evaluated total (or the thermal headroom) and the uncertainty
follows the evidence that backs the term today. Nothing here operates equipment;
double-pulse tests at bus voltage are hazardous and stay draft until reviewed.
"""

from pydantic import Field

from aipe_devices.domain.base import Model
from aipe_devices.domain.conditions import OperatingCondition
from aipe_devices.domain.device import PowerSemiconductorDevice
from aipe_devices.domain.measurement import MeasurementProtocol
from aipe_devices.domain.quantities import Quantity
from aipe_devices.measurement.plans import SweepAxis, TestPlanItem
from aipe_devices.measurement.request_generator import MeasurementRequest
from aipe_devices.services.loss.dab import DABLossResult

SCHEMA = "aipe-prioritised-measurement-request/0.1"
SAFETY = (
    "No measurement is executed automatically; every item is a draft for laboratory review.",
    "Double-pulse and static tests at DC-bus voltage involve lethal voltages and stored "
    "energy; a reviewed safety procedure, interlocks and discharge means are prerequisites.",
    "Junction-temperature sweeps above 150 degC need the datasheet maximum confirmed first.",
)


class MeasurementPriority(Model):
    item_id: str
    engineering_question: str
    expected_design_benefit: float = Field(ge=0, le=1)
    benefit_basis: str
    current_uncertainty: float = Field(ge=0, le=1)
    uncertainty_basis: str
    score: float = Field(ge=0, le=1)
    uncertainty_target: str
    rank: int = Field(ge=1)


class PrioritisedMeasurementRequest(Model):
    request_schema: str = Field(default=SCHEMA, alias="schema")
    request: MeasurementRequest
    priorities: tuple[MeasurementPriority, ...]
    context: dict
    safety: tuple[str, ...] = SAFETY

    model_config = {
        "extra": "forbid",
        "frozen": True,
        "allow_inf_nan": False,
        "populate_by_name": True,
    }


def _round_values(values, step):
    rounded = []
    for v in values:
        r = round(v / step) * step
        if r > 0 and r not in rounded:
            rounded.append(r)
    return tuple(rounded)


def _coverage_status(result: DABLossResult, quantity_prefix: str):
    for note in result.coverage:
        if note.quantity.startswith(quantity_prefix):
            return note.status
    return None


def _uncertainty(status, evidence_present: bool):
    """Map evidence status to a current-uncertainty weight."""
    if not evidence_present:
        return 1.0, "no evidence in the record"
    table = {
        "exact": (0.35, "manufacturer model point at the operating coordinates, unmeasured"),
        "interpolated": (0.45, "manufacturer model interpolated between source points, unmeasured"),
        "approximated": (0.6, "approximation of manufacturer model data, unmeasured"),
        "extrapolated": (0.8, "extrapolated beyond the manufacturer model envelope"),
        "not_evaluated": (0.9, "term not evaluated"),
        "unavailable": (1.0, "quantity unavailable"),
    }
    return table.get(status, (0.6, "unmeasured manufacturer data"))


def generate_dab_measurement_requests(
    device: PowerSemiconductorDevice,
    result: DABLossResult,
    *,
    thermal_headroom: float | None = None,
    design_tj_limit: float = 398.15,
    ambient_temperature: float = 313.15,
    request_id: str | None = None,
    physical_sample_id: str | None = None,
) -> PrioritisedMeasurementRequest:
    op = result.operating_point
    tj = op.junction_temperature.value
    vdc = op.dc_bus_voltage.value
    stress = result.stress
    breakdown = result.breakdown()
    total = result.total_loss or 0.0

    def share(name):
        value = breakdown.get(name)
        return 0.0 if not value or total <= 0 else min(1.0, value / total)

    i_rms = stress.current_rms
    i_peak = max(abs(stress.current_peak_forward or i_rms), abs(stress.current_peak_reverse or 0.0))
    i_off = max([abs(c) for c in stress.turn_off_currents] or [i_rms])
    current_step = 1.0 if i_peak < 50 else 5.0
    temperatures = (298.15, 348.15, 398.15, 423.15, 448.15)
    gate_on = op.gate_voltage_on
    gate_off = op.gate_voltage_off
    fixed_gate = OperatingCondition(gate_voltage_on=gate_on, gate_voltage_off=gate_off)
    items = []
    priorities = []

    def add(item, question, benefit, benefit_basis, status, evidence_present, target):
        uncertainty, basis = _uncertainty(status, evidence_present)
        items.append(item)
        priorities.append(
            dict(
                item_id=item.id,
                engineering_question=question,
                expected_design_benefit=round(min(max(benefit, 0.0), 1.0), 4),
                benefit_basis=benefit_basis,
                current_uncertainty=uncertainty,
                uncertainty_basis=basis,
                uncertainty_target=target,
            )
        )

    conduction_present = bool(device.conduction.curves or device.conduction.scalars)
    currents = _round_values(
        (0.25 * i_peak, 0.5 * i_peak, 0.75 * i_peak, i_peak, 1.25 * i_peak), current_step
    )
    add(
        TestPlanItem(
            id="static-iv-channel",
            protocol=MeasurementProtocol(
                id="AIPE-STATIC", version="1.0", category="static_conduction"
            ),
            fixed_conditions=OperatingCondition(gate_voltage_on=gate_on, gate_state="on"),
            sweep_axes=(
                SweepAxis(parameter="drain_current", unit="A", values=currents),
                SweepAxis(parameter="junction_temperature", unit="K", values=temperatures),
            ),
            requested_metrics=("voltage_drop",),
            repetitions=3,
            notes=f"Gate-on output characteristic over the actual current range of {stress.switch_id} "
            f"(I_rms {i_rms:.1f} A, peak {i_peak:.1f} A); pulsed measurement to hold Tj.",
            requirements=(
                "Pulsed drain current to keep self-heating below 1 K per point.",
                *SAFETY[:1],
            ),
            draft=True,
        ),
        "What is the channel voltage drop at the operating currents and temperatures?",
        share("conduction_loss"),
        f"conduction loss is {share('conduction_loss'):.0%} of the evaluated total",
        _coverage_status(result, "conduction_voltage_drop_at_tj"),
        conduction_present,
        "voltage_drop +/-2 % (k=2) per point",
    )
    add(
        TestPlanItem(
            id="rds-on-vs-tj",
            protocol=MeasurementProtocol(
                id="AIPE-STATIC", version="1.0", category="static_conduction"
            ),
            fixed_conditions=OperatingCondition(
                gate_voltage_on=gate_on,
                drain_current=Quantity(value=_round_values((i_rms,), current_step)[0], unit="A"),
                gate_state="on",
            ),
            sweep_axes=(
                SweepAxis(parameter="junction_temperature", unit="K", values=temperatures),
            ),
            requested_metrics=("rds_on",),
            repetitions=3,
            notes=f"On-resistance versus junction temperature at the RMS switch current; the record "
            f"has no Rds(on) scalar and the evaluation at {tj - 273.15:.0f} degC relies on the "
            "voltage_drop tensor between manufacturer temperature points.",
            requirements=(*SAFETY[:1],),
            draft=True,
        ),
        "How does the on-resistance scale with junction temperature at the operating current?",
        share("conduction_loss"),
        "conduction loss share; Rds(on)(Tj) drives the electro-thermal fixed point",
        _coverage_status(result, "rds_on_vs_tj"),
        "rds_on" in {r.name for r in device.conduction.scalars} or conduction_present,
        "rds_on +/-3 % (k=2) per temperature",
    )
    voltages = _round_values((0.5 * vdc, 0.75 * vdc, vdc, 1.1 * vdc), 10.0)
    off_currents = _round_values(
        (0.25 * i_off, 0.5 * i_off, 0.75 * i_off, i_off, 1.25 * i_off), current_step
    )
    rg_values = []
    for value in (1.0, 2.0, 4.7, 10.0):
        rg_values.append(value)
    for parameter in ("gate_resistance_on", "gate_resistance_off"):
        requested = getattr(op, parameter)
        if requested is not None and requested.value not in rg_values:
            rg_values.append(requested.value)
    rg_values = tuple(sorted(set(rg_values)))
    hard_turn_on = bool(breakdown.get("turn_on_loss"))
    switching_present = bool(device.switching.curves or device.switching.scalars)
    add(
        TestPlanItem(
            id="dpt-eoff-eon",
            protocol=MeasurementProtocol(id="AIPE-DPT", version="1.0", category="dpt"),
            fixed_conditions=fixed_gate,
            sweep_axes=(
                SweepAxis(parameter="dc_bus_voltage", unit="V", values=voltages),
                SweepAxis(parameter="drain_current", unit="A", values=off_currents),
                SweepAxis(parameter="gate_resistance_on", unit="Ohm", values=rg_values),
                SweepAxis(parameter="gate_resistance_off", unit="Ohm", values=rg_values),
                SweepAxis(
                    parameter="junction_temperature", unit="K", values=(298.15, 398.15, 423.15)
                ),
            ),
            requested_metrics=("Eon", "Eoff", "dv_dt", "di_dt", "Vds_peak"),
            repetitions=5,
            notes=f"Double-pulse Eoff/Eon around the actual commutation point of {stress.switch_id}: "
            f"{vdc:g} V, {i_off:.1f} A turn-off current, requested Rg "
            f"{op.gate_resistance_on.value if op.gate_resistance_on else '?'} / "
            f"{op.gate_resistance_off.value if op.gate_resistance_off else '?'} Ohm. The complementary "
            "device of the same type is the freewheeling element (DAB bridge leg).",
            requirements=(
                "Same-type complementary switch as freewheeling device; record dead time and gate driver.",
                "Deskew current and voltage probes; document integration windows per AIPE-DPT.",
                *SAFETY[1:2],
            ),
            draft=True,
        ),
        "What are the turn-off (and hard turn-on) energies at the actual bus voltage, commutation "
        "current, junction temperature and gate resistances?",
        share("turn_off_loss") + (share("turn_on_loss") if hard_turn_on else 0.0),
        f"switching loss is {share('turn_off_loss') + share('turn_on_loss'):.0%} of the evaluated total; "
        "gate-resistance dependence comes from a manufacturer formula or is absent",
        "approximated"
        if _coverage_status(result, "rg_dependence_Eoff") == "approximated"
        else _coverage_status(result, "Eoff"),
        switching_present,
        "Eoff/Eon +/-5 % (k=2) per point; dv/dt +/-10 %",
    )
    reverse_present = bool(device.reverse_conduction.curves or device.reverse_conduction.scalars)
    reverse_currents = tuple(-c for c in reversed(currents))
    reverse_share = share("conduction_loss_reverse")
    reverse_basis = "reverse-conduction loss share from the waveform integral"
    if breakdown.get("conduction_loss_reverse") is None:
        fraction = stress.reverse_charge_fraction
        if fraction is not None:
            reverse_share = share("conduction_loss") * fraction
            reverse_basis = (
                f"conduction share times the reverse charge fraction {fraction:.0%} of the "
                "conducted charge (summary metrics cannot separate the reverse term)"
            )
        else:
            reverse_share = 0.5 * share("conduction_loss")
            reverse_basis = (
                "reverse share unknown; half of the conduction share assumed for priority"
            )
    for gate_state, item_id, note in (
        (
            "off",
            "reverse-conduction-body-diode",
            "gate off: body-diode/third-quadrant drop during dead time",
        ),
        (
            "on",
            "reverse-conduction-synchronous",
            "gate on: channel reverse conduction (synchronous rectification)",
        ),
    ):
        add(
            TestPlanItem(
                id=item_id,
                protocol=MeasurementProtocol(
                    id="AIPE-REVERSE", version="1.0", category="reverse_conduction"
                ),
                fixed_conditions=OperatingCondition(
                    gate_voltage_on=gate_on if gate_state == "on" else None,
                    gate_voltage_off=gate_off if gate_state == "off" else None,
                    gate_state=gate_state,
                ),
                sweep_axes=(
                    SweepAxis(parameter="drain_current", unit="A", values=reverse_currents),
                    SweepAxis(parameter="junction_temperature", unit="K", values=temperatures),
                ),
                requested_metrics=("voltage_drop",),
                repetitions=3,
                notes=f"Third-quadrant characteristic, {note}; negative drain current is source-to-drain.",
                requirements=("Pulsed measurement; record the gate bias used.", *SAFETY[:1]),
                draft=True,
            ),
            "What is the reverse (source-to-drain) voltage drop with the gate off and on?",
            reverse_share * (0.3 if gate_state == "off" else 1.0),
            reverse_basis
            + (
                "; dead-time body-diode intervals are a fraction of the reverse intervals"
                if gate_state == "off"
                else ""
            ),
            _coverage_status(result, "dead_time_body_diode_conduction")
            if gate_state == "off"
            else _coverage_status(result, "conduction_voltage_drop_at_tj"),
            reverse_present,
            "voltage_drop +/-2 % (k=2) per point",
        )
    capacitance_present = bool(device.capacitance.curves or device.capacitance.scalars)
    zvs = all(stress.zvs_turn_on) if stress.zvs_turn_on else False
    add(
        TestPlanItem(
            id="coss-eoss",
            protocol=MeasurementProtocol(id="AIPE-CAP", version="1.0", category="capacitance"),
            fixed_conditions=OperatingCondition(
                junction_temperature=Quantity(value=298.15, unit="K"), gate_voltage_off=gate_off
            ),
            sweep_axes=(
                SweepAxis(
                    parameter="drain_source_voltage",
                    unit="V",
                    values=_round_values(tuple(vdc * k / 20 for k in range(1, 23)), 10.0),
                ),
            ),
            requested_metrics=("coss", "Eoss", "qoss"),
            repetitions=3,
            notes="Nonlinear output capacitance, stored energy and charge up to 110 % of the bus voltage "
            "for the charge-based ZVS check (current condition met: "
            f"{zvs}) and the Coss-related turn-on residual.",
            requirements=(
                "Small-signal C-V plus large-signal charge method; state both.",
                *SAFETY[:1],
            ),
            draft=True,
        ),
        "Is the commutation charge available during the dead time sufficient for complete ZVS, and "
        "what residual turn-on loss remains?",
        0.4 if zvs else 0.8,
        "ZVS current condition is met in the waveform but cannot be verified without Coss/Qoss; "
        "turn-on loss is assumed zero",
        _coverage_status(result, "coss"),
        capacitance_present,
        "coss +/-5 %, Eoss/qoss +/-5 % (k=2)",
    )
    thermal_present = bool(device.thermal)
    if thermal_headroom is None:
        thermal_benefit = 0.5
        thermal_basis = "junction temperature not estimated; default medium benefit"
    else:
        span = max(design_tj_limit - ambient_temperature, 1.0)
        thermal_benefit = min(1.0, max(0.0, 1.0 - thermal_headroom / span))
        thermal_basis = (
            f"headroom {thermal_headroom:.1f} K to the design limit over a {span:.0f} K span"
        )
    pulse_widths = (1e-5, 3e-5, 1e-4, 3e-4, 1e-3, 3e-3, 1e-2, 3e-2, 1e-1, 3e-1, 1.0)
    add(
        TestPlanItem(
            id="zth-junction-case",
            protocol=MeasurementProtocol(id="AIPE-THERMAL", version="1.0", category="thermal"),
            fixed_conditions=OperatingCondition(case_temperature=Quantity(value=298.15, unit="K")),
            sweep_axes=(SweepAxis(parameter="pulse_width", unit="s", values=pulse_widths),),
            requested_metrics=("thermal_impedance",),
            repetitions=3,
            notes="Transient thermal impedance junction-to-case to validate the manufacturer Cauer "
            f"network ({'present' if thermal_present else 'absent'}) used for Tj; use a "
            "temperature-sensitive electrical parameter calibrated per sample.",
            requirements=("Controlled case temperature; report the TSEP calibration.", *SAFETY[:1]),
            draft=True,
        ),
        "Does the junction-to-case thermal impedance match the manufacturer network used for the "
        "junction-temperature estimate?",
        thermal_benefit,
        thermal_basis,
        "approximated" if thermal_present else "unavailable",
        thermal_present,
        "Zth(t) +/-10 % (k=2) per pulse width",
    )
    add(
        TestPlanItem(
            id="package-thermal-interface",
            protocol=MeasurementProtocol(id="AIPE-THERMAL", version="1.0", category="thermal"),
            fixed_conditions=OperatingCondition(case_temperature=Quantity(value=348.15, unit="K")),
            requested_metrics=("rth_jc", "rth_cs"),
            repetitions=3,
            notes="Steady-state junction-to-case and case-to-sink resistance with the intended thermal "
            "interface material and mounting force; the screening uses a user-supplied Rth(c-s).",
            requirements=("State TIM, mounting torque/force and heat-sink flatness.", *SAFETY[:1]),
            draft=True,
        ),
        "What are the actual package and interface thermal resistances for the chosen mounting?",
        thermal_benefit,
        thermal_basis + "; Rth(c-s) is a user assumption",
        "unavailable",
        False,
        "rth_jc, rth_cs +/-10 % (k=2)",
    )
    for p in priorities:
        p["score"] = round(p["expected_design_benefit"] * p["current_uncertainty"], 4)
    priorities.sort(key=lambda p: -p["score"])
    ranked = tuple(MeasurementPriority(**p, rank=i + 1) for i, p in enumerate(priorities))
    request = MeasurementRequest(
        id=request_id or f"request:dab:{device.device_id}:{stress.switch_id}",
        device_id=device.device_id,
        physical_sample_id=physical_sample_id,
        test_plan_items=tuple(items),
    )
    context = {
        "device_id": device.device_id,
        "device_revision": device.revision,
        "switch_id": stress.switch_id,
        "operating_point": op.model_dump(mode="json", exclude_none=True),
        "loss_breakdown_W": {k: v for k, v in breakdown.items() if v is not None},
        "coverage": [n.model_dump(mode="json") for n in result.coverage],
        "waveform_dataset_sha256": stress.dataset_sha256,
        "prioritisation": "score = expected_design_benefit * current_uncertainty",
    }
    return PrioritisedMeasurementRequest(request=request, priorities=ranked, context=context)
