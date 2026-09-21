"""PLECS adapter: source tables become generic SI tensors; formulas remain opaque."""

import hashlib
import re
import xml.etree.ElementTree as ET
from pathlib import Path

from aipe_devices.domain.conditions import OperatingCondition
from aipe_devices.domain.curves import Axis, CharacteristicData, Curve
from aipe_devices.domain.device import PowerSemiconductorDevice
from aipe_devices.domain.identity import Classification, DeviceIdentity
from aipe_devices.domain.models import ModelReference
from aipe_devices.domain.provenance import AccessMetadata, ArtifactRef, Provenance, Source
from aipe_devices.domain.quality import Quality
from aipe_devices.domain.thermal import ThermalElement, ThermalNetwork
from aipe_devices.importers.base import UnsupportedFormatError
from aipe_devices.schema.enums import Availability, Origin, Technology


def numbers(text):
    return tuple(float(x) for x in (text or "").split())


def flatten(element):
    if len(element):
        return tuple(v for child in element for v in flatten(child))
    return numbers(element.text)


def tensor_shape(element):
    if not len(element):
        return (len(numbers(element.text)),)
    shapes = [tensor_shape(c) for c in element]
    if len(set(shapes)) != 1:
        raise ValueError("Ragged PLECS table")
    return (len(element), *shapes[0])


def device_key(manufacturer, part_number):
    return re.sub(r"[^a-z0-9_.-]+", "_", f"{manufacturer}_{part_number}".lower())


class PlecsImporter:
    def load(
        self,
        path: str | Path,
        *,
        technology: Technology = Technology.UNKNOWN,
        integration: str = "unknown",
        source_uri: str | None = None,
        device_id: str | None = None,
    ) -> PowerSemiconductorDevice:
        path = Path(path)
        return self.loads(
            path.read_bytes(),
            technology=technology,
            integration=integration,
            source_uri=source_uri or path.resolve().as_uri(),
            device_id=device_id,
        )

    def loads(
        self,
        raw: bytes,
        *,
        technology: Technology = Technology.UNKNOWN,
        integration: str = "unknown",
        source_uri: str = "urn:aipe:unlocated-source",
        device_id: str | None = None,
        allow_incomplete_models: bool = False,
    ) -> PowerSemiconductorDevice:
        # Reject DTDs/entities; source XML is data, never executable input.
        if b"<!DOCTYPE" in raw.upper() or b"<!ENTITY" in raw.upper():
            raise ValueError("DTD/entity declarations are not supported")
        root = ET.fromstring(raw)
        namespace = root.tag.partition("}")[0].lstrip("{") if "}" in root.tag else ""
        for element in root.iter():
            element.tag = element.tag.split("}")[-1]
        if root.tag != "SemiconductorLibrary" or len(root.findall("Package")) != 1:
            raise UnsupportedFormatError("Expected one PLECS SemiconductorLibrary Package")
        package = root.find("Package")
        if any(n.tag != "Package" for n in root):
            raise UnsupportedFormatError("Unsupported library-level section")
        allowed_sections = {
            "Variables",
            "SemiconductorData",
            "ThermalModel",
            "Comment",
            "CustomTables",
        }
        if any(n.tag not in allowed_sections for n in package):
            raise UnsupportedFormatError(
                "Unsupported package section; preserve and map source explicitly"
            )
        manufacturer, part = package.attrib["vendor"], package.attrib["partnumber"]
        key = device_id or device_key(manufacturer, part)
        digest = hashlib.sha256(raw).hexdigest()
        artifact = ArtifactRef(
            id=f"sha256:{digest}",
            uri=source_uri,
            checksum=digest,
            size=len(raw),
            format="application/xml",
        )
        source = Source(
            id=f"source:{digest}",
            kind="manufacturer",
            name=manufacturer,
            artifact=artifact,
            access=AccessMetadata(owner=manufacturer, category="manufacturer", visibility="public"),
        )
        provenance = Provenance(origin=Origin.MODEL, source_ids=(source.id,))
        curves = {"switching": [], "conduction": [], "reverse_conduction": []}
        bindings = []
        semiconductor = package.find("SemiconductorData")
        if semiconductor is None:
            raise UnsupportedFormatError("Missing SemiconductorData")
        for index, section in enumerate(semiconductor):
            if section.tag not in {"TurnOnLoss", "TurnOffLoss", "ConductionLoss"}:
                raise UnsupportedFormatError(f"Unmapped semiconductor section {section.tag}")
            energy = section.tag != "ConductionLoss"
            name = {"TurnOnLoss": "Eon", "TurnOffLoss": "Eoff", "ConductionLoss": "voltage_drop"}[
                section.tag
            ]
            group = (
                "switching"
                if energy
                else ("reverse_conduction" if section.get("gate") == "off" else "conduction")
            )
            axes = [
                Axis(
                    name="junction_temperature",
                    unit="K",
                    values=tuple(t + 273.15 for t in numbers(section.findtext("TemperatureAxis"))),
                )
            ]
            if energy:
                axes.append(
                    Axis(
                        name="dc_bus_voltage",
                        unit="V",
                        values=numbers(section.findtext("VoltageAxis")),
                    )
                )
            axes.append(
                Axis(name="current", unit="A", values=numbers(section.findtext("CurrentAxis")))
            )
            values_element = section.find("Energy" if energy else "VoltageDrop")
            if values_element is None:
                raise UnsupportedFormatError("Formula without tabulated evidence is not supported")
            scale = float(values_element.get("scale", "1"))
            if scale <= 0:
                raise ValueError("Table scale must be positive")
            if tensor_shape(values_element) != tuple(len(a.values) for a in axes):
                raise ValueError("PLECS nested dimensions disagree with axes")
            curve_id = f"{key}:{name}:{index}"
            condition = OperatingCondition(gate_state=section.get("gate", "unknown"))
            curve = Curve(
                id=curve_id,
                name=name,
                axes=tuple(axes),
                values=tuple(x * scale for x in flatten(values_element)),
                unit="J" if energy else "V",
                provenance=provenance,
                condition=condition,
            )
            curves[group].append(curve)
            bindings.append(
                {
                    "curve_id": curve_id,
                    "section": section.tag,
                    "method": section.findtext("ComputationMethod", "Table only"),
                    "formula": section.findtext("Formula"),
                    "scale": scale,
                }
            )
        custom_bindings = []
        for table in package.findall("CustomTables/Table"):
            name = table.findtext("Name")
            matches = [
                b
                for b in bindings
                if b["formula"]
                == f"lookup('{name}',i,v,T,{'Rgon' if name == 'Eon' else 'Rgoff'})*1e-3"
            ]
            if name not in {"Eon", "Eoff"} or not matches or table.get("numDimensions") != "4":
                raise UnsupportedFormatError(
                    "Unknown custom-table axis/unit semantics; source retained"
                )
            raw_axes = [numbers(a.text) for a in table.findall("Axis")]
            if len(raw_axes) != 4:
                raise ValueError("Custom table must have four axes")
            axes = (
                Axis(
                    name="gate_resistance_on" if name == "Eon" else "gate_resistance_off",
                    unit="Ohm",
                    values=raw_axes[3],
                ),
                Axis(
                    name="junction_temperature",
                    unit="K",
                    values=tuple(t + 273.15 for t in raw_axes[2]),
                ),
                Axis(name="dc_bus_voltage", unit="V", values=raw_axes[1]),
                Axis(name="current", unit="A", values=raw_axes[0]),
            )
            values_element = table.find("FunctionValues")
            if values_element is None or tensor_shape(values_element) != tuple(
                len(a.values) for a in axes
            ):
                raise ValueError("Custom table shape disagrees with axes")
            scale = float(values_element.get("scale", "1"))
            if scale <= 0:
                raise ValueError("Custom table scale must be positive")
            curve_id = f"{key}:{name}:gate_resistance"
            curves["switching"].append(
                Curve(
                    id=curve_id,
                    name=name,
                    axes=axes,
                    values=tuple(v * scale * 1e-3 for v in flatten(values_element)),
                    unit="J",
                    provenance=provenance,
                )
            )
            custom_bindings.append({"curve_id": curve_id, "name": name, "scale": scale})
        unresolved = False
        for binding in bindings:
            names = re.findall(r"lookup\(['\"]([^'\"]+)['\"]", binding["formula"] or "")
            if names and not set(names) <= {b["name"] for b in custom_bindings}:
                unresolved = True
                if not allow_incomplete_models:
                    raise UnsupportedFormatError("Unresolved PLECS lookup table")
        thermal = []
        for index, branch in enumerate(package.findall("ThermalModel/Branch")):
            thermal.append(
                ThermalNetwork(
                    id=f"{key}:thermal:{index}",
                    topology=branch.attrib["type"],
                    elements=tuple(
                        ThermalElement(
                            resistance={"value": float(e.attrib["R"]), "unit": "K/W"},
                            capacitance={"value": float(e.attrib["C"]), "unit": "J/K"},
                        )
                        for e in branch.findall("RCElement")
                    ),
                    provenance=provenance,
                )
            )
        variables = [
            {c.tag: c.text or "" for c in v} for v in package.findall("Variables/Variable")
        ]
        metadata = {
            "version": root.get("version", "1.4"),
            "namespace": namespace,
            "package_class": package.get("class"),
            "semiconductor_type": semiconductor.get("type"),
            "variables": variables,
            "bindings": bindings,
            "custom_tables": custom_bindings,
            "unresolved_tables": unresolved,
            "comments": [n.text or "" for n in package.findall("Comment/Line")],
        }
        model = ModelReference(
            id=f"{key}:plecs",
            format="plecs",
            artifact=artifact,
            provenance=provenance,
            adapter_metadata=metadata,
        )
        return PowerSemiconductorDevice(
            device_id=key,
            identity=DeviceIdentity(manufacturer=manufacturer, part_number=part),
            classification=Classification(technology=technology, integration=integration),
            provenance=(source,),
            models=(model,),
            thermal=tuple(thermal),
            quality=Quality(flags=("manufacturer_model_not_measurement",)),
            **{
                group: CharacteristicData(availability=Availability.AVAILABLE, curves=tuple(items))
                for group, items in curves.items()
                if items
            },
        )
