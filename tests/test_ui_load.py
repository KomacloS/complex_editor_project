from __future__ import annotations

import types
import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

sys.modules.setdefault("pyodbc", types.ModuleType("pyodbc"))
pyodbc = sys.modules["pyodbc"]
pyodbc.SQL_DATABASE_NAME = 0

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src")))

from PyQt6 import QtWidgets
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

    def fetchone(self):
        return (10,)

    def fetchall(self):
        if "tabFunction" in self.last_query:
            return [(1, "MACRO1")]
        if "tabCompDesc" in self.last_query:
            return [
                (1, 1, "A1", "B1", None, None, None),
                (2, 1, "A2", "B2", None, None, None),
            ]
        if "tabFuncMacro" in self.last_query:
            return [(1, "P1", "INT", "0", "0", "10")]
        return []


class FakeConnection:
    def cursor(self):
        return FakeCursor()

    def getinfo(self, code):
        return "dummy.mdb"


def test_main_window_load(qtbot):
    window = MainWindow(FakeConnection())
    qtbot.addWidget(window)
    model = window.list_panel.model
    assert model.rowCount() == 2


def test_editor_save(qtbot, monkeypatch):
    conn = FakeConnection()
    window = MainWindow(conn)
    qtbot.addWidget(window)
    window.list_panel.complexSelected.emit(None)
    window.editor_panel.pin_edits[0].setText("X1")
    window.editor_panel.pin_edits[1].setText("X2")
    window.editor_panel.macro_combo.setCurrentIndex(0)
    widget = window.editor_panel.param_widgets["P1"]
    widget.setValue(5)

    def fake_insert(c, dev):
        window.list_panel.model.rows.append((3, dev.id_function, *dev.pins, b""))
        return 3

    monkeypatch.setattr(
        "complex_editor.ui.complex_editor.insert_complex", fake_insert
    )
    bak_called = {}
    monkeypatch.setattr(
        "complex_editor.ui.complex_editor.make_backup",
        lambda p: (bak_called.setdefault("path", p), Path("backup.bak"))[1],
    )
    info_text = {}
    monkeypatch.setattr(
        QtWidgets.QMessageBox,
        "information",
        lambda *a, **k: info_text.setdefault("msg", a[2]),
    )
    monkeypatch.setattr(window.list_panel, "load_rows", lambda c, m: None)
    window.editor_panel.conn = conn
    window.editor_panel.save_complex()
    assert window.list_panel.model.rowCount() == 3
    assert Path("backup.bak") == Path(info_text["msg"].split()[-1])
    assert bak_called["path"] == "dummy.mdb"
