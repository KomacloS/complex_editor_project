"""Helper functions for buffer-mode UI operations."""
from __future__ import annotations

from typing import Mapping


def format_pins(pin_items: Mapping[str, str]) -> str:
    """Return a user-facing string for the Pins column.

    Pins ``A`` through ``H`` are shown in that order if present.  The special
    ``S`` pin carrying PinS XML is always ignored.  Any additional pins are
    appended alphabetically afterwards.  Values are formatted as ``PIN=PAD`` and
    joined by commas.
    """

    ordered = [k for k in "ABCDEFGH" if k in pin_items]
    ordered += [k for k in sorted(pin_items.keys()) if k not in "ABCDEFGH" and k != "S"]
    return ", ".join(f"{k}={pin_items[k]}" for k in ordered)
