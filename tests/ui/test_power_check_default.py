import os, sys, types
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.modules.setdefault("pyodbc", types.ModuleType("pyodbc"))

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from complex_editor.io.buffer_loader import WizardPrefill  # noqa: E402
from complex_editor.ui.new_complex_wizard import NewComplexWizard  # noqa: E402
from complex_editor.util.macro_xml_translator import params_to_xml, xml_to_params  # noqa: E402
from complex_editor.param_spec import ALLOWED_PARAMS  # noqa: E402
from PyQt6 import QtWidgets  # noqa: E402


def test_power_check_default(qtbot):
    macros = {"POWER_CHECK": {"Value": "Default", "TestResult": "Default"}}
    xml = params_to_xml(macros, encoding="utf-16", schema=ALLOWED_PARAMS).decode("utf-16")
    prefill = WizardPrefill(
        complex_name="X",
        sub_components=[{"macro_name": "POWER_CHECK", "pins": [1, 2], "pins_s": xml}],
    )
    wiz = NewComplexWizard.from_wizard_prefill(prefill)
    qtbot.addWidget(wiz)
    wiz.activate_pin_mapping_for(0)
    wiz._open_param_page()
    val_widget = wiz.param_page.widgets.get("Value")
    assert isinstance(val_widget, QtWidgets.QSpinBox)
    enum_widget = wiz.param_page.widgets.get("TestResult")
    assert isinstance(enum_widget, QtWidgets.QComboBox)
    assert enum_widget.currentText() == "Default"
    assert not wiz.param_page.errors
    wiz._save_params()
    sc = wiz.sub_components[0]
    parsed = xml_to_params(getattr(sc, "pin_s"))
    assert parsed["POWER_CHECK"] == {}
