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

import logging
from logging.handlers import RotatingFileHandler
import tkinter as tk
from pathlib import Path
from tkinter import ttk
from typing import Dict, Optional, TYPE_CHECKING

from ..core.models import Catalog, Complex
from ..core.pins import parse_pin_field
from ..core.repo import Repository
from ..core.validation import parameter_summary
from complex_editor.config.loader import BridgeConfig
from ce_bridge_service.app import FocusBusyError
from ce_bridge_service.types import BridgeCreateResult
from .editor import ComplexEditor
from .bridge import BridgeManager, TkInvoker
from .widgets import ToastManager, apply_scaling, ensure_theme, get_user_data_dir

if TYPE_CHECKING:  # pragma: no cover - imported for typing only
    from complex_editor.core.app_context import AppContext

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

    def __init__(
        self,
        master: tk.Tk,
        repo: Repository,
        logger: logging.Logger,
        *,
        ctx=None,
        bridge_config: BridgeConfig | None = None,
    ) -> None:
        super().__init__(master)
        self.repo = repo
        self.catalog = repo.catalog
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
        self.ctx = ctx or getattr(repo, "context", None)
        self.invoker = TkInvoker(master)
        self.bridge_manager: BridgeManager | None = None
        self._bridge_wizard_active = False
        self._build_toolbar()
        self._build_body()
        self._load_complexes()
        if bridge_config and getattr(bridge_config, "enabled", False):
            self._start_bridge(bridge_config)

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
        ttk.Button(button_bar, text="New", command=self._new_complex).pack(side=tk.LEFT)
        ttk.Button(button_bar, text="Edit", command=self._open_selected).pack(side=tk.LEFT)

    # ------------------------------------------------------------------
    def _load_complexes(self, focus_identifier: Optional[str] = None) -> None:
        for item in self.tree.get_children():
            self.tree.delete(item)
        complexes = self.repo.list_complexes()
        self._all_complexes = complexes
        for complex_obj in complexes:
            aliases = ", ".join(complex_obj.aliases)
            self.tree.insert(
                "",
                tk.END,
                iid=complex_obj.identifier,
                values=(complex_obj.part_number, aliases, complex_obj.pin_count),
            )
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
            if hasattr(self.ctx, "focused_comp_id"):
                try:
                    self.ctx.focused_comp_id = None
                except Exception:
                    pass
            return
        identifier = selection[0]
        complex_obj = self.repo.get_complex(identifier)
        if complex_obj:
            self.summary.update_summary(complex_obj, self._stats_for_complex(complex_obj))
            if hasattr(self.ctx, "focused_comp_id") and identifier.isdigit():
                try:
                    self.ctx.focused_comp_id = int(identifier)
                except Exception:
                    pass

    def _open_selected(self) -> None:
        selection = self.tree.selection()
        if not selection:
            return
        identifier = selection[0]
        complex_obj = self.repo.get_complex(identifier)
        if not complex_obj:
            return
        self._open_complex(complex_obj)

    def _open_complex(self, complex_obj: Complex) -> ComplexEditor:
        identifier = complex_obj.identifier
        existing = self.open_editors.get(identifier)
        if existing and existing.winfo_exists():
            existing.deiconify()
            existing.lift()
            existing.focus_force()
            return existing
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
        if hasattr(self.ctx, "focused_comp_id") and identifier.isdigit():
            try:
                self.ctx.focused_comp_id = int(identifier)
            except Exception:
                pass
        return editor

    def _open_complex_by_identifier(self, identifier: str) -> ComplexEditor | None:
        complex_obj = self.repo.get_complex(identifier)
        if not complex_obj:
            return None
        return self._open_complex(complex_obj)

    def _new_complex(self) -> None:
        template = self.repo.new_complex()
        editor = self._open_complex(template)
        editor.title("New Complex")

    def _close_editor(self, identifier: str) -> None:
        editor = self.open_editors.pop(identifier, None)
        if editor:
            editor.destroy()

    def _handle_save(self, complex_obj: Complex) -> None:
        saved = self.repo.upsert_complex(complex_obj)
        self.logger.info("Saved complex %s", saved.part_number)
        self.toast.show(f"Saved '{saved.part_number}' successfully")
        self._load_complexes(focus_identifier=saved.identifier)
        self.summary.update_summary(saved, self._stats_for_complex(saved))
        if hasattr(self.ctx, "focused_comp_id"):
            try:
                if saved.identifier.isdigit():
                    self.ctx.focused_comp_id = int(saved.identifier)
                else:
                    self.ctx.focused_comp_id = None
            except Exception:
                pass

    def _summary_callback(self, complex_obj: Complex, stats: Dict[str, str]) -> None:
        selection = self.tree.selection()
        if selection and selection[0] == complex_obj.identifier:
            self.summary.update_summary(complex_obj, stats)

    # ------------------------------------------------------------------
    def _start_bridge(self, config: BridgeConfig) -> None:
        context = self.ctx or getattr(self.repo, "context", None)
        if context is None or not hasattr(context, "current_db_path"):
            self.logger.error("Bridge requested but application context missing")
            return
        state_provider = getattr(context, "bridge_state", None)
        if callable(state_provider):
            provider = state_provider
        else:
            provider = None
        self.bridge_manager = BridgeManager(
            invoker=self.invoker,
            get_mdb_path=lambda: context.current_db_path(),
            state_provider=provider,
            focus_handler=self._focus_complex_for_bridge,
        )
        started = self.bridge_manager.start(config, self._bridge_wizard_handler)
        if not started:
            self.logger.error(
                "Failed to start bridge server: %s",
                self.bridge_manager.last_error or "unknown error",
            )

    def _stop_bridge(self) -> None:
        if self.bridge_manager:
            self.bridge_manager.stop()
            self.bridge_manager = None

    # ------------------------------------------------------------------
    def _focus_complex_for_bridge(self, comp_id: int, mode: str) -> Dict[str, object]:
        if self._bridge_wizard_active:
            raise FocusBusyError("wizard busy")
        identifier = str(comp_id)
        complex_obj = self.repo.get_complex(identifier)
        if not complex_obj:
            raise KeyError(comp_id)
        self.master.deiconify()
        self.master.lift()
        try:
            self.master.focus_force()
        except Exception:
            pass
        self._load_complexes(focus_identifier=identifier)
        if mode.strip().lower() == "edit":
            self._open_complex(complex_obj)
        result: Dict[str, object] = {
            "pn": complex_obj.part_number,
            "focused_comp_id": comp_id,
            "wizard_open": bool(self._bridge_wizard_active),
        }
        return result

    def _bridge_wizard_handler(self, pn: str, aliases: Optional[list[str]]) -> BridgeCreateResult:
        if getattr(self.repo, "mode", "") != "db":
            return BridgeCreateResult(created=False, reason="database unavailable")
        if self._bridge_wizard_active:
            return BridgeCreateResult(created=False, reason="wizard busy")

        context = self.ctx or getattr(self.repo, "context", None)
        if context is None or not hasattr(context, "current_db_path"):
            return BridgeCreateResult(created=False, reason="context unavailable")

        def _run() -> BridgeCreateResult:
            self._bridge_wizard_active = True
            opener = getattr(context, "wizard_opened", None)
            closer = getattr(context, "wizard_closed", None)
            if callable(opener):
                try:
                    opener()
                except Exception:
                    pass
            template = self.repo.new_complex(
                part_number=str(pn or ""),
                aliases=list(aliases or []),
            )
            saved_payload: Dict[str, Complex] = {}

            def _capture(comp: Complex) -> None:
                saved_payload["complex"] = comp

            editor = ComplexEditor(
                parent=self.master,
                catalog=self.catalog,
                complex_obj=template,
                on_saved=_capture,
                summary_callback=lambda *_: None,
            )
            editor.title(f"New Complex {pn}" if pn else "New Complex")
            editor.transient(self.master)
            try:
                editor.grab_set()
            except Exception:
                pass
            editor.focus_force()
            editor.wait_window()

            saved_flag = "complex" in saved_payload
            try:
                if saved_flag:
                    try:
                        stored = self.repo.upsert_complex(saved_payload["complex"])
                    except Exception as exc:
                        self.logger.exception("Failed to persist wizard-created complex")
                        return BridgeCreateResult(created=False, reason=str(exc))
                    self._load_complexes(focus_identifier=stored.identifier)
                    db_path = str(context.current_db_path())
                    comp_id = stored.db_id or (int(stored.identifier) if stored.identifier.isdigit() else None)
                    if comp_id is None:
                        return BridgeCreateResult(created=False, reason="missing comp id")
                    return BridgeCreateResult(created=True, comp_id=int(comp_id), db_path=db_path)
                return BridgeCreateResult(created=False, reason="cancelled")
            finally:
                if callable(closer):
                    try:
                        closer(saved=saved_flag, had_changes=saved_flag)
                    except Exception:
                        pass
                self._bridge_wizard_active = False

        return self.invoker.invoke(_run)

    # ------------------------------------------------------------------
    def on_close(self) -> None:
        self._stop_bridge()
        self.master.destroy()


def main(
    buffer_path: Optional[Path] | None = None,
    mdb_path: Optional[Path] | None = None,
    app_context: "AppContext | None" = None,
    bridge_autostart: BridgeConfig | None = None,
    bridge_ui_mode: str | None = None,
) -> None:
    """Launch the Tkinter Complex Editor demo.

    Parameters
    ----------
    buffer_path:
        Optional path to the JSON buffer file used for persistence. When not
        provided the application stores data inside the user data directory.
    app_context:
        Existing :class:`complex_editor.core.app_context.AppContext` instance to
        reuse database handles opened by the bridge entry point. When omitted a
        fresh context is created by the repository itself.
    """

    root = tk.Tk()
    apply_scaling(root)
    ensure_theme(root)
    logger = _setup_logging()
    resolved_buffer = buffer_path.expanduser().resolve() if buffer_path else None
    resolved_mdb = mdb_path.expanduser().resolve() if mdb_path else None
    repo = Repository(buffer_path=resolved_buffer, mdb_path=resolved_mdb, context=app_context)
    window = MainWindow(
        root,
        repo,
        logger,
        ctx=app_context or repo.context,
        bridge_config=bridge_autostart,
    )
    if bridge_ui_mode:
        logger.info("Bridge UI mode: %s", bridge_ui_mode)
    root.title("Complex Editor Demo")
    root.minsize(960, 600)
    root.protocol("WM_DELETE_WINDOW", window.on_close)
    root.mainloop()


if __name__ == "__main__":
    main()
