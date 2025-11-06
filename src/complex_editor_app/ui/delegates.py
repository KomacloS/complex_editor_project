"""Treeview editing delegates."""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import Callable, Iterable, List, Sequence


class MacroComboDelegate:
    """Combobox overlay used to edit macro cells."""

    def __init__(
        self,
        tree: ttk.Treeview,
        values_provider: Callable[[], Sequence[str]],
        commit: Callable[[str], None],
        cancel: Callable[[], None],
    ) -> None:
        self.tree = tree
        self.values_provider = values_provider
        self.commit = commit
        self.cancel = cancel
        self.editor: ttk.Combobox | None = None
        self._all_values: List[str] = []

    def begin(self, item_id: str, column: str, initial: str = "") -> None:
        bbox = self.tree.bbox(item_id, column)
        if not bbox:
            return
        x, y, width, height = bbox
        self._all_values = sorted(self.values_provider())
        self.editor = ttk.Combobox(
            self.tree,
            values=self._limit(self._all_values),
            state="normal",
        )
        self.editor.place(x=x, y=y, width=width, height=height)
        self.editor.focus_set()
        self.editor.insert(0, initial)
        self.editor.selection_range(0, tk.END)
        self.editor.bind("<KeyRelease>", self._on_keyrelease, add="+")
        self.editor.bind("<Return>", self._on_return, add="+")
        self.editor.bind("<Escape>", self._on_escape, add="+")
        self.editor.bind("<<ComboboxSelected>>", self._on_return, add="+")
        self.editor.after(10, lambda: self.editor.event_generate("<Down>"))
        self._resize_dropdown()

    # ------------------------------------------------------------------
    def _limit(self, values: Sequence[str]) -> Sequence[str]:
        return list(values[:20])

    def _on_keyrelease(self, _event: tk.Event) -> None:
        assert self.editor is not None
        typed = self.editor.get()
        filtered = [value for value in self._all_values if typed.lower() in value.lower()]
        self.editor.configure(values=self._limit(filtered))
        self._resize_dropdown()

    def _resize_dropdown(self) -> None:
        if not self.editor:
            return
        longest = max((len(v) for v in self.editor.cget("values")), default=0)
        width = max(240, min(600, longest * 9))
        self.editor.configure(width=width // 7)
        try:
            self.editor.tk.call(
                "ttk::combobox::PopdownWindow", self.editor, "f.l"
            ).configure(width=width)
        except Exception:
            pass

    def _on_return(self, _event: tk.Event) -> None:
        if not self.editor:
            return
        value = self.editor.get()
        self.close()
        self.commit(value)

    def _on_escape(self, _event: tk.Event) -> None:
        self.close()
        self.cancel()

    def close(self) -> None:
        if self.editor:
            self.editor.destroy()
        self.editor = None


__all__ = ["MacroComboDelegate"]
