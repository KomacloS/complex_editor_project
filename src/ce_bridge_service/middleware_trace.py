from __future__ import annotations

import logging
import time
import uuid
from typing import Callable, Awaitable

from fastapi import Request, Response


TRACE_HEADER = "X-Trace-Id"


class TraceIdMiddleware:
    def __init__(self, app):
        self.app = app
        self.logger = logging.getLogger(__name__)

    async def __call__(self, scope, receive, send):  # type: ignore[override]
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return

        async def send_wrapper(message):
            # Inject response header when sending the response start
            if message.get("type") == "http.response.start":
                headers = message.setdefault("headers", [])
                # scope["state"] is set via request.state in ASGI wrappers; to be safe, we propagate from local var
                value = trace_id.encode("utf-8")
                headers.append((b"x-trace-id", value))
            await send(message)

        # Build Request to access headers easily
        request = Request(scope, receive=receive)
        incoming = request.headers.get(TRACE_HEADER)
        trace_id = incoming.strip() if incoming else str(uuid.uuid4())
        # Expose on request.state for route handlers and exception handlers
        request.state.trace_id = trace_id

        # Measure per-request duration and log access line at end
        start = time.perf_counter()
        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            duration_ms = int((time.perf_counter() - start) * 1000)
            path = scope.get("path", "")
            method = scope.get("method", "")
            status = getattr(request, "_cached_response_status", None)  # may be set by exception handler
            # Log an access-style line using the root logger
            self.logger.info(
                "access", extra={
                    "event": "access",
                    "method": method,
                    "path": path,
                    "status": status,
                    "duration_ms": duration_ms,
                    "trace_id": trace_id,
                }
            )

