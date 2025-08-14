import os, sys, types
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.modules.setdefault("pyodbc", types.ModuleType("pyodbc"))

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from complex_editor.io.buffer_loader import WizardPrefill  # noqa: E402
from complex_editor.ui.new_complex_wizard import NewComplexWizard  # noqa: E402
from PyQt6 import QtWidgets  # noqa: E402


def test_voltageregulator_enum_defaults(qtbot):
    prefill = WizardPrefill(
        complex_name="V",
        sub_components=[{"macro_name": "VOLTAGEREGULATOR", "pins": [1]}],
    )
    wiz = NewComplexWizard.from_wizard_prefill(prefill)
    qtbot.addWidget(wiz)
    wiz.activate_pin_mapping_for(0)
    wiz._open_param_page()
    power_widget = wiz.param_page.widgets.get("PowerSet")
    assert isinstance(power_widget, QtWidgets.QComboBox)
    assert power_widget.currentText() == "ON"
    test_widget = wiz.param_page.widgets.get("TestResult")
    assert isinstance(test_widget, QtWidgets.QComboBox)
    assert test_widget.currentText() == "Default"
