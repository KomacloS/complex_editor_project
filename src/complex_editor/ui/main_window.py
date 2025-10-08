from __future__ import annotations

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
from .settings_dialog import IntegrationSettingsDialog

from ce_bridge_service.types import BridgeCreateResult


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
            lambda: self.ctx.current_db_path(),
            self._bridge_invoker,
        )
        self.db: Optional[MDB] = None
        self._buffer_complexes: List[EditorComplex] | None = None
        self._buffer_raw: List[dict] | None = None
        self._buffer_path: Path | None = None

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

    def _bridge_wizard_handler(self, pn: str, aliases: Optional[list[str]]) -> BridgeCreateResult:
        if self.db is None:
            return BridgeCreateResult(created=False, reason="database unavailable")

        cursor = self.db._conn.cursor()
        try:
            macro_map = schema_introspect.discover_macro_map(cursor) or {}
        except Exception:
            macro_map = {}

        editor = ComplexEditor(macro_map)
        prefill = ComplexDevice(0, [], MacroInstance("", {}))
        prefill.pn = pn.strip()
        prefill.aliases = [a.strip() for a in (aliases or []) if a and a.strip()]
        prefill.pin_count = 0
        editor.load_device(prefill)

        if editor.exec() != QtWidgets.QDialog.DialogCode.Accepted:
            return BridgeCreateResult(created=False, reason="cancelled")

        updated = editor.build_device()
        new_id = self._persist_editor_device(updated, comp_id=None)
        if new_id is None:
            return BridgeCreateResult(created=False, reason="failed to persist")
        db_path = str(self.ctx.current_db_path())
        return BridgeCreateResult(created=True, comp_id=int(new_id), db_path=db_path)

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
        self._refresh_subcomponents_db(int(cid_item.text()))

    # ------------------------------------------------------------------ actions
    def _new_complex(self) -> None:
        if self.db is None:
            return
        cursor = self.db._conn.cursor()
        macro_map = schema_introspect.discover_macro_map(cursor) or {}
        editor = ComplexEditor(macro_map)
        if editor.exec() == QtWidgets.QDialog.DialogCode.Accepted:
            updated = editor.build_device()
            self._persist_editor_device(updated, comp_id=None)


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
            if editor.exec() == QtWidgets.QDialog.DialogCode.Accepted:
                updated = editor.build_device()
                self._persist_editor_device(updated, comp_id=cx.id)
                self.list.selectRow(row)
                self._on_selected()
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
        if editor.exec() == QtWidgets.QDialog.DialogCode.Accepted:
            updated = editor.build_device()
            self._persist_editor_device(updated, comp_id=cid)
            self.list.selectRow(row)
            self._on_selected()
            QtWidgets.QMessageBox.information(self, "Updated", "Complex updated")

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


def run_gui(mdb_file: Path | None = None, buffer_path: Path | None = None) -> None:
    import sys
    from PyQt6 import QtWidgets

    app = QtWidgets.QApplication(sys.argv)
    ctx = AppContext()

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
    sys.exit(app.exec())



