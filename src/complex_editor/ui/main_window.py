from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

from PyQt6 import QtWidgets

from ..core.app_context import AppContext
from ..db.mdb_api import MDB
from ..db import discover_macro_map
from .complex_list import ComplexListPanel
from .complex_editor import ComplexEditor


class MainWindow(QtWidgets.QMainWindow):
    """Main window showing the complex list on the left and editor on the right."""

    def __init__(
        self,
        mdb_path: Optional[Path] = None,
        parent: Any | None = None,
        buffer_path: Optional[Path] = None,
    ) -> None:
        super().__init__(parent)

        if mdb_path is None and buffer_path is None:
            raise ValueError("mdb_path or buffer_path required")

        self.ctx = AppContext()
        self.db: MDB | None = None
        if mdb_path is not None:
            self.db = self.ctx.open_main_db(mdb_path)

        self.list_panel = ComplexListPanel()
        self.list = self.list_panel.view  # backward compatibility
        self.editor = ComplexEditor(db=self.db)
        self.editor.show()  # ensure visible for headless tests

        splitter = QtWidgets.QSplitter()
        splitter.addWidget(self.list_panel)
        splitter.addWidget(self.editor)
        self.setCentralWidget(splitter)

        self.list_panel.complexSelected.connect(self.editor.load_complex)
        self.list_panel.newComplexRequested.connect(self.editor.reset_to_new)
        self.editor.saved.connect(self.list_panel.refresh_and_select)

        if self.db is not None:
            try:
                cur = self.db._cur()
                macro_map = discover_macro_map(cur) or {}
                self.list_panel.load_rows(cur, macro_map)
                self.editor.set_macro_map(macro_map)
                self.list_panel.set_refresh_callback(
                    lambda: self.list_panel.load_rows(self.db._cur(), macro_map)
                )
            except Exception:
                pass

        self.show()  # ensure visibility in headless tests


def run_gui(mdb_file: Path | None = None, buffer_path: Path | None = None) -> None:
    import sys
    from PyQt6 import QtWidgets

    app = QtWidgets.QApplication(sys.argv)
    win = MainWindow(mdb_path=mdb_file, buffer_path=buffer_path)
    win.resize(1100, 600)
    win.show()
    sys.exit(app.exec())


__all__ = ["MainWindow", "run_gui"]

