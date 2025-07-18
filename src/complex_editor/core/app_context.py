from __future__ import annotations

from pathlib import Path
import importlib.resources
import shutil

from complex_editor.db.mdb_api import MDB


class AppContext:
    def __init__(self) -> None:
        self.db: MDB | None = None

    def open_main_db(self, file: Path) -> MDB:
        """Open or create the main MDB and return the handle."""
        if not file.exists():
            file.parent.mkdir(parents=True, exist_ok=True)
            template = importlib.resources.files("complex_editor.assets").joinpath(
                "empty_template.mdb"
            )
            with importlib.resources.as_file(template) as tmpl_path:
                shutil.copy(tmpl_path, file)
        if self.db:
            self.db.__exit__(None, None, None)
        self.db = MDB(file)
        return self.db
