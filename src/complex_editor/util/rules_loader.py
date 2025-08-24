from __future__ import annotations
from pathlib import Path

from ..learn.spec import LearnedRules

_DEFAULT = Path(__file__).resolve().parents[1] / "data" / "learned_rules.json"
_cache: LearnedRules | None = None


def get_learned_rules(path: Path | None = None) -> LearnedRules | None:
    global _cache
    if _cache is not None:
        return _cache
    p = path or _DEFAULT
    if not p.exists():
        return None
    _cache = LearnedRules.from_json(p.read_text(encoding="utf-8"))
    return _cache


__all__ = ["get_learned_rules"]

