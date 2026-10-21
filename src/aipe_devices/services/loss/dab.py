"""Dual-active-bridge switch-position loss evaluation from canonical tensors.

The evaluator implements the ``LossEvaluator`` protocol for one switch position of a
DAB bridge. It combines a canonical device record (conduction, third-quadrant and
Eon/Eoff tensors, PLECS gate-resistance bindings) with actual converter stress from
the AIPE waveform summary or a sampled waveform. Every quantity that the record does
not carry is listed in ``coverage`` instead of being estimated. Results are derived
records with ``physics_derived`` origin and lineage to the tensor IDs.
"""

from typing import Literal

from aipe_devices.domain.base import Model
from aipe_devices.domain.conditions import OperatingCondition
from aipe_devices.domain.curves import Curve, ScalarRecord
from aipe_devices.domain.device import PowerSemiconductorDevice
from aipe_devices.domain.provenance import Dependency, Provenance
from aipe_devices.domain.quality import Quality
from aipe_devices.domain.quantities import Quantity
from aipe_devices.schema.enums import Lifecycle, Origin
from aipe_devices.services.interpolation import EnvelopePolicy, PreparedTensor

from .plecs_formula import FormulaError, formula_variables, gate_resistance_factor
from .stress import SwitchStress, trapezoid

RECIPE = ("dab-switch-loss", "1.0")
ReversePolicy = Literal["gate_aware", "body_diode", "channel"]
CoverageStatus = Literal[
    "unavailable", "approximated", "interpolated", "extrapolated", "not_evaluated", "exact"
]


class CoverageNote(Model):
    quantity: str
    status: CoverageStatus
    detail: str
    affects: tuple[str, ...] = ()


class LossComponent(Model):
    name: str
    value: float | None = None
    unit: Literal["W"] = "W"
    available: bool = True
    method: str
    flags: tuple[str, ...] = ()
    energies_per_event: tuple[float, ...] = ()
    evidence: tuple[str, ...] = ()


class DABLossResult(Model):
    device_id: str
    device_revision: int
    switch_id: str
    operating_point: OperatingCondition
    stress: SwitchStress
    components: tuple[LossComponent, ...]
    total_loss: float | None
    complete: bool
    records: tuple[ScalarRecord, ...]
    coverage: tuple[CoverageNote, ...]
    warnings: tuple[str, ...]
    evidence_origins: dict[str, str]
    recipe: dict[str, str] = {"id": RECIPE[0], "version": RECIPE[1]}

    def breakdown(self) -> dict[str, float | None]:
        return {c.name: c.value for c in self.components}


def _select_curve(curves, name, required, prefer=None):
    matches = [
        c
        for c in curves
        if c.name == name and required <= {a.name for a in c.axes} and c.unit in {"J", "V"}
    ]
    if not matches:
        return None
    if prefer:
        with_axis = [c for c in matches if prefer in {a.name for a in c.axes}]
        if with_axis:
            return with_axis[0]
    return min(matches, key=lambda c: len(c.axes))


def _axis_note(quantity, evaluation, affects):
    axis = evaluation.axes
    for a in axis:
        if a.extrapolated:
            return CoverageNote(
                quantity=quantity,
                status="extrapolated",
                detail=f"{a.axis} {a.coordinate} {a.unit} outside source [{a.lower}, {a.upper}]",
                affects=affects,
            )
    inexact = [a for a in axis if not a.exact]
    if inexact:
        detail = "; ".join(
            f"{a.axis} {a.coordinate:g} {a.unit} between source points {a.bracket[0]:g} and "
            f"{a.bracket[1]:g}"
            for a in inexact
        )
        return CoverageNote(
            quantity=quantity, status="interpolated", detail=detail, affects=affects
        )
    return CoverageNote(
        quantity=quantity,
        status="exact",
        detail="All coordinates coincide with source points",
        affects=affects,
    )


class DABLossEvaluator:
    """LossEvaluator for a DAB switch position; stress is supplied at construction."""

    def __init__(
        self,
        stress: SwitchStress,
        *,
        policy: EnvelopePolicy | None = None,
        reverse_conduction: ReversePolicy = "gate_aware",
        events_per_period: int = 1,
        zvs_turn_on: bool | None = None,
        threshold_fraction: float = 0.01,
    ):
        self.stress = stress
        self.policy = policy or EnvelopePolicy()
        self.reverse_conduction = reverse_conduction
        self.events_per_period = events_per_period
        self.zvs_override = zvs_turn_on
        self.threshold_fraction = threshold_fraction

    def evaluate(
        self, *, device: PowerSemiconductorDevice, operating_point: OperatingCondition
    ) -> tuple[ScalarRecord, ...]:
        return self.evaluate_detailed(device=device, operating_point=operating_point).records

    # -- helpers -----------------------------------------------------------------------
    def _rg_factor(self, device, curve, operating_point, metric, warnings, coverage):
        parameter = "gate_resistance_on" if metric == "Eon" else "gate_resistance_off"
        requested = getattr(operating_point, parameter)
        axis_names = {a.name for a in curve.axes}
        if parameter in axis_names:
            if requested is None:
                raise ValueError(f"{curve.id} has a {parameter} axis; the operating point needs it")
            return 1.0, "tensor_axis", ()
        if requested is None:
            coverage.append(
                CoverageNote(
                    quantity=f"rg_dependence_{metric}",
                    status="not_evaluated",
                    detail="Operating point does not specify the external gate resistance; "
                    "table reference gate resistance applies",
                    affects=(metric,),
                )
            )
            return 1.0, "table_reference_rg", ()
        for model in device.models:
            if model.format != "plecs":
                continue
            metadata = model.adapter_metadata
            for binding in metadata.get("bindings", ()):
                if binding.get("curve_id") != curve.id or not binding.get("formula"):
                    continue
                formula = binding["formula"]
                try:
                    names = formula_variables(formula) - {"E"}
                except FormulaError as exc:
                    warnings.append(f"{metric}: stored formula not usable ({exc})")
                    break
                if len(names) != 1:
                    warnings.append(f"{metric}: formula variables {sorted(names)} not understood")
                    break
                variable = names.pop()
                limits = next(
                    (v for v in metadata.get("variables", ()) if v.get("Name") == variable), {}
                )
                flags = ["rg_scaling:plecs_formula"]
                try:
                    low = float(limits.get("MinValue", "nan"))
                    high = float(limits.get("MaxValue", "nan"))
                except ValueError:
                    low = high = float("nan")
                if low == low and high == high and not low <= requested.value <= high:
                    if not self.policy.allow_extrapolation:
                        raise ValueError(
                            f"{parameter} {requested.value} Ohm is outside the PLECS model range "
                            f"[{low}, {high}] for {curve.id}; set allow_extrapolation=True"
                        )
                    flags.append(f"extrapolated:{parameter}")
                    warnings.append(
                        f"{metric}: gate resistance {requested.value} Ohm outside model range "
                        f"[{low}, {high}]"
                    )
                try:
                    factor = gate_resistance_factor(formula, variable, requested.value)
                except FormulaError as exc:
                    warnings.append(f"{metric}: stored formula not usable ({exc})")
                    break
                coverage.append(
                    CoverageNote(
                        quantity=f"rg_dependence_{metric}",
                        status="approximated",
                        detail=f"Manufacturer PLECS formula {formula!r} scales the table by "
                        f"{factor:.4f} at {requested.value} Ohm",
                        affects=(metric,),
                    )
                )
                return factor, "plecs_formula", tuple(flags)
        coverage.append(
            CoverageNote(
                quantity=f"rg_dependence_{metric}",
                status="unavailable",
                detail="No gate-resistance axis or scaling formula; energy evaluated at the "
                "table's unspecified reference gate resistance",
                affects=(metric,),
            )
        )
        return 1.0, "no_rg_dependence", ("rg_dependence_unavailable",)

    def _energy_tensor(self, device, metric, operating_point):
        parameter = "gate_resistance_on" if metric == "Eon" else "gate_resistance_off"
        prefer = parameter if getattr(operating_point, parameter) is not None else None
        curve = _select_curve(
            device.switching.curves, metric, {"junction_temperature", "dc_bus_voltage", "current"}
        )
        if prefer:
            curve = _select_curve(
                device.switching.curves,
                metric,
                {"junction_temperature", "dc_bus_voltage", "current"},
                prefer=prefer,
            )
        return curve

    # -- evaluation --------------------------------------------------------------------
    def evaluate_detailed(
        self, *, device: PowerSemiconductorDevice, operating_point: OperatingCondition
    ) -> DABLossResult:
        op = operating_point
        for name in ("junction_temperature", "dc_bus_voltage", "switching_frequency"):
            if getattr(op, name) is None:
                raise ValueError(f"Operating point requires {name}")
        tj = op.junction_temperature.value
        vdc = op.dc_bus_voltage.value
        fsw = op.switching_frequency.value
        stress = self.stress
        warnings = list(stress.notes)
        coverage: list[CoverageNote] = []
        used: dict[str, Curve] = {}
        components: list[LossComponent] = []
        if stress.switching_frequency and abs(stress.switching_frequency - fsw) > 0.01 * fsw:
            warnings.append(
                f"Operating point frequency {fsw:g} Hz differs from the waveform window "
                f"({stress.switching_frequency:g} Hz)"
            )
        if stress.blocking_voltages:
            worst = max(abs(v - vdc) for v in stress.blocking_voltages)
            if worst > 0.02 * vdc:
                warnings.append(
                    f"Blocking voltage after turn-off deviates from dc_bus_voltage by {worst:g} V"
                )
        if stress.v_ds_max is not None and stress.v_ds_max > 1.05 * vdc:
            warnings.append(f"Waveform v_ds_max {stress.v_ds_max:g} V exceeds the bus by >5 %")

        forward = _select_curve(
            device.conduction.curves, "voltage_drop", {"junction_temperature", "current"}
        )
        reverse = _select_curve(
            device.reverse_conduction.curves, "voltage_drop", {"junction_temperature", "current"}
        )
        self._conduction(device, forward, reverse, tj, stress, used, components, coverage, warnings)
        self._turn_off(device, op, tj, vdc, fsw, stress, used, components, coverage, warnings)
        self._turn_on(device, op, tj, vdc, fsw, stress, used, components, coverage, warnings)
        self._static_coverage(device, op, used, coverage)

        by_name = {c.name: c for c in components}
        switching = [by_name["turn_off_loss"], by_name["turn_on_loss"]]
        if all(c.available for c in switching):
            components.append(
                LossComponent(
                    name="switching_loss",
                    value=sum(c.value for c in switching),
                    method="turn_off_loss + turn_on_loss",
                    evidence=tuple(sorted({e for c in switching for e in c.evidence})),
                )
            )
        primary = [by_name["conduction_loss"], by_name["turn_off_loss"], by_name["turn_on_loss"]]
        complete = all(c.available for c in primary)
        total = (
            sum(c.value for c in primary if c.available)
            if any(c.available for c in primary)
            else None
        )
        components.append(
            LossComponent(
                name="total_loss",
                value=total,
                available=total is not None,
                method="conduction_loss + turn_off_loss + turn_on_loss"
                + ("" if complete else " (incomplete: unavailable terms excluded)"),
                flags=() if complete else ("total_incomplete",),
                evidence=tuple(sorted({e for c in primary for e in c.evidence})),
            )
        )
        records = self._records(device, op, stress, components, used)
        return DABLossResult(
            device_id=device.device_id,
            device_revision=device.revision,
            switch_id=stress.switch_id,
            operating_point=op,
            stress=stress.without_waveform(),
            components=tuple(components),
            total_loss=total,
            complete=complete,
            records=records,
            coverage=tuple(dict.fromkeys(coverage)),
            warnings=tuple(dict.fromkeys(warnings)),
            evidence_origins={cid: str(c.provenance.origin) for cid, c in used.items()},
        )

    def _conduction(self, device, forward, reverse, tj, stress, used, components, cov, warn):
        unavailable = []
        if forward is None:
            cov.append(
                CoverageNote(
                    quantity="conduction_voltage_drop",
                    status="unavailable",
                    detail="No gate-on voltage_drop tensor over (junction_temperature, current)",
                    affects=("conduction_loss",),
                )
            )
            for name in ("conduction_loss_forward", "conduction_loss_reverse", "conduction_loss"):
                unavailable.append(
                    LossComponent(name=name, available=False, method="no conduction evidence")
                )
            components.extend(unavailable)
            return
        fwd = PreparedTensor(forward, self.policy)
        used[forward.id] = forward
        rev = None
        if reverse is not None:
            rev = PreparedTensor(reverse, self.policy)
            used[reverse.id] = reverse
        flags = []
        if fwd.dropped.get("junction_temperature"):
            flags.append("guard_rows_dropped:junction_temperature")
        probe = fwd.value({"junction_temperature": tj, "current": fwd.grids["current"][-1]})
        cov.append(_axis_note("conduction_voltage_drop_at_tj", probe, ("conduction_loss",)))
        policy = self.reverse_conduction
        if stress.waveform is None:
            if policy == "body_diode":
                raise ValueError(
                    "The body_diode reverse-conduction policy needs a sampled waveform; "
                    "summary metrics cannot separate reverse-current intervals"
                )
            irms = stress.current_rms
            if irms <= 0:
                value = 0.0
            else:
                point = fwd.value({"junction_temperature": tj, "current": irms})
                value = point.value / irms * irms**2
                flags.extend(f for f in point.flags if f.startswith("extrapolated"))
            components.append(
                LossComponent(
                    name="conduction_loss_forward",
                    available=False,
                    method="not separable from summary metrics",
                    evidence=(forward.id,),
                )
            )
            components.append(
                LossComponent(
                    name="conduction_loss_reverse",
                    available=False,
                    method="not separable from summary metrics",
                    evidence=(forward.id,),
                )
            )
            components.append(
                LossComponent(
                    name="conduction_loss",
                    value=value,
                    method="rms_equivalent_secant_resistance: v(Tj, I_rms)/I_rms * I_rms^2 "
                    "from the gate-on voltage_drop tensor",
                    flags=tuple(flags + ["method:rms_equivalent_resistance"]),
                    evidence=(forward.id,),
                )
            )
            cov.append(
                CoverageNote(
                    quantity="conduction_waveform_integral",
                    status="approximated",
                    detail="Summary metrics only: conduction loss uses the secant on-resistance at "
                    "I_rms; reverse-current intervals are assumed channel-conducted "
                    "(synchronous rectification)",
                    affects=("conduction_loss",),
                )
            )
            cov.append(
                CoverageNote(
                    quantity="dead_time_body_diode_conduction",
                    status="not_evaluated",
                    detail="No gate timing in summary metrics; dead-time third-quadrant "
                    "conduction is not evaluated",
                    affects=("conduction_loss_reverse",),
                )
            )
            return
        waveform = stress.waveform
        t, i = waveform.time, waveform.current
        gate = waveform.gate
        level = None
        if gate is not None:
            level = 0.5 * (max(gate) + min(gate))
        lower_fwd, _ = fwd.envelope("current")
        p_fwd = []
        p_rev = []
        body_samples = 0
        channel_fallback = 0
        forward_while_off = 0.0
        peak = max(abs(x) for x in i) or 1.0
        threshold = self.threshold_fraction * peak
        for k, current in enumerate(i):
            gate_on = None if gate is None else gate[k] >= level
            if abs(current) <= 1e-15:
                p_fwd.append(0.0)
                p_rev.append(0.0)
                continue
            if current > 0:
                if gate_on is False and current > threshold and k + 1 < len(t):
                    forward_while_off += t[k + 1] - t[k]
                drop = fwd.value({"junction_temperature": tj, "current": current}).value
                p_fwd.append(drop * current)
                p_rev.append(0.0)
                continue
            use_body = policy == "body_diode" or (policy == "gate_aware" and gate_on is False)
            if use_body:
                if rev is not None:
                    body_samples += 1
                    drop = rev.value({"junction_temperature": tj, "current": current}).value
                else:
                    channel_fallback += 1
                    drop = fwd.value({"junction_temperature": tj, "current": current}).value
            elif lower_fwd < 0:
                drop = fwd.value({"junction_temperature": tj, "current": current}).value
            elif rev is not None:
                channel_fallback += 1
                drop = rev.value({"junction_temperature": tj, "current": current}).value
            else:
                raise ValueError("No tensor covers negative switch current")
            p_rev.append(drop * current)
            p_fwd.append(0.0)
        window = waveform.window
        value_fwd = trapezoid(t, p_fwd) / window
        value_rev = trapezoid(t, p_rev) / window
        if value_fwd < 0 or value_rev < 0:
            warn.append("Negative conduction power from tensor sign convention; check tables")
        method = f"waveform_integral: mean(v(Tj, i(t)) * i(t)); reverse policy {policy}"
        flags.append("method:waveform_integral")
        if forward_while_off > 0.005 * window:
            warn.append(
                f"Forward current flows while the gate is off for {forward_while_off / window:.1%}"
                " of the window; evaluated with the gate-on table"
            )
        if channel_fallback:
            warn.append(f"{channel_fallback} samples used the other conduction table as fallback")
        evidence = (forward.id,) + ((reverse.id,) if reverse is not None else ())
        components.append(
            LossComponent(
                name="conduction_loss_forward",
                value=value_fwd,
                method=method,
                flags=tuple(flags),
                evidence=(forward.id,),
            )
        )
        components.append(
            LossComponent(
                name="conduction_loss_reverse",
                value=value_rev,
                method=method,
                flags=tuple(flags),
                evidence=evidence,
            )
        )
        components.append(
            LossComponent(
                name="conduction_loss",
                value=value_fwd + value_rev,
                method=method,
                flags=tuple(flags),
                evidence=evidence,
            )
        )
        if reverse is None:
            cov.append(
                CoverageNote(
                    quantity="third_quadrant_voltage_drop",
                    status="unavailable",
                    detail="No gate-off reverse-conduction tensor; negative current evaluated "
                    "with the gate-on table",
                    affects=("conduction_loss_reverse",),
                )
            )
        if gate is None and policy == "gate_aware":
            cov.append(
                CoverageNote(
                    quantity="dead_time_body_diode_conduction",
                    status="not_evaluated",
                    detail="Waveform has no gate signal; reverse current treated as channel "
                    "conduction",
                    affects=("conduction_loss_reverse",),
                )
            )
        elif body_samples == 0 and policy == "gate_aware":
            cov.append(
                CoverageNote(
                    quantity="dead_time_body_diode_conduction",
                    status="exact",
                    detail="No gate-off reverse-current samples in the window (zero dead time)",
                    affects=("conduction_loss_reverse",),
                )
            )

    def _turn_off(self, device, op, tj, vdc, fsw, stress, used, components, cov, warn):
        curve = self._energy_tensor(device, "Eoff", op)
        if curve is None:
            cov.append(
                CoverageNote(
                    quantity="Eoff",
                    status="unavailable",
                    detail="No Eoff tensor over (junction_temperature, dc_bus_voltage, current)",
                    affects=("turn_off_loss",),
                )
            )
            components.append(
                LossComponent(name="turn_off_loss", available=False, method="no Eoff evidence")
            )
            return
        factor, rg_method, rg_flags = self._rg_factor(device, curve, op, "Eoff", warn, cov)
        tensor = PreparedTensor(curve, self.policy)
        used[curve.id] = curve
        energies = []
        flags = list(rg_flags)
        notes = []
        peak = max([abs(x) for x in stress.turn_off_currents] + [stress.current_rms, 1e-12])
        threshold = self.threshold_fraction * peak
        for current in stress.turn_off_currents:
            if current <= threshold:
                energies.append(0.0)
                notes.append("turn-off at reverse or ~zero current: no Eoff")
                continue
            coords = {"junction_temperature": tj, "dc_bus_voltage": vdc, "current": current}
            if "gate_resistance_off" in tensor.names:
                coords["gate_resistance_off"] = op.gate_resistance_off.value
            point = tensor.value(coords)
            energies.append(point.value * factor)
            flags.extend(point.flags)
            cov.append(_axis_note("Eoff_at_operating_point", point, ("turn_off_loss",)))
        if notes:
            warn.append(f"Eoff: {len(notes)} of {len(stress.turn_off_currents)} events soft")
        expected = stress.periods * self.events_per_period
        if stress.turn_off_currents and abs(len(stress.turn_off_currents) - expected) > 0.5:
            warn.append(
                f"{len(stress.turn_off_currents)} turn-off events in {stress.periods:g} periods "
                f"(expected {expected:g})"
            )
        value = fsw * sum(energies) / stress.periods if stress.turn_off_currents else 0.0
        if not stress.turn_off_currents:
            warn.append("No turn-off events in the window; turn-off loss is zero by construction")
        components.append(
            LossComponent(
                name="turn_off_loss",
                value=value,
                method=f"f_sw * sum(Eoff(Tj, Vdc, I_off) * k_rg) / periods; Rg: {rg_method}",
                flags=tuple(dict.fromkeys(flags)),
                energies_per_event=tuple(energies),
                evidence=(curve.id,),
            )
        )

    def _zvs_flags(self, op, stress):
        if self.zvs_override is not None:
            return [self.zvs_override] * len(stress.turn_on_currents), "constructor override"
        if stress.zvs_turn_on:
            return list(stress.zvs_turn_on), "waveform current condition"
        for extension in op.extensions:
            if extension.name == "zvs_turn_on":
                flag = bool(extension.quantity.value)
                return [flag] * len(stress.turn_on_currents), "operating point extension"
        return [None] * len(stress.turn_on_currents), "unknown"

    def _turn_on(self, device, op, tj, vdc, fsw, stress, used, components, cov, warn):
        zvs, basis = self._zvs_flags(op, stress)
        curve = self._energy_tensor(device, "Eon", op)
        energies = []
        flags = []
        hard_events = 0
        peak = max([abs(x) for x in stress.turn_on_currents] + [stress.current_rms, 1e-12])
        threshold = self.threshold_fraction * peak
        factor, rg_method, rg_flags = 1.0, "not_needed", ()
        tensor = None
        for current, flag in zip(stress.turn_on_currents, zvs):
            soft = flag is True or (flag is None and current < -threshold)
            if soft:
                energies.append(0.0)
                continue
            if flag is None and abs(current) <= threshold:
                warn.append("Turn-on at ~zero current without a ZVS flag: Eon(0 A) used")
            hard_events += 1
            if curve is None:
                energies.append(None)
                continue
            if tensor is None:
                factor, rg_method, rg_flags = self._rg_factor(device, curve, op, "Eon", warn, cov)
                tensor = PreparedTensor(curve, self.policy)
                used[curve.id] = curve
                flags.extend(rg_flags)
            coords = {
                "junction_temperature": tj,
                "dc_bus_voltage": vdc,
                "current": max(current, 0.0),
            }
            if "gate_resistance_on" in tensor.names:
                coords["gate_resistance_on"] = op.gate_resistance_on.value
            point = tensor.value(coords)
            energies.append(point.value * factor)
            flags.extend(point.flags)
            cov.append(_axis_note("Eon_at_operating_point", point, ("turn_on_loss",)))
        if hard_events == 0:
            cov.append(
                CoverageNote(
                    quantity="turn_on_loss_under_zvs",
                    status="approximated",
                    detail=f"All turn-on events satisfy the ZVS condition ({basis}); turn-on "
                    "loss set to zero. Residual loss from incomplete Coss charge transfer "
                    "needs Coss/Eoss/Qoss, which are unavailable",
                    affects=("turn_on_loss",),
                )
            )
            flags.append("zvs_turn_on_assumed_lossless")
            method = f"ZVS on every event ({basis}): 0 W"
        elif curve is None:
            cov.append(
                CoverageNote(
                    quantity="Eon",
                    status="unavailable",
                    detail=f"{hard_events} hard turn-on events but no Eon tensor",
                    affects=("turn_on_loss",),
                )
            )
            components.append(
                LossComponent(
                    name="turn_on_loss",
                    available=False,
                    method="hard turn-on without Eon evidence",
                    flags=("eon_unavailable",),
                )
            )
            return
        else:
            method = f"f_sw * sum(Eon(Tj, Vdc, I_on) * k_rg) / periods; Rg: {rg_method}"
            if hard_events < len(energies):
                method += f"; {len(energies) - hard_events} ZVS events at 0 J ({basis})"
        if not stress.turn_on_currents:
            warn.append("No turn-on events in the window; turn-on loss is zero by construction")
            method = "no turn-on events: 0 W"
        value = fsw * sum(e for e in energies if e is not None) / stress.periods
        components.append(
            LossComponent(
                name="turn_on_loss",
                value=value,
                method=method,
                flags=tuple(dict.fromkeys(flags)),
                energies_per_event=tuple(e if e is not None else 0.0 for e in energies),
                evidence=(curve.id,) if tensor is not None else (),
            )
        )

    def _static_coverage(self, device, op, used, cov):
        names = {r.name for group in ("capacitance",) for r in getattr(device, group).scalars} | {
            c.name for c in device.capacitance.curves
        }
        for quantity in ("coss", "Eoss", "qoss"):
            if quantity not in names:
                cov.append(
                    CoverageNote(
                        quantity=quantity,
                        status="unavailable",
                        detail="Not in the record; charge-based ZVS verification and Coss-related "
                        "turn-on residuals cannot be evaluated",
                        affects=("turn_on_loss",),
                    )
                )
        rating_names = {r.name for r in device.ratings}
        for quantity in ("vds_max", "id_max", "tj_max"):
            if quantity not in rating_names:
                cov.append(
                    CoverageNote(
                        quantity=quantity,
                        status="unavailable",
                        detail="No rating record; voltage/current derating and junction limit "
                        "checks need a datasheet or candidate record",
                        affects=("suitability",),
                    )
                )
        if "rds_on" not in {r.name for r in device.conduction.scalars}:
            cov.append(
                CoverageNote(
                    quantity="rds_on_vs_tj",
                    status="unavailable" if not used else "approximated",
                    detail="No Rds(on) scalar records; on-resistance follows the voltage_drop "
                    "tensor at the evaluated temperature",
                    affects=("conduction_loss",),
                )
            )
        if any(c.condition.gate_voltage_on is None for c in used.values()) and (
            op.gate_voltage_on is not None or op.gate_voltage_off is not None
        ):
            cov.append(
                CoverageNote(
                    quantity="gate_voltage_dependence",
                    status="unavailable",
                    detail="Tensors carry no gate-voltage condition; the requested gate drive "
                    f"({op.gate_voltage_on.value if op.gate_voltage_on else '?'} V / "
                    f"{op.gate_voltage_off.value if op.gate_voltage_off else '?'} V) is not "
                    "represented",
                    affects=("conduction_loss", "turn_off_loss", "turn_on_loss"),
                )
            )
        if not any(r.name in {"Err", "Qrr"} for r in device.reverse_conduction.scalars) and not any(
            c.name in {"Err", "Qrr"} for c in device.reverse_conduction.curves
        ):
            cov.append(
                CoverageNote(
                    quantity="reverse_recovery",
                    status="unavailable",
                    detail="No Qrr/Err evidence; diode recovery energy during hard commutation "
                    "is not evaluated",
                    affects=("turn_on_loss",),
                )
            )
        if not device.thermal:
            cov.append(
                CoverageNote(
                    quantity="thermal_network",
                    status="unavailable",
                    detail="No junction-to-case network; junction temperature cannot be derived",
                    affects=("junction_temperature",),
                )
            )
        if used and all(str(c.provenance.origin) != "measured" for c in used.values()):
            origins = sorted({str(c.provenance.origin) for c in used.values()})
            cov.append(
                CoverageNote(
                    quantity="measured_evidence",
                    status="unavailable",
                    detail=f"All tensors originate from {', '.join(origins)}; no laboratory "
                    "measurement backs the evaluated losses",
                    affects=("conduction_loss", "turn_off_loss", "turn_on_loss"),
                )
            )

    def _records(self, device, op, stress, components, used):
        source_ids = tuple(s.id for s in device.provenance)
        dependencies = [Dependency(id=c.id, version=str(device.revision)) for c in used.values()]
        dependencies.append(Dependency(id=RECIPE[0], version=RECIPE[1]))
        if stress.dataset_sha256:
            dependencies.append(
                Dependency(
                    id=f"waveform-dataset:{stress.dataset_sha256[:16]}",
                    version="1",
                    checksum=stress.dataset_sha256,
                )
            )
        provenance = Provenance(
            origin=Origin.PHYSICS,
            source_ids=source_ids,
            lifecycle=Lifecycle.DERIVED,
            recipe_id=RECIPE[0],
            recipe_version=RECIPE[1],
            dependencies=tuple(dependencies),
        )
        records = []
        for component in components:
            if not component.available or component.value is None:
                continue
            records.append(
                ScalarRecord(
                    id=f"{device.device_id}:{stress.switch_id}:{component.name}",
                    name=component.name,
                    quantity=Quantity(value=component.value, unit="W"),
                    condition=op,
                    provenance=provenance,
                    quality=Quality(flags=component.flags),
                )
            )
            if component.energies_per_event and component.name in {
                "turn_off_loss",
                "turn_on_loss",
            }:
                energy_name = component.name.replace("_loss", "_energy_per_period")
                records.append(
                    ScalarRecord(
                        id=f"{device.device_id}:{stress.switch_id}:{energy_name}",
                        name=energy_name,
                        quantity=Quantity(
                            value=sum(component.energies_per_event) / stress.periods, unit="J"
                        ),
                        condition=op,
                        provenance=provenance,
                        quality=Quality(flags=component.flags),
                    )
                )
        return tuple(records)


def operating_point(
    *,
    junction_temperature: float,
    dc_bus_voltage: float,
    switching_frequency: float,
    gate_resistance_on: float | None = None,
    gate_resistance_off: float | None = None,
    gate_voltage_on: float | None = None,
    gate_voltage_off: float | None = None,
) -> OperatingCondition:
    """Convenience constructor with SI units (K, V, Hz, Ohm, V)."""

    def q(value, unit):
        return None if value is None else Quantity(value=value, unit=unit)

    return OperatingCondition(
        junction_temperature=q(junction_temperature, "K"),
        dc_bus_voltage=q(dc_bus_voltage, "V"),
        switching_frequency=q(switching_frequency, "Hz"),
        gate_resistance_on=q(gate_resistance_on, "Ohm"),
        gate_resistance_off=q(gate_resistance_off, "Ohm"),
        gate_voltage_on=q(gate_voltage_on, "V"),
        gate_voltage_off=q(gate_voltage_off, "V"),
    )
