from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from complex_editor.assets import write_template

if TYPE_CHECKING:  # pragma: no cover - for type hints only
    from complex_editor.db.mdb_api import MDB


class AppContext:
    def __init__(self) -> None:
        self.db: MDB | None = None

    def _create_empty_db(self, path: Path) -> None:
        import win32com.client

        win32com.client.Dispatch("ADOX.Catalog").Create(
            rf"Provider=Microsoft.Jet.OLEDB.4.0;Data Source={path}"
        )

    def open_main_db(self, file: Path) -> MDB:
        """Open or create the main MDB and return the handle."""
        for attempt in range(2):
            if not file.exists():
                file.parent.mkdir(parents=True, exist_ok=True)
                try:
                    write_template(file)
                except Exception:
                    try:
                        self._create_empty_db(file)
                    except Exception:
                        if attempt:
                            raise
                        else:
                            continue
            if self.db:
                self.db.__exit__(None, None, None)
                self.db = None
            try:
                from complex_editor.db.mdb_api import MDB
                import pyodbc  # noqa: F401  # imported here to delay requirement
                self.db = MDB(file)
                return self.db
            except Exception:
                if attempt:
                    raise
                if file.exists():
                    file.unlink()
        raise RuntimeError("Could not open main database")
