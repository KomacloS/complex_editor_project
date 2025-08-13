from __future__ import annotations

import os
import sys
import types
from pathlib import Path

import pytest
from PyQt6 import QtWidgets

sys.modules.setdefault("pyodbc", types.ModuleType("pyodbc"))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from complex_editor.core.app_context import AppContext
from complex_editor.ui.main_window import MainWindow
from complex_editor.ui.new_complex_wizard import NewComplexWizard


class DummyDB:
    def __init__(self) -> None:
        self.added = []
        self.commit_called = False
        self._conn = types.SimpleNamespace(commit=self._commit)

    def _commit(self) -> None:  # pragma: no cover - simple flag
        self.commit_called = True

    def add_complex(self, dev) -> None:  # pragma: no cover - simple record
        self.added.append(dev)

    def list_complexes(self):  # pragma: no cover - minimal API
        return []

    def list_functions(self):  # pragma: no cover - minimal API
        return []


@pytest.fixture
def dummy_db(monkeypatch) -> DummyDB:
    db = DummyDB()
    monkeypatch.setattr(AppContext, "open_main_db", lambda self, file: db)
    return db


def test_load_buffer_prefilled_wizard_saves(tmp_path: Path, qtbot, monkeypatch, dummy_db: DummyDB) -> None:
    win = MainWindow(mdb_path=tmp_path / "dummy.mdb")
    qtbot.addWidget(win)

    buf_path = Path(__file__).parent / "data" / "buffer_simple.json"
    monkeypatch.setattr(
        QtWidgets.QFileDialog,
        "getOpenFileName",
        lambda *_, **__: (str(buf_path), "json"),
    )

    class DummyWizard:
        def __init__(self) -> None:
            self.basics_page = types.SimpleNamespace(
                pin_spin=types.SimpleNamespace(value=lambda: 4)
            )
            self.sub_components = ["sub"]

        def exec(self) -> int:  # pragma: no cover - trivial
            return QtWidgets.QDialog.DialogCode.Accepted

        def result(self) -> QtWidgets.QDialog.DialogCode:  # pragma: no cover
            return QtWidgets.QDialog.DialogCode.Accepted

    monkeypatch.setattr(
        NewComplexWizard, "from_wizard_prefill", lambda prefill, parent=None: DummyWizard()
    )
    monkeypatch.setattr(
        QtWidgets.QMessageBox, "information", lambda *_, **__: None
    )

    refreshed = {"ok": False}

    def fake_refresh() -> None:
        refreshed["ok"] = True

    win._refresh_list = fake_refresh  # type: ignore[method-assign]
    win._load_complex_from_buffer()

    assert len(dummy_db.added) == 1
    assert dummy_db.commit_called
    assert refreshed["ok"]
