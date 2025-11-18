import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from PyQt6 import QtWidgets
from complex_editor.domain import MacroDef, MacroParam
from complex_editor.ui.param_editor_dialog import ParamEditorDialog


def test_param_editor_dialog_returns_only_changed(qtbot):
    macro = MacroDef(0, "MAC", [
        MacroParam("P1", "INT", "0", None, None),
        MacroParam("P2", "INT", "0", None, None),
    ])
    dlg = ParamEditorDialog(macro)
    qtbot.addWidget(dlg)
    widgets = dlg._widgets
    assert isinstance(widgets["P1"], QtWidgets.QSpinBox)
    widgets["P1"].setValue(5)
    assert dlg.params() == {"P1": "5"}


def test_param_editor_dialog_preserves_existing_values(qtbot):
    macro = MacroDef(0, "MAC", [MacroParam("P1", "INT", "0", None, None)])
    dlg = ParamEditorDialog(macro, {"P1": "7"})
    qtbot.addWidget(dlg)
    assert dlg.params() == {"P1": "7"}


def test_param_editor_dialog_can_revert_to_default(qtbot):
    macro = MacroDef(0, "MAC", [MacroParam("P1", "INT", "5", None, None)])
    dlg = ParamEditorDialog(macro, {"P1": "9"})
    qtbot.addWidget(dlg)
    widget = dlg._widgets["P1"]
    assert isinstance(widget, QtWidgets.QSpinBox)
    widget.setValue(5)
    assert dlg.params() == {}
