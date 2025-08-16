from __future__ import annotations

import os
import sys
import types

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

sys.modules.setdefault("pyodbc", types.ModuleType("pyodbc"))

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src")))

from PyQt6 import QtWidgets  # noqa: E402

from complex_editor.domain import MacroDef, MacroParam  # noqa: E402
from complex_editor.param_spec import ALLOWED_PARAMS, resolve_macro_name  # noqa: E402
from complex_editor.ui.new_complex_wizard import ParamPage  # noqa: E402
from complex_editor.domain.pinxml import MacroInstance, PinXML  # noqa: E402


@pytest.fixture(scope="session")
def qapp():
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    return app


def _macro_from_spec(name: str, alias: str | None = None) -> MacroDef:
    spec = ALLOWED_PARAMS[name]
    params = []
    for pname, s in spec.items():
        if isinstance(s, dict):
            params.append(
                MacroParam(
                    pname,
                    s.get("type", "INT"),
                    str(s.get("default")) if s.get("default") is not None else None,
                    str(s.get("min")) if s.get("min") is not None else None,
                    str(s.get("max")) if s.get("max") is not None else None,
                )
            )
        elif isinstance(s, list):
            params.append(MacroParam(pname, "ENUM", s[0] if s else None, None, None))
        else:
            params.append(MacroParam(pname, "INT", None, None, None))
    return MacroDef(0, alias or name, params)


def test_unknown_macro_string_defaults_are_text(qapp):
    macro = MacroDef(0, "MYSTERY", [MacroParam("TestResult", "INT", None, None, None), MacroParam("MeasureType", "INT", None, None, None)])
    page = ParamPage()
    page.build_widgets(macro, {"TestResult": "Default", "MeasureType": "OFF"})
    assert isinstance(page.widgets["TestResult"], QtWidgets.QComboBox)
    assert isinstance(page.widgets["MeasureType"], QtWidgets.QComboBox)
    assert page.errors == []
    assert page.param_values() == {"TestResult": "Default", "MeasureType": "OFF"}


def test_alias_resolution(qapp):
    assert resolve_macro_name("fan") == "FAN"
    assert resolve_macro_name("FANCONTROL") == "FAN"
    macro = _macro_from_spec("FAN", alias="FANCONTROL")
    page = ParamPage()
    page.build_widgets(macro, {"TolPosI": "10"})
    assert "TolPosI" in page.widgets
    assert isinstance(page.widgets["TolPosI"], QtWidgets.QSpinBox)
    assert page.widgets["TolPosI"].maximum() == 1000


def test_roundtrip_fallback(qapp):
    xml = PinXML.serialize([MacroInstance("UNKNOWN", {"Mode": "Default"})])
    parsed = PinXML.deserialize(xml)
    macro = MacroDef(0, parsed[0].name, [MacroParam("Mode", "INT", None, None, None)])
    page = ParamPage()
    page.build_widgets(macro, parsed[0].params)
    out_params = page.param_values()
    xml2 = PinXML.serialize([MacroInstance(parsed[0].name, out_params)])
    assert PinXML.deserialize(xml) == PinXML.deserialize(xml2)
