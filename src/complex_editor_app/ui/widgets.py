"""Reusable widget utilities for the Complex Editor demo."""
from __future__ import annotations

import os
import platform
import tkinter as tk
from pathlib import Path
from tkinter import ttk
from typing import Optional

try:  # optional ttkbootstrap theme support
    import ttkbootstrap as tb
except Exception:  # pragma: no cover - optional dependency
    tb = None  # type: ignore


APP_NAME = "ComplexEditor"


def get_user_data_dir() -> Path:
    if platform.system() == "Windows":
        base = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
    elif platform.system() == "Darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))
    path = base / APP_NAME
    path.mkdir(parents=True, exist_ok=True)
    return path


def ensure_theme(root: tk.Tk) -> ttk.Style:
    """Attempt to apply ttkbootstrap, falling back to stock ttk styles."""

    if tb is not None:
        try:
            return tb.Style("flatly")
        except Exception:  # pragma: no cover - optional dependency
            return ttk.Style(root)

    style = ttk.Style(root)
    style.configure("TButton", padding=(8, 4))
    style.configure("Treeview", rowheight=26)
    style.map(
        "TButton",
        foreground=[("disabled", "#999")],
        relief=[("pressed", "sunken"), ("active", "flat")],
    )
    return style


class ToastManager:
    """Display transient notifications anchored to the main window."""

    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self._current: Optional[tk.Toplevel] = None

    def show(self, message: str, duration_ms: int = 2500) -> None:
        if self._current:
            self._current.destroy()
        window = tk.Toplevel(self.root)
        window.overrideredirect(True)
        window.attributes("-topmost", True)
        label = ttk.Label(window, text=message, padding=(12, 8))
        label.pack()
        window.update_idletasks()
        x = self.root.winfo_rootx() + (self.root.winfo_width() - window.winfo_width()) // 2
        y = self.root.winfo_rooty() + self.root.winfo_height() - window.winfo_height() - 40
        window.geometry(f"+{x}+{y}")
        self._current = window
        self.root.after(duration_ms, window.destroy)


def apply_scaling(root: tk.Tk) -> None:
    system = platform.system()
    factor = 1.25 if system == "Windows" else 1.0
    try:
        root.call("tk", "scaling", factor)
    except tk.TclError:  # pragma: no cover - defensive
        pass


__all__ = ["ToastManager", "ensure_theme", "get_user_data_dir", "apply_scaling"]
