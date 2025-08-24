import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "src")))

from PyQt6 import QtWidgets
from complex_editor.ui.main_window import MainWindow, AppContext
from complex_editor.db.mdb_api import SubComponent as DbSub, ComplexDevice as DbComplex
from complex_editor.util.macro_xml_translator import params_to_xml
import complex_editor.db.schema_introspect as schema_introspect


class DummyConn:
    def cursor(self):
        return object()


class DummyDB:
    def __init__(self, xml: str):
        self.xml = xml
        self._conn = DummyConn()

    def list_functions(self):
        return [(1, "GATE")]

    def list_complexes(self):
        return [(1, "CX", 1)]

    def get_complex(self, cid):
        sc = DbSub(None, 1, pins={"A": 1, "B": 2, "S": self.xml})
        return DbComplex(1, "CX", 4, [sc])


def test_xml_name_mismatch_fallback(qtbot, monkeypatch):
    xml = params_to_xml({"GATE_V1": {"P": "2"}}, encoding="utf-16", schema=None).decode("utf-16")
    dummy = DummyDB(xml)
    monkeypatch.setattr(AppContext, "open_main_db", lambda self, path: dummy)
    monkeypatch.setattr(schema_introspect, "discover_macro_map", lambda _c: {})

    captured = {}

    class FakeEditor(QtWidgets.QDialog):
        def __init__(self, *a, **k):
            super().__init__()
            captured["editor"] = self
            self.loaded = None

        def load_device(self, dev):
            self.loaded = dev

        def exec(self):
            return QtWidgets.QDialog.DialogCode.Rejected

    monkeypatch.setattr("complex_editor.ui.main_window.ComplexEditor", FakeEditor)

    win = MainWindow(mdb_path=Path("dummy.mdb"))
    qtbot.addWidget(win)
    win.list.setCurrentCell(0, 0)
    win._on_edit()

    editor = captured["editor"]
    params = editor.loaded.subcomponents[0].macro.params
    assert params.get("P") == "2"
