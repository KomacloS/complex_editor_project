from __future__ import annotations

from xml.etree import ElementTree as ET

from .models import MacroInstance

__all__ = ["macro_to_xml", "parse_param_xml"]


def macro_to_xml(macro: MacroInstance) -> str:
    """Return UTF-16-LE XML string for the given macro."""
    root = ET.Element("R")
    macros_el = ET.SubElement(root, "Macros")
    macro_el = ET.SubElement(macros_el, "Macro", Name=macro.name)
    for name, value in macro.params.items():
        ET.SubElement(macro_el, "Param", Value=value, Name=name)
    ET.indent(root, space="  ")
    xml_body = ET.tostring(root, encoding="unicode")
    return "<?xml version=\"1.0\" encoding=\"utf-16\"?>\n" + xml_body


def parse_param_xml(xml_blob: bytes) -> dict[str, str]:
    """Return mapping of parameter name to value from UTF-16 XML blob."""
    xml_str = xml_blob.decode("utf-16le")
    root = ET.fromstring(xml_str)
    params: dict[str, str] = {}
    for param_el in root.findall(".//Param"):
        name = param_el.get("Name")
        value = param_el.get("Value")
        if name is not None and value is not None:
            params[name] = value
    return params
