from __future__ import annotations

import os
from pathlib import Path
import importlib
import builtins

import pytest

import sys

ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from complex_editor.config.loader import (
    CONFIG_ENV_VAR,
    ConfigError,
    DEFAULT_MDB_PATH,
    load_config,
    save_config,
)


def test_config_load_save_roundtrip(tmp_path, monkeypatch):
    cfg_path = tmp_path / "bridge.yml"
    monkeypatch.setenv(CONFIG_ENV_VAR, str(cfg_path))

    cfg = load_config()
    assert cfg.database.mdb_path == DEFAULT_MDB_PATH

    custom_path = tmp_path / "prod" / "complex.accdb"
    cfg.database.mdb_path = custom_path
    cfg.links.bom_db_hint = "http://example.test"
    cfg.bridge.enabled = True
    cfg.bridge.host = "127.0.0.1"
    cfg.bridge.port = 8123
    cfg.bridge.auth_token = "secret"
    save_config(cfg)

    loaded = load_config()
    assert loaded.database.mdb_path == custom_path
    assert loaded.links.bom_db_hint == "http://example.test"
    assert loaded.bridge.enabled is True
    assert loaded.bridge.port == 8123
    assert loaded.bridge.auth_token == "secret"
    assert loaded.source_path == Path(cfg_path)


def test_env_override_uses_specified_file(tmp_path, monkeypatch):
    first = tmp_path / "first.yml"
    second = tmp_path / "second.yml"

    monkeypatch.setenv(CONFIG_ENV_VAR, str(first))
    cfg1 = load_config()
    cfg1.links.bom_db_hint = "env-first"
    save_config(cfg1)

    monkeypatch.setenv(CONFIG_ENV_VAR, str(second))
    cfg2 = load_config()
    assert cfg2.links.bom_db_hint != "env-first"
    assert cfg2.source_path == Path(second)


def test_invalid_database_path_raises(tmp_path, monkeypatch):
    cfg_path = tmp_path / "invalid.yml"
    cfg_path.write_text("database:\n  mdb_path: .\n", encoding="utf-8")
    monkeypatch.setenv(CONFIG_ENV_VAR, str(cfg_path))
    with pytest.raises(ConfigError):
        load_config()


def test_loader_works_without_pyyaml(tmp_path, monkeypatch):
    cfg_path = tmp_path / "fallback.yml"
    cfg_path.write_text(
        "\n".join(
            [
                "database:",
                "  mdb_path: C:/Temp/complex.accdb",
                "links:",
                "  bom_db_hint: http://example.invalid",
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv(CONFIG_ENV_VAR, str(cfg_path))

    import complex_editor.utils.yaml_adapter as yaml_adapter
    import complex_editor.config.loader as loader_module

    real_import = builtins.__import__

    def fake_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "yaml":
            raise ModuleNotFoundError("No module named 'yaml'")
        return real_import(name, globals, locals, fromlist, level)

    with monkeypatch.context() as ctx:
        ctx.setattr(builtins, "__import__", fake_import)
        importlib.reload(yaml_adapter)
        importlib.reload(loader_module)

        cfg = loader_module.load_config()
        assert cfg.database.mdb_path == Path("C:/Temp/complex.accdb")
        assert cfg.links.bom_db_hint == "http://example.invalid"
        cfg.links.bom_db_hint = "changed"
        loader_module.save_config(cfg)

    importlib.reload(yaml_adapter)
    importlib.reload(loader_module)

    saved = cfg_path.read_text(encoding="utf-8")
    assert "changed" in saved
