"""Dialog used to edit macro parameters."""

from __future__ import annotations

from typing import Dict
from PyQt6 import QtWidgets

from ..domain import MacroDef


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
        self._present_keys = set(values.keys()) if values else set()
        self._changed_keys = set(self._present_keys)

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
                    w.setButtonSymbols(QtWidgets.QAbstractSpinBox.ButtonSymbols.NoButtons)
                elif p.type == "FLOAT":
                    w = QtWidgets.QDoubleSpinBox()
                    w.setMinimum(float(p.min or 0.0))
                    w.setMaximum(float(p.max or 1e9))
                    w.setButtonSymbols(QtWidgets.QAbstractSpinBox.ButtonSymbols.NoButtons)
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
                if isinstance(w, QtWidgets.QSpinBox):
                    w.valueChanged.connect(lambda _=0, n=p.name, d=p.default: self._on_param_changed(n, d))
                elif isinstance(w, QtWidgets.QDoubleSpinBox):
                    w.valueChanged.connect(lambda _=0, n=p.name, d=p.default: self._on_param_changed(n, d))
                elif isinstance(w, QtWidgets.QCheckBox):
                    w.stateChanged.connect(lambda _=0, n=p.name, d=p.default: self._on_param_changed(n, d))
                elif isinstance(w, QtWidgets.QComboBox):
                    w.currentTextChanged.connect(lambda _=0, n=p.name, d=p.default: self._on_param_changed(n, d))
                else:
                    w.textChanged.connect(lambda _="", n=p.name, d=p.default: self._on_param_changed(n, d))
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
                w.textChanged.connect(lambda _="", n=pname: self._on_param_changed(n))
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
        for name in self._present_keys:
            self._set_changed_style(name, True)

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

    def params(self, *, only_changed: bool = True) -> Dict[str, str]:
        """Return a mapping of parameter names to values.

        Parameters that differ from their defaults (or were explicitly
        provided in ``values``) are considered *changed*.  Only these
        parameters are returned by default.  Pass ``only_changed=False``
        to retrieve all values regardless of modification state.
        """

        result: Dict[str, str] = {}
        for name, w in self._widgets.items():
            if only_changed and name not in self._changed_keys:
                continue
            result[name] = self._string_value(w)
        return result

    # --------------------------------------------------------------- helpers
    def _string_value(self, w: QtWidgets.QWidget) -> str:
        if isinstance(w, QtWidgets.QSpinBox):
            return str(w.value())
        if isinstance(w, QtWidgets.QDoubleSpinBox):
            return str(w.value())
        if isinstance(w, QtWidgets.QCheckBox):
            return "1" if w.isChecked() else "0"
        if isinstance(w, QtWidgets.QComboBox):
            return w.currentText()
        return w.text()

    def _set_changed_style(self, name: str, on: bool) -> None:
        w = self._widgets.get(name)
        if not w:
            return
        w.setStyleSheet("background:#C5F1FF" if on else "")

    def _on_param_changed(self, name: str, default: str | None = None) -> None:
        w = self._widgets[name]
        val = self._string_value(w)
        changed = (name in self._present_keys) or (default not in (None, "", val) and val != (default or ""))
        self._set_changed_style(name, changed)
        if changed:
            self._changed_keys.add(name)
        else:
            self._changed_keys.discard(name)
