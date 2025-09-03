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
    overrides: list[tuple[str, str]] = field(default_factory=list)


@dataclass
class ComplexDevice:
    """Full complex definition (pins live in tabCompDesc columns, not XML)."""

    id_function: int
    pins: List[str]
    macro: MacroInstance
    pn: str = ""
    alt_pn: str = ""
    # NEW: multiple alternative PNs carried in-memory for UI; optional
    aliases: List[str] = field(default_factory=list)
    pin_count: int = 0
    subcomponents: List[SubComponent] = field(default_factory=list)
    id: int | None = None


@dataclass
class SubComponent:
    """One macro instance mapped to specific pins within a complex."""
    macro: MacroInstance
    pins: tuple[int, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        # ensure an immutable tuple is always stored internally
        self.pins = tuple(self.pins)


