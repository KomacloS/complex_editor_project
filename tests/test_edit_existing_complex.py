import os
import sys
import types
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

# Ensure project modules import correctly
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src")))
# Ensure pyodbc placeholder exists for modules importing it
sys.modules.setdefault("pyodbc", types.ModuleType("pyodbc"))

from PyQt6 import QtWidgets
import pytest

from complex_editor.domain import (
    ComplexDevice,
    MacroDef,
    MacroInstance,
    MacroParam,
    SubComponent,
)
from complex_editor.domain.pinxml import PinXML
from complex_editor.ui.complex_editor import ComplexEditor


def test_complexdevice_pins_property():
    """Pins derived from sub-components are exposed via the property."""
    sub1 = SubComponent(MacroInstance("A", {}), [1, 2])
    sub2 = SubComponent(MacroInstance("B", {}), [2, 3])
    dev = ComplexDevice(0, None, MacroInstance("", {}), [sub1, sub2])
    assert dev.pins == ["1", "2", "3"]


def test_load_existing_complex_exposes_pins(qtbot):
    macro_map = {1: MacroDef(1, "FUNC", [])}
    cx = ComplexDevice(1, ["1", "2"], MacroInstance("FUNC", {}))
    dlg = ComplexEditor(macro_map)
    qtbot.addWidget(dlg)
    dlg.load_from_model(cx)
    assert dlg.pin_table.pins() == ["1", "2"]


def test_update_existing_complex_roundtrip(qtbot):
    macro = MacroDef(1, "FUNC", [MacroParam("P", "INT", "0", "0", "10")])
    cx = ComplexDevice(1, ["1", "2"], MacroInstance("FUNC", {"P": "1"}))
    dlg = ComplexEditor({1: macro})
    qtbot.addWidget(dlg)
    dlg.load_from_model(cx)

    # simulate edits
    dlg.pin_table.set_pins(["3", "4"])
    widget = dlg.param_widgets["P"]
    assert isinstance(widget, QtWidgets.QSpinBox)
    widget.setValue(5)

    updates = dlg.to_update_dict()
    assert updates["PinA"] == "3"
    assert updates["PinB"] == "4"
    params = PinXML.deserialize(updates["PinS"])
    assert str(params[0].params["P"]) == "5"

    # ensure dict can be forwarded to DB update
    calls = []

    class StubDB:
        def update_complex(self, cid, **fields):
            calls.append((cid, fields))

    db = StubDB()
    db.update_complex(7, **updates)
    assert calls[0][0] == 7
    assert calls[0][1] == updates
