from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass(slots=True)
class BridgeCreateResult:
    """Outcome of a bridge-initiated complex creation."""

    created: bool
    comp_id: Optional[int] = None
    db_path: Optional[str] = None
    reason: Optional[str] = None


__all__ = ["BridgeCreateResult"]
