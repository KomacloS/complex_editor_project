from __future__ import annotations

import logging
import traceback
from typing import Dict, List, Optional, cast

from PyQt6 import QtWidgets, QtCore

from ..domain import (
    ComplexDevice,
    MacroDef,
    MacroInstance,
    SubComponent,
    MacroParam,
)
from ..param_spec import ALLOWED_PARAMS
from ..db import discover_macro_map
from ..io.buffer_loader import WizardPrefill


class BasicsPage(QtWidgets.QWidget):
    def __init__(self) -> None:
        super().__init__()
        layout = QtWidgets.QFormLayout(self)
        self.pin_spin = QtWidgets.QSpinBox()
        self.pin_spin.setRange(2, 256)
        self.pin_spin.setValue(2)
        self.pn_edit = QtWidgets.QLineEdit()
        self.alt_edit = QtWidgets.QLineEdit()
        layout.addRow("Pin-count", self.pin_spin)
        layout.addRow("Primary PN", self.pn_edit)
        layout.addRow("Alternate PNs", self.alt_edit)


class SubCompListPage(QtWidgets.QWidget):
    def __init__(self) -> None:
        super().__init__()
        layout = QtWidgets.QHBoxLayout(self)
        self.list = QtWidgets.QListWidget()
        layout.addWidget(self.list)
        btns = QtWidgets.QVBoxLayout()
        self.add_btn = QtWidgets.QPushButton("Add")
        self.dup_btn = QtWidgets.QPushButton("Duplicate")
        self.del_btn = QtWidgets.QPushButton("Delete")
        btns.addWidget(self.add_btn)
        btns.addWidget(self.dup_btn)
        btns.addWidget(self.del_btn)
        self.edit_pins_btn = QtWidgets.QPushButton("Edit Pins")
        self.edit_params_btn = QtWidgets.QPushButton("Edit Parameters")
        btns.addWidget(self.edit_pins_btn)
        btns.addWidget(self.edit_params_btn)
        btns.addStretch()
        layout.addLayout(btns)


# ────────── MacroPinsPage ──────────────────────────────────────────
class MacroPinsPage(QtWidgets.QWidget):
    """Pick a macro and map its logical pins to physical pads."""

    def __init__(self, macro_map: dict[int, MacroDef]) -> None:
        super().__init__()
        # Preserve the passed-in dictionary even if empty so updates
        # remain visible to the caller.
        self.macro_map = macro_map if macro_map is not None else {}

        vbox = QtWidgets.QVBoxLayout(self)

        # ── macro selector ──────────────────────────────────────────────
        self.macro_combo = QtWidgets.QComboBox()

        # Only list macros that are defined in the YAML spec. Any macros loaded
        # from the MDB are ignored for the purpose of parameter editing.
        self.macro_map = self.macro_map or {}

        if not self.macro_map:
            self.macro_combo.addItem("⚠  No macros loaded")
            self.macro_combo.setEnabled(False)
        else:
            for id_func, macro in self.macro_map.items():
                self.macro_combo.addItem(macro.name, id_func)
            self.macro_combo.setCurrentIndex(0)
        vbox.addWidget(self.macro_combo)

        # ── ordered-pin table ───────────────────────────────────────────
        self.pin_table = QtWidgets.QTableWidget(0, 2, self)
        self.pin_table.setHorizontalHeaderLabels(["Macro pin", "Pad #"])
        hdr = cast(QtWidgets.QHeaderView, self.pin_table.horizontalHeader())
        hdr.setSectionResizeMode(0, QtWidgets.QHeaderView.ResizeMode.Stretch)
        hdr.setSectionResizeMode(1, QtWidgets.QHeaderView.ResizeMode.ResizeToContents)
        vbox.addWidget(self.pin_table)
        self.current_subcomponent: SubComponent | None = None

    # ------------------------------------------------------------------
    # public helpers used by the wizard
    # ------------------------------------------------------------------
    def set_pin_count(self, total_pads: int) -> None:
        idfunc = self.macro_combo.currentData()
        macro = self.macro_map.get(int(idfunc)) if idfunc is not None else None
        if not macro or not macro.params:
            logical_names = ["Pin A", "Pin B", "Pin C", "Pin D"]
        else:
            logical_names = [p.name for p in macro.params if p.name.startswith("Pin")]
            if not logical_names:
                logical_names = ["Pin A", "Pin B", "Pin C", "Pin D"]
        if len(logical_names) < 4:
            extra = ["Pin A", "Pin B", "Pin C", "Pin D"]
            for name in extra[len(logical_names):4]:
                logical_names.append(name)

        self.pin_table.blockSignals(True)
        self.pin_table.setRowCount(len(logical_names))
        for row, lname in enumerate(logical_names):
            self.pin_table.setItem(row, 0, QtWidgets.QTableWidgetItem(lname))
            combo = QtWidgets.QComboBox()
            free = [str(p) for p in range(1, total_pads + 1)]
            combo.addItems([""] + free)
            combo.currentIndexChanged.connect(self._on_table_change)
            self.pin_table.setCellWidget(row, 1, combo)
        self.pin_table.blockSignals(False)
        self._on_table_change()

    def checked_pins(self) -> list[int]:
        """Return selected pad numbers in logical order."""
        result: list[int] = []
        for row in range(self.pin_table.rowCount()):
            combo = cast(QtWidgets.QComboBox, self.pin_table.cellWidget(row, 1))
            text = combo.currentText()
            if text:
                result.append(int(text))
        return result

    # ------------------------------------------------------------------
    # internal
    # ------------------------------------------------------------------
    def _on_table_change(self) -> None:
        """Highlight duplicate order numbers but allow them."""
        seen: dict[int, int] = {}
        duplicates: set[int] = set()

        for row in range(self.pin_table.rowCount()):
            combo = cast(QtWidgets.QComboBox, self.pin_table.cellWidget(row, 1))
            text = combo.currentText()
            combo.setStyleSheet("")

            if not text:
                continue
            val = int(text)
            if val in seen:
                duplicates.update({row, seen[val]})
            seen[val] = row

        for row in duplicates:
            widget = self.pin_table.cellWidget(row, 1)
            if widget is not None:
                widget.setStyleSheet("background:#FFCCCC;")

        mapping_ok = True  # duplicates allowed
        parent = self.parentWidget()
        if parent is None or parent.parent() is None:
            return
        wiz = cast(NewComplexWizard, parent.parent())  # the QDialog
        wiz._mapping_ok = mapping_ok
        wiz._update_nav()

        # navigation to the parameter page now happens only when the user
        # presses "Next" in the wizard. The table change merely updates
        # navigation button state without auto-switching pages.

    def pad_combo_at_row(self, row: int) -> QtWidgets.QComboBox:
        return cast(QtWidgets.QComboBox, self.pin_table.cellWidget(row, 1))

    def _index_for_function_id(self, func_id: int) -> int:
        return self.macro_combo.findData(func_id)

    def _index_for_macro_name(self, name: str) -> int:
        return self.macro_combo.findText(name)

    def load_from_subcomponent(self, sc: SubComponent) -> None:
        """Populate macro selector and pad assignments from ``sc``."""
        idx = -1
        if getattr(sc.macro, "id_function", None) is not None:
            idx = self._index_for_function_id(sc.macro.id_function)
            # If the ID points to a different macro (YAML order changed),
            # fall back to matching by macro name.
            if idx >= 0 and self.macro_combo.itemText(idx) != sc.macro.name:
                idx = -1
        if idx < 0:
            idx = self._index_for_macro_name(sc.macro.name)
        self.macro_combo.setCurrentIndex(idx)

        self.pin_table.blockSignals(True)
        for r, pin in enumerate(sc.pins):
            combo = cast(QtWidgets.QComboBox, self.pin_table.cellWidget(r, 1))
            if combo is not None:
                combo.setCurrentText(str(pin))
        self.pin_table.blockSignals(False)
        self.current_subcomponent = sc
        self._on_table_change()


class ParamPage(QtWidgets.QWidget):
    widgets: dict[str, QtWidgets.QWidget]
    required: set[str]
    macro_name: str

    def __init__(self) -> None:
        super().__init__()
        layout = QtWidgets.QVBoxLayout(self)
        self.heading = QtWidgets.QLabel()
        font = self.heading.font()
        font.setBold(True)
        self.heading.setFont(font)
        layout.addWidget(self.heading)

        self.scroll = QtWidgets.QScrollArea()
        self.scroll.setWidgetResizable(True)
        layout.addWidget(self.scroll)

        self.group_box = QtWidgets.QGroupBox()
        self.grid = QtWidgets.QGridLayout()
        self.grid.setHorizontalSpacing(20)
        self.grid.setVerticalSpacing(10)
        self.grid.setColumnStretch(1, 1)
        self.grid.setColumnStretch(3, 1)
        self.group_box.setLayout(self.grid)
        self.group_box.setContentsMargins(10, 10, 10, 10)
        self.group_box.setMinimumWidth(300)
        self.scroll.setWidget(self.group_box)
        self.warn_label = QtWidgets.QLabel()
        self.warn_label.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        self.warn_label.setStyleSheet(
            "background:#FFEB9C;padding:20px;font-weight:bold"
        )
        self.warn_label.hide()
        layout.addWidget(self.warn_label)
        # copy button removed – params are edited directly
        self.widgets: dict[str, QtWidgets.QWidget] = {}
        self.required: set[str] = set()
        self.macro_name: str = ""
        self.errors: list[str] = []

    def build_widgets(self, macro: MacroDef, params: dict[str, str]) -> None:
        try:
            while self.grid.count():
                item = self.grid.takeAt(0)
                if item is not None:
                    w = item.widget()
                    if w is not None:
                        w.deleteLater()
            self.widgets = {}
            self.required = set()
            self.errors = []
            self.macro_name = macro.name
            self.heading.setText(macro.name)
            self.group_box.setTitle(macro.name)
            self.warn_label.hide()
            self.group_box.show()
            allowed = ALLOWED_PARAMS.get(macro.name)
            if allowed is None:
                logging.getLogger(__name__).warning(
                    "Macro %s has no parameter definition in DB or YAML", macro.name
                )
                self.group_box.hide()
                self.warn_label.setText(
                    f"\N{WARNING SIGN} Parameters for '{macro.name}' could not be found. Check your YAML file."
                )
                self.warn_label.show()
                return
            # ---- merge YAML params not present in MacroDef ----
            existing = {p.name for p in macro.params}
            for pname, spec in allowed.items():
                if pname in existing:
                    continue
                if isinstance(spec, dict):
                    if "choices" in spec or spec.get("type") == "ENUM":
                        ptype = "ENUM"
                        default = spec.get("default")
                        macro.params.append(
                            MacroParam(pname, ptype, str(default) if default is not None else None, None, None)
                        )
                        continue
                    min_v = spec.get("min")
                    max_v = spec.get("max")
                    is_int = (
                        min_v is not None
                        and max_v is not None
                        and float(min_v).is_integer()
                        and float(max_v).is_integer()
                    )
                    ptype = "INT" if is_int else "FLOAT"
                    macro.params.append(
                        MacroParam(
                            pname,
                            ptype,
                            str(spec.get("default")) if spec.get("default") is not None else None,
                            str(min_v) if min_v is not None else None,
                            str(max_v) if max_v is not None else None,
                        )
                    )
                elif isinstance(spec, list):
                    default = spec[0] if spec else None
                    macro.params.append(
                        MacroParam(pname, "ENUM", str(default) if default is not None else None, None, None)
                    )
                else:
                    macro.params.append(MacroParam(pname, "INT", None, None, None))
            self.required = {p.name for p in macro.params if p.default is None}
            row = 0
            col = 0
            mid = (len(macro.params) + 1) // 2
            left = macro.params[:mid]
            right = macro.params[mid:]
            ordered = list(left) + list(right)
            for idx, p in enumerate(ordered):
                if idx < len(left):
                    row = idx
                    col = 0
                else:
                    row = idx - len(left)
                    col = 1
                label = QtWidgets.QLabel(p.name)
                spec = allowed.get(p.name)
                w: QtWidgets.QWidget
                if macro.name == "GATE" and p.name in {
                    "Check_A",
                    "Check_B",
                    "Check_C",
                    "Check_D",
                }:
                    w = QtWidgets.QLineEdit()
                elif isinstance(spec, dict) and ("min" in spec or "max" in spec):
                    min_val = spec.get("min")
                    max_val = spec.get("max")
                    use_int = all(
                        v is not None and float(v).is_integer()
                        for v in (min_val, max_val)
                    ) and all(
                        v is None or -2147483648 <= int(float(v)) <= 2147483647
                        for v in (min_val, max_val)
                    )
                    if use_int:
                        w = QtWidgets.QSpinBox()
                        if min_val is not None:
                            w.setMinimum(int(float(min_val)))
                        if max_val is not None:
                            w.setMaximum(int(float(max_val)))
                    else:
                        w = QtWidgets.QDoubleSpinBox()
                        if min_val is not None:
                            w.setMinimum(float(min_val))
                        if max_val is not None:
                            w.setMaximum(float(max_val))
                    init = p.default if p.default is not None else min_val
                    if isinstance(w, QtWidgets.QSpinBox) and init is not None:
                        w.setValue(int(float(init)))
                    elif isinstance(w, QtWidgets.QDoubleSpinBox) and init is not None:
                        w.setValue(float(init))
                elif isinstance(spec, list):
                    w = QtWidgets.QComboBox()
                    w.addItems([str(s) for s in spec])
                    if p.default is not None and str(p.default) in [
                        str(s) for s in spec
                    ]:
                        idx = [str(s) for s in spec].index(str(p.default))
                        w.setCurrentIndex(idx)
                elif isinstance(spec, dict) and "choices" in spec:
                    w = QtWidgets.QComboBox()
                    w.addItems([str(c) for c in spec.get("choices", [])])
                    if p.default is not None and str(p.default) in [
                        str(c) for c in spec.get("choices", [])
                    ]:
                        idx = [str(c) for c in spec.get("choices", [])].index(
                            str(p.default)
                        )
                        w.setCurrentIndex(idx)
                else:
                    if p.type == "INT":
                        w = QtWidgets.QSpinBox()
                        if p.min is not None:
                            w.setMinimum(int(p.min))
                        if p.max is not None:
                            w.setMaximum(int(p.max))
                    elif p.type == "FLOAT":
                        w = QtWidgets.QDoubleSpinBox()
                        if p.min is not None:
                            w.setMinimum(float(p.min))
                        if p.max is not None:
                            w.setMaximum(float(p.max))
                    elif p.type == "BOOL":
                        w = QtWidgets.QCheckBox()
                    elif p.type == "ENUM":
                        w = QtWidgets.QComboBox()
                        choices = (p.default or p.min or "").split(";")
                        if len(choices) > 1:
                            w.addItems(choices)
                    else:
                        w = QtWidgets.QLineEdit()
                self.widgets[p.name] = w
                self.grid.addWidget(label, row, col * 2)
                self.grid.addWidget(w, row, col * 2 + 1)
                val = params.get(p.name, p.default)
                if isinstance(w, QtWidgets.QSpinBox) and val is not None:
                    w.setValue(int(float(val)))
                elif isinstance(w, QtWidgets.QDoubleSpinBox) and val is not None:
                    w.setValue(float(val))
                elif isinstance(w, QtWidgets.QCheckBox):
                    w.setChecked(str(val).lower() in ("1", "true", "yes"))
                elif isinstance(w, QtWidgets.QComboBox) and val is not None:
                    idx = w.findText(str(val))
                    if idx >= 0:
                        w.setCurrentIndex(idx)
                elif isinstance(w, QtWidgets.QLineEdit):
                    if val is not None and not (
                        p.type == "PIN" and str(val) == "-99999999999.0"
                    ):
                        if not (
                            macro.name == "GATE"
                            and p.name in {
                                "PathPin_A",
                                "PathPin_B",
                                "PathPin_C",
                                "PathPin_D",
                                "Check_A",
                                "Check_B",
                                "Check_C",
                                "Check_D",
                            }
                            and str(val) in {"-1", "-1.0"}
                        ):
                            w.setText(str(val))

                if isinstance(w, (QtWidgets.QSpinBox, QtWidgets.QDoubleSpinBox)):
                    w.valueChanged.connect(self._validate)
                elif isinstance(w, QtWidgets.QComboBox):
                    w.currentIndexChanged.connect(self._validate)
                elif isinstance(w, QtWidgets.QCheckBox):
                    w.stateChanged.connect(self._validate)
                else:
                    w.textChanged.connect(self._validate)

            self._validate()
        except Exception as e:
            logging.getLogger(__name__).exception(
                "Failed to build param page for %s", macro.name
            )
            QtWidgets.QMessageBox.critical(
                self,
                "Param Page Error",
                f"{e.__class__.__name__}: {e}\n\n" + traceback.format_exc(),
            )
            raise

    def param_values(self) -> dict[str, str]:
        result: dict[str, str] = {}
        for name, w in self.widgets.items():
            if isinstance(w, QtWidgets.QSpinBox):
                result[name] = str(w.value())
            elif isinstance(w, QtWidgets.QDoubleSpinBox):
                result[name] = str(w.value())
            elif isinstance(w, QtWidgets.QCheckBox):
                result[name] = "1" if w.isChecked() else "0"
            elif isinstance(w, QtWidgets.QComboBox):
                result[name] = w.currentText()
            elif isinstance(w, QtWidgets.QLineEdit):
                result[name] = w.text()
        return result

    def required_filled(self) -> bool:
        for name in self.required:
            w = self.widgets.get(name)
            if isinstance(w, QtWidgets.QLineEdit) and not w.text().strip():
                return False
            if isinstance(w, QtWidgets.QComboBox) and not w.currentText():
                return False
        return True

    # ------------------------------------------------------------------ helpers
    def _widget_value(self, w: QtWidgets.QWidget) -> str | int | float | bool | None:
        if isinstance(w, QtWidgets.QSpinBox):
            return w.value()
        if isinstance(w, QtWidgets.QDoubleSpinBox):
            return w.value()
        if isinstance(w, QtWidgets.QComboBox):
            return w.currentText()
        if isinstance(w, QtWidgets.QCheckBox):
            return w.isChecked()
        return w.text()

    def _validate(self) -> None:
        """
        Mark invalid inputs red and expose boolean flag
        (`self.parent().parent()._params_ok`) so the wizard
        can enable/disable navigation buttons.
        """
        allowed = ALLOWED_PARAMS.get(self.macro_name, {})
        self.errors = []
        self_valid = True
        for pname, widget in self.widgets.items():
            widget.setStyleSheet("")
            spec = allowed.get(pname)
            value = self._widget_value(widget)
            ok = True
            if isinstance(spec, dict) and ("min" in spec or "max" in spec):
                lo, hi = spec.get("min"), spec.get("max")
                try:
                    val = float(value)  # type: ignore[arg-type]
                    if lo is not None and val < float(lo):
                        ok = False
                    if hi is not None and val > float(hi):
                        ok = False
                except Exception:
                    ok = False
            elif isinstance(spec, list):
                ok = str(value) in [str(s) for s in spec]
            elif isinstance(spec, dict) and "choices" in spec:
                ok = str(value) in [str(c) for c in spec.get("choices", [])]
            elif isinstance(spec, list):
                ok = str(value) in [str(s) for s in spec]
            if not ok:
                self_valid = False
                widget.setStyleSheet("background:#FFCCCC;")
                if isinstance(spec, dict) and ("min" in spec or "max" in spec):
                    msg = f"{pname} must be between {lo} and {hi}"
                elif isinstance(spec, list):
                    msg = f"{pname} must be one of {', '.join(str(s) for s in spec)}"
                elif isinstance(spec, dict) and "choices" in spec:
                    msg = f"{pname} must be one of {', '.join(str(c) for c in spec.get('choices', []))}"
                else:
                    msg = f"{pname} is invalid"
                self.errors.append(msg)

        if self.macro_name == "GATE":
            gate_errs: list[str] = []
            path_names = [f"PathPin_{c}" for c in "ABCD"]
            check_names = [f"Check_{c}" for c in "ABCD"]
            values: dict[str, str] = {}
            for name in path_names + check_names:
                w = self.widgets.get(name)
                if isinstance(w, QtWidgets.QLineEdit):
                    text = w.text().strip()
                    if text in {"-1", "-1.0"}:
                        text = ""
                    values[name] = text
            lengths = {len(v) for v in values.values() if v}
            if len(lengths) > 1:
                gate_errs.append("PathPin/Check fields must all have the same length")
                for name in values:
                    widget = self.widgets.get(name)
                    if widget is not None:
                        widget.setStyleSheet("background:#FFCCCC;")
            for name in path_names:
                text = values.get(name, "")
                if text in {"", "-1", "-1.0"}:
                    continue
                allowed_set = {"1", "0", "H", "L"}
                if name in ("PathPin_B", "PathPin_D"):
                    allowed_set.add("Z")
                if any(ch not in allowed_set for ch in text):
                    gate_errs.append(f"{name} allows only {' '.join(sorted(allowed_set))}")
                    widget = self.widgets.get(name)
                    if widget is not None:
                        widget.setStyleSheet("background:#FFCCCC;")
            for name in check_names:
                text = values.get(name, "")
                if text in {"", "-1", "-1.0"}:
                    continue
                if any(ch not in {"1", "0"} for ch in text):
                    gate_errs.append(f"{name} allows only 1 or 0")
                    widget = self.widgets.get(name)
                    if widget is not None:
                        widget.setStyleSheet("background:#FFCCCC;")
            if gate_errs:
                self_valid = False
                self.errors.extend(gate_errs)
        wiz_parent = self.parentWidget()
        if wiz_parent is not None and wiz_parent.parent() is not None:
            wiz = cast(NewComplexWizard, wiz_parent.parent())
            wiz._params_ok = self_valid
            wiz._update_nav()


class ReviewPage(QtWidgets.QWidget):
    def __init__(self) -> None:
        super().__init__()
        layout = QtWidgets.QVBoxLayout(self)
        self.table = QtWidgets.QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["Macro", "Pins", "Params"])
        layout.addWidget(self.table)
        self.warn_label = QtWidgets.QLabel()
        self.warn_label.setStyleSheet("color:#b00;")
        self.warn_label.setWordWrap(True)
        self.warn_label.hide()
        layout.addWidget(self.warn_label)
        self.save_btn = QtWidgets.QPushButton("Save")
        layout.addWidget(self.save_btn)
        self.edit_pins_btn = QtWidgets.QPushButton("Edit Pins")
        self.edit_params_btn = QtWidgets.QPushButton("Edit Parameters")
        self.edit_pins_btn.setEnabled(False)
        self.edit_params_btn.setEnabled(False)
        layout.insertWidget(layout.indexOf(self.save_btn), self.edit_pins_btn)
        layout.insertWidget(layout.indexOf(self.save_btn), self.edit_params_btn)
        self.edit_pins_btn.clicked.connect(self.on_edit_pins_clicked)
        self.table.currentCellChanged.connect(lambda *_: self._update_buttons())
        self.table.cellClicked.connect(lambda *_: self._update_buttons())
        self._update_buttons()

    def _update_buttons(self) -> None:
        ok = self.table.currentRow() >= 0
        self.edit_pins_btn.setEnabled(ok)
        self.edit_params_btn.setEnabled(ok)

    def populate(self, comps: list[SubComponent], warnings: list[str] | None = None) -> None:
        self.table.setRowCount(len(comps))
        for i, sc in enumerate(comps):
            self.table.setItem(i, 0, QtWidgets.QTableWidgetItem(sc.macro.name))
            self.table.setItem(
                i, 1, QtWidgets.QTableWidgetItem(",".join(str(p) for p in sc.pins))
            )
            keys = ",".join(sorted(sc.macro.params.keys()))
            self.table.setItem(i, 2, QtWidgets.QTableWidgetItem(keys))
        if warnings:
            self.warn_label.setText("\n".join(warnings))
            self.warn_label.show()
        else:
            self.warn_label.hide()

    def wizard(self) -> "NewComplexWizard":
        return cast("NewComplexWizard", self.parentWidget().parent())

    def on_edit_pins_clicked(self) -> None:
        row = self.table.currentRow()
        if row < 0 and self.table.rowCount() > 0:
            row = 0
            self.table.selectRow(row)
        self.wizard().activate_pin_mapping_for(row)


class NewComplexWizard(QtWidgets.QDialog):
    def __init__(self, macro_map: dict[int, MacroDef] | None, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("New Complex")
        self.resize(600, 500)
        # Always build the macro map from the YAML spec to avoid relying on the
        # MDB for parameter information.
        self.macro_map = discover_macro_map(None)
        self.sub_components: list[SubComponent] = []
        self.current_index: Optional[int] = None

        layout = QtWidgets.QVBoxLayout(self)
        self.stack = QtWidgets.QStackedWidget()
        layout.addWidget(self.stack)
        nav = QtWidgets.QHBoxLayout()
        self.back_btn = QtWidgets.QPushButton("Back")
        self.next_btn = QtWidgets.QPushButton("Next")
        nav.addWidget(self.back_btn)
        nav.addStretch()
        nav.addWidget(self.next_btn)
        layout.addLayout(nav)

        self.basics_page = BasicsPage()
        self.basics_page.setWindowTitle("Step 1: Basic Settings")
        self.list_page = SubCompListPage()
        self.list_page.setWindowTitle("Step 2: Sub-Components")
        self.macro_page = MacroPinsPage(self.macro_map)
        self.macro_page.setWindowTitle("Step 3: Edit Pins")
        self.pin_mapping_page = self.macro_page
        # update macro_map in case dummy entries were added
        self.macro_map = self.macro_page.macro_map
        self.param_page = ParamPage()
        self.param_page.setWindowTitle("Step 4: Edit Parameters")
        self.review_page = ReviewPage()
        self.review_page.setWindowTitle("Step 5: Review Complex")

        self.stack.addWidget(self.basics_page)
        self.stack.addWidget(self.list_page)
        self.stack.addWidget(self.macro_page)
        self.stack.addWidget(self.param_page)
        self.stack.addWidget(self.review_page)

        self.back_btn.clicked.connect(self._back)
        self.next_btn.clicked.connect(self._next)
        self.list_page.add_btn.clicked.connect(self._add_sub)
        self.list_page.dup_btn.clicked.connect(self._dup_sub)
        self.list_page.del_btn.clicked.connect(self._del_sub)
        self.list_page.edit_pins_btn.clicked.connect(self._edit_selected_pins)
        self.list_page.edit_params_btn.clicked.connect(self._edit_selected_params)
        self.list_page.list.currentRowChanged.connect(self._update_edit_buttons)
        self.review_page.edit_params_btn.clicked.connect(
            self._edit_selected_params_review
        )
        self.review_page.save_btn.clicked.connect(self._finish)
        self._mapping_ok = False  # ② flag updated by pin-table
        self._params_ok = True
        self._param_page_disabled = False
        self.mode = "new"
        self.editing_complex_id: Optional[int] = None

        self._update_edit_buttons(-1)

        self._update_nav()

    @classmethod
    def from_wizard_prefill(cls, prefill: WizardPrefill, parent=None) -> "NewComplexWizard":
        """Build a wizard pre-populated from :class:`WizardPrefill`."""

        wiz = cls(None, parent)
        wiz._param_page_disabled = True
        if prefill.complex_name:
            wiz.basics_page.pn_edit.setText(prefill.complex_name)
        max_pin = 0
        for sc in prefill.sub_components:
            pins = list(sc.get("pins") or [])
            if pins:
                max_pin = max(max_pin, max(pins))
            mi = MacroInstance(sc.get("macro_name", ""), {})
            if sc.get("id_function") is not None:
                mi.id_function = sc.get("id_function")
            subc = SubComponent(mi, pins)
            wiz.sub_components.append(subc)
            text = f"{mi.name} ({','.join(str(p) for p in pins)})"
            wiz.list_page.list.addItem(text)
        if max_pin:
            wiz.basics_page.pin_spin.setValue(max_pin)
        warnings: List[str] = []
        used: Dict[int, str] = {}
        for sc in wiz.sub_components:
            if getattr(sc.macro, "id_function", None) is None:
                warnings.append(f"Macro '{sc.macro.name}' has no IDFunction")
            for pin in sc.pins:
                if pin in used:
                    warnings.append(f"Pad {pin} used by multiple sub-components")
                else:
                    used[pin] = sc.macro.name
        wiz.review_page.populate(wiz.sub_components, warnings)
        wiz.param_page.group_box.hide()
        wiz.param_page.warn_label.setText(
            "Parameters not preloaded (PinS pending)."
        )
        wiz.param_page.warn_label.show()
        wiz._mapping_ok = True
        wiz.stack.setCurrentWidget(wiz.review_page)
        wiz._update_nav()
        return wiz

    @classmethod
    def from_existing(
        cls, prefill: WizardPrefill, complex_id: int, parent=None
    ) -> "NewComplexWizard":
        """Open the wizard in *edit* mode using ``prefill`` data."""

        wiz = cls(None, parent)
        wiz.mode = "edit"
        wiz.editing_complex_id = complex_id
        wiz._param_page_disabled = True

        if prefill.complex_name:
            wiz.basics_page.pn_edit.setText(prefill.complex_name)

        pin_cnt = getattr(prefill, "pin_count", 0)
        max_pin = 0
        for sc in prefill.sub_components:
            pins = list(sc.get("pins") or [])
            if pins:
                max_pin = max(max_pin, max(pins))
            mi = MacroInstance(sc.get("macro_name", ""), {})
            if sc.get("id_function") is not None:
                mi.id_function = sc.get("id_function")
            subc = SubComponent(mi, pins)
            wiz.sub_components.append(subc)
            text = f"{mi.name} ({','.join(str(p) for p in pins)})"
            wiz.list_page.list.addItem(text)

        # prefer explicit pin count if provided
        if pin_cnt:
            wiz.basics_page.pin_spin.setValue(int(pin_cnt))
        elif max_pin:
            wiz.basics_page.pin_spin.setValue(max_pin)

        warnings: List[str] = []
        used: Dict[int, str] = {}
        for sc in wiz.sub_components:
            if getattr(sc.macro, "id_function", None) is None:
                warnings.append(f"Macro '{sc.macro.name}' has no IDFunction")
            for pin in sc.pins:
                if pin in used:
                    warnings.append(f"Pad {pin} used by multiple sub-components")
                else:
                    used[pin] = sc.macro.name

        wiz.review_page.populate(wiz.sub_components, warnings)
        wiz.param_page.group_box.hide()
        wiz.param_page.warn_label.setText("(PinS editing coming soon)")
        wiz.param_page.warn_label.show()
        wiz._mapping_ok = True
        wiz.stack.setCurrentWidget(wiz.review_page)
        wiz._update_nav()
        return wiz
    # ------------------------------------------------------------------ actions
    def _add_sub(self) -> None:
        sc = SubComponent(MacroInstance("", {}), [])
        self.sub_components.append(sc)
        self.list_page.list.addItem("<new>")
        self.current_index = len(self.sub_components) - 1
        self._open_macro_page()

    def _dup_sub(self) -> None:
        row = self.list_page.list.currentRow()
        if row < 0:
            return
        orig = self.sub_components[row]
        new_sc = SubComponent(
            MacroInstance(orig.macro.name, orig.macro.params.copy()), orig.pins.copy()
        )
        self.sub_components.append(new_sc)
        self.list_page.list.addItem("<dup>")
        self.current_index = len(self.sub_components) - 1
        self.list_page.list.setCurrentRow(self.current_index)
        self._open_macro_page()
        idx = self.macro_page.macro_combo.findText(orig.macro.name)
        if idx >= 0:
            self.macro_page.macro_combo.setCurrentIndex(idx)
        for r, pin in enumerate(orig.pins):
            if r >= self.macro_page.pin_table.rowCount():
                break
            combo = cast(
                QtWidgets.QComboBox, self.macro_page.pin_table.cellWidget(r, 1)
            )
            combo.setCurrentText(str(pin))

    def _del_sub(self) -> None:
        row = self.list_page.list.currentRow()
        if row < 0:
            return
        self.sub_components.pop(row)
        self.list_page.list.takeItem(row)
        self._update_edit_buttons(self.list_page.list.currentRow())

    def _edit_selected_pins(self) -> None:
        row = self.list_page.list.currentRow()
        if row < 0:
            return
        self.activate_pin_mapping_for(row)

    def _edit_selected_params(self) -> None:
        row = self.list_page.list.currentRow()
        if row < 0:
            return
        self.activate_pin_mapping_for(row)
        self._open_param_page()

    def _edit_selected_params_review(self):
        row = self.review_page.table.currentRow()
        if row < 0:
            return
        self.activate_pin_mapping_for(row)
        self._open_param_page()

    def activate_pin_mapping_for(self, sub_idx: int) -> None:
        """Programmatically open the pin-mapping page for ``sub_idx``."""
        self.current_index = sub_idx
        if hasattr(self.list_page, "list"):
            self.list_page.list.setCurrentRow(sub_idx)
        sc = self.sub_components[sub_idx]
        self._open_macro_page()
        self.pin_mapping_page.load_from_subcomponent(sc)

    def _open_macro_page(self) -> None:
        count = self.basics_page.pin_spin.value()
        self.macro_page.set_pin_count(count)
        self.stack.setCurrentWidget(self.macro_page)
        self._update_nav()

    def _open_param_page(self) -> None:
        index = self.macro_page.macro_combo.currentData()
        macro = self.macro_map.get(int(index)) if index is not None else None
        if not macro and self.macro_map:
            macro = list(self.macro_map.values())[0]
        if macro is None:
            return
        assert self.current_index is not None
        pins = self.macro_page.checked_pins()
        sc = self.sub_components[self.current_index]
        sc.macro.name = macro.name
        sc.pins = pins
        if self._param_page_disabled:
            self.param_page.group_box.hide()
            self.param_page.warn_label.setText(
                "Parameters not preloaded (PinS pending)."
            )
            self.param_page.warn_label.show()
            self.stack.setCurrentWidget(self.param_page)
            self._update_nav()
            return
        if macro.params:  # normal case
            self.param_page.build_widgets(macro, sc.macro.params)
            self.stack.setCurrentWidget(self.param_page)
        else:  # no parameters → skip page
            self._save_params()
            self.stack.setCurrentWidget(self.review_page)
        self._update_nav()

    def _goto_param_page(self) -> None:
        """Switch to the parameter page if appropriate."""
        if self.stack.currentWidget() is self.param_page:
            return
        if self.stack.currentWidget() is not self.macro_page:
            return
        if not self._mapping_ok:
            return
        self._open_param_page()

    def _save_params(self) -> None:
        assert self.current_index is not None
        sc = self.sub_components[self.current_index]
        all_vals = self.param_page.param_values()
        sc.macro.params = all_vals
        macro_def = next(
            (m for m in self.macro_map.values() if m.name == sc.macro.name), None
        )
        overrides = []
        if macro_def:
            for p in macro_def.params:
                cur = all_vals.get(p.name)
                default = p.default
                try:
                    cur_s = cur if cur is not None else ""
                    cur_f = float(cur_s)
                    def_f = float(default) if default is not None else None
                    same = def_f is not None and abs(cur_f - def_f) < 1e-9
                except Exception:
                    if (
                        p.type == "PIN"
                        and (cur is None or str(cur) == "")
                        and str(default) == "-99999999999.0"
                    ):
                        same = True
                    elif (
                        macro_def
                        and macro_def.name == "GATE"
                        and p.name
                        in {
                            "PathPin_A",
                            "PathPin_B",
                            "PathPin_C",
                            "PathPin_D",
                            "Check_A",
                            "Check_B",
                            "Check_C",
                            "Check_D",
                        }
                        and (cur is None or str(cur) == "")
                        and str(default) in {"-1", "-1.0"}
                    ):
                        same = True
                    else:
                        same = str(cur) == str(default)
                if not same:
                    overrides.append((p.name, str(cur)))
        sc.macro.overrides = overrides
        text = f"{sc.macro.name} ({','.join(str(p) for p in sc.pins)})"
        item = self.list_page.list.item(self.current_index)
        if item is not None:
            item.setText(text)

    def _back(self) -> None:
        page = self.stack.currentWidget()
        if page is self.list_page:
            self.stack.setCurrentWidget(self.basics_page)
        elif page is self.macro_page:
            self.stack.setCurrentWidget(self.list_page)
        elif page is self.param_page:
            self.stack.setCurrentWidget(self.macro_page)
        elif page is self.review_page:
            self.stack.setCurrentWidget(self.list_page)
        self._update_nav()

    def _next(self) -> None:
        page = self.stack.currentWidget()
        if page is self.basics_page:
            self.stack.setCurrentWidget(self.list_page)
        elif page is self.macro_page:
            self._open_param_page()
        elif page is self.param_page:
            self.param_page._validate()
            if not self._params_ok or not self.param_page.required_filled():
                msg = "\n".join(self.param_page.errors) or "Invalid parameters"
                QtWidgets.QMessageBox.warning(self, "Parameter Error", msg)
                return
            self._save_params()
            self.stack.setCurrentWidget(self.list_page)
        elif page is self.list_page:
            self.review_page.populate(self.sub_components)
            self.stack.setCurrentWidget(self.review_page)
        self._update_nav()

    def _finish(self) -> None:
        if self.stack.currentWidget() is self.param_page:
            self._save_params()
        pin_count = self.basics_page.pin_spin.value()
        pins = [str(i) for i in range(1, pin_count + 1)]
        self.result_device = ComplexDevice(0, pins, MacroInstance("", {}))
        self.accept()

    # public --------------------------------------------------------------
    def to_complex_device(self) -> ComplexDevice:
        """Return the current wizard state as a :class:`ComplexDevice`."""

        pin_count = self.basics_page.pin_spin.value()
        pins = [str(i) for i in range(1, pin_count + 1)]
        dev = ComplexDevice(0, pins, MacroInstance("", {}))
        dev.subcomponents = self.sub_components
        dev.name = self.basics_page.pn_edit.text()
        return dev

    def _update_nav(self) -> None:
        """Enable/disable Back & Next based on current page content."""
        page = self.stack.currentWidget()
        self.back_btn.setEnabled(
            page is not self.basics_page or page is self.review_page
        )
        if page is self.macro_page:
            ok = self._mapping_ok
            self.next_btn.setEnabled(ok)
        elif page is self.param_page:
            self.next_btn.setEnabled(self.param_page.required_filled())
        elif page is self.review_page:
            ok = self._mapping_ok and self._params_ok
            self.next_btn.setEnabled(False)
            self.review_page.save_btn.setText("Finish")
            self.review_page.save_btn.setEnabled(ok)
        else:
            self.next_btn.setEnabled(True)
            self.review_page.save_btn.setText("Save")
            self.review_page.save_btn.setEnabled(self._mapping_ok and self._params_ok)

    def _update_edit_buttons(self, row: int) -> None:
        ok = row >= 0
        self.list_page.edit_pins_btn.setEnabled(ok)
        self.list_page.edit_params_btn.setEnabled(ok)
