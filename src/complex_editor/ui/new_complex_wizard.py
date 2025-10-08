from __future__ import annotations

"""Compatibility shim for the removed :class:`NewComplexWizard`.

This lightweight adapter exposes a handful of attributes that legacy tests
expect while delegating all real work to :class:`~complex_editor.ui.complex_editor.ComplexEditor`.
"""

from typing import List

from PyQt6 import QtCore, QtWidgets

from ..domain import ComplexDevice, MacroInstance, MacroDef, SubComponent
from .complex_editor import ComplexEditor


class _BasicsPage(QtWidgets.QWidget):
    """Expose basic widgets mirroring the editor's fields."""

    def __init__(self, pin_spin: QtWidgets.QSpinBox, pn_edit: QtWidgets.QLineEdit) -> None:
        super().__init__()
        _ = QtWidgets.QFormLayout(self)  # placeholder layout (legacy tests expect a widget)
        self.pin_spin = QtWidgets.QSpinBox()
        self.pin_spin.setRange(pin_spin.minimum(), pin_spin.maximum())
        self.pin_spin.setValue(pin_spin.value())
        self.pn_edit = QtWidgets.QLineEdit()
        self.pn_edit.setText(pn_edit.text())
        self.alt_edit = QtWidgets.QLineEdit()
        self.alt_edit.setText(
            getattr(pn_edit.parent(), "alt_pn_edit", QtWidgets.QLineEdit()).text()
        )
        # two-way synchronization so tests manipulating either widget stay in sync
        self.pin_spin.valueChanged.connect(pin_spin.setValue)
        pin_spin.valueChanged.connect(self.pin_spin.setValue)
        self.pn_edit.textChanged.connect(pn_edit.setText)
        pn_edit.textChanged.connect(self.pn_edit.setText)
        if hasattr(pn_edit.parent(), "alt_pn_edit"):
            alt_src = pn_edit.parent().alt_pn_edit
            self.alt_edit.textChanged.connect(alt_src.setText)
            alt_src.textChanged.connect(self.alt_edit.setText)


class NewComplexWizard(QtWidgets.QDialog):
    """Backwards compatible facade around :class:`ComplexEditor`.

    The original multi‑page wizard was removed in favour of a single dialog
    (:class:`ComplexEditor`).  Some tests (and potentially third‑party scripts)
    still import ``NewComplexWizard``; this shim keeps them working by exposing a
    similar surface API and forwarding work to the editor.
    """

    def __init__(self, macro_map, parent=None, *, title: str | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(title or "New Complex")
        # embed the real editor; keep as child so Qt manages its lifetime
        self._editor = ComplexEditor(macro_map, parent=self)
        self.basics_page = _BasicsPage(self._editor.pin_spin, self._editor.pn_edit)
        self._sub_components: List[SubComponent] = []
        # legacy tests may access pin_mapping_page; provide a minimal stub
        self.pin_mapping_page = MacroPinsPage(macro_map, parent=self)

    # ------------------------------------------------------------ factories
    @classmethod
    def from_existing(cls, prefill, cid, parent=None) -> "NewComplexWizard":
        """Create a wizard pre‑loaded from an object resembling
        :class:`ComplexDevice`.

        ``prefill`` may lack attributes; missing ones default to sensible values.
        """

        macro_map = getattr(prefill, "macro_map", {}) or {}
        wiz = cls(macro_map, parent=parent)
        dev = ComplexDevice(0, [], MacroInstance("", {}))
        dev.id = cid
        dev.pn = getattr(prefill, "pn", "") or ""
        dev.alt_pn = getattr(prefill, "alt_pn", "") or ""
        dev.pin_count = int(getattr(prefill, "pin_count", 0) or 0)
        dev.subcomponents = getattr(prefill, "subcomponents", []) or []
        wiz._editor.load_device(dev)
        return wiz

    @classmethod
    def from_wizard_prefill(cls, prefill, parent=None) -> "NewComplexWizard":
        """Build a wizard pre‑populated from :class:`WizardPrefill` data."""

        macro_map = getattr(prefill, "macro_map", {}) or {}
        wiz = cls(macro_map, parent=parent, title=getattr(prefill, "complex_name", None))
        dev = ComplexDevice(0, [], MacroInstance("", {}))
        dev.pn = getattr(prefill, "complex_name", "") or ""
        dev.pin_count = int(getattr(prefill, "pin_count", 0) or 0)

        subs: List[SubComponent] = []
        for entry in getattr(prefill, "sub_components", []) or []:
            name = entry.get("macro_name") or ""
            pins = [int(p) for p in entry.get("pins", []) if isinstance(p, int)]
            subs.append(SubComponent(MacroInstance(name, {}), tuple(pins)))
        dev.subcomponents = subs
        wiz._editor.load_device(dev)
        return wiz

    # --------------------------------------------------------------- dialog API
    def exec(self) -> int:  # pragma: no cover - simple pass‑through
        result = self._editor.exec()
        if result == QtWidgets.QDialog.DialogCode.Accepted:
            self._sub_components = self._editor.build_device().subcomponents
        return int(result)

    def __getattr__(self, item):  # pragma: no cover - thin delegation
        return getattr(self._editor, item)

    # --------------------------------------------------------- legacy helpers
    @property
    def sub_components(self) -> List[SubComponent]:
        return self._sub_components

    @sub_components.setter
    def sub_components(self, value: List[SubComponent]) -> None:
        self._sub_components = value

    def activate_pin_mapping_for(self, sub_idx: int) -> None:
        """Legacy helper to select a subcomponent row."""
        try:
            self._editor.table.selectRow(sub_idx)
        except Exception:
            pass

    def _open_param_page(self) -> None:
        """Legacy no-op kept for backwards compatibility."""
        return

    def _goto_param_page(self) -> None:
        """Legacy no-op for navigation APIs."""
        return

    def to_complex_device(self) -> ComplexDevice:
        """Return the current device state from the embedded editor."""
        return self._editor.build_device()


# -------------------------------------------------------------------- test shims
class MacroPinsPage(QtWidgets.QWidget):
    """Minimal replacement for the old wizard's pin selection page."""

    def __init__(self, macro_map, parent=None) -> None:
        super().__init__(parent)
        self.macro_map = macro_map or {}
        layout = QtWidgets.QVBoxLayout(self)
        self.macro_combo = QtWidgets.QComboBox()
        for mid, macro in sorted(self.macro_map.items()):
            self.macro_combo.addItem(macro.name, mid)
        layout.addWidget(self.macro_combo)

    def load_from_subcomponent(self, sc: SubComponent) -> None:
        if sc.macro.name:
            idx = self.macro_combo.findText(sc.macro.name)
            if idx >= 0:
                self.macro_combo.setCurrentIndex(idx)
                return
        fid = getattr(sc.macro, "id_function", None)
        if fid is not None:
            pos = self.macro_combo.findData(fid)
            if pos >= 0:
                self.macro_combo.setCurrentIndex(pos)

    # --------------------------- compat helpers ---------------------------
    def set_pin_count(self, total_pads: int) -> None:
        self._total_pads = int(total_pads or 0)

    def checked_pins(self) -> list[int]:
        # no table in the shim; return empty list to keep callers happy
        return []

    def pad_combo_at_row(self, row: int) -> QtWidgets.QComboBox:
        cb = QtWidgets.QComboBox()
        if getattr(self, "_total_pads", 0) > 0:
            cb.addItems([""] + [str(i) for i in range(1, self._total_pads + 1)])
        return cb


class ParamPage(QtWidgets.QWidget):
    """Simplified parameter editor used by unit tests."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.widgets: dict[str, QtWidgets.QWidget] = {}
        self.errors: list[str] = []
        self._layout = QtWidgets.QFormLayout(self)

    def build_widgets(self, macro: MacroDef | None = None, defaults: dict[str, str] | None = None) -> None:
        self.widgets.clear()
        self.errors.clear()
        defaults = defaults or {}
        if macro is None:
            return
        for p in macro.params:
            val = defaults.get(p.name)
            widget: QtWidgets.QWidget
            if p.type == "ENUM" or (val is not None and not _looks_int(val)):
                cb = QtWidgets.QComboBox()
                if val is not None:
                    cb.addItem(val)
                widget = cb
            else:
                spin = QtWidgets.QSpinBox()
                min_val = _maybe_int(p.min)
                max_val = _maybe_int(p.max)
                if min_val is not None:
                    spin.setMinimum(min_val)
                if max_val is not None:
                    spin.setMaximum(max_val)
                default_val = _maybe_int(val) if val is not None else None
                if default_val is not None:
                    spin.setValue(default_val)
                widget = spin
            self.widgets[p.name] = widget
            self._layout.addRow(p.name, widget)

    def param_values(self) -> dict[str, str]:
        result: dict[str, str] = {}
        for name, w in self.widgets.items():
            if isinstance(w, QtWidgets.QComboBox):
                result[name] = w.currentText()
            elif isinstance(w, QtWidgets.QSpinBox):
                result[name] = str(w.value())
        return result


def _looks_int(val: str) -> bool:
    return _maybe_int(val) is not None


def _maybe_int(val) -> int | None:
    if val is None:
        return None
    try:
        return int(str(val).replace(",", "").strip())
    except Exception:
        return None

