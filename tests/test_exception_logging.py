from __future__ import annotations

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


def test_exception_logging_contains_trace_context(tmp_path):
    os.environ["CE_LOG_DIR"] = str(tmp_path)

    app = create_app(
        get_mdb_path=lambda: ROOT / "tests" / "data" / "dummy.mdb",
        auth_token="token",
        wizard_handler=lambda pn, aliases: BridgeCreateResult(created=False, reason="cancelled"),
        mdb_factory=None,
        bridge_host="127.0.0.1",
        bridge_port=8765,
    )
    client = TestClient(app, raise_server_exceptions=False)

    # Inject a route that raises an error to trigger the global handler
    async def boom():
        raise RuntimeError("kaboom")

    client.app.add_api_route("/boom", boom, methods=["GET"])  # type: ignore[attr-defined]

    trace_id = "test-trace-xyz"
    resp = client.get("/boom", headers={"Authorization": "Bearer token", "X-Trace-Id": trace_id})
    assert resp.status_code == 500
    body = resp.json()
    assert body["trace_id"] == trace_id
    assert body["reason"] == "internal_error"

    # Scan the log file and assert at least one line includes trace context
    logs = list(Path(os.environ["CE_LOG_DIR"]).glob("*.log"))
    assert logs, "no log file created"
    found = False
    for path in logs:
        for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
            if trace_id in line and "event=unhandled_exception" in line:
                found = True
                break
        if found:
            break
    assert found, "no exception log line with trace_id found"
