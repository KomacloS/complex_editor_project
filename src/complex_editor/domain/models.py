from __future__ import annotations

from dataclasses import dataclass


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

