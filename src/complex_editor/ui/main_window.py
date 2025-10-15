﻿from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

from PyQt6 import QtCore, QtWidgets

from ..config.loader import BridgeConfig
from ..core.app_context import AppContext
from ..domain import ComplexDevice, MacroDef, MacroInstance, SubComponent
from ..db.mdb_api import MDB, SubComponent as DbSub, ComplexDevice as DbComplex
from ..db import schema_introspect
from ..param_spec import ALLOWED_PARAMS
from ..util.macro_xml_translator import params_to_xml, xml_to_params_tolerant
from ..util.rules_loader import get_learned_rules
from .adapters import EditorComplex, EditorMacro
from .bridge_controller import BridgeController, QtInvoker
from .buffer_loader import load_editor_complexes_from_buffer
from .buffer_persistence import load_buffer, save_buffer
from .complex_editor import ComplexEditor
from .new_complex_wizard import NewComplexWizard
from .settings_dialog import IntegrationSettingsDialog

from ce_bridge_service.types import BridgeCreateResult
from ce_bridge_service.app import FocusBusyError


class MainWindow(QtWidgets.QMainWindow):
    """Main window showing complexes from the MDB or a JSON buffer."""

    def __init__(
        self,
        mdb_path: Optional[Path] = None,
        parent: Any | None = None,
        buffer_path: Optional[Path] = None,
        ctx: AppContext | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Complex View")
        self.ctx = ctx or AppContext()
        self._bridge_invoker = QtInvoker()
        self._bridge_controller = BridgeController(
            get_mdb_path=lambda: self.ctx.current_db_path(),
            invoker=self._bridge_invoker,
            state_provider=self.ctx.bridge_state,
            open_complex=lambda comp_id, mode: self.focus_complex(comp_id, mode=mode),
        )
        self.db: Optional[MDB] = None
        self._buffer_complexes: List[EditorComplex] | None = None
        self._buffer_raw: List[dict] | None = None
        self._buffer_path: Path | None = None
        self._active_wizard: QtWidgets.QDialog | None = None
        self._active_editor: ComplexEditor | None = None
        self._active_editor_id: int | None = None

        if buffer_path is not None and Path(buffer_path).exists():
            self._buffer_path = Path(buffer_path)
            self._buffer_raw = load_buffer(self._buffer_path)
            self._buffer_complexes = load_editor_complexes_from_buffer(buffer_path)
        else:
            target_path = Path(mdb_path) if mdb_path is not None else self.ctx.current_db_path()
            self.db = self.ctx.open_main_db(target_path, create_if_missing=True)

        # cache of {IDFunction -> Name}
        self._func_map: Dict[int, str] = {}

        # left list of complexes with per-column search filters
        self.list = QtWidgets.QTableWidget(0, 3)
        self.list.setHorizontalHeaderLabels(["ID", "Name", "#Subs"])
        self.list.setSelectionBehavior(
            QtWidgets.QAbstractItemView.SelectionBehavior.SelectRows
        )
        self.list.setEditTriggers(
            QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers
        )
        self.list.itemSelectionChanged.connect(self._on_selected)
        self.list.doubleClicked.connect(self._on_edit)

        self._filters: List[QtWidgets.QLineEdit] = []
        filter_bar = QtWidgets.QHBoxLayout()
        for i in range(3):
            edit = QtWidgets.QLineEdit()
            header = self.list.horizontalHeaderItem(i).text()
            edit.setPlaceholderText(header)
            edit.textChanged.connect(self._apply_filters)
            self._filters.append(edit)
            filter_bar.addWidget(edit)
        filter_bar.addStretch()

        # right table with sub components (summary view)
        self.sub_table = QtWidgets.QTableWidget(0, 0)

        new_btn = QtWidgets.QPushButton("New Complex")
        new_btn.clicked.connect(self._new_complex)
        edit_btn = QtWidgets.QPushButton("Edit")
        edit_btn.clicked.connect(self._on_edit)
        del_btn = QtWidgets.QPushButton("Delete")
        del_btn.clicked.connect(self._delete_selected)

        if self._buffer_complexes is not None:
            # buffer mode is read-only
            new_btn.setEnabled(False)
            new_btn.setToolTip("Disabled in buffer mode")
            del_btn.setEnabled(False)

        toolbar = QtWidgets.QHBoxLayout()
        toolbar.addWidget(new_btn)
        toolbar.addWidget(edit_btn)
        toolbar.addWidget(del_btn)
        toolbar.addStretch()

        left = QtWidgets.QVBoxLayout()
        left.addLayout(toolbar)
        left.addLayout(filter_bar)
        left.addWidget(self.list)

        container = QtWidgets.QWidget()
        layout = QtWidgets.QHBoxLayout(container)
        layout.addLayout(left)
        layout.addWidget(self.sub_table)
        self.setCentralWidget(container)

        self._init_menu()
        self._refresh_list()
        self._apply_bridge_config()
        self._update_window_title()

    # ------------------------------------------------------------------ helpers
    def _ensure_func_map(self) -> None:
        """Populate {IDFunction -> Name} once (or refresh if empty)."""
        if not self._func_map:
            try:
                self._func_map = {int(fid): str(name) for fid, name in self.db.list_functions()}
            except Exception:
                self._func_map = {}

    def _func_name(self, id_function: int) -> str:
        self._ensure_func_map()
        return self._func_map.get(int(id_function), f"Function {id_function}")

    def _macro_id_from_name(self, name: str) -> Optional[int]:
        self._ensure_func_map()
        for fid, fname in self._func_map.items():
            if fname.lower() == str(name).lower():
                return fid
        return None

    def _pin_normalizer(self, pin_map: Dict[str, str]) -> Dict[str, str]:
        result: Dict[str, str] = {}
        for k, v in pin_map.items():
            key = str(k)
            if key in {"PinS", "S"}:
                continue
            if not key.startswith("Pin"):
                key = "Pin" + key.strip().upper()
            result[key] = str(v)
        return result

    def _persist_editor_device(self, updated_ui_dev, comp_id) -> int | None:
        """
        Persist ComplexDevice to MAIN_DB.mdb via mdb_api with strict typing.

        Fixes 22018 by ensuring detCompDesc numeric fields (Value, IDUnit, TolP, TolN, ForceBits)
        are always numbers, pins A..H are ints (0 for NC), and PinS is a TEXT string.

        Returns
        -------
        int | None
            The database ID of the persisted complex.
        """

        # ---------- helpers ----------
        def _as_int(v, default=0):
            try:
                if v is None or v == "":
                    return int(default)
                if isinstance(v, bool):
                    return int(bool(v))
                return int(v)
            except Exception:
                return int(default)

        def _as_int_or_none(v):
            if v is None or v == "":
                return None
            return _as_int(v)

        def _pin_from_list(lst, idx):
            try:
                return _as_int(lst[idx], 0)
            except Exception:
                return 0

        def _params_xml_text(macro_name: str, params: dict | None) -> str:
            # Prefer the project serializer, fall back to minimal XML
            try:
                from ..util.macro_xml_translator import params_to_xml  # type: ignore
                xml = params_to_xml({macro_name: (params or {})}, encoding="utf-16")
                return xml.decode("utf-16") if isinstance(xml, (bytes, bytearray)) else str(xml)
            except Exception:
                pass
            header = '<?xml version="1.0" encoding="utf-16"?>'
            if not params:
                return (
                    f"{header}\n"
                    '<R xmlns:xsd="http://www.w3.org/2001/XMLSchema" '
                    'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">\n'
                    "  <Macros/>\n"
                    "</R>"
                )
            import html
            esc = lambda x: html.escape(str(x), quote=True)
            lines = [
                header,
                '<R xmlns:xsd="http://www.w3.org/2001/XMLSchema" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">',
                "  <Macros>",
                f'    <Macro Name="{esc(macro_name)}">',
            ]
            for k, v in (params or {}).items():
                lines.append(f'      <Param Value="{esc(v)}" Name="{esc(k)}" />')
            lines += ["    </Macro>", "  </Macros>", "</R>"]
            return "\n".join(lines)

        # ---------- build DB-side dataclasses ----------
        from ..db.mdb_api import SubComponent as DbSub, ComplexDevice as DbComplex  # type: ignore

        comp_id_i = _as_int_or_none(comp_id)

        subs = []
        for sc in updated_ui_dev.subcomponents:
            fid = self._macro_id_from_name(sc.macro.name)
            if fid is None:
                raise ValueError(f"Unknown macro/function '{sc.macro.name}' (no IDFunction).")
            fid_i = _as_int(fid)

            pins_list = getattr(sc, "pins", []) or []
            pin_vals = {
                "A": _pin_from_list(pins_list, 0),
                "B": _pin_from_list(pins_list, 1),
                "C": _pin_from_list(pins_list, 2),
                "D": _pin_from_list(pins_list, 3),
                "E": _pin_from_list(pins_list, 4),
                "F": _pin_from_list(pins_list, 5),
                "G": _pin_from_list(pins_list, 6),
                "H": _pin_from_list(pins_list, 7),
            }
            pin_s_text = _params_xml_text(sc.macro.name, getattr(sc.macro, "params", {}))

            # >>> Critical: normalize numeric fields <<<
            # Match detCompDesc.csv typical defaults seen in your MDB:
            # Value: 0.0 (DOUBLE), IDUnit: 1 (LONG), TolP: 0.0, TolN: 0.0, ForceBits: 0
            value_num     = float(getattr(sc.macro, "value", 0.0) or 0.0)
            id_unit_num   = _as_int(getattr(sc.macro, "id_unit", 1), 1)
            tol_p_num     = float(getattr(sc.macro, "tol_p", 0.0) or 0.0)
            tol_n_num     = float(getattr(sc.macro, "tol_n", 0.0) or 0.0)
            force_bits_num= _as_int(getattr(sc.macro, "force_bits", 0), 0)

            # Build SubComponent compatible with mdb_api.SubComponent._flatten()
            try:
                sub = DbSub(
                    id_sub_component=None,
                    id_function=fid_i,
                    value=value_num,
                    id_unit=id_unit_num,
                    tol_p=tol_p_num,
                    tol_n=tol_n_num,
                    force_bits=force_bits_num,
                    pins={**pin_vals, "S": pin_s_text or ""},   # TEXT PinS
                )
            except TypeError:
                # Fallback for explicit-field dataclass variants
                sub = DbSub(
                    id_sub_component=None,
                    id_function=fid_i,
                    value=value_num,
                    id_unit=id_unit_num,
                    tol_p=tol_p_num,
                    tol_n=tol_n_num,
                    force_bits=force_bits_num,
                    pin_a=pin_vals["A"], pin_b=pin_vals["B"],
                    pin_c=pin_vals["C"], pin_d=pin_vals["D"],
                    pin_e=pin_vals["E"], pin_f=pin_vals["F"],
                    pin_g=pin_vals["G"], pin_h=pin_vals["H"],
                    pin_s=pin_s_text or "",
                )

            subs.append(sub)

        db_dev = DbComplex(
            id_comp_desc=comp_id_i,
            name=str(updated_ui_dev.pn).strip(),
            total_pins=_as_int(getattr(updated_ui_dev, "pin_count", 0)),
            subcomponents=subs,
            aliases=getattr(updated_ui_dev, "aliases", []) or [],
        )

        # ---------- persist ----------
        assert self.db is not None
        if comp_id_i is None:
            comp_id_i = self.db.add_complex(db_dev)            # INSERT
        else:
            self.db.update_complex(comp_id_i, updated=db_dev)  # UPDATE

        try:
            self.db._conn.commit()
        except Exception:
            pass

        self._refresh_list()
        return comp_id_i

    def _refresh_list(self) -> None:
        """
        Reload the complexes table from the MDB and preserve current sort & selection.
        Sorting works by clicking the "ID" or "Name" header.
        """
        t = self.list  # QTableWidget

        # Remember selection (by ID) and current sort state
        sel_id = None
        if t.currentRow() >= 0:
            try:
                sel_id = t.item(t.currentRow(), 0).data(QtCore.Qt.ItemDataRole.DisplayRole)
                sel_id = int(sel_id) if sel_id is not None else None
            except Exception:
                sel_id = None

        hh = t.horizontalHeader()
        sort_col = hh.sortIndicatorSection() if hh else 0
        sort_ord = hh.sortIndicatorOrder() if hh else QtCore.Qt.SortOrder.AscendingOrder

        # Fetch rows: [(CompID, Name, SubCount), ...]
        rows = self.db.list_complexes()

        # Refill table with numeric-aware items
        t.setSortingEnabled(False)
        t.setRowCount(len(rows))

        for r, (comp_id, name, subcnt) in enumerate(rows):
            # ID column (numeric sort)
            id_item = QtWidgets.QTableWidgetItem()
            id_item.setData(QtCore.Qt.ItemDataRole.DisplayRole, int(comp_id))
            id_item.setTextAlignment(
                QtCore.Qt.AlignmentFlag.AlignRight | QtCore.Qt.AlignmentFlag.AlignVCenter
            )
            id_item.setFlags(id_item.flags() & ~QtCore.Qt.ItemFlag.ItemIsEditable)

            # Name column (text sort)
            name_item = QtWidgets.QTableWidgetItem(str(name or ""))
            name_item.setFlags(name_item.flags() & ~QtCore.Qt.ItemFlag.ItemIsEditable)

            # Subs column (numeric)
            subs_item = QtWidgets.QTableWidgetItem()
            subs_item.setData(QtCore.Qt.ItemDataRole.DisplayRole, int(subcnt or 0))
            subs_item.setTextAlignment(
                QtCore.Qt.AlignmentFlag.AlignRight | QtCore.Qt.AlignmentFlag.AlignVCenter
            )
            subs_item.setFlags(subs_item.flags() & ~QtCore.Qt.ItemFlag.ItemIsEditable)

            t.setItem(r, 0, id_item)
            t.setItem(r, 1, name_item)
            t.setItem(r, 2, subs_item)

        # Re-apply sort and selection
        t.setSortingEnabled(True)
        t.sortItems(max(0, sort_col), sort_ord)

        # Restore previous selection by ID (if still present)
        if sel_id is not None:
            for r in range(t.rowCount()):
                try:
                    rid = t.item(r, 0).data(QtCore.Qt.ItemDataRole.DisplayRole)
                    if int(rid) == int(sel_id):
                        t.setCurrentCell(r, 0)
                        break
                except Exception:
                    continue
        elif t.rowCount() > 0:
            t.setCurrentCell(0, 0)


    # ---------------------------------------------------------------- settings
    def _init_menu(self) -> None:
        menubar = self.menuBar()
        settings_menu = menubar.addMenu("&Settings")
        integration_action = settings_menu.addAction("Integration…")
        integration_action.triggered.connect(self._open_integration_settings)
        self._settings_action = integration_action

    def _open_integration_settings(self) -> None:
        dialog = IntegrationSettingsDialog(
            self.ctx,
            is_bridge_running=self._is_bridge_running,
            start_bridge=self._start_bridge,
            stop_bridge=self._stop_bridge,
            client_snippet=self._bridge_client_snippet,
            bridge_error=self._bridge_last_error,
            parent=self,
        )
        if dialog.exec() == QtWidgets.QDialog.DialogCode.Accepted:
            self.db = self.ctx.db
            self._func_map.clear()
            if self.db is not None and self._buffer_complexes is None:
                self._refresh_list()
            self._update_window_title()
            self._apply_bridge_config()

    def _apply_bridge_config(self) -> None:
        cfg = self.ctx.config.bridge
        if not cfg.enabled:
            self._bridge_controller.stop()
            return
        if not self.ctx.current_db_path().exists():
            return
        self._bridge_controller.start(cfg, self._bridge_wizard_handler)

    def _is_bridge_running(self) -> bool:
        return self._bridge_controller.is_running()

    def _start_bridge(self, cfg: BridgeConfig) -> bool:
        return self._bridge_controller.start(cfg, self._bridge_wizard_handler)

    def _stop_bridge(self) -> None:
        self._bridge_controller.stop()

    def _bridge_client_snippet(self, cfg: BridgeConfig) -> str:
        return self._bridge_controller.snippet(cfg)

    def _bridge_last_error(self) -> str | None:
        return self._bridge_controller.last_error()

    def _create_prefilled_wizard(
        self,
        macro_map: dict[int, MacroDef],
        pn: str,
        aliases: Optional[list[str]],
    ) -> NewComplexWizard:
        pn_clean = (pn or "").strip()
        alias_list = [a.strip() for a in (aliases or []) if a and a.strip()]
        try:
            title = f"New Complex — {pn_clean}" if pn_clean else None
        except Exception:
            title = None
        wizard = NewComplexWizard(macro_map, parent=self, title=title)

        device = ComplexDevice(0, [], MacroInstance("", {}))
        device.pn = pn_clean
        device.aliases = alias_list
        device.alt_pn = alias_list[0] if alias_list else ""
        device.pin_count = 0
        device.subcomponents = []

        try:
            wizard._editor.load_device(device)  # type: ignore[attr-defined]
        except AttributeError:
            pass
        return wizard

    def _bridge_wizard_handler(self, pn: str, aliases: Optional[list[str]]) -> BridgeCreateResult:
        if self.db is None:
            return BridgeCreateResult(created=False, reason="database unavailable")

        if self._active_wizard is not None or getattr(self.ctx, "wizard_open", False):
            return BridgeCreateResult(created=False, reason="wizard busy")

        cursor = self.db._conn.cursor()
        try:
            macro_map = schema_introspect.discover_macro_map(cursor) or {}
        except Exception:
            macro_map = {}

        opener = getattr(self.ctx, "wizard_opened", None)
        closer = getattr(self.ctx, "wizard_closed", None)

        wizard = self._create_prefilled_wizard(macro_map, pn, aliases)
        wizard.setMinimumSize(1000, 720)
        wizard.show()
        try:
            wizard.raise_()
        except Exception:
            pass
        try:
            wizard.activateWindow()
        except Exception:
            pass
        app = QtWidgets.QApplication.instance()
        if app is not None:
            try:
                app.processEvents()
            except Exception:
                pass

        if callable(opener):
            try:
                opener()
            except Exception:
                pass

        self._active_wizard = wizard
        saved = False
        had_changes = False
        try:
            result = wizard.exec()
            if result != QtWidgets.QDialog.DialogCode.Accepted:
                return BridgeCreateResult(created=False, reason="cancelled")

            had_changes = True
            editor_device: ComplexDevice
            if hasattr(wizard, "to_complex_device"):
                editor_device = wizard.to_complex_device()  # type: ignore[call-arg]
            else:
                editor_obj = getattr(wizard, "_editor", None)
                if editor_obj is None:
                    raise AttributeError("Wizard does not expose editor state")
                editor_device = editor_obj.build_device()
            new_id = self._persist_editor_device(editor_device, comp_id=None)
            if new_id is None:
                return BridgeCreateResult(created=False, reason="failed to persist")
            saved = True
            db_path = str(self.ctx.current_db_path())
            return BridgeCreateResult(created=True, comp_id=int(new_id), db_path=db_path)
        finally:
            if callable(closer):
                try:
                    closer(saved=saved, had_changes=had_changes)
                except Exception:
                    pass
            try:
                wizard.deleteLater()
            except Exception:
                pass
            self._active_wizard = None

    def _update_window_title(self) -> None:
        try:
            self.setWindowTitle(f"Complex Editor - {self.ctx.current_db_path()}")
        except Exception:
            pass

    def closeEvent(self, event):  # type: ignore[override]
        try:
            self._bridge_controller.stop()
        finally:
            super().closeEvent(event)


    def _refresh_subcomponents_db(self, cid: int) -> None:
        """Fill the right table with a friendly view of subcomponents (DB mode)."""
        assert self.db is not None
        cx = self.db.get_complex(cid)

        # Build display rows: Macro, PinA-D, PinS (raw XML), Value
        display_rows: List[Dict[str, str]] = []
        for sc in getattr(cx, "subcomponents", []) or []:
            name = self._func_name(sc.id_function)
            pin_map = {k: str(v) for k, v in (sc.pins or {}).items()}
            pin_s = pin_map.get("S") or ""
            if isinstance(pin_s, bytes):
                pin_s = pin_s.decode("utf-16", errors="ignore")
            display_rows.append(
                {
                    "Macro": name,
                    "PinA": pin_map.get("A", ""),
                    "PinB": pin_map.get("B", ""),
                    "PinC": pin_map.get("C", ""),
                    "PinD": pin_map.get("D", ""),
                    "PinS": pin_s,
                    "Value": "" if sc.value is None else str(sc.value),
                }
            )

        if not display_rows:
            self.sub_table.setRowCount(0)
            self.sub_table.setColumnCount(0)
            return

        headers = ["Macro", "PinA", "PinB", "PinC", "PinD", "PinS", "Value"]
        self.sub_table.setColumnCount(len(headers))
        self.sub_table.setHorizontalHeaderLabels(headers)
        self.sub_table.setRowCount(len(display_rows))
        for r, row in enumerate(display_rows):
            for c, key in enumerate(headers):
                self.sub_table.setItem(r, c, QtWidgets.QTableWidgetItem(row.get(key, "")))

        self.sub_table.resizeColumnsToContents()

    def _refresh_subcomponents_buffer(self, cx: EditorComplex) -> None:
        """Fill the right table with subcomponents from a buffer."""
        display_rows: List[Dict[str, str]] = []
        for sc in cx.subcomponents:
            pin_map = sc.pins or {}
            pin_s = getattr(sc, "pin_s_raw", "")
            if not pin_s and getattr(sc, "all_macros", None):
                try:
                    pin_s = params_to_xml(sc.all_macros, encoding="utf-16", schema=ALLOWED_PARAMS).decode(
                        "utf-16"
                    )
                except Exception:
                    pin_s = ""
            display_rows.append(
                {
                    "SubID": str(getattr(sc, "sub_id", "")),
                    "Macro": sc.name,
                    "PinA": pin_map.get("A", ""),
                    "PinB": pin_map.get("B", ""),
                    "PinC": pin_map.get("C", ""),
                    "PinD": pin_map.get("D", ""),
                    "PinS": pin_s,
                    "Value": "" if getattr(sc, "value", None) in (None, "") else str(getattr(sc, "value")),
                    "ForceBits": "" if getattr(sc, "force_bits", None) in (None, "") else str(getattr(sc, "force_bits")),
                }
            )

        if not display_rows:
            self.sub_table.setRowCount(0)
            self.sub_table.setColumnCount(0)
            return

        headers = ["SubID", "Macro", "PinA", "PinB", "PinC", "PinD", "PinS", "Value", "ForceBits"]
        self.sub_table.setColumnCount(len(headers))
        self.sub_table.setHorizontalHeaderLabels(headers)
        self.sub_table.setRowCount(len(display_rows))
        for r, row in enumerate(display_rows):
            for c, key in enumerate(headers):
                self.sub_table.setItem(r, c, QtWidgets.QTableWidgetItem(row.get(key, "")))

        self.sub_table.resizeColumnsToContents()

    def _apply_filters(self) -> None:
        """Hide rows that do not match all active column filters."""
        for r in range(self.list.rowCount()):
            visible = True
            for c, edit in enumerate(self._filters):
                text = edit.text().lower().strip()
                if not text:
                    continue
                item = self.list.item(r, c)
                cell = item.text().lower() if item else ""
                if text not in cell:
                    visible = False
                    break
            self.list.setRowHidden(r, not visible)

    def _on_selected(self) -> None:
        row = self.list.currentRow()
        if row < 0:
            if hasattr(self.ctx, "focused_comp_id"):
                self.ctx.focused_comp_id = None
            self.sub_table.setRowCount(0)
            self.sub_table.setColumnCount(0)
            return
        if self._buffer_complexes is not None:
            if 0 <= row < len(self._buffer_complexes):
                self._refresh_subcomponents_buffer(self._buffer_complexes[row])
            return

        cid_item = self.list.item(row, 0)
        if cid_item is None:
            return
        try:
            cid_val = int(cid_item.text())
        except Exception:
            cid_val = None
        if hasattr(self.ctx, "focused_comp_id"):
            self.ctx.focused_comp_id = cid_val
        if cid_val is None:
            return
        self._refresh_subcomponents_db(cid_val)

    def _process_events(self) -> None:
        app = QtWidgets.QApplication.instance()
        if app is None:
            return
        try:
            app.processEvents()
        except Exception:
            pass

    def _bring_window_forward(self, widget: QtWidgets.QWidget) -> None:
        try:
            widget.showNormal()
        except Exception:
            try:
                widget.show()
            except Exception:
                pass
        try:
            widget.setWindowState(widget.windowState() & ~QtCore.Qt.WindowState.WindowMinimized)
        except Exception:
            pass
        try:
            widget.raise_()
        except Exception:
            pass
        try:
            widget.activateWindow()
        except Exception:
            pass

    def _find_row_for_comp(self, comp_id: int) -> Optional[int]:
        for row in range(self.list.rowCount()):
            item = self.list.item(row, 0)
            if item is None:
                continue
            try:
                if int(item.text()) == int(comp_id):
                    return row
            except Exception:
                continue
        return None

    def _create_editor_for(self, comp_id: int) -> ComplexEditor:
        assert self.db is not None
        cursor = self.db._conn.cursor()
        try:
            macro_map = schema_introspect.discover_macro_map(cursor) or {}
        except Exception:
            macro_map = {}
        raw = self.db.get_complex(comp_id)
        editor = ComplexEditor(macro_map)
        device = ComplexDevice(0, [], MacroInstance("", {}))
        device.id = comp_id
        device.pn = getattr(raw, "name", "")
        try:
            device.aliases = list(getattr(raw, "aliases", []) or [])
        except Exception:
            device.aliases = []
        device.pin_count = getattr(raw, "total_pins", 0)
        device.subcomponents = []
        for sc in getattr(raw, "subcomponents", []) or []:
            name = self._func_name(sc.id_function)
            pin_list = [sc.pins.get(k, 0) for k in ["A", "B", "C", "D"]]
            pin_s_raw = (sc.pins or {}).get("S", "")
            if isinstance(pin_s_raw, bytes):
                try:
                    pin_s_text = pin_s_raw.decode("utf-16", errors="ignore")
                except Exception:
                    pin_s_text = ""
            else:
                pin_s_text = str(pin_s_raw or "")
            _rules = get_learned_rules()
            xml_map = {}
            try:
                xml_map = xml_to_params_tolerant(pin_s_text, rules=_rules) if pin_s_text else {}
            except Exception:
                xml_map = {}
            params = xml_map.get(name) or (next(iter(xml_map.values())) if xml_map else {})
            device.subcomponents.append(SubComponent(MacroInstance(name, params), tuple(pin_list)))
        editor.load_device(device)
        try:
            editor.setWindowTitle(f"Edit Complex — {device.pn}")
        except Exception:
            pass
        return editor

    def _ensure_editor_for(self, comp_id: int, pn_text: str) -> bool:
        if self.db is None:
            raise FocusBusyError("database unavailable")
        if self._active_wizard is not None:
            raise FocusBusyError("wizard busy")
        if self._active_editor is not None:
            if self._active_editor_id == comp_id:
                self._bring_window_forward(self._active_editor)
                self._process_events()
                return True
            raise FocusBusyError("editor busy")
        if getattr(self.ctx, "wizard_open", False):
            raise FocusBusyError("wizard busy")

        editor = self._create_editor_for(comp_id)
        editor.setModal(False)
        try:
            editor.setAttribute(QtCore.Qt.WidgetAttribute.WA_DeleteOnClose, True)
        except Exception:
            pass

        opener = getattr(self.ctx, "wizard_opened", None)
        if callable(opener):
            try:
                opener()
            except Exception:
                pass

        self._active_editor = editor
        self._active_editor_id = int(comp_id)

        def _on_finished(result: int, dlg=editor, cid=comp_id) -> None:
            self._on_editor_finished(dlg, cid, result)

        editor.finished.connect(_on_finished)
        editor.show()
        try:
            editor.setWindowTitle(editor.windowTitle() or f"Edit Complex — {pn_text}")
        except Exception:
            pass
        self._bring_window_forward(editor)
        self._process_events()
        return True

    def _reselect_after_save(self, comp_id: int) -> None:
        self._refresh_list()
        row = self._find_row_for_comp(comp_id)
        if row is None:
            return
        self.list.setCurrentCell(row, 0)
        self.list.scrollToItem(
            self.list.item(row, 0),
            QtWidgets.QAbstractItemView.ScrollHint.PositionAtCenter,
        )
        self._process_events()
        self._on_selected()

    def _on_editor_finished(self, editor: ComplexEditor, comp_id: int, result: int) -> None:
        saved = False
        had_changes = result == QtWidgets.QDialog.DialogCode.Accepted
        try:
            if result == QtWidgets.QDialog.DialogCode.Accepted:
                try:
                    updated = editor.build_device()
                    saved_id = self._persist_editor_device(updated, comp_id=comp_id)
                    saved = saved_id is not None
                    if saved:
                        self._reselect_after_save(comp_id)
                        try:
                            QtWidgets.QMessageBox.information(self, "Updated", "Complex updated")
                        except Exception:
                            pass
                except Exception as exc:
                    try:
                        QtWidgets.QMessageBox.warning(
                            self,
                            "Save Failed",
                            f"Failed to update complex {comp_id}: {exc}",
                        )
                    except Exception:
                        pass
            else:
                had_changes = False
        finally:
            closer = getattr(self.ctx, "wizard_closed", None)
            if callable(closer):
                try:
                    closer(saved=saved, had_changes=had_changes)
                except Exception:
                    pass
            if self._active_editor is editor:
                self._active_editor = None
                self._active_editor_id = None
            try:
                editor.deleteLater()
            except Exception:
                pass
            self._process_events()

    # ------------------------------------------------------------------ actions
    def focus_complex(self, comp_id: int, mode: str = "view") -> dict[str, object]:
        """
        Select the complex in the list, refresh the detail pane, and bring the window forward.

        Returns a dict with ``pn`` for logging. Raises KeyError if the complex is not found.
        """

        if self.db is None:
            raise KeyError(comp_id)

        normalized_mode = (mode or "view").strip().lower()
        if normalized_mode not in {"view", "edit"}:
            raise ValueError(f"Unsupported focus mode: {mode}")

        # Refresh to keep the table aligned with the database contents.
        self._refresh_list()

        target_row = self._find_row_for_comp(comp_id)
        if target_row is None:
            raise KeyError(comp_id)

        previous_row = self.list.currentRow()

        self._bring_window_forward(self)

        self.list.setCurrentCell(target_row, 0)
        self.list.scrollToItem(
            self.list.item(target_row, 0),
            QtWidgets.QAbstractItemView.ScrollHint.PositionAtCenter,
        )
        self._process_events()
        self._on_selected()

        pn_item = self.list.item(target_row, 1)
        pn_text = pn_item.text() if pn_item is not None else ""
        self.ctx.focused_comp_id = int(comp_id)

        try:
            self.list.setFocus(QtCore.Qt.FocusReason.OtherFocusReason)
            app = QtWidgets.QApplication.instance()
            if app is not None:
                app.setActiveWindow(self)
        except Exception:
            pass

        wizard_flag = False
        if normalized_mode == "edit":
            try:
                self._ensure_editor_for(comp_id, pn_text)
                wizard_flag = getattr(self.ctx, "wizard_open", True)
            except FocusBusyError:
                if previous_row != target_row and previous_row >= 0:
                    try:
                        self.list.setCurrentCell(previous_row, 0)
                        self._on_selected()
                    except Exception:
                        pass
                raise
        else:
            try:
                app = QtWidgets.QApplication.instance()
                if app is not None:
                    app.setActiveWindow(self)

            except Exception:
                pass

        self._process_events()
        return {
            "pn": pn_text,
            "focused_comp_id": int(comp_id),
            "wizard_open": bool(wizard_flag),
        }

    def _new_complex(self) -> None:
        if self.db is None:
            return
        cursor = self.db._conn.cursor()
        macro_map = schema_introspect.discover_macro_map(cursor) or {}
        editor = ComplexEditor(macro_map)
        opener = getattr(self.ctx, "wizard_opened", None)
        closer = getattr(self.ctx, "wizard_closed", None)
        closer_called = False
        result: int | QtWidgets.QDialog.DialogCode = QtWidgets.QDialog.DialogCode.Rejected
        if callable(opener):
            opener()
        try:
            result = editor.exec()
            if result == QtWidgets.QDialog.DialogCode.Accepted:
                updated = editor.build_device()
                new_id = self._persist_editor_device(updated, comp_id=None)
                if callable(closer):
                    closer(saved=new_id is not None, had_changes=True)
                    closer_called = True
            else:
                if callable(closer):
                    closer(saved=False, had_changes=False)
                    closer_called = True
        finally:
            if callable(closer) and not closer_called:
                closer(
                    saved=False,
                    had_changes=result == QtWidgets.QDialog.DialogCode.Accepted,
                )


    def _on_edit(self) -> None:
        row = self.list.currentRow()
        if row < 0:
            return
        if self._buffer_complexes is not None:
            cx = self._buffer_complexes[row]
            try:
                macro_map = schema_introspect.discover_macro_map(None) or {}
            except Exception:
                macro_map = {}
            if not macro_map:
                names = set()
                for em in cx.subcomponents:
                    names.add(getattr(em, "selected_macro", em.name))
                macro_map = {i + 1: MacroDef(i + 1, n, []) for i, n in enumerate(sorted(names))}
            editor = ComplexEditor(macro_map)
            dev = ComplexDevice(0, [], MacroInstance("", {}))
            dev.id = cx.id
            dev.pn = cx.name
            dev.pin_count = len(cx.pins)
            for em in cx.subcomponents:
                mname = getattr(em, "selected_macro", em.name)
                pins = [int(em.pins.get(k, 0) or 0) for k in ["A", "B", "C", "D"]]
                pin_s_raw = getattr(em, "pin_s_raw", "") or em.pins.get("S", "")
                if isinstance(pin_s_raw, bytes):
                    try:
                        pin_s_text = pin_s_raw.decode("utf-16", errors="ignore")
                    except Exception:
                        pin_s_text = ""
                else:
                    pin_s_text = str(pin_s_raw or "")

                _rules = get_learned_rules()
                xml_map = {}
                try:
                    xml_map = xml_to_params_tolerant(pin_s_text, rules=_rules) if pin_s_text else {}
                except Exception:
                    xml_map = {}

                params = xml_map.get(mname) or (next(iter(xml_map.values())) if xml_map else {})

                dev.subcomponents.append(SubComponent(MacroInstance(mname, params), tuple(pins)))
            editor.load_device(dev)
            opener = getattr(self.ctx, "wizard_opened", None)
            closer = getattr(self.ctx, "wizard_closed", None)
            closer_called = False
            if callable(opener):
                try:
                    opener()
                except Exception:
                    pass
            result = QtWidgets.QDialog.DialogCode.Rejected
            try:
                result = editor.exec()
                if result == QtWidgets.QDialog.DialogCode.Accepted:
                    updated = editor.build_device()
                    self._persist_editor_device(updated, comp_id=cx.id)
                    self.list.selectRow(row)
                    self._on_selected()
                    if callable(closer):
                        closer(saved=True, had_changes=True)
                        closer_called = True
                else:
                    if callable(closer):
                        closer(saved=False, had_changes=False)
                        closer_called = True
            finally:
                if callable(closer) and not closer_called:
                    try:
                        closer(
                            saved=False,
                            had_changes=result == QtWidgets.QDialog.DialogCode.Accepted,
                        )
                    except Exception:
                        pass
            return

        cid_item = self.list.item(row, 0)
        if cid_item is None:
            return

        cursor = self.db._conn.cursor()
        macro_map = schema_introspect.discover_macro_map(cursor) or {}
        cid = int(cid_item.text())
        raw = self.db.get_complex(cid)
        editor = ComplexEditor(macro_map)
        dev = ComplexDevice(0, [], MacroInstance("", {}))
        dev.id = cid
        dev.pn = getattr(raw, "name", "")
        # carry DB aliases into the editor
        try:
            dev.aliases = list(getattr(raw, "aliases", []) or [])
        except Exception:
            dev.aliases = []
        dev.pin_count = getattr(raw, "total_pins", 0)
        dev.subcomponents = []
        for sc in getattr(raw, "subcomponents", []) or []:
            name = self._func_name(sc.id_function)
            pin_list = [sc.pins.get(k, 0) for k in ["A", "B", "C", "D"]]
            pin_s_raw = (sc.pins or {}).get("S", "")
            if isinstance(pin_s_raw, bytes):
                try:
                    pin_s_text = pin_s_raw.decode("utf-16", errors="ignore")
                except Exception:
                    pin_s_text = ""
            else:
                pin_s_text = str(pin_s_raw or "")

            _rules = get_learned_rules()
            xml_map = {}
            try:
                xml_map = xml_to_params_tolerant(pin_s_text, rules=_rules) if pin_s_text else {}
            except Exception:
                xml_map = {}

            params = xml_map.get(name) or (next(iter(xml_map.values())) if xml_map else {})

            dev.subcomponents.append(SubComponent(MacroInstance(name, params), tuple(pin_list)))
        editor.load_device(dev)
        opener = getattr(self.ctx, "wizard_opened", None)
        closer = getattr(self.ctx, "wizard_closed", None)
        closer_called = False
        if callable(opener):
            try:
                opener()
            except Exception:
                pass
        result = QtWidgets.QDialog.DialogCode.Rejected
        saved = False
        try:
            result = editor.exec()
            if result == QtWidgets.QDialog.DialogCode.Accepted:
                updated = editor.build_device()
                saved_id = self._persist_editor_device(updated, comp_id=cid)
                saved = saved_id is not None
                self.list.selectRow(row)
                self._on_selected()
                if saved:
                    try:
                        QtWidgets.QMessageBox.information(self, "Updated", "Complex updated")
                    except Exception:
                        pass
                if callable(closer):
                    closer(saved=saved, had_changes=True)
                    closer_called = True
            else:
                if callable(closer):
                    closer(saved=False, had_changes=False)
                    closer_called = True
        finally:
            if callable(closer) and not closer_called:
                try:
                    closer(saved=saved, had_changes=result == QtWidgets.QDialog.DialogCode.Accepted)
                except Exception:
                    pass

    def _delete_selected(self) -> None:
        row = self.list.currentRow()
        if row < 0:
            return
        if self.db is None:
            return
        cid = int(self.list.item(row, 0).text())
        if (
            QtWidgets.QMessageBox.question(self, "Delete?", f"Delete complex {cid}?")
            == QtWidgets.QMessageBox.StandardButton.Yes
        ):
            self.db.delete_complex(cid, cascade=True)
            self.db._conn.commit()
            self._refresh_list()

    def _setup_sortable_list(self) -> None:
        """
        One-time table setup: enable header-click sorting for ID/Name.
        Assumes self.list is a QTableWidget.
        """
        t = self.list  # QTableWidget
        t.setColumnCount(3)
        t.setHorizontalHeaderLabels(["ID", "Name", "Subs"])
        t.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectionBehavior.SelectRows)
        t.setSelectionMode(QtWidgets.QAbstractItemView.SelectionMode.SingleSelection)
        t.setEditTriggers(QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers)
        t.verticalHeader().setVisible(False)

        hh = t.horizontalHeader()
        hh.setSectionsClickable(True)
        hh.setSortIndicatorShown(True)
        hh.setStretchLastSection(True)

        # Enable sorting and default to ID ascending
        t.setSortingEnabled(True)
        t.sortItems(0, QtCore.Qt.SortOrder.AscendingOrder)




def _ensure_database_available(ctx: AppContext, parent: QtWidgets.QWidget | None = None) -> Path:
    from PyQt6 import QtWidgets

    while True:
        candidate = ctx.current_db_path()
        if candidate.exists():
            return candidate
        msg = QtWidgets.QMessageBox(parent)
        msg.setIcon(QtWidgets.QMessageBox.Icon.Warning)
        msg.setWindowTitle("Access Database Required")
        msg.setText(
            "The configured Access database could not be found."
            "Select an existing file or create a new database from the template."
        )
        select_btn = msg.addButton("Select Existing...", QtWidgets.QMessageBox.ButtonRole.AcceptRole)
        create_btn = msg.addButton("Create from Template...", QtWidgets.QMessageBox.ButtonRole.ActionRole)
        quit_btn = msg.addButton("Quit", QtWidgets.QMessageBox.ButtonRole.RejectRole)
        msg.exec()
        clicked = msg.clickedButton()
        if clicked is quit_btn:
            raise SystemExit(0)
        if clicked is select_btn:
            file_name, _ = QtWidgets.QFileDialog.getOpenFileName(
                parent,
                "Select Access Database",
                str(candidate.parent if candidate.parent.exists() else Path.home()),
                "Access Database (*.mdb *.accdb);;All files (*)",
            )
            if not file_name:
                continue
            try:
                ctx.update_mdb_path(Path(file_name), create_if_missing=False)
                ctx.persist_config()
                return ctx.current_db_path()
            except FileNotFoundError:
                QtWidgets.QMessageBox.warning(
                    parent,
                    "File Not Found",
                    f"The selected file does not exist\n{file_name}",
                )
        elif clicked is create_btn:
            file_name, _ = QtWidgets.QFileDialog.getSaveFileName(
                parent,
                "Create Access Database",
                str(candidate.with_suffix(".mdb")),
                "Access Database (*.mdb)",
            )
            if not file_name:
                continue
            dest = Path(file_name)
            ctx.update_mdb_path(dest, create_if_missing=True)
            ctx.persist_config()
            return dest


def run_gui(
    mdb_file: Path | None = None,
    buffer_path: Path | None = None,
    *,
    ctx: AppContext | None = None,
    bridge_autostart: BridgeConfig | None = None,
    bridge_ui_mode: str = "headless",
) -> None:
    from PyQt6 import QtWidgets

    app = QtWidgets.QApplication(sys.argv)
    ctx = ctx or AppContext()

    if mdb_file is not None:
        ctx.update_mdb_path(Path(mdb_file), create_if_missing=True)
        ctx.persist_config()

    if buffer_path is None:
        while True:
            try:
                ctx.open_main_db(create_if_missing=False)
                break
            except FileNotFoundError:
                _ensure_database_available(ctx)
        print(f"[complex_editor] Using MDB: {ctx.current_db_path()}")

    win = MainWindow(
        mdb_path=ctx.current_db_path() if buffer_path is None else None,
        buffer_path=buffer_path,
        ctx=ctx,
    )
    win.resize(1100, 600)
    win.show()

    if bridge_autostart is not None:
        started = win._bridge_controller.start(bridge_autostart, win._bridge_wizard_handler)
        auth_mode = "enabled" if bridge_autostart.auth_token else "disabled"
        ui_mode = bridge_ui_mode or "headless"
        host = bridge_autostart.host
        port = int(bridge_autostart.port)
        if not started:
            print(
                f"[ce-bridge] failed to start on http://{host}:{port} "
                f"(auth: {auth_mode}, ui: {ui_mode})",
                file=sys.stderr,
                flush=True,
            )
            raise SystemExit(1)
        print(
            f"[ce-bridge] listening on http://{host}:{port} "
            f"(auth: {auth_mode}, ui: {ui_mode})",
            flush=True,
        )

    app.aboutToQuit.connect(win._bridge_controller.stop)
    sys.exit(app.exec())



