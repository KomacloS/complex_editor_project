from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

from PyQt6 import QtWidgets

from ..core.app_context import AppContext
from ..domain import ComplexDevice, MacroInstance
from ..db.mdb_api import MDB
from ..db import schema_introspect
from .complex_editor import ComplexEditor
from .adapters import EditorComplex, EditorMacro
from .buffer_loader import load_editor_complexes_from_buffer
from .buffer_persistence import load_buffer, save_buffer
from ..util.macro_xml_translator import params_to_xml
from .new_complex_wizard import NewComplexWizard
from ..io.buffer_loader import (
    load_complex_from_buffer_json,
    to_wizard_prefill,
)
from ..io.db_adapter import to_wizard_prefill_from_db


class MainWindow(QtWidgets.QMainWindow):
    """Main window showing complexes from the MDB or a JSON buffer."""

    def __init__(
        self,
        mdb_path: Optional[Path] = None,
        parent: Any | None = None,
        buffer_path: Optional[Path] = None,
    ) -> None:
        super().__init__(parent)
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
            del_btn.setEnabled(False)

        toolbar = QtWidgets.QHBoxLayout()
        toolbar.addWidget(new_btn)
        toolbar.addWidget(edit_btn)
        toolbar.addWidget(del_btn)
        load_buf_btn = QtWidgets.QPushButton("Load Complex from Buffer…")
        load_buf_btn.clicked.connect(self._load_complex_from_buffer)
        toolbar.addWidget(load_buf_btn)
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

        # Build display rows: Macro, Pins, Value
        display_rows: List[Dict[str, str]] = []
        for sc in getattr(cx, "subcomponents", []) or []:
            name = self._func_name(sc.id_function)
            pin_items = sc.pins or {}
            ordered_keys = [k for k in list("ABCDEFGH") + ["S"] if k in pin_items] + [
                k for k in pin_items.keys() if k not in "ABCDEFGH" and k != "S"
            ]
            pins_str = ", ".join(f"{k}:{pin_items[k]}" for k in ordered_keys)
            display_rows.append(
                {"Macro": name, "Pins": pins_str, "Value": "" if sc.value is None else str(sc.value)}
            )

        if not display_rows:
            self.sub_table.setRowCount(0)
            self.sub_table.setColumnCount(0)
            return

        headers = ["Macro", "Pins", "Value"]
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
            pin_items = sc.pins or {}
            ordered_keys = [k for k in sorted(pin_items.keys()) if k.isalpha()]
            pins_str = ", ".join(f"{k}={pin_items[k]}" for k in ordered_keys)
            display_rows.append(
                {
                    "SubID": str(getattr(sc, "sub_id", "")),
                    "Macro": sc.name,
                    "Pins": pins_str,
                    "Value": "" if getattr(sc, "value", None) in (None, "") else str(getattr(sc, "value")),
                    "ForceBits": "" if getattr(sc, "force_bits", None) in (None, "") else str(getattr(sc, "force_bits")),
                }
            )

        if not display_rows:
            self.sub_table.setRowCount(0)
            self.sub_table.setColumnCount(0)
            return

        headers = ["SubID", "Macro", "Pins", "Value", "ForceBits"]
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
        wiz = NewComplexWizard(macro_map)
        if wiz.exec() == QtWidgets.QDialog.DialogCode.Accepted:
            dev = ComplexDevice(
                id_function=0,
                pins=[str(i) for i in range(1, wiz.basics_page.pin_spin.value() + 1)],
                macro=MacroInstance("", {}),
            )
            dev.subcomponents = wiz.sub_components
            self.db.add_complex(dev)
            self.db._conn.commit()
            self._refresh_list()

    def _on_edit(self) -> None:
        row = self.list.currentRow()
        if row < 0:
            return
        cid_item = self.list.item(row, 0)
        if cid_item is None:
            return

        if self._buffer_complexes is not None:
            cx = self._buffer_complexes[row]
            dlg = ComplexEditor({})
            dlg.load_editor_complex(cx)
            if (
                dlg.exec() == QtWidgets.QDialog.DialogCode.Accepted
                and self._buffer_raw is not None
                and self._buffer_path is not None
            ):
                raw_cx = self._buffer_raw[row]
                for raw_sc, sc in zip(raw_cx.get("subcomponents", []), cx.subcomponents):
                    sc.all_macros[sc.selected_macro] = sc.macro_params
                    xml = params_to_xml(sc.all_macros, encoding="utf-16")
                    raw_sc.setdefault("pins", {})["S"] = xml.decode("utf-16")
                save_buffer(self._buffer_path, self._buffer_raw)
            return

        cid = int(cid_item.text())
        assert self.db is not None
        raw = self.db.get_complex(cid)

        # annotate sub-components with macro names for the adapter
        self._ensure_func_map()
        for sc in getattr(raw, "subcomponents", []) or []:
            setattr(sc, "macro_name", self._func_name(sc.id_function))

        prefill = to_wizard_prefill_from_db(
            raw, self._macro_id_from_name, self._pin_normalizer
        )
        wiz = NewComplexWizard.from_existing(prefill, cid, parent=self)

        if wiz.exec() == QtWidgets.QDialog.DialogCode.Accepted:
            from ..db.mdb_api import SubComponent as DbSubComponent, ComplexDevice as DbComplex

            pin_count = wiz.basics_page.pin_spin.value()
            updated = DbComplex(cid, wiz.basics_page.pn_edit.text(), pin_count, [])
            for sc in wiz.sub_components:
                id_func = getattr(sc.macro, "id_function", None)
                if id_func is None:
                    id_func = self._macro_id_from_name(sc.macro.name) or 0
                pin_map = {chr(ord('A') + i): p for i, p in enumerate(sc.pins)}
                updated.subcomponents.append(
                    DbSubComponent(
                        None,
                        int(id_func),
                        "",
                        None,
                        None,
                        None,
                        None,
                        pin_map,
                    )
                )
            self.db.update_complex(cid, updated=updated)
            self.db._conn.commit()
            self._refresh_list()
            QtWidgets.QMessageBox.information(
                self, "Updated", "Complex updated"
            )

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

    def _load_complex_from_buffer(self) -> None:
        path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self, "Open buffer.json", "", "JSON Files (*.json)"
        )
        if not path:
            return
        try:
            buf = load_complex_from_buffer_json(path)
            prefill = to_wizard_prefill(
                buf, self._macro_id_from_name, self._pin_normalizer
            )
        except Exception as exc:  # pragma: no cover - GUI warning only
            QtWidgets.QMessageBox.warning(self, "Buffer Error", str(exc))
            return
        wiz = NewComplexWizard.from_wizard_prefill(prefill, parent=self)
        wiz.exec()
        if wiz.result() == QtWidgets.QDialog.DialogCode.Accepted:
            pin_count = wiz.basics_page.pin_spin.value()
            dev = ComplexDevice(
                id_function=0,
                pins=[str(i) for i in range(1, pin_count + 1)],
                macro=MacroInstance("", {}),
            )
            dev.subcomponents = wiz.sub_components
            if self.db is not None:
                self.db.add_complex(dev)
                self.db._conn.commit()
                self._refresh_list()
                QtWidgets.QMessageBox.information(
                    self, "Saved", "Complex saved to database"
                )


def run_gui(mdb_file: Path | None = None, buffer_path: Path | None = None) -> None:
    app = QtWidgets.QApplication(sys.argv)
    win = MainWindow(mdb_path=mdb_file, buffer_path=buffer_path)
    win.resize(1100, 600)
    win.show()
    sys.exit(app.exec())
