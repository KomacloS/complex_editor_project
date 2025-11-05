"""Tooltip helpers used throughout the Tkinter widgets."""
from __future__ import annotations

import tkinter as tk
from dataclasses import dataclass
from typing import Optional


@dataclass
class Tooltip:
    widget: tk.Widget
    text: str
    _window: Optional[tk.Toplevel] = None

    def show(self, event: Optional[tk.Event] = None) -> None:
        if not self.text:
            return
        if self._window:
            return
        self._window = tk.Toplevel(self.widget)
        self._window.wm_overrideredirect(True)
        self._window.wm_geometry("+%d+%d" % (event.x_root + 8 if event else 0, event.y_root + 8 if event else 0))
        label = tk.Label(
            self._window,
            text=self.text,
            background="#ffffe0",
            relief=tk.SOLID,
            borderwidth=1,
            justify=tk.LEFT,
            padx=6,
            pady=4,
        )
        label.pack(ipadx=1)

    def hide(self, _event: Optional[tk.Event] = None) -> None:
        if self._window:
            self._window.destroy()
            self._window = None


class TooltipManager:
    """Manage a set of tooltips bound to widgets."""

    def __init__(self) -> None:
        self._tooltips: dict[int, Tooltip] = {}

    def bind(self, widget: tk.Widget, text: str) -> None:
        tooltip = Tooltip(widget=widget, text=text)
        self._tooltips[id(widget)] = tooltip
        widget.bind("<Enter>", tooltip.show, add="+")
        widget.bind("<Leave>", tooltip.hide, add="+")

    def unbind(self, widget: tk.Widget) -> None:
        tooltip = self._tooltips.pop(id(widget), None)
        if not tooltip:
            return
        widget.unbind("<Enter>", tooltip.show)
        widget.unbind("<Leave>", tooltip.hide)
        tooltip.hide()


__all__ = ["Tooltip", "TooltipManager"]
