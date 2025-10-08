from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

import sys

ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from ce_bridge_service.app import create_app
from ce_bridge_service import run as run_module
from ce_bridge_service.types import BridgeCreateResult
from complex_editor.db.mdb_api import ComplexDevice as DbComplex
from complex_editor.db.mdb_api import SubComponent as DbSub


class FakeCursor:
    def __init__(self, owner: "FakeMDB") -> None:
        self.owner = owner
        self.params: tuple = ()

    def execute(self, query: str, *params):  # noqa: ANN001 - signature dictated by pyodbc
        self.params = params
        return self

    def fetchall(self):
        needle = ""
        if self.params:
            needle = str(self.params[0]).replace("%", "").lower()
        results = []
        for cid, info in self.owner.data.items():
            device = info["device"]
            name = device.name.lower()
            aliases = [a.lower() for a in device.aliases]
            if not needle or needle in name or any(needle in a for a in aliases):
                results.append((cid, device.name))
        limit = getattr(self.owner, "_bridge_limit", None)
        if isinstance(limit, int):
            results = results[:limit]
        return results


class FakeMDB:
    def __init__(self, path: Path, data: dict[int, dict]) -> None:
        self.path = Path(path)
        self.data = data
        self.closed = False

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        self.closed = True
        return False

    def _cur(self) -> FakeCursor:
        return FakeCursor(self)

    def _alias_schema(self, cur):  # noqa: ANN001 - mimics real signature
        return "IDCompDesc", "Alias", None

    def get_aliases(self, comp_id: int) -> list[str]:
        return list(self.data[comp_id]["device"].aliases)

    def get_complex(self, comp_id: int) -> DbComplex:
        return self.data[comp_id]["device"]


def _make_dataset() -> dict[int, dict]:
    sub = DbSub(
        id_sub_component=1,
        id_function=10,
        value="",
        id_unit=None,
        tol_p=None,
        tol_n=None,
        force_bits=None,
        pins={"A": 1, "S": "<xml />"},
    )
    device = DbComplex(
        id_comp_desc=1,
        name="PN-100",
        total_pins=8,
        subcomponents=[sub],
        aliases=["ALT-1"],
    )
    return {1: {"device": device}}


def _make_client(handler) -> TestClient:
    data = _make_dataset()

    def factory(path: Path) -> FakeMDB:
        return FakeMDB(path, data)

    app = create_app(
        get_mdb_path=lambda: Path("dummy.mdb"),
        auth_token="token",
        wizard_handler=handler,
        mdb_factory=factory,
        bridge_host="127.0.0.1",
        bridge_port=8765,
    )
    return TestClient(app)


def _auth() -> dict[str, str]:
    return {"Authorization": "Bearer token"}


def test_bridge_requires_bearer_token():
    client = _make_client(lambda pn, aliases: BridgeCreateResult(created=False, reason="cancelled"))
    assert client.get("/health").status_code == 401
    assert client.get("/health", headers={"Authorization": "Bearer nope"}).status_code == 403


def test_bridge_health_and_search_and_detail():
    client = _make_client(lambda pn, aliases: BridgeCreateResult(created=False, reason="cancelled"))

    health = client.get("/health", headers=_auth())
    assert health.status_code == 200
    payload = health.json()
    assert payload["ok"] is True
    assert payload["port"] == 8765
    assert payload["auth_required"] is True

    search = client.get("/complexes/search", params={"pn": "PN"}, headers=_auth())
    assert search.status_code == 200
    body = search.json()
    assert len(body) == 1
    assert body[0]["id"] == 1
    assert body[0]["aliases"] == ["ALT-1"]

    detail = client.get("/complexes/1", headers=_auth())
    assert detail.status_code == 200
    payload = detail.json()
    assert payload["id"] == 1
    assert payload["pin_map"]["1"]["A"] == 1
    assert payload["macro_ids"] == [10]


def test_bridge_create_complex_success():
    calls: list[tuple[str, list[str]]] = []

    def handler(pn: str, aliases: list[str] | None) -> BridgeCreateResult:
        calls.append((pn, aliases or []))
        return BridgeCreateResult(created=True, comp_id=42, db_path="dummy.mdb")

    client = _make_client(handler)
    resp = client.post(
        "/complexes",
        headers=_auth() | {"Content-Type": "application/json"},
        json={"pn": "NEW-PN", "aliases": ["ALT"]},
    )
    assert resp.status_code == 201
    assert resp.json()["id"] == 42
    assert calls == [("NEW-PN", ["ALT"])]


def test_bridge_create_complex_cancelled():
    def handler(pn: str, aliases: list[str] | None) -> BridgeCreateResult:
        return BridgeCreateResult(created=False, reason="cancelled")

    client = _make_client(handler)
    resp = client.post(
        "/complexes",
        headers=_auth() | {"Content-Type": "application/json"},
        json={"pn": "PN", "aliases": []},
    )
    assert resp.status_code == 409
    assert resp.json()["detail"] == "cancelled"


def test_bridge_shutdown_endpoint_sets_flag():
    triggered = {"value": False}

    def handler(pn: str, aliases: list[str] | None) -> BridgeCreateResult:
        return BridgeCreateResult(created=False, reason="cancelled")

    client = _make_client(handler)
    client.app.state.trigger_shutdown = lambda: triggered.__setitem__("value", True)

    resp = client.post("/admin/shutdown", headers=_auth())
    assert resp.status_code == 200
    assert resp.json() == {"ok": True}
    assert triggered["value"] is True


def test_build_server_cmd_frozen(monkeypatch):
    monkeypatch.setattr(run_module.sys, "frozen", True, raising=False)
    monkeypatch.setattr(run_module.sys, "executable", "ComplexEditor.exe")
    cmd = run_module._build_server_cmd("127.0.0.1", 8765, "XYZ")
    assert cmd == [
        "ComplexEditor.exe",
        "--host",
        "127.0.0.1",
        "--port",
        "8765",
        "--token",
        "XYZ",
    ]


def test_build_server_cmd_dev(monkeypatch):
    monkeypatch.setattr(run_module.sys, "frozen", False, raising=False)
    monkeypatch.setattr(run_module.sys, "executable", "/usr/bin/python")
    cmd = run_module._build_server_cmd("localhost", 9000, None)
    assert cmd == [
        "/usr/bin/python",
        "-m",
        "ce_bridge_service.run",
        "--host",
        "localhost",
        "--port",
        "9000",
    ]
