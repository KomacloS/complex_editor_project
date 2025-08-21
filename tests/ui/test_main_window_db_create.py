import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "src")))

from PyQt6 import QtWidgets
from complex_editor.ui.main_window import MainWindow
from complex_editor.ui.main_window import AppContext
from complex_editor.domain import MacroDef, MacroParam, MacroInstance, ComplexDevice, SubComponent
from complex_editor.db.mdb_api import ComplexDevice as DbComplex
from complex_editor.util.macro_xml_translator import xml_to_params
import complex_editor.db.schema_introspect as schema_introspect


class DummyConn:
    def cursor(self):
        return object()

    def commit(self):
        pass


class DummyDB:
    def __init__(self):
        self.add_complex_called = None
        self._conn = DummyConn()

    def list_functions(self):
        return [(1, "GATE")]

    def list_complexes(self):
        return []

    def add_complex(self, cx):
        self.add_complex_called = cx


class FakeEditor(QtWidgets.QDialog):
    def __init__(self, *args, **kwargs):
        super().__init__()

    def exec(self):
        return QtWidgets.QDialog.DialogCode.Accepted

    def build_device(self):
        sc = SubComponent(MacroInstance("GATE", {"P": "1"}), [1, 2, 0, 0])
        dev = ComplexDevice(0, [], MacroInstance("", {}))
        dev.pn = "CX1"
        dev.pin_count = 4
        dev.subcomponents = [sc]
        return dev


def test_db_create_called(qtbot, monkeypatch):
    dummy = DummyDB()
    monkeypatch.setattr(AppContext, "open_main_db", lambda self, path: dummy)
    monkeypatch.setattr(schema_introspect, "discover_macro_map", lambda _c: {1: MacroDef(1, "GATE", [MacroParam("P", "INT", None, "0", "10")])})
    monkeypatch.setattr("complex_editor.ui.main_window.ComplexEditor", FakeEditor)

    win = MainWindow(mdb_path=Path("dummy.mdb"))
    qtbot.addWidget(win)

    win._new_complex()

    called = dummy.add_complex_called
    assert isinstance(called, DbComplex)
    assert called.subcomponents
    sc = called.subcomponents[0]
    assert sc.id_function == 1
    assert sc.pins["A"] == 1 and sc.pins["B"] == 2
    params = xml_to_params(sc.pins["S"])
    assert params["GATE"]["P"] == "1"
