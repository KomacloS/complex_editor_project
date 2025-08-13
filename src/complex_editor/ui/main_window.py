from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

from PyQt6 import QtWidgets

from ..core.app_context import AppContext
from ..domain import ComplexDevice, MacroInstance
from ..db.mdb_api import MDB
from ..db import schema_introspect
from .complex_editor import ComplexEditor
from .new_complex_wizard import NewComplexWizard


class MainWindow(QtWidgets.QMainWindow):
    """Main window showing complexes from the MDB."""

    def __init__(self, mdb_path: Path, parent: Any | None = None) -> None:
        super().__init__(parent)
        self.ctx = AppContext()
        self.db: MDB = self.ctx.open_main_db(mdb_path)

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

        # right table with sub components
        self.sub_table = QtWidgets.QTableWidget(0, 0)

        new_btn = QtWidgets.QPushButton("New Complex")
        new_btn.clicked.connect(self._new_complex)
        edit_btn = QtWidgets.QPushButton("Edit")
        edit_btn.clicked.connect(self._on_edit)
        del_btn = QtWidgets.QPushButton("Delete")
        del_btn.clicked.connect(self._delete_selected)

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
    def _refresh_list(self) -> None:
        rows = self.db.list_complexes()
        self.list.setRowCount(len(rows))
        for r, row in enumerate(rows):
            if len(row) == 3:
                cid, name, nsubs = row
            else:
                cid, name, _func, nsubs = row
            self.list.setItem(r, 0, QtWidgets.QTableWidgetItem(str(cid)))
            self.list.setItem(r, 1, QtWidgets.QTableWidgetItem(str(name)))
            self.list.setItem(r, 2, QtWidgets.QTableWidgetItem(str(nsubs)))

    def _refresh_subcomponents(self, cid: int) -> None:
        try:
            subs = self.db.list_subcomponents(cid)  # type: ignore[attr-defined]
        except AttributeError:
            cx = self.db.get_complex(cid)
            subs = [
                {
                    "IDFunction": sc.id_function,
                    "Value": sc.value,
                    "Pins": ",".join(
                        f"{k}:{v}" for k, v in (sc.pins or {}).items()
                    ),
                }
                for sc in cx.subcomponents
            ]

        if not subs:
            self.sub_table.setRowCount(0)
            self.sub_table.setColumnCount(0)
            return

        headers = list(subs[0].keys())
        self.sub_table.setColumnCount(len(headers))
        self.sub_table.setHorizontalHeaderLabels([str(h) for h in headers])
        self.sub_table.setRowCount(len(subs))
        for r, row in enumerate(subs):
            for c, key in enumerate(headers):
                val = str(row.get(key, ""))
                self.sub_table.setItem(r, c, QtWidgets.QTableWidgetItem(val))

    def _on_selected(self) -> None:
        row = self.list.currentRow()
        if row < 0:
            self.sub_table.setRowCount(0)
            self.sub_table.setColumnCount(0)
            return
        cid_item = self.list.item(row, 0)
        if cid_item is None:
            return
        self._refresh_subcomponents(int(cid_item.text()))

    # ------------------------------------------------------------------ actions
    def _new_complex(self) -> None:
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
        cid = int(cid_item.text())
        raw = self.db.get_complex(cid)

        total = getattr(raw, "total_pins", 0) or 0
        pins_list = [str(i) for i in range(1, total + 1)]
        dom = raw
        if not hasattr(raw, "pins"):
            class _DomWrapper:  # noqa: D401 - simple attribute bag
                pass

            dom = _DomWrapper()
            dom.id_comp_desc = raw.id_comp_desc
            dom.name = raw.name
            dom.total_pins = total
            dom.subcomponents = raw.subcomponents
            dom.pins = pins_list

        cursor = self.db._conn.cursor()
        macro_map = schema_introspect.discover_macro_map(cursor) or {}
        dlg = ComplexEditor(macro_map)
        dlg.load_from_model(dom)
        if dlg.exec() == QtWidgets.QDialog.DialogCode.Accepted:
            try:
                updates = dlg.to_update_dict()
            except ValueError as exc:  # pragma: no cover - user error path
                QtWidgets.QMessageBox.warning(self, "Invalid", str(exc))
                return
            self.db.update_complex(cid, **updates)
            self.db._conn.commit()
            self._refresh_list()

    def _delete_selected(self) -> None:
        row = self.list.currentRow()
        if row < 0:
            return
        cid = int(self.list.item(row, 0).text())
        if (
            QtWidgets.QMessageBox.question(self, "Delete?", f"Delete complex {cid}?")
            == QtWidgets.QMessageBox.StandardButton.Yes
        ):
            self.db.delete_complex(cid, cascade=True)
            self.db._conn.commit()
            self._refresh_list()


def run_gui(mdb_file: Path) -> None:
    app = QtWidgets.QApplication(sys.argv)
    win = MainWindow(mdb_file)
    win.resize(1000, 600)
    win.show()
    sys.exit(app.exec())

