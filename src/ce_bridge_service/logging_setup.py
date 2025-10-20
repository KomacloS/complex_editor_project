from __future__ import annotations

import os
from pathlib import Path


def _expand(path_value: str) -> Path:
    return Path(os.path.expandvars(path_value)).expanduser()


def resolve_log_file() -> Path:
    """Return the target log file path based on environment overrides."""
    file_override = os.environ.get("CE_LOG_FILE", "").strip()
    if file_override:
        try:
            return _expand(file_override)
        except Exception:
            pass

    dir_override = os.environ.get("CE_LOG_DIR", "").strip()
    if dir_override:
        try:
            return _expand(dir_override) / "bridge.log"
        except Exception:
            pass

    if os.name == "nt":
        base = os.environ.get("LOCALAPPDATA")
        if base:
            return Path(base).expanduser() / "CE" / "logs" / "bridge.log"
        return Path.home() / "AppData" / "Local" / "CE" / "logs" / "bridge.log"

    return Path.home() / ".local" / "share" / "ce" / "logs" / "bridge.log"


def resolve_log_dir() -> Path:
    return resolve_log_file().parent
