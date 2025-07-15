"""Bootstrap helpers for working from a repo checkout."""

from __future__ import annotations

from pathlib import Path
import importlib.util
import logging
import sys


def add_repo_src_to_syspath() -> None:
    """Prepend ``<repo-root>/src`` to ``sys.path`` if needed."""

    if importlib.util.find_spec("complex_editor") is not None:
        return

    src_root = Path(__file__).resolve().parents[2] / "src"
    if src_root.exists() and str(src_root) not in sys.path:
        sys.path.insert(0, str(src_root))
        logging.getLogger(__name__).info("Added %s to sys.path", src_root)

__all__ = ["add_repo_src_to_syspath"]
