import os, sys, types
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.modules.setdefault("pyodbc", types.ModuleType("pyodbc"))

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from complex_editor.io.buffer_loader import load_complex_from_buffer_json, to_wizard_prefill  # noqa: E402
from complex_editor.ui.new_complex_wizard import NewComplexWizard  # noqa: E402
from complex_editor.util.macro_xml_translator import xml_to_params, params_to_xml  # noqa: E402
from complex_editor.param_spec import ALLOWED_PARAMS  # noqa: E402
from PyQt6 import QtWidgets  # noqa: E402


def _resolver(name: str):
    return {"DIODE": 3}.get(name.upper())


def _normalizer(pin_map):
    return pin_map


@pytest.mark.parametrize("remove_value", [False, True])
def test_pins_preload_buffer(qtbot, remove_value):
    path = Path(__file__).resolve().parents[2] / "tools" / "buffer.json"
    buf = load_complex_from_buffer_json(path)
    pre = to_wizard_prefill(buf, _resolver, _normalizer)

    target = None
    xml_value = None
    for sc in pre.sub_components:
        s_xml = sc.get("pins_s")
        if not s_xml or sc.get("value") in (None, ""):
            continue
        macros = xml_to_params(s_xml)
        params = macros.get(sc["macro_name"], {}) if sc.get("macro_name") else {}
        if any(k.lower() == "value" for k in params):
            target = sc
            xml_value = params[next(k for k in params if k.lower() == "value")]
            break
    assert target is not None
    if remove_value:
        macros = xml_to_params(target["pins_s"])
        macros[target["macro_name"]].pop("Value", None)
        target = dict(target)
        target["pins_s"] = params_to_xml(macros, encoding="utf-16", schema=ALLOWED_PARAMS).decode("utf-16")
    prefill = type(pre)(complex_name=pre.complex_name, sub_components=[target])

    wiz = NewComplexWizard.from_wizard_prefill(prefill)
    qtbot.addWidget(wiz)
    wiz.activate_pin_mapping_for(0)
    wiz._open_param_page()
    val_widget = wiz.param_page.widgets.get("Value")
    assert val_widget is not None
    if isinstance(val_widget, QtWidgets.QSpinBox):
        val = val_widget.value()
    else:
        val = float(val_widget.text())
    if remove_value:
        assert pytest.approx(val, rel=1e-6) == float(target.get("value"))
    else:
        assert pytest.approx(val, rel=1e-6) == float(xml_value)
    assert wiz.param_page.warn_label.isHidden()
