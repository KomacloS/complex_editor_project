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
import html
from decimal import Decimal, localcontext, InvalidOperation

# new import for tolerant translation
from ..learn.spec import LearnedRules


def _ensure_text(data: bytes | str | memoryview | bytearray) -> str:
    """Return *data* as a string.

    Tries utf-16, utf-16-le, utf-8, latin-1. Never raises on malformed input.
    """
    if isinstance(data, str):
        return data
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
    return data.decode("latin-1", errors="replace")


def xml_to_params(xml: bytes | str) -> Dict[str, Dict[str, str]]:
    """Parse the ``PinS`` XML blob into a nested mapping {Macro:{Param:Value}}."""
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
    Parse like :func:`xml_to_params` but apply *rules* to normalize aliases and
    coerce values (decimal comma, simple SI suffix stripping).
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


# ------------------------- XML serialization -----------------------------

def _xml_esc(s: Any) -> str:
    """Escape a value for XML attribute usage with quotes."""
    return html.escape(str(s), quote=True)


def _fmt_number(v: Any) -> str:
    """
    Deterministic number formatting:
      • bool → '1' / '0'
      • int → '123'
      • float/Decimal → no scientific notation; trim trailing zeros;
        integral floats become integers ('1.0' → '1')
      • numeric-looking strings ('1.0', '2.500', '0,10') are parsed via Decimal
        (comma accepted) and formatted as above
      • other values → str(v)
    """
    if isinstance(v, bool):
        return "1" if v else "0"
    if isinstance(v, int):
        return str(v)
    if isinstance(v, float):
        with localcontext() as ctx:
            ctx.prec = 28
            d = Decimal(repr(v)).normalize()
        if d == d.to_integral():
            return str(d.quantize(Decimal(1)))
        s = format(d, "f")
        return s.rstrip("0").rstrip(".")
    if isinstance(v, Decimal):
        d = v.normalize()
        if d == d.to_integral():
            return str(d.quantize(Decimal(1)))
        s = format(d, "f")
        return s.rstrip("0").rstrip(".")
    if isinstance(v, str):
        s = v.strip()
        if "," in s and "." not in s:
            s = s.replace(",", ".")
        try:
            with localcontext() as ctx:
                ctx.prec = 28
                d = Decimal(s).normalize()
            if d == d.to_integral():
                return str(d.quantize(Decimal(1)))
            out = format(d, "f").rstrip("0").rstrip(".")
            return out if out else "0"
        except InvalidOperation:
            return v
    return str(v)


def params_to_xml(
    macros: Mapping[str, Mapping[str, Any]],
    *,
    encoding: str = "utf-16",
    schema: Optional[Mapping[str, Mapping[str, Any]]] = None,
    pretty: bool = False,  # default minified (single line) to match target
) -> bytes:
    """
    Serialize *macros* into the exact ``PinS`` XML format expected by VIVA.

    Key guarantees:
      • XML declaration: <?xml version="1.0" encoding="utf-16"?>
      • Root namespaces on <R>: xmlns:xsd / xmlns:xsi
      • <Param> attribute order is Value then Name
      • Numbers normalized; integral floats become integers (e.g., '1.0' → '1')
      • Defaults (from schema) omitted
      • Returns *bytes* in requested *encoding*

    Set pretty=True to get multi-line, indented XML for debugging; default is
    the single-line format you provided as the target.
    """
    defaults = _extract_defaults(schema) if schema is not None else _load_defaults()

    # Validate GATE macro up front
    if "GATE" in macros:
        _validate_gate(macros["GATE"])

    # Build as tokens to control whitespace and attribute order precisely
    toks: list[str] = []
    toks.append('<?xml version="1.0" encoding="utf-16"?>')
    toks.append('<R xmlns:xsd="http://www.w3.org/2001/XMLSchema" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">')
    toks.append('<Macros>')

    def _is_gate_path_or_check(m: str, p: str) -> bool:
        ml = (m or "").strip().upper()
        pl = (p or "").strip().lower()
        if ml != "GATE":
            return False
        if pl.startswith("pathpin_") or pl.startswith("check_"):
            return True
        # common aliases sometimes used by tools
        return pl in {"pathpins", "checksum"}

    for mname, params in macros.items():
        toks.append(f'<Macro Name="{_xml_esc(mname)}">')
        dvals = defaults.get(mname, {}) if defaults else {}
        for pname, value in (params or {}).items():
            if pname in dvals and _is_default(value, dvals[pname]):
                continue
            # Preserve strings for GATE PathPin_*/Check_* parameters (leading zeros matter)
            if _is_gate_path_or_check(mname, pname):
                vtxt = str(value)
            else:
                vtxt = _fmt_number(value)
            # Attribute order: Value then Name
            toks.append(f'<Param Value="{_xml_esc(vtxt)}" Name="{_xml_esc(pname)}" />')
        toks.append('</Macro>')

    toks.append('</Macros>')
    toks.append('</R>')

    if pretty:
        # Expand the same tokens with newlines/indentation
        # Minimal pretty printer (no dependency on minidom)
        out: list[str] = []
        indent = 0
        for t in toks:
            if t.startswith("</"):
                indent = max(indent - 2, 0)
            out.append(" " * indent + t)
            if t.startswith("<") and not t.startswith("</") and not t.endswith("/>") and not t.startswith('<?xml'):
                indent += 2
        xml_text = "\n".join(out)
    else:
        # Minified: single line with single spaces between tokens
        xml_text = " ".join(toks)

    return xml_text.encode(encoding, errors="strict")


def load_schema(path: str | Path) -> Mapping[str, Any]:
    """Load a YAML schema file if one is provided."""
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
