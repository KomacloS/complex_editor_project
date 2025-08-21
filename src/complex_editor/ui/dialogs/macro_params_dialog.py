from __future__ import annotations

from typing import Dict

from PyQt6 import QtWidgets

from ...domain import MacroDef, MacroParam


class MacroParamsDialog(QtWidgets.QDialog):
    """Dialog that renders editors for each parameter in a MacroDef."""

    def __init__(
        self,
        macro: MacroDef,
        values: Dict[str, str] | None = None,
        parent: QtWidgets.QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Macro Parameters")
        self._macro = macro
        self._widgets: Dict[str, QtWidgets.QWidget] = {}

        layout = QtWidgets.QVBoxLayout(self)
        form = QtWidgets.QFormLayout()
        layout.addLayout(form)

        for param in macro.params:
            label = QtWidgets.QLabel(param.name)
            widget: QtWidgets.QWidget
            if param.type == "INT":
                sb = QtWidgets.QSpinBox()
                if param.min is not None:
                    sb.setMinimum(int(param.min))
                if param.max is not None:
                    sb.setMaximum(int(param.max))
                widget = sb
            elif param.type == "FLOAT":
                dsb = QtWidgets.QDoubleSpinBox()
                if param.min is not None:
                    dsb.setMinimum(float(param.min))
                if param.max is not None:
                    dsb.setMaximum(float(param.max))
                widget = dsb
            elif param.type == "BOOL":
                widget = QtWidgets.QCheckBox()
            elif param.type == "ENUM":
                cb = QtWidgets.QComboBox()
                choices = (param.default or "").split(";")
                cb.addItems([c for c in choices if c])
                widget = cb
            else:
                widget = QtWidgets.QLineEdit()
            form.addRow(label, widget)
            self._widgets[param.name] = widget

        if values:
            for name, val in values.items():
                w = self._widgets.get(name)
                if isinstance(w, QtWidgets.QSpinBox):
                    w.setValue(int(val))
                elif isinstance(w, QtWidgets.QDoubleSpinBox):
                    w.setValue(float(val))
                elif isinstance(w, QtWidgets.QCheckBox):
                    w.setChecked(val in {"1", "true", "True"})
                elif isinstance(w, QtWidgets.QComboBox):
                    idx = w.findText(str(val))
                    if idx >= 0:
                        w.setCurrentIndex(idx)
                elif isinstance(w, QtWidgets.QLineEdit):
                    w.setText(str(val))

        buttons = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.StandardButton.Ok
            | QtWidgets.QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _on_accept(self) -> None:
        self._result: Dict[str, str] = {}
        for name, w in self._widgets.items():
            if isinstance(w, QtWidgets.QSpinBox):
                self._result[name] = str(w.value())
            elif isinstance(w, QtWidgets.QDoubleSpinBox):
                self._result[name] = str(w.value())
            elif isinstance(w, QtWidgets.QCheckBox):
                self._result[name] = "1" if w.isChecked() else "0"
            elif isinstance(w, QtWidgets.QComboBox):
                self._result[name] = w.currentText()
            elif isinstance(w, QtWidgets.QLineEdit):
                self._result[name] = w.text()
        self.accept()

    # ------------------------------------------------------------------ API
    def values(self) -> Dict[str, str]:
        return getattr(self, "_result", {})
