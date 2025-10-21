from __future__ import annotations

import asyncio
from collections import Counter
import importlib.resources
import importlib.resources as _ires
import hashlib
import json
import logging
from logging.handlers import RotatingFileHandler
import os
import secrets
import tempfile
import uuid
from dataclasses import dataclass
from pathlib import Path
import re
from typing import Callable, Dict, List, Optional, Sequence

from fastapi import Depends, FastAPI, HTTPException, Query, Request, status
from fastapi.responses import JSONResponse

from complex_editor import __version__
from complex_editor.config.loader import PnNormalizationConfig
from complex_editor.db import SubsetExportError
from complex_editor.db.mdb_api import (
    ALIAS_T,
    DETAIL_T,
    MASTER_T,
    MDB,
    NAME_COL,
    PK_DETAIL,
    PK_MASTER,
)

from .models import (
    AliasUpdateRequest,
    AliasUpdateResponse,
    ComplexCreateRequest,
    ComplexCreateResponse,
    ComplexOpenRequest,
    ComplexDetail,
    ComplexSummary,
    MatchKind,
    MdbExportRequest,
    MdbExportResponse,
    ResolvedPart,
)
from .types import BridgeCreateResult
from .logging_setup import resolve_log_file
from .middleware_trace import TraceIdMiddleware, TRACE_HEADER
from .exceptions import install_exception_handlers
from .admin_logs import router as admin_logs_router
from .normalization import NORMALIZATION_RULES_VERSION, PartNumberNormalizer

try:  # pragma: no cover - optional dependency during tests
    import pyodbc  # type: ignore

    _PYODBC_ERROR = (pyodbc.Error,)  # type: ignore[attr-defined]
except Exception:  # pragma: no cover - pyodbc not available in unit tests
    pyodbc = None  # type: ignore[assignment]
    _PYODBC_ERROR = tuple()


logger = logging.getLogger(__name__)


def _truthy(raw: str | None) -> bool:
    if raw is None:
        return False
    return raw.strip().lower() in {"1", "true", "yes", "on"}


class _BridgeFormatter(logging.Formatter):
    def __init__(self) -> None:
        super().__init__(
            "%(asctime)s %(levelname)s %(name)s: %(message)s",
            "%Y-%m-%dT%H:%M:%S%z",
        )

    def format(self, record: logging.LogRecord) -> str:  # type: ignore[override]
        base = super().format(record)
        extras: list[str] = []
        for key in ("trace_id", "event", "method", "path", "status", "duration_ms"):
            value = getattr(record, key, None)
            if value is None:
                continue
            if isinstance(value, str):
                if not value:
                    continue
                extras.append(f"{key}={value}")
            else:
                extras.append(f"{key}={value}")
        if extras:
            return f"{base} {' '.join(extras)}"
        return base


def configure_logging() -> Path | None:
    """Configure application logging based on environment variables."""

    level_name = (os.environ.get("CE_LOG_LEVEL", "WARNING") or "").strip().upper() or "WARNING"
    debug_enabled = _truthy(os.environ.get("CE_DEBUG"))
    if debug_enabled:
        level_name = "DEBUG"
    level = getattr(logging, level_name, logging.WARNING)

    log_file = resolve_log_file()
    formatter = _BridgeFormatter()
    handlers: list[logging.Handler] = []
    destination: Path | None = log_file

    try:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        file_handler = RotatingFileHandler(
            log_file,
            maxBytes=5_000_000,
            backupCount=3,
            encoding="utf-8",
        )
        file_handler.setLevel(level)
        file_handler.setFormatter(formatter)
        handlers.append(file_handler)
    except OSError:
        destination = None
        stream_handler = logging.StreamHandler()
        stream_handler.setLevel(level)
        stream_handler.setFormatter(formatter)
        handlers.append(stream_handler)

    if debug_enabled and destination is not None:
        console_handler = logging.StreamHandler()
        console_handler.setLevel(logging.DEBUG)
        console_handler.setFormatter(formatter)
        handlers.append(console_handler)

    root_logger = logging.getLogger()
    for existing in list(root_logger.handlers):
        root_logger.removeHandler(existing)
    for handler in handlers:
        root_logger.addHandler(handler)
    root_logger.setLevel(level)

    for name in ("uvicorn", "uvicorn.error", "uvicorn.access", "ce_bridge_service", "complex_editor"):
        target = logging.getLogger(name)
        target.handlers = []
        target.setLevel(level)
        target.propagate = True

    configured_logger = logging.getLogger(__name__)
    if destination is None:
        configured_logger.warning(
            "Logging to console because CE_LOG_FILE/CE_LOG_DIR is unavailable."
        )
    else:
        configured_logger.debug("Logging configured for file %s", destination)

    return destination

ASSET_PKG = "complex_editor.assets"
ASSET_NAME = "Empty_mdb.mdb"


class TemplateResolutionError(Exception):
    def __init__(self, attempted: str) -> None:
        super().__init__("Template file is missing or empty.")
        self.attempted = attempted


def _resolve_template_path(requested: str | None) -> Path:
    attempts: list[str] = []

    def _validate(candidate: Path) -> Path:
        attempts.append(str(candidate))
        try:
            exists = candidate.exists()
            size = candidate.stat().st_size if exists else 0
        except OSError as exc:
            raise TemplateResolutionError(str(candidate)) from exc
        if not exists or size <= 0:
            raise TemplateResolutionError(str(candidate))
        return candidate.resolve()

    if requested:
        candidate = Path(requested).expanduser()
        return _validate(candidate)

    env = os.environ.get("CE_TEMPLATE_MDB", "").strip()
    if env:
        env_path = Path(env).expanduser()
        return _validate(env_path)

    try:
        resource = _ires.files(ASSET_PKG) / ASSET_NAME
        with _ires.as_file(resource) as asset_path:
            asset = Path(asset_path)
            return _validate(asset)
    except TemplateResolutionError:
        raise
    except Exception:
        pass

    attempted = attempts[-1] if attempts else ""
    raise TemplateResolutionError(attempted)


class FocusBusyError(Exception):
    """Raised when the UI refuses to focus/open the requested complex because it is busy."""


def create_app(
    *,
    get_mdb_path: Callable[[], Path],
    auth_token: str | None = None,
    wizard_handler: Optional[Callable[[str, Optional[List[str]]], BridgeCreateResult]] = None,
    mdb_factory: Optional[Callable[[Path], MDB]] = None,
    bridge_host: str | None = None,
    bridge_port: int | None = None,
    state_provider: Callable[[], Dict[str, object]] | None = None,
    focus_handler: Callable[[int, str], Dict[str, object]] | None = None,
    allow_headless_exports: bool | None = None,
    pn_normalization: PnNormalizationConfig | None = None,
) -> FastAPI:
    """Return a configured FastAPI application for the bridge."""

    # Configure logging early
    log_file = configure_logging()
    log_dir = log_file.parent if isinstance(log_file, Path) else None
    token = (auth_token or "").strip()
    auth_mode = "enabled" if token else "disabled"
    app = FastAPI(title="Complex Editor Bridge", version=__version__)
    app.state.bridge_host = bridge_host or ""
    app.state.bridge_port = int(bridge_port) if bridge_port is not None else 0
    app.state.trigger_shutdown = lambda: None
    app.state.auth_required = bool(token)
    app.state.ready = False
    app.state.last_ready_error = "warming_up"
    app.state.mdb_path = ""
    app.state.last_ready_checks = []
    app.state.wizard_available = wizard_handler is not None
    app.state._observed_mdb_path = ""
    app.state._readiness_lock = asyncio.Lock()
    app.state._readiness_task = None
    app.state._reschedule_required = False
    app.state._pending_mdb_path = None
    app.state.focused_comp_id = None
    app.state.wizard_open = False
    app.state.log_file_path = str(log_file) if isinstance(log_file, Path) else ""
    app.state.log_directory = str(log_dir) if log_dir is not None else ""
    app.state.focus_handler_available = bool(focus_handler)
    factory = mdb_factory or MDB

    headless_mode = wizard_handler is None
    app.state.headless = headless_mode
    app.state.ui_present = not headless_mode

    normalization_config = pn_normalization or PnNormalizationConfig()
    normalizer = PartNumberNormalizer(normalization_config)
    app.state.normalization_rules_version = NORMALIZATION_RULES_VERSION
    app.state.search_match_kind_supported = True
    app.state.pn_normalizer = normalizer
    logger.info(
        "PN normalization configured case=%s remove_chars=%s ignore_suffixes=%s version=%s",
        normalization_config.case,
        list(normalization_config.remove_chars),
        list(normalization_config.ignore_suffixes),
        NORMALIZATION_RULES_VERSION,
        extra={"event": "pn_normalization_config"},
    )

    def _effective_allow_headless() -> bool:
        if allow_headless_exports is not None:
            return bool(allow_headless_exports)
        return _truthy(os.getenv("CE_ALLOW_HEADLESS_EXPORTS"))

    def _allow_headless_current() -> bool:
        effective = bool(_effective_allow_headless())
        app.state.allow_headless_exports = effective
        return effective

    app.state.allow_headless_exports = _allow_headless_current()

    # Install exception handlers
    install_exception_handlers(app)

    # Trace middleware (propagate or generate X-Trace-Id, log access)
    app.add_middleware(TraceIdMiddleware)

    # Protected admin logs router under /admin
    def _require_auth(request: Request) -> None:
        if not token:
            return
        header = request.headers.get("Authorization", "").strip()
        if not header or not header.lower().startswith("bearer "):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Missing bearer token",
            )
        candidate = header.split(" ", 1)[1].strip()
        if not candidate:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Missing bearer token",
            )
        if not secrets.compare_digest(candidate, token):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Invalid bearer token",
            )

    app.include_router(admin_logs_router, prefix="/admin", dependencies=[Depends(_require_auth)])

    def _caller_identity(request: Request) -> str:
        client = getattr(request, "client", None)
        if client is None:
            return ""
        host = getattr(client, "host", "") or ""
        port = getattr(client, "port", None)
        if port not in (None, 0):
            return f"{host}:{port}"
        return host

    def _set_ready(value: bool, reason: str = "", *, force_log: bool = False) -> None:
        previous = bool(getattr(app.state, "ready", False))
        app.state.ready = bool(value)
        error = "" if value else (reason or "warming_up")
        app.state.last_ready_error = error
        if previous != app.state.ready or force_log:
            host = app.state.bridge_host or ""
            port = app.state.bridge_port or 0
            if app.state.ready:
                logger.info("Bridge ready host=%s port=%s auth=%s", host, port, auth_mode)
            else:
                logger.warning(
                    "Bridge not ready host=%s port=%s auth=%s reason=%s",
                    host,
                    port,
                    auth_mode,
                    error or "warming_up",
                )

    def _summarize_failures(checks: List[Dict[str, object]]) -> str:
        failures: List[str] = []
        for entry in checks:
            if entry.get("ok"):
                continue
            detail = entry.get("detail")
            if detail is None:
                detail = entry.get("name", "")
            failures.append(str(detail))
        summary = "; ".join(part for part in (item.strip() for item in failures) if part)
        return summary

    def _execute_checks() -> tuple[bool, List[Dict[str, object]], str]:
        checks: List[Dict[str, object]] = []
        ok_all = True
        resolved_path = ""

        def record_success(name: str, detail: Optional[str] = None) -> None:
            entry: Dict[str, object] = {"name": name, "ok": True}
            if detail:
                entry["detail"] = detail
            checks.append(entry)

        def record_failure(name: str, error: Exception) -> None:
            nonlocal ok_all
            ok_all = False
            checks.append({"name": name, "ok": False, "detail": str(error)})

        try:
            raw_path = get_mdb_path()
            path = raw_path if isinstance(raw_path, Path) else Path(str(raw_path))
            resolved_path = str(path)
            record_success("config_loaded", resolved_path)
        except Exception as exc:
            record_failure("config_loaded", exc)
            return False, checks, resolved_path

        path_obj = Path(resolved_path)
        try:
            if not path_obj.exists():
                raise FileNotFoundError(resolved_path)
            if not path_obj.is_file():
                raise IsADirectoryError(resolved_path)
            record_success("mdb_path_accessible", resolved_path)
        except Exception as exc:
            record_failure("mdb_path_accessible", exc)
            return False, checks, resolved_path

        try:
            with factory(path_obj) as db:
                cur = db._cur()
                cur.execute(f"SELECT {PK_MASTER} FROM {MASTER_T}")
                cur.fetchall()
            record_success("mdb_connection", "select_ok")
        except Exception as exc:
            record_failure("mdb_connection", exc)

        try:
            signature = hashlib.sha256(resolved_path.encode("utf-8")).hexdigest()
            record_success("bridge_signature", signature)
        except Exception as exc:
            record_failure("bridge_signature", exc)

        record_success("auth_mode", auth_mode)
        return ok_all, checks, resolved_path

    async def run_startup_checks() -> tuple[bool, List[Dict[str, object]], str]:
        return await asyncio.to_thread(_execute_checks)

    def _apply_check_result(
        ok: bool,
        checks: List[Dict[str, object]],
        resolved_path: str,
        *,
        log_failures: bool,
    ) -> None:
        app.state.last_ready_checks = list(checks)
        app.state.mdb_path = resolved_path
        pending = getattr(app.state, "_pending_mdb_path", None)
        if pending and str(pending) == resolved_path:
            app.state._pending_mdb_path = None
        if ok:
            _set_ready(True, "")
            return
        reason = _summarize_failures(checks) or "readiness_failed"
        _set_ready(False, reason, force_log=log_failures)

    def _record_exception(exc: Exception) -> None:
        app.state.last_ready_checks = []
        message = f"{type(exc).__name__}: {exc}"
        _set_ready(False, message, force_log=True)

    async def _perform_check_and_update(*, log_failures: bool) -> tuple[bool, List[Dict[str, object]], str]:
        async with app.state._readiness_lock:
            try:
                ok, checks, resolved_path = await run_startup_checks()
            except Exception as exc:  # pragma: no cover - defensive
                _record_exception(exc)
                return False, [], str(getattr(app.state, "mdb_path", ""))
            _apply_check_result(ok, checks, resolved_path, log_failures=log_failures)
            return ok, checks, resolved_path

    async def _background_readiness_runner(log_failures: bool) -> None:
        try:
            while True:
                await _perform_check_and_update(log_failures=log_failures)
                if not getattr(app.state, "_reschedule_required", False):
                    break
                app.state._reschedule_required = False
        finally:
            app.state._readiness_task = None
            app.state._reschedule_required = False

    def _schedule_readiness_check(*, log_failures: bool) -> None:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:  # pragma: no cover - startup safeguard
            return
        task = getattr(app.state, "_readiness_task", None)
        if task is None or task.done():
            app.state._reschedule_required = False
            app.state._readiness_task = loop.create_task(
                _background_readiness_runner(log_failures)
            )
        else:
            app.state._reschedule_required = True

    @app.on_event("startup")
    async def _on_app_startup() -> None:
        _set_ready(False, "warming_up")
        logger.info(
            "Bridge listening host=%s port=%s auth=%s",
            app.state.bridge_host or "",
            app.state.bridge_port or 0,
            auth_mode,
        )
        # Advertise log destination at debug level to avoid noise in production
        if log_dir is not None:
            logger.debug("Log files stored in %s", str(log_dir))
        else:
            logger.debug("Log output directed to console")
        sample_trace = str(uuid.uuid4())
        curl = (
            f"curl -s -H \"Authorization: Bearer {token}\" "
            f"http://{app.state.bridge_host or '127.0.0.1'}:{app.state.bridge_port or 0}/admin/logs/{sample_trace}"
        ) if token else (
            f"curl -s http://{app.state.bridge_host or '127.0.0.1'}:{app.state.bridge_port or 0}/admin/logs/{sample_trace}"
        )
        logger.debug("Sample curl for logs by trace_id: %s", curl)
        _schedule_readiness_check(log_failures=True)

    @app.on_event("shutdown")
    async def _on_app_shutdown() -> None:
        _set_ready(False, "shutdown")

    # Note: _require_auth is defined above and used by routers

    def _normalize_pattern(term: str) -> str:
        like = term.replace("*", "%")
        if "%" not in like:
            like = f"%{like}%"
        return like

    def _iter_aliases(db: MDB, comp_id: int) -> List[str]:
        try:
            return db.get_aliases(comp_id)
        except Exception:
            return []

    def _normalize_aliases(values: Optional[List[str]]) -> List[str]:
        return [a.strip() for a in (values or []) if a and a.strip()]

    def _alias_key(value: str) -> str:
        return value.strip().upper()

    def _normalize_alias_tokens(values: Optional[List[str]]) -> List[str]:
        tokens: List[str] = []
        seen: set[str] = set()
        for raw in values or []:
            cleaned = raw.strip().upper()
            if not cleaned or cleaned in seen:
                continue
            seen.add(cleaned)
            tokens.append(cleaned)
        return tokens

    @dataclass(slots=True)
    class TemplateProbe:
        path: Path
        sha256: str

    def _normalize_pn_list(values: Optional[Sequence[str]]) -> List[str]:
        ordered: List[str] = []
        seen: set[str] = set()
        for raw in values or []:
            candidate = (raw or "").strip()
            if not candidate:
                continue
            key = candidate.lower()
            if key in seen:
                continue
            seen.add(key)
            ordered.append(candidate)
        return ordered

    def _normalize_comp_ids(values: Optional[Sequence[int]]) -> List[int]:
        ordered: List[int] = []
        seen: set[int] = set()
        for raw in values or []:
            try:
                candidate = int(raw)
            except Exception:
                continue
            if candidate <= 0 or candidate in seen:
                continue
            seen.add(candidate)
            ordered.append(candidate)
        return ordered

    def _build_lookup_indexes(db: MDB) -> tuple[dict[str, tuple[int, str]], dict[str, tuple[int, str]], dict[int, str]]:
        canonical: dict[str, tuple[int, str]] = {}
        alias_map: dict[str, tuple[int, str]] = {}
        id_to_name: dict[int, str] = {}
        try:
            rows = db.list_complexes()
        except Exception as exc:  # pragma: no cover - defensive
            raise RuntimeError(f"failed to list complexes: {exc}") from exc
        for comp_id, name, _ in rows:
            cid = int(comp_id)
            canonical_name = str(name or "").strip()
            id_to_name[cid] = canonical_name
            if canonical_name:
                canonical.setdefault(canonical_name.lower(), (cid, canonical_name))
            aliases = _iter_aliases(db, cid)
            for alias in aliases:
                cleaned = alias.strip()
                if not cleaned:
                    continue
                key = cleaned.lower()
                alias_map.setdefault(key, (cid, canonical_name or cleaned))
        return canonical, alias_map, id_to_name

    def _collect_canonical_map(db: MDB) -> Dict[str, int]:
        mapping: Dict[str, int] = {}
        try:
            rows = db.list_complexes()
        except Exception:
            return mapping
        for cid, name, _ in rows:
            key = _alias_key(str(name or ""))
            if key:
                mapping[key] = int(cid)
        return mapping

    def _find_existing_complex(pn: str, aliases: List[str]) -> Dict[str, object] | None:
        tokens = {pn.strip().lower()}
        tokens.update(a.strip().lower() for a in aliases)
        tokens.discard("")
        if not tokens:
            return None
        mdb_path = get_mdb_path()
        with factory(mdb_path) as db:
            cur = db._cur()
            cur.execute(
                f"SELECT {PK_MASTER}, {NAME_COL} FROM {MASTER_T} ORDER BY {NAME_COL} ASC"
            )
            rows = cur.fetchall()
            for comp_id, name in rows:
                cid = int(comp_id)
                canonical = str(name or "").strip()
                canonical_norm = canonical.lower()
                alias_list = [a.strip() for a in _iter_aliases(db, cid)]
                alias_norms = {a.lower() for a in alias_list if a}
                if (
                    canonical_norm in tokens
                    or alias_norms & tokens
                    or (canonical_norm and canonical_norm in alias_norms)
                ):
                    return {
                        "id": cid,
                        "pn": canonical,
                        "aliases": alias_list,
                        "db_path": str(mdb_path),
                    }
        return None

    def _search(term: str, limit: int, analyze: bool, trace_id: str | None) -> List[ComplexSummary]:
        like = _normalize_pattern(term)
        term_casefold = term.casefold()
        mdb_path = get_mdb_path()
        with factory(mdb_path) as db:
            setattr(db, "_bridge_limit", limit)
            cur = db._cur()
            try:
                fk_col, alias_col, _ = db._alias_schema(cur)  # type: ignore[attr-defined]
                query = (
                    f"SELECT TOP {limit} c.{PK_MASTER}, c.{NAME_COL} "
                    f"FROM {MASTER_T} AS c "
                    f"LEFT JOIN {ALIAS_T} AS alias ON alias.[{fk_col}] = c.{PK_MASTER} "
                    f"WHERE c.{NAME_COL} LIKE ? OR alias.[{alias_col}] LIKE ? "
                    f"GROUP BY c.{PK_MASTER}, c.{NAME_COL} "
                    f"ORDER BY c.{NAME_COL} ASC"
                )
                cur.execute(query, like, like)
            except Exception:
                cur.execute(
                    f"SELECT TOP {limit} {PK_MASTER}, {NAME_COL} "
                    f"FROM {MASTER_T} WHERE {NAME_COL} LIKE ? ORDER BY {NAME_COL} ASC",
                    like,
                )
            rows = cur.fetchall()
            summaries: List[ComplexSummary] = []

            if not analyze:
                for comp_id, name in rows:
                    cid = int(comp_id)
                    aliases = _iter_aliases(db, cid)
                    summaries.append(
                        ComplexSummary(
                            id=cid,
                            pn=str(name or ""),
                            aliases=aliases,
                            db_path=str(mdb_path),
                        )
                    )
                return summaries

            normalized_input_result = normalizer.normalize(term)
            normalized_input = normalized_input_result.normalized
            input_rule_ids = list(normalized_input_result.rule_ids)
            has_normalized_input = bool(normalized_input)
            needle = term.replace("*", "").replace("%", "").strip().lower()

            def _format_reason(kind: MatchKind, descriptions: List[str], like_target: str | None = None) -> str:
                base = {
                    MatchKind.EXACT_PN: "Exact PN match",
                    MatchKind.EXACT_ALIAS: "Exact alias match",
                    MatchKind.NORMALIZED_PN: "Normalized input matched PN",
                    MatchKind.NORMALIZED_ALIAS: "Normalized input matched alias",
                    MatchKind.LIKE: "LIKE match",
                }[kind]
                if kind is MatchKind.LIKE and like_target:
                    base = f"LIKE match on {like_target}"
                if descriptions:
                    return f"{base} ({', '.join(descriptions)})"
                return base

            def _unique(values: List[str]) -> List[str]:
                seen: set[str] = set()
                ordered: List[str] = []
                for item in values:
                    if item not in seen:
                        seen.add(item)
                        ordered.append(item)
                return ordered

            scored: List[tuple[int, int, MatchKind, ComplexSummary]] = []
            priority = {
                MatchKind.EXACT_PN: 0,
                MatchKind.EXACT_ALIAS: 1,
                MatchKind.NORMALIZED_PN: 2,
                MatchKind.NORMALIZED_ALIAS: 3,
                MatchKind.LIKE: 4,
            }

            for index, (comp_id, name) in enumerate(rows):
                cid = int(comp_id)
                pn_value = str(name or "")
                aliases = _iter_aliases(db, cid)

                if pn_value.casefold() == term_casefold:
                    match_kind = MatchKind.EXACT_PN
                    reason = _format_reason(match_kind, [])
                    normalized_targets: List[str] = []
                elif any(alias.casefold() == term_casefold for alias in aliases):
                    match_kind = MatchKind.EXACT_ALIAS
                    reason = _format_reason(match_kind, [])
                    normalized_targets = []
                else:
                    if has_normalized_input:
                        pn_result = normalizer.normalize(pn_value)
                        if pn_result.normalized == normalized_input:
                            match_kind = MatchKind.NORMALIZED_PN
                            descriptions = PartNumberNormalizer.merge_descriptions(
                                normalized_input_result,
                                pn_result,
                            )
                            reason = _format_reason(match_kind, descriptions)
                            normalized_targets = _unique([pn_result.normalized])
                        else:
                            alias_results = {
                                alias: normalizer.normalize(alias) for alias in aliases
                            }
                            alias_matches = [
                                result
                                for result in alias_results.values()
                                if result.normalized == normalized_input
                            ]
                            if alias_matches:
                                match_kind = MatchKind.NORMALIZED_ALIAS
                                descriptions = PartNumberNormalizer.merge_descriptions(
                                    normalized_input_result,
                                    *alias_matches,
                                )
                                normalized_targets = _unique(
                                    [res.normalized for res in alias_matches]
                                )
                                reason = _format_reason(match_kind, descriptions)
                            else:
                                match_kind = MatchKind.LIKE
                                like_target = None
                                if needle and needle in pn_value.lower():
                                    like_target = "PN"
                                elif needle and any(needle in alias.lower() for alias in aliases):
                                    like_target = "alias"
                                reason = _format_reason(match_kind, [], like_target)
                                normalized_targets = []
                    else:
                        match_kind = MatchKind.LIKE
                        like_target = None
                        if needle and needle in pn_value.lower():
                            like_target = "PN"
                        elif needle and any(needle in alias.lower() for alias in aliases):
                            like_target = "alias"
                        reason = _format_reason(match_kind, [], like_target)
                        normalized_targets = []

                summary = ComplexSummary(
                    id=cid,
                    pn=pn_value,
                    aliases=aliases,
                    db_path=str(mdb_path),
                    match_kind=match_kind,
                    reason=reason,
                    normalized_input=normalized_input,
                    normalized_targets=normalized_targets,
                    rule_ids=list(input_rule_ids),
                )
                scored.append((priority[match_kind], index, match_kind, summary))

            scored.sort(key=lambda item: (item[0], item[1]))
            ordered = [entry[3] for entry in scored]
            counts = Counter(
                summary.match_kind.value  # type: ignore[union-attr]
                for summary in ordered
                if summary.match_kind is not None
            )
            most_common = counts.most_common(3)
            rules_version = getattr(
                app.state,
                "normalization_rules_version",
                NORMALIZATION_RULES_VERSION,
            )
            top_keys: dict[str, object] = {}
            for idx in range(1, 4):
                if idx <= len(most_common):
                    kind, count = most_common[idx - 1]
                    top_keys[f"match_top_{idx}_kind"] = kind
                    top_keys[f"match_top_{idx}_count"] = count
                else:
                    top_keys[f"match_top_{idx}_kind"] = ""
                    top_keys[f"match_top_{idx}_count"] = 0
            logger.info(
                "Bridge search analyze term=%s normalized=%s counts=%s",
                term,
                normalized_input,
                dict(counts),
                extra={
                    "trace_id": trace_id or "",
                    "event": "search_analyze",
                    "method": "GET",
                    "path": "/complexes/search",
                    "normalized_input": normalized_input,
                    "rules_version": rules_version,
                    **top_keys,
                },
            )
            return ordered

    def _detail(comp_id: int) -> ComplexDetail:
        mdb_path = get_mdb_path()
        with factory(mdb_path) as db:
            device = db.get_complex(comp_id)
            aliases = list(device.aliases or [])
            pin_map: dict[str, dict[str, object]] = {}
            macro_ids: set[int] = set()
            for idx, sub in enumerate(device.subcomponents or []):
                if getattr(sub, "id_function", None) is not None:
                    try:
                        macro_ids.add(int(sub.id_function))
                    except Exception:
                        pass
                entries = {}
                for key, value in (sub.pins or {}).items():
                    if value in (None, ""):
                        continue
                    if isinstance(value, (int, float)):
                        entries[key] = int(value)
                    else:
                        entries[key] = str(value)
                if entries:
                    key = str(sub.id_sub_component) if getattr(sub, "id_sub_component", None) is not None else str(idx)
                    pin_map[key] = entries
            payload = {
                "id": int(device.id_comp_desc or comp_id),
                "pn": str(device.name or ""),
                "aliases": aliases,
                "db_path": str(mdb_path),
                "total_pins": int(device.total_pins or 0),
                "pin_map": pin_map,
                "macro_ids": sorted(macro_ids),
                "updated_at": None,
            }
            hash_basis = {
                "id": payload["id"],
                "pn": payload["pn"],
                "aliases": aliases,
                "pin_map": pin_map,
                "macro_ids": payload["macro_ids"],
            }
            payload["source_hash"] = hashlib.sha256(
                json.dumps(hash_basis, sort_keys=True, default=str).encode("utf-8")
            ).hexdigest()
            return ComplexDetail(**payload)

    async def _handle_create(req: ComplexCreateRequest) -> BridgeCreateResult:
        if wizard_handler is None:
            reason = "wizard unavailable (headless)"
            logger.warning(
                "Bridge create request rejected: %s (pn=%s)",
                reason,
                req.pn,
            )
            return BridgeCreateResult(created=False, reason=reason)
        try:
            result = await asyncio.to_thread(wizard_handler, req.pn, req.aliases)
        except Exception as exc:  # pragma: no cover - defensive logging
            logger.exception("Wizard handler raised while creating pn=%s", req.pn)
            return BridgeCreateResult(
                created=False,
                reason=f"wizard handler failed: {exc}",
            )
        if result is None:  # pragma: no cover - defensive fallback
            logger.error("Wizard handler returned no result for pn=%s", req.pn)
            return BridgeCreateResult(created=False, reason="wizard handler returned no result")
        return result

    def _state_snapshot() -> dict[str, object]:
        base: dict[str, object] = {
            "wizard_open": bool(getattr(app.state, "wizard_open", False)),
            "unsaved_changes": False,
            "mdb_path": str(app.state.mdb_path or ""),
            "focused_comp_id": getattr(app.state, "focused_comp_id", None),
        }
        if state_provider is None:
            return base
        try:
            payload = state_provider() or {}
        except Exception:
            return base
        for key in ("wizard_open", "unsaved_changes"):
            if key in payload:
                base[key] = bool(payload[key])
        if "mdb_path" in payload:
            try:
                base["mdb_path"] = str(payload["mdb_path"] or "")
            except Exception:
                base["mdb_path"] = ""
        new_path_val = payload.get("mdb_path") if isinstance(payload, dict) else None
        if new_path_val is not None:
            new_path = str(new_path_val).strip()
            app.state._observed_mdb_path = new_path
            current = str(app.state.mdb_path or "").strip()
            pending = app.state._pending_mdb_path
            if new_path and new_path != current:
                if pending != new_path:
                    app.state._pending_mdb_path = new_path
                    _set_ready(False, "warming_up")
                    app.state.last_ready_checks = []
                    _schedule_readiness_check(log_failures=True)
            elif pending and new_path == current:
                app.state._pending_mdb_path = None
        if isinstance(payload, dict) and "focused_comp_id" in payload:
            try:
                value = payload["focused_comp_id"]
                base["focused_comp_id"] = None if value in (None, "") else int(value)
            except Exception:
                base["focused_comp_id"] = None
        app.state.focused_comp_id = base["focused_comp_id"]
        app.state.wizard_open = bool(base["wizard_open"])
        return base

    def _is_headless() -> bool:
        ui_present = getattr(app.state, "ui_present", None)
        if ui_present is not None:
            return ui_present is False
        return bool(getattr(app.state, "headless", False))

    def _resolve_trace_id(request: Request) -> str:
        existing = getattr(request.state, "trace_id", None)
        if existing:
            return str(existing)
        incoming = (request.headers.get(TRACE_HEADER) or "").strip()
        trace_id = incoming or _make_trace_id()
        request.state.trace_id = trace_id
        return trace_id

    def _health_payload(trace_id: str) -> tuple[Dict[str, object], int]:
        headless_flag = _is_headless()
        allow_headless_flag = bool(_allow_headless_current())
        ready_raw = bool(getattr(app.state, "ready", False))
        ready_flag = ready_raw and (not headless_flag or allow_headless_flag)
        reason = getattr(app.state, "last_ready_error", "") or "warming_up"
        if headless_flag and not allow_headless_flag:
            ready_flag = False
            reason = "exports_disabled_in_headless_mode"
        elif ready_flag:
            reason = "ok"
        payload: Dict[str, object] = {
            "ready": bool(ready_flag),
            "headless": bool(headless_flag),
            "allow_headless": bool(allow_headless_flag),
            "reason": reason,
            "trace_id": trace_id,
        }
        status_code = status.HTTP_200_OK if ready_flag else status.HTTP_503_SERVICE_UNAVAILABLE
        return payload, status_code

    @app.get("/health")
    async def health(request: Request, _: None = Depends(_require_auth)) -> JSONResponse:
        """Readiness-aware liveness probe."""

        trace_id = _resolve_trace_id(request)
        payload, status_code = _health_payload(trace_id)
        return JSONResponse(status_code=status_code, content=payload)

    @app.get("/admin/health")
    async def admin_health(request: Request, _: None = Depends(_require_auth)) -> JSONResponse:
        trace_id = _resolve_trace_id(request)
        payload, status_code = _health_payload(trace_id)
        return JSONResponse(status_code=status_code, content=payload)

    @app.get("/admin/pn_normalization")
    async def admin_pn_normalization(_: None = Depends(_require_auth)) -> dict[str, object]:
        config = normalizer.config
        return {
            "rules_version": getattr(
                app.state,
                "normalization_rules_version",
                NORMALIZATION_RULES_VERSION,
            ),
            "config": {
                "case": config.case,
                "remove_chars": list(config.remove_chars),
                "ignore_suffixes": list(config.ignore_suffixes),
            },
        }

    def _make_trace_id() -> str:
        return uuid.uuid4().hex

    def _error_response(
        *,
        status_code: int,
        reason: str,
        trace_id: str,
        detail: Optional[str] = None,
        **extra: object,
    ) -> JSONResponse:
        payload: Dict[str, object] = {"reason": reason, "trace_id": trace_id, "status": status_code}
        if detail is not None:
            payload["detail"] = detail
        elif reason:
            payload["detail"] = reason
        payload.update(extra)
        return JSONResponse(status_code=status_code, content=payload)

    def _normalize_out_dir(raw: str) -> tuple[Path, str]:
        cleaned = (raw or "").strip().strip('"')
        if not cleaned:
            raise ValueError("empty_out_dir")
        expanded = os.path.expandvars(cleaned)
        # Allow UNC (\\server\share) and Windows style paths
        normalized = expanded.replace("\\", "/")
        candidate = Path(normalized).expanduser()
        looks_windows = bool(re.match(r"^[a-zA-Z]:/", normalized))
        is_unc = normalized.startswith("//")
        if not (candidate.is_absolute() or looks_windows or is_unc):
            raise ValueError("not_absolute")
        return candidate, str(candidate)

    def _validate_filename(raw: str | None) -> str:
        name = (raw or "").strip() or "bom_complexes.mdb"
        if any(sep in name for sep in ("/", "\\")):
            raise ValueError("path_separator")
        if any(part == ".." for part in Path(name).parts):
            raise ValueError("traversal")
        if not name.lower().endswith(".mdb"):
            raise ValueError("missing_suffix")
        if len(name) > 64:
            raise ValueError("too_long")
        return name

    def _probe_template() -> TemplateProbe | None:
        cached = getattr(app.state, "_template_probe", None)
        if isinstance(cached, TemplateProbe):
            return cached
        package = "complex_editor.assets"
        candidates = ("empty_template.mdb", "MAIN_DB.mdb")
        files_fn = getattr(importlib.resources, "files", None)
        if files_fn is None:  # pragma: no cover - legacy Python fallback
            return None
        try:
            resources_obj = files_fn(package)
        except Exception:
            return None
        for name in candidates:
            try:
                resource = resources_obj.joinpath(name)
            except (FileNotFoundError, AttributeError):
                continue
            try:
                with importlib.resources.as_file(resource) as template_path:
                    if not template_path.exists():
                        continue
                    digest = hashlib.sha256(template_path.read_bytes()).hexdigest()
                    probe = TemplateProbe(path=template_path, sha256=digest)
                    setattr(app.state, "_template_probe", probe)
                    return probe
            except FileNotFoundError:
                continue
        return None

    @app.get("/state")
    async def state(_: None = Depends(_require_auth)) -> dict[str, object]:
        snapshot = _state_snapshot()
        headless_flag = _is_headless()
        allow_headless_flag = bool(_allow_headless_current())
        ready_flag = bool(getattr(app.state, "ready", False))
        return {
            "ready": ready_flag,
            "last_ready_error": str(getattr(app.state, "last_ready_error", "")),
            "checks": list(getattr(app.state, "last_ready_checks", [])),
            "wizard_open": snapshot["wizard_open"],
            "unsaved_changes": snapshot["unsaved_changes"],
            "mdb_path": str(snapshot.get("mdb_path", app.state.mdb_path or "")),
            "version": __version__,
            "host": str(app.state.bridge_host or ""),
            "port": int(app.state.bridge_port or 0),
            "auth_required": bool(token),
            "wizard_available": bool(app.state.wizard_available),
            "alias_ops_supported": True,
            "focused_comp_id": snapshot.get("focused_comp_id"),
            "headless": headless_flag,
            "allow_headless": allow_headless_flag,
            "features": {
                "export_mdb": ready_flag and (not headless_flag or allow_headless_flag),
                "search_match_kind": bool(
                    getattr(app.state, "search_match_kind_supported", False)
                ),
                "normalization_rules_version": getattr(
                    app.state,
                    "normalization_rules_version",
                    NORMALIZATION_RULES_VERSION,
                ),
            },
        }

    @app.post("/selftest")
    async def selftest(_: None = Depends(_require_auth)) -> JSONResponse:
        ok, checks, _ = await _perform_check_and_update(log_failures=True)
        exporter_probe: Dict[str, object] = {
            "template_ok": False,
            "template_path": "",
            "template_hash": "",
            "write_test": False,
            "write_dir": "",
            "subset_roundtrip_ok": False,
            "subset_error_reason": "",
            "subset_error_detail": "",
        }
        template_info = _probe_template()
        if template_info is not None:
            exporter_probe["template_ok"] = True
            exporter_probe["template_path"] = str(template_info.path)
            exporter_probe["template_hash"] = template_info.sha256
        else:
            exporter_probe["template_error"] = "template_not_found"
        try:
            with tempfile.TemporaryDirectory(prefix="ce_export_probe_") as tmp:
                probe_dir = Path(tmp)
                exporter_probe["write_dir"] = str(probe_dir)
                test_file = probe_dir / "probe.txt"
                test_file.write_text("ok", encoding="utf-8")
                exporter_probe["write_test"] = True
        except Exception as exc:  # pragma: no cover - defensive guard
            exporter_probe["write_error"] = str(exc)
        if exporter_probe["write_test"] and template_info is not None:
            try:
                with tempfile.TemporaryDirectory(prefix="ce_export_subset_") as tmp_subset:
                    subset_dir = Path(tmp_subset)
                    subset_path = subset_dir / "subset_test.mdb"
                    subset_ids: list[int] = []
                    try:
                        with factory(mdb_path) as test_db:
                            subset_ids = [int(row[0]) for row in test_db.list_complexes()[:2]]
                    except Exception as exc_subset:
                        exporter_probe["subset_error_reason"] = "list_complexes_failed"
                        exporter_probe["subset_error_detail"] = str(exc_subset)
                    else:
                        if subset_ids:
                            try:
                                with factory(mdb_path) as exporter_db:
                                    exporter_db.save_subset_to_mdb(subset_path, subset_ids)
                                exporter_probe["subset_roundtrip_ok"] = True
                            except SubsetExportError as exc_subset:
                                exporter_probe["subset_error_reason"] = exc_subset.reason
                                exporter_probe["subset_error_detail"] = str(exc_subset)
                            except Exception as exc_subset:
                                exporter_probe["subset_error_reason"] = "unexpected"
                                exporter_probe["subset_error_detail"] = str(exc_subset)
                        else:
                            exporter_probe["subset_roundtrip_ok"] = True
            except Exception as exc_subset:
                if not exporter_probe["subset_error_reason"]:
                    exporter_probe["subset_error_reason"] = "selftest_exception"
                    exporter_probe["subset_error_detail"] = str(exc_subset)
        status_code = status.HTTP_200_OK if ok else status.HTTP_503_SERVICE_UNAVAILABLE
        reason = getattr(app.state, "last_ready_error", "")
        host = app.state.bridge_host or ""
        port = app.state.bridge_port or 0
        if ok:
            logger.info("Bridge selftest passed host=%s port=%s auth=%s", host, port, auth_mode)
        else:
            logger.warning(
                "Bridge selftest failed host=%s port=%s auth=%s reason=%s",
                host,
                port,
                auth_mode,
                reason or "selftest_failed",
            )
        return JSONResponse(
            status_code=status_code,
            content={"ok": ok, "checks": checks, "exporter": exporter_probe},
        )

    @app.get(
        "/complexes/search",
        response_model=List[ComplexSummary],
        response_model_exclude_none=True,
    )
    async def search_complexes(
        request: Request,
        pn: str = Query(..., description="Part number or alias pattern"),
        limit: int = Query(20, ge=1, le=200),
        analyze: bool = Query(False, description="Return match analysis metadata"),
        _: None = Depends(_require_auth),
    ) -> List[ComplexSummary]:
        pn_value = pn.strip()
        if not pn_value:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="pn must not be empty")
        if not any(ch.isalnum() for ch in pn_value):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="pn must not be empty")
        trace_id = _resolve_trace_id(request) if analyze and request is not None else ""
        return _search(pn_value, limit, analyze, trace_id or None)

    @app.post(
        "/exports/mdb",
        response_model=MdbExportResponse,
        responses={
            status.HTTP_503_SERVICE_UNAVAILABLE: {
                "description": "Bridge is running headless and exports are disabled.",
                "content": {
                    "application/json": {
                        "example": {
                            "reason": "bridge_headless",
                            "status": 503,
                            "detail": "exports disabled in headless mode",
                            "trace_id": "example-trace-id",
                            "allow_headless": False,
                        }
                    }
                },
            }
        },
    )
    async def export_mdb_subset(
        payload: MdbExportRequest,
        request: Request,
        _: None = Depends(_require_auth),
    ) -> MdbExportResponse | JSONResponse:
        trace_id = _resolve_trace_id(request)
        caller = _caller_identity(request) or "unknown"
        headless = _is_headless()
        allow_headless = bool(_allow_headless_current())
        if headless and not allow_headless:
            logger.info(
                "Bridge MDB export rejected (headless) trace_id=%s caller=%s allow_headless=%s",
                trace_id,
                caller,
                allow_headless,
            )
            return _error_response(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                reason="bridge_headless",
                trace_id=trace_id,
                detail="exports disabled in headless mode",
                allow_headless=False,
            )

        snapshot = _state_snapshot()
        wizard_open = bool(snapshot.get("wizard_open"))
        unsaved = bool(snapshot.get("unsaved_changes"))
        if wizard_open or unsaved:
            logger.info(
                "Bridge MDB export rejected (busy) trace_id=%s caller=%s wizard_open=%s unsaved=%s",
                trace_id,
                caller,
                wizard_open,
                unsaved,
            )
            return _error_response(
                status_code=status.HTTP_409_CONFLICT,
                reason="busy",
                trace_id=trace_id,
                wizard_open=wizard_open,
                unsaved_changes=unsaved,
            )

        pn_list = _normalize_pn_list(payload.pns)
        comp_ids = _normalize_comp_ids(payload.comp_ids)
        if comp_ids:
            pn_list = []
        logger.info(
            "Bridge MDB export request trace_id=%s caller=%s count_pns=%s count_ids=%s out_dir=%s mdb_name=%s",
            trace_id,
            caller,
            len(pn_list),
            len(comp_ids),
            str(payload.out_dir),
            str(payload.mdb_name or ""),
        )
        if not pn_list and not comp_ids:
            logger.info(
                "Bridge MDB export rejected (empty selection) trace_id=%s caller=%s",
                trace_id,
                caller,
            )
            return _error_response(
                status_code=status.HTTP_400_BAD_REQUEST,
                reason="empty_selection",
                trace_id=trace_id,
                detail="pns_or_comp_ids_required",
            )

        try:
            out_dir, normalized_out_dir = _normalize_out_dir(payload.out_dir)
        except ValueError:
            logger.info(
                "Bridge MDB export invalid out_dir trace_id=%s caller=%s out_dir=%s",
                trace_id,
                caller,
                payload.out_dir,
            )
            return _error_response(
                status_code=status.HTTP_409_CONFLICT,
                reason="outdir_unwritable",
                trace_id=trace_id,
                out_dir=str(payload.out_dir or ""),
                detail="invalid_out_dir",
            )

        try:
            mdb_name = _validate_filename(payload.mdb_name)
        except ValueError:
            logger.info(
                "Bridge MDB export invalid filename trace_id=%s caller=%s name=%s",
                trace_id,
                caller,
                payload.mdb_name,
            )
            return _error_response(
                status_code=status.HTTP_400_BAD_REQUEST,
                reason="bad_filename",
                trace_id=trace_id,
            )
        export_path = out_dir / mdb_name

        mdb_path = get_mdb_path()
        resolved_map: dict[int, ResolvedPart] = {}
        missing: List[str] = []
        missing_comp_ids: List[int] = []
        unlinked: List[str] = []
        export_ids: set[int] = set()

        def _resolved_payload() -> List[dict[str, object]]:
            return [item.model_dump() for item in sorted(resolved_map.values(), key=lambda r: r.comp_id)]

        try:
            with factory(mdb_path) as db:
                canonical_idx, alias_idx, id_to_name = _build_lookup_indexes(db)
                for pn_value in pn_list:
                    key = pn_value.lower()
                    entry = canonical_idx.get(key) or alias_idx.get(key)
                    if entry is None:
                        missing.append(pn_value)
                        continue
                    comp_id, resolved_name = entry
                    export_ids.add(comp_id)
                    if comp_id not in resolved_map:
                        resolved_map[comp_id] = ResolvedPart(pn=resolved_name, comp_id=comp_id)

                for cid in comp_ids:
                    if cid in id_to_name:
                        export_ids.add(cid)
                        if cid not in resolved_map:
                            resolved_name = id_to_name.get(cid, "") or str(cid)
                            resolved_map[cid] = ResolvedPart(pn=resolved_name, comp_id=cid)
                    else:
                        missing_comp_ids.append(cid)
                        missing.append(str(cid))

                if payload.require_linked and (missing or unlinked):
                    logger.info(
                        "Bridge MDB export rejected (unlinked) trace_id=%s caller=%s missing=%s unlinked=%s export_path=%s",
                        trace_id,
                        caller,
                        missing,
                        unlinked,
                        str(export_path),
                    )
                    return _error_response(
                        status_code=status.HTTP_409_CONFLICT,
                        reason="unlinked_or_missing",
                        trace_id=trace_id,
                        missing=missing,
                        unlinked=unlinked,
                        resolved=_resolved_payload(),
                    )

                if missing and not export_ids:
                    if comp_ids:
                        logger.info(
                            "Bridge MDB export rejected (comp_ids not found) trace_id=%s caller=%s comp_ids=%s",
                            trace_id,
                            caller,
                            comp_ids,
                        )
                        return _error_response(
                            status_code=status.HTTP_404_NOT_FOUND,
                            reason="comp_ids_not_found",
                            trace_id=trace_id,
                            detail="No valid comp_ids to export.",
                            missing=[str(cid) for cid in comp_ids],
                        )
                    logger.info(
                        "Bridge MDB export rejected (no matches) trace_id=%s caller=%s missing=%s",
                        trace_id,
                        caller,
                        missing,
                    )
                    return _error_response(
                        status_code=status.HTTP_409_CONFLICT,
                        reason="no_matches",
                        trace_id=trace_id,
                        missing=missing,
                    )

                if not export_ids:
                    return _error_response(
                        status_code=status.HTTP_409_CONFLICT,
                        reason="empty_selection",
                        trace_id=trace_id,
                    )

                try:
                    template_path = _resolve_template_path(getattr(payload, "template_path", None))
                except TemplateResolutionError as exc:
                    return _error_response(
                        status_code=status.HTTP_409_CONFLICT,
                        reason="template_missing_or_incompatible",
                        trace_id=trace_id,
                        detail="Template file is missing or empty.",
                        template_path=exc.attempted,
                    )
                logger.debug("Resolved template_path=%s", str(template_path))

                try:
                    out_dir.mkdir(parents=True, exist_ok=True)
                except OSError as exc:
                    logger.exception(
                        "Bridge MDB export failed preparing directory trace_id=%s path=%s", trace_id, out_dir
                    )
                    return _error_response(
                        status_code=status.HTTP_409_CONFLICT,
                        reason="outdir_unwritable",
                        trace_id=trace_id,
                        out_dir=normalized_out_dir,
                        errno=getattr(exc, "errno", None),
                        detail=str(exc),
                    )

                export_list = sorted(export_ids)
                try:
                    saver = getattr(db, "save_subset_to_mdb", None)
                    used_mdb_saver = False
                    fallback_required = False
                    if saver and callable(saver):
                        try:
                            saver(export_path, export_list, template_path=template_path)
                            used_mdb_saver = True
                        except NotImplementedError:
                            fallback_required = True
                    else:
                        fallback_required = True

                    if fallback_required or not used_mdb_saver:
                        if not (headless and allow_headless):
                            logger.info(
                                "Bridge MDB export rejected (headless) trace_id=%s caller=%s export_path=%s allow_headless=%s",
                                trace_id,
                                caller,
                                str(export_path),
                                allow_headless,
                            )
                            return _error_response(
                                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                                reason="bridge_headless",
                                trace_id=trace_id,
                                detail="exports disabled in headless mode",
                                allow_headless=allow_headless,
                            )
                        from complex_editor.db.pn_exporter import ExportOptions, export_pn_to_mdb  # type: ignore

                        logger.debug(
                            "headless export: fallback_to_export_pn_to_mdb template=%s",
                            str(template_path),
                        )
                        opts = ExportOptions()
                        export_pn_to_mdb(
                            source_db_path=mdb_path,
                            template_path=template_path,
                            target_path=export_path,
                            pn_list=pn_list,
                            comp_ids=export_list,
                            options=opts,
                            progress_cb=None,
                            cancel_cb=None,
                        )
                except FileNotFoundError as exc:
                    logger.exception(
                        "Bridge MDB export template missing trace_id=%s export_path=%s", trace_id, export_path
                    )
                    payload = {
                        "template_path": str(getattr(exc, "filename", "")) or str(template_path),
                        "detail": str(exc),
                    }
                    return _error_response(
                        status_code=status.HTTP_409_CONFLICT,
                        reason="template_missing_or_incompatible",
                        trace_id=trace_id,
                        **payload,
                    )
                except SubsetExportError as exc:
                    payload = dict(exc.payload)
                    payload.setdefault("detail", str(exc))
                    logger.info(
                        "Bridge MDB export subset error trace_id=%s reason=%s payload=%s",
                        trace_id,
                        exc.reason,
                        payload,
                    )
                    return _error_response(
                        status_code=exc.status_code,
                        reason=exc.reason,
                        trace_id=trace_id,
                        **payload,
                    )
                except LookupError as exc:
                    logger.exception(
                        "Bridge MDB export data invalid trace_id=%s export_path=%s", trace_id, export_path
                    )
                    return _error_response(
                        status_code=status.HTTP_409_CONFLICT,
                        reason="data_invalid",
                        trace_id=trace_id,
                        offending_comp_ids=export_list,
                        detail=str(exc),
                    )
                except ValueError as exc:
                    logger.exception(
                        "Bridge MDB export validation failed trace_id=%s export_path=%s", trace_id, export_path
                    )
                    return _error_response(
                        status_code=status.HTTP_409_CONFLICT,
                        reason="data_invalid",
                        trace_id=trace_id,
                        offending_comp_ids=export_list,
                        detail=str(exc),
                    )
                except _PYODBC_ERROR as exc:  # pragma: no cover - depends on pyodbc
                    logger.exception(
                        "Bridge MDB export database engine error trace_id=%s export_path=%s", trace_id, export_path
                    )
                    return _error_response(
                        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                        reason="db_engine_error",
                        trace_id=trace_id,
                        error_class=exc.__class__.__name__,
                        message=str(exc),
                    )
                except OSError as exc:
                    logger.exception(
                        "Bridge MDB export filesystem error trace_id=%s export_path=%s", trace_id, export_path
                    )
                    return _error_response(
                        status_code=status.HTTP_409_CONFLICT,
                        reason="filesystem_error",
                        trace_id=trace_id,
                        errno=getattr(exc, "errno", None),
                        path=str(getattr(exc, "filename", export_path)),
                        detail=str(exc),
                    )
                except Exception as exc:  # pragma: no cover - defensive
                    logger.exception(
                        "Bridge MDB export unexpected failure trace_id=%s export_path=%s", trace_id, export_path
                    )
                    return _error_response(
                        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                        reason="db_engine_error",
                        trace_id=trace_id,
                        detail=str(exc),
                    )

        except HTTPException as exc:  # pragma: no cover - defensive
            logger.exception("Bridge MDB export unexpected HTTPException trace_id=%s", trace_id)
            return _error_response(
                status_code=exc.status_code,
                reason="db_engine_error",
                trace_id=trace_id,
                detail=str(exc.detail),
            )
        except Exception as exc:  # pragma: no cover - defensive
            logger.exception("Bridge MDB export unexpected error trace_id=%s", trace_id)
            return _error_response(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                reason="db_engine_error",
                trace_id=trace_id,
                detail=str(exc),
            )

        resolved_list = sorted(resolved_map.values(), key=lambda r: r.comp_id)
        if missing_comp_ids and export_list:
            logger.warning("export partial: missing_comp_ids=%s", missing_comp_ids)
        logger.info(
            "Bridge MDB export completed trace_id=%s caller=%s exported=%s missing=%s export_path=%s",
            trace_id,
            caller,
            export_list,
            missing,
            str(export_path),
        )

        return MdbExportResponse(
            ok=True,
            export_path=str(export_path),
            exported_comp_ids=export_list,
            resolved=resolved_list,
            unlinked=unlinked,
            missing=missing,
        )

    @app.post("/admin/shutdown")
    async def shutdown(
        request: Request,
        force: int = Query(0, description="Force shutdown even with unsaved changes"),
        _: None = Depends(_require_auth),
    ) -> dict[str, bool]:
        snapshot = _state_snapshot()
        if int(force) != 1 and snapshot.get("unsaved_changes"):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="unsaved_changes",
            )
        trigger = getattr(request.app.state, "trigger_shutdown", None)
        if not callable(trigger):
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Shutdown handler unavailable",
            )
        trigger()
        return {"ok": True}

    @app.get("/complexes/{comp_id}", response_model=ComplexDetail)
    async def get_complex(comp_id: int, _: None = Depends(_require_auth)) -> ComplexDetail:
        try:
            return _detail(comp_id)
        except KeyError as exc:  # pragma: no cover - defensive
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    @app.post("/complexes/{comp_id}/open")
    async def open_complex(
        comp_id: int,
        payload: ComplexOpenRequest | None = None,
        _: None = Depends(_require_auth),
    ) -> JSONResponse:
        if focus_handler is None:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="headless",
            )

        request_model = payload or ComplexOpenRequest()
        raw_mode = request_model.mode or "view"
        mode = raw_mode.strip().lower()
        if mode not in {"view", "edit"}:
            logger.info(
                "Bridge open request rejected (invalid mode) comp_id=%s mode=%s",
                comp_id,
                raw_mode,
            )
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="invalid_mode",
            )

        logger.info("Bridge open request received comp_id=%s mode=%s", comp_id, mode)

        snapshot = _state_snapshot()
        if mode != "edit" and (snapshot.get("wizard_open") or snapshot.get("unsaved_changes")):
            logger.info(
                "Bridge open request rejected (busy) comp_id=%s mode=%s wizard_open=%s unsaved=%s",
                comp_id,
                mode,
                snapshot.get("wizard_open"),
                snapshot.get("unsaved_changes"),
            )
            return JSONResponse(
                status_code=status.HTTP_409_CONFLICT,
                content={"reason": "busy"},
            )

        mdb_path = get_mdb_path()
        pn = ""
        with factory(mdb_path) as db:
            try:
                device = db.get_complex(comp_id)
                pn = str(getattr(device, "name", "") or "")
            except KeyError as exc:
                logger.info("Bridge open request missing comp_id=%s mode=%s", comp_id, mode)
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
            except Exception as exc:  # pragma: no cover - defensive
                logger.exception("Bridge open lookup failed comp_id=%s mode=%s", comp_id, mode)
                raise HTTPException(
                    status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail="lookup_failed",
                ) from exc

        try:
            result = focus_handler(comp_id, mode)
        except FocusBusyError:
            logger.info("Bridge open handler reported busy comp_id=%s mode=%s", comp_id, mode)
            return JSONResponse(
                status_code=status.HTTP_409_CONFLICT,
                content={"reason": "busy"},
            )
        except KeyError as exc:
            logger.info("Bridge open handler reported missing comp_id=%s mode=%s", comp_id, mode)
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
        except Exception as exc:  # pragma: no cover - defensive
            logger.exception("Bridge open handler failed comp_id=%s mode=%s", comp_id, mode)
            raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, detail="focus_failed") from exc

        focus_id = comp_id
        if isinstance(result, dict):
            pn = str(result.get("pn") or pn)
            if "focused_comp_id" in result:
                try:
                    candidate = result["focused_comp_id"]
                    if candidate not in (None, ""):
                        focus_id = int(candidate)
                except Exception:
                    focus_id = comp_id
            if "wizard_open" in result:
                app.state.wizard_open = bool(result["wizard_open"])
        app.state.focused_comp_id = focus_id
        # Refresh cached state after the UI updates so /state reflects the change
        updated_snapshot = _state_snapshot()
        logger.info(
            "Bridge open request completed comp_id=%s mode=%s focus_id=%s wizard_open=%s",
            comp_id,
            mode,
            updated_snapshot.get("focused_comp_id"),
            updated_snapshot.get("wizard_open"),
        )
        return JSONResponse(status_code=status.HTTP_200_OK, content={"ok": True})

    @app.post(
        "/complexes/{comp_id}/aliases",
        response_model=AliasUpdateResponse,
    )
    async def update_aliases(
        comp_id: int,
        payload: AliasUpdateRequest,
        request: Request,
        _: None = Depends(_require_auth),
    ) -> AliasUpdateResponse:
        alias_request = payload.model_copy(deep=True)
        add_tokens = _normalize_alias_tokens(alias_request.add)
        remove_tokens = _normalize_alias_tokens(alias_request.remove)
        mdb_path = get_mdb_path()
        added: List[str] = []
        removed: List[str] = []
        skipped: List[str] = []
        trace_id = _resolve_trace_id(request)

        with factory(mdb_path) as db:
            try:
                device = db.get_complex(comp_id)
            except KeyError as exc:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

            canonical = str(device.name or "")
            canonical_key = _alias_key(canonical)
            canonical_norm = normalizer.normalize(canonical)
            canonical_norm_value = canonical_norm.normalized
            canonical_rule_ids = list(canonical_norm.rule_ids)
            canonical_map = _collect_canonical_map(db)
            if canonical_key:
                canonical_map.setdefault(canonical_key, comp_id)

            conflicts = []
            for alias in add_tokens:
                owner = canonical_map.get(alias)
                if owner is not None and owner != comp_id:
                    conflicts.append({"alias": alias, "existing_id": owner})
            if conflicts:
                logger.warning(
                    "Bridge alias update conflict comp_id=%s conflicts=%s",
                    comp_id,
                    len(conflicts),
                )
                return JSONResponse(
                    status_code=status.HTTP_409_CONFLICT,
                    content={"reason": "alias_conflict", "conflicts": conflicts},
                )

            existing_aliases = db.get_aliases(comp_id)
            alias_map = {_alias_key(a): a for a in existing_aliases}
            current_aliases = dict(alias_map)

            for alias in remove_tokens:
                if alias in current_aliases:
                    removed_value = current_aliases.pop(alias)
                    removed.append(_alias_key(removed_value))
                else:
                    skipped.append(alias)

            for alias in add_tokens:
                if alias == canonical_key:
                    skipped.append(alias)
                    continue
                if alias in current_aliases:
                    skipped.append(alias)
                    continue
                current_aliases[alias] = alias
                added.append(alias)

            changed = bool(added or removed)
            if changed:
                db.set_aliases(comp_id, list(current_aliases.values()))

        updated_summary = {
            "added": added,
            "removed": removed,
            "skipped": skipped,
        }
        detail = _detail(comp_id)
        normalized_alias_rule_ids: dict[str, dict[str, List[str]]] = {"added": {}, "removed": {}}

        def _record_alias(bucket: str, alias_value: str) -> None:
            if canonical_rule_ids and alias_value == canonical_norm_value:
                normalized_alias_rule_ids[bucket][alias_value] = list(canonical_rule_ids)

        for alias in added:
            _record_alias("added", alias)
        for alias in removed:
            _record_alias("removed", alias)

        normalized_alias_rule_ids = {
            bucket: values for bucket, values in normalized_alias_rule_ids.items() if values
        }
        log_extra = {
            "trace_id": trace_id or "",
            "event": "alias_update",
            "method": "POST",
            "path": f"/complexes/{comp_id}/aliases",
        }
        if normalized_alias_rule_ids:
            log_extra["rule_ids"] = normalized_alias_rule_ids
        logger.info(
            "Bridge alias update completed comp_id=%s added=%s removed=%s skipped=%s",
            comp_id,
            len(added),
            len(removed),
            len(skipped),
            extra=log_extra,
        )
        return AliasUpdateResponse(
            id=detail.id,
            pn=detail.pn,
            aliases=detail.aliases,
            db_path=str(mdb_path),
            updated=updated_summary,
            source_hash=detail.source_hash,
        )

    @app.post(
        "/complexes",
        response_model=ComplexCreateResponse,
        status_code=status.HTTP_201_CREATED,
    )
    async def create_complex(
        payload: ComplexCreateRequest,
        _: None = Depends(_require_auth),
    ) -> ComplexCreateResponse:
        request = payload.model_copy(deep=True)
        request.pn = request.pn.strip()
        if not request.pn:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="pn must not be empty")
        request.aliases = _normalize_aliases(request.aliases)

        existing = _find_existing_complex(request.pn, request.aliases)
        if existing is not None:
            logger.info(
                "Bridge create request found existing complex pn=%s id=%s", request.pn, existing["id"]
            )
            model = ComplexCreateResponse(**existing)
            return JSONResponse(status_code=status.HTTP_200_OK, content=model.model_dump())

        result = await _handle_create(request)
        if result.created:
            db_path = result.db_path or str(get_mdb_path())
            logger.info(
                "Bridge wizard created new complex pn=%s id=%s", request.pn, result.comp_id
            )
            return ComplexCreateResponse(
                id=int(result.comp_id or 0),
                pn=request.pn,
                aliases=request.aliases,
                db_path=db_path,
            )
        reason = (result.reason or "cancelled").strip() or "cancelled"
        lowered = reason.lower()
        if lowered in {"cancelled", "cancelled by user"}:
            message = "cancelled by user"
            logger.info("Bridge wizard cancelled by user pn=%s", request.pn)
            return JSONResponse(
                status_code=status.HTTP_409_CONFLICT,
                content={"reason": message},
            )
        if "busy" in lowered:
            logger.warning("Bridge create request rejected: %s pn=%s", reason, request.pn)
            return JSONResponse(
                status_code=status.HTTP_409_CONFLICT,
                content={"reason": reason},
            )
        if "unavailable" in lowered:
            logger.warning("Bridge create request failed: %s pn=%s", reason, request.pn)
            raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=reason)
        logger.error("Bridge wizard failed pn=%s reason=%s", request.pn, reason)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=reason)

    return app


__all__ = ["create_app", "FocusBusyError"]
