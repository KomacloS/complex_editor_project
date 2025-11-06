"""Tkinter-based Complex Editor UI shims replacing the legacy PyQt widgets."""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from .main_window import run_gui

__all__ = ["run_gui", "launch"]


def launch(mdb_file: Optional[Path] = None, buffer_path: Optional[Path] = None) -> None:
    """Backward-compatible entry point for the deprecated PyQt launcher."""

    run_gui(mdb_file=mdb_file, buffer_path=buffer_path)
