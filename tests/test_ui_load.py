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

from PyQt6 import QtWidgets  # noqa: E402
from complex_editor.ui.main_window import MainWindow  # noqa: E402
from complex_editor.ui.complex_editor import ComplexEditor  # noqa: E402
from complex_editor.domain import ComplexDevice, MacroInstance  # noqa: E402


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


class FakeMDB:
    def __init__(self):
        self.added = []

    def list_complexes(self):
        return [
            (1, "CX1", "FUNC", 1),
            (2, "CX2", "FUNC", 2),
        ]

    def discover_macro_map(self):
        return {}

    def get_complex(self, cid):
        return ComplexDevice(cid, ["1", "2"], MacroInstance("FUNC", {}))

    def add_complex(self, dev):
        self.added.append(dev)
        return 3

    def update_complex(self, *a, **k):
        pass

    def delete_complex(self, *a, **k):
        pass


class DummyCtx:
    def open_main_db(self, _):
        return FakeMDB()

    def wizard_opened(self) -> None:
        pass

    def wizard_closed(self, *, saved: bool, had_changes: bool = False) -> None:
        pass

    def bridge_state(self) -> dict[str, bool]:
        return {"wizard_open": False, "unsaved_changes": False}


def test_main_window_load(qtbot, monkeypatch):
    monkeypatch.setattr("complex_editor.ui.main_window.AppContext", lambda: DummyCtx())
    window = MainWindow(Path("dummy.mdb"))
    qtbot.addWidget(window)
    assert window.list.rowCount() == 2


def test_editor_save(qtbot, monkeypatch):
    monkeypatch.setattr("complex_editor.ui.main_window.AppContext", lambda: DummyCtx())
    window = MainWindow(Path("dummy.mdb"))
    qtbot.addWidget(window)
    dlg = ComplexEditor({})
    qtbot.addWidget(dlg)
    dlg.pin_table.set_pins(["1", "2"])
    dlg.save_btn.click()
    assert dlg.result() == QtWidgets.QDialog.DialogCode.Accepted
