from __future__ import annotations

"""Helpers for reading and writing the GUI JSON buffer."""

from pathlib import Path
from typing import Any, List
import json


def load_buffer(path: Path) -> List[dict]:
    """Load ``path`` and return the list of complexes contained within."""

    p = Path(path)
    with p.open("r", encoding="utf-8") as f:
        data = json.load(f)
    assert isinstance(data, list)
    return data  # type: ignore[return-value]


def save_buffer(path: Path, complexes: List[dict]) -> None:
    """Write *complexes* to ``path`` in JSON format."""

    p = Path(path)
    with p.open("w", encoding="utf-8") as f:
        json.dump(complexes, f, ensure_ascii=False, indent=2)
