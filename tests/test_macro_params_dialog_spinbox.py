import pytest
from PyQt6 import QtWidgets, QtCore, QtGui
from complex_editor.ui.param_editor import MacroParamsDialog


def test_macro_params_dialog_spinbox_allows_float_and_wheel(qtbot):
    dlg = MacroParamsDialog({"Value": "1.5"})
    qtbot.addWidget(dlg)
    spin = dlg.table.cellWidget(0, 1)
    assert isinstance(spin, QtWidgets.QDoubleSpinBox)
    assert spin.value() == pytest.approx(1.5)
    spin.setValue(2.25)
    assert dlg.params()["Value"] == "2.25"
    evt = QtGui.QWheelEvent(
        QtCore.QPointF(),
        QtCore.QPointF(),
        QtCore.QPoint(),
        QtCore.QPoint(0, 120),
        QtCore.Qt.MouseButton.NoButton,
        QtCore.Qt.KeyboardModifier.NoModifier,
        QtCore.Qt.ScrollPhase.ScrollUpdate,
        False,
    )
    QtWidgets.QApplication.sendEvent(spin, evt)
    assert float(dlg.params()["Value"]) == pytest.approx(2.35, abs=0.001)
