from __future__ import annotations
from dataclasses import dataclass, field, asdict
from typing import Dict, Set
import json


@dataclass
class LearnedParam:
    param_aliases: Dict[str, str] = field(default_factory=dict)  # raw→canonical
    enum_extra_values: Set[str] = field(default_factory=set)     # allowed extras


@dataclass
class LearnedRules:
    macro_aliases: Dict[str, str] = field(default_factory=dict)  # raw→canonical
    per_macro: Dict[str, LearnedParam] = field(default_factory=dict)
    accept_si_suffixes: bool = True
    accept_decimal_comma: bool = True

    def to_json(self) -> str:
        data = asdict(self)
        # sets → sorted lists for stable output
        for m, lp in data["per_macro"].items():
            lp["enum_extra_values"] = sorted(lp["enum_extra_values"])
        return json.dumps(data, indent=2, ensure_ascii=False)

    @staticmethod
    def from_json(s: str) -> "LearnedRules":
        raw = json.loads(s)
        rules = LearnedRules()
        rules.macro_aliases = raw.get("macro_aliases", {})
        rules.accept_si_suffixes = bool(raw.get("accept_si_suffixes", True))
        rules.accept_decimal_comma = bool(raw.get("accept_decimal_comma", True))
        for mname, lp in (raw.get("per_macro") or {}).items():
            rules.per_macro[mname] = LearnedParam(
                param_aliases=lp.get("param_aliases", {}),
                enum_extra_values=set(lp.get("enum_extra_values", [])),
            )
        return rules


__all__ = ["LearnedRules", "LearnedParam"]

