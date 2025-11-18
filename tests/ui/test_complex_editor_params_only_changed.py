import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from PyQt6 import QtWidgets

from complex_editor.domain import MacroDef, MacroParam
from complex_editor.ui.complex_editor import ComplexEditor


def test_complex_editor_stores_only_changed_params(monkeypatch, qtbot):
    macro = MacroDef(1, "MAC", [MacroParam("GAIN", "INT", "0", None, None)])
    editor = ComplexEditor({1: macro})
    qtbot.addWidget(editor)
    row_idx = editor.model.add_row()
    editor.model.rows[row_idx].macro_id = 1

    class DummyDialog:
        called = []

        def __init__(self, macro_def, values, parent):
            self.values = values

        def exec(self):
            return QtWidgets.QDialog.DialogCode.Accepted

        def params(self, *, only_changed=True):
            DummyDialog.called.append(only_changed)
            return {"GAIN": "7"}

    monkeypatch.setattr("complex_editor.ui.complex_editor.ParamEditorDialog", DummyDialog)

    editor._open_param_editor(row_idx)

    assert DummyDialog.called == [True]
    assert editor.model.rows[row_idx].params == {"GAIN": "7"}
