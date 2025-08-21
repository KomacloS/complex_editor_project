from __future__ import annotations

import json
import os
import sys
import types
from pathlib import Path

from PyQt6 import QtWidgets, QtCore
from PyQt6.QtWidgets import QApplication

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src")))
from complex_editor.domain import MacroInstance, SubComponent, ComplexDevice
from complex_editor.ui.main_window import MainWindow


class DummyWizard:
    def __init__(self, prefill, cid, parent=None):
        self.prefill = prefill
        self.editing_complex_id = cid
        self.basics_page = types.SimpleNamespace(pn_edit=types.SimpleNamespace(text=lambda: "CX1 edited", setText=lambda s: None), pin_spin=types.SimpleNamespace(value=lambda: getattr(prefill, "pin_count", 2)))
        mi = MacroInstance("MAC", {})
        if prefill.sub_components and prefill.sub_components[0].get("id_function") is not None:
            mi.id_function = prefill.sub_components[0].get("id_function")
        self.sub_components = [SubComponent(mi, list(prefill.sub_components[0].get("pins")))]

    @classmethod
    def from_existing(cls, prefill, complex_id, parent=None, title=None):
        return cls(prefill, complex_id, parent)

    def exec(self):
        return QtWidgets.QDialog.DialogCode.Accepted

    def to_complex_device(self):
        pins = ["1", "2"]
        dev = ComplexDevice(0, pins, MacroInstance("", {}))
        dev.name = "CX1 edited"
        dev.subcomponents = self.sub_components
        return dev


def test_edit_existing_complex_updates_buffer(tmp_path: Path, qtbot, monkeypatch):
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

    monkeypatch.setattr("complex_editor.ui.main_window.NewComplexWizard", DummyWizard)

    app = QApplication.instance() or QApplication([])
    win = MainWindow(mdb_path=None, buffer_path=buf)
    qtbot.addWidget(win)

    index = win.list_panel.model.index(0, 0)
    win.list_panel.view.doubleClicked.emit(index)

    updated = json.loads(buf.read_text())
    assert updated[0]["name"] == "CX1 edited"
    # model reflects the update
    assert (
        win.list_panel.model.data(
            win.list_panel.model.index(0, 1), QtCore.Qt.ItemDataRole.DisplayRole
        )
        == "CX1 edited"
    )
    # ensure the edited row is selected
    assert win.list_panel.view.selectionModel().isRowSelected(0, QtCore.QModelIndex())
