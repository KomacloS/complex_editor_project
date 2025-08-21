import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "src")))

from PyQt6 import QtCore
from PyQt6 import QtWidgets
from complex_editor.ui.complex_editor import ComplexEditor
from complex_editor.domain import MacroDef, MacroParam


def _macro_map():
    macro = MacroDef(1, "GATE", [MacroParam("P", "INT", None, "0", "10")])
    return {1: macro}


def test_complex_editor_new_flow(qtbot, monkeypatch):
    editor = ComplexEditor(_macro_map())
    qtbot.addWidget(editor)
    editor.pn_edit.setText("CX1")
    editor.pin_spin.setValue(4)
    row = editor.model.add_row()
    editor.model.setData(editor.model.index(row, 1), 1, QtCore.Qt.ItemDataRole.EditRole)
    editor.model.setData(editor.model.index(row, 2), 1, QtCore.Qt.ItemDataRole.EditRole)
    editor.model.setData(editor.model.index(row, 3), 2, QtCore.Qt.ItemDataRole.EditRole)
    editor.model.setData(editor.model.index(row, 4), 3, QtCore.Qt.ItemDataRole.EditRole)
    editor.model.setData(editor.model.index(row, 5), 4, QtCore.Qt.ItemDataRole.EditRole)
    editor.model.rows[row].params = {"P": "1"}
    editor._update_state()
    assert editor.save_btn.isEnabled()
    editor._on_accept()
    dev = editor.build_device()
    assert dev.pn == "CX1"
    assert dev.subcomponents and dev.subcomponents[0].pins[:2] == [1, 2]
