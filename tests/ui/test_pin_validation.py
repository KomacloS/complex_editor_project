import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "src")))

from PyQt6 import QtCore
from complex_editor.ui.validators import validate_pins
from complex_editor.ui.complex_editor import ComplexEditor
from complex_editor.domain import MacroDef, MacroParam


def test_pin_validation():
    assert validate_pins([1, 2, 3, 4], 4)[0]
    assert not validate_pins([1, 2, 2], 4)[0]
    assert not validate_pins([0, 1], 4)[0]


def _macro_map():
    return {1: MacroDef(1, "M", [MacroParam("P", "INT", None, "0", "5")])}


def test_pin_delegate_rejects_invalid(qtbot):
    editor = ComplexEditor(_macro_map())
    qtbot.addWidget(editor)
    editor.pn_edit.setText("CX")
    editor.pin_spin.setValue(4)
    row = editor.model.add_row()
    editor.model.setData(editor.model.index(row, 1), 1, QtCore.Qt.ItemDataRole.EditRole)
    delegate = editor.table.itemDelegateForColumn(2)
    idx = editor.model.index(row, 2)
    spin = delegate.createEditor(editor.table, None, idx)
    delegate.setEditorData(spin, idx)
    spin.setValue(1)
    delegate.setModelData(spin, editor.model, idx)
    idx_b = editor.model.index(row, 3)
    spin_b = delegate.createEditor(editor.table, None, idx_b)
    delegate.setEditorData(spin_b, idx_b)
    spin_b.setValue(1)  # duplicate
    delegate.setModelData(spin_b, editor.model, idx_b)
    editor._update_state()
    assert not editor.save_btn.isEnabled()
    spin_b.setValue(5)  # out of range -> clamped to 4
    delegate.setModelData(spin_b, editor.model, idx_b)
    assert editor.model.rows[row].pins[1] <= 4


def test_cross_row_duplicate_pins_disable_save(qtbot):
    editor = ComplexEditor(_macro_map())
    qtbot.addWidget(editor)
    editor.pn_edit.setText("CX")
    editor.pin_spin.setValue(4)
    r1 = editor.model.add_row()
    r2 = editor.model.add_row()
    editor.model.setData(editor.model.index(r1, 1), 1, QtCore.Qt.ItemDataRole.EditRole)
    editor.model.setData(editor.model.index(r2, 1), 1, QtCore.Qt.ItemDataRole.EditRole)
    delegate = editor.table.itemDelegateForColumn(2)
    idx1 = editor.model.index(r1, 2)
    sp1 = delegate.createEditor(editor.table, None, idx1)
    delegate.setEditorData(sp1, idx1)
    sp1.setValue(1)
    delegate.setModelData(sp1, editor.model, idx1)
    idx2 = editor.model.index(r2, 2)
    sp2 = delegate.createEditor(editor.table, None, idx2)
    delegate.setEditorData(sp2, idx2)
    sp2.setValue(1)
    delegate.setModelData(sp2, editor.model, idx2)
    editor._update_state()
    assert not editor.save_btn.isEnabled()
