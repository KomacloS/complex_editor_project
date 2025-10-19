from __future__ import annotations

import json
import logging
import logging.handlers
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional


_TRACE_CTX_KEY = "trace_id"


def _default_log_dir() -> Path:
    if os.name == "nt":
        local = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA")
        if local:
            return Path(local) / "CE" / "logs"
        # Fallback to home if LOCALAPPDATA missing
        return Path.home() / "AppData" / "Local" / "CE" / "logs"
    return Path("/var/log/ce")


def resolve_log_dir() -> Path:
    raw = os.environ.get("CE_LOG_DIR", "").strip()
    if raw:
        try:
            return Path(os.path.expandvars(raw)).expanduser()
        except Exception:
            pass
    return _default_log_dir()


class JsonLogFormatter(logging.Formatter):
    def __init__(self) -> None:
        super().__init__()

    def format(self, record: logging.LogRecord) -> str:  # type: ignore[override]
        payload: dict[str, Any] = {}
        payload["time"] = (
            datetime.fromtimestamp(record.created, tz=timezone.utc)
            .isoformat()
            .replace("+00:00", "Z")
        )
        payload["level"] = record.levelname
        payload["logger"] = record.name
        payload["message"] = record.getMessage()

        trace_id = getattr(record, _TRACE_CTX_KEY, None)
        if isinstance(trace_id, str) and trace_id:
            payload["trace_id"] = trace_id

        # Common HTTP context fields if attached by middleware
        method = getattr(record, "method", None)
        path = getattr(record, "path", None)
        status = getattr(record, "status", None)
        duration = getattr(record, "duration_ms", None)
        event = getattr(record, "event", None)
        if method:
            payload["method"] = method
        if path:
            payload["path"] = path
        if status is not None:
            payload["status"] = status
        if duration is not None:
            payload["duration_ms"] = duration
        if event:
            payload["event"] = event

        # Capture exceptions when present
        exc_text: Optional[str] = None
        if record.exc_info:
            try:
                exc_text = self.formatException(record.exc_info)
            except Exception:
                exc_text = None
        if not exc_text:
            exc_text = getattr(record, "exception", None)
        if isinstance(exc_text, str) and exc_text:
            payload["exception"] = exc_text

        # Special handling for uvicorn.access default message to extract method/path/status
        if record.name == "uvicorn.access":
            # record.args may be a dict with keys: client_addr, request_line, status_code
            try:
                args = record.args or {}
                request_line = args.get("request_line")
                status_code = args.get("status_code")
                if isinstance(request_line, str):
                    # Example: "GET /path HTTP/1.1"
                    parts = request_line.split(" ")
                    if len(parts) >= 2:
                        payload.setdefault("method", parts[0])
                        payload.setdefault("path", parts[1])
                if status_code is not None:
                    payload.setdefault("status", status_code)
                payload.setdefault("event", "access")
            except Exception:
                pass

        return json.dumps(payload, ensure_ascii=False)


class PlainFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:  # type: ignore[override]
        ts = (
            datetime.fromtimestamp(record.created, tz=timezone.utc)
            .isoformat()
            .replace("+00:00", "Z")
        )
        base = f"{ts} {record.levelname} {record.name}: {record.getMessage()}"
        suffix = []
        trace_id = getattr(record, _TRACE_CTX_KEY, None)
        if isinstance(trace_id, str) and trace_id:
            suffix.append(f"trace_id={trace_id}")
        method = getattr(record, "method", None)
        path = getattr(record, "path", None)
        status = getattr(record, "status", None)
        duration = getattr(record, "duration_ms", None)
        event = getattr(record, "event", None)
        if method:
            suffix.append(f"method={method}")
        if path:
            suffix.append(f"path={path}")
        if status is not None:
            suffix.append(f"status={status}")
        if duration is not None:
            suffix.append(f"duration_ms={duration}")
        if event:
            suffix.append(f"event={event}")
        if record.exc_info:
            try:
                exc_text = self.formatException(record.exc_info)
            except Exception:
                exc_text = None
            if exc_text:
                suffix.append(f"exception={exc_text}")
        else:
            exc_text = getattr(record, "exception", None)
            if isinstance(exc_text, str) and exc_text:
                suffix.append(f"exception={exc_text}")
        if suffix:
            base += " " + " ".join(suffix)
        return base


def _build_handler(log_dir: Path, json_mode: bool, max_bytes: int, backups: int) -> logging.Handler:
    log_dir.mkdir(parents=True, exist_ok=True)
    logfile = log_dir / "ce_bridge.log"
    handler = logging.handlers.RotatingFileHandler(
        str(logfile), maxBytes=max_bytes, backupCount=backups, encoding="utf-8"
    )
    handler.setFormatter(JsonLogFormatter() if json_mode else PlainFormatter())
    return handler


def setup_logging() -> Path:
    # Env configuration
    log_dir = resolve_log_dir()
    level = os.environ.get("CE_LOG_LEVEL", "INFO").upper().strip() or "INFO"
    json_mode = (os.environ.get("CE_LOG_JSON", "true").strip().lower() != "false")
    max_bytes = int(os.environ.get("CE_LOG_MAX_BYTES", str(10_485_760)))
    backups = int(os.environ.get("CE_LOG_BACKUP_COUNT", str(5)))

    handler = _build_handler(log_dir, json_mode, max_bytes, backups)

    root = logging.getLogger()
    # Avoid duplicate handlers on reconfigure in tests
    for h in list(root.handlers):
        if isinstance(h, logging.handlers.RotatingFileHandler) and getattr(h, "baseFilename", "").endswith("ce_bridge.log"):
            root.removeHandler(h)
    root.addHandler(handler)
    try:
        root.setLevel(getattr(logging, level, logging.INFO))
    except Exception:
        root.setLevel(logging.INFO)

    # Route uvicorn.access to the same handler, use JSON formatter for it as well
    access_logger = logging.getLogger("uvicorn.access")
    access_logger.handlers = [handler]
    access_logger.propagate = False
    access_logger.setLevel(root.level)

    # Also route uvicorn.error to root so exceptions are captured
    logging.getLogger("uvicorn.error").setLevel(root.level)

    logging.getLogger(__name__).info("CE bridge logs directory: %s", str(log_dir))
    return log_dir

