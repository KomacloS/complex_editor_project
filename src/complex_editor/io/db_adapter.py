from __future__ import annotations

import logging
from typing import Callable, Optional, Dict, Any

from .buffer_loader import WizardPrefill

log = logging.getLogger(__name__)

def to_wizard_prefill_from_db(
    db_complex,
    macro_id_resolver: Callable[[str], Optional[int]],
    pin_normalizer: Callable[[dict], dict],
) -> WizardPrefill:
    """Convert a DB-loaded complex into :class:`WizardPrefill`.

    ``db_complex`` is expected to expose ``name``, ``total_pins`` and
    ``subcomponents`` where each sub-component has ``id_function`` and a
    ``pins`` mapping (e.g. ``{"A":1, "B":2}``).  ``macro_name`` can be
    optionally provided on each sub-component; if ``id_function`` is missing but
    ``macro_name`` is present, ``macro_id_resolver`` is used to resolve it to an
    ID.  Pin names are normalized through ``pin_normalizer`` and converted to the
    integer list expected by the wizard.
    """

    prefill_subs: list[Dict[str, Any]] = []

    for sc in getattr(db_complex, "subcomponents", []) or []:
        macro_name = getattr(sc, "macro_name", "") or ""
        id_function = getattr(sc, "id_function", None)
        if (id_function is None or id_function == 0) and macro_name:
            try:
                resolved = macro_id_resolver(macro_name)
            except Exception:  # pragma: no cover - resolver errors are logged
                resolved = None
            if resolved is not None:
                id_function = resolved
            else:
                log.warning("Could not resolve macro '%s' to ID", macro_name)

        pin_map = {f"Pin{k}": str(v) for k, v in (getattr(sc, "pins", {}) or {}).items()}
        normalized = pin_normalizer(pin_map)
        pins: list[int] = []
        seen: set[str] = set()
        for key in sorted(normalized.keys()):
            if not key.startswith("Pin"):
                log.warning("Ignoring illegal pin name '%s'", key)
                continue
            val = normalized[key]
            if val in seen:
                log.warning("Duplicate pin '%s' in sub-component", val)
                continue
            seen.add(val)
            try:
                pins.append(int(val))
            except Exception:
                log.warning("Illegal pin value '%s'", val)
        prefill_subs.append(
            {
                "macro_name": macro_name,
                "id_function": id_function,
                "pins": pins,
            }
        )

    prefill = WizardPrefill(
        complex_name=getattr(db_complex, "name", ""),
        sub_components=prefill_subs,
    )
    # total pin count is not part of WizardPrefill dataclass, but we attach it as
    # a dynamic attribute so callers can use it if available.
    setattr(prefill, "pin_count", getattr(db_complex, "total_pins", 0))
    return prefill
