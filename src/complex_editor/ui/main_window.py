"""Compatibility wrapper that exposes the Tkinter editor as the primary UI."""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from complex_editor_app.ui.main import main as run_tk_main


def run_gui(
    *,
    ctx: object | None = None,
    mdb_file: Optional[Path] = None,
    buffer_path: Optional[Path] = None,
    **_: object,
) -> None:
    """Launch the Tkinter Complex Editor UI.

    Parameters mirror the legacy PyQt entry point so existing launch scripts can
    continue to import :func:`run_gui`. The ``ctx`` object is accepted for
    signature compatibility but ignored because the Tkinter frontend constructs
    its own repository context.
    """

    run_tk_main(buffer_path=buffer_path, mdb_path=mdb_file, app_context=ctx)
