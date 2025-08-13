from __future__ import annotations

from typing import Dict
from PyQt6 import QtWidgets


class SubcomponentEditor(QtWidgets.QDialog):
    """Minimal dialog for editing a subcomponent's macro and pins."""

    def __init__(
        self,
        macro_choices: list[str],
        *,
        macro: str = "",
        pins: Dict[str, str] | None = None,
        parent: QtWidgets.QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Subcomponent")

        form = QtWidgets.QFormLayout(self)

        self.macro_combo = QtWidgets.QComboBox()
        self.macro_combo.setEditable(True)
        self.macro_combo.addItems(sorted(macro_choices))
        self.macro_combo.setCurrentText(macro)
        form.addRow("Macro", self.macro_combo)

        self.pin_edits: Dict[str, QtWidgets.QLineEdit] = {}
        for name in list("ABCDEFGH") + ["S"]:
            edit = QtWidgets.QLineEdit()
            if pins and name in pins:
                edit.setText(str(pins[name]))
            form.addRow(f"Pin {name}", edit)
            self.pin_edits[name] = edit

        btns = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.StandardButton.Ok
            | QtWidgets.QDialogButtonBox.StandardButton.Cancel
        )
        self.ok_btn = btns.button(QtWidgets.QDialogButtonBox.StandardButton.Ok)
        self.ok_btn.setEnabled(bool(self.macro_combo.currentText().strip()))
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        form.addRow(btns)

        self.macro_combo.editTextChanged.connect(
            lambda text: self.ok_btn.setEnabled(bool(text.strip()))
        )

    def get_result(self) -> tuple[str, Dict[str, str]] | None:
        if self.result() != QtWidgets.QDialog.DialogCode.Accepted:
            return None
        macro = self.macro_combo.currentText().strip()
        pins: Dict[str, str] = {}
        for name, edit in self.pin_edits.items():
            val = edit.text().strip()
            if val:
                pins[name] = val
        return macro, pins
