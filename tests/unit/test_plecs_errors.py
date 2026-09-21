import xml.etree.ElementTree as ET

import pytest
from conftest import RAW

from aipe_devices.importers.base import UnsupportedFormatError
from aipe_devices.importers.plecs import PlecsImporter


def source_tree(name="C2M0025120D"):
    root = ET.parse(next(RAW.rglob(f"{name}.xml"))).getroot()
    for element in root.iter():
        element.tag = element.tag.split("}")[-1]
    return root


def test_reject_unmapped_sections():
    root = source_tree()
    ET.SubElement(root.find("Package"), "UnknownPhysics")
    with pytest.raises(UnsupportedFormatError):
        PlecsImporter().loads(ET.tostring(root))


def test_missing_one_of_two_lookup_tables_is_not_silently_exportable():
    root = source_tree("C4MS036120K")
    tables = root.find("Package/CustomTables")
    tables.remove(tables.findall("Table")[1])
    with pytest.raises(UnsupportedFormatError, match="lookup"):
        PlecsImporter().loads(ET.tostring(root))


def test_ragged_source_table_and_dtd_rejected():
    root = source_tree()
    root.find(".//Energy/Temperature/Voltage").text = "0 1"
    with pytest.raises(ValueError, match="Ragged"):
        PlecsImporter().loads(ET.tostring(root))
    with pytest.raises(ValueError, match="DTD"):
        PlecsImporter().loads(b'<!DOCTYPE x [<!ENTITY e "test">]><x/>')
