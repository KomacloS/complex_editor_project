from __future__ import annotations

import logging
import sys
import socket
import threading
from concurrent.futures import Future
from types import SimpleNamespace
from dataclasses import replace
from pathlib import Path
from typing import Callable, Optional
from copy import deepcopy

import uvicorn
from PyQt6 import QtCore, QtWidgets

from ce_bridge_service import BridgeCreateResult, create_app
from ce_bridge_service import run as bridge_run
from complex_editor.config.loader import BridgeConfig

logger = logging.getLogger(__name__)


class QtInvoker(QtCore.QObject):
    """Utility to run callables on the Qt GUI thread and wait for the result."""

    _execute_signal = QtCore.pyqtSignal(object)

    def __init__(self) -> None:
        super().__init__()
        self._execute_signal.connect(
            self._execute,
            QtCore.Qt.ConnectionType.QueuedConnection,
        )

    @QtCore.pyqtSlot(object)
    def _execute(self, payload: tuple[Callable, tuple, dict, Future]) -> None:
        func, args, kwargs, future = payload
        if future.done():  # pragma: no cover - defensive
            return
        try:
            result = func(*args, **kwargs)
        except Exception as exc:  # pragma: no cover - propagated to caller
            future.set_exception(exc)
        else:
            future.set_result(result)

    def invoke(self, func: Callable, *args, **kwargs):
        app = QtWidgets.QApplication.instance()
        if app is None:
            return func(*args, **kwargs)
        if QtCore.QThread.currentThread() == app.thread():
            return func(*args, **kwargs)
        future: Future = Future()
        payload = (func, args, kwargs, future)
        self._execute_signal.emit(payload)
        return future.result()


class BridgeController:
    """Manage the lifetime of the FastAPI bridge inside the Qt application."""

    def __init__(
        self,
        get_mdb_path: Callable[[], Path],
        invoker: QtInvoker,
        state_provider: Callable[[], dict[str, object]] | None = None,
        open_complex: Callable[[int, str], dict[str, object]] | None = None,
    ) -> None:
        self._get_mdb_path = get_mdb_path
        self._invoker = invoker
        self._state_provider = state_provider
        self._focus_callback = open_complex
        self._external_capable = getattr(sys, "frozen", False)
        self._use_external: bool | None = None
        self._server: uvicorn.Server | None = None
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()
        self._ready_event = threading.Event()
        self._running = threading.Event()
        self._last_config: BridgeConfig | None = None
        self._last_error: str | None = None
        self._startup_success = False

    def start(
        self,
        config: BridgeConfig,
        wizard_handler: Callable[[str, Optional[list[str]]], BridgeCreateResult],
    ) -> bool:
        auth_state = "enabled" if config.auth_token else "disabled"
        self._last_error = None
        self._startup_success = False
        logger.info(
            "Bridge start requested host=%s port=%s (auth %s)",
            config.host,
            config.port,
            auth_state,
        )
        use_external = self._decide_external()
        self._use_external = use_external
        if use_external:
            return self._start_external(config)

        if self.is_running():
            if self._last_config and self._configs_equal(self._last_config, config):
                logger.info(
                    "Bridge already running with matching configuration; reusing existing server."
                )
                return True
            logger.info("Bridge configuration changed; restarting bridge server.")
            self.stop()
        with self._lock:
            if self._port_in_use(config.host, int(config.port)):
                msg = f"Port {config.port} is already in use on host {config.host}."
                self._last_error = msg
                logger.warning("Bridge start aborted: %s", msg)
                return False

            try:
                app = create_app(
                    get_mdb_path=lambda: self._coerce_path(self._get_mdb_path()),
                    auth_token=config.auth_token or None,
                    wizard_handler=lambda pn, aliases: self._invoker.invoke(
                        wizard_handler, pn, aliases
                    ),
                    bridge_host=config.host,
                    bridge_port=int(config.port),
                    state_provider=self._state_provider,
                    focus_handler=(
                        None
                        if self._focus_callback is None
                        else lambda comp_id, mode: self._invoker.invoke(
                            self._focus_callback, comp_id, mode
                        )
                    ),
                )
            except Exception as exc:
                msg = f"Failed to initialize bridge service: {exc}"
                self._last_error = msg
                logger.exception("Bridge start failed while constructing FastAPI application.")
                return False
            app.add_event_handler("startup", self._on_startup)
            app.add_event_handler("shutdown", self._on_shutdown)

            log_config = self._uvicorn_log_config()
            uvicorn_config = uvicorn.Config(
                app,
                host=config.host,
                port=int(config.port),
                log_level="info",
                use_colors=False,
                log_config=log_config,
            )
            server = uvicorn.Server(uvicorn_config)

            thread = threading.Thread(
                target=self._server_worker,
                args=(server,),
                name="CEBridgeServer",
                daemon=True,
            )
            self._server = server
            self._thread = thread
            self._ready_event.clear()
            self._running.clear()
            thread.start()
            logger.debug("Bridge server thread launched.")

        if not self._ready_event.wait(timeout=3):
            msg = "Bridge service did not report ready state within 3 seconds."
            self._last_error = msg
            logger.error("Bridge server failed to report ready state within timeout; shutting it down.")
            self.stop()
            return False

        with self._lock:
            startup_ok = self._startup_success
            last_error = self._last_error
        if not startup_ok:
            logger.error("Bridge server failed during startup: %s", last_error or "unknown error")
            self.stop()
            return False

        self._running.set()
        self._last_config = replace(config)
        self._last_error = None
        logger.info(
            "Bridge server running on http://%s:%s (auth %s)",
            config.host,
            config.port,
            auth_state,
        )
        return True

    def stop(self) -> None:
        use_external = self._use_external if self._use_external is not None else self._decide_external()
        if use_external:
            self._stop_external()
            self._use_external = None
            return
        thread: threading.Thread | None = None
        was_running = self._running.is_set()
        with self._lock:
            if self._server is None or self._thread is None:
                logger.debug("Bridge stop requested but no server instance is active.")
                return
            logger.info("Stopping bridge server.")
            self._server.should_exit = True
            self._server.force_exit = True
            thread = self._thread
        if thread is not None:
            thread.join(timeout=5)
            if thread.is_alive():
                logger.warning("Bridge server thread did not terminate within timeout.")
        with self._lock:
            self._server = None
            self._thread = None
            self._running.clear()
            self._last_config = None
            if was_running:
                self._last_error = None
            self._startup_success = False
            logger.debug("Bridge server state cleared.")
        self._use_external = None

    def is_running(self) -> bool:
        use_external = self._use_external if self._use_external is not None else self._decide_external()
        if use_external:
            return self._external_is_running()
        if self._running.is_set():
            return True
        with self._lock:
            return self._thread is not None and self._thread.is_alive()

    def snippet(self, config: BridgeConfig) -> str:
        base = config.base_url.rstrip("/") or f"http://{config.host}:{config.port}"
        auth = (
            f"-H \"Authorization: Bearer {config.auth_token}\" "
            if config.auth_token
            else ""
        )
        return (
            f"curl -X POST {base}/complexes "
            f"-H \"Content-Type: application/json\" "
            f"{auth}-d '{{\"pn\": \"PN123\", \"aliases\": [\"ALT1\"]}}'"
        )

    def last_error(self) -> str | None:
        return self._last_error

    # --------------------------- external helpers ---------------------------
    def _decide_external(self) -> bool:
        if not self._external_capable:
            return False
        try:
            app = QtWidgets.QApplication.instance()
        except Exception:
            app = None
        return app is None

    def _uvicorn_log_config(self) -> dict[str, object]:
        base = deepcopy(uvicorn.config.LOGGING_CONFIG)
        try:
            base["formatters"]["default"]["use_colors"] = False
        except Exception:
            pass
        try:
            base["formatters"]["access"]["use_colors"] = False
        except Exception:
            pass

        stderr = getattr(sys, "stderr", None)
        stdout = getattr(sys, "stdout", None)

        if stderr is None:
            base["handlers"]["default"] = {"class": "logging.NullHandler"}
        if stdout is None:
            base["handlers"]["access"] = {"class": "logging.NullHandler"}
        return base

    def _start_external(self, config: BridgeConfig) -> bool:
        cfg = self._build_external_config(config)
        try:
            bridge_run._ensure_bridge(cfg, cfg.bridge)
        except SystemExit as exc:
            message = str(exc) or "Bridge start failed"
            self._last_error = message
            logger.error("External bridge start failed: %s", message)
            return False
        except Exception as exc:  # pragma: no cover - defensive
            self._last_error = f"Unexpected bridge start failure: {exc}"
            logger.exception("External bridge start raised unexpected exception.")
            return False
        self._last_config = replace(config)
        self._last_error = None
        logger.info(
            "Bridge server running via external process on http://%s:%s (auth %s, frozen)",
            cfg.bridge.host,
            cfg.bridge.port,
            "enabled" if cfg.bridge.auth_token else "disabled",
        )
        return True

    def _external_is_running(self) -> bool:
        if self._last_config is None:
            return False
        cfg = self._build_external_config(self._last_config)
        token = cfg.bridge.auth_token or None
        status, _, _ = bridge_run._probe_health(
            cfg.bridge.host,
            int(cfg.bridge.port),
            token,
        )
        return status == "running"

    def _stop_external(self) -> None:
        if self._last_config is None:
            return
        cfg = self._build_external_config(self._last_config)
        try:
            bridge_run._shutdown_bridge(cfg, cfg.bridge)
        except SystemExit as exc:
            message = str(exc) or "Bridge shutdown reported failure"
            self._last_error = message
            logger.warning("External bridge shutdown raised SystemExit: %s", message)
        except Exception as exc:  # pragma: no cover - defensive
            self._last_error = f"Unexpected bridge shutdown failure: {exc}"
            logger.exception("External bridge shutdown raised unexpected exception.")
        else:
            self._last_error = None
            self._last_config = None
            logger.info("External bridge server shutdown complete.")

    def _build_external_config(self, config: BridgeConfig) -> SimpleNamespace:
        db_path = self._coerce_path(self._get_mdb_path())
        base_url = getattr(config, "base_url", None) or f"http://{config.host}:{int(config.port)}"
        timeout = getattr(config, "request_timeout_seconds", 15)
        database = SimpleNamespace(mdb_path=db_path)
        bridge_ns = SimpleNamespace(
            enabled=config.enabled,
            base_url=base_url,
            auth_token=config.auth_token or "",
            host=config.host,
            port=int(config.port),
            request_timeout_seconds=timeout,
        )
        cfg = SimpleNamespace(database=database, bridge=bridge_ns)
        return cfg

    # --------------------------- embedded server helpers ---------------------------
    def _server_worker(self, server: uvicorn.Server) -> None:
        try:
            server.run()
        except BaseException as exc:  # pragma: no cover - defensive
            logger.exception("Bridge server crashed while running.")
            with self._lock:
                self._last_error = f"Bridge server crashed: {exc}"
                self._startup_success = False
            self._ready_event.set()
            raise

    def _on_startup(self) -> None:
        logger.debug("Bridge server signaled startup.")
        with self._lock:
            self._startup_success = True
        self._ready_event.set()

    def _on_shutdown(self) -> None:
        logger.debug("Bridge server signaled shutdown.")
        self._ready_event.clear()
        self._running.clear()

    @staticmethod
    def _configs_equal(a: BridgeConfig, b: BridgeConfig) -> bool:
        return (
            a.enabled == b.enabled
            and a.host == b.host
            and int(a.port) == int(b.port)
            and a.auth_token == b.auth_token
        )

    @staticmethod
    def _port_in_use(host: str, port: int) -> bool:
        probe_host = host if host not in {"0.0.0.0", "::"} else "127.0.0.1"
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.settimeout(0.25)
            try:
                sock.connect((probe_host, port))
            except OSError:
                return False
            return True

    @staticmethod
    def _coerce_path(path_like) -> Path:
        if isinstance(path_like, Path):
            return path_like
        return Path(str(path_like))


__all__ = ["BridgeController", "QtInvoker"]
