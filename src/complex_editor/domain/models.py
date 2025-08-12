from __future__ import annotations

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


@dataclass(init=False)
class ComplexDevice:
    """Full complex definition used by the editor.

    ``pins`` can either be provided directly or be derived from the
    ``subcomponents``.  The :pyattr:`pins` attribute is exposed as a property
    returning a sorted, unique list of stringified pin numbers.
    """

    id_function: int
    macro: MacroInstance
    subcomponents: list["SubComponent"] = field(default_factory=list)
    _pins: list[str] = field(default_factory=list)

    def __init__(
        self,
        id_function: int,
        pins: List[str] | None,
        macro: MacroInstance,
        subcomponents: list["SubComponent"] | None = None,
    ) -> None:
        self.id_function = id_function
        self.macro = macro
        self.subcomponents = subcomponents or []
        self._pins = [str(p) for p in pins] if pins else []

    @property
    def pins(self) -> list[str]:
        """Return a stable list of pin names.

        If explicit pins were supplied they take precedence; otherwise the
        union of pins from all sub-components is used.
        """

        if self._pins:
            return list(self._pins)
        pin_set = {
            str(p)
            for sc in self.subcomponents
            for p in getattr(sc, "pins", [])
        }
        # sort numerically when possible, otherwise lexicographically
        return sorted(pin_set, key=lambda x: (int(x) if x.isdigit() else float("inf"), x))

    @pins.setter
    def pins(self, value: List[str]) -> None:
        self._pins = [str(p) for p in value]


@dataclass
class SubComponent:
    """One macro instance mapped to specific pins within a complex."""

    macro: MacroInstance
    pins: list[int] = field(default_factory=list)


