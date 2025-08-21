import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "src")))

from PyQt6 import QtCore
from PyQt6 import QtWidgets
from complex_editor.ui.complex_editor import ComplexEditor
from complex_editor.domain import ComplexDevice, MacroDef, MacroInstance, MacroParam, SubComponent


def _macro_map():
    macro = MacroDef(1, "GATE", [MacroParam("P", "INT", None, "0", "10")])
    return {1: macro}


def test_complex_editor_edit_flow(qtbot, monkeypatch):
    sc = SubComponent(MacroInstance("GATE", {"P": "1"}), [1, 2, 3, 4])
    dev = ComplexDevice(0, [], MacroInstance("", {}), pn="CX1", pin_count=4, subcomponents=[sc], id=5)
    editor = ComplexEditor(_macro_map())
    qtbot.addWidget(editor)
    editor.load_device(dev)
    editor.alt_pn_edit.setText("ALT")
    editor._update_state()
    assert editor.save_btn.isEnabled()
    editor._on_accept()
    dev2 = editor.build_device()
    assert dev2.id == 5
    assert dev2.alt_pn == "ALT"
