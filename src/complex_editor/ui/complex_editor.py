from __future__ import annotations

from PyQt6 import QtCore, QtGui, QtWidgets
import pyodbc

from ..domain import (
    ComplexDevice,
    MacroDef,
    MacroInstance,
    parse_param_xml,
)
from ..services import insert_complex
from ..db import make_backup


class ComplexEditor(QtWidgets.QWidget):
    """Form for editing/creating a complex device."""

    dirtyChanged = QtCore.pyqtSignal(bool)

    def __init__(self, macro_map: dict[int, MacroDef] | None = None, parent=None):
        super().__init__(parent)
        self.conn = None
        self.macro_map: dict[int, MacroDef] = macro_map or {}
        self.dirty = False

        layout = QtWidgets.QVBoxLayout(self)
        form = QtWidgets.QFormLayout()
        self.pin_edits = [QtWidgets.QLineEdit() for _ in range(4)]
        regex = QtCore.QRegularExpression("[A-Za-z0-9]+")
        validator = QtGui.QRegularExpressionValidator(regex)
        for i, edit in enumerate(self.pin_edits):
            edit.setValidator(validator)
            form.addRow(f"Pin {chr(65 + i)}", edit)
        self.macro_combo = QtWidgets.QComboBox()
        form.addRow("Macro", self.macro_combo)
        layout.addLayout(form)
        self.param_form = QtWidgets.QFormLayout()
        layout.addLayout(self.param_form)
        self.xml_preview = QtWidgets.QPlainTextEdit()
        self.xml_preview.setReadOnly(True)
        layout.addWidget(self.xml_preview)
        self.save_btn = QtWidgets.QPushButton("Save")
        self.save_btn.setStyleSheet("background:#28a745;color:white")
        layout.addWidget(self.save_btn)

        self.save_btn.clicked.connect(self.save_complex)
        self.macro_combo.currentIndexChanged.connect(self._on_macro_change)
        self.set_macro_map(self.macro_map)

    # ------------------------------------------------------------------ utils
    def set_macro_map(self, macro_map: dict[int, MacroDef]) -> None:
        self.macro_map = macro_map
        self.macro_combo.clear()
        for id_func, macro in sorted(self.macro_map.items()):
            self.macro_combo.addItem(macro.name, id_func)

    def _clear_params(self) -> None:
        while self.param_form.rowCount():
            self.param_form.removeRow(0)
        self.param_widgets: dict[str, QtWidgets.QWidget] = {}

    def _on_macro_change(self) -> None:
        data = self.macro_combo.currentData()
        macro = self.macro_map.get(int(data)) if data is not None else None
        self._build_param_widgets(macro)
        self.on_dirty()

    def _build_param_widgets(self, macro: MacroDef | None) -> None:
        self._clear_params()
        if not macro:
            return
        for param in macro.params:
            label = QtWidgets.QLabel(param.name)
            label.setStyleSheet("background:#C5F1FF")
            if param.type == "INT":
                widget = QtWidgets.QSpinBox()
                if param.min is not None:
                    widget.setMinimum(int(param.min))
                if param.max is not None:
                    widget.setMaximum(int(param.max))
            elif param.type == "FLOAT":
                widget = QtWidgets.QDoubleSpinBox()
                if param.min is not None:
                    widget.setMinimum(float(param.min))
                if param.max is not None:
                    widget.setMaximum(float(param.max))
            elif param.type == "BOOL":
                widget = QtWidgets.QCheckBox()
            elif param.type == "ENUM":
                widget = QtWidgets.QComboBox()
                choices = (param.default or param.min or "").split(";")
                if len(choices) > 1:
                    widget.addItems(choices)
            else:
                widget = QtWidgets.QLineEdit()
            self.param_widgets[param.name] = widget
            self.param_form.addRow(label, widget)
            if isinstance(widget, QtWidgets.QSpinBox):
                widget.valueChanged.connect(self.on_dirty)
            elif isinstance(widget, QtWidgets.QDoubleSpinBox):
                widget.valueChanged.connect(self.on_dirty)
            elif isinstance(widget, QtWidgets.QCheckBox):
                widget.stateChanged.connect(self.on_dirty)
            elif isinstance(widget, QtWidgets.QComboBox):
                widget.currentIndexChanged.connect(self.on_dirty)
            else:
                widget.textChanged.connect(self.on_dirty)

    def _widget_value(self, widget: QtWidgets.QWidget) -> str:
        if isinstance(widget, QtWidgets.QSpinBox):
            return str(widget.value())
        if isinstance(widget, QtWidgets.QDoubleSpinBox):
            return str(widget.value())
        if isinstance(widget, QtWidgets.QCheckBox):
            return "1" if widget.isChecked() else "0"
        if isinstance(widget, QtWidgets.QComboBox):
            return widget.currentText()
        if isinstance(widget, QtWidgets.QLineEdit):
            return widget.text()
        return ""

    # ------------------------------------------------------------------ loading
    def load_complex(self, row) -> None:
        if row is None:
            for edit in self.pin_edits:
                edit.clear()
            macro = None
            if self.macro_combo.count():
                self.macro_combo.setCurrentIndex(0)
                data = self.macro_combo.currentData()
                if data is not None:
                    macro = self.macro_map.get(int(data))
            self._build_param_widgets(macro)
            self.xml_preview.clear()
            self.on_dirty()
            return

        pins = [
            getattr(row, f"Pin{c}", row[i + 2]) if len(row) > i + 2 else None
            for i, c in enumerate("ABCD")
        ]
        for edit, value in zip(self.pin_edits, pins):
            edit.setText(str(value) if value else "")
        id_func = int(getattr(row, "IDFunction", row[1]))
        index = self.macro_combo.findData(id_func)
        if index >= 0:
            self.macro_combo.setCurrentIndex(index)
        macro = self.macro_map.get(id_func)
        self._build_param_widgets(macro)
        pin_s = getattr(row, "PinS", row[6] if len(row) > 6 else None)
        values = parse_param_xml(pin_s) if pin_s else {}
        if macro:
            for p in macro.params:
                w = self.param_widgets.get(p.name)
                if not w:
                    continue
                val = values.get(p.name, p.default)
                if isinstance(w, QtWidgets.QSpinBox):
                    if val is not None:
                        w.setValue(int(val))
                elif isinstance(w, QtWidgets.QDoubleSpinBox):
                    if val is not None:
                        w.setValue(float(val))
                elif isinstance(w, QtWidgets.QCheckBox):
                    w.setChecked(str(val).lower() in ("1", "true", "yes"))
                elif isinstance(w, QtWidgets.QComboBox):
                    if val is not None:
                        idx = w.findText(str(val))
                        if idx >= 0:
                            w.setCurrentIndex(idx)
                        elif w.count() == 0:
                            w.addItem(str(val))
                else:
                    w.setText(str(val) if val else "")
        self.dirty = False
        self.dirtyChanged.emit(False)

    # ------------------------------------------------------------------ dirty
    def on_dirty(self) -> None:
        if not self.dirty:
            self.dirty = True
            self.dirtyChanged.emit(True)

    # ------------------------------------------------------------------- save
    def save_complex(self) -> None:
        if not self.conn:
            QtWidgets.QMessageBox.warning(self, "Error", "No database open")
            return
        pins = [e.text().strip() for e in self.pin_edits]
        pins = [p for p in pins if p]
        if len(set(pins)) < 2:
            QtWidgets.QMessageBox.warning(
                self, "Error", "At least two unique pins required"
            )
            return
        data = self.macro_combo.currentData()
        if data is None:
            QtWidgets.QMessageBox.warning(self, "Error", "No macro selected")
            return
        id_func = int(data)
        macro_name = self.macro_combo.currentText()
        params = {n: self._widget_value(w) for n, w in self.param_widgets.items()}
        device = ComplexDevice(
            id_function=id_func, pins=pins, macro=MacroInstance(macro_name, params)
        )
        db_path = self.conn.getinfo(pyodbc.SQL_DATABASE_NAME)
        bak = make_backup(db_path)
        try:
            new_id = insert_complex(self.conn, device)
        except Exception as exc:  # pragma: no cover - error path
            QtWidgets.QMessageBox.warning(self, "Error", str(exc))
            return
        self.dirty = False
        self.dirtyChanged.emit(False)
        parent = self.parent()
        if parent and hasattr(parent, "list_panel"):
            parent.list_panel.load_rows(parent.cursor, parent.macro_map)
        QtWidgets.QMessageBox.information(
            self, "Saved", f"Inserted {new_id}\nBackup: {bak}"
        )
