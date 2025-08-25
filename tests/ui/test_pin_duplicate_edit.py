import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "src")))

from PyQt6 import QtWidgets
from complex_editor.ui.complex_editor import ComplexEditor
from complex_editor.domain import MacroDef, MacroParam


def _macro_map():
    return {1: MacroDef(1, "M", [MacroParam("P", "INT", None, "0", "10")])}


def test_pin_delegate_allows_duplicates(qtbot):
    editor = ComplexEditor(_macro_map())
    qtbot.addWidget(editor)
    editor.pin_spin.setValue(3)
    row = editor.model.add_row()
    # prepare pins with a duplicate candidate
    editor.model.rows[row].pins = [1, 2, 0, 0]
    delegate = editor.table.itemDelegateForColumn(2)
    spin = QtWidgets.QSpinBox()
    spin.setValue(2)
    delegate.setModelData(spin, editor.model, editor.model.index(row, 2))
    assert editor.model.rows[row].pins[0] == 2
