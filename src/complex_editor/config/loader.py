from __future__ import annotations

import copy
import os
import pkgutil
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Optional, cast

import importlib.resources

from ..utils import yaml_adapter as yaml

from ..internal.paths import get_app_root, get_internal_root

CONFIG_ENV_VAR = "CE_CONFIG"

_CONFIG_FILENAME = "complex_editor.yml"
_DEFAULT_CONFIG_RESOURCE = "default_config.yaml"


class ConfigError(Exception):
    """Raised when the configuration file is malformed or invalid."""


def _load_default_config() -> Dict[str, Any]:
    package = "complex_editor.resources"

    def _read_default_config_text() -> Optional[str]:
        files_attr = getattr(importlib.resources, "files", None)
        if files_attr is not None:
            try:
                resource = files_attr(package) / _DEFAULT_CONFIG_RESOURCE
                return resource.read_text(encoding="utf-8")
            except (FileNotFoundError, AttributeError, OSError):
                pass

        open_text = getattr(importlib.resources, "open_text", None)
        if open_text is not None:
            try:
                with open_text(package, _DEFAULT_CONFIG_RESOURCE, encoding="utf-8") as fh:
                    return fh.read()
            except (FileNotFoundError, AttributeError, OSError):
                pass

        try:
            data = pkgutil.get_data(package, _DEFAULT_CONFIG_RESOURCE)
            if data is not None:
                return data.decode("utf-8")
        except (FileNotFoundError, OSError, UnicodeDecodeError):
            pass

        base_path = getattr(sys, "_MEIPASS", None)
        if base_path:
            candidate = (
                Path(base_path)
                / "complex_editor"
                / "resources"
                / _DEFAULT_CONFIG_RESOURCE
            )
            try:
                if candidate.exists():
                    return candidate.read_text(encoding="utf-8")
            except OSError:
                pass

        return None

    raw_text = _read_default_config_text()
    if raw_text is None:
        default_db = Path.home() / "Documents" / "ComplexBuilder" / "main_db.mdb"
        return {
            "database": {
                "mdb_path": str(default_db),
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
            "pn_normalization": {
                "case": "upper",
                "remove_chars": [" ", "-", "_", ".", "/", "–", "—", "\u00A0"],
                "ignore_suffixes": ["-TR", "-T", "-REEL", "/TP", "-BK"],
            },
        }

    data = yaml.safe_load(raw_text) or {}
    if not isinstance(data, dict):
        raise ConfigError("default_config.yaml must contain a mapping at the top level")
    return cast(Dict[str, Any], data)


_DEFAULT_CONFIG_DATA: Dict[str, Any] = _load_default_config()


def _default_config_candidates() -> list[Path]:
    candidates: list[Path] = []

    def _add(path: Path) -> None:
        resolved = path.resolve()
        if resolved not in candidates:
            candidates.append(resolved)

    _add(Path.home() / ".complex_editor" / _CONFIG_FILENAME)
    _add(get_internal_root() / "config" / _CONFIG_FILENAME)
    _add(get_app_root() / "config" / _CONFIG_FILENAME)
    _add(Path(__file__).resolve().parents[3] / "config" / _CONFIG_FILENAME)
    return candidates


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
    allow_headless_exports: Optional[bool] = None


@dataclass
class PnNormalizationConfig:
    case: str = "upper"
    remove_chars: tuple[str, ...] = (" ", "-", "_", ".", "/", "–", "—", "\u00A0")
    ignore_suffixes: tuple[str, ...] = ("-TR", "-T", "-REEL", "/TP", "-BK")


@dataclass
class CEConfig:
    database: DatabaseConfig
    links: LinksConfig = field(default_factory=LinksConfig)
    bridge: BridgeConfig = field(default_factory=BridgeConfig)
    pn_normalization: PnNormalizationConfig = field(default_factory=PnNormalizationConfig)
    _source_path: Optional[Path] = field(default=None, repr=False, compare=False)

    @property
    def source_path(self) -> Optional[Path]:
        return self._source_path

    def with_source(self, path: Path) -> "CEConfig":
        self._source_path = path
        return self


def _default_dict() -> Dict[str, Any]:
    return copy.deepcopy(_DEFAULT_CONFIG_DATA)


def _resolve_config_path() -> Path:
    env_override = os.environ.get(CONFIG_ENV_VAR)
    if env_override:
        return Path(env_override).expanduser().resolve()
    for candidate in _default_config_candidates():
        if candidate.exists():
            return candidate
    return _default_config_candidates()[0]


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
    allow_headless_raw = section.get("allow_headless_exports", None)
    allow_headless = None if allow_headless_raw is None else bool(allow_headless_raw)

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
        allow_headless_exports=allow_headless,
    )


def _coerce_pn_normalization(section: Dict[str, Any]) -> PnNormalizationConfig:
    if not isinstance(section, dict):
        raise ConfigError("pn_normalization must be a mapping")

    case_raw = section.get("case", "upper")
    if case_raw is None:
        case_raw = "upper"
    if not isinstance(case_raw, str):
        raise ConfigError("pn_normalization.case must be a string")
    case = case_raw.strip() or "upper"

    def _coerce_list(value: Any, name: str) -> tuple[str, ...]:
        if value is None:
            return tuple()
        if isinstance(value, str):
            items = [value]
        else:
            try:
                items = list(value)
            except TypeError as exc:  # pragma: no cover - defensive
                raise ConfigError(f"pn_normalization.{name} must be a list of strings") from exc
        result: list[str] = []
        for item in items:
            if item is None:
                continue
            text = str(item)
            if not text:
                continue
            result.append(text)
        return tuple(result)

    remove_chars = _coerce_list(section.get("remove_chars", (" ", "-", "_", ".", "/")), "remove_chars")
    ignore_suffixes = _coerce_list(
        section.get("ignore_suffixes", ("-TR", "-T", "-REEL", "/TP", "-BK")),
        "ignore_suffixes",
    )

    return PnNormalizationConfig(case=case, remove_chars=remove_chars, ignore_suffixes=ignore_suffixes)


def _coerce_config(raw: Dict[str, Any]) -> CEConfig:
    base = _default_dict()
    merged: Dict[str, Any] = {}
    merged.update(base)
    merged.update(raw or {})

    db_section = merged.get("database", {})
    links_section = merged.get("links", {})
    bridge_section = merged.get("bridge", {})
    pn_norm_section = merged.get("pn_normalization", {})

    database = _coerce_database(db_section)
    links = _coerce_links(links_section)
    bridge = _coerce_bridge(bridge_section)
    pn_norm = _coerce_pn_normalization(pn_norm_section)

    return CEConfig(database=database, links=links, bridge=bridge, pn_normalization=pn_norm)


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
        "pn_normalization": {
            "case": config.pn_normalization.case,
            "remove_chars": list(config.pn_normalization.remove_chars),
            "ignore_suffixes": list(config.pn_normalization.ignore_suffixes),
        },
    }
    if config.bridge.allow_headless_exports is not None:
        data["bridge"]["allow_headless_exports"] = bool(config.bridge.allow_headless_exports)
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
    "PnNormalizationConfig",
    "ConfigError",
    "load_config",
    "save_config",
]
