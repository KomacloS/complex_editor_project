import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src")))

from PyQt6 import QtWidgets

from complex_editor.ui.dialogs.pin_assignment_dialog import PinAssignmentDialog


def test_pin_assignment_dialog_validation(qtbot):
    dlg = PinAssignmentDialog(["A", "B"], ["1", "2"])
    qtbot.addWidget(dlg)
    dlg._combos[0].setCurrentText("1")
    dlg._combos[1].setCurrentText("1")
    ok_btn = dlg.buttons.button(QtWidgets.QDialogButtonBox.StandardButton.Ok)
    assert not ok_btn.isEnabled()
    dlg._combos[1].setCurrentText("2")
    assert ok_btn.isEnabled()
    ok_btn.click()
    assert dlg.mapping() == {"A": "1", "B": "2"}
