import os
import sys
import types
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.modules.setdefault("pyodbc", types.ModuleType("pyodbc"))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from PyQt6 import QtWidgets
from complex_editor.domain import MacroDef, MacroParam
from complex_editor.ui.param_editor_dialog import ParamEditorDialog


def test_param_editor_accepts_extra_enum(qtbot):
    macro = MacroDef(0, "GATE", [MacroParam("Mode", "ENUM", "SLOW;MED", None, None)])
    dlg = ParamEditorDialog(macro)
    qtbot.addWidget(dlg)
    dlg.set_values({"Mode": "FAST"})
    combo = dlg._widgets["Mode"]
    assert isinstance(combo, QtWidgets.QComboBox)
    assert combo.findText("FAST") >= 0
    assert combo.currentText() == "FAST"

