from __future__ import annotations

import os
import sys
import types

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

sys.modules.setdefault("pyodbc", types.ModuleType("pyodbc"))

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src")))

from PyQt6 import QtWidgets  # noqa: E402
from complex_editor.ui.main_window import MainWindow  # noqa: E402
from complex_editor.db.schema_introspect import discover_macro_map  # noqa: E402


class FakeCursorNoTables:
    def tables(self, table=None, tableType=None):
        if False:
            yield

    def columns(self, table):
        raise AssertionError("columns should not be called")

    def execute(self, query):
        raise AssertionError("execute should not be called")


def test_xml_preview(qtbot):
    macro_map = discover_macro_map(FakeCursorNoTables())
    window = MainWindow(None)
    qtbot.addWidget(window)
    window.editor_panel.set_macro_map(macro_map)
    window.list_panel.complexSelected.emit(None)
    table = window.editor_panel.pin_table
    table.setItem(0, 1, QtWidgets.QTableWidgetItem("P1"))
    table.setItem(1, 1, QtWidgets.QTableWidgetItem("P2"))
    window.editor_panel.macro_combo.setCurrentIndex(0)
    widget = window.editor_panel.param_widgets["Value"]
    widget.setValue(5)
    preview = window.editor_panel.xml_preview.toPlainText()
    assert "RESISTOR|Value=" in preview
    assert window.windowTitle().endswith("*")
