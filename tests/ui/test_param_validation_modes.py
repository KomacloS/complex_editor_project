import os, sys, types
from pathlib import Path
import os, sys, types
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.modules.setdefault("pyodbc", types.ModuleType("pyodbc"))

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from PyQt6 import QtWidgets  # noqa: E402
from complex_editor.io.buffer_loader import WizardPrefill  # noqa: E402
from complex_editor.ui.new_complex_wizard import NewComplexWizard  # noqa: E402
from complex_editor.util.macro_xml_translator import params_to_xml, xml_to_params  # noqa: E402
from complex_editor.param_spec import ALLOWED_PARAMS  # noqa: E402


def _make_wizard(macro, params, qtbot):
    xml = params_to_xml({macro: params}, encoding="utf-16", schema=ALLOWED_PARAMS).decode("utf-16")
    prefill = WizardPrefill(
        complex_name="X",
        sub_components=[{"macro_name": macro, "pins": [1], "pins_s": xml}],
    )
    wiz = NewComplexWizard.from_wizard_prefill(prefill)
    qtbot.addWidget(wiz)
    wiz.activate_pin_mapping_for(0)
    wiz._open_param_page()
    return wiz


def test_enum_validation(qtbot):
    wiz = _make_wizard("VOLTAGEREGULATOR", {"PowerSet": "OFF"}, qtbot)
    assert not wiz.param_page.errors


def test_default_numeric_validation(qtbot):
    wiz = _make_wizard("POWER_CHECK", {"Value": "Default", "TestResult": "Default"}, qtbot)
    assert not wiz.param_page.errors
    wiz._save_params()
    params = xml_to_params(wiz.sub_components[0].pin_s)
    assert params["POWER_CHECK"] == {}


def test_numeric_range_error(qtbot):
    wiz = _make_wizard("FAN", {"TolPosI": "500"}, qtbot)
    w = wiz.param_page.widgets.get("TolPosI")
    assert isinstance(w, QtWidgets.QSpinBox)
    w.setMaximum(5000)
    w.setValue(2000)
    wiz.param_page._validate()
    assert any("TolPosI" in err for err in wiz.param_page.errors)
