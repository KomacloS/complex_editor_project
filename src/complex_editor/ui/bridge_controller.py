from __future__ import annotations

import socket
import threading
from concurrent.futures import Future
from dataclasses import replace
from pathlib import Path
from typing import Callable, Optional

import uvicorn
from PyQt6 import QtCore, QtWidgets

from ce_bridge_service import BridgeCreateResult, create_app
from complex_editor.config.loader import BridgeConfig


class QtInvoker(QtCore.QObject):
    """Utility to run callables on the Qt GUI thread and wait for the result."""

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
        if QtCore.QThread.currentThread() == QtWidgets.QApplication.instance().thread():
            return func(*args, **kwargs)
        future: Future = Future()
        payload = (func, args, kwargs, future)
        QtCore.QMetaObject.invokeMethod(
            self,
            "_execute",
            QtCore.Qt.ConnectionType.QueuedConnection,
            payload,
        )
        return future.result()


class BridgeController:
    """Manage the lifetime of the FastAPI bridge inside the Qt application."""

    def __init__(
        self,
        get_mdb_path: Callable[[], Path],
        invoker: QtInvoker,
    ) -> None:
        self._get_mdb_path = get_mdb_path
        self._invoker = invoker
        self._server: uvicorn.Server | None = None
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()
        self._ready_event = threading.Event()
        self._running = threading.Event()
        self._last_config: BridgeConfig | None = None

    def start(
        self,
        config: BridgeConfig,
        wizard_handler: Callable[[str, Optional[list[str]]], BridgeCreateResult],
    ) -> bool:
        if self.is_running():
            if self._last_config and self._configs_equal(self._last_config, config):
                return True
            self.stop()
        with self._lock:

            if self._port_in_use(config.host, int(config.port)):
                return False

            app = create_app(
                get_mdb_path=lambda: self._coerce_path(self._get_mdb_path()),
                auth_token=config.auth_token or None,
                wizard_handler=lambda pn, aliases: self._invoker.invoke(
                    wizard_handler, pn, aliases
                ),
                bridge_host=config.host,
                bridge_port=int(config.port),
            )
            app.add_event_handler("startup", self._ready_event.set)
            app.add_event_handler("shutdown", self._ready_event.clear)

            uvicorn_config = uvicorn.Config(
                app,
                host=config.host,
                port=int(config.port),
                log_level="info",
            )
            server = uvicorn.Server(uvicorn_config)

            thread = threading.Thread(target=server.run, name="CEBridgeServer", daemon=True)
            self._server = server
            self._thread = thread
            self._ready_event.clear()
            self._running.clear()
            thread.start()

        if not self._ready_event.wait(timeout=3):
            self.stop()
            return False

        self._running.set()
        self._last_config = replace(config)
        return True

    def stop(self) -> None:
        thread: threading.Thread | None = None
        with self._lock:
            if self._server is None or self._thread is None:
                return
            self._server.should_exit = True
            self._server.force_exit = True
            thread = self._thread
        if thread is not None:
            thread.join(timeout=5)
        with self._lock:
            self._server = None
            self._thread = None
            self._running.clear()
            self._last_config = None

    def is_running(self) -> bool:
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
