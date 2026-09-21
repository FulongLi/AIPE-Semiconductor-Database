"""Export supported canonical tensors; never evaluate manufacturer expressions."""

import xml.etree.ElementTree as ET
from itertools import islice
from pathlib import Path

from aipe_devices.domain.device import CHARACTERISTICS
from aipe_devices.importers.base import UnsupportedFormatError
from aipe_devices.services.validation import validate_device
from aipe_devices.storage.artifact_store import atomic_write


def text_values(values):
    return " ".join(format(v, ".17g") for v in values)


def write_tensor(parent, values, shape, tags, scale):
    iterator = iter(values)

    def write(node, dimensions, names):
        if len(dimensions) == 1:
            node.text = text_values(v / scale for v in islice(iterator, dimensions[0]))
        else:
            for _ in range(dimensions[0]):
                child = ET.SubElement(node, names[0])
                write(child, dimensions[1:], names[1:])

    write(parent, shape, tags)


class PlecsExporter:
    def export(self, device, path: str | Path | None = None) -> str:
        validate_device(device).raise_for_errors()
        models = [m for m in device.models if m.format == "plecs"]
        if len(models) != 1:
            raise UnsupportedFormatError("PLECS export needs one explicit adapter model/binding")
        metadata = models[0].adapter_metadata
        if metadata.get("unresolved_tables"):
            raise UnsupportedFormatError(
                "Legacy source omitted required lookup tables; reimport raw XML"
            )
        curves = {c.id: c for name in CHARACTERISTICS for c in getattr(device, name).curves}
        root = ET.Element("SemiconductorLibrary", version=metadata["version"])
        if metadata.get("namespace"):
            root.set("xmlns", metadata["namespace"])
        package = ET.SubElement(
            root,
            "Package",
            {
                "class": metadata["package_class"],
                "vendor": device.identity.manufacturer,
                "partnumber": device.identity.part_number,
            },
        )
        variables = ET.SubElement(package, "Variables")
        for variable in metadata["variables"]:
            node = ET.SubElement(variables, "Variable")
            for name, value in variable.items():
                ET.SubElement(node, name).text = value
        semiconductor = ET.SubElement(
            package, "SemiconductorData", type=metadata["semiconductor_type"]
        )
        for binding in metadata["bindings"]:
            curve = curves[binding["curve_id"]]
            energy = binding["section"] != "ConductionLoss"
            expected = (
                ["junction_temperature", "dc_bus_voltage", "current"]
                if energy
                else ["junction_temperature", "current"]
            )
            if [a.name for a in curve.axes] != expected or curve.unit != ("J" if energy else "V"):
                raise UnsupportedFormatError(
                    "PLECS binding axes/units no longer match canonical curve"
                )
            section = ET.SubElement(semiconductor, binding["section"])
            if curve.condition.gate_state != "unknown":
                section.set("gate", curve.condition.gate_state)
            ET.SubElement(section, "ComputationMethod").text = binding["method"]
            if binding["formula"]:
                ET.SubElement(section, "Formula").text = binding["formula"]
            axis_by_name = {a.name: a for a in curve.axes}
            for name, tag in [
                ("current", "CurrentAxis"),
                ("dc_bus_voltage", "VoltageAxis"),
                ("junction_temperature", "TemperatureAxis"),
            ]:
                if name in axis_by_name:
                    axis = axis_by_name[name]
                    values = (
                        tuple(t - 273.15 for t in axis.values) if axis.unit == "K" else axis.values
                    )
                    ET.SubElement(section, tag).text = text_values(values)
            scale = binding["scale"]
            data = ET.SubElement(section, "Energy" if energy else "VoltageDrop", scale=str(scale))
            write_tensor(
                data,
                curve.values,
                [len(a.values) for a in curve.axes],
                ["Temperature", "Voltage"] if energy else ["Temperature"],
                scale,
            )
        if metadata["custom_tables"]:
            custom = ET.SubElement(package, "CustomTables")
            for binding in metadata["custom_tables"]:
                curve = curves[binding["curve_id"]]
                expected = [
                    "gate_resistance_on" if binding["name"] == "Eon" else "gate_resistance_off",
                    "junction_temperature",
                    "dc_bus_voltage",
                    "current",
                ]
                if [a.name for a in curve.axes] != expected or curve.unit != "J":
                    raise UnsupportedFormatError("Custom table binding axes/units mismatch")
                table = ET.SubElement(custom, "Table", numDimensions="4")
                ET.SubElement(table, "Name").text = binding["name"]
                for axis in reversed(curve.axes):
                    values = (
                        tuple(t - 273.15 for t in axis.values) if axis.unit == "K" else axis.values
                    )
                    ET.SubElement(table, "Axis").text = text_values(values)
                data = ET.SubElement(table, "FunctionValues", scale=str(binding["scale"]))
                write_tensor(
                    data,
                    curve.values,
                    [len(a.values) for a in curve.axes],
                    ["Dimension"] * 3,
                    binding["scale"] * 1e-3,
                )
        if device.thermal:
            thermal = ET.SubElement(package, "ThermalModel")
            for network in device.thermal:
                branch = ET.SubElement(thermal, "Branch", type=network.topology)
                for element in network.elements:
                    ET.SubElement(
                        branch,
                        "RCElement",
                        R=str(element.resistance.value),
                        C=str(element.capacitance.value),
                    )
        comments = ET.SubElement(package, "Comment")
        for line in metadata["comments"]:
            ET.SubElement(comments, "Line").text = line
        ET.indent(root)
        result = ET.tostring(root, encoding="unicode", xml_declaration=True)
        if path is not None:
            atomic_write(Path(path), result.encode())
        return result
