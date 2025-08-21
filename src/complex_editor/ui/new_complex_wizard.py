from __future__ import annotations

import logging
import traceback
from typing import Dict, List, Optional, cast

from PyQt6 import QtWidgets, QtCore

from .widgets.step_indicator import StepIndicator

from ..domain import (
    ComplexDevice,
    MacroDef,
    MacroInstance,
    SubComponent,
    MacroParam,
)
from ..param_spec import ALLOWED_PARAMS, resolve_macro_name
from ..db import discover_macro_map
from ..io.buffer_loader import WizardPrefill
from ..util.macro_xml_translator import xml_to_params, params_to_xml


def _norm(s: str) -> str:
    return str(s).strip().lower()


def _is_default(val: object) -> bool:
    return isinstance(val, str) and _norm(val) == "default"


_PARAM_SCHEMA = {
    m: { _norm(p): spec for p, spec in params.items() }
    for m, params in ALLOWED_PARAMS.items()
}


def _macro_spec(name: str) -> dict | None:
    canonical = resolve_macro_name(name)
    return ALLOWED_PARAMS.get(canonical) if canonical else None


def _param_spec(macro: str, param: str):
    canonical = resolve_macro_name(macro)
    if not canonical:
        return None
    macro_map = _PARAM_SCHEMA.get(canonical)
    return macro_map.get(_norm(param)) if macro_map else None


def _get_case_insensitive(mapping: dict[str, str], key: str):
    for k, v in mapping.items():
        if _norm(k) == _norm(key):
            return v
    return None


def _safe_numeric(init, default: float | str | None = 0.0) -> float:
    """Coerce *init* to ``float`` with tolerant fallback."""

    def _coerce(val: float | str | None) -> float | None:
        if val is None:
            return None
        s = str(val).strip()
        if not s or s.lower() in {"default", "none", "null", "auto"}:
            return None
        try:
            return float(s.replace(",", ""))
        except Exception:
            return None

    num = _coerce(init)
    if num is not None:
        return num
    fallback = _coerce(default)
    return fallback if fallback is not None else 0.0


_COMMON_ENUMS = {"DEFAULT", "ON", "OFF", "LOW", "HIGH"}


def _infer_widget_for_value(param_name: str, raw_value: object) -> QtWidgets.QWidget:
    """Infer a reasonable widget for ``raw_value`` when no schema is present."""

    s = "" if raw_value is None else str(raw_value).strip()
    try:
        ival = int(s)
        w = QtWidgets.QSpinBox()
        w.setRange(-(10 ** 9), 10 ** 9)
        w.setSingleStep(1)
        w.setValue(ival)
        return w
    except Exception:
        pass
    try:
        fval = float(s)
        w = QtWidgets.QDoubleSpinBox()
        w.setRange(-1e12, 1e12)
        w.setSingleStep(0.01)
        w.setDecimals(2)
        w.setValue(fval)
        return w
    except Exception:
        pass
    if s.upper() in _COMMON_ENUMS:
        w = QtWidgets.QComboBox()
        w.setEditable(True)
        for opt in sorted(_COMMON_ENUMS):
            w.addItem("Default" if opt == "DEFAULT" else opt)
        idx = w.findText(s, QtCore.Qt.MatchFlag.MatchFixedString)
        if idx >= 0:
            w.setCurrentIndex(idx)
        else:
            w.setEditText(s)
        return w
    w = QtWidgets.QLineEdit()
    w.setText(s)
    return w


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

        self.pin_s_banner = QtWidgets.QFrame()
        self.pin_s_banner.setStyleSheet("background:#FFEB9C;padding:6px")
        banner_layout = QtWidgets.QHBoxLayout(self.pin_s_banner)
        banner_layout.setContentsMargins(6, 6, 6, 6)
        self.pin_s_label = QtWidgets.QLabel(
            "Some sub-components had unreadable PinS XML. Parameters were not pre-loaded. You can still edit them manually."
        )
        self.pin_s_label.setWordWrap(True)
        banner_layout.addWidget(self.pin_s_label)
        self.pin_s_more = QtWidgets.QPushButton("Learn more…")
        banner_layout.addWidget(self.pin_s_more)
        self.pin_s_banner.hide()
        layout.addWidget(self.pin_s_banner)

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
        self.special_values: dict[str, str] = {}

        self.pin_s_more.clicked.connect(
            lambda: QtWidgets.QToolTip.showText(
                self.pin_s_more.mapToGlobal(QtCore.QPoint()),
                "PinS XML stores default macro parameters. When unreadable, parameters must be entered manually.",
            )
        )

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
            self.special_values = {}
            self.macro_name = macro.name
            self.heading.setText(macro.name)
            self.group_box.setTitle(macro.name)
            self.warn_label.hide()
            self.group_box.show()
            allowed = _macro_spec(macro.name)
            if allowed is None:
                logging.getLogger(__name__).warning(
                    "Macro %s has no parameter definition in DB or YAML", macro.name
                )
                self.warn_label.setText(
                    f"\N{WARNING SIGN} Parameters for '{macro.name}' could not be found."
                )
                self.warn_label.show()
                allowed = {}
            else:
                self.warn_label.hide()

            # ---- merge YAML params not present in MacroDef ----
            if allowed:
                existing = {p.name.lower() for p in macro.params}
                for pname, spec in allowed.items():
                    if pname.lower() in existing:
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
            if macro.name == "GATE":
                for suf in "ABCD":
                    self.required.discard(f"Check_{suf}")
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
                spec = _param_spec(macro.name, p.name)
                w: QtWidgets.QWidget
                val = _get_case_insensitive(params, p.name)
                if spec is None:
                    w = _infer_widget_for_value(p.name, val if val is not None else p.default)
                    self.widgets[p.name] = w
                    self.grid.addWidget(label, row, col * 2)
                    self.grid.addWidget(w, row, col * 2 + 1)
                    if isinstance(w, QtWidgets.QSpinBox) or isinstance(w, QtWidgets.QDoubleSpinBox):
                        w.valueChanged.connect(lambda _v, n=p.name: self._on_spin_change(n))
                    elif isinstance(w, QtWidgets.QComboBox):
                        w.currentIndexChanged.connect(self._validate)
                    elif isinstance(w, QtWidgets.QLineEdit):
                        w.textChanged.connect(self._validate)
                    continue
                if macro.name == "GATE" and p.name in {
                    "Check_A",
                    "Check_B",
                    "Check_C",
                    "Check_D",
                }:
                    w = QtWidgets.QLineEdit()
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
                elif isinstance(spec, list):
                    w = QtWidgets.QComboBox()
                    w.addItems([str(s) for s in spec])
                    if p.default is not None and str(p.default) in [
                        str(s) for s in spec
                    ]:
                        idx = [str(s) for s in spec].index(str(p.default))
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
                if val is None:
                    val = p.default
                if isinstance(w, QtWidgets.QSpinBox):
                    default = p.default
                    if isinstance(spec, dict) and spec.get("default") is not None:
                        default = spec.get("default")
                    if _is_default(val):
                        w.setSpecialValueText("Default")
                        w.setValue(w.minimum())
                        self.special_values[p.name] = "Default"
                    else:
                        num = int(
                            _safe_numeric(
                                val,
                                default if default is not None else w.minimum(),
                            )
                        )
                        w.setValue(num)
                    w.valueChanged.connect(lambda _v, n=p.name: self._on_spin_change(n))
                elif isinstance(w, QtWidgets.QDoubleSpinBox):
                    default = p.default
                    if isinstance(spec, dict) and spec.get("default") is not None:
                        default = spec.get("default")
                    if _is_default(val):
                        w.setSpecialValueText("Default")
                        w.setValue(w.minimum())
                        self.special_values[p.name] = "Default"
                    else:
                        num = _safe_numeric(
                            val, default if default is not None else w.minimum()
                        )
                        w.setValue(num)
                    w.valueChanged.connect(lambda _v, n=p.name: self._on_spin_change(n))
                elif isinstance(w, QtWidgets.QCheckBox):
                    w.setChecked(str(val).lower() in ("1", "true", "yes"))
                    w.stateChanged.connect(self._validate)
                elif isinstance(w, QtWidgets.QComboBox) and val is not None:
                    idx = w.findText(str(val))
                    if idx >= 0:
                        w.setCurrentIndex(idx)
                    else:
                        w.setCurrentText(str(val))
                    w.currentIndexChanged.connect(self._validate)
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
            if name in self.special_values:
                result[name] = self.special_values[name]
            elif isinstance(w, QtWidgets.QSpinBox):
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
    def _on_spin_change(self, name: str) -> None:
        self.special_values.pop(name, None)
        self._validate()

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
        allowed = _macro_spec(self.macro_name) or {}
        self.errors = []
        self_valid = True
        for pname, widget in self.widgets.items():
            widget.setStyleSheet("")
            spec = _param_spec(self.macro_name, pname)
            value = self.special_values.get(pname, self._widget_value(widget))
            ok = True
            msg = ""
            if isinstance(spec, dict) and (
                (spec.get("type") or "").upper() == "ENUM" or "choices" in spec
            ):
                choices = [str(c) for c in spec.get("choices", [])]
                ok = any(_norm(str(value)) == _norm(c) for c in choices)
                msg = f"{pname} must be one of {', '.join(choices)}"
            elif isinstance(spec, list):
                choices = [str(s) for s in spec]
                ok = any(_norm(str(value)) == _norm(c) for c in choices)
                msg = f"{pname} must be one of {', '.join(choices)}"
            elif isinstance(spec, dict) and ("min" in spec or "max" in spec):
                lo, hi = spec.get("min"), spec.get("max")
                if _is_default(value) or value in ("", None):
                    ok = True
                else:
                    try:
                        val = float(value)  # type: ignore[arg-type]
                        if lo is not None and val < float(lo):
                            ok = False
                        if hi is not None and val > float(hi):
                            ok = False
                    except Exception:
                        ok = False
                msg = f"{pname} must be between {lo} and {hi}"
            if not ok:
                self_valid = False
                widget.setStyleSheet("background:#FFCCCC;")
                self.errors.append(msg or f"{pname} is invalid")

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
            for suf in "ABCD":
                path = values.get(f"PathPin_{suf}", "")
                check = values.get(f"Check_{suf}", "")
                if check and not path:
                    gate_errs.append(f"Check_{suf} requires PathPin_{suf}")
                    for name in (f"Check_{suf}", f"PathPin_{suf}"):
                        widget = self.widgets.get(name)
                        if widget is not None:
                            widget.setStyleSheet("background:#FFCCCC;")
                elif check and len(check) != len(path):
                    gate_errs.append(
                        f"Check_{suf} length must match PathPin_{suf}"
                    )
                    widget = self.widgets.get(f"Check_{suf}")
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
    def __init__(
        self,
        macro_map: dict[int, MacroDef] | None,
        parent=None,
        *,
        title: str | None = None,
    ) -> None:
        super().__init__(parent)
        self._custom_title = title
        self.setWindowTitle(title or "New Complex")
        self.resize(600, 500)
        # Always build the macro map from the YAML spec to avoid relying on the
        # MDB for parameter information.
        self.macro_map = discover_macro_map(None)
        self.sub_components: list[SubComponent] = []
        self.current_index: Optional[int] = None

        layout = QtWidgets.QVBoxLayout(self)
        self.step_indicator = StepIndicator(
            ["Basics", "Subcomponents", "Parameters", "Review"]
        )
        layout.addWidget(self.step_indicator)
        # Parameters step should not be directly clickable
        if len(getattr(self.step_indicator, "_labels", [])) > 2:
            self.step_indicator._labels[2].setEnabled(False)
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
        self.step_indicator.step_clicked.connect(self._on_step_clicked)
        self.stack.currentChanged.connect(self._on_page_changed)
        self._mapping_ok = False  # ② flag updated by pin-table
        self._params_ok = True
        self.mode = "new"
        self.editing_complex_id: Optional[int] = None

        self._update_edit_buttons(-1)

        self._update_nav()
        self._on_page_changed(self.stack.currentIndex())

    def _on_page_changed(self, idx: int) -> None:
        page = self.stack.widget(idx)
        if page is self.basics_page:
            step = 0
        elif page in (self.list_page, self.macro_page):
            step = 1
        elif page is self.param_page:
            step = 2
        elif page is self.review_page:
            step = 3
        else:
            step = 0
        self._update_step_indicator(step)

    def _update_step_indicator(self, current_idx: int) -> None:
        self.step_indicator.set_current(current_idx)

    def _on_step_clicked(self, idx: int) -> None:
        if idx == 2:
            # Parameters page should only be opened via explicit buttons
            return
        if idx == 0:
            self.stack.setCurrentWidget(self.basics_page)
        elif idx == 1:
            self.stack.setCurrentWidget(self.list_page)
        elif idx == 3:
            self.review_page.populate(self.sub_components)
            self.stack.setCurrentWidget(self.review_page)
        self._update_nav()

    @classmethod
    def from_wizard_prefill(
        cls, prefill: WizardPrefill, parent=None, *, title: str | None = None
    ) -> "NewComplexWizard":
        """Build a wizard pre-populated from :class:`WizardPrefill`."""

        wiz = cls(None, parent, title=title)
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
            s_xml = sc.get("pins_s") or sc.get("S")
            subc = SubComponent(mi, pins)
            val_field = sc.get("value")
            if val_field not in (None, ""):
                setattr(subc, "value", val_field)
            macros: dict[str, dict[str, str]] = {}
            pin_s_error = False
            if s_xml:
                try:
                    macros = xml_to_params(s_xml)
                except Exception:
                    macros = {}
                    pin_s_error = True
                else:
                    if not macros:
                        pin_s_error = True
            sel = sc.get("macro_name") or (macros and next(iter(macros))) or mi.name
            if sel not in macros:
                macros.setdefault(sel, {})
            mi.name = sel
            mi.params = dict(macros.get(sel, {}))
            if val_field not in (None, ""):
                key = next(
                    (
                        k
                        for k in ALLOWED_PARAMS.get(
                            resolve_macro_name(mi.name), {}
                        ).keys()
                        if k.lower() == "value"
                    ),
                    None,
                )
                if key and key not in mi.params:
                    mi.params[key] = str(val_field)
                    macros.setdefault(mi.name, {})[key] = str(val_field)
            setattr(subc, "_pins_s_macros", macros)
            if s_xml:
                setattr(subc, "pin_s", s_xml)
            if pin_s_error:
                setattr(subc, "pin_s_error", True)
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
        wiz._mapping_ok = True
        wiz.stack.setCurrentWidget(wiz.review_page)
        wiz._update_nav()
        return wiz

    @classmethod
    def from_existing(
        cls,
        prefill: WizardPrefill,
        complex_id: int,
        parent=None,
        *,
        title: str | None = None,
    ) -> "NewComplexWizard":
        """Open the wizard in *edit* mode using ``prefill`` data."""

        wiz = cls(None, parent, title=title or prefill.complex_name or None)
        wiz.mode = "edit"
        wiz.editing_complex_id = complex_id

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
            s_xml = sc.get("pins_s") or sc.get("S")
            subc = SubComponent(mi, pins)
            val_field = sc.get("value")
            if val_field not in (None, ""):
                setattr(subc, "value", val_field)
            macros: dict[str, dict[str, str]] = {}
            pin_s_error = False
            if s_xml:
                try:
                    macros = xml_to_params(s_xml)
                except Exception:
                    macros = {}
                    pin_s_error = True
                else:
                    if not macros:
                        pin_s_error = True
            sel = sc.get("macro_name") or (macros and next(iter(macros))) or mi.name
            if sel not in macros:
                macros.setdefault(sel, {})
            mi.name = sel
            mi.params = dict(macros.get(sel, {}))
            if val_field not in (None, ""):
                key = next(
                    (
                        k
                        for k in ALLOWED_PARAMS.get(
                            resolve_macro_name(mi.name), {}
                        ).keys()
                        if k.lower() == "value"
                    ),
                    None,
                )
                if key and key not in mi.params:
                    mi.params[key] = str(val_field)
                    macros.setdefault(mi.name, {})[key] = str(val_field)
            setattr(subc, "_pins_s_macros", macros)
            if s_xml:
                setattr(subc, "pin_s", s_xml)
            if pin_s_error:
                setattr(subc, "pin_s_error", True)
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
        macros = getattr(sc, "_pins_s_macros", getattr(sc, "all_macros", {}))
        if isinstance(macros, dict):
            sc.macro.params = dict(macros.get(sc.macro.name, {}))
            if sc.macro.params:
                self.param_page.warn_label.hide()
            else:
                self.param_page.warn_label.setText("No PinS found")
                self.param_page.warn_label.show()
        else:
            self.param_page.warn_label.setText("No PinS found")
            self.param_page.warn_label.show()
        if getattr(sc, "pin_s_error", False):
            self.param_page.pin_s_banner.show()
        else:
            self.param_page.pin_s_banner.hide()
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
        macros = getattr(sc, "_pins_s_macros", getattr(sc, "all_macros", {}))
        macros[sc.macro.name] = all_vals
        setattr(sc, "_pins_s_macros", macros)
        xml = params_to_xml(macros, encoding="utf-16", schema=ALLOWED_PARAMS)
        setattr(sc, "pin_s", xml.decode("utf-16"))
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
