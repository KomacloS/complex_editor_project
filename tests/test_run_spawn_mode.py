from __future__ import annotations

import sys
from pathlib import Path

SRC_ROOT = Path(__file__).resolve().parents[1] / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from ce_bridge_service import run as bridge_run


class Dummy:
    pass


def test_builds_exe_command_when_frozen(monkeypatch):
    cfg = Dummy()
    cfg.bridge = Dummy()
    cfg.bridge.host = "127.0.0.1"
    cfg.bridge.port = 9999
    cfg.bridge.auth_token = "abc"
    cfg.database = Dummy()
    cfg.database.mdb_path = Path(__file__)

    monkeypatch.setattr(sys, "frozen", True, raising=False)

    captured: dict[str, list[str]] = {}

    class _FakeProcess:
        def poll(self):
            return None

        def terminate(self):
            return None

        def wait(self, timeout=None):
            return None

        def kill(self):
            return None

    def fake_popen(cmd, **_kwargs):
        captured["cmd"] = cmd
        return _FakeProcess()

    monkeypatch.setattr(bridge_run, "_probe_health", lambda *a, **k: ("not_running", None, "127.0.0.1"))
    monkeypatch.setattr(bridge_run.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(bridge_run.time, "sleep", lambda _s: None)

    tick = {"value": 0.0}

    def fake_monotonic():
        tick["value"] += 1.0
        return tick["value"]

    monkeypatch.setattr(bridge_run.time, "monotonic", fake_monotonic)

    try:
        bridge_run._ensure_bridge(cfg, cfg.bridge)
    except SystemExit:
        pass

    cmd = captured["cmd"]
    assert cmd[0].endswith("ComplexEditor.exe") or cmd[0] == sys.executable
    assert "--run-bridge-server" in cmd
