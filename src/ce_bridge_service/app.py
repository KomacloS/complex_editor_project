from __future__ import annotations

import hashlib
import json
import secrets
from pathlib import Path
from typing import Callable, Dict, List, Optional

from fastapi import Depends, FastAPI, HTTPException, Query, Request, status

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
    ComplexCreateRequest,
    ComplexCreateResponse,
    ComplexDetail,
    ComplexSummary,
    HealthResponse,
)
from .types import BridgeCreateResult


def create_app(
    *,
    get_mdb_path: Callable[[], Path],
    auth_token: str | None = None,
    wizard_handler: Optional[Callable[[str, Optional[List[str]]], BridgeCreateResult]] = None,
    mdb_factory: Optional[Callable[[Path], MDB]] = None,
    bridge_host: str | None = None,
    bridge_port: int | None = None,
    state_provider: Callable[[], Dict[str, object]] | None = None,
) -> FastAPI:
    """Return a configured FastAPI application for the bridge."""

    token = (auth_token or "").strip()
    app = FastAPI(title="Complex Editor Bridge", version=__version__)
    app.state.bridge_host = bridge_host or ""
    app.state.bridge_port = int(bridge_port) if bridge_port is not None else 0
    app.state.trigger_shutdown = lambda: None
    factory = mdb_factory or MDB

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
                        name=str(name or ""),
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
                "id": int(device.id_comp_desc),
                "name": device.name,
                "aliases": aliases,
                "db_path": str(mdb_path),
                "total_pins": int(device.total_pins or 0),
                "pin_map": pin_map,
                "macro_ids": sorted(macro_ids),
                "updated_at": None,
            }
            hash_basis = {
                "id": payload["id"],
                "name": payload["name"],
                "aliases": aliases,
                "pin_map": pin_map,
                "macro_ids": payload["macro_ids"],
            }
            payload["source_hash"] = hashlib.sha256(
                json.dumps(hash_basis, sort_keys=True, default=str).encode("utf-8")
            ).hexdigest()
            return ComplexDetail(**payload)

    def _handle_create(req: ComplexCreateRequest) -> BridgeCreateResult:
        if wizard_handler is None:
            return BridgeCreateResult(created=False, reason="wizard handler unavailable")
        return wizard_handler(req.pn, req.aliases)

    def _state_snapshot() -> dict[str, bool]:
        base = {"wizard_open": False, "unsaved_changes": False}
        if state_provider is None:
            return base
        try:
            payload = state_provider() or {}
        except Exception:
            return base
        for key in ("wizard_open", "unsaved_changes"):
            if key in payload:
                base[key] = bool(payload[key])
        return base

    @app.get("/health", response_model=HealthResponse)
    async def health(_: None = Depends(_require_auth)) -> HealthResponse:  # noqa: D401
        """Liveness probe."""

        mdb_path = str(get_mdb_path())
        return HealthResponse(
            ok=True,
            version=__version__,
            db_path=mdb_path,
            host=str(app.state.bridge_host or ""),
            port=int(app.state.bridge_port or 0),
            auth_required=bool(token),
        )

    @app.get("/state")
    async def state(_: None = Depends(_require_auth)) -> dict[str, object]:
        snapshot = _state_snapshot()
        return {
            "wizard_open": snapshot["wizard_open"],
            "unsaved_changes": snapshot["unsaved_changes"],
            "version": __version__,
            "db_path": str(get_mdb_path()),
            "host": str(app.state.bridge_host or ""),
            "port": int(app.state.bridge_port or 0),
            "auth_required": bool(token),
        }

    @app.get("/complexes/search", response_model=List[ComplexSummary])
    async def search_complexes(
        pn: str = Query(..., description="Part number or alias pattern"),
        limit: int = Query(20, ge=1, le=200),
        _: None = Depends(_require_auth),
    ) -> List[ComplexSummary]:
        if not pn.strip():
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="pn must not be empty")
        return _search(pn.strip(), limit)

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
        request.aliases = [a.strip() for a in (request.aliases or []) if a and a.strip()]
        result = _handle_create(request)
        if result.created:
            db_path = result.db_path or str(get_mdb_path())
            return ComplexCreateResponse(id=int(result.comp_id or 0), db_path=db_path)
        reason = result.reason or "cancelled"
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=reason)

    return app


__all__ = ["create_app"]
