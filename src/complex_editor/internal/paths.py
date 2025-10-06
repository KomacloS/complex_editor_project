"""Helpers for resolving runtime paths inside packaged builds."""

from __future__ import annotations

import sys
from pathlib import Path


def get_app_root() -> Path:
    """Return the directory that should be treated as the application root."""
    if getattr(sys, "frozen", False):  # PyInstaller / frozen executables
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[3]


def get_internal_root() -> Path:
    """Return the folder that contains the bundled runtime payload."""
    app_root = get_app_root()

    if app_root.name.lower() == "internal":
        return app_root

    internal_dir = app_root / "internal"
    if internal_dir.exists():
        return internal_dir

    repo_internal = Path(__file__).resolve().parents[3] / "internal"
    if repo_internal.exists():
        return repo_internal

    return app_root


__all__ = ["get_app_root", "get_internal_root"]
