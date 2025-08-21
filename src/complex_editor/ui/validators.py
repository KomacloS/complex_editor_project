from __future__ import annotations

"""Validation helpers shared between GUI components."""

from typing import Iterable, Sequence, Tuple


def validate_pins(pins: Iterable[int], max_pin: int) -> Tuple[bool, str]:
    """Validate *pins* against range and duplicate rules.

    Parameters
    ----------
    pins:
        Iterable of pin numbers; ``None`` values are ignored.
    max_pin:
        Highest allowed pin number.
    Returns
    -------
    tuple
        ``(is_valid, message)`` where ``message`` describes the first error.
    """

    numbers = [p for p in pins if p is not None]
    for p in numbers:
        if p < 1 or p > max_pin:
            return False, f"pin {p} out of range"
    if len(numbers) != len(set(numbers)):
        return False, "duplicate pins"
    return True, ""


def validate_pin_table(rows: Sequence[Sequence[int]], max_pin: int) -> Tuple[bool, str]:
    """Validate a full table of pin assignments.

    The legacy ``NewComplexWizard`` rejected any reuse of a physical pad across
    sub-components.  This helper mirrors those rules so both the wizard and the
    new :class:`~complex_editor.ui.complex_editor.ComplexEditor` behave
    identically.

    Parameters
    ----------
    rows:
        Iterable over pin rows ``[A, B, C, D]``.
    max_pin:
        Upper bound for allowed pin numbers.

    Returns
    -------
    tuple
        ``(is_valid, message)`` describing the first encountered violation.
    """

    used = set()
    for r in rows:
        ok, msg = validate_pins(r, max_pin)
        if not ok:
            return False, msg
        for p in [x for x in r if x is not None and x > 0]:
            if p in used:
                return False, f"pin {p} reused"
            used.add(p)
    return True, ""
