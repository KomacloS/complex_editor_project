from complex_editor.domain import MacroDef, MacroParam
from complex_editor.ui.param_editor_dialog import ParamEditorDialog
from PyQt6 import QtWidgets


def test_param_editor_dialog_clamps_spinbox(qtbot):
    """Spin boxes should clamp values to the valid range to avoid overflow."""
    big_min = str(-2**40)
    big_max = str(2**40)
    macro = MacroDef(0, "M", [MacroParam("p", "INT", None, big_min, big_max)])
    dlg = ParamEditorDialog(macro)
    qtbot.addWidget(dlg)
    spin = dlg._widgets["p"]
    assert isinstance(spin, QtWidgets.QSpinBox)
    assert spin.minimum() == -2**31
    assert spin.maximum() == 2**31 - 1
