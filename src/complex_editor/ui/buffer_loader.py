from __future__ import annotations

from pathlib import Path
from typing import List, Dict, Any
import json

from .adapters import EditorComplex, EditorMacro
from ..util.macro_xml_translator import xml_to_params, _ensure_text


def load_editor_complexes_from_buffer(path: str | Path) -> List[EditorComplex]:
    """Read ``path`` and return a list of :class:`EditorComplex`.

    The buffer JSON is expected to be a list of complexes as produced by
    ``tools/make_gui_buffer.py``.  Each complex entry should contain ``id``,
    ``name``, ``pins`` and a ``subcomponents`` list with ``function_name`` and
    a ``pins`` mapping.  Optional fields like ``id``/``value``/``force_bits`` on
    subcomponents are attached to the returned :class:`EditorMacro` objects as
    attributes for convenience.
    """

    p = Path(path)
    with p.open("r", encoding="utf-8") as f:
        raw = json.load(f)

    result: List[EditorComplex] = []
    for cx in raw:
        name = str(cx.get("name", ""))
        cid = int(cx.get("id", 0) or 0)
        pins = [str(x) for x in (cx.get("pins") or [])]

        sub_macros: List[EditorMacro] = []
        for sc in cx.get("subcomponents") or []:
            macro_name = str(
                sc.get("function_name") or f"Function {sc.get('id_function', '')}"
            )
            pin_map: Dict[str, str] = {}
            s_xml = None
            for k, v in (sc.get("pins") or {}).items():
                if k == "S":
                    s_xml = v
                    continue
                pin_map[str(k)] = str(v)

            all_macros: Dict[str, Dict[str, str]] = {}
            selected_macro = macro_name
            macro_params: Dict[str, str] = {}
            pin_s_error = False
            pin_s_raw = ""
            if s_xml:
                pin_s_raw = _ensure_text(s_xml)
                try:
                    all_macros = xml_to_params(s_xml)
                except Exception:
                    all_macros = {}
                    pin_s_error = True
                else:
                    if len(all_macros) == 1:
                        selected_macro = next(iter(all_macros))
                    elif macro_name in all_macros:
                        selected_macro = macro_name
                    elif all_macros:
                        selected_macro = next(iter(all_macros))
                    macro_params = dict(all_macros.get(selected_macro, {}))
                    if not all_macros:
                        pin_s_error = True

            em = EditorMacro(
                name=macro_name,
                pins=pin_map,
                params=macro_params,
                selected_macro=selected_macro,
                macro_params=macro_params,
                all_macros=all_macros,
                pin_s_error=pin_s_error,
                pin_s_raw=pin_s_raw,
            )
            if sc.get("id") is not None:
                em.sub_id = sc.get("id")
            if sc.get("value") is not None:
                em.value = sc.get("value")
            if sc.get("force_bits") is not None:
                em.force_bits = sc.get("force_bits")
            sub_macros.append(em)

        result.append(
            EditorComplex(id=cid, name=name, pins=pins, subcomponents=sub_macros)
        )
    return result
