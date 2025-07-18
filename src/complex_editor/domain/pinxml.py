"""
Serialise / de-serialise <R><Macros><Macro …><Param …/></Macro></Macros></R>
blocks used in detCompDesc.PinS (UTF-16 XML).
"""

from __future__ import annotations
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from typing import Any, Dict, List


@dataclass(slots=True, frozen=True)
class MacroInstance:
    name: str
    params: Dict[str, Any] = field(default_factory=dict)


class PinXML:
    _XMLNS = {
        "xmlns:xsi": "http://www.w3.org/2001/XMLSchema-instance",
        "xmlns:xsd": "http://www.w3.org/2001/XMLSchema",
    }

    # ---------- public API ----------

    @staticmethod
    def serialize(macros: List[MacroInstance], *, encoding: str = "utf-16le") -> bytes:
        root = ET.Element("R", PinXML._XMLNS)
        macros_el = ET.SubElement(root, "Macros")

        for inst in macros:
            macro_el = ET.SubElement(macros_el, "Macro", {"Name": inst.name})
            for pname, pval in inst.params.items():
                ET.SubElement(macro_el, "Param", {"Value": str(pval), "Name": pname})

        xml = ET.tostring(root, encoding=encoding, xml_declaration=True)
        return xml.replace(b"utf-16le", b"utf-16", 1)

    @staticmethod
    def deserialize(xml: bytes | str) -> List[MacroInstance]:
        tree = ET.fromstring(xml)
        result: List[MacroInstance] = []
        for m_el in tree.find("Macros") or []:
            name = m_el.attrib["Name"]
            params = {}
            for p in m_el:
                val = p.attrib.get("Value")
                if val is not None:
                    try:
                        val = int(val)
                    except ValueError:
                        try:
                            val = float(val)
                        except ValueError:
                            pass
                params[p.attrib["Name"]] = val
            result.append(MacroInstance(name, params))
        return result


# quick manual check
if __name__ == "__main__":
    _g = MacroInstance("GATE", {"PathPin_A": "010101", "PathPin_B": "HLHLHL"})
    print(PinXML.serialize([_g]).decode("utf-16le"))
