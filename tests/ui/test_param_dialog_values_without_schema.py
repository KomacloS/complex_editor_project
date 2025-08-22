import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "src")))

from PyQt6 import QtWidgets
from complex_editor.ui.param_editor_dialog import ParamEditorDialog
from complex_editor.domain import MacroDef


def test_dialog_renders_values_without_schema(qtbot):
    macro = MacroDef(1, "GATE", [])
    dlg = ParamEditorDialog(macro, {"P": "2"})
    qtbot.addWidget(dlg)
    w = dlg._widgets.get("P")
    assert isinstance(w, QtWidgets.QLineEdit)
    assert w.text() == "2"
