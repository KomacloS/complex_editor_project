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
        layout = QtWidgets.QGridLayout(self)
        self._widgets: dict[str, QtWidgets.QWidget] = {}

        params = list(macro.params)
        row_count = 0
        if params:
            mid = (len(params) + 1) // 2
            left = params[:mid]
            right = params[mid:]
            ordered = list(left) + list(right)
            for idx, p in enumerate(ordered):
                if idx < len(left):
                    row = idx
                    col = 0
                else:
                    row = idx - len(left)
                    col = 1
                w: QtWidgets.QWidget
                if p.type == "INT":
                    w = QtWidgets.QSpinBox()
                    # QSpinBox only supports 32-bit signed integers. Some macros
                    # specify values outside this range which would otherwise raise
                    # an ``OverflowError`` when passed to ``setMinimum``/``setMaximum``.
                    # Clamp to the valid range to keep the dialog usable even with
                    # overly large macro definitions.
                    min_val = int(p.min or 0)
                    max_val = int(p.max or 1_000_000)
                    INT_MIN, INT_MAX = -2**31, 2**31 - 1
                    min_val = max(min_val, INT_MIN)
                    max_val = min(max_val, INT_MAX)
                    if min_val > max_val:
                        min_val = max_val
                    w.setMinimum(min_val)
                    w.setMaximum(max_val)
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
                label = QtWidgets.QLabel(p.name)
                layout.addWidget(label, row, col * 2)
                layout.addWidget(w, row, col * 2 + 1)
                self._widgets[p.name] = w
            row_count = max(len(left), len(right))

        # Fallback: no schema but values exist -> render simple line edits
        if not params and values:
            items = list(values.items())
            mid = (len(items) + 1) // 2
            left = items[:mid]
            right = items[mid:]
            ordered = list(left) + list(right)
            for idx, (pname, pval) in enumerate(ordered):
                if idx < len(left):
                    row = idx
                    col = 0
                else:
                    row = idx - len(left)
                    col = 1
                w = QtWidgets.QLineEdit()
                w.setText(str(pval))
                label = QtWidgets.QLabel(pname)
                layout.addWidget(label, row, col * 2)
                layout.addWidget(w, row, col * 2 + 1)
                self._widgets[pname] = w
            row_count = max(len(left), len(right))

        buttons = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.StandardButton.Ok
            | QtWidgets.QDialogButtonBox.StandardButton.Cancel,
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons, row_count, 0, 1, 4)
        if values:
            self.set_values(values)

    # ------------------------------------------------------------------
    def set_values(self, values: Dict[str, str]) -> None:
        for name, val in values.items():
            w = self._widgets.get(name)
            if w is None:
                continue
            if isinstance(w, QtWidgets.QSpinBox):
                try:
                    w.setValue(int(val))
                except ValueError:
                    # Some legacy macros store non-integer defaults for INT
                    # parameters.  Coerce through float to avoid crashing the
                    # editor when such values are encountered.
                    try:
                        w.setValue(int(float(val)))
                    except ValueError:
                        continue
            elif isinstance(w, QtWidgets.QDoubleSpinBox):
                try:
                    w.setValue(float(val))
                except ValueError:
                    continue
            elif isinstance(w, QtWidgets.QCheckBox):
                w.setChecked(str(val).lower() in {"1", "true", "yes"})
            elif isinstance(w, QtWidgets.QComboBox):
                idx = w.findText(str(val))
                if idx < 0:
                    w.addItem(str(val))
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
