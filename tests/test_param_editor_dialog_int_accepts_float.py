from complex_editor.domain import MacroDef, MacroParam
from complex_editor.ui.param_editor_dialog import ParamEditorDialog
from PyQt6 import QtWidgets


def test_param_editor_dialog_int_accepts_float(qtbot):
    """Float values for INT parameters should not crash the dialog."""
    macro = MacroDef(0, "M", [MacroParam("p", "INT", None, None, None)])
    dlg = ParamEditorDialog(macro, {"p": "4.9"})
    qtbot.addWidget(dlg)
    spin = dlg._widgets["p"]
    assert isinstance(spin, QtWidgets.QSpinBox)
    assert spin.value() == 4
    assert dlg.params()["p"] == "4"
