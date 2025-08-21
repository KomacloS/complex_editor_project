import os
import sys
import json
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "src")))

from PyQt6 import QtWidgets, QtCore
from complex_editor.ui.main_window import MainWindow, AppContext
from complex_editor.ui.complex_editor import ComplexEditor
import complex_editor.db.schema_introspect as schema_introspect


def test_buffer_edit_updates_json(tmp_path, qtbot, monkeypatch):
    data = [
        {
            "id": 1,
            "name": "CX",
            "pins": ["1", "2", "3", "4"],
            "subcomponents": [
                {
                    "function_name": "GATE",
                    "pins": {
                        "A": 1,
                        "B": 2,
                        "C": 3,
                        "D": 4,
                        "S": "<GATE><P>1</P></GATE>",
                    },
                }
            ],
        }
    ]
    buf_path = tmp_path / "buf.json"
    buf_path.write_text(json.dumps(data))

    monkeypatch.setattr(AppContext, "open_main_db", lambda *a, **k: None)
    monkeypatch.setattr(schema_introspect, "discover_macro_map", lambda _c: {})

    win = MainWindow(buffer_path=buf_path)
    qtbot.addWidget(win)

    win.list.setCurrentCell(0, 0)

    def fake_exec(self):
        self.alt_pn_edit.setText("ALT2")
        self._update_state()
        assert self.save_btn.isEnabled()
        self._on_accept()
        return QtWidgets.QDialog.DialogCode.Accepted

    monkeypatch.setattr(ComplexEditor, "exec", fake_exec)
    win._on_edit()

    raw = json.loads(buf_path.read_text())
    xml = raw[0]["subcomponents"][0]["pins"]["S"]
    assert "<Macro Name=\"GATE\"" in xml
    assert raw[0]["alt_pn"] == "ALT2"
