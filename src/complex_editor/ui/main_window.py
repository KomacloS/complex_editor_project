from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

from PyQt6 import QtWidgets

from ..core.app_context import AppContext
from ..domain import ComplexDevice, MacroDef, MacroInstance, SubComponent
from ..db.mdb_api import MDB, SubComponent as DbSub, ComplexDevice as DbComplex
from ..db import schema_introspect
from .complex_editor import ComplexEditor
from .adapters import EditorComplex, EditorMacro
from .buffer_loader import load_editor_complexes_from_buffer
from .buffer_persistence import load_buffer, save_buffer
from ..util.macro_xml_translator import params_to_xml, xml_to_params
from ..param_spec import ALLOWED_PARAMS


class MainWindow(QtWidgets.QMainWindow):
    """Main window showing complexes from the MDB or a JSON buffer."""

    def __init__(
        self,
        mdb_path: Optional[Path] = None,
        parent: Any | None = None,
        buffer_path: Optional[Path] = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Complex View")
        self.ctx = AppContext()
        self.db: Optional[MDB] = None
        self._buffer_complexes: List[EditorComplex] | None = None
        self._buffer_raw: List[dict] | None = None
        self._buffer_path: Path | None = None

        if buffer_path is not None and Path(buffer_path).exists():
            self._buffer_path = Path(buffer_path)
            self._buffer_raw = load_buffer(self._buffer_path)
            self._buffer_complexes = load_editor_complexes_from_buffer(buffer_path)
        else:
            if mdb_path is None:
                raise ValueError("mdb_path must be provided when no buffer is given")
            self.db = self.ctx.open_main_db(mdb_path)

        # cache of {IDFunction -> Name}
        self._func_map: Dict[int, str] = {}

        # left list of complexes
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
        left.addWidget(self.list)

        container = QtWidgets.QWidget()
        layout = QtWidgets.QHBoxLayout(container)
        layout.addLayout(left)
        layout.addWidget(self.sub_table)
        self.setCentralWidget(container)

        self._refresh_list()

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

    def _refresh_list(self) -> None:
        if self._buffer_complexes is not None:
            rows = self._buffer_complexes
            self.list.setRowCount(len(rows))
            for r, cx in enumerate(rows):
                self.list.setItem(r, 0, QtWidgets.QTableWidgetItem(str(cx.id)))
                self.list.setItem(r, 1, QtWidgets.QTableWidgetItem(str(cx.name)))
                self.list.setItem(r, 2, QtWidgets.QTableWidgetItem(str(len(cx.subcomponents))))
            return

        # DB mode
        assert self.db is not None  # for type checkers
        rows_db = self.db.list_complexes()
        self.list.setRowCount(len(rows_db))
        for r, row in enumerate(rows_db):
            # tolerate either (id, name, subcount) or (id, name, func, subcount)
            if len(row) == 3:
                cid, name, nsubs = row
            else:
                cid, name, _func, nsubs = row
            self.list.setItem(r, 0, QtWidgets.QTableWidgetItem(str(cid)))
            self.list.setItem(r, 1, QtWidgets.QTableWidgetItem(str(name)))
            self.list.setItem(r, 2, QtWidgets.QTableWidgetItem(str(nsubs)))

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
            dev = editor.build_device()
            subs: List[DbSub] = []
            for sc in dev.subcomponents:
                fid = self._macro_id_from_name(sc.macro.name) or 0
                pins = {k: v for k, v in zip(["A", "B", "C", "D"], sc.pins)}
                xml = params_to_xml({sc.macro.name: sc.macro.params}, encoding="utf-16", schema=ALLOWED_PARAMS).decode("utf-16")
                pins["S"] = xml
                subs.append(DbSub(None, fid, pins=pins))
            db_dev = DbComplex(None, dev.pn, dev.pin_count, subs)
            # alt_pn is UI-only; DB schema lacks a column
            self.db.add_complex(db_dev)
            self.db._conn.commit()
            self._refresh_list()


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
                params = dict(getattr(em, "macro_params", {}))
                dev.subcomponents.append(SubComponent(MacroInstance(mname, params), pins))
            editor.load_device(dev)
            if editor.exec() == QtWidgets.QDialog.DialogCode.Accepted:
                updated = editor.build_device()
                raw = self._buffer_raw[row]
                raw["name"] = updated.pn
                if updated.alt_pn:
                    raw["alt_pn"] = updated.alt_pn
                raw["pins"] = [str(i) for i in range(1, updated.pin_count + 1)]
                subs_raw = []
                for sc in updated.subcomponents:
                    xml = params_to_xml({sc.macro.name: sc.macro.params}, encoding="utf-16", schema=ALLOWED_PARAMS).decode("utf-16")
                    subs_raw.append(
                        {
                            "function_name": sc.macro.name,
                            "pins": {
                                "A": sc.pins[0],
                                "B": sc.pins[1],
                                "C": sc.pins[2],
                                "D": sc.pins[3],
                                "S": xml,
                            },
                        }
                    )
                raw["subcomponents"] = subs_raw
                save_buffer(self._buffer_path, self._buffer_raw)
                cx.name = updated.pn
                cx.pins = [str(i) for i in range(1, updated.pin_count + 1)]
                cx.subcomponents = []
                for sc in updated.subcomponents:
                    em = EditorMacro(sc.macro.name, {"A": str(sc.pins[0]), "B": str(sc.pins[1]), "C": str(sc.pins[2]), "D": str(sc.pins[3])}, sc.macro.params)
                    cx.subcomponents.append(em)
                self._refresh_list()
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
        dev.pin_count = getattr(raw, "total_pins", 0)
        dev.subcomponents = []
        for sc in getattr(raw, "subcomponents", []) or []:
            name = self._func_name(sc.id_function)
            pin_list = [sc.pins.get(k, 0) for k in ["A", "B", "C", "D"]]
            params = xml_to_params(sc.pins.get("S", "")).get(name, {})
            dev.subcomponents.append(SubComponent(MacroInstance(name, params), pin_list))
        editor.load_device(dev)
        if editor.exec() == QtWidgets.QDialog.DialogCode.Accepted:
            updated = editor.build_device()
            subs: List[DbSub] = []
            for sc in updated.subcomponents:
                fid = self._macro_id_from_name(sc.macro.name) or 0
                pins = {k: v for k, v in zip(["A", "B", "C", "D"], sc.pins)}
                xml = params_to_xml({sc.macro.name: sc.macro.params}, encoding="utf-16", schema=ALLOWED_PARAMS).decode("utf-16")
                pins["S"] = xml
                subs.append(DbSub(None, fid, pins=pins))
            db_dev = DbComplex(cid, updated.pn, updated.pin_count, subs)
            # alt_pn is UI-only; DB schema lacks a column
            self.db.update_complex(cid, updated=db_dev)
            self.db._conn.commit()
            self._refresh_list()
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


def run_gui(mdb_file: Path | None = None, buffer_path: Path | None = None) -> None:
    app = QtWidgets.QApplication(sys.argv)
    win = MainWindow(mdb_path=mdb_file, buffer_path=buffer_path)
    win.resize(1100, 600)
    win.show()
    sys.exit(app.exec())
