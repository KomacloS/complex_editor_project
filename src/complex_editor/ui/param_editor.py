from __future__ import annotations

"""Simple dialog for editing macro parameters."""

from typing import Dict, Mapping
from PyQt6 import QtWidgets, QtCore


class MacroParamsDialog(QtWidgets.QDialog):
    """Dialog allowing users to edit a mapping of ``{name: value}`` pairs."""

    def __init__(self, params: Mapping[str, float] | None = None, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Macro Parameters")
        layout = QtWidgets.QVBoxLayout(self)

        self.table = QtWidgets.QTableWidget(0, 2)
        self.table.setHorizontalHeaderLabels(["Param", "Value"])
        self.table.horizontalHeader().setStretchLastSection(True)
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
    def set_params(self, params: Dict[str, float]) -> None:
        self.table.setRowCount(0)
        for key, val in params.items():
            r = self.table.rowCount()
            self.table.insertRow(r)
            self.table.setItem(r, 0, QtWidgets.QTableWidgetItem(str(key)))
            self.table.setCellWidget(r, 1, self._spinbox(val))

    def params(self) -> Dict[str, float]:
        result: Dict[str, float] = {}
        for r in range(self.table.rowCount()):
            k_item = self.table.item(r, 0)
            key = k_item.text().strip() if k_item else ""
            val: float | None = None
            widget = self.table.cellWidget(r, 1)
            if isinstance(widget, QtWidgets.QDoubleSpinBox):
                val = widget.value()
            else:
                v_item = self.table.item(r, 1)
                if v_item is not None:
                    try:
                        val = float(v_item.text())
                    except ValueError:
                        val = None
            if key and val is not None:
                result[key] = val
        return result

    # ----------------------------------------------------------------- callbacks
    def _add_row(self) -> None:
        r = self.table.rowCount()
        self.table.insertRow(r)
        self.table.setCellWidget(r, 1, self._spinbox())
        self.table.setItem(r, 0, QtWidgets.QTableWidgetItem(""))

    def _remove_row(self) -> None:
        row = self.table.currentRow()
        if row >= 0:
            self.table.removeRow(row)

    # --------------------------------------------------------------- internals
    def _spinbox(self, val: float | None = None) -> QtWidgets.QDoubleSpinBox:
        box = QtWidgets.QDoubleSpinBox()
        box.setRange(-1e9, 1e9)
        box.setDecimals(6)
        box.setSingleStep(0.1)
        box.setFocusPolicy(QtCore.Qt.FocusPolicy.StrongFocus)
        if val is not None:
            try:
                box.setValue(float(val))
            except ValueError:
                box.setValue(0.0)
        return box
