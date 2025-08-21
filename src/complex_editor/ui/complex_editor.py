from __future__ import annotations

from typing import Any, Dict, Optional

from PyQt6 import QtCore, QtWidgets

from ..db.mdb_api import MDB, ComplexDevice as DbComplex, SubComponent as DbSub
from ..domain import MacroDef
from ..param_spec import ALLOWED_PARAMS
from ..util.macro_xml_translator import (
    _ensure_text,
    params_to_xml,
    xml_to_params,
)
from .dialogs.pin_assignment_dialog import PinAssignmentDialog
from .dialogs.macro_params_dialog import MacroParamsDialog


class ComplexEditor(QtWidgets.QWidget):
    """Unified editor widget with modal pin/parameter dialogs."""

    dirtyChanged = QtCore.pyqtSignal(bool)
    saved = QtCore.pyqtSignal(int)

    def __init__(
        self,
        macro_map: dict[int, MacroDef] | None = None,
        parent: Optional[QtWidgets.QWidget] = None,
        db: MDB | None = None,
    ) -> None:
        super().__init__(parent)
        self.db = db
        self.macro_map: dict[int, MacroDef] = {}
        self._current_id: int | None = None
        self._pins: list[str] = []
        self.param_values: Dict[str, str] = {}
        self._last_state: Dict[str, Any] = {}

        layout = QtWidgets.QVBoxLayout(self)

        basics_row = QtWidgets.QHBoxLayout()
        self.name_edit = QtWidgets.QLineEdit()
        self.name_edit.setPlaceholderText("Name/PN")
        self.name_edit.textChanged.connect(self._update_save_enabled)
        basics_row.addWidget(self.name_edit)
        self.total_pins_spin = QtWidgets.QSpinBox()
        self.total_pins_spin.setRange(1, 64)
        self.total_pins_spin.setValue(4)
        basics_row.addWidget(self.total_pins_spin)
        layout.addLayout(basics_row)

        self.macro_combo = QtWidgets.QComboBox()
        layout.addWidget(self.macro_combo)

        pin_row = QtWidgets.QHBoxLayout()
        self.pin_label = QtWidgets.QLabel("")
        pin_btn = QtWidgets.QPushButton("Assign Pins…")
        pin_btn.clicked.connect(self._assign_pins)
        pin_row.addWidget(self.pin_label)
        pin_row.addWidget(pin_btn)
        layout.addLayout(pin_row)

        param_row = QtWidgets.QHBoxLayout()
        self.param_label = QtWidgets.QLabel("")
        param_btn = QtWidgets.QPushButton("Edit Parameters…")
        param_btn.clicked.connect(self._edit_params)
        param_row.addWidget(self.param_label)
        param_row.addWidget(param_btn)
        layout.addLayout(param_row)

        btn_row = QtWidgets.QHBoxLayout()
        self.save_btn = QtWidgets.QPushButton("Save")
        self.save_btn.clicked.connect(self.save_complex)
        self.save_btn.setEnabled(False)
        cancel_btn = QtWidgets.QPushButton("Cancel")
        cancel_btn.clicked.connect(self._on_cancel)
        btn_row.addWidget(self.save_btn)
        btn_row.addWidget(cancel_btn)
        layout.addLayout(btn_row)

        if macro_map:
            self.set_macro_map(macro_map)
    # ------------------------------------------------------------------ helpers
    def set_macro_map(self, macro_map: dict[int, MacroDef]) -> None:
        self.macro_map = macro_map or {}
        self.macro_combo.clear()
        for fid, macro in sorted(self.macro_map.items()):
            self.macro_combo.addItem(macro.name, fid)
        self._update_save_enabled()

    def _current_macro(self) -> MacroDef | None:
        data = self.macro_combo.currentData()
        if data is None:
            return None
        return self.macro_map.get(int(data))

    def _assign_pins(self) -> None:
        macro_pins = ["A", "B", "C", "D"]
        total = self.total_pins_spin.value() or 32
        pads = [str(i) for i in range(1, total + 1)]
        mapping = {p: v for p, v in zip(macro_pins, self._pins) if v}
        dlg = PinAssignmentDialog(macro_pins, pads, mapping, self)
        if dlg.exec() == QtWidgets.QDialog.DialogCode.Accepted:
            mapping = dlg.mapping()
            self._pins = [mapping.get(p, "") for p in macro_pins]
            self.pin_label.setText(
                ", ".join(mapping.get(p, "") for p in macro_pins if mapping.get(p, ""))
            )
            self._update_save_enabled()

    def _edit_params(self) -> None:
        macro = self._current_macro()
        if not macro:
            return
        dlg = MacroParamsDialog(macro, self.param_values, self)
        if dlg.exec() == QtWidgets.QDialog.DialogCode.Accepted:
            self.param_values = dlg.values()
            summary = ", ".join(
                f"{k}={v}" for k, v in list(self.param_values.items())[:3]
            )
            self.param_label.setText(summary)

    def _update_save_enabled(self) -> None:
        pins = [p.strip() for p in self._pins if p.strip()]
        name_ok = bool(self.name_edit.text().strip())
        self.save_btn.setEnabled(len(set(pins)) >= 2 and name_ok)

    def _revert_to_last_state(self) -> None:
        if not self._last_state:
            self.reset_to_new()
            return
        state = self._last_state
        self._current_id = state.get("current_id")
        self.name_edit.setText(state.get("name", ""))
        self.total_pins_spin.setValue(state.get("total_pins", 4))
        macro_id = state.get("macro_id")
        if macro_id is not None:
            idx = self.macro_combo.findData(macro_id)
            if idx >= 0:
                self.macro_combo.setCurrentIndex(idx)
        self._pins = list(state.get("pins", []))
        self.pin_label.setText(", ".join(p for p in self._pins if p))
        self.param_values = dict(state.get("param_values", {}))
        self.param_label.setText(
            ", ".join(f"{k}={v}" for k, v in self.param_values.items())
        )
        self._update_save_enabled()

    def _on_cancel(self) -> None:
        if self._current_id is None:
            self.reset_to_new()
        else:
            self._revert_to_last_state()

    # ------------------------------------------------------------------ loading
    def reset_to_new(self) -> None:
        self._current_id = None
        self._pins = []
        self.param_values = {}
        self.name_edit.clear()
        self.total_pins_spin.setValue(4)
        self.pin_label.clear()
        self.param_label.clear()
        self._last_state = {}
        self._update_save_enabled()

    def load_complex(self, row: Any | None) -> None:
        if row is None:
            self.reset_to_new()
            return
        cid = getattr(row, "IDCompDesc", row[0])
        self._current_id = int(cid)
        if self.db is not None:
            try:
                cx = self.db.get_complex(self._current_id)
                self.name_edit.setText(cx.name or "")
                self.total_pins_spin.setValue(cx.total_pins or 4)
                if cx.subcomponents:
                    sub = cx.subcomponents[0]
                    idx = self.macro_combo.findData(int(sub.id_function))
                    if idx >= 0:
                        self.macro_combo.setCurrentIndex(idx)
                    self._pins = [
                        str(sub.pins.get(c, "")) if sub.pins.get(c) else ""
                        for c in "ABCD"
                    ]
                    self.pin_label.setText(
                        ", ".join(p for p in self._pins if p)
                    )
                    xml = sub.pins.get("S") or ""
                    self.param_values = {}
                    if xml:
                        try:
                            macros = xml_to_params(xml)
                        except Exception:
                            macros = {}
                        if macros:
                            macro_name = self.macro_combo.currentText()
                            self.param_values = macros.get(macro_name, {}) or next(
                                iter(macros.values()), {},
                            )
                    self.param_label.setText(
                        ", ".join(f"{k}={v}" for k, v in self.param_values.items())
                    )
                    self._update_save_enabled()
                    self._last_state = {
                        "current_id": self._current_id,
                        "name": self.name_edit.text(),
                        "total_pins": self.total_pins_spin.value(),
                        "macro_id": self.macro_combo.currentData(),
                        "pins": list(self._pins),
                        "param_values": dict(self.param_values),
                    }
                    return
            except Exception:
                pass
        self.name_edit.clear()
        self.total_pins_spin.setValue(4)
        id_func = getattr(row, "IDFunction", row[1])
        idx = self.macro_combo.findData(int(id_func))
        if idx >= 0:
            self.macro_combo.setCurrentIndex(idx)
        pins = [getattr(row, f"Pin{c}", row[i + 2]) for i, c in enumerate("ABCD")]
        self._pins = [str(p) if p else "" for p in pins]
        self.pin_label.setText(", ".join(p for p in self._pins if p))
        pin_s = getattr(row, "PinS", row[6] if len(row) > 6 else None)
        self.param_values = {}
        if pin_s:
            try:
                macros = xml_to_params(pin_s)
            except Exception:
                macros = {}
            if macros:
                macro_name = self.macro_combo.currentText()
                self.param_values = macros.get(macro_name, {}) or next(
                    iter(macros.values()), {},
                )
        self.param_label.setText(
            ", ".join(f"{k}={v}" for k, v in self.param_values.items())
        )
        self._update_save_enabled()
        self._last_state = {
            "current_id": self._current_id,
            "name": self.name_edit.text(),
            "total_pins": self.total_pins_spin.value(),
            "macro_id": self.macro_combo.currentData(),
            "pins": list(self._pins),
            "param_values": dict(self.param_values),
        }
    # ------------------------------------------------------------------- save
    def to_update_dict(self) -> dict[str, Any]:
        pins = [p.strip() for p in self._pins if p.strip()]
        if len(set(pins)) < 2:
            raise ValueError("At least two unique pins required")
        data = self.macro_combo.currentData()
        if data is None:
            raise ValueError("No macro selected")
        id_func = int(data)
        macro_name = self.macro_combo.currentText()
        xml = params_to_xml({macro_name: self.param_values}, schema=ALLOWED_PARAMS)
        pad_vals = (pins + [None, None, None, None])[:4]
        return {
            "IDFunction": id_func,
            "PinA": pad_vals[0],
            "PinB": pad_vals[1],
            "PinC": pad_vals[2],
            "PinD": pad_vals[3],
            "PinS": xml,
        }

    def save_complex(self) -> None:
        try:
            fields = self.to_update_dict()
        except Exception as exc:  # pragma: no cover - message box
            QtWidgets.QMessageBox.warning(self, "Invalid", str(exc))
            return

        if self.db is None:
            self.saved.emit(self._current_id or 0)
            return

        try:
            xml = _ensure_text(fields["PinS"])
            pad_vals = [fields.get(f"Pin{c}") for c in "ABCD"]
            updated_sub = DbSub(
                sub_id=None,
                id_function=fields["IDFunction"],
                value="",
                tol_p=None,
                tol_n=None,
                force_bits=None,
                pins={
                    "A": pad_vals[0],
                    "B": pad_vals[1],
                    "C": pad_vals[2],
                    "D": pad_vals[3],
                    "S": xml,
                },
            )
            if self._current_id is None:
                db_cx = DbComplex(
                    comp_id=None,
                    name=self.name_edit.text().strip(),
                    total_pins=self.total_pins_spin.value(),
                    subcomponents=[updated_sub],
                )
                new_id = self.db.add_complex(db_cx)
                self._current_id = new_id
                self.saved.emit(new_id)
            else:
                cx = self.db.get_complex(self._current_id)
                sub_id = cx.subcomponents[0].sub_id if cx.subcomponents else None
                updated_sub.sub_id = sub_id
                if cx.subcomponents:
                    cx.subcomponents[0] = updated_sub
                else:
                    cx.subcomponents.append(updated_sub)
                cx.name = self.name_edit.text().strip()
                cx.total_pins = self.total_pins_spin.value()
                self.db.update_complex(self._current_id, updated=cx)
                self.saved.emit(self._current_id)
        except Exception as exc:  # pragma: no cover - message box
            QtWidgets.QMessageBox.critical(self, "Save failed", str(exc))


__all__ = ["ComplexEditor"]

