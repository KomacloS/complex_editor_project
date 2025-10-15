from __future__ import annotations

import importlib.resources
import shutil
from pathlib import Path
from typing import Optional

from complex_editor.config.loader import CEConfig, load_config, save_config
from complex_editor.db.mdb_api import MDB
from complex_editor.internal.paths import get_app_root, get_internal_root


class AppContext:
    """Central application state: config + database handle."""

    def __init__(self, config: Optional[CEConfig] = None) -> None:
        self.config: CEConfig = config or load_config()
        persist_needed = False
        if self._is_packaged_path(self.config.source_path):
            self.config.with_source(self._user_config_path())
            persist_needed = True
        if self._needs_database_migration(self.config.database.mdb_path):
            self.config.database.mdb_path = self._default_db_path()
            persist_needed = True
        if persist_needed:
            try:
                self.persist_config()
            except Exception:
                pass
        self.db: MDB | None = None
        self.wizard_open: bool = False
        self.unsaved_changes: bool = False
        self.focused_comp_id: int | None = None

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
        candidates = ("MAIN_DB.mdb", "empty_template.mdb")
        assets_pkg = "complex_editor.assets"
        dest.parent.mkdir(parents=True, exist_ok=True)
        files_fn = getattr(importlib.resources, "files", None)
        for name in candidates:
            try:
                if files_fn is not None:
                    resource = files_fn(assets_pkg).joinpath(name)
                    with importlib.resources.as_file(resource) as tmpl_path:
                        if tmpl_path.exists() and tmpl_path.stat().st_size > 0:
                            shutil.copy(tmpl_path, dest)
                            return
                else:  # pragma: no cover - legacy Python fallback
                    with importlib.resources.path(assets_pkg, name) as tmpl_path:  # type: ignore[attr-defined]
                        if tmpl_path.exists() and tmpl_path.stat().st_size > 0:
                            shutil.copy(tmpl_path, dest)
                            return
            except (FileNotFoundError, AttributeError):
                continue
        raise FileNotFoundError("No database template available in assets package")

    @staticmethod
    def _default_db_path() -> Path:
        return Path.home() / "Documents" / "ComplexBuilder" / "main_db.mdb"

    @staticmethod
    def _user_config_path() -> Path:
        return Path.home() / ".complex_editor" / "complex_editor.yml"

    def _is_packaged_path(self, source: Optional[Path]) -> bool:
        if source is None:
            return True
        try:
            resolved = source.expanduser().resolve(strict=False)
        except Exception:
            resolved = source
        roots: list[Path] = []
        for root_fn in (get_internal_root, get_app_root):
            try:
                roots.append(root_fn().resolve(strict=False))
            except Exception:
                roots.append(root_fn())
        for root in roots:
            try:
                if resolved.is_relative_to(root):
                    return True
            except AttributeError:  # pragma: no cover - legacy Python fallback
                if root in resolved.parents or resolved == root:
                    return True
            except ValueError:
                continue
        return False

    def _needs_database_migration(self, candidate: Path) -> bool:
        if self._is_packaged_path(candidate):
            return True
        expanded = candidate.expanduser()
        try:
            resolved = expanded.resolve(strict=False)
        except Exception:
            resolved = expanded
        try:
            if resolved.exists() and resolved.stat().st_size == 0:
                return True
        except OSError:
            pass
        return False

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
        target = target.expanduser().resolve(strict=False)
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

    # ----------------------------- wizard tracking ---------------------------
    def wizard_opened(self) -> None:
        """Mark the new complex wizard as open with unsaved data."""

        self.wizard_open = True
        self.unsaved_changes = True

    def wizard_closed(self, *, saved: bool, had_changes: bool = False) -> None:
        """Update wizard flags when the dialog closes.

        Parameters
        ----------
        saved:
            ``True`` when the wizard successfully persisted changes.
        had_changes:
            ``True`` if the user made changes that were not saved.  When
            ``False`` the wizard closed without modifications and we clear the
            unsaved flag regardless of ``saved``.
        """

        self.wizard_open = False
        if saved or not had_changes:
            self.unsaved_changes = False
        else:
            # Preserve the unsaved flag so external controllers know that work
            # was lost (for example when persistence fails).
            self.unsaved_changes = True

    def bridge_state(self) -> dict[str, object]:
        """Return a snapshot of bridge-relevant state."""

        return {
            "wizard_open": bool(self.wizard_open),
            "unsaved_changes": bool(self.unsaved_changes),
            "mdb_path": str(self.current_db_path()),
            "focused_comp_id": None if self.focused_comp_id is None else int(self.focused_comp_id),
        }


__all__ = ["AppContext"]
