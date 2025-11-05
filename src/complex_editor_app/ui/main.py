"""Minimal runnable Complex Editor demo.

How to run
==========
1. Install dependencies: ``pip install -r requirements.txt`` (optional; the demo
   relies only on the standard library unless ttkbootstrap/ttkwidgets are
   available).
2. Launch the UI with ``python -m complex_editor_app.ui.main``.

The module wires together the repository, macro catalog, and Tkinter widgets to
illustrate the editor, parameter dialog, and inline validation improvements.
"""
from __future__ import annotations

import json
import logging
from logging.handlers import RotatingFileHandler
import shutil
import tkinter as tk
from pathlib import Path
from tkinter import ttk
from typing import Dict, Optional

from ..core.models import Catalog, Complex, build_sample_catalog
from ..core.pins import parse_pin_field
from ..core.repo import Repository
from ..core.validation import parameter_summary
from .editor import ComplexEditor
from .widgets import ToastManager, apply_scaling, ensure_theme, get_user_data_dir

DATA_FILE = "buffer.json"
SAMPLE_DATA = Path(__file__).resolve().parent.parent / "data" / "sample_buffer.json"


def _setup_logging() -> logging.Logger:
    log_dir = get_user_data_dir()
    log_path = log_dir / "complex_editor.log"
    logger = logging.getLogger("complex_editor_app")
    if logger.handlers:
        return logger
    logger.setLevel(logging.INFO)
    handler = RotatingFileHandler(log_path, maxBytes=1_000_000, backupCount=5)
    formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")
    handler.setFormatter(formatter)
    logger.addHandler(handler)
    return logger


class SummaryPane(ttk.Frame):
    """Right-hand summary displaying per-row stats."""

    def __init__(self, parent: tk.Widget, catalog: Catalog) -> None:
        super().__init__(parent, padding=12)
        self.catalog = catalog
        self.header = ttk.Label(self, text="Select a complex to view details", anchor="w")
        self.header.pack(fill=tk.X)
        columns = ("position", "macro", "pins", "params")
        self.tree = ttk.Treeview(self, columns=columns, show="headings", height=10)
        self.tree.heading("position", text="#")
        self.tree.heading("macro", text="Macro")
        self.tree.heading("pins", text="Pins (A-D)")
        self.tree.heading("params", text="Changed Params")
        self.tree.column("position", width=40, anchor=tk.CENTER)
        self.tree.column("macro", width=160, anchor=tk.W)
        self.tree.column("pins", width=160, anchor=tk.W)
        self.tree.column("params", width=220, anchor=tk.W)
        self.tree.pack(fill=tk.BOTH, expand=True, pady=(8, 0))

    def update_summary(self, complex_obj: Optional[Complex], stats: Dict[str, str]) -> None:
        for item in self.tree.get_children():
            self.tree.delete(item)
        if not complex_obj:
            self.header.config(text="Select a complex to view details")
            return
        summary_text = " | ".join(f"{key}: {value}" for key, value in stats.items())
        self.header.config(text=summary_text)
        for sub in complex_obj.subcomponents:
            pins = "/".join(filter(None, [sub.pin_a, sub.pin_b, sub.pin_c, sub.pin_d])) or "(none)"
            macro = sub.macro or "(unassigned)"
            params = ""
            macro_obj = self.catalog.get(sub.macro) if sub.macro else None
            if macro_obj:
                params, _ = parameter_summary(macro_obj, sub.parameters)
            self.tree.insert("", tk.END, values=(sub.position, macro, pins, params))


class MainWindow(ttk.Frame):
    """Host the main list of complexes and manage editor dialogs."""

    def __init__(self, master: tk.Tk, repo: Repository, catalog: Catalog, logger: logging.Logger) -> None:
        super().__init__(master)
        self.repo = repo
        self.catalog = catalog
        self.logger = logger
        self.toast = ToastManager(master)
        self.pack(fill=tk.BOTH, expand=True)
        self.open_editors: Dict[str, ComplexEditor] = {}
        self.filter_job: Optional[str] = None
        self.filter_vars: Dict[str, tk.StringVar] = {
            "pn": tk.StringVar(),
            "alias": tk.StringVar(),
            "macro": tk.StringVar(),
        }
        self._build_toolbar()
        self._build_body()
        self._load_complexes()

    # ------------------------------------------------------------------
    def _build_toolbar(self) -> None:
        bar = ttk.Frame(self, padding=(12, 8))
        bar.pack(fill=tk.X)
        ttk.Label(bar, text="Filter PN").pack(side=tk.LEFT)
        entry_pn = ttk.Entry(bar, textvariable=self.filter_vars["pn"], width=20)
        entry_pn.pack(side=tk.LEFT, padx=(4, 12))
        ttk.Label(bar, text="Alias").pack(side=tk.LEFT)
        entry_alias = ttk.Entry(bar, textvariable=self.filter_vars["alias"], width=16)
        entry_alias.pack(side=tk.LEFT, padx=(4, 12))
        ttk.Label(bar, text="Macro contains").pack(side=tk.LEFT)
        entry_macro = ttk.Entry(bar, textvariable=self.filter_vars["macro"], width=16)
        entry_macro.pack(side=tk.LEFT, padx=(4, 12))
        self.filter_vars["pn"].trace_add("write", lambda *_: self._schedule_filter())
        self.filter_vars["alias"].trace_add("write", lambda *_: self._schedule_filter())
        self.filter_vars["macro"].trace_add("write", lambda *_: self._schedule_filter())

    def _build_body(self) -> None:
        paned = ttk.PanedWindow(self, orient=tk.HORIZONTAL)
        paned.pack(fill=tk.BOTH, expand=True)
        list_frame = ttk.Frame(paned, padding=12)
        summary_frame = SummaryPane(paned, self.catalog)
        paned.add(list_frame, weight=2)
        paned.add(summary_frame, weight=3)
        self.summary = summary_frame

        columns = ("part_number", "aliases", "pin_count")
        self.tree = ttk.Treeview(list_frame, columns=columns, show="headings")
        self.tree.heading("part_number", text="Part Number")
        self.tree.heading("aliases", text="Aliases")
        self.tree.heading("pin_count", text="Pins")
        self.tree.column("part_number", width=160, anchor=tk.W)
        self.tree.column("aliases", width=180, anchor=tk.W)
        self.tree.column("pin_count", width=60, anchor=tk.E)
        self.tree.pack(fill=tk.BOTH, expand=True)
        self.tree.bind("<Double-1>", lambda _e: self._open_selected())
        self.tree.bind("<Return>", lambda _e: self._open_selected())
        self.tree.bind("<<TreeviewSelect>>", lambda _e: self._update_summary_from_selection())

        button_bar = ttk.Frame(list_frame)
        button_bar.pack(fill=tk.X, pady=(8, 0))
        ttk.Button(button_bar, text="Edit", command=self._open_selected).pack(side=tk.LEFT)

    # ------------------------------------------------------------------
    def _load_complexes(self, focus_identifier: Optional[str] = None) -> None:
        for item in self.tree.get_children():
            self.tree.delete(item)
        complexes = self.repo.list_complexes()
        self._all_complexes = complexes
        for complex_obj in complexes:
            aliases = ", ".join(complex_obj.aliases)
            self.tree.insert("", tk.END, iid=complex_obj.identifier, values=(complex_obj.part_number, aliases, complex_obj.pin_count))
        target_id = focus_identifier
        if target_id and target_id in self.tree.get_children():
            self.tree.selection_set(target_id)
            self.tree.focus(target_id)
            complex_obj = self.repo.get_complex(target_id)
            if complex_obj:
                self.summary.update_summary(complex_obj, self._stats_for_complex(complex_obj))
        elif complexes:
            first = complexes[0]
            self.tree.selection_set(first.identifier)
            self.tree.focus(first.identifier)
            self.summary.update_summary(first, self._stats_for_complex(first))
        self._apply_filters()

    def _schedule_filter(self) -> None:
        if self.filter_job:
            self.after_cancel(self.filter_job)
        self.filter_job = self.after(300, self._apply_filters)

    def _apply_filters(self) -> None:
        self.filter_job = None
        pn_filter = self.filter_vars["pn"].get().strip().lower()
        alias_filter = self.filter_vars["alias"].get().strip().lower()
        macro_filter = self.filter_vars["macro"].get().strip().lower()
        previous = self.tree.selection()
        for item in self.tree.get_children():
            self.tree.delete(item)
        for complex_obj in self._all_complexes:
            if pn_filter and pn_filter not in complex_obj.part_number.lower():
                continue
            if alias_filter and not any(alias_filter in alias.lower() for alias in complex_obj.aliases):
                continue
            if macro_filter:
                if not any(macro_filter in sub.macro.lower() for sub in complex_obj.subcomponents):
                    continue
            aliases = ", ".join(complex_obj.aliases)
            self.tree.insert("", tk.END, iid=complex_obj.identifier, values=(complex_obj.part_number, aliases, complex_obj.pin_count))
        if previous:
            for identifier in previous:
                if identifier in self.tree.get_children():
                    self.tree.selection_set(identifier)
                    self.tree.focus(identifier)
                    break
        self._update_summary_from_selection()

    def _stats_for_complex(self, complex_obj: Complex) -> Dict[str, str]:
        pins_used = 0
        for sub in complex_obj.subcomponents:
            for value in (sub.pin_a, sub.pin_b, sub.pin_c, sub.pin_d):
                try:
                    pins_used += len(parse_pin_field(value))
                except Exception:
                    pass
        pins_free = max(0, complex_obj.pin_count - pins_used)
        return {
            "Pin Count": str(complex_obj.pin_count),
            "Pins Used": str(pins_used),
            "Pins Free": str(pins_free),
            "Rows": str(len(complex_obj.subcomponents)),
            "Errors": "0",
        }

    def _update_summary_from_selection(self) -> None:
        selection = self.tree.selection()
        if not selection:
            self.summary.update_summary(None, {})
            return
        identifier = selection[0]
        complex_obj = self.repo.get_complex(identifier)
        if complex_obj:
            self.summary.update_summary(complex_obj, self._stats_for_complex(complex_obj))

    def _open_selected(self) -> None:
        selection = self.tree.selection()
        if not selection:
            return
        identifier = selection[0]
        complex_obj = self.repo.get_complex(identifier)
        if not complex_obj:
            return
        if identifier in self.open_editors:
            editor = self.open_editors[identifier]
            editor.deiconify()
            editor.lift()
            editor.focus_force()
            return
        editor = ComplexEditor(
            parent=self.master,
            catalog=self.catalog,
            complex_obj=complex_obj,
            on_saved=self._handle_save,
            summary_callback=self._summary_callback,
        )
        self.open_editors[identifier] = editor
        editor.protocol("WM_DELETE_WINDOW", lambda ident=identifier: self._close_editor(ident))
        editor.bind("<Destroy>", lambda _e, ident=identifier: self.open_editors.pop(ident, None), add="+")
        self.logger.info("Opened editor for %s", complex_obj.part_number)

    def _close_editor(self, identifier: str) -> None:
        editor = self.open_editors.pop(identifier, None)
        if editor:
            editor.destroy()

    def _handle_save(self, complex_obj: Complex) -> None:
        self.repo.upsert_complex(complex_obj)
        self.logger.info("Saved complex %s", complex_obj.part_number)
        self.toast.show(f"Saved '{complex_obj.part_number}' successfully")
        self._load_complexes(focus_identifier=complex_obj.identifier)
        self.summary.update_summary(complex_obj, self._stats_for_complex(complex_obj))

    def _summary_callback(self, complex_obj: Complex, stats: Dict[str, str]) -> None:
        selection = self.tree.selection()
        if selection and selection[0] == complex_obj.identifier:
            self.summary.update_summary(complex_obj, stats)


def ensure_sample_data(path: Path) -> None:
    if path.exists():
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    if SAMPLE_DATA.exists():
        shutil.copyfile(SAMPLE_DATA, path)
    else:
        path.write_text(json.dumps({"complexes": []}, indent=2), encoding="utf-8")


def main() -> None:
    root = tk.Tk()
    apply_scaling(root)
    ensure_theme(root)
    logger = _setup_logging()
    data_path = get_user_data_dir() / DATA_FILE
    ensure_sample_data(data_path)
    catalog = build_sample_catalog()
    repo = Repository(data_path, catalog)
    MainWindow(root, repo, catalog, logger)
    root.title("Complex Editor Demo")
    root.minsize(960, 600)
    root.mainloop()


if __name__ == "__main__":
    main()
