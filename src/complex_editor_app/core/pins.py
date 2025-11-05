"""Parsing and validation utilities for pin assignments."""
from __future__ import annotations

from dataclasses import dataclass
import itertools
import re
from typing import Dict, Iterable, List, Sequence

NC_TOKENS = {"", "NC", "N/C", "N\\C", "-"}
TOKEN_SPLIT_RE = re.compile(r"[\s,]+")
RANGE_RE = re.compile(r"^(?P<start>\d+)-(?:\s*(?P<end>\d+))$")


class PinParseError(ValueError):
    """Raised when a pin field cannot be parsed."""


@dataclass(slots=True)
class Row:
    index: int
    macro: str
    pins: Dict[str, Sequence[int]]


@dataclass(slots=True)
class ValidationError:
    row_index: int
    column: str
    message: str


# ---------------------------------------------------------------------------
def parse_pin_field(text: str) -> List[int]:
    """Parse a pin entry returning concrete pin numbers.

    Parameters
    ----------
    text:
        Raw cell value supplied by the user.

    Returns
    -------
    list[int]
        Concrete pin numbers (1-based). ``[]`` indicates no connection.
    """

    if text is None:
        return []

    raw = text.strip()
    if not raw:
        return []

    upper = raw.upper()
    if upper in NC_TOKENS:
        return []

    pins: List[int] = []
    for token in TOKEN_SPLIT_RE.split(raw):
        token = token.strip()
        if not token:
            continue
        normalized = token.upper()
        if normalized in NC_TOKENS:
            continue
        range_match = RANGE_RE.match(token)
        if range_match:
            start = int(range_match.group("start"))
            end = int(range_match.group("end"))
            if end < start:
                raise PinParseError(f"Invalid range {token!r}: end must be >= start")
            pins.extend(range(start, end + 1))
            continue
        try:
            pins.append(int(token))
        except ValueError as exc:  # pragma: no cover - defensive
            raise PinParseError(f"Unrecognised token {token!r}") from exc
    return pins


# ---------------------------------------------------------------------------
def validate_pins(rows: Iterable[Row], pin_count: int) -> List[ValidationError]:
    """Validate the pin matrix for a complex.

    The function enforces that all pin numbers fall within ``1..pin_count`` and
    that the combined usage across rows does not produce duplicates.
    """

    errors: List[ValidationError] = []
    occupied: Dict[int, List[int]] = {}
    for row in rows:
        for column, values in row.pins.items():
            for pin in values:
                if pin < 1 or pin > pin_count:
                    errors.append(
                        ValidationError(
                            row_index=row.index,
                            column=column,
                            message=f"Pin {pin} outside 1..{pin_count}",
                        )
                    )
                occupied.setdefault(pin, []).append(row.index)
            if len(values) != len(set(values)):
                errors.append(
                    ValidationError(
                        row_index=row.index,
                        column=column,
                        message="Duplicate pin within row",
                    )
                )
    for pin, rows_using in occupied.items():
        if len(rows_using) > 1:
            rows_text = ", ".join(str(idx) for idx in rows_using)
            for row_index in rows_using:
                errors.append(
                    ValidationError(
                        row_index=row_index,
                        column="Pins",
                        message=f"Pin {pin} is reused by rows {rows_text}",
                    )
                )
    errors.sort(key=lambda err: (err.row_index, err.column))
    return errors


def flatten_pins(pin_map: Dict[str, Sequence[int]]) -> List[int]:
    """Return a sorted, de-duplicated list of all pins consumed by ``pin_map``."""

    merged = list(itertools.chain.from_iterable(pin_map.values()))
    return sorted(set(merged))


__all__ = [
    "PinParseError",
    "Row",
    "ValidationError",
    "parse_pin_field",
    "validate_pins",
    "flatten_pins",
]
