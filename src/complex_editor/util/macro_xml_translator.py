from __future__ import annotations

"""Utility functions for converting between PinS macro XML and dictionaries.

This module exposes helpers to decode and encode the XML blobs stored in the
``S`` pin of sub–components.  The functions are intentionally small and do not
have any dependency on the rest of the project so they can be reused by the GUI
as well as command line tools.
"""

from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, Mapping, Optional
import xml.etree.ElementTree as ET
import yaml

# new import for tolerant translation
from ..learn.spec import LearnedRules


def _ensure_text(data: bytes | str | memoryview | bytearray) -> str:
    """Return *data* as a string.

    ``data`` may be a :class:`str`, :class:`bytes`, :class:`bytearray`,
    :class:`memoryview` or any object implementing the buffer protocol.  The
    bytes are decoded using a best-effort strategy trying ``utf-16``, ``utf-8``
    and finally ``latin-1`` so that malformed inputs never raise an exception.
    """

    if isinstance(data, str):
        return data

    # ``data`` might be a memoryview/bytearray or any object implementing the
    # buffer protocol.  ``bytes()`` handles these transparently and returns a
    # ``bytes`` instance which we can decode using a best-effort strategy.
    if not isinstance(data, (bytes, bytearray)):
        try:
            data = bytes(data)
        except TypeError:
            return str(data)

    for enc in ("utf-16", "utf-16-le", "utf-8", "latin-1"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    # ``latin-1`` will always decode but include replacement as last resort.
    return data.decode("latin-1", errors="replace")


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


def xml_to_params_tolerant(
    xml_bytes_or_str: bytes | str,
    macro_map=None,
    rules: LearnedRules | None = None,
) -> Dict[str, Dict[str, str]]:
    """
    Parse *xml_bytes_or_str* like :func:`xml_to_params` but apply *rules* to
    normalize macro and parameter names and coerce values.

    ``rules`` may be :class:`~complex_editor.learn.spec.LearnedRules` as loaded
    by :mod:`complex_editor.util.rules_loader`.  When provided, macro names and
    parameter names present in the XML are mapped through the learned aliases
    and simple value coercions are applied:

    * Macro aliases are resolved via ``rules.macro_aliases``.
    * Parameter aliases are resolved per macro via
      ``rules.per_macro[macro].param_aliases``.
    * Decimal commas are converted to dots when ``accept_decimal_comma`` is
      enabled.
    * SI suffixes (``k``, ``M`` …) are stripped when ``accept_si_suffixes`` is
      enabled.  Only a single trailing suffix is stripped; proper range
      validation is left to UI widgets.

    The function returns a mapping of canonical macro names to canonical
    parameter names with coerced string values.
    """

    parsed = xml_to_params(xml_bytes_or_str) or {}
    if not rules:
        return parsed

    out: Dict[str, Dict[str, str]] = {}
    for raw_macro, params in parsed.items():
        macro = rules.macro_aliases.get(raw_macro, raw_macro)
        lparam = rules.per_macro.get(macro)
        canon_params: Dict[str, str] = {}
        for raw_p, val in (params or {}).items():
            pname = raw_p
            if lparam:
                pname = lparam.param_aliases.get(raw_p, raw_p)
            sval = str(val)
            if rules.accept_decimal_comma and "," in sval and "." not in sval:
                sval = sval.replace(",", ".")
            if rules.accept_si_suffixes:
                for suf in ("k", "K", "M", "G", "m", "u", "µ", "n", "p"):
                    if sval.endswith(suf):
                        sval = sval[:-1]
                        break
            canon_params[pname] = sval
        out.setdefault(macro, {}).update(canon_params)
    return out


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

    The optional ``schema`` parameter may provide default values for parameters.
    If provided (or if the built-in defaults are loaded), parameters matching
    their default values are omitted from the resulting XML.  The ``GATE`` macro
    is also validated so that ``Check_[A-D]`` parameters either match the length
    of their corresponding ``PathPin_[A-D]`` values or are left empty.
    """

    defaults = _extract_defaults(schema) if schema is not None else _load_defaults()

    root = ET.Element("R")
    macros_el = ET.SubElement(root, "Macros")
    for mname, params in macros.items():
        if mname == "GATE":
            _validate_gate(params)
        m_el = ET.SubElement(macros_el, "Macro", {"Name": str(mname)})
        dvals = defaults.get(mname, {})
        for pname, value in (params or {}).items():
            if pname in dvals and _is_default(value, dvals[pname]):
                continue
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


# ---------------------------------------------------------------------------
# helper utilities


def _is_default(val: Any, default: Any) -> bool:
    if val in (None, ""):
        return True
    if isinstance(val, str) and val.strip().lower() == "default":
        return True
    try:
        return float(val) == float(default)
    except (TypeError, ValueError):
        return str(val) == str(default)


@lru_cache(maxsize=1)
def _load_defaults(
    path: Path = Path(__file__).resolve().parents[1]
    / "resources"
    / "function_param_allowed.yaml",
) -> Mapping[str, Dict[str, Any]]:
    data = load_schema(path)
    return _extract_defaults(data)


def _extract_defaults(data: Mapping[str, Mapping[str, Any]]) -> Mapping[str, Dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for fname, params in data.items():
        if isinstance(params, Mapping):
            d: dict[str, Any] = {}
            for pname, spec in params.items():
                if isinstance(spec, Mapping) and "default" in spec:
                    d[pname] = spec["default"]
            result[fname] = d
    return result


def _validate_gate(params: Mapping[str, Any]) -> None:
    def _plen(v: Any) -> int:
        if v is None:
            return 0
        s = str(v)
        return 0 if s in {"", "-1", "-1.0"} else len(s)

    for suf in "ABCD":
        path_len = _plen(params.get(f"PathPin_{suf}"))
        check_len = _plen(params.get(f"Check_{suf}"))
        if path_len == 0 and check_len != 0:
            raise ValueError(f"Check_{suf} without PathPin_{suf}")
        if path_len > 0 and check_len not in (0, path_len):
            raise ValueError(
                f"Check_{suf} length {check_len} does not match PathPin_{suf} length {path_len}"
            )
