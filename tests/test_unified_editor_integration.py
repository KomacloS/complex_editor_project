import json
import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src")))

from PyQt6 import QtWidgets
from PyQt6.QtWidgets import QApplication

from complex_editor.ui.main_window import MainWindow
from complex_editor.ui.complex_editor import ComplexEditor
from complex_editor.ui.dialogs.pin_assignment_dialog import PinAssignmentDialog
from complex_editor.domain import MacroDef


def test_editor_shown_in_main_window_headless(qtbot, tmp_path: Path) -> None:
    buf = tmp_path / "buffer.json"
    buf.write_text(json.dumps([]), encoding="utf-8")
    app = QApplication.instance() or QApplication([])
    win = MainWindow(mdb_path=None, buffer_path=buf)
    qtbot.addWidget(win)
    assert win.editor.isVisible()
    assert isinstance(win.list, QtWidgets.QTableView)


def test_save_emits_real_id(qtbot) -> None:
    class DummyDB:
        def add_complex(self, dev):
            return 123

        def get_complex(self, cid):
            raise AssertionError("should not be called")

        def update_complex(self, cid, updated):
            return None

    editor = ComplexEditor(db=DummyDB())
    editor.set_macro_map({1: MacroDef(1, "M", [])})
    editor.name_edit.setText("cx")
    editor._pins = ["1", "2"]
    editor.param_values = {}
    called = {}

    def refresh(cid):
        called["id"] = cid

    editor.saved.connect(refresh)
    editor.save_complex()
    assert called["id"] == 123


def test_set_macro_map_enables_save(qtbot) -> None:
    editor = ComplexEditor()
    editor.set_macro_map({1: MacroDef(1, "M", [])})
    assert editor.macro_combo.count() == 1
    editor.name_edit.setText("cx")
    editor._pins = ["1", "2"]
    editor._update_save_enabled()
    assert editor.save_btn.isEnabled()


def test_pin_dialog_blocks_duplicates(qtbot):
    dlg = PinAssignmentDialog(["A", "B"], ["1", "2"])
    qtbot.addWidget(dlg)
    dlg._combos[0].setCurrentText("1")
    dlg._combos[1].setCurrentText("1")
    ok_btn = dlg.buttons.button(QtWidgets.QDialogButtonBox.StandardButton.Ok)
    assert not ok_btn.isEnabled()
    dlg._combos[1].setCurrentText("2")
    assert ok_btn.isEnabled()

