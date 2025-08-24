import os
import types
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src")))

from PyQt6 import QtWidgets
from complex_editor.ui.main_window import MainWindow
from complex_editor.db.mdb_api import SubComponent as DbSub, ComplexDevice as DbComplex
from complex_editor.domain import MacroInstance, SubComponent


class FakeDB:
    def __init__(self):
        self.updated = None
        self._conn = types.SimpleNamespace(commit=lambda: None)

    def list_complexes(self):
        return [(1, "CX1", 1)]

    def list_functions(self):
        return [(10, "MAC")]  # id->name mapping

    def get_complex(self, cid):
        sc = DbSub(1, 10, "", None, None, None, None, {"A": 1, "B": 2})
        return DbComplex(cid, "CX1", 4, [sc])

    def update_complex(self, comp_id, updated=None, **fields):
        self.updated = (comp_id, updated, fields)


class DummyCtx:
    def open_main_db(self, _):
        return FakeDB()


class DummyLine:
    def __init__(self, text=""):
        self._t = text

    def text(self):
        return self._t

    def setText(self, t):
        self._t = t


class DummySpin:
    def __init__(self, value=0):
        self._v = value

    def value(self):
        return self._v

    def setValue(self, v):
        self._v = v


class DummyWizard:
    def __init__(self, prefill, cid):
        self.basics_page = types.SimpleNamespace(
            pin_spin=DummySpin(getattr(prefill, "pin_count", 0)),
            pn_edit=DummyLine(prefill.complex_name),
        )
        self.sub_components = []
        for sc in prefill.sub_components:
            mi = MacroInstance(sc.get("macro_name", ""), {})
            if sc.get("id_function") is not None:
                mi.id_function = sc.get("id_function")
            self.sub_components.append(SubComponent(mi, tuple(sc.get("pins") or [])))

    @classmethod
    def from_existing(cls, prefill, complex_id, parent=None):
        return cls(prefill, complex_id)

    def exec(self):
        # simulate user changing first pin
        if self.sub_components and self.sub_components[0].pins:
            pins = list(self.sub_components[0].pins)
            pins[0] = 5
            self.sub_components[0].pins = tuple(pins)
        return QtWidgets.QDialog.DialogCode.Accepted


def test_edit_existing_complex_flow(qtbot, monkeypatch):
    monkeypatch.setattr("complex_editor.ui.main_window.AppContext", lambda: DummyCtx())
    monkeypatch.setattr(
        "complex_editor.ui.main_window.NewComplexWizard", DummyWizard
    )
    monkeypatch.setattr(
        "complex_editor.ui.main_window.QtWidgets.QMessageBox.information",
        lambda *a, **k: None,
    )

    win = MainWindow(Path("dummy.mdb"))
    qtbot.addWidget(win)

    win.list.selectRow(0)
    win._on_edit()

    db = win.db
    assert isinstance(db, FakeDB)
    assert db.updated is not None
    comp_id, updated, fields = db.updated
    assert comp_id == 1
    assert not fields
    assert updated.subcomponents[0].pins["A"] == 5
