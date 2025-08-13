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
from .new_complex_wizard import NewComplexWizard
from .subcomponent_editor import SubcomponentEditor
from .buffer_ops import (
    load_buffer,
    save_buffer,
    get_all_macro_choices,
    format_pins_for_table,
    apply_add_sub,
    apply_edit_sub,
    apply_delete_sub,
)


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

        self.buffer_mode = buffer_path is not None
        self.buffer_path: Path | None = buffer_path
        self.buffer_data: Dict[str, Any] | None = None
        self._current_buffer_complex: Dict[str, Any] | None = None

        if self.buffer_mode:
            if buffer_path is None:
                raise ValueError("buffer_path must be provided in buffer mode")
            self.buffer_data = load_buffer(buffer_path)
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

        if self.buffer_mode:
            new_btn.setEnabled(False)
            del_btn.setEnabled(False)

        toolbar = QtWidgets.QHBoxLayout()
        toolbar.addWidget(new_btn)
        toolbar.addWidget(edit_btn)
        toolbar.addWidget(del_btn)
        toolbar.addStretch()

        left = QtWidgets.QVBoxLayout()
        left.addLayout(toolbar)
        left.addWidget(self.list)

        # subcomponent toolbar (buffer mode)
        self.add_sub_btn = QtWidgets.QPushButton("Add Sub")
        self.add_sub_btn.clicked.connect(self._on_add_subcomponent_buffer)
        self.edit_sub_btn = QtWidgets.QPushButton("Edit Sub")
        self.edit_sub_btn.clicked.connect(self._on_edit_subcomponent_buffer)
        self.del_sub_btn = QtWidgets.QPushButton("Delete Sub")
        self.del_sub_btn.clicked.connect(self._on_delete_subcomponent_buffer)
        self.save_buf_btn = QtWidgets.QPushButton("Save Buffer")
        self.save_buf_btn.clicked.connect(self._on_save_buffer)

        if not self.buffer_mode:
            for b in [self.add_sub_btn, self.edit_sub_btn, self.del_sub_btn, self.save_buf_btn]:
                b.setEnabled(False)

        sub_toolbar = QtWidgets.QHBoxLayout()
        sub_toolbar.addWidget(self.add_sub_btn)
        sub_toolbar.addWidget(self.edit_sub_btn)
        sub_toolbar.addWidget(self.del_sub_btn)
        sub_toolbar.addWidget(self.save_buf_btn)
        sub_toolbar.addStretch()

        right = QtWidgets.QVBoxLayout()
        right.addLayout(sub_toolbar)
        right.addWidget(self.sub_table)

        container = QtWidgets.QWidget()
        layout = QtWidgets.QHBoxLayout(container)
        layout.addLayout(left)
        layout.addLayout(right)
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

    def _refresh_list(self) -> None:
        if self.buffer_mode and self.buffer_data is not None:
            rows = self.buffer_data.get("complexes", [])
            self.list.setRowCount(len(rows))
            for r, cx in enumerate(rows):
                self.list.setItem(r, 0, QtWidgets.QTableWidgetItem(str(cx.get("id", ""))))
                self.list.setItem(r, 1, QtWidgets.QTableWidgetItem(str(cx.get("name", ""))))
                subs = cx.get("subcomponents") or []
                self.list.setItem(r, 2, QtWidgets.QTableWidgetItem(str(len(subs))))
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

    def _refresh_subcomponents_from_buffer(self, cx: Dict[str, Any]) -> None:
        """Fill the right table with subcomponents from a buffer."""
        display_rows: List[Dict[str, str]] = []
        for sc in cx.get("subcomponents", []) or []:
            pins_str = format_pins_for_table(sc.get("pins") or {})
            display_rows.append(
                {
                    "ID": str(sc.get("id", "")),
                    "Macro": str(sc.get("function_name", "")),
                    "Pins": pins_str,
                }
            )

        if not display_rows:
            self.sub_table.setRowCount(0)
            self.sub_table.setColumnCount(0)
            return

        headers = ["ID", "Macro", "Pins"]
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
        if self.buffer_mode and self.buffer_data is not None:
            complexes = self.buffer_data.get("complexes", [])
            if 0 <= row < len(complexes):
                self._current_buffer_complex = complexes[row]
                self._refresh_subcomponents_from_buffer(self._current_buffer_complex)
            return

        cid_item = self.list.item(row, 0)
        if cid_item is None:
            return
        self._refresh_subcomponents_db(int(cid_item.text()))

    # ------------------------------------------------------------------ actions
    def _new_complex(self) -> None:
        if self.buffer_mode:
            return
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
        if self.buffer_mode:
            return
        row = self.list.currentRow()
        if row < 0:
            return
        cid_item = self.list.item(row, 0)
        if cid_item is None:
            return

        cid = int(cid_item.text())
        assert self.db is not None
        raw = self.db.get_complex(cid)

        # Top-level pins list (1..TotalPinNumber)
        total = int(getattr(raw, "total_pins", 0) or 0)
        pins_list = [str(i) for i in range(1, total + 1)]

        # Wrap to the shape ComplexEditor expects:
        # - .pins: List[str]
        # - .macro: MacroInstance (name used by header)
        # - .subcomponents: List[MacroInstance] (name + pins mapping)
        class _DomWrapper:
            pass

        dom = _DomWrapper()
        dom.id_comp_desc = getattr(raw, "id_comp_desc", None)
        dom.name = getattr(raw, "name", "")
        dom.total_pins = total
        dom.pins = pins_list
        dom.id_function = 0
        dom.macro = MacroInstance("(from DB)", {})  # placeholder top macro

        # convert every DB subcomponent to a MacroInstance that carries
        # the chosen macro (by *name*) and the assigned pin map
        self._ensure_func_map()
        sub_macros: List[MacroInstance] = []
        for sc in getattr(raw, "subcomponents", []) or []:
            macro_name = self._func_name(sc.id_function)
            pin_map = {str(k): str(v) for k, v in (sc.pins or {}).items()}
            sub_macros.append(MacroInstance(macro_name, pin_map))
        dom.subcomponents = sub_macros

        # Editor also likes having a macro definition map (by ID) for validation.
        cursor = self.db._conn.cursor()
        macro_map = schema_introspect.discover_macro_map(cursor) or {}

        dlg = ComplexEditor(macro_map)
        dlg.load_from_model(dom)

        if dlg.exec() == QtWidgets.QDialog.DialogCode.Accepted:
            try:
                updates = dlg.to_update_dict()
            except ValueError as exc:
                QtWidgets.QMessageBox.warning(self, "Invalid", str(exc))
                return
            # NOTE: wiring the "save back to MDB" will be done in the next step
            # when we add the reverse adapter (GUI -> DB).
            self.db.update_complex(cid, **updates)
            self.db._conn.commit()
            self._refresh_list()

    def _delete_selected(self) -> None:
        if self.buffer_mode:
            return
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

    # ------------------------------------------------------------------ buffer ops
    def _on_add_subcomponent_buffer(self) -> None:
        if not self.buffer_mode or self.buffer_data is None or self._current_buffer_complex is None:
            return
        dlg = SubcomponentEditor(get_all_macro_choices(self.buffer_data))
        if dlg.exec() == QtWidgets.QDialog.DialogCode.Accepted:
            result = dlg.get_result()
            if result:
                macro, pins = result
                apply_add_sub(
                    self.buffer_data, self._current_buffer_complex["id"], macro, pins
                )
                self._refresh_subcomponents_from_buffer(self._current_buffer_complex)
                self._refresh_list()

    def _on_edit_subcomponent_buffer(self) -> None:
        if not self.buffer_mode or self.buffer_data is None or self._current_buffer_complex is None:
            return
        row = self.sub_table.currentRow()
        subs = self._current_buffer_complex.get("subcomponents", [])
        if row < 0 or row >= len(subs):
            return
        sc = subs[row]
        dlg = SubcomponentEditor(
            get_all_macro_choices(self.buffer_data),
            macro=str(sc.get("function_name", "")),
            pins=sc.get("pins") or {},
        )
        if dlg.exec() == QtWidgets.QDialog.DialogCode.Accepted:
            result = dlg.get_result()
            if result:
                macro, pins = result
                apply_edit_sub(
                    self.buffer_data,
                    self._current_buffer_complex["id"],
                    sc.get("id", 0),
                    macro,
                    pins,
                )
                self._refresh_subcomponents_from_buffer(self._current_buffer_complex)
                self._refresh_list()

    def _on_delete_subcomponent_buffer(self) -> None:
        if not self.buffer_mode or self.buffer_data is None or self._current_buffer_complex is None:
            return
        row = self.sub_table.currentRow()
        subs = self._current_buffer_complex.get("subcomponents", [])
        if row < 0 or row >= len(subs):
            return
        sc = subs[row]
        sub_id = sc.get("id")
        if (
            QtWidgets.QMessageBox.question(
                self, "Delete?", f"Delete subcomponent {sub_id}?"
            )
            == QtWidgets.QMessageBox.StandardButton.Yes
        ):
            apply_delete_sub(
                self.buffer_data, self._current_buffer_complex["id"], sub_id
            )
            self._refresh_subcomponents_from_buffer(self._current_buffer_complex)
            self._refresh_list()

    def _on_save_buffer(self) -> None:
        if not self.buffer_mode or self.buffer_data is None or self.buffer_path is None:
            return
        save_buffer(self.buffer_path, self.buffer_data)
        QtWidgets.QMessageBox.information(
            self, "Saved", f"Buffer saved to {self.buffer_path}"
        )


def run_gui(mdb_file: Path | None = None, buffer_path: Path | None = None) -> None:
    app = QtWidgets.QApplication(sys.argv)
    win = MainWindow(mdb_path=mdb_file, buffer_path=buffer_path)
    win.resize(1100, 600)
    win.show()
    sys.exit(app.exec())
