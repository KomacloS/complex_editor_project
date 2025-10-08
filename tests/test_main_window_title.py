import os
import sys
from pathlib import Path

import types

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src")))

from PyQt6 import QtWidgets  # noqa: E402
from complex_editor.ui.main_window import MainWindow  # noqa: E402



class DummyDB:
    def list_complexes(self):
        return []


class DummyCtx:
    def open_main_db(self, _):
        return DummyDB()

    def wizard_opened(self) -> None:
        pass

    def wizard_closed(self, *, saved: bool, had_changes: bool = False) -> None:
        pass

    def bridge_state(self) -> dict[str, bool]:
        return {"wizard_open": False, "unsaved_changes": False}


def test_window_title(qtbot, monkeypatch):
    monkeypatch.setattr("complex_editor.ui.main_window.AppContext", lambda: DummyCtx())
    win = MainWindow(Path("dummy.mdb"))
    qtbot.addWidget(win)
    assert win.windowTitle() == "Complex View"
