from __future__ import annotations

import sys
from typing import Optional

from PyQt6 import QtWidgets

from ..db import connect, discover_macro_map
from .complex_list import ComplexListPanel
from .complex_editor import ComplexEditor
from .datasheet_viewer import DatasheetViewer


class MainWindow(QtWidgets.QMainWindow):
    """Main application window."""

    def __init__(self, conn: Optional[object] = None) -> None:
        super().__init__()
        self.conn = conn
        self.cursor = conn.cursor() if conn else None
        self.macro_map = {}
        self.setWindowTitle("Complex Editor")
        self._build_ui()
        if self.cursor:
            self.load_data()

    def _build_ui(self) -> None:
        central = QtWidgets.QWidget()
        main_layout = QtWidgets.QHBoxLayout(central)
        # Navigation bar
        nav_widget = QtWidgets.QWidget()
        nav_widget.setStyleSheet("background:#003D66;color:white")
        nav_layout = QtWidgets.QVBoxLayout(nav_widget)
        btn_program = QtWidgets.QPushButton("Program Configuration")
        btn_program.clicked.connect(lambda: self.stack.setCurrentWidget(self.list_panel))
        nav_layout.addWidget(btn_program)
        nav_layout.addStretch()
        main_layout.addWidget(nav_widget)
        # Stacked area
        self.stack = QtWidgets.QStackedWidget()
        main_layout.addWidget(self.stack, 1)
        self.list_panel = ComplexListPanel()
        self.stack.addWidget(self.list_panel)
        self.editor_panel = ComplexEditor()
        self.stack.addWidget(self.editor_panel)
        self.setCentralWidget(central)
        # Menu
        file_menu = self.menuBar().addMenu("File")
        open_act = file_menu.addAction("Open…")
        open_act.triggered.connect(self.open_mdb)

    def open_mdb(self) -> None:
        path, _ = QtWidgets.QFileDialog.getOpenFileName(self, "Open MDB", filter="MDB Files (*.mdb *.accdb)")
        if not path:
            return
        self.conn = connect(path)
        self.cursor = self.conn.cursor()
        self.load_data()

    def load_data(self) -> None:
        if not self.cursor:
            return
        self.macro_map = discover_macro_map(self.cursor)
        self.list_panel.load_rows(self.cursor, self.macro_map)


def run_gui(mdb_path: Optional[str] = None) -> None:
    app = QtWidgets.QApplication(sys.argv)
    conn = connect(mdb_path) if mdb_path else None
    window = MainWindow(conn)
    window.resize(800, 600)
    window.show()
    sys.exit(app.exec())
