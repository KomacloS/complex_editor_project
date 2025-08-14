
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from ..parameters.interface import MacroParamProvider, NullParamProvider


log = logging.getLogger(__name__)


@dataclass
class BufferSubComponent:
    """Raw sub-component as loaded from ``buffer.json``.

    ``pin_s`` contains the raw XML stored in the ``S`` pin if present.
    """

    name: str
    refdes: Optional[str]
    id_function: Optional[int]
    macro_name: Optional[str]
    pin_map: Dict[str, str]
    pin_s: Optional[str] = None
    value: Optional[str] = None


@dataclass
class BufferComplex:
    """Container for a complex loaded from ``buffer.json``."""

    complex_name: str
    complex_id: Optional[int]
    sub_components: List[BufferSubComponent]


@dataclass
class WizardPrefill:
    """Data passed to :class:`~complex_editor.ui.new_complex_wizard.NewComplexWizard`.

    ``sub_components`` contains entries with the keys ``macro_name``,
    ``id_function`` (optional) and ``pins`` (list of pad numbers).  This mirrors
    the internal structure expected by the wizard's list page.
    """

    complex_name: str
    sub_components: List[Dict[str, Any]]


def load_complex_from_buffer_json(path: str | Path) -> BufferComplex:
    """Parse a ``buffer.json`` file.

    The parser is intentionally forgiving and accepts several shapes as
    produced by different tooling revisions.
    """

    p = Path(path)
    with p.open("r", encoding="utf-8") as f:
        raw = json.load(f)

    if isinstance(raw, list):
        complex_name = ""
        complex_id: Optional[int] = None
        sub_raw = raw
    elif isinstance(raw, dict):
        cx = raw.get("Complex") or raw
        complex_name = str(cx.get("Name", ""))
        complex_id = cx.get("ID")
        sub_raw = raw.get("SubComponents") or raw.get("Subcomponents") or []
    else:  # pragma: no cover - defensive
        raise ValueError("Unsupported buffer format")

    sub_components: List[BufferSubComponent] = []
    for entry in sub_raw:
        if not isinstance(entry, dict):
            continue
        name = str(entry.get("Name") or entry.get("Alias") or "")
        refdes = entry.get("RefDes") or entry.get("Ref")
        id_function = (
            entry.get("IDFunction")
            or entry.get("IdFunction")
            or entry.get("FunctionID")
        )
        if id_function is not None:
            try:
                id_function = int(id_function)
            except Exception:  # pragma: no cover - best effort
                id_function = None
        macro_name = (
            entry.get("MacroName")
            or entry.get("FunctionName")
            or entry.get("Macro")
        )

        pin_map: Dict[str, str] = {}
        s_xml: Optional[str] = None
        value = entry.get("Value") or entry.get("value")
        raw_pins = entry.get("PinMap") or entry.get("Pins")
        if isinstance(raw_pins, dict):
            for k, v in raw_pins.items():
                if str(k) == "S":
                    s_xml = str(v)
                else:
                    pin_map[str(k)] = str(v)
        else:
            for key, val in entry.items():
                if not key:
                    continue
                k = str(key)
                if k in {"PinS", "MacroParameters", "Parameters"}:
                    if k == "PinS":
                        s_xml = str(val)
                    continue
                if k.startswith("Pin") and len(k) == 4 and k[3].isalpha():
                    pin_map[k] = str(val)
                elif k in list("ABCDEFGH"):
                    pin_map[f"Pin{k.upper()}"] = str(val)
        sub_components.append(
            BufferSubComponent(
                name=name,
                refdes=str(refdes) if refdes is not None else None,
                id_function=id_function,
                macro_name=str(macro_name) if macro_name is not None else None,
                pin_map=pin_map,
                pin_s=s_xml,
                value=str(value) if value not in (None, "") else None,
            )
        )

    return BufferComplex(
        complex_name=complex_name,
        complex_id=complex_id if complex_id is not None else None,
        sub_components=sub_components,
    )


def to_wizard_prefill(
    buffer: BufferComplex,
    macro_id_resolver: Callable[[str], Optional[int]],
    pin_normalizer: Callable[[Dict[str, str]], Dict[str, str]],
    param_provider: MacroParamProvider | None = None,
) -> WizardPrefill:
    """Convert a :class:`BufferComplex` into :class:`WizardPrefill`.

    ``param_provider`` is currently unused but reserved for future PinS
    integration.
    """

    param_provider = param_provider or NullParamProvider()

    prefill_subs: List[Dict[str, Any]] = []
    for sc in buffer.sub_components:
        macro_name = sc.macro_name or ""
        id_function = sc.id_function
        if id_function is None and macro_name:
            try:
                resolved = macro_id_resolver(macro_name)
            except Exception:  # pragma: no cover - resolver errors are logged
                resolved = None
            if resolved is not None:
                id_function = resolved
            else:
                log.warning("Could not resolve macro '%s' to ID", macro_name)

        normalized = pin_normalizer(sc.pin_map)
        pins: List[int] = []
        seen: set[str] = set()
        for key in sorted(normalized.keys()):
            if not key.startswith("Pin"):
                log.warning("Ignoring illegal pin name '%s'", key)
                continue
            val = normalized[key]
            if val in seen:
                log.warning(
                    "Duplicate pin '%s' in sub-component '%s'", val, sc.name
                )
                continue
            seen.add(val)
            try:
                pins.append(int(val))
            except Exception:
                log.warning(
                    "Illegal pin value '%s' in sub-component '%s'", val, sc.name
                )

        prefill_subs.append(
            {
                "macro_name": macro_name or sc.name,
                "id_function": id_function,
                "pins": pins,
                "name": sc.name,
                "refdes": sc.refdes,
                "pins_s": sc.pin_s,
                "value": sc.value,
            }
        )

    return WizardPrefill(complex_name=buffer.complex_name, sub_components=prefill_subs)
