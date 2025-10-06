from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Optional
import os

import yaml

CONFIG_ENV_VAR = "CE_CONFIG"

_CONFIG_RELATIVE_PATH = Path("config") / "complex_editor.yml"
_SRC_ROOT = Path(__file__).resolve().parents[3]
_REPO_ROOT = _SRC_ROOT.parent
DEFAULT_CONFIG_PATH = (_REPO_ROOT / _CONFIG_RELATIVE_PATH).resolve()
DEFAULT_MDB_PATH = Path(r"C:/ProductionData/Complexes/complexes.accdb")


class ConfigError(Exception):
    """Raised when the configuration file is malformed or invalid."""


@dataclass
class DatabaseConfig:
    mdb_path: Path


@dataclass
class LinksConfig:
    bom_db_hint: str = ""


@dataclass
class BridgeConfig:
    enabled: bool = False
    base_url: str = "http://127.0.0.1:8765"
    auth_token: str = ""
    host: str = "0.0.0.0"
    port: int = 8765
    request_timeout_seconds: int = 15


@dataclass
class CEConfig:
    database: DatabaseConfig
    links: LinksConfig = field(default_factory=LinksConfig)
    bridge: BridgeConfig = field(default_factory=BridgeConfig)
    _source_path: Optional[Path] = field(default=None, repr=False, compare=False)

    @property
    def source_path(self) -> Optional[Path]:
        return self._source_path

    def with_source(self, path: Path) -> "CEConfig":
        self._source_path = path
        return self


def _default_dict() -> Dict[str, Any]:
    return {
        "database": {
            "mdb_path": str(DEFAULT_MDB_PATH),
        },
        "links": {"bom_db_hint": ""},
        "bridge": {
            "enabled": False,
            "base_url": "http://127.0.0.1:8765",
            "auth_token": "",
            "host": "0.0.0.0",
            "port": 8765,
            "request_timeout_seconds": 15,
        },
    }


def _resolve_config_path() -> Path:
    env_override = os.environ.get(CONFIG_ENV_VAR)
    if env_override:
        return Path(env_override).expanduser().resolve()
    return DEFAULT_CONFIG_PATH


def _coerce_database(section: Dict[str, Any]) -> DatabaseConfig:
    try:
        raw_path = section["mdb_path"]
    except KeyError as exc:
        raise ConfigError("database.mdb_path missing") from exc
    if not isinstance(raw_path, str) or not raw_path.strip():
        raise ConfigError("database.mdb_path must be a non-empty string")
    path = Path(raw_path).expanduser()
    if path.exists() and path.is_dir():
        raise ConfigError("database.mdb_path points to a directory, expected file")
    # ensure parent directory can be created
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
    except Exception as exc:  # pragma: no cover - defensive
        raise ConfigError(f"Unable to ensure parent directory for {path}") from exc
    return DatabaseConfig(mdb_path=path)


def _coerce_links(section: Dict[str, Any]) -> LinksConfig:
    hint = section.get("bom_db_hint", "")
    if hint is None:
        hint = ""
    if not isinstance(hint, str):
        raise ConfigError("links.bom_db_hint must be a string")
    return LinksConfig(bom_db_hint=hint.strip())


def _coerce_bridge(section: Dict[str, Any]) -> BridgeConfig:
    enabled = bool(section.get("enabled", False))
    base_url = section.get("base_url", "http://127.0.0.1:8765")
    auth_token = section.get("auth_token", "") or ""
    host = section.get("host", "0.0.0.0")
    port = section.get("port", 8765)
    timeout = section.get("request_timeout_seconds", 15)

    if not isinstance(base_url, str):
        raise ConfigError("bridge.base_url must be a string")
    if not isinstance(auth_token, str):
        raise ConfigError("bridge.auth_token must be a string")
    if not isinstance(host, str) or not host:
        raise ConfigError("bridge.host must be a non-empty string")
    try:
        port = int(port)
    except (TypeError, ValueError) as exc:
        raise ConfigError("bridge.port must be an integer") from exc
    if port <= 0 or port > 65535:
        raise ConfigError("bridge.port must be between 1 and 65535")
    try:
        timeout = int(timeout)
    except (TypeError, ValueError) as exc:
        raise ConfigError("bridge.request_timeout_seconds must be an integer") from exc
    if timeout <= 0:
        raise ConfigError("bridge.request_timeout_seconds must be positive")

    return BridgeConfig(
        enabled=enabled,
        base_url=str(base_url),
        auth_token=auth_token.strip(),
        host=host,
        port=port,
        request_timeout_seconds=timeout,
    )


def _coerce_config(raw: Dict[str, Any]) -> CEConfig:
    base = _default_dict()
    merged: Dict[str, Any] = {}
    merged.update(base)
    merged.update(raw or {})

    db_section = merged.get("database", {})
    links_section = merged.get("links", {})
    bridge_section = merged.get("bridge", {})

    database = _coerce_database(db_section)
    links = _coerce_links(links_section)
    bridge = _coerce_bridge(bridge_section)

    return CEConfig(database=database, links=links, bridge=bridge)


def load_config() -> CEConfig:
    path = _resolve_config_path()
    if path.exists():
        with path.open("r", encoding="utf-8") as handle:
            raw = yaml.safe_load(handle) or {}
    else:
        raw = {}
    config = _coerce_config(raw)
    config.with_source(path)
    return config


def save_config(config: CEConfig) -> None:
    target = config.source_path or _resolve_config_path()
    data = {
        "database": {
            "mdb_path": str(config.database.mdb_path),
        },
        "links": {
            "bom_db_hint": config.links.bom_db_hint,
        },
        "bridge": {
            "enabled": config.bridge.enabled,
            "base_url": config.bridge.base_url,
            "auth_token": config.bridge.auth_token,
            "host": config.bridge.host,
            "port": int(config.bridge.port),
            "request_timeout_seconds": int(config.bridge.request_timeout_seconds),
        },
    }
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("w", encoding="utf-8") as handle:
        yaml.safe_dump(data, handle, sort_keys=False)
    config.with_source(target)


__all__ = [
    "CONFIG_ENV_VAR",
    "CEConfig",
    "DatabaseConfig",
    "LinksConfig",
    "BridgeConfig",
    "ConfigError",
    "load_config",
    "save_config",
]
