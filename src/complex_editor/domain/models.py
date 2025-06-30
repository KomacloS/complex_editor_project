from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List


@dataclass
class MacroParam:
    name: str
    type: str | None  # "INT", "ENUM", "BOOL", ...
    default: str | None
    min: str | None
    max: str | None


@dataclass
class MacroDef:
    id_function: int
    name: str
    params: list[MacroParam]


@dataclass
class MacroInstance:
    """One concrete use of a VIVA macro inside a complex."""

    name: str
    params: Dict[str, str] = field(default_factory=dict)


@dataclass
class ComplexDevice:
    """Full complex definition (pins live in tabCompDesc columns, not XML)."""

    id_function: int
    pins: List[str]
    macro: MacroInstance


