from __future__ import annotations

import json
import os
import sys
import types
from pathlib import Path

from PyQt6.QtWidgets import QApplication
from PyQt6 import QtWidgets, QtCore

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src")))
from complex_editor.domain import MacroInstance, SubComponent, ComplexDevice
from complex_editor.ui.main_window import MainWindow


class DummyNewWizard:
    def __init__(self, macro_map, parent=None):
        self.basics_page = types.SimpleNamespace(pn_edit=types.SimpleNamespace(text=lambda: "NEW", setText=lambda s: None), pin_spin=types.SimpleNamespace(value=lambda: 2))
        mi = MacroInstance("MAC", {})
        mi.id_function = 10
        self.sub_components = [SubComponent(mi, [1, 2])]

    def exec(self):
        return QtWidgets.QDialog.DialogCode.Accepted

    def to_complex_device(self):
        pins = ["1", "2"]
        dev = ComplexDevice(0, pins, MacroInstance("", {}))
        dev.name = "NEW"
        dev.subcomponents = self.sub_components
        return dev


def test_create_new_complex_appends_buffer(tmp_path: Path, qtbot, monkeypatch):
    data = [
        {
            "id": 1,
            "name": "CX1",
            "total_pins": 2,
            "pins": ["1", "2"],
            "subcomponents": [
                {"id_function": 10, "function_name": "MAC", "pins": {"A": "1", "B": "2"}}
            ],
        }
    ]
    buf = tmp_path / "buffer.json"
    buf.write_text(json.dumps(data), encoding="utf-8")

    monkeypatch.setattr("complex_editor.ui.main_window.NewComplexWizard", DummyNewWizard)

    app = QApplication.instance() or QApplication([])
    win = MainWindow(mdb_path=None, buffer_path=buf)
    qtbot.addWidget(win)

    win.list_panel.newComplexRequested.emit()

    updated = json.loads(buf.read_text())
    assert len(updated) == 2
    assert updated[1]["name"] == "NEW"
    # new row added and selected
    assert win.list_panel.model.rowCount() == 2
    assert win.list_panel.view.selectionModel().isRowSelected(1, QtCore.QModelIndex())
