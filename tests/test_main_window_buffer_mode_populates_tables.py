import os, json, sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'src')))

from PyQt6.QtWidgets import QApplication
from complex_editor.ui.main_window import MainWindow


def test_main_window_buffer_mode_populates_tables(qtbot, tmp_path: Path) -> None:
    data = [
        {
            "id": 42,
            "name": "RY12",
            "total_pins": 8,
            "pins": [str(i) for i in range(1, 9)],
            "subcomponents": [
                {
                    "id": 15806,
                    "id_function": 16,
                    "function_name": "RELAIS",
                    "value": "12.0",
                    "force_bits": 1,
                    "pins": {"A": "1", "B": "2", "S": "<xml>ignored</xml>", "C": "3", "D": "4"},
                },
            ],
        }
    ]
    buf = tmp_path / "buffer.json"
    buf.write_text(json.dumps(data), encoding="utf-8")

    app = QApplication.instance() or QApplication([])
    win = MainWindow(mdb_path=None, buffer_path=buf)
    qtbot.addWidget(win)

    win.list.selectRow(0)
    win._on_selected()
    row0 = {
        win.sub_table.horizontalHeaderItem(i).text(): (win.sub_table.item(0, i).text() if win.sub_table.item(0, i) else "")
        for i in range(win.sub_table.columnCount())
    }
    assert "S" not in row0["Pins"]
    assert "A=1" in row0["Pins"] and "D=4" in row0["Pins"]
