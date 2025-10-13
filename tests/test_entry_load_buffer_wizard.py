import json
import os
import sys
import types
from pathlib import Path

import pytest
from PyQt6 import QtWidgets

sys.modules.setdefault("pyodbc", types.ModuleType("pyodbc"))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src")))

import complex_editor.__main__ as entry  # noqa: E402


@pytest.fixture
def restore_env():
    original = os.environ.get("QT_QPA_PLATFORM")
    yield
    if original is None:
        os.environ.pop("QT_QPA_PLATFORM", None)
    else:
        os.environ["QT_QPA_PLATFORM"] = original


class DummySignal:
    def __init__(self):
        self._callback = None

    def connect(self, callback):
        self._callback = callback

    def emit(self, value):  # pragma: no cover - defensive
        if self._callback:
            self._callback(value)


class DummyWizard:
    def __init__(self):
        self.finished = DummySignal()
        self.calls = {}
        self._title = ""

    def setWindowTitle(self, title: str) -> None:
        self.calls["title"] = title
        self._title = title

    def setMinimumSize(self, w: int, h: int) -> None:
        self.calls["size"] = (w, h)

    def show(self) -> None:
        self.calls["shown"] = True

    def raise_(self) -> None:
        self.calls["raised"] = True

    def activateWindow(self) -> None:
        self.calls["activated"] = True

    def exec(self) -> int:
        self.calls["exec"] = True
        return 0


def test_load_buffer_wizard_focus(tmp_path, monkeypatch, restore_env):
    buffer_path = tmp_path / "prefill.json"
    payload = {"Complex": {"Name": "PN-900"}, "SubComponents": []}
    buffer_path.write_text(json.dumps(payload), encoding="utf-8")

    ctx_holder = {}

    class DummyCtx:
        def __init__(self):
            ctx_holder["instance"] = self
            self.opened = False
            self.closed = None

        def wizard_opened(self):
            self.opened = True

        def wizard_closed(self, *, saved, had_changes):
            self.closed = (saved, had_changes)

    monkeypatch.setattr(entry, "AppContext", DummyCtx)

    wizard_instance = DummyWizard()

    def fake_from_prefill(prefill, parent=None):
        wizard_instance.calls.clear()
        wizard_instance.finished = DummySignal()
        wizard_instance.calls["prefill_name"] = getattr(prefill, "complex_name", "")
        return wizard_instance

    monkeypatch.setattr(entry, "NewComplexWizard", types.SimpleNamespace(from_wizard_prefill=fake_from_prefill))

    class DummyApp:
        def __init__(self, *_, **__):
            self.processed = False

        def processEvents(self) -> None:
            self.processed = True

        def exec(self) -> int:
            if wizard_instance.finished._callback:
                wizard_instance.finished._callback(QtWidgets.QDialog.DialogCode.Accepted)
            return 0

    monkeypatch.setattr(entry, "QtWidgets", types.SimpleNamespace(QApplication=lambda *_: DummyApp(), QDialog=QtWidgets.QDialog))

    with pytest.raises(SystemExit) as exc:
        entry.main(["--load-buffer", str(buffer_path)])
    assert exc.value.code == 0

    calls = wizard_instance.calls
    assert calls["prefill_name"] == "PN-900"
    assert calls["size"] == (1000, 720)
    assert calls.get("shown") is True
    assert calls.get("raised") is True
    assert calls.get("activated") is True
    assert ctx_holder["instance"].opened is True
    assert ctx_holder["instance"].closed == (True, True)
    assert os.environ.get("QT_QPA_PLATFORM") != "offscreen"
