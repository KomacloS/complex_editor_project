from __future__ import annotations
from difflib import SequenceMatcher
from typing import Dict, Iterable

from ..util.macro_xml_translator import xml_to_params
from ..domain import MacroDef
from .spec import LearnedRules, LearnedParam


def _norm(s: str) -> str:
    return " ".join(s.strip().replace("_", " ").split()).upper()


def _best(name: str, candidates: Iterable[str], thr: float = 0.7) -> str | None:
    n = _norm(name)
    best, score = None, 0.0
    for c in candidates:
        sc = SequenceMatcher(a=n, b=_norm(c)).ratio()
        if sc > score:
            best, score = c, sc
    return best if score >= thr else None


def learn_from_rows(
    rows: Iterable[tuple[str, str]],
    macro_map: Dict[int, MacroDef],
) -> LearnedRules:
    """Learn alias rules from PinS XML snippets.

    ``rows`` is an iterable of ``(macroNameOrId, pinS_xml)`` pairs, typically
    extracted from existing databases or buffer JSON dumps.  ``macro_map`` maps
    ``IDFunction`` integers to :class:`~complex_editor.domain.MacroDef` objects
    describing the canonical macro names and their parameters.
    """

    rules = LearnedRules()
    canon_names = [m.name for m in macro_map.values()]
    pdefs_by_macro = {m.name: {p.name for p in m.params} for m in macro_map.values()}

    for _name_or_id, pin_s in rows:
        try:
            parsed = xml_to_params(pin_s) or {}
        except Exception:
            continue
        for xml_macro_name, pmap in parsed.items():
            # macro alias
            if xml_macro_name not in canon_names:
                guess = _best(xml_macro_name, canon_names)
                if guess:
                    rules.macro_aliases.setdefault(xml_macro_name, guess)
                    macro_name = guess
                else:
                    continue  # unknown macro; skip param learning
            else:
                macro_name = xml_macro_name

            lp = rules.per_macro.setdefault(macro_name, LearnedParam())
            # param aliases
            declared = pdefs_by_macro.get(macro_name, set())
            for raw_p, raw_v in pmap.items():
                if raw_p not in declared:
                    guessp = _best(raw_p, declared)
                    if guessp:
                        lp.param_aliases.setdefault(raw_p, guessp)
                if isinstance(raw_v, str):
                    pass  # enum extras recorded at application-time
    return rules


__all__ = ["learn_from_rows"]

