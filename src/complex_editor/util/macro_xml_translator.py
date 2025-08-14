from __future__ import annotations

"""Utility functions for converting between PinS macro XML and dictionaries.

This module exposes helpers to decode and encode the XML blobs stored in the
``S`` pin of sub–components.  The functions are intentionally small and do not
have any dependency on the rest of the project so they can be reused by the GUI
as well as command line tools.
"""

from pathlib import Path
from typing import Any, Dict, Mapping, Optional
import xml.etree.ElementTree as ET
import yaml


def _ensure_text(data: bytes | str) -> str:
    """Return *data* as text.

    Parameters
    ----------
    data:
        Bytes or string containing XML.  Various encodings used by legacy
        tools are tolerated (``utf-16``, ``utf-16-le`` and ``utf-8``).
    """

    if isinstance(data, str):
        return data
    for enc in ("utf-16", "utf-16-le", "utf-8"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    # Last resort – decode as utf-8 with replacement to avoid raising.
    return data.decode("utf-8", errors="replace")


def xml_to_params(xml: bytes | str) -> Dict[str, Dict[str, str]]:
    """Parse the ``PinS`` XML blob into a nested mapping.

    The returned mapping has the shape ``{MacroName: {ParamName: Value}}``.
    If *xml* is empty or malformed an empty dictionary is returned.
    """

    text = _ensure_text(xml).strip()
    if not text:
        return {}
    try:
        root = ET.fromstring(text)
    except ET.ParseError:
        return {}
    macros_elem = root.find("Macros")
    result: Dict[str, Dict[str, str]] = {}
    if macros_elem is None:
        return result
    for macro in macros_elem.findall("Macro"):
        mname = macro.get("Name", "")
        params: Dict[str, str] = {}
        for param in macro.findall("Param"):
            pname = param.get("Name", "")
            pval = param.get("Value", "")
            params[pname] = pval
        result[mname] = params
    return result


def params_to_xml(
    macros: Mapping[str, Mapping[str, Any]],
    *,
    encoding: str = "utf-16",
    schema: Optional[Mapping[str, Mapping[str, Any]]] = None,
) -> bytes:
    """Serialize *macros* into the ``PinS`` XML format.

    ``macros`` is expected to be a mapping of ``{MacroName: {ParamName: Value}}``.
    The output always contains an XML declaration and is encoded using
    ``encoding`` (``utf-16`` by default for compatibility with legacy tools).

    The optional ``schema`` parameter may contain validation/coercion rules, but
    it is currently only a placeholder and values are written verbatim.
    """

    root = ET.Element("R")
    macros_el = ET.SubElement(root, "Macros")
    for mname, params in macros.items():
        m_el = ET.SubElement(macros_el, "Macro", {"Name": str(mname)})
        for pname, value in (params or {}).items():
            ET.SubElement(
                m_el,
                "Param",
                {"Name": str(pname), "Value": "" if value is None else str(value)},
            )
    return ET.tostring(root, encoding=encoding, xml_declaration=True)


def load_schema(path: str | Path) -> Mapping[str, Any]:
    """Load a YAML schema file if one is provided.

    The schema is optional and is primarily intended for future validation of
    parameter values.  This function simply returns the loaded mapping and will
    raise ``OSError``/``yaml.YAMLError`` if the file cannot be read.
    """

    p = Path(path)
    with p.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}
