"""Conservative V2 migration: preserve available points, label historical assumptions."""

import hashlib
import json
from pathlib import Path

from aipe_devices.domain.conditions import OperatingCondition
from aipe_devices.domain.curves import Axis, CharacteristicData, Curve, ScalarRecord
from aipe_devices.domain.device import PowerSemiconductorDevice
from aipe_devices.domain.identity import Classification, DeviceIdentity
from aipe_devices.domain.models import ModelReference
from aipe_devices.domain.provenance import ArtifactRef, Dependency, Provenance, Source
from aipe_devices.domain.quality import Quality
from aipe_devices.domain.thermal import ThermalElement, ThermalNetwork
from aipe_devices.normalizers.units import normalize
from aipe_devices.schema.enums import Availability, Lifecycle, Origin, Technology


def migrate(data: dict, *, source_uri: str = "urn:aipe:legacy-v2", raw: bytes | None = None):
    raw = raw if raw is not None else json.dumps(data, sort_keys=True).encode()
    digest = hashlib.sha256(raw).hexdigest()
    artifact = ArtifactRef(
        id=f"sha256:{digest}",
        uri=source_uri,
        checksum=digest,
        format="application/json",
        size=len(raw),
    )
    source = Source(
        id=f"source:{digest}",
        kind="simulation_model",
        name="Legacy V2 transcription (contains inferred defaults)",
        artifact=artifact,
    )
    provenance = Provenance(origin=Origin.MODEL, source_ids=(source.id,))
    inferred = Provenance(
        origin=Origin.INFERRED,
        source_ids=(source.id,),
        lifecycle=Lifecycle.DERIVED,
        dependencies=(Dependency(id=artifact.id, version="2", checksum=digest),),
    )
    key = data["device_id"]
    curves = {"switching": [], "conduction": [], "reverse_conduction": []}
    losses = data.get("loss_curves", {})
    for name in ["eon", "eoff"]:
        for index, table in enumerate(losses.get(name, {}).get("data", [])):
            temps = table["temperature_axis"]
            current = table["current_axis"]
            values = table["energy"]
            axes = (
                Axis(
                    name="junction_temperature",
                    unit="K",
                    values=tuple(
                        normalize(t, "degC" if temps["unit"] == "C" else temps["unit"]).value
                        for t in temps["values"]
                    ),
                ),
                Axis(
                    name="current",
                    unit="A",
                    values=tuple(normalize(i, current["unit"]).value for i in current["values"]),
                ),
            )
            normalized = tuple(
                normalize(v, values["unit"]).value
                for t in temps["values"]
                for v in values["data_by_temperature"][str(float(t))]
            )
            # V2's vgs=15 is an injected assumption, not a known condition.
            condition = OperatingCondition(
                dc_bus_voltage=normalize(table["conditions"]["vdc"], "V")
            )
            curves["switching"].append(
                Curve(
                    id=f"{key}:{name}:{index}",
                    name="Eon" if name == "eon" else "Eoff",
                    axes=axes,
                    values=normalized,
                    unit="J",
                    provenance=provenance,
                    condition=condition,
                    quality=Quality(
                        flags=("legacy_v2_filtered_axes", "assumed_gate_voltage_omitted")
                    ),
                )
            )
    for index, table in enumerate(losses.get("vf", [])):
        temps, current, values = (
            table["temperature_axis"],
            table["current_axis"],
            table["voltage_drop"],
        )
        axes = (
            Axis(
                name="junction_temperature",
                unit="K",
                values=tuple(
                    normalize(t, "degC" if temps["unit"] == "C" else temps["unit"]).value
                    for t in temps["values"]
                ),
            ),
            Axis(
                name="current",
                unit="A",
                values=tuple(normalize(i, current["unit"]).value for i in current["values"]),
            ),
        )
        group = "reverse_conduction" if table.get("gate") == "off" else "conduction"
        curves[group].append(
            Curve(
                id=f"{key}:vf:{index}",
                name="voltage_drop",
                axes=axes,
                values=tuple(
                    normalize(v * values.get("scale", 1), values["unit"]).value
                    for t in temps["values"]
                    for v in values["data_by_temperature"][str(float(t))]
                ),
                unit="V",
                provenance=provenance,
                condition=OperatingCondition(gate_state=table.get("gate", "unknown")),
            )
        )
    ratings = []
    for name, value in data.get("ratings", {}).items():
        if value is not None:
            ratings.append(
                ScalarRecord(
                    id=f"{key}:legacy:{name}",
                    name=name,
                    quantity=normalize(
                        value["value"], "degC" if value["unit"] == "C" else value["unit"]
                    ),
                    provenance=inferred,
                    quality=Quality(flags=("legacy_inferred_rating_not_verified",)),
                )
            )
    scalar_groups = {
        name: [] for name in ("conduction", "reverse_conduction", "capacitance", "gate_charge")
    }
    for name, entries in {**data.get("static", {}), **data.get("switching", {})}.items():
        if entries is None:
            continue
        if isinstance(entries, dict):
            entries = [entries]
        group = {
            "vf_body_diode": "reverse_conduction",
            "qg_total": "gate_charge",
            "ciss": "capacitance",
            "coss": "capacitance",
            "crss": "capacitance",
        }.get(name, "conduction")
        for index, entry in enumerate(entries):
            scalar_groups[group].append(
                ScalarRecord(
                    id=f"{key}:legacy:{name}:{index}",
                    name=name,
                    quantity=normalize(entry["value"], entry["unit"]),
                    provenance=inferred,
                    quality=Quality(flags=("legacy_condition_and_statistic_unverified",)),
                )
            )
    thermal = data.get("thermal", {})
    networks = ()
    if thermal.get("rc_elements"):
        networks = (
            ThermalNetwork(
                id=f"{key}:thermal:0",
                topology=thermal["model_type"],
                provenance=provenance,
                elements=tuple(
                    ThermalElement(
                        resistance=normalize(e["R"], e["R_unit"]),
                        capacitance=normalize(e["C"], e["C_unit"]),
                    )
                    for e in thermal["rc_elements"]
                ),
            ),
        )
    identity = data["identity"]
    groups = {}
    for group in curves.keys() | scalar_groups.keys():
        cs, ss = tuple(curves.get(group, [])), tuple(scalar_groups.get(group, []))
        if cs or ss:
            groups[group] = CharacteristicData(
                availability=Availability.PARTIAL, curves=cs, scalars=ss
            )
    return PowerSemiconductorDevice(
        device_id=key,
        identity=DeviceIdentity(
            manufacturer=identity["manufacturer"],
            part_number=identity["part_number"],
            aliases=tuple(identity.get("aliases", [])),
        ),
        classification=Classification(
            technology=Technology(data["classification"]["technology"]),
            integration=data["classification"].get("integration_level", "unknown"),
        ),
        provenance=(source,),
        ratings=tuple(ratings),
        thermal=networks,
        models=(
            ModelReference(
                id=f"{key}:legacy-v2", format="legacy-v2", artifact=artifact, provenance=provenance
            ),
        ),
        quality=Quality(
            flags=(
                "legacy_v2_lossy",
                "source_points_missing",
                "unverified_defaults",
                "formulas_variables_and_identity_guesses_retained_in_source_artifact",
            )
        ),
        **groups,
    )


def load(path: str | Path):
    path = Path(path)
    raw = path.read_bytes()
    return migrate(json.loads(raw), raw=raw, source_uri=path.resolve().as_uri())
