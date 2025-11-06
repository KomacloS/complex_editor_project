"""General validation helpers shared between widgets and tests."""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Dict, Iterable, List, Tuple

from .models import Catalog, Complex, Macro, MacroParameterSpec, Subcomponent
from .pins import Row, ValidationError, flatten_pins, parse_pin_field, validate_pins

@dataclass(slots=True)
class FieldError:
    field: str
    message: str


# ---------------------------------------------------------------------------
def validate_part_number(pn: str) -> List[FieldError]:
    if not pn or not pn.strip():
        return [FieldError("part_number", "Part number is required")]
    return []


def validate_aliases(values: Iterable[str]) -> List[FieldError]:
    errors: List[FieldError] = []
    for alias in values:
        if not alias:
            continue
        if not alias.strip():
            errors.append(FieldError("aliases", "Alias cannot be blank"))
    return errors


def _enforce_dependencies(spec: MacroParameterSpec, values: Dict[str, object]) -> Tuple[bool, str | None]:
    if not spec.dependencies:
        return True, None
    for key, allowed in spec.dependencies.items():
        current = values.get(key)
        if isinstance(allowed, (list, tuple, set)):
            if current not in allowed:
                return False, f"Requires {key} in {sorted(allowed)}"
        else:
            if current != allowed:
                return False, f"Requires {key} = {allowed!r}"
    return True, None


def validate_parameters(macro: Macro, values: Dict[str, object]) -> List[FieldError]:
    errors: List[FieldError] = []
    for name, spec in macro.parameters.items():
        value = values.get(name, spec.default)
        ok, message = _enforce_dependencies(spec, values)
        if not ok:
            errors.append(FieldError(name, message or "Dependency not satisfied"))
            continue
        if value is None:
            if spec.required:
                errors.append(FieldError(name, "Value required"))
            continue
        if spec.type == "int":
            if not isinstance(value, int):
                errors.append(FieldError(name, "Must be an integer"))
                continue
        elif spec.type == "float":
            if not isinstance(value, (int, float)):
                errors.append(FieldError(name, "Must be a number"))
                continue
        elif spec.type == "bool":
            if not isinstance(value, bool):
                errors.append(FieldError(name, "Must be true/false"))
                continue
        elif spec.type == "enum":
            if value not in (spec.choices or []):
                errors.append(FieldError(name, f"Must be one of {spec.choices}"))
                continue
        elif spec.type == "str":
            if not isinstance(value, str):
                errors.append(FieldError(name, "Must be text"))
                continue
        elif spec.type == "list[str]":
            if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
                errors.append(FieldError(name, "Must be a list of strings"))
                continue
        if isinstance(value, (int, float)):
            if spec.minimum is not None and value < spec.minimum:
                errors.append(FieldError(name, f"Must be >= {spec.minimum}"))
            if spec.maximum is not None and value > spec.maximum:
                errors.append(FieldError(name, f"Must be <= {spec.maximum}"))
    return errors


def validate_subcomponent(sub: Subcomponent, macro: Macro, pin_count: int) -> List[FieldError]:
    errors: List[FieldError] = []
    if not sub.macro:
        errors.append(FieldError("macro", "Macro is required"))
        return errors
    pin_values: Dict[str, List[int]] = {}
    for leg, raw in sub.pins().items():
        try:
            pin_values[leg] = parse_pin_field(raw)
        except Exception as exc:  # pragma: no cover - UI level handles error detail
            errors.append(FieldError(f"pin_{leg.lower()}", str(exc)))
            continue
    pin_errors = validate_pins(
        [Row(index=sub.position, macro=sub.macro, pins=pin_values)],
        pin_count,
    )
    for err in pin_errors:
        errors.append(FieldError(err.column, err.message))
    errors.extend(validate_parameters(macro, sub.parameters))
    return errors


def validate_complex(complex_obj: Complex, catalog: Catalog) -> List[FieldError]:
    errors = []
    errors.extend(validate_part_number(complex_obj.part_number))
    errors.extend(validate_aliases(complex_obj.aliases))
    for sub in complex_obj.subcomponents:
        macro = catalog.get(sub.macro)
        if not macro:
            errors.append(FieldError("macro", f"Unknown macro '{sub.macro}'"))
            continue
        for err in validate_subcomponent(sub, macro, complex_obj.pin_count):
            errors.append(FieldError(f"row_{sub.position}", f"{err.field}: {err.message}"))
    return errors


def parameter_summary(macro: Macro, params: Dict[str, object], width: int = 40) -> Tuple[str, str]:
    """Return a short summary and the expanded JSON representation."""

    non_defaults = macro.non_default_summary(params)
    if not non_defaults:
        return ("(defaults)", json.dumps(non_defaults, separators=(",", ":")))
    parts = [f"{key}={value}" for key, value in non_defaults.items()]
    full = ", ".join(parts)
    if len(full) > width:
        short = full[: width - 1] + "…"
    else:
        short = full
    return short, json.dumps(non_defaults, indent=2, sort_keys=True)


__all__ = [
    "FieldError",
    "validate_part_number",
    "validate_aliases",
    "validate_parameters",
    "validate_subcomponent",
    "validate_complex",
    "parameter_summary",
]
