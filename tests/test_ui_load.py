from __future__ import annotations

import types
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

sys.modules.setdefault("pyodbc", types.ModuleType("pyodbc"))

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src")))

from complex_editor.ui.main_window import MainWindow  # noqa: E402


class FakeCursor:
    def tables(self, table=None, tableType=None):
        yield types.SimpleNamespace(table_name="tabCompDesc")
        yield types.SimpleNamespace(table_name="tabFunction")
        yield types.SimpleNamespace(table_name="tabFuncMacro")

    def columns(self, table):
        if table == "tabCompDesc":
            cols = [
                "IDCompDesc",
                "IDFunction",
                "PinA",
                "PinB",
                "PinC",
                "PinD",
                "PinS",
            ]
        elif table == "tabFunction":
            cols = ["IDFunction", "MacroName"]
        else:
            cols = [
                "IDFunction",
                "ParamName",
                "ParamType",
                "DefValue",
                "MinValue",
                "MaxValue",
            ]
        for c in cols:
            yield types.SimpleNamespace(column_name=c)

    def execute(self, query):
        self.last_query = query
        return self

    def fetchall(self):
        if "tabFunction" in self.last_query:
            return [(1, "MACRO1")]
        if "tabCompDesc" in self.last_query:
            return [
                (1, 1, "A1", "B1", None, None, None),
                (2, 1, "A2", "B2", None, None, None),
            ]
        return []


class FakeConnection:
    def cursor(self):
        return FakeCursor()


def test_main_window_load(qtbot):
    window = MainWindow(FakeConnection())
    qtbot.addWidget(window)
    model = window.list_panel.model
    assert model.rowCount() == 2
