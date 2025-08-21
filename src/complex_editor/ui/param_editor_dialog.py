from __future__ import annotations

"""Dialog used to edit macro parameters."""

from typing import Dict
from PyQt6 import QtWidgets

from ..domain import MacroDef, MacroParam


class ParamEditorDialog(QtWidgets.QDialog):
    """Create a dialog populated from a :class:`MacroDef`.

    Each parameter is represented by an appropriate Qt widget.  Upon
    acceptance the :meth:`params` method returns a mapping of
    ``{param_name: value}`` pairs using string values.
    """

    def __init__(self, macro: MacroDef, values: Dict[str, str] | None = None, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"Parameters - {macro.name}")
        self._macro = macro
        layout = QtWidgets.QFormLayout(self)
        self._widgets: dict[str, QtWidgets.QWidget] = {}
        for p in macro.params:
            w: QtWidgets.QWidget
            if p.type == "INT":
                w = QtWidgets.QSpinBox()
                w.setMinimum(int(p.min or 0))
                w.setMaximum(int(p.max or 1_000_000))
            elif p.type == "FLOAT":
                w = QtWidgets.QDoubleSpinBox()
                w.setMinimum(float(p.min or 0.0))
                w.setMaximum(float(p.max or 1e9))
            elif p.type == "BOOL":
                w = QtWidgets.QCheckBox()
            elif p.type == "ENUM":
                w = QtWidgets.QComboBox()
                for choice in (p.default or "").split(";"):
                    if choice:
                        w.addItem(choice)
            else:
                w = QtWidgets.QLineEdit()
            layout.addRow(p.name, w)
            self._widgets[p.name] = w
        buttons = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.StandardButton.Ok
            | QtWidgets.QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addRow(buttons)
        if values:
            self.set_values(values)

    # ------------------------------------------------------------------
    def set_values(self, values: Dict[str, str]) -> None:
        for name, val in values.items():
            w = self._widgets.get(name)
            if w is None:
                continue
            if isinstance(w, QtWidgets.QSpinBox):
                w.setValue(int(val))
            elif isinstance(w, QtWidgets.QDoubleSpinBox):
                w.setValue(float(val))
            elif isinstance(w, QtWidgets.QCheckBox):
                w.setChecked(str(val).lower() in {"1", "true", "yes"})
            elif isinstance(w, QtWidgets.QComboBox):
                idx = w.findText(str(val))
                if idx >= 0:
                    w.setCurrentIndex(idx)
            else:
                w.setText(str(val))

    def params(self) -> Dict[str, str]:
        result: Dict[str, str] = {}
        for name, w in self._widgets.items():
            if isinstance(w, QtWidgets.QSpinBox):
                result[name] = str(w.value())
            elif isinstance(w, QtWidgets.QDoubleSpinBox):
                result[name] = str(w.value())
            elif isinstance(w, QtWidgets.QCheckBox):
                result[name] = "1" if w.isChecked() else "0"
            elif isinstance(w, QtWidgets.QComboBox):
                result[name] = w.currentText()
            else:
                result[name] = w.text()
        return result
