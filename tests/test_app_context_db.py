from __future__ import annotations

from pathlib import Path

import pytest

import sys

ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from complex_editor.config.loader import CONFIG_ENV_VAR, load_config, save_config
from complex_editor.core.app_context import AppContext


class DummyMDB:
    def __init__(self, file):
        self.path = Path(file)
        self.closed = False

    def __exit__(self, exc_type, exc, tb):
        self.closed = True


def test_app_context_reconnects_on_path_change(tmp_path, monkeypatch):
    cfg_path = tmp_path / "ctx.yml"
    monkeypatch.setenv(CONFIG_ENV_VAR, str(cfg_path))

    cfg = load_config()
    original_db = tmp_path / "db1.accdb"
    cfg.database.mdb_path = original_db
    save_config(cfg)

    monkeypatch.setattr("complex_editor.core.app_context.MDB", DummyMDB)

    def fake_copy(self, dest: Path) -> None:
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.touch()

    monkeypatch.setattr(AppContext, "_copy_template", fake_copy)

    ctx = AppContext()
    ctx.open_main_db(create_if_missing=True)
    first = ctx.db
    assert isinstance(first, DummyMDB)
    assert first.path == original_db

    new_db = tmp_path / "db2.accdb"
    ctx.update_mdb_path(new_db, create_if_missing=True)
    assert isinstance(ctx.db, DummyMDB)
    assert ctx.db is not first
    assert first.closed is True
    assert ctx.db.path == new_db
    assert ctx.config.database.mdb_path == new_db

    ctx.persist_config()
    reloaded = load_config()
    assert reloaded.database.mdb_path == new_db
