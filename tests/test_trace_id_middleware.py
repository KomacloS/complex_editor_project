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


def test_trace_id_propagation_and_generation(tmp_path):
    os.environ["CE_LOG_DIR"] = str(tmp_path)

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

    # Add a simple route we can call; we only assert the response header
    async def ping():
        return {"ok": True}

    client.app.add_api_route("/ping", ping, methods=["GET"])  # type: ignore[attr-defined]

    # Provided trace id is propagated
    given = "abc-123"
    r1 = client.get("/ping", headers={"Authorization": "Bearer token", "X-Trace-Id": given})
    # Debug aide on failure
    assert r1.status_code == 200, r1.text
    assert r1.headers.get("X-Trace-Id") == given
    assert r1.json()["ok"] is True

    # If not provided, it's generated (UUID4-like) and returned
    r2 = client.get("/ping", headers={"Authorization": "Bearer token"})
    assert r2.status_code == 200
    auto = r2.headers.get("X-Trace-Id")
    assert auto and isinstance(auto, str) and len(auto) >= 8
    assert r2.json()["ok"] is True
