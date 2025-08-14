from __future__ import annotations

"""Simple dialog for editing macro parameters."""

from typing import Dict, Mapping
from PyQt6 import QtWidgets


class MacroParamsDialog(QtWidgets.QDialog):
    """Dialog allowing users to edit a mapping of ``{name: value}`` pairs."""

    def __init__(self, params: Mapping[str, str] | None = None, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Macro Parameters")
        layout = QtWidgets.QVBoxLayout(self)

        self.table = QtWidgets.QTableWidget(0, 2)
        self.table.setHorizontalHeaderLabels(["Param", "Value"])
        layout.addWidget(self.table)

        btn_layout = QtWidgets.QHBoxLayout()
        add_btn = QtWidgets.QPushButton("Add")
        rm_btn = QtWidgets.QPushButton("Remove")
        btn_layout.addWidget(add_btn)
        btn_layout.addWidget(rm_btn)
        btn_layout.addStretch()
        layout.addLayout(btn_layout)

        add_btn.clicked.connect(self._add_row)
        rm_btn.clicked.connect(self._remove_row)

        buttons = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.StandardButton.Ok
            | QtWidgets.QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        if params:
            self.set_params(dict(params))

    # ------------------------------------------------------------------ helpers
    def set_params(self, params: Dict[str, str]) -> None:
        self.table.setRowCount(0)
        for key, val in params.items():
            r = self.table.rowCount()
            self.table.insertRow(r)
            self.table.setItem(r, 0, QtWidgets.QTableWidgetItem(str(key)))
            self.table.setItem(r, 1, QtWidgets.QTableWidgetItem(str(val)))

    def params(self) -> Dict[str, str]:
        result: Dict[str, str] = {}
        for r in range(self.table.rowCount()):
            k_item = self.table.item(r, 0)
            v_item = self.table.item(r, 1)
            key = k_item.text().strip() if k_item else ""
            val = v_item.text() if v_item else ""
            if key:
                result[key] = val
        return result

    # ----------------------------------------------------------------- callbacks
    def _add_row(self) -> None:
        self.table.insertRow(self.table.rowCount())

    def _remove_row(self) -> None:
        row = self.table.currentRow()
        if row >= 0:
            self.table.removeRow(row)
