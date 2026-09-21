"""V1 is a PLECS-shaped legacy document, not an alternative domain model."""

import hashlib
import json
import xml.etree.ElementTree as ET
from pathlib import Path

from aipe_devices.domain.provenance import ArtifactRef
from aipe_devices.domain.quality import Quality
from aipe_devices.importers.plecs import PlecsImporter
from aipe_devices.schema.enums import Technology


def migrate(data: dict, *, source_uri: str = "urn:aipe:legacy-v1", raw: bytes | None = None):
    metadata, package = data["metadata"], data["package"]
    root = ET.Element("SemiconductorLibrary", version=data.get("library", {}).get("version", "1.4"))
    node = ET.SubElement(
        root,
        "Package",
        {
            "class": package["class"],
            "vendor": metadata["manufacturer"],
            "partnumber": metadata["part_number"],
        },
    )
    variables = ET.SubElement(node, "Variables")
    tags = {
        "name": "Name",
        "description": "Description",
        "default_value": "DefaultValue",
        "min_value": "MinValue",
        "max_value": "MaxValue",
    }
    for variable in package.get("variables", []):
        var = ET.SubElement(variables, "Variable")
        for key, tag in tags.items():
            if key in variable:
                ET.SubElement(var, tag).text = str(variable[key])
    sem = package["semiconductor_data"]
    target = ET.SubElement(node, "SemiconductorData", type=sem["type"])
    for key, tag in [
        ("turn_on_loss", "TurnOnLoss"),
        ("turn_off_loss", "TurnOffLoss"),
        ("conduction_loss", "ConductionLoss"),
    ]:
        sections = sem.get(key, [])
        if isinstance(sections, dict):
            sections = [sections]
        for section in sections:
            child = ET.SubElement(target, tag)
            if section.get("gate"):
                child.set("gate", section["gate"])
            for field, xml_tag in [
                ("computation_method", "ComputationMethod"),
                ("formula", "Formula"),
            ]:
                if field in section:
                    ET.SubElement(child, xml_tag).text = section[field]
            for field, xml_tag in [
                ("current_axis", "CurrentAxis"),
                ("voltage_axis", "VoltageAxis"),
                ("temperature_axis", "TemperatureAxis"),
            ]:
                if field in section:
                    ET.SubElement(child, xml_tag).text = " ".join(map(str, section[field]))
            for field, xml_tag in [("energy", "Energy"), ("voltage_drop", "VoltageDrop")]:
                if field in section:
                    values = section[field]
                    v = ET.SubElement(child, xml_tag, scale=str(values["scale"]))
                    for row in values["data"]:
                        temperature = ET.SubElement(v, "Temperature")
                        if field == "energy":
                            for voltage_row in row:
                                ET.SubElement(temperature, "Voltage").text = " ".join(
                                    map(str, voltage_row)
                                )
                        else:
                            temperature.text = " ".join(map(str, row))
    thermal = package.get("thermal_model")
    if thermal and thermal.get("rc_elements"):
        branch = ET.SubElement(ET.SubElement(node, "ThermalModel"), "Branch", type=thermal["type"])
        for element in thermal["rc_elements"]:
            ET.SubElement(branch, "RCElement", {k: str(element[k]) for k in ("R", "C")})
    comment = ET.SubElement(node, "Comment")
    for line in package.get("comment", []):
        ET.SubElement(comment, "Line").text = line
    technology = Technology.SIC_MOSFET if metadata.get("material") == "SiC" else Technology.UNKNOWN
    integration = {"discrete": "discrete", "power module": "module"}.get(
        metadata.get("package_type"), "unknown"
    )
    device = PlecsImporter().loads(
        ET.tostring(root),
        technology=technology,
        integration=integration,
        source_uri=source_uri,
        allow_incomplete_models=True,
    )
    raw = raw if raw is not None else json.dumps(data, sort_keys=True).encode()
    digest = hashlib.sha256(raw).hexdigest()
    artifact = ArtifactRef(
        id=f"sha256:{digest}",
        uri=source_uri,
        checksum=digest,
        format="application/json",
        size=len(raw),
    )
    # Source ID is preserved as the transformation identity; actual evidence points to legacy bytes.
    source = device.provenance[0].model_copy(
        update={
            "artifact": artifact,
            "kind": "simulation_model",
            "name": "Legacy V1 manufacturer-model transcription",
        }
    )
    model = device.models[0].model_copy(update={"artifact": artifact})
    flags = ("legacy_v1", "custom_tables_and_namespace_may_be_lost", "reimport_xml_preferred")
    return device.model_copy(
        update={"provenance": (source,), "models": (model,), "quality": Quality(flags=flags)}
    )


def load(path: str | Path):
    path = Path(path)
    raw = path.read_bytes()
    return migrate(json.loads(raw), raw=raw, source_uri=path.resolve().as_uri())
