"""Utilities for selecting XML macro names based on MDB rules."""
from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping
import re
import operator

from complex_editor.utils import yaml_adapter as yaml
from packaging.version import Version

OPS = {
    "==": operator.eq,
    "!=": operator.ne,
    ">=": operator.ge,
    "<=": operator.le,
    ">": operator.gt,
    "<": operator.lt,
}


def load_rules(path: str | Path) -> dict:
    """Load macro selection rules from *path*."""
    p = Path(path)
    with p.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def _coerce(value: Any) -> Any:
    """Coerce *value* to int/float/:class:`Version` when appropriate."""
    if isinstance(value, (int, float, Version)):
        return value
    s = str(value)
    if re.fullmatch(r"\d+(?:\.\d+)+", s):
        return Version(s)
    try:
        return int(s)
    except ValueError:
        try:
            return float(s)
        except ValueError:
            return s


def eval_criteria(expr: str | None, ctx: Mapping[str, Any]) -> bool:
    """Evaluate a selection *expr* against *ctx*.

    The expected syntax is ``?VAR OP VALUE`` where ``OP`` is one of ``==``,
    ``!=``, ``>=``, ``<=``, ``>`` or ``<``.  ``VALUE`` may be numeric or a
    dotted version string.  Missing variables in the context result in
    ``False``.
    """

    if not expr:
        return True
    m = re.match(r"^\?(?P<var>[A-Za-z_][A-Za-z0-9_]*)\s*(==|!=|>=|<=|>|<)\s*(?P<val>.+)$", expr)
    if not m:
        return False
    var = m.group("var")
    op = m.group(2)
    val = m.group("val").strip()
    if var not in ctx:
        return False
    left = _coerce(ctx[var])
    right = _coerce(val)
    # If either side looks like a version, convert both to Version
    if isinstance(left, str) and re.fullmatch(r"\d+(?:\.\d+)+", left):
        left = Version(left)
    if isinstance(right, str) and re.fullmatch(r"\d+(?:\.\d+)+", right):
        right = Version(right)
    return OPS[op](left, right)


def choose_macro(function_name: str, ctx: Mapping[str, Any], rules: Mapping) -> str:
    """Choose the XML macro name for *function_name* using *rules* and *ctx*."""
    entry = rules.get(function_name)
    if not entry:
        return function_name
    candidates = sorted(entry.get("candidates", []), key=lambda c: c.get("order", 0))
    if not candidates:
        return function_name
    if entry.get("ignore_selection_criteria"):
        return candidates[0]["macro_name"]
    for cand in candidates:
        if eval_criteria(cand.get("criteria"), ctx):
            return cand["macro_name"]
    return candidates[0]["macro_name"]


def map_macro_to_function(macro_name: str, inv_map: Mapping[str, list[str]]) -> str | None:
    """Return the canonical function for *macro_name* or ``None`` if ambiguous."""
    funcs = inv_map.get(macro_name, [])
    return funcs[0] if len(funcs) == 1 else None
