from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from PyQt6 import QtCore
from PyQt6.QtWidgets import QApplication

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src")))
from complex_editor.ui.main_window import MainWindow


def test_main_window_shows_buffer_list(qtbot, tmp_path: Path) -> None:
    data = [
        {
            "id": 1,
            "name": "CX1",
            "total_pins": 4,
            "pins": ["1", "2", "3", "4"],
            "subcomponents": [
                {
                    "id_function": 10,
                    "function_name": "MAC",
                    "pins": {"A": "1", "B": "2"},
                }
            ],
        }
    ]
    buf = tmp_path / "buffer.json"
    buf.write_text(json.dumps(data), encoding="utf-8")

    app = QApplication.instance() or QApplication([])
    win = MainWindow(mdb_path=None, buffer_path=buf)
    qtbot.addWidget(win)

    model = win.list_panel.model
    assert model.rowCount() == 1
    idx = model.index(0, 0)
    assert model.data(idx, QtCore.Qt.ItemDataRole.DisplayRole) == "1"
    idx_name = model.index(0, 1)
    assert model.data(idx_name, QtCore.Qt.ItemDataRole.DisplayRole) == "CX1"
    idx_subs = model.index(0, 2)
    assert model.data(idx_subs, QtCore.Qt.ItemDataRole.DisplayRole) == "1"

    # central widget should be the list panel in buffer mode
    assert win.centralWidget() is win.list_panel
