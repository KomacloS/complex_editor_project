from __future__ import annotations

import json
import os
from pathlib import Path

from fastapi.testclient import TestClient

import sys

ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from ce_bridge_service.app import create_app  # noqa: E402
from ce_bridge_service.types import BridgeCreateResult  # noqa: E402


def test_admin_logs_lookup_returns_hits_and_stack(tmp_path):
    os.environ["CE_LOG_DIR"] = str(tmp_path)
    os.environ["CE_LOG_JSON"] = "true"

    trace_id = "trace-4444"
    traceback_text = (
        "Traceback (most recent call last):\n"
        "  File \"/app/main.py\", line 10, in boom\n"
        "    1/0\n"
        "ZeroDivisionError: division by zero"
    )
    # Create a fake JSON log line
    log_obj = {
        "time": "2025-01-01T00:00:00Z",
        "level": "ERROR",
        "logger": "test",
        "message": "Unhandled exception",
        "trace_id": trace_id,
        "exception": traceback_text,
    }
    log_path = Path(tmp_path) / "ce_bridge.log"
    log_path.write_text(json.dumps(log_obj) + "\n", encoding="utf-8")

    client = TestClient(
        create_app(
            get_mdb_path=lambda: ROOT / "tests" / "data" / "dummy.mdb",
            auth_token="token",
            wizard_handler=lambda pn, aliases: BridgeCreateResult(created=False, reason="cancelled"),
            mdb_factory=None,
            bridge_host="127.0.0.1",
            bridge_port=8765,
        )
    )

    resp = client.get(f"/admin/logs/{trace_id}", headers={"Authorization": "Bearer token"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["trace_id"] == trace_id
    assert isinstance(body.get("hits"), list) and body["hits"], "expected at least one hit"
    assert traceback_text in body.get("stacktrace", "")

