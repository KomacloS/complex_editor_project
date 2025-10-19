from __future__ import annotations

import logging
import traceback
from typing import Any, Dict

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse


logger = logging.getLogger(__name__)


def install_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(Exception)
    async def _unhandled_exception(request: Request, exc: Exception):  # type: ignore[override]
        trace_id = getattr(getattr(request, "state", object()), "trace_id", "")
        stack = traceback.format_exc()
        path = getattr(request, "url", None)
        method = getattr(request, "method", "")
        status_code = 500
        # Record on request object for middleware access log
        setattr(request, "_cached_response_status", status_code)
        logger.error(
            "Unhandled exception",
            extra={
                "trace_id": trace_id,
                "path": str(getattr(path, "path", path) or ""),
                "method": method,
                "status": status_code,
                "event": "unhandled_exception",
                "exception": stack,
            },
        )
        payload: Dict[str, Any] = {
            "reason": "internal_error",
            "detail": str(exc) or "internal_error",
            "trace_id": trace_id,
        }
        return JSONResponse(status_code=status_code, content=payload)

    @app.exception_handler(HTTPException)
    async def _http_exception(request: Request, exc: HTTPException):  # type: ignore[override]
        trace_id = getattr(getattr(request, "state", object()), "trace_id", "")
        path = getattr(request, "url", None)
        method = getattr(request, "method", "")
        status_code = int(getattr(exc, "status_code", 500))
        setattr(request, "_cached_response_status", status_code)
        # Avoid double-logging 401/403 noise; log others at error for visibility
        level_logger = logger.info if status_code in (401, 403, 404) else logger.error
        level_logger(
            "HTTPException",
            extra={
                "trace_id": trace_id,
                "path": str(getattr(path, "path", path) or ""),
                "method": method,
                "status": status_code,
                "event": "http_exception",
            },
        )
        detail = exc.detail if isinstance(exc.detail, str) else str(exc.detail)
        content: Dict[str, Any] = {"reason": detail or "error", "detail": detail or "error", "trace_id": trace_id}
        return JSONResponse(status_code=status_code, content=content)

