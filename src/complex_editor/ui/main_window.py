from __future__ import annotations
# ruff: noqa: E402

from typing import Any, Optional, cast
import logging
import sys

from ..bootstrap import add_repo_src_to_syspath

add_repo_src_to_syspath()

from PyQt6 import QtWidgets, QtGui

from ..db import connect, discover_macro_map
from ..domain import MacroDef
from .complex_editor import ComplexEditor
from .complex_list import ComplexListPanel
from .new_complex_wizard import NewComplexWizard


class MainWindow(QtWidgets.QMainWindow):
    """Main application window."""

    db_cursor: Any | None
    macro_map: dict[int, MacroDef]
    stack: QtWidgets.QStackedWidget
    list_panel: ComplexListPanel

    def __init__(self, conn: Optional[Any] = None) -> None:
        super().__init__()
        self.conn = conn
        self.db_cursor: Any | None = conn.cursor() if conn else None
        self.macro_map: dict[int, MacroDef] = {}
        self.setWindowTitle("Complex Editor")
        self._build_ui()
        if self.db_cursor:
            self.load_data()

    def _build_ui(self) -> None:
        central = QtWidgets.QWidget()
        main_layout = QtWidgets.QHBoxLayout(central)
        # Navigation bar
        nav_widget = QtWidgets.QWidget()
        nav_widget.setStyleSheet("background:#003D66;color:white")
        nav_layout = QtWidgets.QVBoxLayout(nav_widget)
        btn_program = QtWidgets.QPushButton("Program Configuration")
        btn_program.clicked.connect(
            lambda: self.stack.setCurrentWidget(self.list_panel)
        )
        nav_layout.addWidget(btn_program)
        nav_layout.addStretch()
        main_layout.addWidget(nav_widget)
        # Stacked area
        self.stack: QtWidgets.QStackedWidget = QtWidgets.QStackedWidget()
        main_layout.addWidget(self.stack, 1)
        self.list_panel: ComplexListPanel = ComplexListPanel()
        self.stack.addWidget(self.list_panel)
        self.editor_panel = ComplexEditor(self.macro_map)
        self.editor_panel.conn = self.conn
        self.editor_panel.dirtyChanged.connect(self._on_dirty)
        self.stack.addWidget(self.editor_panel)
        self.list_panel.complexSelected.connect(self._open_editor)
        self.list_panel.newComplexRequested.connect(self._new_complex)
        self.setCentralWidget(central)
        # Menu
        menubar = cast(QtWidgets.QMenuBar, self.menuBar())
        file_menu = cast(QtWidgets.QMenu, menubar.addMenu("File"))
        open_act = cast(QtGui.QAction, file_menu.addAction("Open…"))
        open_act.triggered.connect(self.open_mdb)
        self.save_act = cast(QtGui.QAction, file_menu.addAction("Save"))
        self.save_act.triggered.connect(self.editor_panel.save_complex)
        self.save_act.setEnabled(False)

    def _open_editor(self, row) -> None:
        """Open the editor panel for the selected complex."""
        self.editor_panel.load_complex(row)
        self.stack.setCurrentWidget(self.editor_panel)

    def _new_complex(self) -> None:
        wizard = NewComplexWizard(self.macro_map, self)
        if wizard.exec() == QtWidgets.QDialog.DialogCode.Accepted:
            self.editor_panel.load_complex(None)
            self.editor_panel.set_sub_components(wizard.sub_components)
            if wizard.sub_components:
                sc = wizard.sub_components[0]
                pins = [str(p) for p in sc.pins]
                self.editor_panel.pin_table.set_pins(pins)
                idx = self.editor_panel.macro_combo.findText(sc.macro.name)
                if idx >= 0:
                    self.editor_panel.macro_combo.setCurrentIndex(idx)
                macro = next(
                    (m for m in self.macro_map.values() if m.name == sc.macro.name),
                    None,
                )
                if macro:
                    self.editor_panel._build_param_widgets(macro)
                for k, v in sc.macro.params.items():
                    w = self.editor_panel.param_widgets.get(k)
                    if isinstance(w, QtWidgets.QSpinBox):
                        w.setValue(int(v))
                    elif isinstance(w, QtWidgets.QDoubleSpinBox):
                        w.setValue(float(v))
                    elif isinstance(w, QtWidgets.QCheckBox):
                        w.setChecked(str(v).lower() in ("1", "true", "yes"))
                    elif isinstance(w, QtWidgets.QComboBox):
                        idx = w.findText(str(v))
                        if idx >= 0:
                            w.setCurrentIndex(idx)
                        elif w.count() == 0:
                            w.addItem(str(v))
                    elif isinstance(w, QtWidgets.QLineEdit):
                        w.setText(str(v))
                self.editor_panel.on_dirty()
            self.stack.setCurrentWidget(self.editor_panel)

    def open_mdb(self) -> None:
        path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self, "Open MDB", filter="MDB Files (*.mdb *.accdb)"
        )
        if not path:
            return
        try:
            self.conn = connect(path)
        except Exception:
            logging.getLogger(__name__).exception("Failed to connect to MDB %s", path)
            QtWidgets.QMessageBox.critical(
                self,
                "Open MDB Error",
                "Could not open database. Check logs for details.",
            )
            return
        self.db_cursor = self.conn.cursor()
        self.load_data()

    def load_data(self) -> None:
        """
        Load all lookups and tree/list data from the database cursor.
        Always attempt to load macros (DB first, then fallback YAML).
        """
        self.macro_map = discover_macro_map(self.db_cursor)
        self.list_panel.load_rows(self.db_cursor, self.macro_map)
        self.editor_panel.conn = self.conn
        self.editor_panel.set_macro_map(self.macro_map)

    def _on_dirty(self, dirty: bool) -> None:
        self.save_act.setEnabled(dirty)


def run_gui(mdb_path: Optional[str] = None) -> None:
    import complex_editor.logging_cfg  # noqa: F401

    app = QtWidgets.QApplication(sys.argv)
    conn = connect(mdb_path) if mdb_path else None
    window = MainWindow(conn)
    window.resize(800, 600)
    window.show()
    sys.exit(app.exec())
