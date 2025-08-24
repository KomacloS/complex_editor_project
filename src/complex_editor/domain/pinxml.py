
"""Serialise / de-serialise <R><Macros><Macro …><Param …/></Macro></Macros></R>
blocks used in detCompDesc.PinS (UTF-16 XML)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List

from ..util.macro_xml_translator import params_to_xml, xml_to_params


@dataclass(slots=True, frozen=True)
class MacroInstance:
    name: str
    params: Dict[str, Any] = field(default_factory=dict)


class PinXML:
    """Helpers to serialise/deserialise PinS XML blocks."""

    # ---------- public API ----------

    @staticmethod
    def serialize(macros: List[MacroInstance], *, encoding: str = "utf-16") -> bytes:
        """Return PinS XML for *macros* excluding default parameters."""

        mapping: Dict[str, Dict[str, Any]] = {m.name: dict(m.params) for m in macros}
        return params_to_xml(mapping, encoding=encoding)

    @staticmethod
    def deserialize(xml: bytes | str) -> List[MacroInstance]:
        """Parse PinS XML into :class:`MacroInstance` objects."""

        result: List[MacroInstance] = []
        for name, params in xml_to_params(xml).items():
            converted: Dict[str, Any] = {}
            for pname, pval in params.items():
                if pval is None:
                    converted[pname] = None
                    continue
                try:
                    converted[pname] = int(pval)
                except (TypeError, ValueError):
                    try:
                        converted[pname] = float(pval)
                    except (TypeError, ValueError):
                        converted[pname] = pval
            result.append(MacroInstance(name, converted))
        return result


# quick manual check
if __name__ == "__main__":
    _g = MacroInstance("GATE", {"PathPin_A": "010101", "PathPin_B": "HLHLHL"})
    print(PinXML.serialize([_g]).decode("utf-16le"))
