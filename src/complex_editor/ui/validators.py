from __future__ import annotations

"""Validation helpers shared between GUI components."""

from typing import Iterable, Sequence, Tuple

def validate_pins(pins: Iterable[int], max_pin: int) -> Tuple[bool, str]:
    """
    Accept 0/None as 'unset'. Validate range only for >0 and check in-row duplicates
    only among >0 values.
    """
    numbers = [p for p in pins if p is not None and p > 0]
    for p in numbers:
        if p > max_pin:
            return False, f"pin {p} out of range"
    if len(numbers) != len(set(numbers)):
        return False, "duplicate pins"
    return True, ""


def validate_pin_table(
    rows: Sequence[Sequence[int]],
    max_pin: int,
    *,
    enforce_unique_across_rows: bool = False,  # <— NEW: default allows reuse
) -> Tuple[bool, str]:
    """
    Validate a full table of pin assignments.

    - Always validates range and in-row duplicates.
    - Optionally enforces cross-row uniqueness when `enforce_unique_across_rows=True`.
    """
    used = set()
    for r in rows:
        ok, msg = validate_pins(r, max_pin)
        if not ok:
            return False, msg
        if enforce_unique_across_rows:
            for p in (x for x in r if x is not None and x > 0):
                if p in used:
                    return False, f"pin {p} reused"
                used.add(p)
    return True, ""
