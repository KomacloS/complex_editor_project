from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import yaml

ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = ROOT / "src"


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _run_module(args: list[str], env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    cmd = [sys.executable, "-m", "complex_editor", *args]
    return subprocess.run(cmd, check=False, text=True, env=env)


def _wait_for_health(port: int, token: str, timeout: float = 10.0) -> dict:
    deadline = time.monotonic() + timeout
    url = f"http://127.0.0.1:{port}/health"
    headers = {"Authorization": f"Bearer {token}"}
    while time.monotonic() < deadline:
        request = Request(url, headers=headers)
        try:
            with urlopen(request, timeout=1.0) as response:  # nosec B310 - controlled URL
                payload = response.read()
        except (URLError, ConnectionError):  # pragma: no cover - network error variations
            time.sleep(0.2)
            continue
        except HTTPError as exc:
            if exc.code in (401, 403):
                raise AssertionError("Bridge rejected token during health probe") from exc
            time.sleep(0.2)
            continue
        data = json.loads(payload.decode("utf-8"))
        if data.get("ok"):
            return data
        time.sleep(0.2)
    raise AssertionError("Bridge health endpoint did not become ready in time")


def _wait_for_shutdown(port: int, token: str, timeout: float = 10.0) -> None:
    deadline = time.monotonic() + timeout
    url = f"http://127.0.0.1:{port}/health"
    headers = {"Authorization": f"Bearer {token}"}
    while time.monotonic() < deadline:
        request = Request(url, headers=headers)
        try:
            with urlopen(request, timeout=1.0):  # nosec B310 - controlled URL
                pass
        except URLError:
            return
        except HTTPError:
            time.sleep(0.2)
            continue
        time.sleep(0.2)
    raise AssertionError("Bridge did not shutdown in time")


def test_complex_editor_module_controls_bridge(tmp_path: Path) -> None:
    port = _free_port()
    token = "test-token"

    mdb_path = tmp_path / "dummy.mdb"
    mdb_path.touch()

    config_path = tmp_path / "ce.yml"
    config_payload = {
        "database": {"mdb_path": str(mdb_path)},
        "bridge": {"host": "127.0.0.1"},
    }
    config_path.write_text(yaml.safe_dump(config_payload, sort_keys=False), encoding="utf-8")

    env = os.environ.copy()
    env["PYTHONPATH"] = str(SRC_ROOT) + os.pathsep + env.get("PYTHONPATH", "")
    env.setdefault("QT_QPA_PLATFORM", "offscreen")
    env["CE_CONFIG"] = str(config_path)

    start_args = [
        "--start-bridge",
        "--port",
        str(port),
        "--token",
        token,
        "--config",
        str(config_path),
    ]

    start_proc = _run_module(start_args, env)
    if start_proc.returncode != 0:
        raise AssertionError(start_proc.stderr or start_proc.stdout)

    try:
        health = _wait_for_health(port, token)
    except AssertionError as exc:  # pragma: no cover - diagnostic aid
        raise AssertionError(
            f"{exc}\nstdout:\n{start_proc.stdout or ''}\nstderr:\n{start_proc.stderr or ''}"
        ) from exc
    assert health["ok"] is True
    assert health["port"] == port
    assert health["auth_required"] is True

    reuse_proc = _run_module(start_args, env)
    if reuse_proc.returncode != 0:
        raise AssertionError(reuse_proc.stderr or reuse_proc.stdout)

    shutdown_args = [
        "--shutdown-bridge",
        "--port",
        str(port),
        "--token",
        token,
        "--config",
        str(config_path),
    ]

    try:
        stop_proc = _run_module(shutdown_args, env)
        if stop_proc.returncode != 0:
            raise AssertionError(stop_proc.stderr or stop_proc.stdout)
    finally:
        _wait_for_shutdown(port, token)
