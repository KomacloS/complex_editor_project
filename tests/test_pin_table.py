from __future__ import annotations

import os
import sys
import types

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

sys.modules.setdefault("pyodbc", types.ModuleType("pyodbc"))

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src")))

from PyQt6 import QtWidgets  # noqa: E402
from complex_editor.ui.pin_table import PinTable  # noqa: E402


def test_pin_table(qtbot):
    table = PinTable()
    qtbot.addWidget(table)
    table.set_pins(["A1", "A2"])
    table.add_pin_btn.click()
    table.setItem(2, 1, QtWidgets.QTableWidgetItem("A3"))
    assert table.pins() == ["A1", "A2", "A3"]


