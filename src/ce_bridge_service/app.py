from __future__ import annotations

import asyncio
import importlib.resources
import hashlib
import json
import logging
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
    HealthResponse,
    MdbExportRequest,
    MdbExportResponse,
    ResolvedPart,
)
from .types import BridgeCreateResult

try:  # pragma: no cover - optional dependency during tests
    import pyodbc  # type: ignore

    _PYODBC_ERROR = (pyodbc.Error,)  # type: ignore[attr-defined]
except Exception:  # pragma: no cover - pyodbc not available in unit tests
    pyodbc = None  # type: ignore[assignment]
    _PYODBC_ERROR = tuple()


logger = logging.getLogger(__name__)


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
) -> FastAPI:
    """Return a configured FastAPI application for the bridge."""

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
    app.state.focus_handler_available = bool(focus_handler)
    factory = mdb_factory or MDB

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
        _schedule_readiness_check(log_failures=True)

    @app.on_event("shutdown")
    async def _on_app_shutdown() -> None:
        _set_ready(False, "shutdown")

    async def _require_auth(request: Request) -> None:
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

    def _search(term: str, limit: int) -> List[ComplexSummary]:
        like = _normalize_pattern(term)
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

    @app.get("/health", response_model=HealthResponse)
    async def health(_: None = Depends(_require_auth)) -> HealthResponse | JSONResponse:  # noqa: D401
        """Readiness-aware liveness probe."""

        if not getattr(app.state, "ready", False):
            reason = getattr(app.state, "last_ready_error", "") or "warming_up"
            return JSONResponse(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                content={"ok": False, "reason": reason},
            )
        resolved_path = app.state.mdb_path or ""
        if not resolved_path:
            try:
                resolved_path = str(get_mdb_path())
            except Exception:
                resolved_path = ""
        return HealthResponse(
            ok=True,
            version=__version__,
            db_path=resolved_path,
            host=str(app.state.bridge_host or ""),
            port=int(app.state.bridge_port or 0),
            auth_required=bool(token),
        )

    def _make_trace_id() -> str:
        return str(uuid.uuid4())

    def _error_response(
        *,
        status_code: int,
        reason: str,
        trace_id: str,
        detail: Optional[str] = None,
        **extra: object,
    ) -> JSONResponse:
        payload: Dict[str, object] = {"reason": reason, "trace_id": trace_id}
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
        return {
            "ready": bool(getattr(app.state, "ready", False)),
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
            "features": {"export_mdb": bool(getattr(app.state, "ready", False))},
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

    @app.get("/complexes/search", response_model=List[ComplexSummary])
    async def search_complexes(
        pn: str = Query(..., description="Part number or alias pattern"),
        limit: int = Query(20, ge=1, le=200),
        _: None = Depends(_require_auth),
    ) -> List[ComplexSummary]:
        if not pn.strip():
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="pn must not be empty")
        return _search(pn.strip(), limit)

    @app.post("/exports/mdb", response_model=MdbExportResponse)
    async def export_mdb_subset(
        payload: MdbExportRequest,
        request: Request,
        _: None = Depends(_require_auth),
    ) -> MdbExportResponse | JSONResponse:
        trace_id = _make_trace_id()
        caller = _caller_identity(request) or "unknown"
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
        unlinked: List[str] = []
        export_ids: set[int] = set()

        template_info = _probe_template()

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

                invalid_comp_ids = [cid for cid in comp_ids if cid not in id_to_name]
                if invalid_comp_ids:
                    logger.info(
                        "Bridge MDB export invalid comp_ids trace_id=%s caller=%s invalid=%s",
                        trace_id,
                        caller,
                        invalid_comp_ids,
                    )
                    return _error_response(
                        status_code=status.HTTP_409_CONFLICT,
                        reason="invalid_comp_ids",
                        trace_id=trace_id,
                        not_found_ids=invalid_comp_ids,
                    )

                for cid in comp_ids:
                    export_ids.add(cid)
                    if cid not in resolved_map:
                        resolved_name = id_to_name.get(cid, "") or str(cid)
                        resolved_map[cid] = ResolvedPart(pn=resolved_name, comp_id=cid)

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

                saver = getattr(db, "save_subset_to_mdb", None)
                if saver is None or not callable(saver):
                    logger.info(
                        "Bridge MDB export rejected (headless) trace_id=%s caller=%s export_path=%s",
                        trace_id,
                        caller,
                        str(export_path),
                    )
                    return _error_response(
                        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                        reason="headless",
                        trace_id=trace_id,
                        detail="headless",
                    )

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
                    saver(export_path, export_list)
                except NotImplementedError as exc:
                    logger.info(
                        "Bridge MDB export rejected (headless) trace_id=%s caller=%s export_path=%s",
                        trace_id,
                        caller,
                        str(export_path),
                    )
                    return _error_response(
                        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                        reason="headless",
                        trace_id=trace_id,
                        detail=str(exc) or "headless",
                    )
                except FileNotFoundError as exc:
                    logger.exception(
                        "Bridge MDB export template missing trace_id=%s export_path=%s", trace_id, export_path
                    )
                    payload = {
                        "template_path": str(getattr(exc, "filename", "")) or (str(template_info.path) if template_info else ""),
                        "detail": str(exc),
                    }
                    if template_info is not None:
                        payload["template_hash"] = template_info.sha256
                    return _error_response(
                        status_code=status.HTTP_409_CONFLICT,
                        reason="template_missing_or_incompatible",
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
        _: None = Depends(_require_auth),
    ) -> AliasUpdateResponse:
        request = payload.model_copy(deep=True)
        add_tokens = _normalize_alias_tokens(request.add)
        remove_tokens = _normalize_alias_tokens(request.remove)
        mdb_path = get_mdb_path()
        added: List[str] = []
        removed: List[str] = []
        skipped: List[str] = []

        with factory(mdb_path) as db:
            try:
                device = db.get_complex(comp_id)
            except KeyError as exc:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

            canonical = str(device.name or "")
            canonical_key = _alias_key(canonical)
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
        logger.info(
            "Bridge alias update completed comp_id=%s added=%s removed=%s skipped=%s",
            comp_id,
            len(added),
            len(removed),
            len(skipped),
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
