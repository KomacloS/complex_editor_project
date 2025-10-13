import os
import sys
import types
from pathlib import Path

from fastapi.testclient import TestClient
from PyQt6 import QtWidgets

sys.modules.setdefault("pyodbc", types.ModuleType("pyodbc"))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src")))

from complex_editor.core.app_context import AppContext  # noqa: E402
from complex_editor.ui.main_window import MainWindow  # noqa: E402
import complex_editor.db.schema_introspect as schema_introspect  # noqa: E402
from ce_bridge_service.app import create_app  # noqa: E402
from complex_editor.domain import ComplexDevice, MacroInstance  # noqa: E402


class DummyConn:
    def cursor(self):  # pragma: no cover - trivial stub
        return object()


class DummyDB:
    def __init__(self):
        self._conn = DummyConn()


def _prepare_window(tmp_path: Path, qtbot, monkeypatch) -> tuple[MainWindow, AppContext]:
    ctx = AppContext()
    ctx.config.database.mdb_path = tmp_path / "bridge.mdb"

    dummy_db = DummyDB()

    def fake_open(self, target_path, create_if_missing=True):  # pragma: no cover - simple stub
        self.db = dummy_db
        return dummy_db

    monkeypatch.setattr(AppContext, "open_main_db", fake_open)
    monkeypatch.setattr(schema_introspect, "discover_macro_map", lambda _c: {})

    win = MainWindow(mdb_path=ctx.config.database.mdb_path, ctx=ctx)
    qtbot.addWidget(win)
    return win, ctx


def test_bridge_wizard_success_returns_201(tmp_path, qtbot, monkeypatch):
    win, ctx = _prepare_window(tmp_path, qtbot, monkeypatch)

    captured: dict[str, object] = {}

    class FakeWizard:
        def __init__(self, pn: str, aliases: list[str]):
            self._pn = pn
            self._aliases = aliases
            self.finished = types.SimpleNamespace(connect=lambda cb: None)

        def setMinimumSize(self, w: int, h: int) -> None:
            captured["size"] = (w, h)

        def setWindowTitle(self, title: str) -> None:  # pragma: no cover - defensive
            captured["title"] = title

        def show(self) -> None:
            captured["shown"] = True

        def raise_(self) -> None:
            captured["raised"] = True

        def activateWindow(self) -> None:
            captured["activated"] = True

        def exec(self) -> QtWidgets.QDialog.DialogCode:
            return QtWidgets.QDialog.DialogCode.Accepted

        def to_complex_device(self) -> ComplexDevice:
            dev = ComplexDevice(0, [], MacroInstance("", {}))
            dev.pn = self._pn
            dev.aliases = list(self._aliases)
            dev.pin_count = 0
            dev.subcomponents = []
            return dev

        def deleteLater(self) -> None:  # pragma: no cover - defensive
            captured["deleted"] = True

    def fake_create(self, macro_map, pn, aliases):
        captured["pn"] = pn
        captured["aliases"] = list(aliases or [])
        return FakeWizard(pn, list(aliases or []))

    monkeypatch.setattr(MainWindow, "_create_prefilled_wizard", fake_create)
    monkeypatch.setattr(MainWindow, "_persist_editor_device", lambda self, dev, comp_id=None: 123)

    app = create_app(
        get_mdb_path=lambda: ctx.current_db_path(),
        auth_token=None,
        wizard_handler=win._bridge_wizard_handler,
        state_provider=ctx.bridge_state,
        bridge_host="127.0.0.1",
        bridge_port=8765,
    )

    with TestClient(app) as client:
        resp = client.post("/complexes", json={"pn": "NEW-123", "aliases": ["ALT"]})
    win.close()

    assert resp.status_code == 201
    payload = resp.json()
    assert payload["id"] == 123
    assert captured["pn"] == "NEW-123"
    assert captured["aliases"] == ["ALT"]
    assert captured["size"] == (1000, 720)
    assert captured.get("shown") is True
    assert captured.get("raised") is True
    assert ctx.wizard_open is False
    assert ctx.unsaved_changes is False


def test_bridge_wizard_cancel_returns_409(tmp_path, qtbot, monkeypatch):
    win, ctx = _prepare_window(tmp_path, qtbot, monkeypatch)

    class CancelWizard:
        def __init__(self):
            self.finished = types.SimpleNamespace(connect=lambda cb: None)

        def setMinimumSize(self, *_):
            pass

        def show(self):
            pass

        def raise_(self):
            pass

        def activateWindow(self):
            pass

        def exec(self):
            return QtWidgets.QDialog.DialogCode.Rejected

        def deleteLater(self):  # pragma: no cover - defensive
            pass

    monkeypatch.setattr(MainWindow, "_create_prefilled_wizard", lambda *a, **k: CancelWizard())
    monkeypatch.setattr(MainWindow, "_persist_editor_device", lambda self, dev, comp_id=None: 999)

    app = create_app(
        get_mdb_path=lambda: ctx.current_db_path(),
        auth_token=None,
        wizard_handler=win._bridge_wizard_handler,
        state_provider=ctx.bridge_state,
        bridge_host="127.0.0.1",
        bridge_port=8765,
    )

    with TestClient(app) as client:
        resp = client.post("/complexes", json={"pn": "NEW-123"})
    win.close()

    assert resp.status_code == 409
    assert ctx.wizard_open is False
    assert ctx.unsaved_changes is False
