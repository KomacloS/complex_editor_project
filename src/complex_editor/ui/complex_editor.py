from __future__ import annotations

from typing import Any, Dict

from PyQt6 import QtCore, QtWidgets

from ..domain import ComplexDevice, MacroDef, MacroInstance, SubComponent
from ..util.macro_xml_translator import xml_to_params, params_to_xml
from ..param_spec import ALLOWED_PARAMS
from .pin_table import PinTable
from .param_editor import MacroParamsDialog


class ComplexEditor(QtWidgets.QDialog):
    """Dialog for editing/creating a complex device."""

    dirtyChanged = QtCore.pyqtSignal(bool)

    def __init__(self, macro_map: dict[int, MacroDef] | None = None, parent=None):
        super().__init__(parent)
        self.macro_map: dict[int, MacroDef] = macro_map or {}
        self.dirty = False

        layout = QtWidgets.QVBoxLayout(self)
        self.sub_table = QtWidgets.QTableWidget(0, 0)
        layout.addWidget(self.sub_table)

        self.sub_group = QtWidgets.QGroupBox("Sub-components")
        self.sub_group.setCheckable(True)
        self.sub_group.setChecked(False)
        sg_layout = QtWidgets.QVBoxLayout(self.sub_group)
        self.sub_list = QtWidgets.QListWidget()
        sg_layout.addWidget(self.sub_list)
        self.sub_group.toggled.connect(self.sub_list.setVisible)
        self.sub_list.setVisible(False)
        self.sub_list.currentRowChanged.connect(self._on_sub_selected)
        layout.addWidget(self.sub_group)
        self.sub_components: list[SubComponent] = []

        form = QtWidgets.QFormLayout()
        self.pin_table = PinTable()
        form.addRow("Pins", self.pin_table)
        self.macro_combo = QtWidgets.QComboBox()
        self._last_idx = -1
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
        self._editor_cx = None

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

    def set_sub_components(self, subs: list[SubComponent]) -> None:
        self.sub_components = subs
        self.sub_list.clear()
        for sc in subs:
            pins = ",".join(str(p) for p in sc.pins)
            self.sub_list.addItem(f"{sc.macro.name} \N{RIGHTWARDS ARROW} {pins}")
        self._on_sub_selected(self.sub_list.currentRow())

    def _on_sub_selected(self, row: int) -> None:
        if 0 <= row < len(self.sub_components):
            self.pin_table.highlight_pins(self.sub_components[row].pins)
        else:
            self.pin_table.highlight_pins([])

    def _on_macro_change(self) -> None:
        if self.macro_combo.currentIndex() == self._last_idx:
            return
        self._last_idx = self.macro_combo.currentIndex()
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
            tip = f"{param.name}   "
            if param.min is not None or param.max is not None:
                tip += f"[{param.min or ''}-{param.max or ''}] "
            unit = next(
                (
                    u
                    for u in ["Ohm", "F", "H", "V", "A", "Hz", "°C", "%"]
                    if param.name.endswith(u)
                ),
                "",
            )
            tip = tip + unit if unit else tip.rstrip()
            widget.setToolTip(tip.strip())
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
            self.pin_table.set_pins([])
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
        self.pin_table.set_pins([p for p in pins if p])
        id_func = int(getattr(row, "IDFunction", row[1]))
        index = self.macro_combo.findData(id_func)
        if index >= 0:
            self.macro_combo.setCurrentIndex(index)
        macro = self.macro_map.get(id_func)
        self._build_param_widgets(macro)
        pin_s = getattr(row, "PinS", row[6] if len(row) > 6 else None)
        macros = {}
        pin_s_error = False
        if pin_s:
            try:
                macros = xml_to_params(pin_s)
            except Exception:
                macros = {}
                pin_s_error = True
            else:
                if not macros:
                    pin_s_error = True
        values: Dict[str, str] = {}
        if macros:
            if macro and macro.name in macros:
                values = macros.get(macro.name, {})
            else:
                values = next(iter(macros.values()))
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
        if pin_s_error:
            QtWidgets.QMessageBox.warning(
                self,
                "PinS translation failed",
                "The PinS XML for this sub-component could not be translated."
                " Macro parameters may be missing.",
            )

    # ------------------------------------------------------------------ dirty
    def on_dirty(self) -> None:
        if not self.dirty:
            self.dirty = True
            self.dirtyChanged.emit(True)

    # ------------------------------------------------------------------- save
    def save_complex(self) -> None:
        self.accept()

    # ------------------------------------------------------------------ helpers
    def to_update_dict(self) -> dict[str, Any]:
        pins = [p.strip() for p in self.pin_table.pins() if p.strip()]
        if len(set(pins)) < 2:
            raise ValueError("At least two unique pins required")
        data = self.macro_combo.currentData()
        if data is None:
            raise ValueError("No macro selected")
        id_func = int(data)
        macro_name = self.macro_combo.currentText()
        params = {n: self._widget_value(w) for n, w in self.param_widgets.items()}
        xml = params_to_xml({macro_name: params}, schema=ALLOWED_PARAMS)
        pad_vals = (pins + [None, None, None, None])[:4]
        return {
            "IDFunction": id_func,
            "PinA": pad_vals[0],
            "PinB": pad_vals[1],
            "PinC": pad_vals[2],
            "PinD": pad_vals[3],
            "PinS": xml,
        }

    def load_from_model(self, cx: ComplexDevice) -> None:
        pins = getattr(cx, "pins", None)
        if not pins:
            total = getattr(cx, "total_pins", 0) or 0
            pins = [str(i) for i in range(1, total + 1)]
        else:
            pins = [str(p) for p in pins]
        self.pin_table.set_pins(pins)
        idx = self.macro_combo.findText(str(cx.macro.name))
        if idx >= 0:
            self.macro_combo.setCurrentIndex(idx)
        macro = self.macro_map.get(cx.id_function)
        self._build_param_widgets(macro)
        for k, v in cx.macro.params.items():
            w = self.param_widgets.get(k)
            if isinstance(w, QtWidgets.QSpinBox):
                w.setValue(int(v))
            elif isinstance(w, QtWidgets.QDoubleSpinBox):
                w.setValue(float(v))
            elif isinstance(w, QtWidgets.QCheckBox):
                w.setChecked(str(v).lower() in ("1", "true", "yes"))
            elif isinstance(w, QtWidgets.QComboBox):
                idx2 = w.findText(str(v))
                if idx2 >= 0:
                    w.setCurrentIndex(idx2)
                elif w.count() == 0:
                    w.addItem(str(v))
            elif isinstance(w, QtWidgets.QLineEdit):
                w.setText(str(v))
        self.dirty = False
        self.dirtyChanged.emit(False)

    # ----------------------------------------------------------------- buffer
    def load_editor_complex(self, model: "EditorComplex") -> None:
        """Populate :attr:`sub_table` from an :class:`EditorComplex` model.

        This method is used in buffer mode where sub-components already contain
        macro and parameter information.  It intentionally keeps the existing
        single-macro editor intact so tests targeting that behaviour continue to
        work.
        """

        from .adapters import EditorComplex as _EC  # local import to avoid cycle

        assert isinstance(model, _EC)
        self._editor_cx = model
        subs = model.subcomponents
        pin_cols = sorted({p for sc in subs for p in sc.pins.keys()})
        headers = ["Function"] + pin_cols + ["Macro", "Params"]
        self.sub_table.setColumnCount(len(headers))
        self.sub_table.setHorizontalHeaderLabels(headers)
        self.sub_table.setRowCount(len(subs))
        pin_s_problem = False
        for row, sc in enumerate(subs):
            self.sub_table.setItem(row, 0, QtWidgets.QTableWidgetItem(sc.name))
            for col, pin in enumerate(pin_cols, start=1):
                self.sub_table.setItem(
                    row, col, QtWidgets.QTableWidgetItem(sc.pins.get(pin, ""))
                )
            combo = QtWidgets.QComboBox()
            for macro_name in sc.all_macros.keys():
                combo.addItem(macro_name)
            if combo.count() == 0:
                combo.addItem(sc.selected_macro)
            idx = combo.findText(sc.selected_macro)
            if idx >= 0:
                combo.setCurrentIndex(idx)
            combo.currentTextChanged.connect(
                lambda name, sc=sc: self._switch_macro(sc, name)
            )
            self.sub_table.setCellWidget(row, len(pin_cols) + 1, combo)

            btn = QtWidgets.QPushButton("Edit…")
            btn.clicked.connect(lambda _=False, sc=sc: self._edit_params(sc))
            self.sub_table.setCellWidget(row, len(pin_cols) + 2, btn)
            if getattr(sc, "pin_s_error", False):
                pin_s_problem = True

        if pin_s_problem:
            QtWidgets.QMessageBox.warning(
                self,
                "PinS translation failed",
                "Some sub-components had unreadable PinS XML. Parameters were not pre-loaded. You can still edit them manually.",
            )

    # ----------------------------------------------------------------- helpers
    def _switch_macro(self, sc: "EditorMacro", name: str) -> None:
        sc.selected_macro = name
        sc.macro_params = sc.all_macros.get(name, {})
        sc.params = sc.macro_params

    def _edit_params(self, sc: "EditorMacro") -> None:
        if getattr(sc, "pin_s_error", False):
            QtWidgets.QMessageBox.warning(
                self,
                "PinS translation failed",
                "This sub-component had unreadable PinS XML. Parameters were not pre-loaded. You can still edit them manually.",
            )
        dlg = MacroParamsDialog(sc.macro_params, self)
        if dlg.exec() == QtWidgets.QDialog.DialogCode.Accepted:
            updated = dlg.params()
            sc.macro_params = updated
            sc.params = updated
            sc.all_macros[sc.selected_macro] = updated
