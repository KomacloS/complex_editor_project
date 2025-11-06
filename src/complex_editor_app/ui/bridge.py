"""Helpers for hosting the bridge service alongside the Tk UI."""
from __future__ import annotations

import logging
import socket
import threading
from dataclasses import replace
from pathlib import Path
from typing import Callable, Dict, Optional

import uvicorn

from ce_bridge_service import create_app
from ce_bridge_service.types import BridgeCreateResult
from complex_editor.config.loader import BridgeConfig

LOG = logging.getLogger(__name__)


class TkInvoker:
    """Execute callables on the Tk main thread and wait for results."""

    def __init__(self, root) -> None:  # type: ignore[no-untyped-def]
        self._root = root
        self._main_thread = threading.get_ident()

    def invoke(self, func: Callable, *args, **kwargs):  # type: ignore[no-untyped-def]
        """Run ``func`` on the Tk thread, blocking the caller until done."""

        if threading.get_ident() == self._main_thread:
            return func(*args, **kwargs)

        result: Dict[str, object] = {}
        event = threading.Event()

        def _runner() -> None:
            try:
                result["value"] = func(*args, **kwargs)
            except Exception as exc:  # pragma: no cover - propagated to caller
                result["error"] = exc
            finally:
                event.set()

        self._root.after(0, _runner)
        event.wait()
        if "error" in result:
            raise result["error"]  # type: ignore[misc]
        return result.get("value")


class BridgeManager:
    """Manage the lifetime of the embedded FastAPI bridge server."""

    def __init__(
        self,
        *,
        invoker: TkInvoker,
        get_mdb_path: Callable[[], Path],
        state_provider: Callable[[], Dict[str, object]] | None = None,
        focus_handler: Callable[[int, str], Dict[str, object]] | None = None,
    ) -> None:
        self._invoker = invoker
        self._get_mdb_path = get_mdb_path
        self._state_provider = state_provider
        self._focus_handler = focus_handler
        self._server: uvicorn.Server | None = None
        self._thread: threading.Thread | None = None
        self._ready = threading.Event()
        self._running = threading.Event()
        self._lock = threading.Lock()
        self._last_config: BridgeConfig | None = None
        self._last_error: str | None = None

    # ------------------------------------------------------------------
    def start(
        self,
        config: BridgeConfig,
        wizard_handler: Callable[[str, Optional[list[str]]], BridgeCreateResult],
    ) -> bool:
        """Start the bridge server using ``config``."""

        with self._lock:
            if self._running.is_set():
                if self._last_config and self._configs_equal(self._last_config, config):
                    LOG.info(
                        "Bridge already running on http://%s:%s; reusing existing server.",
                        config.host,
                        config.port,
                    )
                    return True
                self.stop()

            if self._port_in_use(config.host, int(config.port)):
                self._last_error = f"Port {config.port} in use on {config.host}"
                LOG.error("Bridge start aborted: %s", self._last_error)
                return False

            try:
                app = create_app(
                    get_mdb_path=lambda: self._get_mdb_path(),
                    auth_token=config.auth_token or None,
                    wizard_handler=lambda pn, aliases: self._invoker.invoke(
                        wizard_handler, pn, aliases
                    ),
                    state_provider=self._state_provider,
                    focus_handler=(
                        None
                        if self._focus_handler is None
                        else lambda comp_id, mode: self._invoker.invoke(
                            self._focus_handler, comp_id, mode
                        )
                    ),
                    bridge_host=config.host,
                    bridge_port=int(config.port),
                )
            except Exception as exc:  # pragma: no cover - defensive
                self._last_error = f"Failed to initialize bridge service: {exc}"
                LOG.exception("Unable to construct FastAPI application for bridge")
                return False

            app.add_event_handler("startup", self._on_startup)
            app.add_event_handler("shutdown", self._on_shutdown)

            server_config = uvicorn.Config(
                app,
                host=config.host,
                port=int(config.port),
                log_level="info",
                use_colors=False,
            )
            server = uvicorn.Server(server_config)
            thread = threading.Thread(
                target=self._run_server,
                args=(server,),
                name="CEBridgeServer",
                daemon=True,
            )
            self._server = server
            self._thread = thread
            self._ready.clear()
            self._running.clear()
            thread.start()

        if not self._ready.wait(timeout=3):
            self._last_error = "Bridge server failed to report ready state"
            LOG.error(self._last_error)
            self.stop()
            return False

        self._running.set()
        self._last_config = replace(config)
        self._last_error = None
        LOG.info(
            "Bridge server listening on http://%s:%s (auth %s)",
            config.host,
            config.port,
            "enabled" if config.auth_token else "disabled",
        )
        return True

    # ------------------------------------------------------------------
    def stop(self) -> None:
        with self._lock:
            server = self._server
            thread = self._thread
            self._server = None
            self._thread = None
        if server is not None:
            server.should_exit = True
        if thread is not None:
            thread.join(timeout=3)
        self._running.clear()
        self._ready.clear()

    # ------------------------------------------------------------------
    def is_running(self) -> bool:
        return self._running.is_set()

    @property
    def last_error(self) -> Optional[str]:
        return self._last_error

    # ------------------------------------------------------------------
    def _run_server(self, server: uvicorn.Server) -> None:
        try:
            server.run()
        except Exception as exc:  # pragma: no cover - defensive
            self._last_error = f"Bridge server crashed: {exc}"
            LOG.exception("Bridge server terminated unexpectedly")
        finally:
            self._running.clear()
            self._ready.clear()

    def _on_startup(self) -> None:
        self._ready.set()

    def _on_shutdown(self) -> None:
        self._ready.clear()

    # ------------------------------------------------------------------
    @staticmethod
    def _configs_equal(a: BridgeConfig, b: BridgeConfig) -> bool:
        return (
            a.host == b.host
            and int(a.port) == int(b.port)
            and (a.auth_token or "") == (b.auth_token or "")
        )

    @staticmethod
    def _port_in_use(host: str, port: int) -> bool:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.settimeout(0.25)
            try:
                return sock.connect_ex((host, port)) == 0
            except OSError:
                return False


__all__ = ["TkInvoker", "BridgeManager"]

