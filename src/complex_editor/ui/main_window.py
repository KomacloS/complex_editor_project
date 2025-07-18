from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

from PyQt6 import QtWidgets

from ..core.app_context import AppContext
from ..domain import ComplexDevice, MacroInstance
from ..db.mdb_api import MDB
from .complex_editor import ComplexEditor
from .new_complex_wizard import NewComplexWizard


class MainWindow(QtWidgets.QMainWindow):
    """Main window showing complexes from the MDB."""

    def __init__(self, mdb_path: Path, parent: Any | None = None) -> None:
        super().__init__(parent)
        self.ctx = AppContext()
        self.db: MDB = self.ctx.open_main_db(mdb_path)

        self.list = QtWidgets.QTableWidget(0, 4)
        self.list.setHorizontalHeaderLabels(["ID", "Name", "#Sub", "Function"])
        self.list.doubleClicked.connect(self._edit_selected)

        new_btn = QtWidgets.QPushButton("New Complex")
        new_btn.clicked.connect(self._new_complex)
        del_btn = QtWidgets.QPushButton("Delete")
        del_btn.clicked.connect(self._delete_selected)

        toolbar = QtWidgets.QHBoxLayout()
        toolbar.addWidget(new_btn)
        toolbar.addWidget(del_btn)
        toolbar.addStretch()

        left = QtWidgets.QVBoxLayout()
        left.addLayout(toolbar)
        left.addWidget(self.list)

        container = QtWidgets.QWidget()
        layout = QtWidgets.QHBoxLayout(container)
        layout.addLayout(left)
        self.setCentralWidget(container)

        self._refresh_list()

    # ------------------------------------------------------------------ helpers
    def _refresh_list(self) -> None:
        rows = self.db.list_complexes()
        self.list.setRowCount(len(rows))
        for r, (cid, name, func, nsubs) in enumerate(rows):
            self.list.setItem(r, 0, QtWidgets.QTableWidgetItem(str(cid)))
            self.list.setItem(r, 1, QtWidgets.QTableWidgetItem(name))
            self.list.setItem(r, 2, QtWidgets.QTableWidgetItem(str(nsubs)))
            self.list.setItem(r, 3, QtWidgets.QTableWidgetItem(func))

    # ------------------------------------------------------------------ actions
    def _new_complex(self) -> None:
        wiz = NewComplexWizard(self.db.discover_macro_map())
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

    def _edit_selected(self) -> None:
        row = self.list.currentRow()
        if row < 0:
            return
        cid = int(self.list.item(row, 0).text())
        cx = self.db.get_complex(cid)
        dlg = ComplexEditor(self.db.discover_macro_map())
        dlg.load_from_model(cx)
        if dlg.exec() == QtWidgets.QDialog.DialogCode.Accepted:
            try:
                updates = dlg.to_update_dict()
            except ValueError as exc:
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
