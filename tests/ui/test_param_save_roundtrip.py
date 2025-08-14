import os, sys, types
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.modules.setdefault("pyodbc", types.ModuleType("pyodbc"))

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from PyQt6 import QtWidgets  # noqa: E402
from complex_editor.ui.new_complex_wizard import NewComplexWizard  # noqa: E402
from complex_editor.io.buffer_loader import WizardPrefill  # noqa: E402
from complex_editor.util.macro_xml_translator import params_to_xml, xml_to_params  # noqa: E402
from complex_editor.param_spec import ALLOWED_PARAMS  # noqa: E402


def test_param_save_roundtrip(qtbot):
    macros = {
        "POWER_CHECK": {"Value": "7", "TolPos": "20", "TolNeg": "20"},
        "OTHER": {"Foo": "1"},
    }
    xml = params_to_xml(macros, encoding="utf-16", schema=ALLOWED_PARAMS).decode("utf-16")
    prefill = WizardPrefill(
        complex_name="X",
        sub_components=[{"macro_name": "POWER_CHECK", "pins": [1], "pins_s": xml}],
    )
    wiz = NewComplexWizard.from_wizard_prefill(prefill)
    qtbot.addWidget(wiz)
    wiz.activate_pin_mapping_for(0)
    wiz._open_param_page()
    val_widget = wiz.param_page.widgets.get("Value")
    assert isinstance(val_widget, QtWidgets.QSpinBox)
    val_widget.setValue(8)
    wiz._save_params()
    sc = wiz.sub_components[0]
    new_xml = getattr(sc, "pin_s")
    parsed = xml_to_params(new_xml)
    assert parsed["POWER_CHECK"]["Value"] == "8"
    assert "OTHER" in parsed and parsed["OTHER"]["Foo"] == "1"
