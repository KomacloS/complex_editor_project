import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "src")))

from PyQt6 import QtCore
from complex_editor.ui.complex_editor import ComplexEditor
from complex_editor.domain import MacroDef, MacroParam


def _macro_map():
    return {1: MacroDef(1, "M1", []), 2: MacroDef(2, "M2", [MacroParam("P", "INT", None, "0", "10")])}


def test_macro_combo_delegate_updates_model(qtbot):
    editor = ComplexEditor(_macro_map())
    qtbot.addWidget(editor)
    row = editor.model.add_row()
    idx = editor.model.index(row, 1)
    delegate = editor.table.itemDelegateForColumn(1)
    combo = delegate.createEditor(editor.table, None, idx)
    delegate.setEditorData(combo, idx)
    combo.setCurrentIndex(combo.findData(2))
    delegate.setModelData(combo, editor.model, idx)
    assert editor.model.rows[row].macro_id == 2
    assert editor.model.data(idx, QtCore.Qt.ItemDataRole.DisplayRole) == "M2"
