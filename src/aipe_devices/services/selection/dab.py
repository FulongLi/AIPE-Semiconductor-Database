"""Automated DAB device screening from actual waveform stress.

Candidates are ranked per bridge by (1) a data-confidence tier and (2) the estimated
total loss at the evaluation junction temperature. Tier A devices carry canonical
manufacturer tensors evaluated by ``DABLossEvaluator``; tier B devices only have
datasheet points, which are scaled linearly in voltage and current and flagged as
estimates; tier C devices lack a rating or a loss term and are never ranked. The two
tiers are never interleaved, so an incomplete dataset cannot outrank complete
evidence by looking cheap. Every exclusion and every approximation is reported.
"""

from typing import Literal

from pydantic import Field

from aipe_devices.domain.base import Model
from aipe_devices.domain.device import PowerSemiconductorDevice
from aipe_devices.importers.datasheet import CandidateImport
from aipe_devices.services.interpolation import EnvelopePolicy
from aipe_devices.services.loss.dab import DABLossEvaluator, DABLossResult, operating_point
from aipe_devices.services.loss.stress import SwitchStress, stress_from_summary
from aipe_devices.services.thermal import (
    FixedPointResult,
    ThermalEvaluator,
    electro_thermal_fixed_point,
)

SCHEMA = "aipe-dab-screening/0.1"
Tier = Literal["A_canonical_tensors", "B_datasheet_points", "C_insufficient"]
Evidence = Literal["canonical_tensor", "datasheet_point", "missing"]


class ScreeningSettings(Model):
    junction_temperature: float = Field(default=398.15, gt=0)
    gate_resistance_on: float | None = Field(default=2.0, ge=0)
    gate_resistance_off: float | None = Field(default=2.0, ge=0)
    gate_voltage_on: float | None = 15.0
    gate_voltage_off: float | None = -4.0
    derating_limit: float = Field(default=0.70, gt=0, le=1)
    rth_case_to_sink: float = Field(ge=0)
    rth_sink_to_ambient: float = Field(ge=0)
    ambient_temperature: float = Field(default=313.15, gt=0)
    design_tj_limit: float = Field(default=398.15, gt=0)
    allow_extrapolation: bool = False


class LossEstimate(Model):
    evidence: Evidence
    conduction: float | None = None
    turn_off: float | None = None
    turn_on: float | None = None
    total: float | None = None
    complete: bool = False
    method: str
    flags: tuple[str, ...] = ()
    evidence_ids: tuple[str, ...] = ()
    coverage_gaps: tuple[str, ...] = ()


class ElectricalCheck(Model):
    vds_rating: float | None = None
    voltage_utilisation: float | None = None
    derating_pass: bool | None = None
    id_rating: float | None = None
    id_rating_condition: str | None = None
    rms_current_margin: float | None = None
    peak_current_margin: float | None = None
    current_pass: bool | None = None
    flags: tuple[str, ...] = ()


class ThermalCheck(Model):
    rth_junction_to_case: float | None = None
    rth_source: str | None = None
    rth_total: float | None = None
    tj_at_fixed_loss: float | None = None
    headroom_to_design_limit: float | None = None
    tj_max_rating: float | None = None
    headroom_to_rating: float | None = None
    fixed_point: FixedPointResult | None = None
    flags: tuple[str, ...] = ()


class Confidence(Model):
    score: float = Field(ge=0, le=1)
    tier: Tier
    components: dict[str, float]
    reasons: tuple[str, ...]


class CandidateAssessment(Model):
    candidate_id: str | None
    canonical_id: str | None
    manufacturer: str
    part_number: str
    package: str | None
    integration: str
    bridge: str
    electrical: ElectricalCheck
    loss: LossEstimate
    thermal: ThermalCheck
    confidence: Confidence
    eligible: bool
    rank: int | None = None
    reasons: tuple[str, ...]


class BridgeScreening(Model):
    bridge: str
    dc_bus_voltage: float
    worst_case_switch: str
    stress: SwitchStress
    ranked: tuple[CandidateAssessment, ...]
    excluded: tuple[CandidateAssessment, ...]
    ranking_rule: str = (
        "Eligible devices sorted by confidence tier (A before B), then by estimated total "
        "loss at the evaluation temperature; tier B values are datasheet-point estimates "
        "and are not comparable with tier A tensor evaluations"
    )


class ScreeningReport(Model):
    screening_schema: str = Field(default=SCHEMA, alias="schema")
    settings: ScreeningSettings
    dataset_sha256: str | None
    switching_frequency: float
    bridges: tuple[BridgeScreening, ...]
    pool: tuple[str, ...]
    notes: tuple[str, ...]

    model_config = {
        "extra": "forbid",
        "frozen": True,
        "allow_inf_nan": False,
        "populate_by_name": True,
    }


class DevicePool(Model):
    """One manufacturer/part with optional canonical and candidate evidence."""

    manufacturer: str
    part_number: str
    canonical: PowerSemiconductorDevice | None = None
    candidate: CandidateImport | None = None

    @property
    def label(self):
        return f"{self.manufacturer} {self.part_number}"


def build_pool(candidates, canonical_repository=None, extra_canonical_ids=()):
    """Merge candidate records with their linked canonical records by identity."""
    pool = {}
    for item in candidates:
        canonical = None
        link = item.dossier.canonical_link
        if link is not None and canonical_repository is not None:
            canonical = canonical_repository.get(link.device_id)
        key = (item.device.identity.manufacturer.lower(), item.device.identity.part_number.lower())
        pool[key] = DevicePool(
            manufacturer=item.device.identity.manufacturer,
            part_number=item.device.identity.part_number,
            canonical=canonical,
            candidate=item,
        )
    for device_id in extra_canonical_ids:
        device = canonical_repository.get(device_id)
        key = (device.identity.manufacturer.lower(), device.identity.part_number.lower())
        if key in pool:
            pool[key] = pool[key].model_copy(update={"canonical": device})
        else:
            pool[key] = DevicePool(
                manufacturer=device.identity.manufacturer,
                part_number=device.identity.part_number,
                canonical=device,
            )
    return tuple(pool.values())


def _tj_interpolate(points, tj, flags, label):
    """Linear interpolation between datasheet temperature points; never beyond them."""
    points = sorted(points, key=lambda p: p[0])
    if len(points) == 1 or tj <= points[0][0] or tj >= points[-1][0]:
        nearest = min(points, key=lambda p: abs(p[0] - tj))
        if abs(nearest[0] - tj) > 1e-9:
            flags.append(
                f"{label}:nearest_datasheet_temperature_{nearest[0] - 273.15:.0f}degC_used"
            )
        return nearest[1]
    for (t0, v0), (t1, v1) in zip(points, points[1:]):
        if t0 <= tj <= t1:
            flags.append(
                f"{label}:linear_in_tj_between_{t0 - 273.15:.0f}_and_{t1 - 273.15:.0f}degC"
            )
            return v0 + (v1 - v0) * (tj - t0) / (t1 - t0)
    return points[-1][1]


def _group_rds_on(device, settings):
    records = [r for r in device.conduction.scalars if r.name == "rds_on"]
    typical = [r for r in records if str(r.statistic) in {"typical", "unspecified"}]
    pool = typical or records
    groups = {}
    for r in pool:
        if r.condition.junction_temperature is None:
            continue
        key = (
            r.condition.gate_voltage_on.value if r.condition.gate_voltage_on else None,
            r.condition.drain_current.value if r.condition.drain_current else None,
        )
        groups.setdefault(key, []).append(r)
    if not groups:
        return None, ()

    def preference(item):
        key, members = item
        vgs_match = settings.gate_voltage_on is not None and key[0] == settings.gate_voltage_on
        return (
            len({m.condition.junction_temperature.value for m in members}),
            vgs_match,
            key[0] or 0,
        )

    key, members = max(groups.items(), key=preference)
    return members, key


def _datasheet_energy(device, metric, settings, vdc):
    records = [r for r in device.switching.scalars if r.name == metric]
    if not records:
        return None
    body = [
        r for r in records if any(f.startswith("freewheeling:body_diode") for f in r.quality.flags)
    ]
    pool = body or records
    groups = {}
    for r in pool:
        c = r.condition
        key = (
            c.dc_bus_voltage.value if c.dc_bus_voltage else None,
            c.drain_current.value if c.drain_current else None,
            c.gate_resistance_off.value if c.gate_resistance_off else None,
            c.gate_voltage_off.value if c.gate_voltage_off else None,
        )
        groups.setdefault(key, []).append(r)

    def preference(item):
        key, members = item
        voltage_distance = abs((key[0] or 0) - vdc)
        return (len(members), -voltage_distance)

    key, members = max(groups.items(), key=preference)
    return members


class DABScreening:
    def __init__(self, summary: dict, settings: ScreeningSettings):
        self.summary = summary
        self.settings = settings
        self.thermal = ThermalEvaluator()
        window = summary.get("window") or {}
        if window.get("cycles") and window.get("t1") is not None:
            frequency = window["cycles"] / (float(window["t1"]) - float(window["t0"]))
            self.frequency = float(f"{frequency:.9g}")
        else:
            raise ValueError("Summary window is required to derive the switching frequency")

    # -- bridge stress -----------------------------------------------------------------
    def bridge_stress(self, bridge: str) -> tuple[SwitchStress, float]:
        switches = [s for s in self.summary["switches"] if s.get("bridge") == bridge]
        if not switches:
            raise ValueError(f"No switches of bridge {bridge} in the summary")
        worst = max(switches, key=lambda s: s["current_rms"]["value"])
        stress = stress_from_summary(self.summary, worst["id"])
        port = self.summary.get("ports", {}).get("port1" if bridge == "primary" else "port2", {})
        voltage = port.get("voltage_avg", {}).get("value")
        if voltage is None:
            voltage = max(stress.blocking_voltages) if stress.blocking_voltages else None
        if voltage is None:
            raise ValueError(f"Cannot determine the {bridge} bus voltage from the summary")
        return stress, float(round(voltage, 3))

    # -- individual checks -------------------------------------------------------------
    def electrical(self, pool: DevicePool, stress: SwitchStress, vdc: float) -> ElectricalCheck:
        flags = []
        device = pool.candidate.device if pool.candidate else None
        ratings = list(device.ratings) if device else []
        vds = [r for r in ratings if r.name == "vds_max"]
        ids = [r for r in ratings if r.name == "id_max"]
        check = {}
        if vds:
            rating = vds[0].quantity.value
            peak_voltage = max(
                [vdc]
                + list(stress.blocking_voltages)
                + ([stress.v_ds_max] if stress.v_ds_max else [])
            )
            utilisation = peak_voltage / rating
            check.update(
                vds_rating=rating,
                voltage_utilisation=utilisation,
                derating_pass=utilisation <= self.settings.derating_limit,
            )
            flags.extend(
                f
                for f in vds[0].quality.flags
                if f.startswith("basis:") and "manufacturer" not in f
            )
        else:
            flags.append("vds_rating_unavailable")
        if ids:

            def condition_distance(r):
                tc = r.condition.case_temperature
                return abs(tc.value - 373.15) if tc else 1e9

            chosen = min(ids, key=condition_distance)
            tc = chosen.condition.case_temperature
            ext = {e.name: e.quantity.value for e in chosen.condition.extensions}
            if tc:
                condition = f"TC {tc.value - 273.15:.0f} degC"
            elif "heatsink_temperature" in ext:
                condition = f"heatsink {ext['heatsink_temperature'] - 273.15:.0f} degC"
            else:
                condition = "conditions not stated"
            rating = chosen.quantity.value
            peak = max(abs(stress.current_peak_forward or 0), abs(stress.current_peak_reverse or 0))
            check.update(
                id_rating=rating,
                id_rating_condition=condition,
                rms_current_margin=rating / stress.current_rms if stress.current_rms else None,
                peak_current_margin=rating / peak if peak else None,
                current_pass=rating >= stress.current_rms,
            )
            if peak and rating < peak:
                flags.append("continuous_rating_below_peak_current")
            if "conditions_not_stated" in chosen.quality.flags:
                flags.append("id_rating_conditions_not_stated")
        else:
            flags.append("id_rating_unavailable")
        return ElectricalCheck(**check, flags=tuple(flags))

    def canonical_loss(self, device, stress, vdc, tj) -> tuple[DABLossResult, list[str]]:
        flags = []
        s = self.settings
        policy = EnvelopePolicy(allow_extrapolation=s.allow_extrapolation)
        op = operating_point(
            junction_temperature=tj,
            dc_bus_voltage=vdc,
            switching_frequency=self.frequency,
            gate_resistance_on=s.gate_resistance_on,
            gate_resistance_off=s.gate_resistance_off,
            gate_voltage_on=s.gate_voltage_on,
            gate_voltage_off=s.gate_voltage_off,
        )
        evaluator = DABLossEvaluator(stress, policy=policy)
        try:
            return evaluator.evaluate_detailed(device=device, operating_point=op), flags
        except ValueError as exc:
            if "PLECS model range" not in str(exc):
                raise
            flags.append(f"gate_resistance_outside_model_range_table_reference_used: {exc}")
            op = operating_point(
                junction_temperature=tj,
                dc_bus_voltage=vdc,
                switching_frequency=self.frequency,
                gate_voltage_on=s.gate_voltage_on,
                gate_voltage_off=s.gate_voltage_off,
            )
            return evaluator.evaluate_detailed(device=device, operating_point=op), flags

    def datasheet_loss(self, device, stress, vdc, tj) -> LossEstimate:
        flags = []
        gaps = []
        evidence_ids = []
        rds_points, key = _group_rds_on(device, self.settings)
        conduction = None
        if rds_points:
            points = [
                (r.condition.junction_temperature.value, r.quantity.value) for r in rds_points
            ]
            resistance = _tj_interpolate(points, tj, flags, "rds_on")
            conduction = resistance * stress.current_rms**2
            evidence_ids.extend(r.id for r in rds_points)
            flags.append("conduction:rds_on_times_irms_squared")
            if (
                key[0] is not None
                and self.settings.gate_voltage_on is not None
                and key[0] != self.settings.gate_voltage_on
            ):
                flags.append(f"rds_on_at_vgs_{key[0]:g}V_not_{self.settings.gate_voltage_on:g}V")
            if max(t for t, _ in points) < tj:
                gaps.append("rds_on at the evaluation temperature (hot value not printed)")
        else:
            gaps.append("rds_on with junction-temperature condition")
        turn_off = None
        off_points = _datasheet_energy(device, "Eoff", self.settings, vdc)
        if off_points:
            ref = off_points[0].condition
            energies = []
            scaled = [
                (
                    r.condition.junction_temperature.value
                    if r.condition.junction_temperature
                    else None,
                    r.quantity.value,
                )
                for r in off_points
            ]
            with_tj = [(t, e) for t, e in scaled if t is not None]
            if with_tj:
                base = _tj_interpolate(with_tj, tj, flags, "Eoff")
            else:
                base = scaled[0][1]
                flags.append("Eoff:datasheet_point_without_junction_temperature")
            v_ref = ref.dc_bus_voltage.value if ref.dc_bus_voltage else None
            i_ref = ref.drain_current.value if ref.drain_current else None
            if not v_ref or not i_ref:
                gaps.append("Eoff test voltage/current")
            else:
                for current in stress.turn_off_currents:
                    if current <= 0:
                        energies.append(0.0)
                        continue
                    energies.append(base * (vdc / v_ref) * (current / i_ref))
                turn_off = self.frequency * sum(energies) / stress.periods
                flags.append(
                    f"Eoff:datasheet_point_linear_scaling_from_{v_ref:g}V_{i_ref:g}A_to_{vdc:g}V_"
                    f"{max(stress.turn_off_currents):.1f}A"
                )
                rg = ref.gate_resistance_off.value if ref.gate_resistance_off else None
                if (
                    rg is not None
                    and self.settings.gate_resistance_off is not None
                    and abs(rg - self.settings.gate_resistance_off)
                    > 0.5 * self.settings.gate_resistance_off
                ):
                    flags.append(
                        f"Eoff:datasheet_rg_{rg:g}Ohm_differs_from_requested_{self.settings.gate_resistance_off:g}Ohm_no_scaling"
                    )
                if abs(v_ref - vdc) > 0.2 * vdc:
                    flags.append("Eoff:test_voltage_differs_by_more_than_20_percent")
                evidence_ids.extend(r.id for r in off_points)
        else:
            gaps.append("Eoff datasheet point")
        turn_on = None
        zvs = all(stress.zvs_turn_on) if stress.zvs_turn_on else False
        if zvs:
            turn_on = 0.0
            flags.append("turn_on:zvs_assumed_lossless_from_current_condition")
        else:
            on_points = _datasheet_energy(device, "Eon", self.settings, vdc)
            if on_points:
                ref = on_points[0].condition
                v_ref = ref.dc_bus_voltage.value if ref.dc_bus_voltage else None
                i_ref = ref.drain_current.value if ref.drain_current else None
                scaled = [
                    (
                        r.condition.junction_temperature.value
                        if r.condition.junction_temperature
                        else None,
                        r.quantity.value,
                    )
                    for r in on_points
                ]
                with_tj = [(t, e) for t, e in scaled if t is not None]
                base = _tj_interpolate(with_tj, tj, flags, "Eon") if with_tj else scaled[0][1]
                if v_ref and i_ref:
                    energies = [
                        base * (vdc / v_ref) * (max(c, 0.0) / i_ref)
                        for c in stress.turn_on_currents
                    ]
                    turn_on = self.frequency * sum(energies) / stress.periods
                    flags.append("Eon:datasheet_point_linear_scaling")
                    evidence_ids.extend(r.id for r in on_points)
                else:
                    gaps.append("Eon test voltage/current")
            else:
                gaps.append("Eon datasheet point (hard turn-on)")
        complete = conduction is not None and turn_off is not None and turn_on is not None
        total = (
            sum(v for v in (conduction, turn_off, turn_on) if v is not None) if complete else None
        )
        return LossEstimate(
            evidence="datasheet_point",
            conduction=conduction,
            turn_off=turn_off,
            turn_on=turn_on,
            total=total,
            complete=complete,
            method="Datasheet points: Rds(on)(Tj) * I_rms^2; Eoff/Eon scaled linearly in V and I "
            "from the printed test point, interpolated linearly in Tj where two temperatures "
            "are printed; no gate-resistance scaling",
            flags=tuple(flags),
            evidence_ids=tuple(evidence_ids),
            coverage_gaps=tuple(gaps),
        )

    def thermal_check(self, pool, loss_total, loss_at, tj_eval) -> ThermalCheck:
        s = self.settings
        flags = []
        rth = None
        source = None
        if pool.canonical is not None and pool.canonical.thermal:
            network = pool.canonical.thermal[0]
            rth = self.thermal.steady_state_resistance(network).value
            source = f"cauer_network:{network.id}"
        elif pool.candidate is not None:
            parasitics = pool.candidate.device.package.parasitics
            jc = [r for r in parasitics if r.name == "rth_jc"]
            jhs = [r for r in parasitics if r.name == "rth_jhs"]
            if jc:
                typical = [r for r in jc if str(r.statistic) in {"typical", "unspecified"}] or jc
                rth = typical[0].quantity.value
                source = f"datasheet_scalar:{typical[0].id} ({typical[0].statistic})"
                if any(str(r.statistic) == "maximum" for r in jc):
                    flags.append(f"rth_jc_maximum_available:{max(r.quantity.value for r in jc):g}")
            elif jhs:
                rth = jhs[0].quantity.value
                source = f"datasheet_scalar_junction_to_heatsink:{jhs[0].id}"
                flags.append("rth_jhs_includes_tim; case-to-sink resistance not added")
        tj_max = None
        if pool.candidate is not None:
            ratings = [r for r in pool.candidate.device.ratings if r.name == "tj_max"]
            if ratings:
                tj_max = ratings[0].quantity.value
        check = {"rth_junction_to_case": rth, "rth_source": source, "tj_max_rating": tj_max}
        if rth is None:
            flags.append("thermal_resistance_unavailable")
            return ThermalCheck(**check, flags=tuple(flags))
        case_to_sink = 0.0 if source and "junction_to_heatsink" in source else s.rth_case_to_sink
        total = rth + case_to_sink + s.rth_sink_to_ambient
        check["rth_total"] = total
        if loss_total is not None:
            tj = s.ambient_temperature + loss_total * total
            check["tj_at_fixed_loss"] = tj
            check["headroom_to_design_limit"] = s.design_tj_limit - tj
            if tj_max is not None:
                check["headroom_to_rating"] = tj_max - tj
            if loss_at is not None:
                check["fixed_point"] = electro_thermal_fixed_point(
                    loss_at,
                    rth_junction_to_sink=total,
                    sink_temperature=s.ambient_temperature,
                    tj_initial=tj_eval,
                    tolerance=0.05,
                    relaxation=0.7,
                    tj_limit=(tj_max or 473.15) + 50,
                )
        return ThermalCheck(**check, flags=tuple(flags))

    def confidence(self, pool, electrical, loss, thermal) -> Confidence:
        reasons = []
        components = {}
        ratings = 0.0
        if electrical.vds_rating is not None:
            ratings += 0.5
        else:
            reasons.append("no VDS rating")
        if electrical.id_rating is not None:
            ratings += 0.25
        if thermal.tj_max_rating is not None:
            ratings += 0.25
        if any(f.startswith("basis:third_party") for f in electrical.flags):
            ratings *= 0.8
            reasons.append("ratings cited by a third party, not read from the datasheet")
        components["ratings"] = ratings
        if loss.evidence == "canonical_tensor":
            components["conduction"] = 1.0 if loss.conduction is not None else 0.0
            switching = 1.0 if loss.turn_off is not None else 0.0
            if any("rg_dependence_unavailable" in f for f in loss.flags):
                switching -= 0.15
                reasons.append("no gate-resistance dependence in the switching tensor")
            if any("table_reference_used" in f for f in loss.flags):
                switching -= 0.15
            components["switching"] = max(switching, 0.0)
            reasons.append("manufacturer PLECS tensors (unreviewed model data, not measurements)")
        elif loss.evidence == "datasheet_point":
            conduction = 0.0
            if loss.conduction is not None:
                conduction = 0.7 if any("linear_in_tj" in f for f in loss.flags) else 0.35
                if conduction < 0.5:
                    reasons.append("Rds(on) at the evaluation temperature is not printed")
            components["conduction"] = conduction
            switching = 0.0
            if loss.turn_off is not None:
                switching = 0.6
                if any(
                    "Eoff:nearest" in f or "without_junction_temperature" in f for f in loss.flags
                ):
                    switching -= 0.1
                if any("more_than_20_percent" in f for f in loss.flags):
                    switching -= 0.1
                if any("no_scaling" in f for f in loss.flags):
                    switching -= 0.1
                reasons.append("switching energies are datasheet points scaled linearly in V and I")
            else:
                reasons.append("no Eoff datasheet point")
            components["switching"] = max(switching, 0.0)
        else:
            components["conduction"] = 0.0
            components["switching"] = 0.0
            reasons.append("no loss evidence")
        if thermal.rth_source is None:
            components["thermal"] = 0.0
            reasons.append("no thermal resistance")
        elif thermal.rth_source.startswith("cauer"):
            components["thermal"] = 1.0
        elif "junction_to_heatsink" in thermal.rth_source:
            components["thermal"] = 0.6
        else:
            components["thermal"] = (
                0.7 if any("maximum_available" in f for f in thermal.flags) else 0.6
            )
        capacitance = 0.0
        if pool.candidate is not None:
            names = {r.name for r in pool.candidate.device.capacitance.scalars}
            if "coss" in names:
                capacitance = 1.0 if "Eoss" in names else 0.6
        if capacitance == 0.0:
            reasons.append("no Coss/Eoss evidence for charge-based ZVS checks")
        components["capacitance"] = capacitance
        components["measured_evidence"] = 0.0
        weights = {
            "ratings": 0.15,
            "conduction": 0.25,
            "switching": 0.30,
            "thermal": 0.15,
            "capacitance": 0.10,
            "measured_evidence": 0.05,
        }
        score = sum(weights[k] * components[k] for k in weights)
        if electrical.vds_rating is None or not loss.complete:
            tier = "C_insufficient"
        elif loss.evidence == "canonical_tensor":
            tier = "A_canonical_tensors"
        else:
            tier = "B_datasheet_points"
        return Confidence(
            score=round(min(max(score, 0.0), 1.0), 4),
            tier=tier,
            components=components,
            reasons=tuple(reasons),
        )

    # -- assessment --------------------------------------------------------------------
    def assess(self, pool: DevicePool, bridge: str, stress: SwitchStress, vdc: float):
        s = self.settings
        tj = s.junction_temperature
        reasons = []
        electrical = self.electrical(pool, stress, vdc)
        if electrical.derating_pass is not None:
            reasons.append(
                f"VDS utilisation {electrical.voltage_utilisation:.1%} "
                f"{'<=' if electrical.derating_pass else '>'} {s.derating_limit:.0%} of "
                f"{electrical.vds_rating:g} V"
            )
        else:
            reasons.append("No VDS rating available; derating cannot be checked")
        if electrical.id_rating is not None:
            reasons.append(
                f"Continuous current rating {electrical.id_rating:g} A ({electrical.id_rating_condition}) "
                f"vs I_rms {stress.current_rms:.2f} A (margin {electrical.rms_current_margin:.2f})"
            )
        loss_at = None
        loss_flags = []
        result = None
        has_tensors = (
            pool.canonical is not None
            and pool.canonical.switching.curves
            and pool.canonical.conduction.curves
        )
        if electrical.derating_pass is False:
            loss = LossEstimate(
                evidence="canonical_tensor"
                if has_tensors
                else ("datasheet_point" if pool.candidate else "missing"),
                method="not evaluated: the device fails the voltage derating gate for this bridge",
                flags=("not_evaluated_derating_failed",),
            )
        elif has_tensors:
            try:
                result, loss_flags = self.canonical_loss(pool.canonical, stress, vdc, tj)
            except ValueError as exc:
                result = None
                loss = LossEstimate(
                    evidence="canonical_tensor",
                    method=f"tensor evaluation failed: {exc}",
                    flags=("tensor_envelope_violation",),
                    coverage_gaps=("operating point outside the manufacturer tensor envelope",),
                )
                reasons.append(f"Loss not evaluated: {exc}")
        if result is not None:
            breakdown = result.breakdown()
            loss = LossEstimate(
                evidence="canonical_tensor",
                conduction=breakdown.get("conduction_loss"),
                turn_off=breakdown.get("turn_off_loss"),
                turn_on=breakdown.get("turn_on_loss"),
                total=result.total_loss,
                complete=result.complete,
                method="DABLossEvaluator on canonical tensors (summary metrics path)",
                flags=tuple(
                    dict.fromkeys(loss_flags + [f for c in result.components for f in c.flags])
                ),
                evidence_ids=tuple(result.evidence_origins),
                coverage_gaps=tuple(
                    dict.fromkeys(
                        f"{n.quantity} ({n.status})" for n in result.coverage if n.status != "exact"
                    )
                ),
            )
            reasons.append(
                f"Losses from canonical tensors at {tj - 273.15:.0f} degC: conduction "
                f"{loss.conduction:.2f} W, turn-off {loss.turn_off:.2f} W, turn-on {loss.turn_on:.2f} W"
            )
            canonical = pool.canonical

            def loss_at(t, _canonical=canonical, _flags=loss_flags):
                evaluated, _ = self.canonical_loss(_canonical, stress, vdc, t)
                if evaluated.total_loss is None:
                    raise ValueError("incomplete loss evaluation")
                return evaluated.total_loss

        elif electrical.derating_pass is False or (has_tensors and result is None):
            pass
        elif pool.candidate is not None:
            loss = self.datasheet_loss(pool.candidate.device, stress, vdc, tj)
            if loss.complete:
                reasons.append(
                    f"Datasheet-point estimate at {tj - 273.15:.0f} degC: conduction "
                    f"{loss.conduction:.2f} W, turn-off {loss.turn_off:.2f} W, turn-on {loss.turn_on:.2f} W "
                    "(linear V/I scaling; flagged estimate)"
                )
                device = pool.candidate.device

                def loss_at(t, _device=device):
                    estimate = self.datasheet_loss(_device, stress, vdc, t)
                    if estimate.total is None:
                        raise ValueError("incomplete datasheet estimate")
                    return estimate.total

            else:
                reasons.append(f"Loss estimate incomplete: missing {', '.join(loss.coverage_gaps)}")
        else:
            loss = LossEstimate(evidence="missing", method="no evidence")
            reasons.append("No loss evidence")
        thermal = self.thermal_check(pool, loss.total, loss_at, tj)
        if thermal.tj_at_fixed_loss is not None:
            reasons.append(
                f"Tj {thermal.tj_at_fixed_loss - 273.15:.1f} degC at {loss.total:.2f} W with Rth(j-a) "
                f"{thermal.rth_total:.2f} K/W; headroom to the {s.design_tj_limit - 273.15:.0f} degC "
                f"design limit {thermal.headroom_to_design_limit:.1f} K"
            )
            if thermal.fixed_point is not None and thermal.fixed_point.converged:
                reasons.append(
                    f"Electro-thermal fixed point: Tj {thermal.fixed_point.junction_temperature - 273.15:.1f} "
                    f"degC, {thermal.fixed_point.loss:.2f} W after {len(thermal.fixed_point.iterations)} iterations"
                )
            elif thermal.fixed_point is not None:
                reasons.append(
                    f"Electro-thermal fixed point did not converge: {thermal.fixed_point.reason}"
                )
        else:
            reasons.append(
                "Junction temperature not estimated (missing loss or thermal resistance)"
            )
        confidence = self.confidence(pool, electrical, loss, thermal)
        eligible = bool(
            electrical.derating_pass
            and (electrical.current_pass is not False)
            and loss.complete
            and confidence.tier != "C_insufficient"
            and (thermal.headroom_to_design_limit is None or thermal.headroom_to_design_limit > 0)
        )
        if electrical.derating_pass is False:
            reasons.append("Excluded: voltage derating limit exceeded")
        if electrical.current_pass is False:
            reasons.append("Excluded: continuous current rating below I_rms")
        if thermal.headroom_to_design_limit is not None and thermal.headroom_to_design_limit <= 0:
            reasons.append("Excluded: no junction-temperature headroom at the design limit")
        if confidence.tier == "C_insufficient":
            reasons.append(
                "Unranked: insufficient evidence (" + "; ".join(confidence.reasons) + ")"
            )
        return CandidateAssessment(
            candidate_id=pool.candidate.device.device_id if pool.candidate else None,
            canonical_id=pool.canonical.device_id if pool.canonical else None,
            manufacturer=pool.manufacturer,
            part_number=pool.part_number,
            package=(pool.candidate.device.package.name if pool.candidate else None)
            or (pool.canonical.package.name if pool.canonical else None),
            integration=(
                pool.candidate.device.classification.integration
                if pool.candidate
                else pool.canonical.classification.integration
            ),
            bridge=bridge,
            electrical=electrical,
            loss=loss,
            thermal=thermal,
            confidence=confidence,
            eligible=eligible,
            reasons=tuple(reasons),
        )

    def screen_bridge(self, bridge: str, pool: tuple[DevicePool, ...]) -> BridgeScreening:
        stress, vdc = self.bridge_stress(bridge)
        assessments = [self.assess(p, bridge, stress, vdc) for p in pool]
        eligible = [a for a in assessments if a.eligible]
        eligible.sort(key=lambda a: (a.confidence.tier, a.loss.total))
        ranked = tuple(a.model_copy(update={"rank": i + 1}) for i, a in enumerate(eligible))
        excluded = tuple(a for a in assessments if not a.eligible)
        return BridgeScreening(
            bridge=bridge,
            dc_bus_voltage=vdc,
            worst_case_switch=stress.switch_id,
            stress=stress,
            ranked=ranked,
            excluded=excluded,
        )

    def screen(
        self, pool: tuple[DevicePool, ...], bridges=("primary", "secondary")
    ) -> ScreeningReport:
        notes = [
            "Confidence tiers are never interleaved in the ranking; datasheet-point estimates "
            "(tier B) are flagged and not comparable with canonical tensor evaluations (tier A).",
            "Turn-on loss is zero where the waveform satisfies the ZVS current condition; a "
            "charge-based verification needs Coss/Eoss evidence.",
            "All evidence is manufacturer model or datasheet data; no laboratory measurement "
            "backs any ranking.",
        ]
        return ScreeningReport(
            settings=self.settings,
            dataset_sha256=self.summary.get("dataset_sha256"),
            switching_frequency=self.frequency,
            bridges=tuple(self.screen_bridge(b, pool) for b in bridges),
            pool=tuple(p.label for p in pool),
            notes=tuple(notes),
        )
