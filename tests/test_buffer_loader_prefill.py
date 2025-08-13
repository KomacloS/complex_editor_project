from __future__ import annotations

import os
import sys
import types
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.modules.setdefault("pyodbc", types.ModuleType("pyodbc"))

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from complex_editor.io.buffer_loader import (  # noqa: E402
    load_complex_from_buffer_json,
    to_wizard_prefill,
)
from complex_editor.ui.new_complex_wizard import NewComplexWizard  # noqa: E402


def _resolver(name: str) -> int | None:
    mapping = {"RESISTOR": 1, "CAP": 2, "DIODE": 3}
    return mapping.get(name.upper())


def _normalizer(pin_map):
    result = {}
    for k, v in pin_map.items():
        key = k if k.startswith("Pin") else f"Pin{k[-1].upper()}"
        if key == "PinS":
            continue
        result[key] = v
    return result


def test_load_complex_from_buffer_json() -> None:
    path = Path(__file__).parent / "data" / "buffer_simple.json"
    buf = load_complex_from_buffer_json(path)
    assert buf.complex_name == "CX1"
    assert len(buf.sub_components) == 2
    assert buf.sub_components[0].pin_map["PinA"] == "1"


def test_load_complex_varied_shapes() -> None:
    path = Path(__file__).parent / "data" / "buffer_varied_shapes.json"
    buf = load_complex_from_buffer_json(path)
    assert buf.complex_name == "CX2"
    assert len(buf.sub_components) == 3
    assert "PinS" not in buf.sub_components[1].pin_map


def test_prefill_and_wizard(qtbot) -> None:
    path = Path(__file__).parent / "data" / "buffer_varied_shapes.json"
    buf = load_complex_from_buffer_json(path)
    pre = to_wizard_prefill(buf, _resolver, _normalizer)
    assert pre.sub_components[0]["id_function"] == 1
    wizard = NewComplexWizard.from_wizard_prefill(pre)
    qtbot.addWidget(wizard)
    assert wizard.stack.currentWidget() is wizard.review_page
    assert "PinS" in wizard.param_page.warn_label.text()
    assert wizard.param_page.group_box.isHidden()
