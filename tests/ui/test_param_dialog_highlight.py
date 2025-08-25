import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "src")))

from PyQt6 import QtWidgets
from complex_editor.domain import MacroDef, MacroParam
from complex_editor.ui.param_editor_dialog import ParamEditorDialog


def test_param_dialog_highlight_present_keys(qtbot):
    params = [
        MacroParam("BurstNr", "INT", "0", None, None),
        MacroParam("StartFreq", "INT", "0", None, None),
        MacroParam("StopFreq", "INT", "0", None, None),
        MacroParam("Other", "INT", "0", None, None),
    ]
    macro = MacroDef(0, "FNODE", params)
    values = {"BurstNr": "5", "StartFreq": "200", "StopFreq": "50000"}
    dlg = ParamEditorDialog(macro, values)
    qtbot.addWidget(dlg)
    widgets = dlg._widgets
    assert widgets["BurstNr"].styleSheet() == "background:#C5F1FF"
    assert widgets["StartFreq"].styleSheet() == "background:#C5F1FF"
    assert widgets["StopFreq"].styleSheet() == "background:#C5F1FF"
    assert widgets["Other"].styleSheet() == ""
