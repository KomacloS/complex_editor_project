from __future__ import annotations

import importlib.resources
import os
import sys
import types
import logging

import pytest
from complex_editor.utils import yaml_adapter as yaml

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

sys.modules.setdefault("pyodbc", types.ModuleType("pyodbc"))

sys.path.insert(
    0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src"))
)

import complex_editor.logging_cfg  # noqa: F401,E402

from PyQt6 import QtWidgets  # noqa: E402

from complex_editor.domain import MacroDef, MacroParam  # noqa: E402
from complex_editor.ui.new_complex_wizard import ParamPage  # noqa: E402

with (
    importlib.resources.files("complex_editor.resources")
    .joinpath("function_param_allowed.yaml")
    .open("r") as fh
):
    ALLOWED = yaml.safe_load(fh)


def make_macro(name: str) -> MacroDef:
    if name == "FALLBACK":
        params = [
            MacroParam("IntParam", "INT", None, "1", "10"),
            MacroParam("FloatParam", "FLOAT", "0.2", "0.0", "1.0"),
            MacroParam("EnumParam", "ENUM", "A;B;C", None, None),
            MacroParam("BoolParam", "BOOL", "1", None, None),
        ]
        return MacroDef(id_function=999, name=name, params=params)

    allowed = ALLOWED[name]
    params = []
    first = True
    for pname, spec in allowed.items():
        if isinstance(spec, dict):
            if "choices" in spec or spec.get("type") == "ENUM":
                ptype = "ENUM"
                default_val = None if first else spec.get("choices", [None])[0]
                params.append(MacroParam(pname, ptype, default_val, None, None))
                first = False
                continue
            min_v = spec.get("min")
            max_v = spec.get("max")
            is_int = (
                min_v is not None
                and max_v is not None
                and float(min_v).is_integer()
                and float(max_v).is_integer()
            )
            ptype = "INT" if is_int else "FLOAT"
            default_val = None if first else min_v
            if default_val is not None and ptype == "INT":
                default_val = str(int(float(default_val)))
            elif default_val is not None:
                default_val = str(float(default_val))
            params.append(
                MacroParam(
                    pname,
                    ptype,
                    default_val,
                    str(min_v) if min_v is not None else None,
                    str(max_v) if max_v is not None else None,
                )
            )
        elif isinstance(spec, list):
            ptype = "ENUM"
            default = None if first else str(spec[0])
            params.append(MacroParam(pname, ptype, default, None, None))
        else:
            params.append(MacroParam(pname, "INT", None, None, None))
        first = False
    return MacroDef(id_function=0, name=name, params=params)


@pytest.fixture(scope="session")
def qapp():
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    return app


ALL_MACROS = [k for k in ALLOWED.keys() if k != "version"]


@pytest.mark.parametrize("macro_name", ALL_MACROS)
def test_param_page_build(qapp, macro_name):
    macro = make_macro(macro_name)
    page = ParamPage()
    page.build_widgets(macro, {})
    allowed = ALLOWED.get(macro_name, {})

    assert page.required == {p.name for p in macro.params if p.default is None}

    for p in macro.params:
        widget = page.widgets[p.name]
        spec = allowed.get(p.name)
        if isinstance(spec, dict):
            if "choices" in spec or spec.get("type") == "ENUM":
                assert isinstance(widget, QtWidgets.QComboBox)
                assert [widget.itemText(i) for i in range(widget.count())] == [
                    str(x) for x in spec.get("choices", [])
                ]
                expected = spec.get("default") if p.default is None else p.default
                if expected is not None:
                    assert widget.currentText() == str(expected)
                assert widget.findText("__invalid__") == -1
            else:
                min_v = spec.get("min")
                max_v = spec.get("max")
                int_range = (
                    min_v is not None
                    and max_v is not None
                    and float(min_v).is_integer()
                    and float(max_v).is_integer()
                    and all(
                        -2147483648 <= int(float(v)) <= 2147483647
                        for v in (min_v, max_v)
                    )
                )
                if int_range:
                    assert isinstance(widget, QtWidgets.QSpinBox)
                    assert widget.minimum() == int(float(min_v))
                    assert widget.maximum() == int(float(max_v))
                    init = p.default if p.default is not None else min_v
                    if init is not None:
                        assert widget.value() == int(float(init))
                    widget.setValue(widget.maximum() + 5)
                    assert widget.value() <= widget.maximum()
                else:
                    if macro_name == "GATE" and p.name.startswith("Check_"):
                        assert isinstance(widget, QtWidgets.QLineEdit)
                    else:
                        assert isinstance(widget, QtWidgets.QDoubleSpinBox)
                    if not isinstance(widget, QtWidgets.QLineEdit):
                        if min_v is not None:
                            assert widget.minimum() == pytest.approx(float(min_v), abs=0.01)
                        if max_v is not None:
                            assert widget.maximum() == pytest.approx(float(max_v), abs=0.01)
                        init = p.default if p.default is not None else min_v
                        if init is not None:
                            assert widget.value() == pytest.approx(float(init), abs=0.01)
                        widget.setValue(widget.maximum() * 2)
                        assert widget.value() <= widget.maximum()
        elif isinstance(spec, list):
            assert isinstance(widget, QtWidgets.QComboBox)
            assert [widget.itemText(i) for i in range(widget.count())] == [
                str(x) for x in spec
            ]
            expected = spec[0] if p.default is None else p.default
            assert widget.currentText() == str(expected)
            assert widget.findText("__invalid__") == -1
        else:
            if p.type == "INT":
                assert isinstance(widget, QtWidgets.QSpinBox)
                if p.min is not None:
                    assert widget.minimum() == int(p.min)
                if p.max is not None:
                    assert widget.maximum() == int(p.max)
            elif p.type == "FLOAT":
                assert isinstance(widget, QtWidgets.QDoubleSpinBox)
                if p.min is not None:
                    assert widget.minimum() == float(p.min)
                if p.max is not None:
                    assert widget.maximum() == float(p.max)
            elif p.type == "BOOL":
                assert isinstance(widget, QtWidgets.QCheckBox)
            elif p.type == "ENUM":
                assert isinstance(widget, QtWidgets.QComboBox)
                choices = (p.default or p.min or "").split(";")
                if len(choices) > 1:
                    assert [
                        widget.itemText(i) for i in range(widget.count())
                    ] == choices
            else:
                assert isinstance(widget, QtWidgets.QLineEdit)


def test_param_page_build_missing_macro(qapp):
    """Macros without YAML definitions should still allow editing."""
    macro = make_macro("FALLBACK")
    page = ParamPage()
    page.build_widgets(macro, {"IntParam": "5", "EnumParam": "OFF"})
    assert not page.group_box.isHidden()
    assert not page.warn_label.isHidden()
    assert "could not be found" in page.warn_label.text()
    assert isinstance(page.widgets["IntParam"], QtWidgets.QSpinBox)
    assert isinstance(page.widgets["EnumParam"], QtWidgets.QComboBox)


def test_param_page_missing_banner(qapp, caplog):
    macro = MacroDef(id_function=1, name="NOPE", params=[])
    page = ParamPage()
    with caplog.at_level(logging.WARNING):
        page.build_widgets(macro, {})
    assert not page.warn_label.isHidden()
    assert "could not be found" in page.warn_label.text()
    assert any(
        "Macro NOPE has no parameter definition in DB or YAML" in rec.getMessage()
        for rec in caplog.records
    )


def test_gate_check_optional(qapp):
    macro = MacroDef(
        id_function=1,
        name="GATE",
        params=[
            MacroParam("PathPin_A", None, None, None, None),
            MacroParam("Check_A", None, None, None, None),
        ],
    )
    page = ParamPage()
    page.build_widgets(macro, {})
    assert "Check_A" not in page.required
    path = page.widgets["PathPin_A"]
    check = page.widgets["Check_A"]
    assert isinstance(path, QtWidgets.QLineEdit)
    assert isinstance(check, QtWidgets.QLineEdit)
    path.setText("0101")
    check.setText("")
    page._validate()
    assert page.errors == []
    assert "background:#FFCCCC" not in check.styleSheet()


def test_gate_check_length_mismatch(qapp):
    macro = MacroDef(
        id_function=1,
        name="GATE",
        params=[
            MacroParam("PathPin_A", None, None, None, None),
            MacroParam("Check_A", None, None, None, None),
        ],
    )
    page = ParamPage()
    page.build_widgets(macro, {})
    path = page.widgets["PathPin_A"]
    check = page.widgets["Check_A"]
    path.setText("0101")
    check.setText("0")
    page._validate()
    assert any("Check_A" in e and "length" in e for e in page.errors)
    assert "background:#FFCCCC" in check.styleSheet()
