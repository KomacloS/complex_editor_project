"""Domain models for the standalone Complex Editor demo application.

These dataclasses intentionally avoid UI-specific concerns so that they can be
shared between the repository implementation and the Tkinter widgets.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass(slots=True)
class MacroParameterSpec:
    """Describe a single configurable parameter for a macro.

    Attributes
    ----------
    name:
        Parameter identifier as it appears in the buffer/database.
    type:
        Logical type (``int``, ``float``, ``bool``, ``str``, ``enum``, ``list[str]``).
    default:
        Default value as supplied by the macro catalog.
    required:
        Whether a value must be supplied when editing a subcomponent.
    choices:
        Optional collection of valid values (used for enum/list fields).
    minimum / maximum:
        Optional numeric range constraints.
    step:
        Preferred increment when editing numeric values.
    help:
        Human readable explanation shown in the parameter dialog.
    dependencies:
        Declarative dependency rules. Keys represent other parameter names and
        values are the allowed values for this parameter. When dependencies are
        active the UI will clamp the available choices/validations accordingly.
    """

    name: str
    type: str
    default: Any
    required: bool = False
    choices: Optional[List[Any]] = None
    minimum: Optional[float] = None
    maximum: Optional[float] = None
    step: Optional[float] = None
    help: str = ""
    dependencies: Dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class Macro:
    """Macro definition with a friendly name and parameter schema."""

    name: str
    description: str
    parameters: Dict[str, MacroParameterSpec]

    def non_default_summary(self, values: Dict[str, Any]) -> Dict[str, Any]:
        """Return only parameters that diverge from the catalog defaults."""
        summary: Dict[str, Any] = {}
        for key, spec in self.parameters.items():
            if key not in values:
                continue
            if values[key] != spec.default:
                summary[key] = values[key]
        return summary


@dataclass(slots=True)
class Subcomponent:
    """A single macro instantiation inside a complex."""

    position: int
    macro: str
    pin_a: str = ""
    pin_b: str = ""
    pin_c: str = ""
    pin_d: str = ""
    parameters: Dict[str, Any] = field(default_factory=dict)

    def pins(self) -> Dict[str, str]:
        return {"A": self.pin_a, "B": self.pin_b, "C": self.pin_c, "D": self.pin_d}


@dataclass(slots=True)
class Complex:
    """Model for the complex assembly being edited."""

    identifier: str
    part_number: str
    alternate_part_numbers: List[str] = field(default_factory=list)
    aliases: List[str] = field(default_factory=list)
    pin_count: int = 0
    subcomponents: List[Subcomponent] = field(default_factory=list)


@dataclass(slots=True)
class Catalog:
    """In-memory representation of the macro catalog."""

    macros: Dict[str, Macro] = field(default_factory=dict)

    def get(self, name: str) -> Optional[Macro]:
        return self.macros.get(name)

    def names(self) -> List[str]:
        return sorted(self.macros)


def build_sample_catalog() -> Catalog:
    """Return a small catalog used by the demo application and unit tests."""

    resistor = Macro(
        name="Resistor",
        description="Generic resistor",
        parameters={
            "value": MacroParameterSpec(
                name="value",
                type="float",
                default=1000.0,
                minimum=0.1,
                maximum=1_000_000,
                step=10.0,
                help="Resistance value in Ohms.",
            ),
            "tolerance": MacroParameterSpec(
                name="tolerance",
                type="enum",
                default="1%",
                choices=["0.1%", "0.5%", "1%", "5%"],
                help="Manufacturing tolerance.",
            ),
        },
    )

    buffer_gate = Macro(
        name="BufferGate",
        description="CMOS buffer",
        parameters={
            "channels": MacroParameterSpec(
                name="channels",
                type="int",
                default=1,
                minimum=1,
                maximum=8,
                step=1,
                help="Number of buffered channels in the package.",
            ),
            "schmitt": MacroParameterSpec(
                name="schmitt",
                type="bool",
                default=False,
                help="Enable Schmitt trigger inputs.",
            ),
            "drive_ma": MacroParameterSpec(
                name="drive_ma",
                type="enum",
                default=4,
                choices=[2, 4, 8, 12],
                help="Drive strength in milliamps.",
                dependencies={"schmitt": False},
            ),
        },
    )

    led = Macro(
        name="LED",
        description="Indicator LED",
        parameters={
            "color": MacroParameterSpec(
                name="color",
                type="enum",
                default="red",
                choices=["red", "green", "blue", "amber"],
                help="Lens color.",
            ),
            "forward_voltage": MacroParameterSpec(
                name="forward_voltage",
                type="float",
                default=2.0,
                minimum=1.2,
                maximum=3.6,
                step=0.1,
                help="Forward voltage at nominal current.",
            ),
            "diffused": MacroParameterSpec(
                name="diffused",
                type="bool",
                default=True,
                help="Diffused lens option.",
            ),
        },
    )

    return Catalog({m.name: m for m in (resistor, buffer_gate, led)})
