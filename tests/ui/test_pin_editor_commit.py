import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "src")))

from PyQt6 import QtCore
from complex_editor.ui.complex_editor import ComplexEditor
from complex_editor.domain import MacroDef, MacroParam


def _macro_map():
    return {1: MacroDef(1, "M", [MacroParam("P", "INT", None, "0", "10")])}


def test_pin_editor_commit(qtbot, monkeypatch):
    editor = ComplexEditor(_macro_map())
    qtbot.addWidget(editor)
    editor.pn_edit.setText("CX")
    editor.pin_spin.setValue(10)
    row = editor.model.add_row()
    editor.model.setData(editor.model.index(row, 1), 1, QtCore.Qt.ItemDataRole.EditRole)
    editor._update_state()
    idx = editor.model.index(row, 2)
    editor.table.setCurrentIndex(idx)
    editor.table.edit(idx)
    qtbot.waitUntil(lambda: editor.table.state() == editor.table.State.EditingState)
    line = editor.table.focusWidget()
    qtbot.keyClicks(line, "7")

    def fake_commit(widget):
        editor.model.setData(idx, int(line.text()), QtCore.Qt.ItemDataRole.EditRole)

    def fake_close(*_args, **_kwargs):
        pass

    monkeypatch.setattr(editor.table, "commitData", fake_commit)
    monkeypatch.setattr(editor.table, "closeEditor", fake_close)

    editor._on_accept()
    dev = editor.build_device()
    assert dev.subcomponents[0].pins[0] == 7
