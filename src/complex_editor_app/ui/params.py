"""Parameter editor dialog."""
from __future__ import annotations

import json
import tkinter as tk
from dataclasses import dataclass
from tkinter import ttk
from typing import Dict, Tuple

from ..core.models import Macro, MacroParameterSpec

ACCENT_BG = "#fff6cc"


@dataclass
class ParameterResult:
    delta: Dict[str, object]
    full: Dict[str, object]


class ParameterDialog(tk.Toplevel):
    """Schema driven parameter editor."""

    def __init__(self, parent: tk.Widget, macro: Macro, values: Dict[str, object]) -> None:
        super().__init__(parent)
        self.title(f"Parameters – {macro.name}")
        self.transient(parent)
        self.macro = macro
        self.style = ttk.Style(self)
        accent_options = {"fieldbackground": ACCENT_BG}
        self.style.configure("Changed.TEntry", **accent_options)
        self.style.configure("Changed.TSpinbox", **accent_options)
        self.style.configure("Changed.TCombobox", **accent_options)
        self.style.configure("Changed.TCheckbutton", background=ACCENT_BG)
        self.initial = dict(values)
        self.result: ParameterResult | None = None
        self.save_full = tk.BooleanVar(value=False)
        self._vars: Dict[str, tk.Variable] = {}
        self._widgets: Dict[str, tk.Widget] = {}
        self._base_styles: Dict[str, str] = {}
        self.protocol("WM_DELETE_WINDOW", self._cancel)

        body = ttk.Frame(self, padding=12)
        body.pack(fill=tk.BOTH, expand=True)

        self._build_fields(body)

        btn_bar = ttk.Frame(self)
        btn_bar.pack(fill=tk.X, padx=12, pady=12)
        restore = ttk.Button(btn_bar, text="Restore Defaults", command=self._restore_defaults)
        restore.pack(side=tk.LEFT)
        copy_btn = ttk.Button(btn_bar, text="Copy Params", command=self._copy)
        copy_btn.pack(side=tk.LEFT, padx=(8, 0))
        paste_btn = ttk.Button(btn_bar, text="Paste Params", command=self._paste)
        paste_btn.pack(side=tk.LEFT, padx=(8, 0))
        ttk.Checkbutton(btn_bar, text="Save full parameter set", variable=self.save_full).pack(side=tk.LEFT, padx=(16, 0))

        ttk.Button(btn_bar, text="Cancel", command=self._cancel).pack(side=tk.RIGHT)
        ttk.Button(btn_bar, text="OK", command=self._accept).pack(side=tk.RIGHT, padx=(0, 8))

        self.grab_set()
        self.resizable(True, True)
        self.update_idletasks()

    # ------------------------------------------------------------------
    def _build_fields(self, container: ttk.Frame) -> None:
        for row, (name, spec) in enumerate(self.macro.parameters.items()):
            label = ttk.Label(container, text=name)
            label.grid(row=row, column=0, sticky="w", pady=4)
            var = self._variable_for_spec(name, spec)
            widget = self._widget_for_spec(container, spec, var)
            widget.grid(row=row, column=1, sticky="ew", padx=(8, 0))
            container.columnconfigure(1, weight=1)
            self._vars[name] = var
            self._widgets[name] = widget
            self._base_styles[name] = widget.cget("style") or widget.winfo_class()
            self._update_highlight(name)
        self._refresh_dependencies()

    def _variable_for_spec(self, name: str, spec: MacroParameterSpec) -> tk.Variable:
        value = self.initial.get(name, spec.default)
        if spec.type == "int":
            var = tk.IntVar(value=int(value if value is not None else spec.default))
        elif spec.type == "float":
            var = tk.DoubleVar(value=float(value if value is not None else spec.default))
        elif spec.type == "bool":
            var = tk.BooleanVar(value=bool(value))
        else:
            var = tk.StringVar(value="" if value is None else value)
        var.trace_add("write", lambda *_: self._on_change(name))
        return var

    def _widget_for_spec(self, container: ttk.Frame, spec: MacroParameterSpec, var: tk.Variable) -> tk.Widget:
        if spec.type == "int":
            widget = ttk.Spinbox(container, from_=spec.minimum or 0, to=spec.maximum or 9999, textvariable=var, increment=spec.step or 1)
        elif spec.type == "float":
            widget = ttk.Spinbox(container, from_=spec.minimum or 0.0, to=spec.maximum or 9999.0, textvariable=var, increment=spec.step or 0.1)
        elif spec.type == "bool":
            widget = ttk.Checkbutton(container, variable=var, text=spec.help or "Enabled")
        elif spec.type == "enum":
            widget = ttk.Combobox(container, values=list(spec.choices or []), textvariable=var, state="readonly")
        else:
            widget = ttk.Entry(container, textvariable=var)
        widget.tooltip_text = spec.help  # type: ignore[attr-defined]
        return widget

    def _on_change(self, name: str) -> None:
        self._update_highlight(name)
        self._refresh_dependencies()

    def _refresh_dependencies(self) -> None:
        for name, spec in self.macro.parameters.items():
            widget = self._widgets[name]
            ok, message = True, None
            if spec.dependencies:
                for key, required in spec.dependencies.items():
                    current = self._value_from_var(self._vars.get(key))
                    if isinstance(required, (list, tuple, set)):
                        ok = current in required
                    else:
                        ok = current == required
                    if not ok:
                        message = f"Requires {key}={required}" if not isinstance(required, (list, tuple, set)) else f"Requires {key} in {required}"
                        break
            if ok:
                widget.state(["!disabled"])
            else:
                widget.state(["disabled"])
            if message:
                widget.tooltip_text = message  # type: ignore[attr-defined]
            else:
                widget.tooltip_text = spec.help  # type: ignore[attr-defined]

    def _update_highlight(self, name: str) -> None:
        widget = self._widgets.get(name)
        if not widget:
            return
        spec = self.macro.parameters[name]
        value = self._value_from_var(self._vars[name])
        default = spec.default
        highlight = value != default
        base_lookup = {
            ttk.Entry: "TEntry",
            ttk.Spinbox: "TSpinbox",
            ttk.Combobox: "TCombobox",
            ttk.Checkbutton: "TCheckbutton",
        }
        style_name = self._base_styles.get(name) or base_lookup.get(type(widget), "TEntry")
        highlight_map = {
            ttk.Entry: "Changed.TEntry",
            ttk.Spinbox: "Changed.TSpinbox",
            ttk.Combobox: "Changed.TCombobox",
            ttk.Checkbutton: "Changed.TCheckbutton",
        }
        for widget_type, highlight_style in highlight_map.items():
            if isinstance(widget, widget_type):
                widget.configure(style=highlight_style if highlight else style_name)
                break

    def _value_from_var(self, var: tk.Variable | None) -> object:
        if var is None:
            return None
        value = var.get()
        return value

    def _restore_defaults(self) -> None:
        for name, spec in self.macro.parameters.items():
            var = self._vars[name]
            default = spec.default
            if isinstance(var, tk.BooleanVar):
                var.set(bool(default))
            else:
                var.set(default)

    def _copy(self) -> None:
        values = {name: self._value_from_var(var) for name, var in self._vars.items()}
        self.clipboard_clear()
        self.clipboard_append(json.dumps(values, indent=2))

    def _paste(self) -> None:
        try:
            payload = json.loads(self.clipboard_get())
        except Exception:
            return
        for name, value in payload.items():
            if name not in self._vars:
                continue
            var = self._vars[name]
            if isinstance(var, tk.BooleanVar):
                var.set(bool(value))
            else:
                var.set(value)
        self._refresh_dependencies()

    def _accept(self) -> None:
        full = {name: self._value_from_var(var) for name, var in self._vars.items()}
        delta = {name: value for name, value in full.items() if value != self.macro.parameters[name].default}
        if self.save_full.get():
            delta = dict(full)
        self.result = ParameterResult(delta=delta, full=full)
        self.destroy()

    def _cancel(self) -> None:
        self.result = None
        self.destroy()

    def show(self) -> ParameterResult | None:
        self.wait_window(self)
        return self.result


__all__ = ["ParameterDialog", "ParameterResult"]
