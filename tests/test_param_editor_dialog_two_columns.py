import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src")))

from PyQt6 import QtWidgets
from complex_editor.ui.param_editor_dialog import ParamEditorDialog
from complex_editor.domain import MacroDef, MacroParam


def test_param_editor_dialog_arranges_two_columns(qtbot):
    params = [MacroParam(f"P{i}", "INT", None, None, None) for i in range(5)]
    macro = MacroDef(1, "MAC", params)
    dlg = ParamEditorDialog(macro)
    qtbot.addWidget(dlg)
    layout = dlg.layout()
    assert isinstance(layout, QtWidgets.QGridLayout)
    assert isinstance(layout.itemAtPosition(0, 0).widget(), QtWidgets.QLabel)
    assert layout.itemAtPosition(0, 0).widget().text() == "P0"
    assert layout.itemAtPosition(1, 0).widget().text() == "P1"
    assert layout.itemAtPosition(2, 0).widget().text() == "P2"
    assert layout.itemAtPosition(0, 2).widget().text() == "P3"
    assert layout.itemAtPosition(1, 2).widget().text() == "P4"

