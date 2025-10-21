from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Tuple
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import uvicorn

from complex_editor.config.loader import CONFIG_ENV_VAR, load_config

from .app import create_app


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Complex Editor bridge service")
    parser.add_argument(
        "--config",
        type=Path,
        default=None,
        help=(
            "Path to complex_editor.yml (defaults to internal/config or other"
            " standard search locations)."
        ),
    )
    parser.add_argument("--host", type=str, default=None, help="Override bridge host")
    parser.add_argument("--port", type=int, default=None, help="Override bridge port")
    parser.add_argument(
        "--token",
        type=str,
        default=None,
        help="Override bearer token (warning: prints in plain text)",
    )
    parser.add_argument(
        "--start-bridge",
        action="store_true",
        help="Ensure the bridge service is running, starting it if necessary.",
    )
    parser.add_argument(
        "--shutdown-bridge",
        action="store_true",
        help="Shutdown a running bridge service (requires matching bearer token).",
    )
    parser.add_argument(
        "--allow-headless-exports",
        action="store_true",
        help="Permit MDB exports even when the bridge runs without a UI (headless).",
    )
    return parser.parse_args(argv)


def _set_config_path(path: Path | None) -> None:
    if path is not None:
        os.environ[CONFIG_ENV_VAR] = str(Path(path).expanduser())


def _display_host(configured: str, probe_host: str) -> str:
    if configured in {"0.0.0.0", "::"}:
        return probe_host
    return configured


def _effective_probe_host(host: str) -> str:
    host = host.strip() or "127.0.0.1"
    if host in {"0.0.0.0", "::"}:
        return "127.0.0.1"
    return host


def _probe_health(host: str, port: int, token: str | None, timeout: float = 1.0) -> Tuple[str, Any, str]:
    probe_host = _effective_probe_host(host)
    url = f"http://{probe_host}:{port}/health"
    headers: dict[str, str] = {}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = Request(url, headers=headers)
    try:
        with urlopen(request, timeout=timeout) as response:  # nosec B310 - controlled URL
            payload = response.read()
    except HTTPError as exc:
        if exc.code in (401, 403):
            return "unauthorized", None, probe_host
        return "other_service", exc, probe_host
    except URLError as exc:
        reason = exc.reason
        if isinstance(reason, (ConnectionRefusedError, TimeoutError)):
            return "not_running", None, probe_host
        if isinstance(reason, OSError) and getattr(reason, "errno", None) in {61, 111, 10061}:
            return "not_running", None, probe_host
        return "other_service", exc, probe_host
    except Exception as exc:  # pragma: no cover - defensive
        return "other_service", exc, probe_host

    try:
        data = json.loads(payload.decode("utf-8"))
    except Exception as exc:  # pragma: no cover - defensive
        return "other_service", exc, probe_host

    if isinstance(data, dict) and data.get("ok") is True:
        return "running", data, probe_host
    return "other_service", data, probe_host


def _run_server(cfg, bridge_cfg) -> int:
    if not cfg.database.mdb_path.exists():
        raise SystemExit(f"Database not found at {cfg.database.mdb_path}")

    allow_headless_raw = getattr(bridge_cfg, "allow_headless_exports", None)
    allow_headless = None if allow_headless_raw is None else bool(allow_headless_raw)

    app = create_app(
        get_mdb_path=lambda: cfg.database.mdb_path,
        auth_token=bridge_cfg.auth_token or None,
        wizard_handler=None,
        bridge_host=bridge_cfg.host,
        bridge_port=int(bridge_cfg.port),
        allow_headless_exports=allow_headless,
        pn_normalization=cfg.pn_normalization,
    )

    mode = "frozen" if getattr(sys, "frozen", False) else "dev"
    auth_mode = "enabled" if bridge_cfg.auth_token else "disabled"
    print(
        f"[ce-bridge] listening on http://{bridge_cfg.host}:{bridge_cfg.port} "
        f"(auth: {auth_mode}, ui: headless, mode: {mode})",
        flush=True,
    )

    config = uvicorn.Config(
        app,
        host=bridge_cfg.host,
        port=int(bridge_cfg.port),
        log_level="info",
        timeout_graceful_shutdown=1,
    )
    server = uvicorn.Server(config)

    def _trigger_shutdown() -> None:
        server.should_exit = True

    app.state.trigger_shutdown = _trigger_shutdown
    try:
        server.run()
    except KeyboardInterrupt:  # pragma: no cover - CLI convenience
        pass
    return 0


def serve_from_config(cfg) -> int:
    """Public entry to run the bridge server from an already-loaded config."""
    bridge_cfg = cfg.bridge
    return _run_server(cfg, bridge_cfg)


def _ensure_bridge(cfg, bridge_cfg) -> int:
    if not cfg.database.mdb_path.exists():
        raise SystemExit(f"Database not found at {cfg.database.mdb_path}")

    token = bridge_cfg.auth_token or ""
    port = int(bridge_cfg.port)
    status, _, probe_host = _probe_health(bridge_cfg.host, port, token or None)

    allow_headless = bool(getattr(bridge_cfg, "allow_headless_exports", False))

    if status == "running":
        auth_mode = "enabled" if token else "disabled"
        print(
            f"[ce-bridge] already running on http://{_display_host(bridge_cfg.host, probe_host)}:{port} "
            f"(auth: {auth_mode})",
            flush=True,
        )
        return 0
    if status == "unauthorized":
        raise SystemExit(
            "Bridge is already running but the provided token was rejected."
        )
    if status == "other_service":
        raise SystemExit(
            f"Port {port} appears to be in use and did not respond like the CE bridge."
        )

    # not running, start new process
    if getattr(sys, "frozen", False):
        cmd = [
            sys.executable,
            "--run-bridge-server",
            "--host",
            bridge_cfg.host,
            "--port",
            str(port),
        ]
        if token:
            cmd += ["--token", token]
        if allow_headless:
            cmd.append("--allow-headless-exports")
        ce_cfg = os.environ.get("CE_CONFIG")
        if ce_cfg:
            cmd += ["--config", ce_cfg]
    else:
        cmd = [
            sys.executable,
            "-m",
            "ce_bridge_service.run",
            "--host",
            bridge_cfg.host,
            "--port",
            str(port),
        ]
        if token:
            cmd += ["--token", token]
        if allow_headless:
            cmd.append("--allow-headless-exports")
    env = os.environ.copy()
    process = subprocess.Popen(
        cmd,
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    deadline = time.monotonic() + 15.0
    status: str = "not_running"
    try:
        while time.monotonic() < deadline:
            if process.poll() is not None:
                raise SystemExit(
                    f"Bridge process exited unexpectedly with code {process.returncode}"
                )
            status, _, _ = _probe_health(bridge_cfg.host, port, token or None)
            if status == "running":
                auth_mode = "enabled" if token else "disabled"
                frozen_suffix = " (frozen)" if getattr(sys, "frozen", False) else ""
                print(
                    f"[ce-bridge] listening on http://{_display_host(bridge_cfg.host, probe_host)}:{port} "
                    f"(auth: {auth_mode}){frozen_suffix}",
                    flush=True,
                )
                return 0
            if status == "unauthorized":
                raise SystemExit(
                    "Bridge started but rejected the provided token."
                )
            if status == "other_service":
                raise SystemExit(
                    f"Port {port} became occupied by another service during startup."
                )
            time.sleep(0.2)
    finally:
        if process.poll() is None and status != "running":
            process.terminate()
            try:
                process.wait(timeout=5)
            except Exception:  # pragma: no cover - defensive
                try:
                    process.kill()
                except Exception:  # pragma: no cover - defensive
                    pass

    raise SystemExit("Timed out waiting for bridge health endpoint")


def _shutdown_bridge(cfg, bridge_cfg) -> int:
    if not cfg.database.mdb_path.exists():
        raise SystemExit(f"Database not found at {cfg.database.mdb_path}")

    token = bridge_cfg.auth_token or ""
    port = int(bridge_cfg.port)
    status, _, probe_host = _probe_health(bridge_cfg.host, port, token or None)

    if status == "unauthorized":
        raise SystemExit("Bridge rejected the provided token; cannot shutdown")
    if status == "other_service":
        raise SystemExit(
            f"Port {port} is occupied by a different service; aborting shutdown."
        )
    if status == "not_running":
        print(
            f"[ce-bridge] no running instance on http://{_display_host(bridge_cfg.host, probe_host)}:{port}",
            flush=True,
        )
        return 0

    url = f"http://{probe_host}:{port}/admin/shutdown"
    headers: dict[str, str] = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = Request(url, data=b"{}", headers=headers, method="POST")
    try:
        with urlopen(request, timeout=3.0):  # nosec B310 - controlled URL
            pass
    except HTTPError as exc:
        if exc.code in (401, 403):
            raise SystemExit("Bridge rejected the provided token; cannot shutdown")
        raise SystemExit(f"Failed to request shutdown: {exc}") from exc
    except URLError as exc:
        raise SystemExit(f"Failed to contact bridge for shutdown: {exc}") from exc

    deadline = time.monotonic() + 10.0
    while time.monotonic() < deadline:
        status, _, _ = _probe_health(bridge_cfg.host, port, token or None)
        if status == "not_running":
            print(
                f"[ce-bridge] shutdown complete for http://{_display_host(bridge_cfg.host, probe_host)}:{port}",
                flush=True,
            )
            return 0
        if status == "other_service":
            raise SystemExit(
                f"Port {port} became occupied by a different service during shutdown."
            )
        time.sleep(0.2)

    raise SystemExit("Timed out waiting for bridge to shutdown")


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)

    if args.start_bridge and args.shutdown_bridge:
        raise SystemExit("--start-bridge and --shutdown-bridge are mutually exclusive")

    if args.port is not None and (args.port <= 0 or args.port > 65535):
        raise SystemExit("Bridge port must be between 1 and 65535")

    _set_config_path(args.config)

    cfg = load_config()
    bridge_cfg = cfg.bridge

    if args.host:
        bridge_cfg.host = args.host
    if args.port is not None:
        bridge_cfg.port = int(args.port)
    if args.token is not None:
        bridge_cfg.auth_token = args.token

    if args.allow_headless_exports:
        bridge_cfg.allow_headless_exports = True

    bridge_cfg.base_url = f"http://{bridge_cfg.host}:{bridge_cfg.port}"

    if args.start_bridge:
        return _ensure_bridge(cfg, bridge_cfg)

    if args.shutdown_bridge:
        return _shutdown_bridge(cfg, bridge_cfg)

    return _run_server(cfg, bridge_cfg)


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main(sys.argv[1:]))
