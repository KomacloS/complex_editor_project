from __future__ import annotations

from pathlib import Path
import importlib.resources
import shutil
from typing import Optional

from complex_editor.config.loader import CEConfig, load_config, save_config
from complex_editor.db.mdb_api import MDB


class AppContext:
    """Central application state: config + database handle."""

    def __init__(self, config: Optional[CEConfig] = None) -> None:
        self.config: CEConfig = config or load_config()
        self.db: MDB | None = None

    # ------------------------------ config helpers ------------------------------
    def reload_config(self) -> CEConfig:
        self.config = load_config()
        return self.config

    def persist_config(self) -> None:
        save_config(self.config)

    # ------------------------------ database helpers ----------------------------
    def current_db_path(self) -> Path:
        return self.config.database.mdb_path

    def _copy_template(self, dest: Path) -> None:
        template = importlib.resources.files("complex_editor.assets").joinpath(
            "empty_template.mdb"
        )
        dest.parent.mkdir(parents=True, exist_ok=True)
        with importlib.resources.as_file(template) as tmpl_path:
            shutil.copy(tmpl_path, dest)

    def create_database(self, dest: Path, *, overwrite: bool = False) -> Path:
        dest = dest.expanduser()
        if dest.exists() and not overwrite:
            raise FileExistsError(f"Target already exists: {dest}")
        if dest.exists() and overwrite:
            dest.unlink()
        self._copy_template(dest)
        return dest

    def _close_db(self) -> None:
        if self.db is not None:
            try:
                self.db.__exit__(None, None, None)
            finally:
                self.db = None

    def open_main_db(self, file: Path | None = None, *, create_if_missing: bool = True) -> MDB:
        """Open the main MDB according to config or explicit ``file``."""
        target = Path(file) if file is not None else self.current_db_path()
        target = target.expanduser().resolve()
        if create_if_missing and not target.exists():
            self._copy_template(target)
        if not target.exists():
            raise FileNotFoundError(f"MDB not found at {target}")
        self._close_db()
        self.db = MDB(target)
        self.config.database.mdb_path = target
        return self.db

    def reconnect(self) -> MDB:
        return self.open_main_db(self.current_db_path(), create_if_missing=False)

    def update_mdb_path(self, new_path: Path, *, create_if_missing: bool = False) -> MDB:
        new_path = new_path.expanduser()
        if create_if_missing and not new_path.exists():
            self._copy_template(new_path)
        if not new_path.exists():
            raise FileNotFoundError(f"MDB not found at {new_path}")
        self.config.database.mdb_path = new_path
        return self.open_main_db(new_path, create_if_missing=False)

    def close(self) -> None:
        self._close_db()


__all__ = ["AppContext"]
