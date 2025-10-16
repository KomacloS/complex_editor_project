from __future__ import annotations

import atexit
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Callable, Sequence

from fastapi.testclient import TestClient

import sys

ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from ce_bridge_service.app import create_app, FocusBusyError
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
            if not isinstance(cid, int):
                continue
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
        self.saved_subset: SimpleNamespace | None = None

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

    def set_aliases(self, comp_id: int, aliases: list[str]) -> None:
        cleaned = [a.strip() for a in (aliases or []) if a and str(a).strip()]
        unique_sorted = sorted(dict.fromkeys(cleaned))
        self.data[comp_id]["device"].aliases = unique_sorted

    def list_complexes(self) -> list[tuple[int, str, int]]:
        entries: list[tuple[int, str, int]] = []
        ids = sorted(cid for cid in self.data if isinstance(cid, int))
        for cid in ids:
            device = self.data[cid]["device"]
            subs = len(device.subcomponents or [])
            entries.append((cid, device.name, subs))
        return entries

    def save_subset_to_mdb(self, target_path: Path, comp_ids: Sequence[int]) -> Path:
        target = Path(target_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        comp_list = [int(cid) for cid in comp_ids]
        target.write_text("subset_export")
        record = {"path": target, "comp_ids": comp_list}
        exports = self.data.setdefault("__exports__", [])
        exports.append(record)
        self.saved_subset = SimpleNamespace(**record)
        return target


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


def _make_dataset_with_peer() -> dict[int, dict]:
    base = _make_dataset()
    peer = DbComplex(
        id_comp_desc=2,
        name="ALT-2",
        total_pins=4,
        subcomponents=[],
        aliases=[],
    )
    base[2] = {"device": peer}
    return base


def _make_client(
    handler: Callable[[str, list[str] | None], BridgeCreateResult] | None,
    state: dict | Callable[[], dict] | None = None,
    mdb_path: Path | Callable[[], Path] | None = None,
    dataset: dict[int, dict] | None = None,
    focus_handler: Callable[[int, str], dict[str, object]] | None = None,
) -> TestClient:
    data = dataset if dataset is not None else _make_dataset()
    default_path = ROOT / "tests" / "data" / "dummy.mdb"

    if callable(mdb_path):
        def get_path() -> Path:
            candidate = mdb_path()
            return candidate if isinstance(candidate, Path) else Path(candidate)
    else:
        mdb_location = Path(mdb_path) if mdb_path is not None else default_path

        def get_path() -> Path:
            return mdb_location

    def factory(path: Path) -> FakeMDB:
        return FakeMDB(path, data)

    if state is None:
        def provider() -> dict[str, object]:
            return {}
    elif callable(state):
        def provider() -> dict[str, object]:
            return state()
    else:
        def provider() -> dict[str, object]:
            return state

    app = create_app(
        get_mdb_path=get_path,
        auth_token="token",
        wizard_handler=handler,
        mdb_factory=factory,
        bridge_host="127.0.0.1",
        bridge_port=8765,
        state_provider=provider,
        focus_handler=focus_handler,
    )
    client = TestClient(app)
    client.__enter__()
    atexit.register(lambda: client.__exit__(None, None, None))
    return client


def _auth() -> dict[str, str]:
    return {"Authorization": "Bearer token"}


def _wait_until(predicate, timeout: float = 1.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return False


def _wait_for_ready(client: TestClient, timeout: float = 1.0) -> bool:
    return _wait_until(lambda: client.app.state.ready, timeout)


def test_bridge_requires_bearer_token():
    client = _make_client(lambda pn, aliases: BridgeCreateResult(created=False, reason="cancelled"))
    assert client.get("/health").status_code == 401
    assert client.get("/health", headers={"Authorization": "Bearer nope"}).status_code == 403


def test_bridge_startup_background_readiness():
    client = _make_client(lambda pn, aliases: BridgeCreateResult(created=False, reason="cancelled"))
    assert isinstance(client.app.state.ready, bool)
    if not client.app.state.ready:
        assert client.app.state.last_ready_error == "warming_up"
    assert _wait_for_ready(client)
    health = client.get("/health", headers=_auth())
    assert health.status_code == 200
    assert health.json()["ok"] is True


def test_bridge_invalid_mdb_path_reports_reason(tmp_path):
    missing = tmp_path / "missing.mdb"
    client = _make_client(lambda pn, aliases: BridgeCreateResult(created=False, reason="cancelled"), mdb_path=missing)
    assert _wait_until(lambda: client.app.state.last_ready_error not in {"", "warming_up"}, timeout=1.0)
    resp = client.get("/health", headers=_auth())
    assert resp.status_code == 503
    body = resp.json()
    assert body["ok"] is False
    assert str(missing) in body["reason"]
    state = client.get("/state", headers=_auth()).json()
    assert state["ready"] is False
    assert str(missing) in state["last_ready_error"]


def test_bridge_mdb_path_change_triggers_recheck(tmp_path):
    valid = tmp_path / "valid.mdb"
    valid.write_text("dummy")
    mutable_path = {"value": valid}
    ui_state = {"wizard_open": False, "unsaved_changes": False, "mdb_path": str(valid)}

    client = _make_client(
        lambda pn, aliases: BridgeCreateResult(created=False, reason="cancelled"),
        state=ui_state,
        mdb_path=lambda: mutable_path["value"],
    )

    assert _wait_for_ready(client)

    missing = tmp_path / "missing.mdb"
    mutable_path["value"] = missing
    ui_state["mdb_path"] = str(missing)
    client.get("/state", headers=_auth())
    assert _wait_until(lambda: client.app.state.ready is False, timeout=1.0)
    assert _wait_until(lambda: str(missing) in client.app.state.last_ready_error, timeout=1.0)
    assert client.get("/health", headers=_auth()).status_code == 503

    mutable_path["value"] = valid
    ui_state["mdb_path"] = str(valid)
    client.get("/state", headers=_auth())
    assert _wait_for_ready(client)
    final_state = client.get("/state", headers=_auth()).json()
    assert final_state["ready"] is True
    assert final_state["last_ready_error"] == ""
    assert final_state["mdb_path"] == str(valid)
    assert final_state["wizard_available"] is True


def test_bridge_health_and_search_and_detail():
    client = _make_client(lambda pn, aliases: BridgeCreateResult(created=False, reason="cancelled"))

    assert _wait_for_ready(client)
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
    assert body[0]["pn"] == "PN-100"
    assert body[0]["aliases"] == ["ALT-1"]

    detail = client.get("/complexes/1", headers=_auth())
    assert detail.status_code == 200
    payload = detail.json()
    assert payload["id"] == 1
    assert payload["pn"] == "PN-100"
    assert payload["pin_map"]["1"]["A"] == 1
    assert payload["macro_ids"] == [10]

    state = client.get("/state", headers=_auth())
    assert state.status_code == 200
    state_payload = state.json()
    assert state_payload["ready"] is True
    assert state_payload["last_ready_error"] == ""
    assert isinstance(state_payload["checks"], list)
    assert state_payload["wizard_open"] is False
    assert state_payload["unsaved_changes"] is False
    assert state_payload["host"] == "127.0.0.1"
    assert state_payload["alias_ops_supported"] is True
    assert state_payload["focused_comp_id"] is None


def test_alias_update_happy_path():
    client = _make_client(lambda pn, aliases: BridgeCreateResult(created=False, reason="cancelled"))

    assert _wait_for_ready(client)

    add_resp = client.post(
        "/complexes/1/aliases",
        json={"add": [" alt-2 "]},
        headers=_auth(),
    )
    assert add_resp.status_code == 200
    add_body = add_resp.json()
    assert add_body["updated"] == {"added": ["ALT-2"], "removed": [], "skipped": []}
    assert "ALT-2" in add_body["aliases"]
    add_hash = add_body["source_hash"]

    repeat_resp = client.post(
        "/complexes/1/aliases",
        json={"add": ["alt-2"]},
        headers=_auth(),
    )
    assert repeat_resp.status_code == 200
    repeat_body = repeat_resp.json()
    assert repeat_body["updated"] == {"added": [], "removed": [], "skipped": ["ALT-2"]}
    assert repeat_body["aliases"].count("ALT-2") == 1
    assert repeat_body["source_hash"] == add_hash

    remove_resp = client.post(
        "/complexes/1/aliases",
        json={"remove": ["alt-2"]},
        headers=_auth(),
    )
    assert remove_resp.status_code == 200
    remove_body = remove_resp.json()
    assert remove_body["updated"] == {"added": [], "removed": ["ALT-2"], "skipped": []}
    assert "ALT-2" not in remove_body["aliases"]
    assert remove_body["source_hash"] != add_hash

    final_resp = client.post(
        "/complexes/1/aliases",
        json={"remove": ["ALT-2"]},
        headers=_auth(),
    )
    assert final_resp.status_code == 200
    final_body = final_resp.json()
    assert final_body["updated"] == {"added": [], "removed": [], "skipped": ["ALT-2"]}
    assert final_body["aliases"] == ["ALT-1"]
    assert final_body["source_hash"] == remove_body["source_hash"]


def test_alias_update_conflict():
    dataset = _make_dataset_with_peer()
    client = _make_client(lambda pn, aliases: BridgeCreateResult(created=False, reason="cancelled"), dataset=dataset)

    assert _wait_for_ready(client)
    resp = client.post(
        "/complexes/1/aliases",
        json={"add": ["alt-2"]},
        headers=_auth(),
    )
    assert resp.status_code == 409
    body = resp.json()
    assert body["reason"] == "alias_conflict"
    assert body["conflicts"] == [{"alias": "ALT-2", "existing_id": 2}]


def test_alias_update_requires_auth():
    client = _make_client(lambda pn, aliases: BridgeCreateResult(created=False, reason="cancelled"))

    resp = client.post("/complexes/1/aliases", json={"add": ["ALT-3"]})
    assert resp.status_code == 401


def test_alias_update_missing_complex():
    client = _make_client(lambda pn, aliases: BridgeCreateResult(created=False, reason="cancelled"))

    resp = client.post("/complexes/999/aliases", json={"add": ["ALT-3"]}, headers=_auth())
    assert resp.status_code == 404


def test_open_complex_success():
    dataset = _make_dataset()
    state = {
        "wizard_open": False,
        "unsaved_changes": False,
        "mdb_path": str(ROOT / "tests" / "data" / "dummy.mdb"),
        "focused_comp_id": None,
    }
    focused: dict[str, object] = {}
    modes: list[str] = []

    def focus_handler(comp_id: int, mode: str) -> dict[str, object]:
        modes.append(mode)
        focused["id"] = comp_id
        device = dataset[comp_id]["device"]
        state["focused_comp_id"] = comp_id
        return {"pn": device.name}

    client = _make_client(
        lambda pn, aliases: BridgeCreateResult(created=False, reason="cancelled"),
        state=lambda: state,
        dataset=dataset,
        focus_handler=focus_handler,
    )

    assert _wait_for_ready(client)
    resp = client.post("/complexes/1/open", headers=_auth())
    assert resp.status_code == 200
    assert resp.json() == {"ok": True}
    assert focused["id"] == 1
    assert modes == ["view"]

    state_resp = client.get("/state", headers=_auth())
    assert state_resp.status_code == 200
    assert state_resp.json()["focused_comp_id"] == 1


def test_open_complex_not_found():
    dataset = _make_dataset()
    invoked = {"count": 0}

    def focus_handler(comp_id: int, mode: str) -> dict[str, object]:
        invoked["count"] += 1
        raise KeyError(comp_id)

    client = _make_client(
        lambda pn, aliases: BridgeCreateResult(created=False, reason="cancelled"),
        dataset=dataset,
        focus_handler=focus_handler,
    )
    assert _wait_for_ready(client)
    resp = client.post("/complexes/99/open", headers=_auth())
    assert resp.status_code == 404
    assert invoked["count"] == 0


def test_open_complex_busy_blocks():
    dataset = _make_dataset()
    state = {
        "wizard_open": True,
        "unsaved_changes": True,
        "mdb_path": str(ROOT / "tests" / "data" / "dummy.mdb"),
        "focused_comp_id": None,
    }
    invoked = {"count": 0}

    def focus_handler(comp_id: int, mode: str) -> dict[str, object]:
        invoked["count"] += 1
        return {"pn": dataset[comp_id]["device"].name}

    client = _make_client(
        lambda pn, aliases: BridgeCreateResult(created=False, reason="cancelled"),
        state=lambda: state,
        dataset=dataset,
        focus_handler=focus_handler,
    )

    assert _wait_for_ready(client)
    resp = client.post("/complexes/1/open", headers=_auth())
    assert resp.status_code == 409
    assert resp.json() == {"reason": "busy"}
    assert invoked["count"] == 0


def test_open_complex_edit_mode_sets_wizard_state():
    dataset = _make_dataset()
    state = {
        "wizard_open": False,
        "unsaved_changes": False,
        "mdb_path": str(ROOT / "tests" / "data" / "dummy.mdb"),
        "focused_comp_id": None,
    }
    recorded: dict[str, object] = {"mode": None, "count": 0}

    def focus_handler(comp_id: int, mode: str) -> dict[str, object]:
        recorded["mode"] = mode
        recorded["count"] = recorded.get("count", 0) + 1
        state["focused_comp_id"] = comp_id
        state["wizard_open"] = True
        return {"pn": dataset[comp_id]["device"].name, "wizard_open": True}

    client = _make_client(
        lambda pn, aliases: BridgeCreateResult(created=False, reason="cancelled"),
        state=lambda: state,
        dataset=dataset,
        focus_handler=focus_handler,
    )

    assert _wait_for_ready(client)
    resp = client.post("/complexes/1/open", headers=_auth(), json={"mode": "edit"})
    assert resp.status_code == 200
    assert resp.json() == {"ok": True}
    assert recorded["mode"] == "edit"
    assert recorded["count"] == 1

    state_payload = client.get("/state", headers=_auth()).json()
    assert state_payload["wizard_open"] is True
    assert state_payload["focused_comp_id"] == 1


def test_open_complex_edit_busy_returns_conflict():
    dataset = _make_dataset()
    invocations = {"count": 0, "mode": None}

    def focus_handler(comp_id: int, mode: str) -> dict[str, object]:
        invocations["count"] += 1
        invocations["mode"] = mode
        raise FocusBusyError("busy")

    client = _make_client(
        lambda pn, aliases: BridgeCreateResult(created=False, reason="cancelled"),
        dataset=dataset,
        focus_handler=focus_handler,
        state={"wizard_open": False, "unsaved_changes": False},
    )

    assert _wait_for_ready(client)
    resp = client.post("/complexes/1/open", headers=_auth(), json={"mode": "edit"})
    assert resp.status_code == 409
    assert resp.json() == {"reason": "busy"}
    assert invocations["count"] == 1
    assert invocations["mode"] == "edit"


def test_open_complex_rejects_invalid_mode():
    client = _make_client(
        lambda pn, aliases: BridgeCreateResult(created=False, reason="cancelled"),
        focus_handler=lambda comp_id, mode: {"pn": "PN-100"},
    )
    assert _wait_for_ready(client)
    resp = client.post("/complexes/1/open", headers=_auth(), json={"mode": "launch"})
    assert resp.status_code == 400
    assert resp.json()["detail"] == "invalid_mode"


def test_open_complex_headless():
    client = _make_client(
        lambda pn, aliases: BridgeCreateResult(created=False, reason="cancelled"),
        focus_handler=None,
    )
    assert _wait_for_ready(client)
    resp = client.post("/complexes/1/open", headers=_auth())
    assert resp.status_code == 503
    assert resp.json()["detail"] == "headless"


def test_bridge_health_blocks_until_ready():
    client = _make_client(lambda pn, aliases: BridgeCreateResult(created=False, reason="cancelled"))

    _wait_until(lambda: getattr(client.app.state, "_readiness_task", None) is None)
    client.app.state.ready = False
    client.app.state.last_ready_error = "warming_up"
    warming = client.get("/health", headers=_auth())
    assert warming.status_code == 503
    assert warming.json() == {"ok": False, "reason": "warming_up"}

    client.app.state.ready = True
    client.app.state.last_ready_error = ""
    healthy = client.get("/health", headers=_auth())
    assert healthy.status_code == 200
    assert healthy.json()["ok"] is True


def test_bridge_selftest_success_and_failure(tmp_path):
    handler = lambda pn, aliases: BridgeCreateResult(created=False, reason="cancelled")  # noqa: E731
    client = _make_client(handler)
    ok_resp = client.post("/selftest", headers=_auth())
    assert ok_resp.status_code == 200
    ok_payload = ok_resp.json()
    assert ok_payload["ok"] is True
    assert any(check["name"] == "mdb_connection" for check in ok_payload["checks"])

    missing_path = tmp_path / "missing.mdb"
    failing_client = _make_client(handler, mdb_path=missing_path)
    fail_resp = failing_client.post("/selftest", headers=_auth())
    assert fail_resp.status_code == 503
    fail_payload = fail_resp.json()
    assert fail_payload["ok"] is False
    assert any(not check["ok"] for check in fail_payload["checks"])


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
    payload = resp.json()
    assert payload["id"] == 42
    assert payload["pn"] == "NEW-PN"
    assert payload["aliases"] == ["ALT"]
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
    assert resp.json() == {"reason": "cancelled by user"}


def test_bridge_create_complex_headless_returns_503():
    client = _make_client(None)
    resp = client.post(
        "/complexes",
        headers=_auth() | {"Content-Type": "application/json"},
        json={"pn": "PN", "aliases": []},
    )
    assert resp.status_code == 503
    body = resp.json()
    assert body["detail"] == "wizard unavailable (headless)"


def test_bridge_create_complex_busy_returns_409():
    def handler(pn: str, aliases: list[str] | None) -> BridgeCreateResult:
        return BridgeCreateResult(created=False, reason="wizard busy")

    client = _make_client(handler)
    resp = client.post(
        "/complexes",
        headers=_auth() | {"Content-Type": "application/json"},
        json={"pn": "PN", "aliases": []},
    )
    assert resp.status_code == 409
    assert resp.json() == {"reason": "wizard busy"}
def test_bridge_create_complex_existing_returns_existing():
    calls: list[tuple[str, list[str]]] = []

    def handler(pn: str, aliases: list[str] | None) -> BridgeCreateResult:
        calls.append((pn, aliases or []))
        return BridgeCreateResult(created=True, comp_id=999, db_path="dummy.mdb")

    client = _make_client(handler)
    resp = client.post(
        "/complexes",
        headers=_auth() | {"Content-Type": "application/json"},
        json={"pn": "PN-100", "aliases": ["ALT-1"]},
    )
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["id"] == 1
    assert payload["pn"] == "PN-100"
    assert payload["aliases"] == ["ALT-1"]
    assert calls == []


def test_bridge_shutdown_endpoint_sets_flag():
    triggered = {"value": False}

    def handler(pn: str, aliases: list[str] | None) -> BridgeCreateResult:
        return BridgeCreateResult(created=False, reason="cancelled")

    client = _make_client(handler, state={"wizard_open": False, "unsaved_changes": False})
    client.app.state.trigger_shutdown = lambda: triggered.__setitem__("value", True)

    resp = client.post("/admin/shutdown", headers=_auth())
    assert resp.status_code == 200
    assert resp.json() == {"ok": True}
    assert triggered["value"] is True


def test_bridge_shutdown_blocked_when_unsaved():
    triggered = {"value": False}

    def handler(pn: str, aliases: list[str] | None) -> BridgeCreateResult:
        return BridgeCreateResult(created=False, reason="cancelled")

    client = _make_client(
        handler,
        state=lambda: {"wizard_open": True, "unsaved_changes": True},
    )
    client.app.state.trigger_shutdown = lambda: triggered.__setitem__("value", True)

    resp = client.post("/admin/shutdown", headers=_auth())
    assert resp.status_code == 409
    assert resp.json()["detail"] == "unsaved_changes"
    assert triggered["value"] is False

    forced = client.post("/admin/shutdown", headers=_auth(), params={"force": 1})
    assert forced.status_code == 200
    assert forced.json() == {"ok": True}
    assert triggered["value"] is True


def test_export_mdb_subset_success(tmp_path):
    dataset = _make_dataset_with_peer()
    client = _make_client(
        lambda pn, aliases: BridgeCreateResult(created=False, reason="cancelled"),
        dataset=dataset,
    )
    out_dir = tmp_path / "exports"
    payload = {
        "pns": ["ALT-1", "UNKNOWN-PN"],
        "comp_ids": [2],
        "out_dir": str(out_dir),
        "mdb_name": "subset.mdb",
    }
    resp = client.post("/exports/mdb", headers=_auth(), json=payload)
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["exported_comp_ids"] == [1, 2]
    assert sorted(entry["comp_id"] for entry in body["resolved"]) == [1, 2]
    assert body["missing"] == ["UNKNOWN-PN"]
    export_path = Path(body["export_path"])
    assert export_path.exists()
    exports = dataset.get("__exports__") or []
    assert exports and exports[0]["comp_ids"] == [1, 2]


def test_export_mdb_requires_linked_blocks_when_missing(tmp_path):
    dataset = _make_dataset()
    client = _make_client(
        lambda pn, aliases: BridgeCreateResult(created=False, reason="cancelled"),
        dataset=dataset,
    )
    out_dir = tmp_path / "exports"
    payload = {
        "pns": ["MISSING-PN"],
        "out_dir": str(out_dir),
        "require_linked": True,
    }
    resp = client.post("/exports/mdb", headers=_auth(), json=payload)
    assert resp.status_code == 409
    body = resp.json()
    assert body["reason"] == "unlinked_or_missing"
    assert body["missing"] == ["MISSING-PN"]
    assert dataset.get("__exports__") is None


def test_export_mdb_busy_returns_409(tmp_path):
    dataset = _make_dataset()
    client = _make_client(
        lambda pn, aliases: BridgeCreateResult(created=False, reason="cancelled"),
        dataset=dataset,
        state={"wizard_open": True, "unsaved_changes": True},
    )
    out_dir = tmp_path / "exports"
    payload = {
        "pns": ["PN-100"],
        "out_dir": str(out_dir),
    }
    resp = client.post("/exports/mdb", headers=_auth(), json=payload)
    assert resp.status_code == 409
    assert resp.json()["reason"] == "busy"
    assert dataset.get("__exports__") is None


def test_export_mdb_headless_returns_503(monkeypatch, tmp_path):
    dataset = _make_dataset()

    def handler(pn: str, aliases: list[str] | None) -> BridgeCreateResult:
        return BridgeCreateResult(created=False, reason="cancelled")

    client = _make_client(handler, dataset=dataset)

    def no_export(self, target_path: Path, comp_ids):  # noqa: ANN001 - signature mirrors real method
        raise NotImplementedError("headless")

    monkeypatch.setattr(FakeMDB, "save_subset_to_mdb", no_export)

    out_dir = tmp_path / "exports"
    payload = {
        "comp_ids": [1],
        "out_dir": str(out_dir),
    }
    resp = client.post("/exports/mdb", headers=_auth(), json=payload)
    assert resp.status_code == 503
    assert resp.json()["detail"] == "headless"
    assert dataset.get("__exports__") is None


def test_build_server_cmd_frozen(monkeypatch):
    db_path = ROOT / "tests" / "data" / "dummy.mdb"
    cfg = SimpleNamespace(database=SimpleNamespace(mdb_path=db_path))
    bridge_cfg = SimpleNamespace(host="127.0.0.1", port=8765, auth_token="XYZ", base_url="http://127.0.0.1:8765")
    responses = iter(
        [
            ("not_running", None, "127.0.0.1"),
            ("running", {"ok": True}, "127.0.0.1"),
        ]
    )
    monkeypatch.setattr(run_module, "_probe_health", lambda host, port, token, timeout=1.0: next(responses))
    recorded: dict[str, object] = {}

    class FakeProcess:
        def poll(self):
            return None

        def wait(self, timeout=None):
            return 0

        def terminate(self):
            recorded["terminated"] = True

        def kill(self):
            recorded["killed"] = True

    def fake_popen(cmd, **kwargs):
        recorded["cmd"] = cmd
        recorded["env"] = kwargs.get("env")
        return FakeProcess()

    monkeypatch.setattr(run_module.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(run_module.time, "sleep", lambda _: None)
    monkeypatch.setattr(run_module.sys, "frozen", True, raising=False)
    monkeypatch.setattr(run_module.sys, "executable", "ComplexEditor.exe", raising=False)
    monkeypatch.setenv("CE_CONFIG", "bridge.yml")

    assert run_module._ensure_bridge(cfg, bridge_cfg) == 0
    assert recorded["cmd"] == [
        "ComplexEditor.exe",
        "--run-bridge-server",
        "--host",
        "127.0.0.1",
        "--port",
        "8765",
        "--token",
        "XYZ",
        "--config",
        "bridge.yml",
    ]


def test_build_server_cmd_dev(monkeypatch):
    db_path = ROOT / "tests" / "data" / "dummy.mdb"
    cfg = SimpleNamespace(database=SimpleNamespace(mdb_path=db_path))
    bridge_cfg = SimpleNamespace(host="localhost", port=9000, auth_token="", base_url="http://localhost:9000")
    responses = iter(
        [
            ("not_running", None, "localhost"),
            ("running", {"ok": True}, "localhost"),
        ]
    )
    monkeypatch.setattr(run_module, "_probe_health", lambda host, port, token, timeout=1.0: next(responses))
    recorded: dict[str, object] = {}

    class FakeProcess:
        def poll(self):
            return None

        def wait(self, timeout=None):
            return 0

        def terminate(self):
            recorded["terminated"] = True

        def kill(self):
            recorded["killed"] = True

    def fake_popen(cmd, **kwargs):
        recorded["cmd"] = cmd
        recorded["env"] = kwargs.get("env")
        return FakeProcess()

    monkeypatch.setattr(run_module.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(run_module.time, "sleep", lambda _: None)
    monkeypatch.setattr(run_module.sys, "frozen", False, raising=False)
    monkeypatch.setattr(run_module.sys, "executable", "/usr/bin/python", raising=False)
    monkeypatch.delenv("CE_CONFIG", raising=False)

    assert run_module._ensure_bridge(cfg, bridge_cfg) == 0
    assert recorded["cmd"] == [
        "/usr/bin/python",
        "-m",
        "ce_bridge_service.run",
        "--host",
        "localhost",
        "--port",
        "9000",
    ]
